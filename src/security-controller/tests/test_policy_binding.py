"""Tests for the agent→policy BINDING model (agent-policy-management M1/M2).

Covers the load-bearing new behavior:
  - get_agent_policy resolves via the agent's `attached_policy_id` (binding),
    loads the bound policy by its STORED id, and requires it active.
  - unbound agent → legacy agent-index GSI fallback (no outage during migration).
  - bound+disabled → PolicyDisabledError → validate() returns POLICY_DISABLED.
  - cloud-from-agent: cloud identity is the AGENT's, not the policy's — binding
    agent-A's policy to agent-B resolves B's region.
  - set_policy_status: enable/disable, 404, and NO system-403 (§2.8); delete
    keeps the system-403.
"""
import pytest
import yaml
from moto import mock_aws
import boto3

from app.config import settings
from app.validators.policy_engine import (
    PolicyEngine, PolicyNotFoundError, PolicyDisabledError,
)
from app.api.models import ValidationRequest

MOCK_BUCKET = "sentra-test-artifacts"


def _create_bucket(s3, bucket: str, region: str) -> None:
    """Create an S3 bucket honoring the real-S3/moto region contract.

    `create_bucket` only omits a LocationConstraint in ``us-east-1``; every
    other region MUST pass ``CreateBucketConfiguration`` or moto raises
    ``IllegalLocationConstraintException``. ``settings`` defaults to
    ``us-west-2`` (config/dev.yaml), so a bare ``create_bucket`` errors on
    setup — this helper makes the moto fixtures region-safe.
    """
    if region == "us-east-1":
        s3.create_bucket(Bucket=bucket)
    else:
        s3.create_bucket(
            Bucket=bucket,
            CreateBucketConfiguration={"LocationConstraint": region},
        )


@pytest.fixture
def aws_credentials(monkeypatch):
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
              "AWS_SECURITY_TOKEN", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(k, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", settings.aws_region)


@pytest.fixture
def env(aws_credentials):
    """Provision agent-registry + policies-metadata (with agent-index) + S3."""
    with mock_aws():
        # PolicyEngine resolves bundles through a PROCESS-WIDE TTL cache
        # (cache_manager, keyed `policy_bundle:{tenant}:{agent_id}`). These tests
        # reuse the same agent_id/policy_id with DIFFERENT content+status across
        # cases (active → disabled, us-east-1 → eu-west-1), bypassing the
        # policy_service writes that would normally invalidate it. Clear the shared
        # cache per test so a prior case's bundle can't satisfy a later get_item.
        from app.utils.cache_manager import get_cache_manager

        get_cache_manager().clear()

        ddb = boto3.resource("dynamodb", region_name=settings.aws_region)
        agents = ddb.create_table(
            TableName=settings.dynamodb_agent_registry_table,
            KeySchema=[{"AttributeName": "agent_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "agent_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        policies = ddb.create_table(
            TableName=settings.dynamodb_policies_metadata_table,
            KeySchema=[{"AttributeName": "policy_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "policy_id", "AttributeType": "S"},
                {"AttributeName": "agent_id", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[{
                "IndexName": "agent-index",
                "KeySchema": [{"AttributeName": "agent_id", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }],
            BillingMode="PAY_PER_REQUEST",
        )
        s3 = boto3.client("s3", region_name=settings.aws_region)
        _create_bucket(s3, MOCK_BUCKET, settings.aws_region)

        def put_policy(policy_id, agent_id, allowed_tools, *, status="active",
                       platform="bedrock", cloud_region="us-east-1", created_by="system"):
            key = f"policies/agents/{agent_id}/{policy_id}.yaml"
            s3.put_object(Bucket=MOCK_BUCKET, Key=key, Body=yaml.safe_dump({
                "schema_version": "v1", "policy_id": policy_id, "agent_id": agent_id,
                "name": f"{agent_id} policy", "version": "1.0.0", "status": status,
                "platform": platform, "cloud_region": cloud_region,
                "allowed_tools": allowed_tools, "allowed_agents": [],
                "max_calls_per_minute": 30, "cross_cloud_dependencies": [],
            }).encode())
            policies.put_item(Item={
                "policy_id": policy_id, "agent_id": agent_id, "version": "1.0.0",
                "status": status, "created_by": created_by,
                "created_at": "2026-06-01T00:00:00Z",
                "s3_bucket": MOCK_BUCKET, "s3_key": key,
            })

        def put_agent(agent_id, *, attached_policy_id=None, platform="bedrock",
                      cloud_provider="aws", cloud_region=None):
            item = {"agent_id": agent_id, "platform": platform,
                    "cloud_provider": cloud_provider, "status": "active"}
            if attached_policy_id:
                item["attached_policy_id"] = attached_policy_id
            if cloud_region:
                item["cloud_region"] = cloud_region
            agents.put_item(Item=item)

        yield {"agents": agents, "policies": policies, "s3": s3,
               "put_policy": put_policy, "put_agent": put_agent}


def _req(agent_id, tool_name="query_customers"):
    return ValidationRequest(
        request_id="r1", session_id="s1", agent_id=agent_id, tool_name=tool_name,
        tool_params={}, user_input="hi", timestamp="2026-06-10T10:00:00Z",
        operation_type="READ",
    )


@pytest.mark.asyncio
async def test_bound_active_loads_bound_policy(env):
    # policy id is NON-derivable (carries a -v1 suffix); binding stores the real id.
    env["put_policy"]("acme-pol-v1", "agentA", ["query_customers"])
    env["put_agent"]("agentA", attached_policy_id="acme-pol-v1", cloud_region="us-east-1")

    policy = await PolicyEngine().get_agent_policy("agentA")
    assert policy["allowed_tools"] == ["query_customers"]
    assert policy["platform"] == "bedrock"
    assert policy["cloud_region"] == "us-east-1"


@pytest.mark.asyncio
async def test_unbound_falls_back_to_gsi(env):
    """No binding → legacy agent-index lookup (migration safety, no outage)."""
    env["put_policy"]("acme-pol-v1", "agentA", ["query_customers"])
    env["put_agent"]("agentA")  # no attached_policy_id

    policy = await PolicyEngine().get_agent_policy("agentA")
    assert policy["allowed_tools"] == ["query_customers"]


@pytest.mark.asyncio
async def test_bound_disabled_raises_policy_disabled(env):
    env["put_policy"]("acme-pol-v1", "agentA", ["query_customers"], status="disabled")
    env["put_agent"]("agentA", attached_policy_id="acme-pol-v1")

    with pytest.raises(PolicyDisabledError):
        await PolicyEngine().get_agent_policy("agentA")


@pytest.mark.asyncio
async def test_validate_returns_policy_disabled_deny(env):
    env["put_policy"]("acme-pol-v1", "agentA", ["query_customers"], status="disabled")
    env["put_agent"]("agentA", attached_policy_id="acme-pol-v1")

    result = await PolicyEngine().validate(_req("agentA"))
    assert result.decision == "DENY"
    assert result.violation_type == "POLICY_DISABLED"
    assert result.should_deny is True


@pytest.mark.asyncio
async def test_unbound_post_migration_denies_not_found(env):
    """Agent with neither a binding nor any active policy → POLICY_NOT_FOUND."""
    env["put_agent"]("lonely")  # no policy anywhere
    with pytest.raises(PolicyNotFoundError):
        await PolicyEngine().get_agent_policy("lonely")


@pytest.mark.asyncio
async def test_cloud_resolves_from_agent_not_policy(env):
    """Bind agentA's (bedrock/us-east-1) policy to agentB (azure_foundry/centralus):
    the engine must resolve B's cloud, not the policy's embedded cloud (§2.3)."""
    env["put_policy"]("shared-pol-v1", "agentA", ["query_customers"],
                      platform="bedrock", cloud_region="us-east-1")
    env["put_agent"]("agentB", attached_policy_id="shared-pol-v1",
                     platform="azure_foundry", cloud_provider="azure",
                     cloud_region="centralus")

    policy = await PolicyEngine().get_agent_policy("agentB")
    assert policy["platform"] == "azure_foundry"     # agent's, not the policy's bedrock
    assert policy["cloud_region"] == "centralus"     # agent's, not us-east-1


@pytest.mark.asyncio
async def test_region_fallback_when_agent_missing_region(env):
    """Agent missing cloud_region → falls back to the policy's region (R7)."""
    env["put_policy"]("acme-pol-v1", "agentA", ["query_customers"], cloud_region="eu-west-1")
    env["put_agent"]("agentA", attached_policy_id="acme-pol-v1")  # no cloud_region

    policy = await PolicyEngine().get_agent_policy("agentA")
    assert policy["cloud_region"] == "eu-west-1"


# ---- set_policy_status (§4.3 / §2.8) ----

@pytest.fixture
def policy_service(env):
    from app.services.policy_service import PolicyService
    return PolicyService()


@pytest.mark.asyncio
async def test_set_status_disable_then_enable_system_policy(env, policy_service):
    """§2.8: enable/disable ALLOWED on system policies (no 403)."""
    env["put_policy"]("acme-pol-v1", "agentA", ["query_customers"], created_by="system")

    off = await policy_service.set_policy_status("acme-pol-v1", "disabled", "op@x.com")
    assert off["status"] == "disabled"
    assert env["policies"].get_item(Key={"policy_id": "acme-pol-v1"})["Item"]["status"] == "disabled"

    on = await policy_service.set_policy_status("acme-pol-v1", "active", "op@x.com")
    assert on["status"] == "active"


@pytest.mark.asyncio
async def test_set_status_404(env, policy_service):
    from app.exceptions import NotFoundException
    with pytest.raises(NotFoundException):
        await policy_service.set_policy_status("nope", "disabled", "op@x.com")


@pytest.mark.asyncio
async def test_set_status_invalid(env, policy_service):
    from app.exceptions import ValidationException
    env["put_policy"]("acme-pol-v1", "agentA", ["query_customers"])
    with pytest.raises(ValidationException):
        await policy_service.set_policy_status("acme-pol-v1", "paused", "op@x.com")


@pytest.mark.asyncio
async def test_delete_keeps_system_403(env, policy_service):
    """§2.8: DELETE stays protected on system policies (the one divergence)."""
    from app.exceptions import ForbiddenException
    env["put_policy"]("acme-pol-v1", "agentA", ["query_customers"], created_by="system")
    with pytest.raises(ForbiddenException):
        await policy_service.delete_policy("acme-pol-v1", "op@x.com")


@pytest.mark.asyncio
async def test_update_without_version_auto_increments(env, policy_service):
    """agent-policy-management §6.3/K10: the editor OMITS version on edit; the
    service must auto-increment (not 422 at the model, not 400 at the validator).
    Regression for the two-layer version bug."""
    env["put_policy"]("acme-pol-v1", "agentA", ["query_customers"])
    env["put_agent"]("agentA")  # validator checks the agent exists in the registry
    # The exact shape the editor PUTs — NO version field.
    body = {
        "schema_version": "v1", "agent_id": "agentA", "name": "agentA policy",
        "allowed_tools": ["query_customers", "query_orders"],
        "policies": [{"policy_id": "r1", "name": "rule one", "severity": "medium"}],
    }
    out = await policy_service.update_policy("acme-pol-v1", body, "op@x.com")
    assert out["success"] is True
    assert out["previous_version"] == "1.0.0"
    assert out["version"] == "1.0.1"   # auto-incremented patch
