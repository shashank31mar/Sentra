"""
Unit Tests for Policy Engine

Tests agent authorization and tool permission validation.

Rewritten to match the hybrid DDB + S3 storage architecture introduced in
Workstream 6 / Task 1.7. The PolicyEngine reads from:
  - sentra-policies-metadata DDB table (queried by agent_id via agent-index GSI)
  - S3 bucket (downloads full policy YAML referenced by s3_bucket + s3_key)

These tests mock both layers using moto. Cross-cloud dependency enforcement
(Workstream 15) is covered in tests/test_context_validator_cross_cloud.py.

Coverage target: >80%
"""
import pytest
import yaml
from moto import mock_aws
import boto3
from app.validators.policy_engine import PolicyEngine, PolicyNotFoundError
from app.api.models import ValidationRequest
from app.config import settings


# A single mock S3 bucket name used across all tests. Doesn't have to match
# the real artifacts bucket — moto creates whatever we ask for.
MOCK_BUCKET = "sentra-test-artifacts"


def _policy_yaml(agent_id: str, allowed_tools: list, allowed_agents: list,
                 max_calls: int = 30, status: str = "active",
                 platform: str = "bedrock", cloud_region: str = "us-east-1") -> str:
    """Build a policy YAML string with the production schema."""
    return yaml.safe_dump({
        "schema_version": "1.1",
        "policy_id": f"{agent_id}-policy-v1",
        "agent_id": agent_id,
        "name": f"{agent_id} Policy",
        "version": "1.0.0",
        "status": status,
        "platform": platform,
        "cloud_region": cloud_region,
        "allowed_tools": allowed_tools,
        "allowed_agents": allowed_agents,
        "max_calls_per_minute": max_calls,
        "cross_cloud_dependencies": [],
    })


@pytest.fixture
def aws_credentials(monkeypatch):
    """Mock AWS credentials for moto."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", settings.aws_region)


@pytest.fixture
def mocked_aws(aws_credentials):
    """Provision the hybrid DDB metadata table + S3 bucket the engine expects."""
    with mock_aws():
        # 1) Metadata DDB table — schema mirrors production (LLD 06 §2.3).
        ddb = boto3.resource("dynamodb", region_name=settings.aws_region)
        metadata_table = ddb.create_table(
            TableName=settings.dynamodb_policies_metadata_table,
            KeySchema=[
                {"AttributeName": "policy_id", "KeyType": "HASH"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "policy_id", "AttributeType": "S"},
                {"AttributeName": "agent_id", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "agent-index",
                    "KeySchema": [
                        {"AttributeName": "agent_id", "KeyType": "HASH"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # 2) S3 bucket for full policy YAMLs.
        s3 = boto3.client("s3", region_name=settings.aws_region)
        s3.create_bucket(Bucket=MOCK_BUCKET)

        # Helper to register a policy in both layers consistently.
        def register(agent_id: str, allowed_tools: list, allowed_agents: list,
                     max_calls: int = 30, status: str = "active"):
            s3_key = f"policies/agents/{agent_id}/v1.0.0.yaml"
            yaml_content = _policy_yaml(agent_id, allowed_tools, allowed_agents, max_calls, status)
            s3.put_object(Bucket=MOCK_BUCKET, Key=s3_key, Body=yaml_content.encode("utf-8"))
            metadata_table.put_item(Item={
                "policy_id": f"{agent_id}-policy-v1",
                "agent_id": agent_id,
                "name": f"{agent_id} Policy",
                "version": "1.0.0",
                "status": status,
                "s3_bucket": MOCK_BUCKET,
                "s3_key": s3_key,
            })

        # Seed the same agents the legacy tests assumed.
        register(
            "customer-query-agent",
            allowed_tools=["query_customers", "query_orders", "query_with_limit", "invoke_agent"],
            allowed_agents=["payment-agent"],
            max_calls=30,
        )
        register(
            "payment-agent",
            allowed_tools=["check_order", "process_refund", "reverse_refund", "invoke_agent"],
            allowed_agents=[],
            max_calls=15,
        )

        # An inactive entry — its FilterExpression status check should exclude it.
        # Note we point it at a DIFFERENT s3 key so it can coexist with the active one.
        inactive_key = "policies/agents/customer-query-agent/v0.9.0.yaml"
        s3.put_object(
            Bucket=MOCK_BUCKET, Key=inactive_key,
            Body=_policy_yaml("customer-query-agent", ["old_tool"], [], status="inactive").encode("utf-8"),
        )
        metadata_table.put_item(Item={
            "policy_id": "customer-query-agent-policy-v0",
            "agent_id": "customer-query-agent",
            "name": "Customer Query Agent Policy (old)",
            "version": "0.9.0",
            "status": "inactive",
            "s3_bucket": MOCK_BUCKET,
            "s3_key": inactive_key,
        })

        yield {"ddb": metadata_table, "s3": s3, "register": register}


@pytest.fixture
def policy_engine(mocked_aws):
    """PolicyEngine wired to the mocked DDB + S3."""
    return PolicyEngine()


@pytest.fixture
def sample_request():
    return ValidationRequest(
        request_id="req-test-123",
        session_id="sess-test-789",
        agent_id="customer-query-agent",
        tool_name="query_customers",
        tool_params={},
        user_input="test input",
        timestamp="2025-01-18T10:00:00Z",
        operation_type="READ",
    )


@pytest.mark.asyncio
async def test_authorized_tool_returns_allow(policy_engine, sample_request):
    """Authorized tool (query_customers in allowed_tools) returns ALLOW."""
    result = await policy_engine.validate(sample_request)
    assert result.decision == "ALLOW"
    assert result.should_deny is False
    assert "passed" in result.reason.lower()
    # Workstream 15: cross-cloud fields populated from policy
    assert result.platform == "bedrock"
    assert result.cloud_region == "us-east-1"


@pytest.mark.asyncio
async def test_unauthorized_tool_returns_deny(policy_engine, sample_request):
    """Unauthorized tool returns DENY."""
    sample_request.tool_name = "process_refund"  # not in customer-query-agent's allowed_tools
    result = await policy_engine.validate(sample_request)
    assert result.decision == "DENY"
    assert result.should_deny is True
    assert result.violation_type == "UNAUTHORIZED_TOOL"
    assert "not authorized" in result.reason.lower()
    assert result.penalty == -15
    # Workstream 15: DENY responses also carry cross-cloud fields
    assert result.platform == "bedrock"


@pytest.mark.asyncio
async def test_authorized_agent_invocation_returns_allow(policy_engine, sample_request):
    sample_request.tool_name = "invoke_agent"
    sample_request.tool_params = {"agent_id": "payment-agent"}
    result = await policy_engine.validate(sample_request)
    assert result.decision == "ALLOW"


@pytest.mark.asyncio
async def test_unauthorized_agent_invocation_returns_deny(policy_engine, sample_request):
    sample_request.tool_name = "invoke_agent"
    sample_request.tool_params = {"agent_id": "unauthorized-agent"}
    result = await policy_engine.validate(sample_request)
    assert result.decision == "DENY"
    assert result.should_deny is True
    assert result.violation_type == "UNAUTHORIZED_AGENT_INVOCATION"
    assert "cannot invoke" in result.reason.lower()
    assert result.penalty == -15


@pytest.mark.asyncio
async def test_invoke_agent_without_target_returns_deny(policy_engine, sample_request):
    sample_request.tool_name = "invoke_agent"
    sample_request.tool_params = {}  # missing agent_id
    result = await policy_engine.validate(sample_request)
    assert result.decision == "DENY"
    assert result.should_deny is True
    assert result.violation_type == "INVALID_AGENT_INVOCATION"
    assert "requires target agent_id" in result.reason.lower()


@pytest.mark.asyncio
async def test_missing_policy_returns_deny(policy_engine, sample_request):
    """Missing policy → fail-secure DENY."""
    sample_request.agent_id = "nonexistent-agent"
    result = await policy_engine.validate(sample_request)
    assert result.decision == "DENY"
    assert result.should_deny is True
    assert result.violation_type == "POLICY_NOT_FOUND"
    assert "no policy found" in result.reason.lower()
    assert result.penalty == -15


@pytest.mark.asyncio
async def test_inactive_policy_filtered_out(policy_engine):
    """Inactive metadata rows must be filtered out by the status FilterExpression.

    customer-query-agent has both an active v1.0.0 entry and an inactive v0.9.0
    entry. The query should always return the active one.
    """
    policy = await policy_engine.get_agent_policy("customer-query-agent")
    assert policy["version"] == "1.0.0"
    assert policy["status"] == "active"


@pytest.mark.asyncio
async def test_payment_agent_cannot_invoke_others(policy_engine, sample_request):
    sample_request.agent_id = "payment-agent"
    sample_request.tool_name = "invoke_agent"
    sample_request.tool_params = {"agent_id": "customer-query-agent"}
    result = await policy_engine.validate(sample_request)
    assert result.decision == "DENY"
    assert result.should_deny is True
    assert result.violation_type == "UNAUTHORIZED_AGENT_INVOCATION"


@pytest.mark.asyncio
async def test_payment_agent_authorized_tools(policy_engine, sample_request):
    sample_request.agent_id = "payment-agent"

    sample_request.tool_name = "check_order"
    assert (await policy_engine.validate(sample_request)).decision == "ALLOW"

    sample_request.tool_name = "process_refund"
    assert (await policy_engine.validate(sample_request)).decision == "ALLOW"

    sample_request.tool_name = "reverse_refund"
    assert (await policy_engine.validate(sample_request)).decision == "ALLOW"


@pytest.mark.asyncio
async def test_get_agent_policy_returns_correct_policy(policy_engine):
    policy = await policy_engine.get_agent_policy("customer-query-agent")
    assert policy["agent_id"] == "customer-query-agent"
    assert policy["status"] == "active"
    assert "query_customers" in policy["allowed_tools"]
    assert "payment-agent" in policy["allowed_agents"]
    assert policy["max_calls_per_minute"] == 30
    # Workstream 15: cross-cloud fields present in the loaded policy
    assert policy["platform"] == "bedrock"
    assert policy["cloud_region"] == "us-east-1"


@pytest.mark.asyncio
async def test_error_handling_returns_deny(policy_engine, sample_request):
    """If the metadata table reference is broken, the engine fails secure (DENY).

    Rewritten from the legacy `policy_engine.table = None` pattern (which targeted
    an attribute that no longer exists) to point at the actual production attribute
    `metadata_table`.
    """
    policy_engine.metadata_table = None
    result = await policy_engine.validate(sample_request)
    assert result.decision == "DENY"
    assert result.should_deny is True
    assert result.violation_type in ["POLICY_NOT_FOUND", "POLICY_ERROR"]
