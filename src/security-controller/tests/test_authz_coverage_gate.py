"""Systemic ungated-route CI gate (WS-M M0.2 / lld/39 §M0).

A build-failing static check: every mutating (``post/put/patch/delete``) route on
the control-plane routers MUST carry an authz ``Depends`` (``require_role`` or
``require_platform``), with an explicit, reasoned allowlist for the deliberate
data-plane exceptions. This is the systemic guard so a NEW ungated route can't
slip in and silently re-open a BUG-1-class hole — presence-of-gate is enforced by
the build, not by review vigilance.

The gate accepts BOTH ``require_role`` and ``require_platform`` (M3 gates the
sigma-retire route with the latter). It also asserts the subtler ownership half:
a route taking a resource-id path param must call ``assert_owns`` or be on a
reasoned ownership-exempt allowlist.
"""
from __future__ import annotations

import inspect

import pytest
from fastapi.routing import APIRoute

from app.api import routes as routes_mod
from app.api import tenancy_routes as tenancy_mod


# Deliberate data-plane / no-target exceptions to the *authz-Depends* rule.
# Each entry MUST carry a reason (the test asserts the reason is non-empty).
#
# NOTE ON THE `PENDING WS-M …` ENTRIES: this round lands M0 (helper + this gate) +
# M1 (policy-CRUD/bind, routes 1-6). The connection/quarantine/rollback/verdict/
# discovery/sigma routes are gated in the LATER WS-M milestones named in each
# reason — they are tracked, NOT permanently exempt. As each milestone lands, its
# route moves out of this allowlist and grows a real gate; the gate then re-fires
# if the route regresses. (Removing an entry here is part of that milestone's DoD.)
_AUTHZ_ALLOWLIST = {
    # --- permanent (data-plane / bootstrap; NOT an operator-RBAC surface) --------
    "validate_tool_call": "data-plane POST /v1/validate; agent-JWT boundary, not RBAC",
    # (WS-N D10: get_session_trail/get_session_signals were here as agent-lane GET
    # reads; they are now operator-bound GETs — removed. GETs never hit this
    # mutating-route gate anyway; kept out for accuracy.)
    # Auth bootstrap routes: an operator with no membership yet cannot depend on
    # resolve_operator_tenant — they verify ALB-OIDC in-body instead.
    "create_tenant": "first-tenant creator has no membership; verifies OIDC in-body",
    "redeem_invite": "pre-membership redemption; verifies OIDC in-body",
    # Route 19 (WS-M M2.8): the external-producer signal write is INTERIM FAIL-CLOSED
    # (403 unless the producer credential ships) — a config fail-closed, not an
    # operator-RBAC surface. It carries no require_role Depends by design; the full
    # producer credential is design-only/deferred (D4).
    "post_session_signal": "external producer write; interim fail-closed (M2.8), no operator-RBAC surface",
}

# Routes that take a resource-id path param but are legitimately ownership-exempt
# (the id is not a cross-tenant target, or ownership is asserted server-side by a
# different mechanism). Each carries a reason.
_OWNERSHIP_EXEMPT = {
    # tenancy_routes assert ownership via _assert_owns_agent / tenant-membership
    # checks inline (LLD-26); they predate assert_owns and are the regression set.
    "register_credential": "tenancy_routes: _assert_owns_agent inline",
    "rotate_credential": "tenancy_routes: _assert_owns_agent inline",
    "revoke_credential": "tenancy_routes: _assert_owns_agent inline",
    "update_tenant": "tenancy_routes: tenant-membership check inline",
    "delete_tenant": "tenancy_routes: tenant-membership check inline",
    "create_invite": "tenancy_routes: tenant-membership check inline",
    "remove_member": "tenancy_routes: tenant-membership check inline",
    "update_sigma_rule": "fleet-global (not tenant-scoped); require_platform (M3)",
    # Data-plane / bootstrap exceptions carry no operator-owned resource target.
    "post_session_signal": "external producer write; no operator-owned target",
    "create_tenant": "creates a new tenant; no pre-existing target",
    "redeem_invite": "redeems into a membership; no pre-existing target",
    # DONE positive template (routes.py:903): the subject_locator is scoped
    # server-side to ctx.tenant_id inside the handler (not a cross-tenant DB key),
    # so it needs no assert_owns — the tenant bind IS the ownership guarantee.
    "delete_feedback_subject": "DONE: delete scoped to ctx.tenant_id server-side (positive template)",
}

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


def _authz_routes():
    """(APIRoute, handler_name) for every mutating route on the two control-plane
    routers. Filters out non-APIRoute entries and pure GETs."""
    out = []
    for mod in (routes_mod, tenancy_mod):
        for r in mod.router.routes:
            if not isinstance(r, APIRoute):
                continue
            if not (_MUTATING & set(r.methods or set())):
                continue
            out.append((r, r.endpoint.__name__))
    return out


def _has_authz_depends(route: APIRoute) -> bool:
    """True if any Depends() on the endpoint resolves (transitively) to
    ``require_role`` or ``require_platform``. ``require_role`` returns a closure
    ``_dep`` whose closure cells reference ``resolve_operator_tenant``;
    ``require_platform`` is the named coroutine itself."""
    sig = inspect.signature(route.endpoint)
    for p in sig.parameters.values():
        dep = getattr(p.default, "dependency", None)
        if dep is None:
            continue
        name = getattr(dep, "__name__", "")
        if name == "require_platform":
            return True
        # require_role("x") -> inner `_dep` closure carrying min_role + the
        # resolve_operator_tenant dependency.
        if name == "_dep":
            closure = dep.__closure__ or ()
            vals = {c.cell_contents for c in closure}
            # min_role string is present in the closure of require_role's _dep.
            if any(isinstance(v, str) for v in vals):
                return True
    return False


def _has_assert_owns(route: APIRoute) -> bool:
    """True if the handler's source calls assert_owns / _assert_owns_agent."""
    try:
        src = inspect.getsource(route.endpoint)
    except OSError:  # pragma: no cover
        return False
    return "assert_owns" in src or "_assert_owns_agent" in src


def _takes_resource_id(route: APIRoute) -> bool:
    """The route path carries a resource-id path param (a potential IDOR target)."""
    # e.g. /v1/policies/{policy_id}; ignore the tenant_id param (self-scoped).
    params = [seg for seg in route.path.split("/") if seg.startswith("{") and seg.endswith("}")]
    named = {p[1:-1] for p in params}
    named.discard("tenant_id")  # tenant target uses membership check, not assert_owns
    return bool(named)


def test_all_mutating_routes_have_authz_depends():
    """Every mutating route has an authz gate, or is on the reasoned allowlist."""
    ungated = []
    for route, name in _authz_routes():
        if name in _AUTHZ_ALLOWLIST:
            continue
        if not _has_authz_depends(route):
            ungated.append(f"{sorted(route.methods)} {route.path} ({name})")
    assert not ungated, (
        "Ungated mutating route(s) — add a require_role/require_platform Depends "
        f"or a reasoned allowlist entry: {ungated}")


def test_gate_accepts_require_platform():
    """The enumerator must count ``Depends(require_platform)`` as a gate (else it
    false-fails once M3 gates the sigma-retire route)."""
    from app.api.deps import require_platform
    from fastapi import Depends

    async def _fake(ctx=Depends(require_platform)):  # pragma: no cover - shape only
        return ctx

    route = APIRoute("/v1/x/{id}", _fake, methods=["PATCH"])
    assert _has_authz_depends(route) is True


def test_role_gated_but_ownership_missing_route_fails():
    """Proves the ownership half is real: a route that is role-gated but takes a
    resource-id and calls no assert_owns is caught (the subtler BUG-1 half)."""
    from app.api.deps import require_role
    from fastapi import Depends

    async def _fake(id: str, ctx=Depends(require_role("editor"))):  # pragma: no cover
        return {"id": id}

    route = APIRoute("/v1/things/{id}", _fake, methods=["PUT"])
    assert _has_authz_depends(route) is True
    assert _takes_resource_id(route) is True
    assert _has_assert_owns(route) is False  # the gate would flag this


def test_resource_id_routes_have_ownership_assert():
    """Every role-gated route taking a resource-id path param calls assert_owns,
    or is on the reasoned ownership-exempt allowlist."""
    missing = []
    for route, name in _authz_routes():
        if name in _AUTHZ_ALLOWLIST or name in _OWNERSHIP_EXEMPT:
            continue
        if _takes_resource_id(route) and not _has_assert_owns(route):
            missing.append(f"{sorted(route.methods)} {route.path} ({name})")
    assert not missing, (
        "Role-gated route(s) with a resource-id but no assert_owns (IDOR risk) — "
        f"add assert_owns or a reasoned ownership-exempt entry: {missing}")


# ============================================================
# WS-N N7 — READ-route auth coverage gate (extends WS-M's GET-blind gate)
# ============================================================

# Reasoned allowlist for GET routes without resolve_operator_tenant.
# Each entry MUST carry a reason. Only genuinely tenant-agnostic routes belong.
_READ_AUTHZ_ALLOWLIST = {
    "health_check": "liveness probe; no auth, no tenant data",
    # WS-N D10 (ADR-038): get_session_trail + get_session_signals were formerly
    # allowlisted here as agent-JWT-lane data-plane reads. They are now OPERATOR
    # control-plane reads carrying Depends(resolve_operator_tenant) (the console is
    # their sole consumer), so they are GATED, not allowlisted — and per lld/40 §5.2
    # a tenant-partitioned read may NEVER be allowlisted. Removed deliberately.
}


def _read_routes():
    """(APIRoute, handler_name) for every GET route on the two control-plane routers."""
    out = []
    for mod in (routes_mod, tenancy_mod):
        for r in mod.router.routes:
            if not isinstance(r, APIRoute):
                continue
            if "GET" not in (r.methods or set()):
                continue
            out.append((r, r.endpoint.__name__))
    return out


def _has_read_auth_depends(route: APIRoute) -> bool:
    """True if any Depends() on the endpoint resolves to resolve_operator_tenant,
    require_role, or require_platform (any form of operator auth)."""
    from app.api.deps import resolve_operator_tenant
    sig = inspect.signature(route.endpoint)
    for p in sig.parameters.values():
        dep = getattr(p.default, "dependency", None)
        if dep is None:
            continue
        # Direct resolve_operator_tenant
        if dep is resolve_operator_tenant:
            return True
        name = getattr(dep, "__name__", "")
        if name == "require_platform":
            return True
        if name == "resolve_operator_tenant":
            return True
        # require_role("x") -> inner `_dep` closure
        if name == "_dep":
            closure = dep.__closure__ or ()
            vals = {c.cell_contents for c in closure}
            if any(isinstance(v, str) for v in vals):
                return True
    return False


def test_all_read_routes_have_auth_dep():
    """WS-N N7: every GET route on the control-plane routers carries an auth
    dependency (resolve_operator_tenant / require_role / require_platform), or is
    on the reasoned allowlist."""
    ungated = []
    for route, name in _read_routes():
        if name in _READ_AUTHZ_ALLOWLIST:
            continue
        if not _has_read_auth_depends(route):
            ungated.append(f"GET {route.path} ({name})")
    assert not ungated, (
        "Ungated read route(s) — add Depends(resolve_operator_tenant) "
        f"or a reasoned allowlist entry: {ungated}")


def test_read_allowlist_requires_reason():
    """Every read allowlist entry must carry a non-empty reason."""
    for name, reason in _READ_AUTHZ_ALLOWLIST.items():
        assert reason, f"allowlist entry {name!r} has no reason"


def test_trail_signals_are_operator_bound():
    """WS-N D10 (ADR-038): get_session_trail + get_session_signals were reclassified
    from the agent-JWT data-plane lane to the OPERATOR control-plane lane. They MUST
    now carry Depends(resolve_operator_tenant) (the console is their sole consumer) and
    MUST NOT be on the read allowlist (a tenant-partitioned read is never allowlisted,
    lld/40 §5.2)."""
    routes_by_name = {name: route for route, name in _read_routes()}
    for dp_name in ("get_session_trail", "get_session_signals"):
        assert dp_name in routes_by_name, f"{dp_name} missing from control-plane GET routes"
        assert _has_read_auth_depends(routes_by_name[dp_name]), (
            f"{dp_name} must carry resolve_operator_tenant (D10 lane reversal)")
        assert dp_name not in _READ_AUTHZ_ALLOWLIST, (
            f"{dp_name} is now bound — remove it from the read allowlist")


def test_allowlist_requires_reason():
    """Every allowlist entry carries a non-empty reason (no silent bypasses)."""
    for name, reason in {**_AUTHZ_ALLOWLIST, **_OWNERSHIP_EXEMPT}.items():
        assert reason and reason.strip(), f"allowlist entry {name} needs a reason"


# ==========================================================================
# WS-N N7 (DEEP) — interprocedural sink-reachability gate (lld/40 §5.2, lines
# 226-234). The shallow `test_all_read_routes_have_auth_dep` above only checks a
# handler's OWN signature for a Depends. The REAL D10 bug class is a handler that
# reaches a tenant-partition STORE-ACCESS SINK *through a service method* with no
# bind (get_agents -> AgentService.list_agents -> tenancy.query_or_scan). A
# body-only check passes that. This gate follows the call graph handler -> service
# -> sink and FAILS a sink-reaching read that carries no operator bind.
#
# Per lld/40 line 234: a tenant-partitioned (sink-reaching) read may NEVER be
# allowlisted — the allowlist is only for genuinely tenant-agnostic routes.
# ==========================================================================
import ast
import os

# The tenant-partition key-composing sinks (lld/40 line 228 + the two KCE/GSI helpers
# in tenancy.py that compose a current_tenant()-scoped key). A GET handler transitively
# reaching ANY of these reads a tenant partition and MUST carry an operator bind.
_TENANT_SINKS = frozenset({
    "query_or_scan", "fleet_scan", "signal_pk_value", "item_key",
    "decision_date_gsi_value", "agent_index_kce_value",
})

# The service/util modules the read handlers reach through (handler -> these -> sink).
_APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(routes_mod.__file__)))  # .../app
# Scan the routers + EVERY service/util module (glob, not a hand-list — a hand-list
# silently misses a new service and under-approximates, which is fail-OPEN). This
# builds the whole-app name-keyed call graph.
def _all_app_py_files():
    files = []
    for sub in ("api", "services", "utils", "combiners", "validators"):
        d = os.path.join(_APP_ROOT, sub)
        if not os.path.isdir(d):
            continue
        for root, _dirs, names in os.walk(d):
            for n in names:
                if n.endswith(".py"):
                    files.append(os.path.join(root, n))
    return files


def _build_function_index():
    """Parse every app .py file → {func_name: set(callee_names)} across the whole
    app surface (keyed by bare function/method name — Python's dynamic dispatch makes
    a fully-qualified graph infeasible, so we over-approximate by name, which is
    fail-CLOSED: it can only flag MORE routes as sink-reaching, never fewer)."""
    calls_by_func: dict[str, set] = {}

    class _V(ast.NodeVisitor):
        def __init__(self):
            self.stack = []

        def _enter(self, node):
            self.stack.append(node.name)
            calls_by_func.setdefault(node.name, set())
            self.generic_visit(node)
            self.stack.pop()

        visit_FunctionDef = _enter
        visit_AsyncFunctionDef = _enter

        def visit_Call(self, node):
            if self.stack:
                fn = node.func
                name = getattr(fn, "attr", None) or getattr(fn, "id", None)
                if name:
                    calls_by_func[self.stack[-1]].add(name)
            self.generic_visit(node)

    for path in _all_app_py_files():
        with open(path) as f:
            _V().visit(ast.parse(f.read(), filename=path))
    return calls_by_func


def _reaches_sink(func_name: str, index: dict, _seen=None) -> bool:
    """True if func_name transitively calls any tenant-partition sink (DFS over the
    name-keyed call graph, cycle-safe)."""
    if _seen is None:
        _seen = set()
    if func_name in _seen:
        return False
    _seen.add(func_name)
    callees = index.get(func_name, set())
    if callees & _TENANT_SINKS:
        return True
    return any(_reaches_sink(c, index, _seen) for c in callees if c in index)


def test_sink_reaching_reads_carry_operator_bind():
    """WS-N N7 DEEP: every GET handler that transitively reaches a tenant-partition
    sink MUST carry an operator bind (resolve_operator_tenant / require_role /
    require_platform). A sink-reaching read may NOT rely on the allowlist (lld/40
    line 234). This catches the interprocedural D10 bug class the shallow check misses."""
    index = _build_function_index()
    offenders = []
    for route, name in _read_routes():
        if not _reaches_sink(name, index):
            continue  # tenant-agnostic by construction — nothing to bind
        if _has_read_auth_depends(route):
            continue  # sink-reaching AND bound → correct
        # sink-reaching + unbound. The allowlist is NOT an escape hatch here.
        offenders.append(f"GET {route.path} ({name}) reaches a tenant sink but has no operator bind")
    assert not offenders, (
        "Sink-reaching read route(s) missing an operator tenant bind (lld/40 §5.2 — "
        "a tenant-partitioned read must be BOUND, never allowlisted):\n  " + "\n  ".join(offenders))


def test_sink_reaching_read_not_on_allowlist():
    """lld/40 line 234: a sink-reaching (tenant-partitioned) read must never appear on
    the read allowlist — allowlisting a partitioned read rubber-stamps a leak."""
    index = _build_function_index()
    bad = [name for _, name in _read_routes()
           if name in _READ_AUTHZ_ALLOWLIST and _reaches_sink(name, index)]
    assert not bad, (
        f"Sink-reaching reads illegally allowlisted (must be BOUND, not allowlisted): {bad}")


def test_sink_set_covers_every_tenant_key_composer():
    """META-GUARD (lld/40 line 228-229): the sink set can't silently go stale. Every
    tenant-partition key-composing helper defined in tenancy.py MUST be in _TENANT_SINKS,
    so a NEW `*_pk_value`/`*_gsi_value`/key-composer added later is force-added to the
    gate (else this fails and the reachability gate would miss it)."""
    tenancy_path = os.path.join(_APP_ROOT, "utils/tenancy.py")
    with open(tenancy_path) as f:
        tree = ast.parse(f.read())
    # Heuristic name-match for the tenant-key-composer family (the concrete functions
    # that compose a current_tenant()-scoped key / do a scoped read).
    key_composers = {
        n.name for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef)
        and (n.name.endswith("_pk_value") or n.name.endswith("_gsi_value")
             or n.name.endswith("_kce_value") or n.name in {"item_key", "query_or_scan", "fleet_scan"})
    }
    missing = key_composers - _TENANT_SINKS
    assert not missing, (
        f"tenancy.py defines tenant-key composer(s) not in the N7 sink set: {missing}. "
        "Add them to _TENANT_SINKS or the sink-reachability gate will miss reads using them.")


def test_deep_gate_is_non_vacuous_flags_unbound_sink_reacher():
    """Non-vacuity (lld/40 line 231/233): prove the gate FLAGS a sink-reaching handler
    with no bind, and PASSES the same handler once bound. Uses a synthetic call-graph
    index + fixture handlers (no live route registration needed)."""
    from app.api.deps import resolve_operator_tenant
    from fastapi import Depends

    # A fake handler that reaches a sink via a service method (handler -> svc -> sink).
    fake_index = {
        "leaky_read": {"list_things"},        # handler calls a service method...
        "list_things": {"query_or_scan"},     # ...which hits a tenant sink
        "safe_read": {"static_lookup"},        # reaches no sink
        "static_lookup": set(),
    }
    assert _reaches_sink("leaky_read", fake_index) is True   # the bug class is detected
    assert _reaches_sink("safe_read", fake_index) is False   # tenant-agnostic is clean

    # And the bind-recognizer distinguishes bound vs unbound signatures.
    def _unbound(agent_id: str):  # no operator Depends  # pragma: no cover
        ...

    async def _bound(agent_id: str, ctx=Depends(resolve_operator_tenant)):  # pragma: no cover
        ...

    unbound_route = APIRoute("/x", _unbound, methods=["GET"])
    bound_route = APIRoute("/x", _bound, methods=["GET"])
    assert _has_read_auth_depends(unbound_route) is False  # would be flagged if sink-reaching
    assert _has_read_auth_depends(bound_route) is True     # correctly bound
