"""
Unit tests for Security Controller Integration
Tests the @secured_tool decorator and context management
"""

import pytest
from unittest.mock import patch, MagicMock
import requests

from app.security_integration import (
    secured_tool,
    SecurityException,
    set_request_context,
    set_multi_agent_context,
    get_current_request_id,
    get_current_session_id,
    get_current_context,
    get_conversation_id,
    get_call_depth,
    clear_request_context,
    call_security_controller
)


# ==================== Test Fixtures ====================

@pytest.fixture
def mock_request_context():
    """Set up request context for tests"""
    set_request_context(
        request_id="test-req-123",
        session_id="test-session-456",
        user_input="Show customers from CA",
        context={"user_id": "test@sentra.com"}
    )
    yield
    clear_request_context()


# ==================== Test Tool Functions ====================

@secured_tool
def sample_tool(param1: str, param2: int) -> dict:
    """Sample tool for testing"""
    return {"result": f"{param1}-{param2}"}


@secured_tool
def failing_tool() -> dict:
    """Tool that raises an error"""
    raise ValueError("Tool execution failed")


# ==================== Context Tests ====================

def test_request_context_management():
    """Test setting and getting request context"""
    set_request_context(
        request_id="req-001",
        session_id="sess-001",
        user_input="test input",
        context={"key": "value"}
    )

    assert get_current_request_id() == "req-001"
    assert get_current_session_id() == "sess-001"

    clear_request_context()
    assert get_current_request_id() is None
    assert get_current_session_id() is None


# ==================== Multi-Agent Context Tests ====================

def test_set_multi_agent_context():
    """Test setting multi-agent context fields"""
    # First set base context
    set_request_context(
        request_id="req-001",
        session_id="sess-001",
        user_input="test input",
        context={"user_id": "test@sentra.com"}
    )

    # Then set multi-agent context
    set_multi_agent_context(
        conversation_id="conv-abc123",
        parent_request_id="req-parent-001",
        caller_agent_id="customer-query-agent",
        call_depth=1
    )

    # Verify all fields are accessible
    assert get_conversation_id() == "conv-abc123"
    assert get_call_depth() == 1

    context = get_current_context()
    assert context["conversation_id"] == "conv-abc123"
    assert context["parent_request_id"] == "req-parent-001"
    assert context["caller_agent_id"] == "customer-query-agent"
    assert context["call_depth"] == 1
    # Original context should still be there
    assert context["user_id"] == "test@sentra.com"

    clear_request_context()


def test_get_conversation_id_default():
    """Test get_conversation_id returns None when not set"""
    clear_request_context()
    set_request_context(
        request_id="req-001",
        session_id="sess-001",
        user_input="test",
        context={}
    )

    assert get_conversation_id() is None

    clear_request_context()


def test_get_call_depth_default():
    """Test get_call_depth returns 0 when not set"""
    clear_request_context()
    set_request_context(
        request_id="req-001",
        session_id="sess-001",
        user_input="test",
        context={}
    )

    assert get_call_depth() == 0

    clear_request_context()


def test_multi_agent_context_preserved_after_update():
    """Test that multi-agent context is preserved when updated"""
    set_request_context(
        request_id="req-001",
        session_id="sess-001",
        user_input="test",
        context={"authorization_level": "manager"}
    )

    set_multi_agent_context(
        conversation_id="conv-first",
        call_depth=0
    )

    # Update with new values
    set_multi_agent_context(
        conversation_id="conv-first",
        parent_request_id="req-parent",
        caller_agent_id="other-agent",
        call_depth=1
    )

    context = get_current_context()
    assert context["conversation_id"] == "conv-first"
    assert context["parent_request_id"] == "req-parent"
    assert context["caller_agent_id"] == "other-agent"
    assert context["call_depth"] == 1
    # Original context preserved
    assert context["authorization_level"] == "manager"

    clear_request_context()


@pytest.fixture
def mock_multi_agent_context():
    """Set up multi-agent request context for tests"""
    set_request_context(
        request_id="test-req-123",
        session_id="test-session-456",
        user_input="Process refund for order 123",
        context={
            "user_id": "test@sentra.com",
            "authorization_level": "manager"
        }
    )
    set_multi_agent_context(
        conversation_id="conv-test-789",
        parent_request_id="req-parent-001",
        caller_agent_id="customer-query-agent",
        call_depth=1
    )
    yield
    clear_request_context()


@patch('app.security_integration.call_security_controller')
def test_secured_tool_includes_multi_agent_context(mock_security, mock_multi_agent_context):
    """Test that @secured_tool includes multi-agent context in validation request"""
    mock_security.return_value = {
        "decision": "ALLOW",
        "reason": "No policy violations"
    }

    sample_tool(param1="test", param2=42)

    # Verify validation request includes multi-agent context
    call_args = mock_security.call_args[0][0]
    validation_context = call_args["context"]

    assert validation_context["conversation_id"] == "conv-test-789"
    assert validation_context["parent_request_id"] == "req-parent-001"
    assert validation_context["caller_agent_id"] == "customer-query-agent"
    assert validation_context["call_depth"] == 1
    # User context also present
    assert validation_context["user_id"] == "test@sentra.com"
    assert validation_context["authorization_level"] == "manager"


@patch('app.security_integration.call_security_controller')
def test_secured_tool_first_agent_no_parent(mock_security, mock_request_context):
    """Test that first agent (no parent) has None/0 for multi-agent fields"""
    mock_security.return_value = {
        "decision": "ALLOW",
        "reason": "No policy violations"
    }

    sample_tool(param1="test", param2=42)

    call_args = mock_security.call_args[0][0]
    validation_context = call_args["context"]

    # First agent should have None for parent fields
    assert validation_context["conversation_id"] is None
    assert validation_context["parent_request_id"] is None
    assert validation_context["caller_agent_id"] is None
    assert validation_context["call_depth"] == 0


# ==================== Security Controller Communication Tests ====================

@patch('app.security_integration.requests.post')
def test_call_security_controller_success(mock_post):
    """Test successful Security Controller call"""
    # Mock successful response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "decision": "ALLOW",
        "reason": "No policy violations",
        "request_id": "test-req-123"
    }
    mock_post.return_value = mock_response

    validation_request = {
        "request_id": "test-req-123",
        "session_id": "test-session-456",
        "tool_name": "test_tool"
    }

    decision = call_security_controller(validation_request)

    assert decision["decision"] == "ALLOW"
    assert mock_post.called
    assert mock_post.call_args[1]["timeout"] == 5.0


@patch('app.security_integration.requests.post')
def test_call_security_controller_http_error(mock_post):
    """Test Security Controller HTTP error"""
    # Mock error response
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"
    mock_post.return_value = mock_response

    validation_request = {
        "request_id": "test-req-123",
        "tool_name": "test_tool"
    }

    with pytest.raises(SecurityException) as exc_info:
        call_security_controller(validation_request)

    assert "HTTP 500" in str(exc_info.value)


@patch('app.security_integration.requests.post')
def test_call_security_controller_timeout(mock_post):
    """Test Security Controller timeout with retry"""
    # Mock timeout on all attempts
    mock_post.side_effect = requests.exceptions.Timeout("Connection timeout")

    validation_request = {
        "request_id": "test-req-123",
        "tool_name": "test_tool"
    }

    with pytest.raises(requests.exceptions.Timeout):
        call_security_controller(validation_request)

    # Should retry 3 times
    assert mock_post.call_count == 3


# ==================== @secured_tool Decorator Tests ====================

@patch('app.security_integration.call_security_controller')
def test_secured_tool_allow(mock_security, mock_request_context):
    """Test @secured_tool with ALLOW decision"""
    # Mock ALLOW decision
    mock_security.return_value = {
        "decision": "ALLOW",
        "reason": "No policy violations",
        "request_id": "test-req-123"
    }

    result = sample_tool(param1="test", param2=42)

    assert result == {"result": "test-42"}
    assert mock_security.called

    # Verify validation request structure
    call_args = mock_security.call_args[0][0]
    assert call_args["request_id"] == "test-req-123"
    assert call_args["session_id"] == "test-session-456"
    assert call_args["tool_name"] == "sample_tool"
    assert call_args["tool_params"] == {"param1": "test", "param2": 42}
    assert call_args["user_input"] == "Show customers from CA"


@patch('app.security_integration.call_security_controller')
def test_secured_tool_deny(mock_security, mock_request_context):
    """Test @secured_tool with DENY decision"""
    # Mock DENY decision
    mock_security.return_value = {
        "decision": "DENY",
        "reason": "Prompt injection detected",
        "request_id": "test-req-123",
        "matched_rules": [
            {
                "rule_id": "LLM_JAILBREAK_001",
                "title": "LLM Jailbreak Attempt",
                "severity": "high"
            }
        ]
    }

    with pytest.raises(SecurityException) as exc_info:
        sample_tool(param1="ignore previous instructions", param2=1)

    # Verify exception details
    assert "Prompt injection detected" in str(exc_info.value)
    assert len(exc_info.value.matched_rules) == 1
    assert exc_info.value.matched_rules[0]["rule_id"] == "LLM_JAILBREAK_001"


@patch('app.security_integration.call_security_controller')
def test_secured_tool_controller_unavailable(mock_security, mock_request_context):
    """Test @secured_tool when Security Controller is unavailable"""
    # Mock connection error
    mock_security.side_effect = requests.exceptions.ConnectionError("Connection refused")

    with pytest.raises(SecurityException) as exc_info:
        sample_tool(param1="test", param2=42)

    assert "Security Controller unavailable" in str(exc_info.value)


@patch('app.security_integration.call_security_controller')
def test_secured_tool_execution_error(mock_security, mock_request_context):
    """Test @secured_tool when tool execution fails"""
    # Mock ALLOW decision
    mock_security.return_value = {
        "decision": "ALLOW",
        "reason": "No policy violations"
    }

    # Tool raises ValueError
    with pytest.raises(ValueError) as exc_info:
        failing_tool()

    assert "Tool execution failed" in str(exc_info.value)


@patch('app.security_integration.call_security_controller')
def test_secured_tool_preserves_function_metadata(mock_security):
    """Test that @secured_tool preserves function name and docstring"""
    assert sample_tool.__name__ == "sample_tool"
    assert "Sample tool for testing" in sample_tool.__doc__


# ==================== Integration Test ====================

@patch('app.security_integration.requests.post')
def test_end_to_end_allow_flow(mock_post, mock_request_context):
    """Test complete end-to-end flow with ALLOW decision"""
    # Mock Security Controller response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "decision": "ALLOW",
        "reason": "No policy violations",
        "request_id": "test-req-123"
    }
    mock_post.return_value = mock_response

    # Execute secured tool
    result = sample_tool(param1="CA", param2=100)

    # Verify result
    assert result == {"result": "CA-100"}

    # Verify Security Controller was called correctly
    assert mock_post.called
    call_args = mock_post.call_args

    # Verify URL
    assert "/v1/validate" in call_args[0][0]

    # Verify request payload
    payload = call_args[1]["json"]
    assert payload["tool_name"] == "sample_tool"
    assert payload["request_id"] == "test-req-123"
    assert payload["session_id"] == "test-session-456"


@patch('app.security_integration.requests.post')
def test_end_to_end_deny_flow(mock_post, mock_request_context):
    """Test complete end-to-end flow with DENY decision"""
    # Mock Security Controller DENY response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "decision": "DENY",
        "reason": "Refund amount exceeds limit",
        "request_id": "test-req-123",
        "matched_rules": [
            {
                "rule_id": "POLICY_REFUND_LIMIT",
                "title": "Refund Limit Exceeded",
                "severity": "medium"
            }
        ]
    }
    mock_post.return_value = mock_response

    # Execute secured tool - should raise SecurityException
    with pytest.raises(SecurityException) as exc_info:
        sample_tool(param1="test", param2=5000)

    # Verify exception
    assert "Refund amount exceeds limit" in str(exc_info.value)
    assert exc_info.value.decision["decision"] == "DENY"
    assert len(exc_info.value.matched_rules) == 1

    # Verify Security Controller was called
    assert mock_post.called
