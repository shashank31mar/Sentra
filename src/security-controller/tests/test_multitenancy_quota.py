"""Quota enforcement + platform-admin gating (LLD-26 WS-E E2/E3)."""
from __future__ import annotations

import boto3
import pytest
from fastapi import HTTPException
from moto import mock_aws

from app.config import settings
from tests.mt_helpers import create_mt_tables, run


@pytest.fixture
def mt_env(monkeypatch):
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SECURITY_TOKEN", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(k, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", settings.aws_region)
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name=settings.aws_region)
        create_mt_tables(ddb)
        _create_quota_table(ddb)
        import app.utils.clients as clients
        import app.services.tenant_service as ts
        import app.services.quota_service as qs
        clients._registry = None
        ts._tenant_store = None
        ts._member_store = None
        qs._counter = None
        yield ddb


def _create_quota_table(ddb):
    ddb.create_table(
        TableName=settings.dynamodb_quota_counters_table,
        KeySchema=[{"AttributeName": "tenant_id", "KeyType": "HASH"},
                   {"AttributeName": "counter_key", "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": "tenant_id", "AttributeType": "S"},
                              {"AttributeName": "counter_key", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )


# --------------------------------------------------------------------------- #
# E2a — max_agents at import
# --------------------------------------------------------------------------- #
def test_max_agents_enforced(mt_env):
    from app.services.quota_service import QuotaExceeded, check_agent_quota
    from app.services.tenant_service import get_tenant_store

    get_tenant_store().create(display_name="Capped", tenant_id="t_cap",
                              quota={"max_agents": 3, "max_validate_rps": 50})
    # Under cap: fine.
    check_agent_quota(current_count=2, adding=1, tenant_id="t_cap")
    # Over cap: rejected.
    with pytest.raises(QuotaExceeded) as exc:
        check_agent_quota(current_count=3, adding=1, tenant_id="t_cap")
    assert exc.value.kind == "max_agents" and exc.value.limit == 3


def test_max_agents_noop_without_tenant_row(mt_env):
    from app.services.quota_service import check_agent_quota

    # No registry row (e.g. `default` pre-identity) → no quota applies (no regression).
    check_agent_quota(current_count=9999, adding=1, tenant_id="default")


# --------------------------------------------------------------------------- #
# E2b — RPS counter: off by default, fail-open
# --------------------------------------------------------------------------- #
def test_rps_disabled_by_default(mt_env, monkeypatch):
    from app.services.quota_service import check_validate_rps

    monkeypatch.setattr(settings, "quota_enforcement_enabled", False)
    # Flag off → always allow, zero hot-path cost.
    assert check_validate_rps("t_cap") is True


def test_rps_counter_allows_under_limit_and_blocks_over(mt_env, monkeypatch):
    from app.services.quota_service import get_quota_counter

    counter = get_quota_counter()
    # Two hits under a limit of 5 → allowed.
    assert counter.allow("t_cap", max_rps=5) is True
    assert counter.allow("t_cap", max_rps=5) is True
    # Exhaust the window: many hits over a limit of 1 → eventually blocks.
    blocked = any(not counter.allow("t_burst", max_rps=1) for _ in range(5))
    assert blocked


def test_rps_fails_open_on_counter_error(monkeypatch):
    # No moto table at all → counter writes raise → fail OPEN (allow).
    import app.services.quota_service as qs
    qs._counter = None
    monkeypatch.setenv("AWS_DEFAULT_REGION", settings.aws_region)
    with mock_aws():
        import app.utils.clients as clients
        clients._registry = None
        # Table intentionally absent → ClientError → allow.
        assert qs.get_quota_counter().allow("t_x", max_rps=1) is True


# --------------------------------------------------------------------------- #
# E3 — platform gating
# --------------------------------------------------------------------------- #
def test_require_platform_blocks_non_platform(mt_env):
    import app.api.deps as deps

    async def scenario():
        deps._alb_claims_override = lambda req: {"sub": "op_cust", "email": "c@acme.io"}
        from app.services.tenant_service import get_member_store
        get_member_store().add("op_cust", "t_cap", role="owner", is_primary=True)

        class Req:
            headers = {}
        # A normal tenant operator (no _platform membership) → 403.
        with pytest.raises(HTTPException) as exc:
            await deps.require_platform(Req())
        assert exc.value.status_code == 403
        deps._alb_claims_override = None

    run(scenario())


def test_require_platform_allows_platform_member(mt_env):
    import app.api.deps as deps
    from app.utils import tenancy

    async def scenario():
        deps._alb_claims_override = lambda req: {"sub": "op_staff", "email": "s@sentra.io"}
        from app.services.tenant_service import get_member_store
        members = get_member_store()
        members.add("op_staff", tenancy.PLATFORM_TENANT, role="admin", is_primary=False)
        members.add("op_staff", "t_cap", role="admin", is_primary=True)

        class Req:
            headers = {}
        ctx = await deps.require_platform(Req())
        assert ctx.is_platform is True
        deps._alb_claims_override = None

    run(scenario())


# --------------------------------------------------------------------------- #
# E3 — cross-tenant read consent gate + immutable audit
# --------------------------------------------------------------------------- #
def _platform_ctx(sub="op_staff"):
    from app.api.deps import OperatorContext
    return OperatorContext(sub=sub, tenant_id="_platform", role="admin", is_platform=True)


def _audit_rows(ddb, target_tenant):
    table = ddb.Table(settings.dynamodb_platform_audit_table)
    return table.query(
        KeyConditionExpression="tenant_id = :t",
        ExpressionAttributeValues={":t": target_tenant},
    ).get("Items", [])


def test_platform_per_tenant_read_denied_without_consent(mt_env, monkeypatch):
    """With enforcement ON, a per-tenant platform read DENIES (403) when the tenant
    hasn't consented, and the DENY is itself written to the immutable audit ledger
    (fail-secure: the data fetch never runs)."""
    from app.api import tenancy_routes as tr
    from app.services.tenant_service import get_tenant_store

    monkeypatch.setattr(settings, "platform_read_consent_enforced", True)

    async def scenario():
        get_tenant_store().create(display_name="No Consent", tenant_id="t_noc")
        with pytest.raises(HTTPException) as exc:
            await tr.platform_tenant_detail("t_noc", ctx=_platform_ctx())
        assert exc.value.status_code == 403
        rows = _audit_rows(mt_env, "t_noc")
        assert len(rows) == 1
        assert rows[0]["decision"] == "DENY" and rows[0]["consent_state"] == "false"
        assert rows[0]["read_type"] == "per-tenant"

    run(scenario())


def test_platform_per_tenant_read_allowed_when_enforcement_off(mt_env, monkeypatch):
    """Default (enforcement OFF): a no-consent per-tenant read is ALLOWED so the
    platform console keeps working — but an honest audit row is still written,
    marked 'false-unenforced'. This is the parked-rollout state."""
    from app.api import tenancy_routes as tr
    from app.services.tenant_service import get_tenant_store

    monkeypatch.setattr(settings, "platform_read_consent_enforced", False)

    async def scenario():
        get_tenant_store().create(display_name="No Consent Off", tenant_id="t_off")
        out = await tr.platform_tenant_detail("t_off", ctx=_platform_ctx())
        assert out["tenant_id"] == "t_off"
        rows = _audit_rows(mt_env, "t_off")
        assert len(rows) == 1
        assert rows[0]["decision"] == "ALLOW"
        assert rows[0]["consent_state"] == "false-unenforced"

    run(scenario())


def test_platform_per_tenant_read_allowed_with_consent(mt_env):
    """With consent granted, the detail is served and an ALLOW audit row persists."""
    from app.api import tenancy_routes as tr
    from app.services.tenant_service import get_tenant_store

    async def scenario():
        store = get_tenant_store()
        store.create(display_name="Consented", tenant_id="t_yes")
        store.set_platform_read_consent("t_yes", True)
        out = await tr.platform_tenant_detail("t_yes", ctx=_platform_ctx())
        assert out["tenant_id"] == "t_yes"
        assert out["platform_read_consent"] is True
        rows = _audit_rows(mt_env, "t_yes")
        assert len(rows) == 1 and rows[0]["decision"] == "ALLOW"
        assert rows[0]["consent_state"] == "true"

    run(scenario())


def test_platform_aggregate_read_ignores_consent(mt_env):
    """The aggregate tenants list is _platform-only and needs no per-tenant
    consent, but is still audited under the '*' partition."""
    from app.api import tenancy_routes as tr
    from app.services.tenant_service import get_tenant_store

    async def scenario():
        get_tenant_store().create(display_name="A", tenant_id="t_a1")  # no consent
        out = await tr.platform_list_tenants(ctx=_platform_ctx())
        assert out["count"] >= 1
        rows = _audit_rows(mt_env, "*")
        assert len(rows) == 1 and rows[0]["read_type"] == "aggregate"
        assert rows[0]["decision"] == "ALLOW"

    run(scenario())


def test_set_platform_read_consent_requires_owner(mt_env):
    """platform_read_consent is owner/platform-only — an admin can't self-serve it."""
    from app.api import tenancy_routes as tr
    from app.api.deps import OperatorContext
    from app.services.tenant_service import get_tenant_store

    async def scenario():
        get_tenant_store().create(display_name="Owned", tenant_id="t_own")
        body = tr.TenantUpdateRequest(platform_read_consent=True)
        admin = OperatorContext(sub="op_admin", tenant_id="t_own", role="admin")
        with pytest.raises(HTTPException) as exc:
            await tr.update_tenant("t_own", body, ctx=admin)
        assert exc.value.status_code == 403
        # Owner succeeds and the flag persists.
        owner = OperatorContext(sub="op_owner", tenant_id="t_own", role="owner")
        out = await tr.update_tenant("t_own", body, ctx=owner)
        assert out["platform_read_consent"] is True

    run(scenario())
