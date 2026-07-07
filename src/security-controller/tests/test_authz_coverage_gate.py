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
    # Data-plane reads gated by the M5 verified-JWT tenant-bind, NOT require_role
    # (Invariant 6 — they carry no operator role).
    "get_session_trail": "data-plane read; M5 JWT-tenant-bind, not RBAC",
    "get_session_signals": "data-plane read; M5 JWT-tenant-bind, not RBAC",
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
    # Data-plane reads gated by the M5 verified-JWT tenant-bind, NOT resolve_operator_tenant.
    "get_session_trail": "data-plane read; M5 JWT-tenant-bind, not operator-OIDC",
    "get_session_signals": "data-plane read; M5 JWT-tenant-bind, not operator-OIDC",
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


def test_read_gate_accepts_dataplane_bind():
    """The data-plane reads (trail, signals) are on the allowlist and do NOT
    need resolve_operator_tenant (they use _dataplane_tenant_bind)."""
    names = {name for _, name in _read_routes()}
    for dp_name in ("get_session_trail", "get_session_signals"):
        assert dp_name in _READ_AUTHZ_ALLOWLIST or dp_name not in names


def test_allowlist_requires_reason():
    """Every allowlist entry carries a non-empty reason (no silent bypasses)."""
    for name, reason in {**_AUTHZ_ALLOWLIST, **_OWNERSHIP_EXEMPT}.items():
        assert reason and reason.strip(), f"allowlist entry {name} needs a reason"
