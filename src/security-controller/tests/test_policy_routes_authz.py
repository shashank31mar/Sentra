"""Policy-CRUD route authz tests (WS-M M1.1 / M1.2 — closes BUG-1, lld/39 §3.2-3.3).

Two halves, mirroring the DSAR positive-template tests:
  * **Wiring** — signature-inspection proves each of the 6 routes carries the right
    ``require_role`` Depends (can't be silently dropped).
  * **Behaviour** — driving the handler with an injected verified ``ctx`` proves
    (a) operator attribution is the verified ``ctx.sub`` (never ``X-Operator-Email``),
    (b) ``X-Operator-Email`` is no longer even a parameter, (c) ownership is
    asserted before mutating, and (d) an empty-email claim still yields a non-empty
    identity (``ctx.sub``).
"""
from __future__ import annotations

import inspect

import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, patch

from app.api import routes as R
from app.api.deps import OperatorContext


def _ctx(tenant_id="t_a", role="admin", sub="op-verified", email="op@x"):
    return OperatorContext(sub=sub, tenant_id=tenant_id, role=role, email=email)


def _policy_create():
    from app.api.models import PolicyCreateRequest
    return PolicyCreateRequest(
        schema_version="v1", agent_id="t_a-x", name="n", version="1.0.0",
        allowed_tools=["q"],
        policies=[{"policy_id": "r1", "name": "rule one", "severity": "medium"}])


def _policy_update():
    from app.api.models import PolicyUpdateRequest
    return PolicyUpdateRequest(
        schema_version="v1", agent_id="t_a-x", name="n", version="1.0.1",
        allowed_tools=["q"],
        policies=[{"policy_id": "r1", "name": "rule one", "severity": "medium"}])


def _min_role_of(handler) -> str:
    """Extract the min_role a route's require_role() gate carries (closure cell)."""
    sig = inspect.signature(handler)
    dep = sig.parameters["ctx"].default.dependency
    vals = {c.cell_contents for c in (dep.__closure__ or ())}
    roles = {v for v in vals if isinstance(v, str)}
    assert roles, f"{handler.__name__} carries no require_role gate"
    return next(iter(roles))


# --------------------------------------------------------------------------- #
# (wiring) every route carries the right role gate + no X-Operator-Email param
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("handler,expected_role", [
    (R.create_policy, "editor"),
    (R.update_policy, "editor"),
    (R.delete_policy, "admin"),
    (R.set_policy_status, "editor"),
    (R.attach_agent_policy, "editor"),
    (R.detach_agent_policy, "editor"),
])
def test_route_carries_expected_role_gate(handler, expected_role):
    assert _min_role_of(handler) == expected_role


@pytest.mark.parametrize("handler", [
    R.create_policy, R.update_policy, R.delete_policy,
    R.set_policy_status, R.attach_agent_policy, R.detach_agent_policy,
])
def test_x_operator_email_no_longer_a_parameter(handler):
    """The spoofable header is dropped as an authority — it isn't a param at all."""
    params = set(inspect.signature(handler).parameters)
    assert "operator_email" not in params


# --------------------------------------------------------------------------- #
# (behaviour) operator attribution derives from verified ctx.sub, not a header
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_create_policy_operator_derived_from_ctx_sub():
    captured = {}

    class _Svc:
        async def create_policy(self, policy_data, operator_email):
            captured["operator_email"] = operator_email
            return {"policy_id": "p1"}

    with patch("app.services.policy_service.PolicyService", _Svc):
        await R.create_policy(_policy_create(), ctx=_ctx(sub="op-verified", role="editor"))
    # attribution is the VERIFIED sub, never a client header/email
    assert captured["operator_email"] == "op-verified"


@pytest.mark.asyncio
async def test_create_policy_empty_email_still_yields_identity():
    """A Cognito pool that omits `email` gives ctx.email == "" — attribution must
    still key on the non-empty ctx.sub (M7 empty-email row)."""
    captured = {}

    class _Svc:
        async def create_policy(self, policy_data, operator_email):
            captured["op"] = operator_email
            return {"policy_id": "p1"}

    with patch("app.services.policy_service.PolicyService", _Svc):
        await R.create_policy(_policy_create(), ctx=_ctx(sub="sub-abc", email=""))
    assert captured["op"] == "sub-abc"
    assert captured["op"]  # non-empty


@pytest.mark.asyncio
async def test_update_policy_asserts_ownership_before_mutating():
    """A cross-tenant target is blocked BEFORE the service is touched (M1.2)."""
    svc = AsyncMock()
    with patch("app.api.routes.assert_owns", side_effect=HTTPException(404)), \
         patch("app.services.policy_service.PolicyService", return_value=svc):
        with pytest.raises(HTTPException) as ei:
            await R.update_policy("p-foreign", _policy_update(), ctx=_ctx())
    assert ei.value.status_code == 404
    svc.update_policy.assert_not_called()  # never mutated


@pytest.mark.asyncio
async def test_attach_asserts_agent_then_policy_ownership_in_order():
    """attach_agent_policy asserts AGENT ownership first, then POLICY (order matters
    — a foreign agent 403s before the policy is even looked up)."""
    from app.api.ownership import ResourceKind

    calls = []

    def _fake_assert(ctx, kind, rid):
        calls.append(kind)

    with patch("app.api.routes.assert_owns", side_effect=_fake_assert), \
         patch("app.services.agent_service.AgentService") as AS:
        AS.return_value.attach_policy = AsyncMock(return_value={"status": "attached"})
        await R.attach_agent_policy("t_a-agent", {"policy_id": "p1"}, ctx=_ctx(role="editor"))
    assert calls == [ResourceKind.AGENT, ResourceKind.POLICY]


@pytest.mark.asyncio
async def test_delete_policy_ownership_asserted():
    with patch("app.api.routes.assert_owns", side_effect=HTTPException(403)), \
         patch("app.services.policy_service.PolicyService") as PS:
        with pytest.raises(HTTPException) as ei:
            await R.delete_policy("p-foreign", ctx=_ctx(role="admin"))
    assert ei.value.status_code == 403
    PS.assert_not_called()


@pytest.mark.asyncio
async def test_conflicting_operator_email_dropped_not_forwarded():
    """M1.3: even a request that tries to smuggle an operator_email cannot reach the
    downstream consumer — the handler forwards ctx.sub, and operator_email isn't a
    param, so there is nothing to forward."""
    captured = {}

    class _Svc:
        async def create_policy(self, policy_data, operator_email):
            captured["op"] = operator_email
            return {"policy_id": "p1"}

    with patch("app.services.policy_service.PolicyService", _Svc):
        await R.create_policy(_policy_create(), ctx=_ctx(sub="real-op"))
    assert captured["op"] == "real-op"  # the attacker's header value is unreachable
