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


# --------------------------------------------------------------------------- #
# (containment) create_policy has NO target to own (a create can't reference an
# existing resource), so it carries no assert_owns. The gap: a tenant-A editor can
# POST a body whose agent_id names another tenant (`t_b-...`). Two independent
# containment layers make that harmless — both proven below, not assumed:
#   (1) VALIDATION layer — `_agent_exists` reads the agent registry with a
#       *tenant-scoped* key (`tenancy.item_key('agent_id', ..)` against the
#       creator's ambient tenant), so a foreign-tenant agent_id is NOT in the
#       creator's registry → the create is rejected 400 before any write.
#   (2) STAMP layer — even for a legitimate same-tenant create, the persisted row
#       is stamped to the creator's ambient tenant via `stamp_base_item`, keyed on
#       the ambient tenant, NEVER the body's agent_id — so the row can only land in
#       the creator's partition (lld/39 §2.3 row 1 "scope body to ctx.tenant_id").
# The bind side is separately re-asserted (attach re-checks AGENT ownership above).
# --------------------------------------------------------------------------- #
def _mk_policies_table(ddb):
    from app.config import settings
    return ddb.create_table(
        TableName=settings.dynamodb_policies_metadata_table_v2,
        KeySchema=[{"AttributeName": "tenant_id", "KeyType": "HASH"},
                   {"AttributeName": "policy_id", "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": "tenant_id", "AttributeType": "S"},
                              {"AttributeName": "policy_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )


def _mk_agent_registry_v2(ddb):
    """The v2 agent registry `tenancy.table_name('agent_registry')` resolves to
    when tenancy_v2 is on (composite tenant-scoped key: tenant_id + agent_id)."""
    from app.config import settings
    return ddb.create_table(
        TableName=settings.dynamodb_agent_registry_table_v2,
        KeySchema=[{"AttributeName": "tenant_id", "KeyType": "HASH"},
                   {"AttributeName": "agent_id", "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": "tenant_id", "AttributeType": "S"},
                              {"AttributeName": "agent_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )


@pytest.mark.asyncio
async def test_create_policy_stamps_row_to_creator_tenant_not_body(monkeypatch):
    """STAMP layer: a legitimate same-tenant create (agent registered under t_a)
    lands the row in the creator's (t_a) partition — the stamp is keyed on the
    ambient operator tenant, not the body's agent_id. (Reverting stamp_base_item
    to honor a body-supplied tenant would fail this.)"""
    import boto3
    from moto import mock_aws

    from app.api.models import PolicyCreateRequest
    from app.config import settings
    from app.utils import tenancy

    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SECURITY_TOKEN", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(k, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", settings.aws_region)
    monkeypatch.setattr(settings, "tenancy_v2_enabled", True)
    monkeypatch.setattr(settings, "cedar_enabled", False)

    body = PolicyCreateRequest(
        schema_version="v1", agent_id="t_a-svc", name="n", version="1.0.0",
        allowed_tools=["q"],
        policies=[{"policy_id": "r1", "name": "rule one", "severity": "medium"}])

    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name=settings.aws_region)
        table = _mk_policies_table(ddb)
        registry = _mk_agent_registry_v2(ddb)
        # The agent is registered under the CREATOR's tenant (t_a) → validation passes.
        registry.put_item(Item={"tenant_id": "t_a", "agent_id": "t_a-svc"})

        async def _fake_upload(self, key, content, metadata=None):
            return "v-1"

        async def _noop_metric(self, *a, **k):
            return None

        tenancy.set_current_tenant("t_a")
        try:
            with patch("app.utils.s3_policy_store.S3PolicyStore.upload", _fake_upload), \
                 patch("app.utils.metrics_publisher.MetricsPublisher.publish_policy_crud_metric", _noop_metric), \
                 patch("app.utils.metrics_publisher.MetricsPublisher.publish_policy_validation_metric", _noop_metric):
                await R.create_policy(body, ctx=_ctx(tenant_id="t_a", role="editor"))
        finally:
            tenancy.set_current_tenant(tenancy.DEFAULT_TENANT)

        in_a = table.get_item(Key={"tenant_id": "t_a", "policy_id": "agent-config-t_a-svc"}).get("Item")
        assert in_a is not None, "policy must land in the creator's (t_a) partition"
        assert in_a["tenant_id"] == "t_a", "row must be stamped to the ambient operator tenant"


@pytest.mark.asyncio
async def test_create_policy_foreign_body_agent_id_rejected_no_cross_tenant_plant(monkeypatch):
    """VALIDATION layer (the exact gap-note scenario): a tenant-A editor whose body
    names a FOREIGN-tenant agent (`t_b-victim`, registered only under t_b) is
    REJECTED 400 — `_agent_exists` reads the registry with a tenant-scoped key
    against the creator's ambient tenant (t_a), so the foreign agent is not found.
    No record is planted in EITHER partition. Proves the foreign body agent_id is
    harmless, not merely assumed (the gap this closes)."""
    import boto3
    from moto import mock_aws

    from app.api.models import PolicyCreateRequest
    from app.config import settings
    from app.utils import tenancy

    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SECURITY_TOKEN", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(k, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", settings.aws_region)
    monkeypatch.setattr(settings, "tenancy_v2_enabled", True)
    monkeypatch.setattr(settings, "cedar_enabled", False)

    foreign_body = PolicyCreateRequest(
        schema_version="v1", agent_id="t_b-victim", name="n", version="1.0.0",
        allowed_tools=["q"],
        policies=[{"policy_id": "r1", "name": "rule one", "severity": "medium"}])

    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name=settings.aws_region)
        table = _mk_policies_table(ddb)
        registry = _mk_agent_registry_v2(ddb)
        # The agent exists ONLY under tenant B — invisible to tenant A's scoped read.
        registry.put_item(Item={"tenant_id": "t_b", "agent_id": "t_b-victim"})

        async def _noop_metric(self, *a, **k):
            return None

        tenancy.set_current_tenant("t_a")
        try:
            with patch("app.utils.metrics_publisher.MetricsPublisher.publish_policy_crud_metric", _noop_metric), \
                 patch("app.utils.metrics_publisher.MetricsPublisher.publish_policy_validation_metric", _noop_metric):
                with pytest.raises(HTTPException) as ei:
                    await R.create_policy(foreign_body, ctx=_ctx(tenant_id="t_a", role="editor"))
        finally:
            tenancy.set_current_tenant(tenancy.DEFAULT_TENANT)

        assert ei.value.status_code == 400, "foreign-tenant agent_id must be rejected, not written"
        # No record planted in EITHER partition.
        in_a = table.get_item(Key={"tenant_id": "t_a", "policy_id": "agent-config-t_b-victim"}).get("Item")
        in_b = table.get_item(Key={"tenant_id": "t_b", "policy_id": "agent-config-t_b-victim"}).get("Item")
        assert in_a is None and in_b is None, "no cross-tenant record may be planted"


@pytest.mark.asyncio
async def test_create_policy_carries_no_ownership_assert_by_design():
    """A create names no existing resource to own, so — unlike update/delete/attach —
    create_policy must NOT call assert_owns (a spurious assert would 404 legitimate
    creates). Containment is the tenant-stamp, asserted above; this pins the absence
    of a target-ownership check so a later 'fix' can't quietly break creates."""
    seen = []
    with patch("app.api.routes.assert_owns", side_effect=lambda *a, **k: seen.append(a)):
        class _Svc:
            async def create_policy(self, policy_data, operator_email):
                return {"policy_id": "p1"}
        with patch("app.services.policy_service.PolicyService", _Svc):
            await R.create_policy(_policy_create(), ctx=_ctx(role="editor"))
    assert seen == [], "create_policy must not assert_owns a body-supplied target"
