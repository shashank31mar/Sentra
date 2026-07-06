"""Data-plane JWT boundary + /trail-/signals tenant bind + operator contextvar reset
(WS-M M5.2 / M5.3, lld/39 §5).

M5.2: the deployed WS-D ``/trail`` + ``/signals`` read handlers resolved the partition
from the ambient ``current_tenant()`` (``"default"``) — a live cross-tenant read for a
non-enforcing tenant. They now bind the VERIFIED agent tenant (NOT ``require_role`` —
Invariant 6). M5.3: a *raising* ``resolve_operator_tenant`` (401/403) must reset the
tenant contextvar to the ``default`` sentinel, not leave a stale same-context bind.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from unittest.mock import Mock, patch

from app.api import routes as R
from app.api.deps import TenantContext
from app.utils import tenancy


class _Req:
    headers = {}


# --------------------------------------------------------------------------- #
# M5.2 — /trail + /signals bind the verified tenant (deny at enforce; no default)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_trail_read_binds_verified_tenant():
    """A verified+enforce agent JWT binds ctx.tenant_id for the DecisionsService read
    (not the ambient default)."""
    seen = {}

    def _trail(**k):
        seen["tenant"] = tenancy.current_tenant()
        return {"ok": True}

    svc = Mock()
    svc.get_session_trail = Mock(side_effect=_trail)
    verified = TenantContext.verified(tenant_id="t_a", agent_id="t_a-x", effective_mode="enforce")
    with patch("app.api.deps.resolve_tenant_from_jwt", return_value=verified), \
         patch("app.api.routes._decisions_service", return_value=svc):
        out = await R.get_session_trail("s1", "r1", _Req())
    assert out == {"ok": True}
    assert seen["tenant"] == "t_a"  # bound to the verified tenant during the read


@pytest.mark.asyncio
async def test_signals_read_binds_verified_tenant():
    seen = {}

    def _signals(**k):
        seen["tenant"] = tenancy.current_tenant()
        return {"signals": []}

    svc = Mock()
    svc.get_session_signals = Mock(side_effect=_signals)
    verified = TenantContext.verified(tenant_id="t_b", agent_id="t_b-x", effective_mode="enforce")
    with patch("app.api.deps.resolve_tenant_from_jwt", return_value=verified), \
         patch("app.api.routes._decisions_service", return_value=svc):
        await R.get_session_signals("s1", _Req())
    assert seen["tenant"] == "t_b"


@pytest.mark.asyncio
async def test_trail_enforce_missing_jwt_denies_not_default():
    """At enforce, a missing/invalid JWT (should_deny) → 401, NEVER a read on the
    ambient default partition."""
    unver = TenantContext.unverified(effective_mode="enforce")  # should_deny is True
    svc = Mock()
    with patch("app.api.deps.resolve_tenant_from_jwt", return_value=unver), \
         patch("app.api.routes._decisions_service", return_value=svc):
        with pytest.raises(HTTPException) as ei:
            await R.get_session_trail("s1", "r1", _Req())
    assert ei.value.status_code == 401
    svc.get_session_trail.assert_not_called()


@pytest.mark.asyncio
async def test_trail_disabled_mode_reads_without_bind_change():
    """Identity OFF fleet-wide (disabled) → the read runs as before (no hard deny —
    the console must keep working before identity rolls out)."""
    svc = Mock()
    svc.get_session_trail = Mock(return_value={"ok": True})
    disabled = TenantContext.disabled()
    with patch("app.api.deps.resolve_tenant_from_jwt", return_value=disabled), \
         patch("app.api.routes._decisions_service", return_value=svc):
        out = await R.get_session_trail("s1", "r1", _Req())
    assert out == {"ok": True}


def test_trail_signals_carry_no_require_role():
    """Invariant 6: these are data-plane reads — they must NOT carry a require_role
    gate (their isolation is the JWT-tenant-bind, not RBAC)."""
    import inspect
    for handler in (R.get_session_trail, R.get_session_signals):
        params = inspect.signature(handler).parameters
        assert "ctx" not in params, f"{handler.__name__} must not carry an operator ctx gate"


# --------------------------------------------------------------------------- #
# M5.3 — operator-dependency contextvar reset (non-vacuous: single shared context)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_operator_dependency_resets_contextvar():
    """Drive resolve_operator_tenant twice within ONE asyncio Task (a single async
    test shares one context): a successful resolve binds tenant-A, then a RAISING
    resolve on the SAME context must leave the DEFAULT sentinel, not tenant-A
    (fail-secure). A two-request TestClient test would be vacuously green (Starlette
    copies context per request) and MUST NOT be used — this asserts the raising-path
    `finally` reset on a shared context."""
    import app.api.deps as deps

    m = Mock()
    m.tenant_id = "t_a"
    m.role = "admin"
    m.is_primary = True

    # 1) success → binds tenant-A on this Task's context
    deps._alb_claims_override = lambda req: {"sub": "op_a", "email": "a@x"}
    try:
        with patch("app.api.deps.get_member_store") as gms:
            gms.return_value.by_operator.return_value = [m]
            ctx = await deps.resolve_operator_tenant(_Req())
        assert ctx.tenant_id == "t_a"
        assert tenancy.current_tenant() == "t_a"

        # 2) a raising resolve on the SAME context (no membership → 403)
        deps._alb_claims_override = lambda req: {"sub": "op_none", "email": "n@x"}
        with patch("app.api.deps.get_member_store") as gms:
            gms.return_value.by_operator.return_value = []
            with pytest.raises(HTTPException):
                await deps.resolve_operator_tenant(_Req())
        # the finally reset forced the default sentinel — NOT the stale tenant-A
        assert tenancy.current_tenant() == tenancy.DEFAULT_TENANT
    finally:
        deps._alb_claims_override = None
        tenancy.set_current_tenant(tenancy.DEFAULT_TENANT)
