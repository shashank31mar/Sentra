"""WS-J §5A — J7 authz / RBAC coverage (WS-M landed 2026-07-07).

J7.1: no-identity → 401/403 (already covered by test_all_routes.py via the updated
      ``scenario_j2_4_positive`` that branches on ``authz_gap_flag``).
J7.2: authorized-positive — the correct role → handler (not 401/403).
J7.3: under-privileged — one tier below required role → 403.
J7.4: cross-tenant IDOR — AGENT-prefix ownership → 403 foreign.
J7.5: dataplane-bind JWT (GET /signals + /trail) → 401 no-token + signals fail-closed.

ALL depth legs are INPROCESS-ONLY (the ALB-OIDC override seam doesn't exist on the
deployed service). Live mode asserts only the no-identity leg (J7.1, via test_all_routes).
"""
from __future__ import annotations

import pytest

from canary.route_manifest import ROUTE_MANIFEST

# ---- the 19 authz-gated key routes (drove empirically, hermetic verified) -----------
_GAP_ROUTES = [
    s for s in ROUTE_MANIFEST
    if s.auth_class == "key" and s.landed_flag and s.authz_gap_flag
]

# Route → (required_role, owns). None owns = no assert_owns (born-scoped / bulk).
# This is the code-truth from routes.py grepped 2026-07-07 — resolve by handler NAME.
_ROLE_MAP = {
    ("POST", "/v1/policies"): ("editor", None),
    ("PUT", "/v1/policies/{policy_id}"): ("editor", "POLICY"),
    ("DELETE", "/v1/policies/{policy_id}"): ("admin", "POLICY"),
    ("PATCH", "/v1/policies/{policy_id}/status"): ("editor", "POLICY"),
    ("POST", "/v1/agents/{agent_id}/policies"): ("editor", "AGENT+POLICY"),
    ("DELETE", "/v1/agents/{agent_id}/policies/{policy_id}"): ("editor", "AGENT"),
    ("POST", "/v1/connections"): ("admin", None),
    ("PUT", "/v1/connections/{connection_id}"): ("admin", "CONNECTION"),
    ("POST", "/v1/connections/{connection_id}/test"): ("editor", "CONNECTION"),
    ("POST", "/v1/connections/{connection_id}/scan"): ("editor", "CONNECTION"),
    ("DELETE", "/v1/connections/{connection_id}"): ("admin", "CONNECTION"),
    ("PATCH", "/v1/sigma-rules/{rule_id}"): ("_platform", None),
    ("DELETE", "/v1/quarantine/{session_id}"): ("admin", "SESSION"),
    ("POST", "/v1/quarantine/{session_id}"): ("admin", "SESSION"),
    ("POST", "/v1/rollback"): ("admin", "ACTION"),
    ("POST", "/v1/rollback/conversation/{conversation_id}"): ("admin", "CONVERSATION"),
    ("POST", "/v1/discovery/import"): ("editor", None),
    ("POST", "/v1/decisions/{decision_id}/verdict"): ("editor", "SESSION"),
    ("POST", "/v1/sessions/{session_id}/signals"): ("_failclosed", None),
}

_LADDER = ["viewer", "editor", "admin", "owner"]


def _below(role: str) -> str:
    """Return one tier below ``role`` in the RBAC ladder. For _platform/_failclosed,
    the tier below is ``admin`` (a tenant admin can't reach platform gates). NOTE:
    ``_below('viewer')`` returns ``'viewer'`` (bottom of the ladder) — this is safe
    because NO gated route in ``_ROLE_MAP`` requires only ``viewer`` (all require
    ≥ editor). If one ever does, J7.3 would need a separate "anonymous" leg."""
    if role in ("_platform", "_failclosed"):
        return "admin"  # tenant-admin is below platform
    idx = _LADDER.index(role)
    return _LADDER[max(0, idx - 1)]


def _fill_path(tmpl: str, tenant_id: str) -> str:
    import re
    return re.sub(r"\{[^}]+\}", f"{tenant_id}-probe-id", tmpl)


def _body(method: str, path: str = ""):
    """A minimal well-formed body per route type so the request reaches the authz gate
    (not a body-shape 400/422 before the handler fires). Routes with richer body
    requirements get per-path overrides."""
    if method in ("GET", "DELETE"):
        return None
    # attach_agent_policy requires {"policy_id": str}
    if "/agents/" in path and "/policies" in path and method == "POST":
        return {"policy_id": "canary-probe-policy"}
    # rollback requires {"action_id": str} or minimal body
    if "/rollback" in path and method == "POST":
        return {"action_id": "canary-act-probe", "operator_id": "x"}
    # quarantine POST requires minimal body
    if "/quarantine" in path and method == "POST":
        return {"operator_id": "x"}
    # discovery/import requires a list body
    if "/discovery/import" in path:
        return {"agents": []}
    # verdict requires verdict+reason
    if "/verdict" in path:
        return {"verdict": "confirmed_threat", "reason": "canary probe"}
    # signals POST requires a signal dict
    if "/signals" in path and method == "POST":
        return {"source": "canary", "decision": "ALLOW", "priority": 50}
    # connections POST/PUT require a minimal shape
    if "/connections" in path and method in ("POST", "PUT"):
        return {"name": "canary", "platform": "aws", "config": {}}
    return {}


# --------------------------------------------------------------------------- J7.2
_J72_ROUTES = [s for s in _GAP_ROUTES if _ROLE_MAP.get((s.method, s.path), (None,))[0] not in ("_failclosed",)]
_J72_IDS = [f"{s.method} {s.path}" for s in _J72_ROUTES]


@pytest.mark.parametrize("spec", _J72_ROUTES, ids=_J72_IDS)
def test_j7_2_authorized_role_succeeds(canary_client, canary_operator, canary_tenant, spec):
    """J7.2 — a sufficient role in the owning tenant reaches the handler (not 401/403).
    The handler may still return a 4xx (400 body-shape / 404 id-not-found on the empty
    hermetic store) — those are honest documented outcomes, not authz failures."""
    if canary_client.mode != "inprocess":
        pytest.skip("J7.2 authorized-positive is inprocess-only (ALB-OIDC seam)")
    role, _owns = _ROLE_MAP[(spec.method, spec.path)]
    canary_operator.mint(canary_tenant, role)
    url = _fill_path(spec.path, canary_tenant)
    body = _body(spec.method, spec.path)
    kw = {"json": body} if body is not None and spec.method not in ("GET", "DELETE") else {}
    resp = getattr(canary_client, spec.method.lower())(url, **kw)
    assert resp.status_code not in (401, 403), (
        f"{spec.method} {spec.path} with {role} → {resp.status_code} — "
        f"authz gate rejected a sufficient role (lock too strict or membership seed failed)"
    )


# --------------------------------------------------------------------------- J7.3
_J73_ROUTES = [
    s for s in _GAP_ROUTES
    if _ROLE_MAP.get((s.method, s.path), (None,))[0] not in ("_failclosed",)
]
_J73_IDS = [f"{s.method} {s.path}" for s in _J73_ROUTES]


@pytest.mark.parametrize("spec", _J73_ROUTES, ids=_J73_IDS)
def test_j7_3_underprivileged_403(canary_client, canary_operator, canary_tenant, spec):
    """J7.3 — one tier below the required role → 403 (the RBAC ladder proof)."""
    if canary_client.mode != "inprocess":
        pytest.skip("J7.3 under-privileged is inprocess-only (ALB-OIDC seam)")
    role, _owns = _ROLE_MAP[(spec.method, spec.path)]
    under_role = _below(role)
    canary_operator.mint(canary_tenant, under_role)
    url = _fill_path(spec.path, canary_tenant)
    body = _body(spec.method, spec.path)
    kw = {"json": body} if body is not None and spec.method not in ("GET", "DELETE") else {}
    resp = getattr(canary_client, spec.method.lower())(url, **kw)
    assert resp.status_code == 403, (
        f"{spec.method} {spec.path} with {under_role} (< {role}) → {resp.status_code} — "
        f"expected 403; the RBAC gate did not refuse an under-privileged caller"
    )


# --------------------------------------------------------------------------- J7.4
# Cross-tenant AGENT ownership: the AGENT-prefix routes 403 on a foreign agent id
# (v2-independent — the tenant-prefix is checked in-memory, not from a store).
_J74_AGENT_ROUTES = [
    s for s in _GAP_ROUTES
    if "AGENT" in (_ROLE_MAP.get((s.method, s.path), ("", ""))[1] or "")
]
_J74_IDS = [f"{s.method} {s.path}" for s in _J74_AGENT_ROUTES]


@pytest.mark.parametrize("spec", _J74_AGENT_ROUTES, ids=_J74_IDS)
def test_j7_4_cross_tenant_agent_403(canary_client, canary_operator, canary_tenant, spec):
    """J7.4 (AGENT) — an operator with a sufficient role in their OWN tenant attempts a
    mutation on an agent belonging to ANOTHER tenant → 403 (the agent id is tenant-
    prefixed, so a foreign agent is an obvious IDOR). This is the BUG-1 regression
    guard for the prefix-ownership family."""
    if canary_client.mode != "inprocess":
        pytest.skip("J7.4 IDOR is inprocess-only (ALB-OIDC seam)")
    role, _owns = _ROLE_MAP[(spec.method, spec.path)]
    # Operator in canary-tenant, but the URL names a FOREIGN agent (tenantB prefix).
    canary_operator.mint(canary_tenant, role)
    foreign_tenant = "canary-tenantB-foreign"
    url = _fill_path(spec.path, foreign_tenant)  # agent id starts with foreign_tenant
    body = _body(spec.method, spec.path)
    kw = {"json": body} if body is not None and spec.method not in ("GET", "DELETE") else {}
    resp = getattr(canary_client, spec.method.lower())(url, **kw)
    assert resp.status_code == 403, (
        f"{spec.method} {spec.path} with foreign agent → {resp.status_code} — "
        f"expected 403 (IDOR: prefix-ownership should refuse a foreign tenant's agent)"
    )


# --------------------------------------------------------------------------- J7.5
def test_j7_5_signals_failclosed(canary_client, canary_operator, canary_tenant):
    """J7.5 — POST /v1/sessions/{id}/signals is INTERIM FAIL-CLOSED (403) with the
    default ``external_signal_write_enabled=False``. Proves the external-producer
    injection surface stays closed."""
    if canary_client.mode != "inprocess":
        pytest.skip("J7.5 signals fail-closed is inprocess-only (config seam)")
    # Operator with editor role (would be sufficient for most routes).
    canary_operator.mint(canary_tenant, "editor")
    resp = canary_client.post(
        f"/v1/sessions/{canary_tenant}-probe-id/signals",
        json={"source": "canary", "decision": "ALLOW", "priority": 50},
    )
    assert resp.status_code == 403, (
        f"POST /signals with external_signal_write_enabled=False → {resp.status_code}; "
        f"expected 403 (interim fail-closed)"
    )


def test_j7_5_dataplane_read_no_token(canary_client):
    """J7.5 — GET /v1/sessions/{id}/signals (and /trail) with NO agent JWT under the
    deployed enforce ceiling → 401 in live. In hermetic (identity off + latch off)
    the bind is not enforced → 200 ambient-read. So this asserts the mode-documented
    honest outcome (never a 5xx, never a fake-200-error). The stronger enforce-401 leg
    is proven by the LIVE hourly monitor (test_all_routes.py, J7.1)."""
    # /signals (no required params → reaches the bind)
    resp = canary_client.get("/v1/sessions/canary-sess/signals")
    assert resp.status_code < 500, f"GET /signals → {resp.status_code}"
    if canary_client.mode == "live":
        assert resp.status_code == 401
    else:
        assert resp.status_code in (200, 401)
    # /trail (requires request_id → without it, FastAPI 422s BEFORE the bind;
    # WITH it and no JWT, the bind fires or the ambient read proceeds).
    resp = canary_client.get("/v1/sessions/canary-sess/trail?request_id=canary-req")
    assert resp.status_code < 500, f"GET /trail → {resp.status_code}"
    if canary_client.mode == "live":
        assert resp.status_code == 401
    else:
        assert resp.status_code in (200, 401, 404)
