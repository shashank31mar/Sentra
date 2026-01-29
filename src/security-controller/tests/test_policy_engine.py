"""
Unit Tests for Policy Engine

Tests agent authorization and tool permission validation.
Uses moto to mock DynamoDB.
Coverage target: >80%
"""
import pytest
from moto import mock_aws
import boto3
from app.validators.policy_engine import PolicyEngine, PolicyNotFoundError
from app.api.models import ValidationRequest
from app.config import settings


@pytest.fixture
def aws_credentials(monkeypatch):
    """Mock AWS credentials for moto"""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")


@pytest.fixture
def dynamodb_table(aws_credentials):
    """Create mock DynamoDB table with policies"""
    with mock_aws():
        # Create table
        dynamodb = boto3.resource('dynamodb', region_name=settings.aws_region)
        table = dynamodb.create_table(
            TableName=settings.dynamodb_policies_table,
            KeySchema=[
                {'AttributeName': 'policy_id', 'KeyType': 'HASH'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'policy_id', 'AttributeType': 'S'},
                {'AttributeName': 'agent_id', 'AttributeType': 'S'},
                {'AttributeName': 'version', 'AttributeType': 'S'}
            ],
            GlobalSecondaryIndexes=[
                {
                    'IndexName': 'agent-version-index',
                    'KeySchema': [
                        {'AttributeName': 'agent_id', 'KeyType': 'HASH'},
                        {'AttributeName': 'version', 'KeyType': 'RANGE'}
                    ],
                    'Projection': {'ProjectionType': 'ALL'},
                    'ProvisionedThroughput': {
                        'ReadCapacityUnits': 5,
                        'WriteCapacityUnits': 5
                    }
                }
            ],
            BillingMode='PAY_PER_REQUEST'
        )
        
        # Add test policies
        table.put_item(Item={
            'policy_id': 'pol-customer-query-001',
            'agent_id': 'customer-query-agent',
            'version': '1.0',
            'is_active': True,
            'allowed_tools': ['query_customers', 'query_orders', 'query_with_limit', 'invoke_agent'],
            'allowed_agents': ['payment-agent'],
            'max_calls_per_minute': 30
        })
        
        table.put_item(Item={
            'policy_id': 'pol-payment-001',
            'agent_id': 'payment-agent',
            'version': '1.0',
            'is_active': True,
            'allowed_tools': ['check_order', 'process_refund', 'reverse_refund', 'invoke_agent'],
            'allowed_agents': [],
            'max_calls_per_minute': 15
        })
        
        # Inactive policy (should not be loaded)
        table.put_item(Item={
            'policy_id': 'pol-old-001',
            'agent_id': 'customer-query-agent',
            'version': '0.9',
            'is_active': False,
            'allowed_tools': ['old_tool'],
            'allowed_agents': [],
            'max_calls_per_minute': 10
        })
        
        yield table


@pytest.fixture
def policy_engine(dynamodb_table):
    """Create PolicyEngine instance with mocked DynamoDB"""
    return PolicyEngine()


@pytest.fixture
def sample_request():
    """Create sample validation request"""
    return ValidationRequest(
        request_id="req-test-123",
        session_id="sess-test-789",
        agent_id="customer-query-agent",
        tool_name="query_customers",
        tool_params={},
        user_input="test input",
        timestamp="2025-01-18T10:00:00Z",
        operation_type="READ"
    )


@pytest.mark.asyncio
async def test_authorized_tool_returns_allow(policy_engine, sample_request):
    """Test: Authorized tool (query_customers in allowed_tools) returns ALLOW"""
    result = await policy_engine.validate(sample_request)
    
    assert result.decision == "ALLOW"
    assert result.should_deny is False
    assert "passed" in result.reason.lower()


@pytest.mark.asyncio
async def test_unauthorized_tool_returns_deny(policy_engine, sample_request):
    """Test: Unauthorized tool (process_refund NOT in allowed_tools) returns DENY"""
    sample_request.tool_name = "process_refund"
    
    result = await policy_engine.validate(sample_request)
    
    assert result.decision == "DENY"
    assert result.should_deny is True
    assert result.violation_type == "UNAUTHORIZED_TOOL"
    assert "not authorized" in result.reason.lower()
    assert result.penalty == -15


@pytest.mark.asyncio
async def test_authorized_agent_invocation_returns_allow(policy_engine, sample_request):
    """Test: Authorized agent invocation returns ALLOW"""
    sample_request.tool_name = "invoke_agent"
    sample_request.tool_params = {"agent_id": "payment-agent"}
    
    result = await policy_engine.validate(sample_request)
    
    assert result.decision == "ALLOW"
    assert result.should_deny is False


@pytest.mark.asyncio
async def test_unauthorized_agent_invocation_returns_deny(policy_engine, sample_request):
    """Test: Unauthorized agent invocation returns DENY"""
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
    """Test: invoke_agent without target agent_id returns DENY"""
    sample_request.tool_name = "invoke_agent"
    sample_request.tool_params = {}  # Missing agent_id
    
    result = await policy_engine.validate(sample_request)
    
    assert result.decision == "DENY"
    assert result.should_deny is True
    assert result.violation_type == "INVALID_AGENT_INVOCATION"
    assert "requires target agent_id" in result.reason.lower()


@pytest.mark.asyncio
async def test_missing_policy_returns_deny(policy_engine, sample_request):
    """Test: Missing policy (agent_id not found) returns DENY (fail-secure)"""
    sample_request.agent_id = "nonexistent-agent"
    
    result = await policy_engine.validate(sample_request)
    
    assert result.decision == "DENY"
    assert result.should_deny is True
    assert result.violation_type == "POLICY_NOT_FOUND"
    assert "no policy found" in result.reason.lower()
    assert result.penalty == -15


@pytest.mark.asyncio
async def test_inactive_policy_not_loaded(policy_engine):
    """Test: Inactive policies are not loaded"""
    # Try to get inactive policy
    with pytest.raises(PolicyNotFoundError):
        await policy_engine.get_agent_policy("customer-query-agent-old")


@pytest.mark.asyncio
async def test_payment_agent_cannot_invoke_others(policy_engine, sample_request):
    """Test: Payment agent (leaf agent) cannot invoke other agents"""
    sample_request.agent_id = "payment-agent"
    sample_request.tool_name = "invoke_agent"
    sample_request.tool_params = {"agent_id": "customer-query-agent"}
    
    result = await policy_engine.validate(sample_request)
    
    assert result.decision == "DENY"
    assert result.should_deny is True
    assert result.violation_type == "UNAUTHORIZED_AGENT_INVOCATION"


@pytest.mark.asyncio
async def test_payment_agent_authorized_tools(policy_engine, sample_request):
    """Test: Payment agent can use its authorized tools"""
    sample_request.agent_id = "payment-agent"
    
    # Test check_order
    sample_request.tool_name = "check_order"
    result = await policy_engine.validate(sample_request)
    assert result.decision == "ALLOW"
    
    # Test process_refund
    sample_request.tool_name = "process_refund"
    result = await policy_engine.validate(sample_request)
    assert result.decision == "ALLOW"
    
    # Test reverse_refund
    sample_request.tool_name = "reverse_refund"
    result = await policy_engine.validate(sample_request)
    assert result.decision == "ALLOW"


@pytest.mark.asyncio
async def test_get_agent_policy_returns_correct_policy(policy_engine):
    """Test: get_agent_policy returns correct policy for agent"""
    policy = await policy_engine.get_agent_policy("customer-query-agent")
    
    assert policy['agent_id'] == "customer-query-agent"
    assert policy['is_active'] is True
    assert 'query_customers' in policy['allowed_tools']
    assert 'payment-agent' in policy['allowed_agents']
    assert policy['max_calls_per_minute'] == 30


@pytest.mark.asyncio
async def test_error_handling_returns_deny(policy_engine, sample_request):
    """Test: Error handling returns DENY on exceptions (fail-secure)"""
    # Force an error by setting table to None
    policy_engine.table = None
    
    result = await policy_engine.validate(sample_request)
    
    assert result.decision == "DENY"
    assert result.should_deny is True
    # Will be POLICY_NOT_FOUND since get_agent_policy raises PolicyNotFoundError
    assert result.violation_type in ["POLICY_NOT_FOUND", "POLICY_ERROR"]
