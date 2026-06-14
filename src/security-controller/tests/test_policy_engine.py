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


# --- CT11: legacy per-tool authorization REMOVED -----------------------------
# The hardcoded checks (allowed_tools, refund cap, fraud gate, invoke_agent) that
# validate() used to run were removed when CedarPolicyEngine became authoritative.
# Those ALLOW/DENY behaviors are now covered by test_cedar_policy_engine.py.
# validate() is a fail-secure floor, reached only via the cedar-disabled/abstain
# paths — so for a loadable policy it now DENYs with POLICY_ERROR.

@pytest.mark.asyncio
async def test_validate_is_fail_secure_after_cedar_cutover(policy_engine, sample_request):
    """A loadable policy (pre-CT11 this returned ALLOW) now fails secure: the
    legacy authorization engine is retired, Cedar is authoritative."""
    result = await policy_engine.validate(sample_request)
    assert result.decision == "DENY"
    assert result.should_deny is True
    assert result.violation_type == "POLICY_ERROR"
    assert "retired" in result.reason.lower()
    # Cloud identity still stamped for the audit log.
    assert result.platform == "bedrock"
    assert result.cloud_region == "us-east-1"


@pytest.mark.asyncio
async def test_validate_fail_secure_regardless_of_tool(policy_engine, sample_request):
    """No tool-specific path remains — every tool/param shape fail-secure DENYs."""
    for tool, params in [
        ("process_refund", {"amount": 1}),
        ("invoke_agent", {"agent_id": "payment-agent"}),
        ("invoke_agent", {}),
    ]:
        sample_request.tool_name = tool
        sample_request.tool_params = params
        result = await policy_engine.validate(sample_request)
        assert result.decision == "DENY"
        assert result.violation_type == "POLICY_ERROR"


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
    """If the policies-metadata table is broken, the engine fails secure (DENY).

    `metadata_table` / `agent_registry` are now flag-aware PROPERTIES (resolved
    via the tenancy helper, workstream T5/T7), so the test breaks the backend
    instead of reassigning the attribute: the registry read still works (cloud
    identity resolves) while the policies-metadata query raises a ClientError —
    exactly the production failure mode that must DENY.
    """
    from unittest.mock import Mock
    from botocore.exceptions import ClientError

    err = ClientError({"Error": {"Code": "InternalError", "Message": "boom"}}, "Query")
    broken = Mock()
    broken.query.side_effect = err
    broken.get_item.side_effect = err
    working_registry = Mock()
    working_registry.get_item.return_value = {}  # agent not found → GSI fallback path

    def _table(name):
        return broken if "policies-metadata" in name else working_registry

    policy_engine.dynamodb = Mock()
    policy_engine.dynamodb.Table.side_effect = _table

    result = await policy_engine.validate(sample_request)
    assert result.decision == "DENY"
    assert result.should_deny is True
    assert result.violation_type in ["POLICY_NOT_FOUND", "POLICY_ERROR"]
