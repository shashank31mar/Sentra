"""WS-G backend-lane tenancy-route tests (package-root). Covers:

* G0.2 (D14) — public `resolve_org(org)→{tenant_id}`: id-only, friendly-404 miss,
  fail-closed 5XX on internal error.
* G0.4 — per-tenant rollup fields present on GET /v1/platform/tenants + computed
  in a SINGLE batched call (NOT N per-tenant scans — the overview-latency footgun).
* G0.5 — platform registry paging + sort + filter.
* M-G3.13 backend — verdict/quarantine derive the operator from ctx.sub and do NOT
  require a client `operator_id`.
* B2.1 — the D3 role-model generator emits every require_role/require_platform
  route + a RANK matching deps._ROLE_ORDER.

Moto-safe: fake creds, mocked AWS.
"""
from __future__ import annotations

import asyncio

import boto3
import pytest
from fastapi import HTTPException
from moto import mock_aws

from app.config import settings
from app.api.deps import OperatorContext
from app.services.decisions_service import DecisionsService
from app.utils.session_manager import SessionManager
from tests.mt_helpers import run, create_mt_tables


class _Req:
    def __init__(self, headers=None):
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.client = type("C", (), {"host": "10.0.0.9"})()


@pytest.fixture
def mt_env(monkeypatch):
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SECURITY_TOKEN", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(k, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", settings.aws_region)
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name=settings.aws_region)
        create_mt_tables(ddb)
        import app.utils.clients as clients
        import app.services.tenant_service as ts
        import app.api.deps as deps
        import app.api.tenancy_routes as tr
        clients._registry = None
        ts._tenant_store = None
        ts._member_store = None
        deps._mode_cache.clear()
        tr._resolve_org_hits.clear()  # reset the per-IP throttle between tests
        tr._resolve_org_global.update(window_start=0.0, count=0)  # reset global brake too
        yield ddb


def _platform_ctx():
    return OperatorContext(sub="ops-1", tenant_id="_platform", role="viewer",
                           email="ops@aegion.ai", is_platform=True)


# --------------------------------------------------------------------------- #
# G0.2 — public resolve_org
# --------------------------------------------------------------------------- #
def test_resolve_org_returns_only_tenant_id(mt_env):
    from app.api.tenancy_routes import resolve_org
    from app.services.tenant_service import get_tenant_store

    t = get_tenant_store().create(display_name="Acme Corp")
    out = run(resolve_org(org="acme corp", request=_Req()))  # case/space-insensitive
    assert out == {"tenant_id": t.tenant_id}, "must return ONLY the tenant_id, nothing else"
    assert set(out.keys()) == {"tenant_id"}, "zero tenant data beyond the id (no counts/plan/members)"


def test_resolve_org_miss_friendly_not_found(mt_env):
    from app.api.tenancy_routes import resolve_org

    with pytest.raises(HTTPException) as ei:
        run(resolve_org(org="does-not-exist", request=_Req()))
    assert ei.value.status_code == 404
    assert "not found" in str(ei.value.detail).lower()


def test_resolve_org_internal_error_fails_closed_5xx(mt_env, monkeypatch):
    """A registry fault must fail CLOSED with an honest 5XX — never a fake-200
    wrapping an error (engineering error-contract rule)."""
    from app.api.tenancy_routes import resolve_org
    from app.services.tenant_service import get_tenant_store

    def _boom(_org):
        raise RuntimeError("dynamo down")
    monkeypatch.setattr(get_tenant_store(), "resolve_org_to_tenant_id", _boom)

    with pytest.raises(HTTPException) as ei:
        run(resolve_org(org="acme", request=_Req()))
    assert 500 <= ei.value.status_code < 600, "internal fault must be a 5XX, not a 200/404"


def test_resolve_org_burst_throttled(mt_env):
    """A per-IP burst trips the throttle (429) — an unauth endpoint can't be swept."""
    from app.api import tenancy_routes as tr
    from app.api.tenancy_routes import resolve_org

    hit_429 = False
    for _ in range(tr._RESOLVE_ORG_BURST + 5):
        try:
            run(resolve_org(org="nope", request=_Req()))
        except HTTPException as exc:
            if exc.status_code == 429:
                hit_429 = True
                break
    assert hit_429, "burst beyond the per-IP ceiling must return 429"


def test_resolve_org_xff_rotation_caught_by_global_brake(mt_env, monkeypatch):
    """FIX-B gap: X-Forwarded-For is client-controlled, so per-IP alone is bypassable
    — an attacker rotating XFF gets a fresh per-IP bucket per fake value. The
    NON-spoofable global window counter must still trip 429. Shrink the global ceiling
    so the test drives it deterministically; each request uses a UNIQUE spoofed XFF so
    the per-IP brake NEVER fires (proving the global brake is what caught it)."""
    from app.api import tenancy_routes as tr
    from app.api.tenancy_routes import resolve_org

    monkeypatch.setattr(tr, "_RESOLVE_ORG_GLOBAL_BURST", 5)
    tr._resolve_org_global.update(window_start=0.0, count=0)
    tr._resolve_org_hits.clear()

    hit_429 = False
    for i in range(tr._RESOLVE_ORG_GLOBAL_BURST + 3):
        req = _Req(headers={"x-forwarded-for": f"9.9.9.{i}"})  # unique spoofed IP each call
        try:
            run(resolve_org(org="nope", request=req))
        except HTTPException as exc:
            if exc.status_code == 429:
                hit_429 = True
                break
    assert hit_429, (
        "rotating X-Forwarded-For must NOT grant unlimited requests — the global "
        "(non-spoofable) sweep brake must trip 429 even when every per-IP key is fresh"
    )
    # And no single per-IP bucket ever reached the per-IP ceiling (each key saw 1 hit),
    # so it was demonstrably the global brake, not the per-IP one.
    assert all(count <= tr._RESOLVE_ORG_BURST for (_ws, count) in tr._resolve_org_hits.values())


def test_resolve_org_per_ip_table_is_bounded(mt_env, monkeypatch):
    """FIX-B gap: `_resolve_org_hits` must not grow unboundedly on a pre-auth endpoint
    (an XFF-rotation flood would otherwise accumulate one entry per fake IP forever).
    Once the hard cap is reached, a not-yet-tracked IP is throttled (429) rather than
    inserted — so the dict size is bounded by _RESOLVE_ORG_MAX_TRACKED_IPS."""
    from app.api import tenancy_routes as tr
    from app.api.tenancy_routes import resolve_org

    monkeypatch.setattr(tr, "_RESOLVE_ORG_MAX_TRACKED_IPS", 3)
    monkeypatch.setattr(tr, "_RESOLVE_ORG_GLOBAL_BURST", 10_000)  # isolate the per-IP cap
    tr._resolve_org_hits.clear()
    tr._resolve_org_global.update(window_start=0.0, count=0)

    seen_429 = False
    for i in range(tr._RESOLVE_ORG_MAX_TRACKED_IPS + 5):
        req = _Req(headers={"x-forwarded-for": f"7.7.7.{i}"})
        try:
            run(resolve_org(org="nope", request=req))
        except HTTPException as exc:
            if exc.status_code == 429:
                seen_429 = True
    assert seen_429, "a new IP beyond the hard cap must be throttled, not tracked"
    assert len(tr._resolve_org_hits) <= tr._RESOLVE_ORG_MAX_TRACKED_IPS, (
        f"per-IP table must stay <= cap; grew to {len(tr._resolve_org_hits)}"
    )


# --------------------------------------------------------------------------- #
# G0.4 / G0.5 — platform rollup + paging/sort/filter
# --------------------------------------------------------------------------- #
def _seed_tenants(n):
    from app.services.tenant_service import get_tenant_store
    store = get_tenant_store()
    return [store.create(display_name=f"Tenant {i}") for i in range(n)]


def test_platform_list_tenants_includes_rollup_fields(mt_env, monkeypatch):
    from app.api import tenancy_routes as tr

    tenants = _seed_tenants(2)
    # Stub the batched rollups so we assert field WIRING, not DDB aggregation.
    sr = {tenants[0].tenant_id: {"agents": 3, "quarantined": 1, "trust": 88.0}}
    dr = {tenants[0].tenant_id: {"decisions_24h": 100, "blocks_24h": 7, "deny_rate": 0.07}}
    monkeypatch.setattr(SessionManager, "fleet_rollup_by_tenant",
                        _async_ret(sr), raising=False)
    monkeypatch.setattr(DecisionsService, "fleet_decisions_rollup_by_tenant",
                        lambda self: dr, raising=False)

    out = run(tr.platform_list_tenants(ctx=_platform_ctx()))
    rows = {r["tenant_id"]: r for r in out["tenants"]}
    r0 = rows[tenants[0].tenant_id]
    for f in ("blocks_24h", "deny_rate", "trust", "agents", "quarantined", "decisions_24h"):
        assert f in r0, f"row must carry rollup field {f}"
    assert r0["agents"] == 3 and r0["quarantined"] == 1 and r0["trust"] == 88.0
    assert r0["decisions_24h"] == 100 and r0["blocks_24h"] == 7 and r0["deny_rate"] == 0.07
    # A tenant with no traffic reads honest zeros/None, never fabricated.
    r1 = rows[tenants[1].tenant_id]
    assert r1["blocks_24h"] == 0 and r1["decisions_24h"] == 0 and r1["trust"] is None


def test_platform_rollup_single_batched_call(mt_env, monkeypatch):
    """The rollup MUST be one batched call per source, NOT N per-tenant scans
    (the overview-latency O(N) incident this deliberately avoids)."""
    from app.api import tenancy_routes as tr

    _seed_tenants(5)  # 5 tenants — a per-tenant fan-out would call 5x.
    calls = {"session": 0, "decisions": 0}

    async def _session(self):
        calls["session"] += 1
        return {}

    def _decisions(self):
        calls["decisions"] += 1
        return {}

    monkeypatch.setattr(SessionManager, "fleet_rollup_by_tenant", _session, raising=False)
    monkeypatch.setattr(DecisionsService, "fleet_decisions_rollup_by_tenant", _decisions, raising=False)

    run(tr.platform_list_tenants(ctx=_platform_ctx()))
    assert calls["session"] == 1, f"session rollup must be ONE batched call, got {calls['session']}"
    assert calls["decisions"] == 1, f"decisions rollup must be ONE batched call, got {calls['decisions']}"


def test_platform_list_tenants_paginates(mt_env, monkeypatch):
    from app.api import tenancy_routes as tr
    _seed_tenants(5)
    monkeypatch.setattr(SessionManager, "fleet_rollup_by_tenant", _async_ret({}), raising=False)
    monkeypatch.setattr(DecisionsService, "fleet_decisions_rollup_by_tenant", lambda self: {}, raising=False)

    page1 = run(tr.platform_list_tenants(limit=2, ctx=_platform_ctx()))
    assert page1["count"] == 5
    assert len(page1["tenants"]) == 2
    assert page1["cursor"], "a cursor must be issued when more rows remain"
    page2 = run(tr.platform_list_tenants(limit=2, cursor=page1["cursor"], ctx=_platform_ctx()))
    # No overlap across pages.
    ids1 = {r["tenant_id"] for r in page1["tenants"]}
    ids2 = {r["tenant_id"] for r in page2["tenants"]}
    assert ids1.isdisjoint(ids2), "cursor pages must not overlap"


def test_platform_list_tenants_sort_filter(mt_env, monkeypatch):
    from app.api import tenancy_routes as tr
    from app.services.tenant_service import get_tenant_store
    store = get_tenant_store()
    a = store.create(display_name="Alpha")
    b = store.create(display_name="Bravo")
    store.create(display_name="Zeta")
    monkeypatch.setattr(SessionManager, "fleet_rollup_by_tenant", _async_ret({}), raising=False)
    monkeypatch.setattr(DecisionsService, "fleet_decisions_rollup_by_tenant", lambda self: {}, raising=False)

    # filter by display name substring
    filtered = run(tr.platform_list_tenants(filter="alph", ctx=_platform_ctx()))
    assert {r["display_name"] for r in filtered["tenants"]} == {"Alpha"}

    # sort ascending by display_name
    sorted_rows = run(tr.platform_list_tenants(sort="display_name", ctx=_platform_ctx()))
    names = [r["display_name"] for r in sorted_rows["tenants"]]
    assert names == sorted(names), "display_name sort must be ascending"


def _async_ret(value):
    async def _f(self):
        return value
    return _f


# --------------------------------------------------------------------------- #
# B2.1 — D3 role-model generator completeness + rank
# --------------------------------------------------------------------------- #
def test_role_model_generator_covers_all_gated_routes():
    from app.main import app
    from app.api import role_model
    from app.api.deps import _ROLE_ORDER

    model = role_model.build_role_model(app)

    # RANK matches the server _ROLE_ORDER exactly.
    assert model["rank"] == list(_ROLE_ORDER)
    assert model["minRole"] == {r: i for i, r in enumerate(_ROLE_ORDER)}

    # COMPLETENESS: every route in the live app carrying require_role/require_platform
    # appears in the emitted routes[] (a missed gated route = a parity hole).
    emitted = {(r["path"], r["method"]) for r in model["routes"]}
    for route in app.routes:
        dep = getattr(route, "dependant", None)
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if dep is None or not path or not methods or not str(path).startswith("/v1"):
            continue
        descriptor = role_model._classify_route(dep)
        if descriptor is None:
            continue
        for m in (methods - {"HEAD", "OPTIONS"}):
            assert (path, m) in emitted, f"gated route missing from role-model: {m} {path}"

    # Known anchors carry the RIGHT floor.
    by_key = {(r["path"], r["method"]): r for r in model["routes"]}
    assert by_key[("/v1/policies/{policy_id}", "DELETE")]["min_role"] == "admin"
    assert by_key[("/v1/decisions/{decision_id}/verdict", "POST")]["min_role"] == "editor"
    # require_platform routes carry platform:true, NOT a tenant min_role.
    sigma = by_key[("/v1/sigma-rules/{rule_id}", "PATCH")]
    assert sigma.get("platform") is True and "min_role" not in sigma


def test_role_model_fixtures_written_and_valid(tmp_path, monkeypatch):
    """`emit()` writes a good + a deliberately-broken fixture; the bad one differs
    (so the frontend negative parity test can catch it)."""
    import json
    from app.main import app
    from app.api import role_model

    good = tmp_path / "role-model.json"
    bad = tmp_path / "role-model.bad.json"
    monkeypatch.setattr(role_model, "FIXTURE_PATH", good)
    monkeypatch.setattr(role_model, "BAD_FIXTURE_PATH", bad)
    role_model.emit(app)

    good_model = json.loads(good.read_text())
    bad_model = json.loads(bad.read_text())
    assert good_model["routes"] and good_model["rank"]
    assert good_model != bad_model, "the negative fixture MUST differ from the good one"


def test_committed_role_model_fixture_matches_live_app():
    """The COMMITTED web/console/src/lib/__fixtures__/role-model.json must match a
    fresh generation from the live app — a stale fixture is a parity hole (the
    frontend G2.9 test reads the committed file). Fails if someone changes a
    require_role floor without re-running the generator."""
    import json
    from app.main import app
    from app.api import role_model

    if not role_model.FIXTURE_PATH.exists():
        # The generator must have been run (this lane owns emitting it).
        raise AssertionError(f"role-model.json not emitted at {role_model.FIXTURE_PATH}")
    committed = json.loads(role_model.FIXTURE_PATH.read_text())
    fresh = role_model.build_role_model(app)
    assert committed == fresh, (
        "committed role-model.json is stale vs the live app — re-run "
        "`python -m app.api.role_model` and commit the result"
    )


# --------------------------------------------------------------------------- #
# G0.4 — the batched DDB rollups actually group by tenant (moto-backed). These
# exercise the real scan/group logic the platform-list route depends on (the unit
# tests above stub the rollups to prove field WIRING; these prove the AGGREGATION).
# --------------------------------------------------------------------------- #
def _create_session_table(ddb):
    ddb.create_table(
        TableName=settings.dynamodb_session_table,
        KeySchema=[{"AttributeName": "session_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "session_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    return ddb.Table(settings.dynamodb_session_table)


def test_session_fleet_rollup_groups_by_tenant(mt_env):
    tbl = _create_session_table(mt_env)
    # t_a: 2 agents (one quarantined session), t_b: 1 agent.
    tbl.put_item(Item={"session_id": "s1", "tenant_id": "t_a", "agent_id": "t_a-1",
                       "trust_score": 90, "quarantine_status": "active"})
    tbl.put_item(Item={"session_id": "s2", "tenant_id": "t_a", "agent_id": "t_a-2",
                       "trust_score": 20, "quarantine_status": "quarantined"})
    tbl.put_item(Item={"session_id": "s3", "tenant_id": "t_b", "agent_id": "t_b-1",
                       "trust_score": 80, "quarantine_status": "active"})

    rollup = run(SessionManager().fleet_rollup_by_tenant())
    assert rollup["t_a"]["agents"] == 2
    assert rollup["t_a"]["quarantined"] == 1
    assert rollup["t_b"]["agents"] == 1
    assert rollup["t_b"]["quarantined"] == 0
    # trust = mean per-agent avg; t_a = mean(90, 20) = 55.
    assert rollup["t_a"]["trust"] == 55.0


def test_decisions_fleet_rollup_matches_per_tenant_sum(mt_env):
    """G0.4 integ-style: the batched decisions rollup's blocks/deny_rate for a
    tenant equals the per-request sum for that tenant (deny-overrides grouping)."""
    import time
    from app.services.decisions_service import DecisionsService
    sig_tbl = settings.dynamodb_validation_signals_table

    mt_env.create_table(
        TableName=sig_tbl,
        KeySchema=[{"AttributeName": "session_id", "KeyType": "HASH"},
                   {"AttributeName": "sk", "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": "session_id", "AttributeType": "S"},
                              {"AttributeName": "sk", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    t = mt_env.Table(sig_tbl)
    now_ms = int(time.time() * 1000)

    def put(tenant, sid, rid, decision, source):
        t.put_item(Item={"session_id": sid, "sk": f"{rid}#{source}", "tenant_id": tenant,
                         "request_id": rid, "decision": decision, "source": source,
                         "timestamp_ms": now_ms})

    # t_a: req-1 has a DENY signal (a block), req-2 all ALLOW → 2 decisions, 1 block.
    put("t_a", "sA", "req-1", "ALLOW", "sentra.trust")
    put("t_a", "sA", "req-1", "DENY", "sentra.sigma")
    put("t_a", "sA", "req-2", "ALLOW", "sentra.trust")
    # t_b: one ALLOW decision, zero blocks.
    put("t_b", "sB", "req-9", "ALLOW", "sentra.trust")

    rollup = DecisionsService().fleet_decisions_rollup_by_tenant()
    assert rollup["t_a"]["decisions_24h"] == 2
    assert rollup["t_a"]["blocks_24h"] == 1
    assert rollup["t_a"]["deny_rate"] == 0.5
    assert rollup["t_b"]["decisions_24h"] == 1
    assert rollup["t_b"]["blocks_24h"] == 0
    assert rollup["t_b"]["deny_rate"] == 0.0
