"""Integration guard for the `_assert_owns_agent` move into app.api.ownership.

`assert_owns` is a SHARED CONTRACT owned by WS-M (M0.1). The tenancy_routes
credential gates historically used a LOCAL `_assert_owns_agent`; M0.1 repoints them
at the re-exported alias in `ownership.py`. This test proves the move is a no-op:
tenancy_routes still imports the same symbol name AND it behaves identically
(delimited-prefix, 403 on a foreign / short-prefix agent id) when driven through
an actual tenancy_routes credential handler.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.deps import OperatorContext


def _ctx(tenant_id: str, role: str = "admin") -> OperatorContext:
    return OperatorContext(sub="op", tenant_id=tenant_id, role=role, email="op@x")


def test_tenancy_routes_uses_reexported_ownership_alias():
    """tenancy_routes._assert_owns_agent IS the ownership alias (same object) — the
    gate can't silently fork back to a local copy."""
    import app.api.tenancy_routes as tr
    from app.api.ownership import _assert_owns_agent_compat

    assert tr._assert_owns_agent is _assert_owns_agent_compat


def test_reexported_alias_still_enforces_delimited_prefix():
    """Behaviour parity: own-tenant OK, foreign → 403, short-prefix no false match."""
    import app.api.tenancy_routes as tr

    tr._assert_owns_agent(_ctx("t_a"), "t_a-aws-x-1")  # own → no raise
    with pytest.raises(HTTPException) as ei:
        tr._assert_owns_agent(_ctx("t_a"), "t_b-aws-x-1")  # foreign → 403
    assert ei.value.status_code == 403
    with pytest.raises(HTTPException) as ei2:
        tr._assert_owns_agent(_ctx("t_01"), "t_01hxyz-aws-x-1")  # short-prefix trap
    assert ei2.value.status_code == 403


@pytest.mark.asyncio
async def test_ownership_helper_reused_by_tenancy_route_handler():
    """Drive an actual gated tenancy_routes handler (register_credential) through the
    re-exported alias: a foreign agent id is rejected 403 by the same ownership path
    the 10-gate regression set relies on — proving the move didn't change behaviour."""
    from app.api.tenancy_routes import register_credential, CredentialRegisterRequest

    body = CredentialRegisterRequest(public_key="-----BEGIN PUBLIC KEY-----\nx\n-----END PUBLIC KEY-----")
    # ctx is tenant t_a; the agent id belongs to t_b → assert_owns must 403 before
    # any store write is attempted.
    with pytest.raises(HTTPException) as ei:
        await register_credential("t_b-aws-victim-1", body, ctx=_ctx("t_a"))
    assert ei.value.status_code == 403
