"""
Unit Tests for Cross-Agent Validator

Tests cross-agent call validation including:
- Call depth limits
- Caller authorization (allowed_callers)
- Non-cross-agent calls (skip validation)

Coverage target: >90%
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.validators.cross_agent_validator import CrossAgentValidator
from app.api.models import ValidationRequest


@pytest.fixture
def validator():
    """Create CrossAgentValidator with mocked policy engine"""
    with patch('app.validators.policy_engine.PolicyEngine') as MockPolicyEngine:
        mock_policy_engine = MagicMock()
        MockPolicyEngine.return_value = mock_policy_engine
        validator = CrossAgentValidator()
        validator.policy_engine = mock_policy_engine
        yield validator


@pytest.fixture
def base_request():
    """Base validation request without cross-agent context"""
    return ValidationRequest(
        request_id="req-test-001",
        session_id="sess-test-001",
        agent_id="payment-agent",
        tool_name="process_refund",
        tool_params={"order_id": "ORD-123", "amount": 100},
        user_input="Process refund for order 123",
        timestamp="2025-01-01T00:00:00Z",
        operation_type="WRITE",
        context={
            "user_id": "test@sentra.com",
            "authorization_level": "manager"
        }
    )


@pytest.fixture
def cross_agent_request():
    """Validation request with cross-agent context (called by another agent)"""
    return ValidationRequest(
        request_id="req-test-002",
        session_id="sess-test-001",
        agent_id="payment-agent",
        tool_name="process_refund",
        tool_params={"order_id": "ORD-123", "amount": 100},
        user_input="Process refund for order 123",
        timestamp="2025-01-01T00:00:00Z",
        operation_type="WRITE",
        context={
            "user_id": "test@sentra.com",
            "authorization_level": "manager",
            "conversation_id": "conv-abc123",
            "parent_request_id": "req-parent-001",
            "caller_agent_id": "customer-query-agent",
            "call_depth": 1
        }
    )


# ==================== Non-Cross-Agent Call Tests ====================

@pytest.mark.asyncio
async def test_skip_validation_no_caller(validator, base_request):
    """Test that validation is skipped when no caller_agent_id"""
    result = await validator.validate(base_request)
    
    assert result.decision == "ALLOW"
    assert result.reason == "Not a cross-agent call"
    assert result.should_deny is False


@pytest.mark.asyncio
async def test_skip_validation_no_parent_request(validator):
    """Test that validation is skipped when no parent_request_id"""
    request = ValidationRequest(
        request_id="req-test-001",
        session_id="sess-test-001",
        agent_id="payment-agent",
        tool_name="process_refund",
        tool_params={},
        user_input="Test",
        timestamp="2025-01-01T00:00:00Z",
        operation_type="WRITE",
        context={
            "caller_agent_id": "customer-query-agent",
            # No parent_request_id
        }
    )
    
    result = await validator.validate(request)
    
    assert result.decision == "ALLOW"
    assert result.should_deny is False


# ==================== Call Depth Tests ====================

@pytest.mark.asyncio
async def test_call_depth_within_limit(validator, cross_agent_request):
    """Test that call depth within limit is allowed"""
    # Mock policy with open allowed_callers
    validator.policy_engine.get_agent_policy = AsyncMock(return_value={
        "allowed_callers": []  # Empty = allow all
    })
    
    cross_agent_request.context["call_depth"] = 3
    result = await validator.validate(cross_agent_request)
    
    assert result.decision == "ALLOW"
    assert result.should_deny is False


@pytest.mark.asyncio
async def test_call_depth_at_limit(validator, cross_agent_request):
    """Test that call depth at exactly MAX_CALL_DEPTH is allowed"""
    validator.policy_engine.get_agent_policy = AsyncMock(return_value={
        "allowed_callers": []
    })
    
    cross_agent_request.context["call_depth"] = 5  # MAX_CALL_DEPTH
    result = await validator.validate(cross_agent_request)
    
    assert result.decision == "ALLOW"
    assert result.should_deny is False


@pytest.mark.asyncio
async def test_call_depth_exceeded(validator, cross_agent_request):
    """Test that call depth exceeding limit is denied"""
    cross_agent_request.context["call_depth"] = 6  # > MAX_CALL_DEPTH
    
    result = await validator.validate(cross_agent_request)
    
    assert result.decision == "DENY"
    assert result.should_deny is True
    assert result.violation_type == "MAX_CALL_DEPTH_EXCEEDED"
    assert "6 > 5" in result.reason


@pytest.mark.asyncio
async def test_call_depth_way_exceeded(validator, cross_agent_request):
    """Test that very high call depth is denied"""
    cross_agent_request.context["call_depth"] = 100
    
    result = await validator.validate(cross_agent_request)
    
    assert result.decision == "DENY"
    assert result.violation_type == "MAX_CALL_DEPTH_EXCEEDED"


# ==================== Caller Authorization Tests ====================

@pytest.mark.asyncio
async def test_caller_authorized(validator, cross_agent_request):
    """Test that authorized caller is allowed"""
    validator.policy_engine.get_agent_policy = AsyncMock(return_value={
        "allowed_callers": ["customer-query-agent", "admin-agent"]
    })
    
    result = await validator.validate(cross_agent_request)
    
    assert result.decision == "ALLOW"
    assert result.reason == "Cross-agent call authorized"
    assert result.should_deny is False


@pytest.mark.asyncio
async def test_caller_not_authorized(validator, cross_agent_request):
    """Test that unauthorized caller is denied"""
    validator.policy_engine.get_agent_policy = AsyncMock(return_value={
        "allowed_callers": ["admin-agent", "internal-agent"]  # CQA not in list
    })
    
    result = await validator.validate(cross_agent_request)
    
    assert result.decision == "DENY"
    assert result.should_deny is True
    assert result.violation_type == "UNAUTHORIZED_CROSS_AGENT_CALL"
    assert "customer-query-agent" in result.reason
    assert "payment-agent" in result.reason


@pytest.mark.asyncio
async def test_open_policy_empty_allowed_callers(validator, cross_agent_request):
    """Test that empty allowed_callers list allows any caller (backward compatible)"""
    validator.policy_engine.get_agent_policy = AsyncMock(return_value={
        "allowed_callers": []  # Empty = open policy
    })
    
    result = await validator.validate(cross_agent_request)
    
    assert result.decision == "ALLOW"
    assert "open policy" in result.reason


@pytest.mark.asyncio
async def test_open_policy_no_allowed_callers_field(validator, cross_agent_request):
    """Test that missing allowed_callers field allows any caller"""
    validator.policy_engine.get_agent_policy = AsyncMock(return_value={
        # No allowed_callers field at all
        "allowed_tools": ["process_refund"]
    })
    
    result = await validator.validate(cross_agent_request)
    
    assert result.decision == "ALLOW"
    assert "open policy" in result.reason


@pytest.mark.asyncio
async def test_wildcard_allows_any_caller(validator, cross_agent_request):
    """Test that wildcard '*' in allowed_callers allows any caller"""
    validator.policy_engine.get_agent_policy = AsyncMock(return_value={
        "allowed_callers": ["*"]
    })
    
    result = await validator.validate(cross_agent_request)
    
    assert result.decision == "ALLOW"
    assert result.should_deny is False


# ==================== Policy Load Error Tests ====================

@pytest.mark.asyncio
async def test_policy_load_error(validator, cross_agent_request):
    """Test that policy load error results in DENY"""
    validator.policy_engine.get_agent_policy = AsyncMock(
        side_effect=Exception("DynamoDB connection failed")
    )
    
    result = await validator.validate(cross_agent_request)
    
    assert result.decision == "DENY"
    assert result.should_deny is True
    assert result.violation_type == "POLICY_LOAD_ERROR"


# ==================== Edge Cases ====================

@pytest.mark.asyncio
async def test_call_depth_zero(validator, cross_agent_request):
    """Test that call_depth 0 is valid for cross-agent call"""
    validator.policy_engine.get_agent_policy = AsyncMock(return_value={
        "allowed_callers": ["customer-query-agent"]
    })
    
    cross_agent_request.context["call_depth"] = 0
    result = await validator.validate(cross_agent_request)
    
    assert result.decision == "ALLOW"


@pytest.mark.asyncio
async def test_empty_context(validator):
    """Test request with empty context"""
    request = ValidationRequest(
        request_id="req-test-001",
        session_id="sess-test-001",
        agent_id="payment-agent",
        tool_name="process_refund",
        tool_params={},
        user_input="Test",
        timestamp="2025-01-01T00:00:00Z",
        operation_type="WRITE",
        context={}
    )
    
    result = await validator.validate(request)
    
    assert result.decision == "ALLOW"
    assert result.reason == "Not a cross-agent call"


@pytest.mark.asyncio
async def test_none_context(validator):
    """Test request with None context"""
    request = ValidationRequest(
        request_id="req-test-001",
        session_id="sess-test-001",
        agent_id="payment-agent",
        tool_name="process_refund",
        tool_params={},
        user_input="Test",
        timestamp="2025-01-01T00:00:00Z",
        operation_type="WRITE",
        context=None
    )
    
    result = await validator.validate(request)
    
    assert result.decision == "ALLOW"
    assert result.reason == "Not a cross-agent call"
