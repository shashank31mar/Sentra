"""WS-J J1.4 — the frozen ``RouteSpec`` manifest (lld/38 §4.1, Appendix A).

The authoritative D-2 coverage list: every wired ``/v1`` method the controller
exposes, reconciled against real code (``routes.py`` 45 decorators + 16
``tenancy_routes.py`` = 61 in-code ``/v1`` routes) plus the 4 demo-agent proxy
methods (65 gateway-wired methods total). The coverage guard (Jc.1) joins
``app.routes`` against this manifest and goes RED if a landed route has no canary.

Auth classes (task §7 / §8):
  * ``public``     — no auth (``GET /v1/health`` liveness probe).
  * ``key``        — ``X-Api-Key`` at API Gateway (the ~44 edge routes).
  * ``key_gated``  — ``X-Api-Key``-reachable BUT ``require_role``-gated in-app
                     (``DELETE /v1/feedback/subjects/{locator}``, routes.py:834).
                     WS-M's authz lock is the code under test; not landed for this
                     route in Increment 1 → ``landed_flag=False`` (exempt, J7).
  * ``oidc``       — ALB ``authenticate-cognito`` + operator RBAC (the 16
                     ``tenancy_routes.py`` rows). Deferred to Increment 2 (console/
                     auth) → ``landed_flag=False``.
  * ``demo_proxy`` — the 4 demo-agent action routes (separate FastAPI apps, not in
                     THIS controller's ``app.routes``). Not introspectable in-process
                     → ``landed_flag=False`` in Increment 1 (live-only, §8.4).

``failure_axis`` (task §7 "Failure-mode axis per route" + J2.4) — the documented
negative cases each route must have a canary for; drawn from the allowed set
``{400,401,403,404,409,422,429,DENY}``.

``authz_gap_flag`` — the ``G``-marked WS-M-scope mutations (policy CRUD, agent-policy
attach/detach, rollback, quarantine POST/DELETE, discovery/import, connections
mutations, sigma PATCH) whose ``require_role``/anti-IDOR lock WS-J tests once landed.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass, field
from typing import Dict, List, Tuple

# The only legal negative-axis tokens (Jc.1 validates the manifest against this).
ALLOWED_AXES = frozenset({"400", "401", "403", "404", "409", "422", "429", "DENY"})

AUTH_CLASSES = frozenset({"public", "key", "key_gated", "oidc", "demo_proxy"})


@dataclass(frozen=True)
class RouteSpec:
    """One wired method + how the canary must exercise it (lld/38 §4.1)."""

    path: str
    method: str
    auth_class: str
    ws_owner: str
    failure_axis: Tuple[str, ...] = ()
    landed_flag: bool = True
    authz_gap_flag: bool = False
    # WS-M M5.2 / lld/39 §5 — a data-plane READ gated by the verified-agent-JWT bind
    # (``_dataplane_tenant_bind``), NOT ``require_role``. Under the deployed enforce
    # ceiling (or the ``require_dataplane_credential`` latch) a tokenless read → 401;
    # at the hermetic default (identity off, latch off) the read runs on the ambient
    # tenant → 200. J7.5 asserts the bind; J7.1's positive probe must accept EITHER
    # honest outcome (200 ambient-read OR 401 refused) for these rows — never a 5xx.
    dataplane_bind: bool = False


def _key(path: str, method: str, owner: str, axes=(), landed: bool = True,
         gap: bool = False, dp_bind: bool = False) -> RouteSpec:
    return RouteSpec(path, method, "key", owner, tuple(axes), landed, gap, dp_bind)


def _oidc(path: str, method: str, owner: str, axes=(), gap: bool = False) -> RouteSpec:
    # Increment-1 deferral (task §0 D-3/§3.2): all OIDC rows are landed_flag=False.
    return RouteSpec(path, method, "oidc", owner, tuple(axes), False, gap)


def _demo(path: str, method: str, axes=()) -> RouteSpec:
    # Demo-agent proxies live in separate apps → not in-process; live-only.
    return RouteSpec(path, method, "demo_proxy", "WS-J", tuple(axes), False, False)


# Common failure axes.
_NA = ("401", "422")            # needs api-key + a well-formed body
_NA404 = ("401", "404")         # id-addressed read
_MUT = ("401", "403", "422")    # gated mutation (403 once authz lands)


ROUTE_MANIFEST: List[RouteSpec] = [
    # --- public --------------------------------------------------------------
    RouteSpec("/v1/health", "GET", "public", "WS-J", (), True, False),

    # --- /v1/validate (WS-B/D) ----------------------------------------------
    _key("/v1/validate", "POST", "WS-B", ("401", "422", "DENY"), landed=True),

    # --- logs / sessions / decisions (read) ----------------------------------
    # NOTE: id-addressed COLLECTION queries (logs-by-conversation, session decisions/
    # signals, agent tools) return 200-empty for a non-existent id — they are
    # filters, not resource fetches — so they carry NO 404 axis (verified 2026-07-05).
    _key("/v1/logs", "GET", "WS-D", ("401",)),
    _key("/v1/logs/conversation/{conversation_id}", "GET", "WS-D", ("401",)),
    _key("/v1/sessions", "GET", "WS-D", ("401",)),
    _key("/v1/sessions/{session_id}/decisions", "GET", "WS-D", ("401",)),
    _key("/v1/sessions/{session_id}/trail", "GET", "WS-D", ("401",), dp_bind=True),
    _key("/v1/sessions/{session_id}/signals", "GET", "WS-D", ("401",), dp_bind=True),
    _key("/v1/sessions/{session_id}/signals", "POST", "WS-D", ("401", "422"), gap=True),
    _key("/v1/decisions", "GET", "WS-D", ("401",)),
    _key("/v1/decisions/{decision_id}/verdict", "POST", "WS-D", ("401", "422"), gap=True),

    # --- metrics -------------------------------------------------------------
    # metrics/overview + decisions-timeseries read CloudWatch GetMetricData, which
    # moto does not faithfully emulate → their positive+401 probes are requires_live
    # (Increment-1 hermetic gap, documented). platform-distribution reads DynamoDB.
    _key("/v1/metrics", "GET", "WS-J", ("401",)),
    RouteSpec("/v1/metrics/overview", "GET", "key", "WS-J", ("401",), False, False),
    _key("/v1/metrics/platform-distribution", "GET", "WS-J", ("401",)),
    RouteSpec("/v1/metrics/decisions-timeseries", "GET", "key", "WS-J", ("401",), False, False),

    # --- rollback / quarantine (WS-M-scope mutations) ------------------------
    _key("/v1/rollback", "POST", "WS-M", ("401", "422"), gap=True),
    _key("/v1/rollback/conversation/{conversation_id}", "POST", "WS-M", ("401", "422"), gap=True),
    _key("/v1/quarantine/{session_id}", "POST", "WS-M", ("401", "404"), gap=True),
    _key("/v1/quarantine/{session_id}", "DELETE", "WS-M", ("401", "404"), gap=True),

    # --- agents --------------------------------------------------------------
    _key("/v1/agents", "GET", "WS-M", ("401",)),
    _key("/v1/agents/{agent_id}", "GET", "WS-M", _NA404),
    # agent tools is a collection query → 200-empty for a missing agent (no 404).
    _key("/v1/agents/{agent_id}/tools", "GET", "WS-M", ("401",)),
    _key("/v1/agents/{agent_id}/policies", "POST", "WS-M", ("401", "422"), gap=True),
    _key("/v1/agents/{agent_id}/policies/{policy_id}", "DELETE", "WS-M", ("401", "404"), gap=True),

    # --- policies (CRUD — the BUG-1 IDOR surface WS-M locks) -----------------
    _key("/v1/policies", "GET", "WS-M", ("401",)),
    _key("/v1/policies/{policy_id}", "GET", "WS-M", _NA404),
    _key("/v1/policies", "POST", "WS-M", ("401", "422", "409"), gap=True),
    _key("/v1/policies/{policy_id}", "PUT", "WS-M", ("401", "404", "422"), gap=True),
    _key("/v1/policies/{policy_id}", "DELETE", "WS-M", ("401", "404"), gap=True),
    _key("/v1/policies/{policy_id}/status", "PATCH", "WS-M", ("401", "404", "422"), gap=True),

    # --- sigma-rules (WS-F/WS-M platform-gate on PATCH retire) ---------------
    _key("/v1/sigma-rules", "GET", "WS-F", ("401",)),
    _key("/v1/sigma-rules/{rule_id}", "PATCH", "WS-F", ("401", "404", "422"), gap=True),
    _key("/v1/sigma-rules/{rule_id}/content", "GET", "WS-F", _NA404),

    # --- discovery -----------------------------------------------------------
    _key("/v1/discovery/agents", "GET", "WS-M", ("401",)),
    _key("/v1/discovery/summary", "GET", "WS-M", ("401",)),
    _key("/v1/discovery/platforms", "GET", "WS-M", ("401",)),
    _key("/v1/discovery/import", "POST", "WS-M", ("401", "422"), gap=True),

    # --- connections (CRUD) --------------------------------------------------
    _key("/v1/connections", "GET", "WS-M", ("401",)),
    _key("/v1/connections", "POST", "WS-M", ("401", "422"), gap=True),
    _key("/v1/connections/{connection_id}", "GET", "WS-M", _NA404),
    _key("/v1/connections/{connection_id}", "PUT", "WS-M", ("401", "404", "422"), gap=True),
    _key("/v1/connections/{connection_id}", "DELETE", "WS-M", ("401", "404"), gap=True),
    _key("/v1/connections/{connection_id}/test", "POST", "WS-M", ("401", "404"), gap=True),
    _key("/v1/connections/{connection_id}/scan", "POST", "WS-M", ("401", "404"), gap=True),

    # --- key-reachable BUT require_role-gated (WS-M authz; exempt Inc-1) ------
    RouteSpec("/v1/feedback/subjects/{subject_locator}", "DELETE", "key_gated",
              "WS-M", ("401", "403", "404"), False, True),

    # --- OIDC (16 — the 2 tenancy_routes.py sets; Increment-2 console/auth) ---
    _oidc("/v1/me", "GET", "WS-G"),
    _oidc("/v1/identity/residual-agents", "GET", "WS-M"),
    _oidc("/v1/agents/{agent_id}/credentials", "GET", "WS-M", _NA404),
    _oidc("/v1/agents/{agent_id}/credentials", "POST", "WS-M", ("401", "403", "422"), gap=True),
    _oidc("/v1/agents/{agent_id}/credentials/{kid}/rotate", "POST", "WS-M", ("401", "403", "404"), gap=True),
    _oidc("/v1/agents/{agent_id}/credentials/{kid}", "DELETE", "WS-M", ("401", "403", "404"), gap=True),
    _oidc("/v1/tenants", "POST", "WS-M", ("401", "403", "422"), gap=True),
    _oidc("/v1/tenants/{tenant_id}", "GET", "WS-M", ("401", "403", "404")),
    _oidc("/v1/tenants/{tenant_id}", "PATCH", "WS-M", ("401", "403", "404", "422"), gap=True),
    _oidc("/v1/tenants/{tenant_id}", "DELETE", "WS-M", ("401", "403", "404"), gap=True),
    _oidc("/v1/tenants/{tenant_id}/members", "GET", "WS-M", ("401", "403", "404")),
    _oidc("/v1/tenants/{tenant_id}/members/{operator_sub}", "DELETE", "WS-M", ("401", "403", "404"), gap=True),
    _oidc("/v1/tenants/{tenant_id}/invites", "POST", "WS-M", ("401", "403", "404", "422"), gap=True),
    _oidc("/v1/invites/redeem", "POST", "WS-M", ("401", "422"), gap=True),
    _oidc("/v1/platform/tenants", "GET", "WS-M", ("401", "403")),
    _oidc("/v1/platform/tenants/{tenant_id}", "GET", "WS-M", ("401", "403", "404")),

    # --- demo-agent proxies (4 — separate apps; live-only) -------------------
    _demo("/action/refund", "POST", ("401", "DENY")),
    _demo("/action/query", "POST", ("401", "DENY")),
    _demo("/action/transfer", "POST", ("401", "DENY")),
    _demo("/action/notify", "POST", ("401", "DENY")),
]


# REQUIRED_SCENARIOS (J1.4) — scenario-letter → is-required-now. J2/J4/J6 gate now;
# J3/J5/J7/J8 are deferred (auto-activate on their landed_flag, task §3 deferred block).
REQUIRED_SCENARIOS: Dict[str, bool] = {
    "J2": True,
    "J4": True,
    "J6": True,
    "J3": False,   # differential conformance — WS-A local-floor + WS-I emitter
    "J5": False,   # metering no-miss/dedup — WS-H
    "J7": True,    # server authz gate — WS-M LANDED 2026-07-07 (§5A); console UI = J8
    "J8": False,   # console UI sweep + OIDC routes — WS-G/WS-M (Increment 2)
}


def manifest_index() -> Dict[Tuple[str, str], RouteSpec]:
    """``(path, method) -> RouteSpec`` for the coverage-guard join (Jc.1)."""
    return {(s.path, s.method): s for s in ROUTE_MANIFEST}


__all__ = [
    "RouteSpec",
    "ROUTE_MANIFEST",
    "REQUIRED_SCENARIOS",
    "ALLOWED_AXES",
    "AUTH_CLASSES",
    "manifest_index",
    "FrozenInstanceError",
]
