"""
Unit Tests for Context Validator

Tests tool sequence validation.
Coverage target: >80%
"""
import pytest
import tempfile
import os
from app.validators.context_validator import ContextValidator
from app.api.models import ValidationRequest


@pytest.fixture
def temp_config():
    """Create temporary config file for testing"""
    config_content = """
process_refund:
  requires:
    - check_order

reverse_refund:
  requires:
    - process_refund

complex_tool:
  requires:
    - tool_a
    - tool_b
    - tool_c
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(config_content)
        temp_path = f.name

    yield temp_path

    # Cleanup
    os.unlink(temp_path)


@pytest.fixture
def context_validator(temp_config):
    """Create ContextValidator instance with test config"""
    return ContextValidator(config_path=temp_config)


@pytest.fixture
def sample_request():
    """Create sample validation request"""
    return ValidationRequest(
        request_id="req-test-123",
        session_id="sess-test-789",
        agent_id="test-agent",
        tool_name="process_refund",
        tool_params={"order_id": "ORD-123", "amount": 100},
        user_input="test input",
        timestamp="2025-01-18T10:00:00Z",
        operation_type="WRITE",
    )


@pytest.mark.asyncio
async def test_process_refund_without_check_order_returns_deny(
    context_validator, sample_request
):
    """Test: process_refund without check_order in history returns DENY"""
    session = {
        "session_id": "sess-test-789",
        "tool_history": [
            {"tool_name": "query_customers", "timestamp": 1000},
            {"tool_name": "query_orders", "timestamp": 2000},
        ],
    }

    result = await context_validator.validate_sequence(session, sample_request)

    assert result.decision == "DENY"
    assert result.should_deny is True
    assert result.violation_type == "SEQUENCE_VIOLATION"
    assert "check_order" in result.reason.lower()
    assert result.penalty == -15


@pytest.mark.asyncio
async def test_process_refund_with_check_order_returns_pass(
    context_validator, sample_request
):
    """Test: process_refund with check_order in history returns PASS"""
    session = {
        "session_id": "sess-test-789",
        "tool_history": [
            {"tool_name": "query_customers", "timestamp": 1000},
            {"tool_name": "check_order", "timestamp": 2000},
            {"tool_name": "query_orders", "timestamp": 3000},
        ],
    }

    result = await context_validator.validate_sequence(session, sample_request)

    assert result.decision == "ALLOW"
    assert result.should_deny is False


@pytest.mark.asyncio
async def test_reverse_refund_without_process_refund_returns_deny(
    context_validator, sample_request
):
    """Test: reverse_refund without process_refund returns DENY"""
    sample_request.tool_name = "reverse_refund"

    session = {
        "session_id": "sess-test-789",
        "tool_history": [
            {"tool_name": "check_order", "timestamp": 1000},
            {"tool_name": "query_orders", "timestamp": 2000},
        ],
    }

    result = await context_validator.validate_sequence(session, sample_request)

    assert result.decision == "DENY"
    assert result.should_deny is True
    assert "process_refund" in result.reason.lower()


@pytest.mark.asyncio
async def test_tool_with_no_requirements_always_passes(
    context_validator, sample_request
):
    """Test: Tool with no requirements always returns PASS"""
    sample_request.tool_name = "query_customers"

    session = {"session_id": "sess-test-789", "tool_history": []}

    result = await context_validator.validate_sequence(session, sample_request)

    assert result.decision == "ALLOW"
    assert result.should_deny is False


@pytest.mark.asyncio
async def test_only_last_10_tools_checked(context_validator, sample_request):
    """Test: Only last 10 tools checked (11th tool in history ignored)"""
    # Create history with 15 tools, check_order is at position 0 (11th from end)
    tool_history = [{"tool_name": "check_order", "timestamp": 1000}]
    for i in range(1, 15):
        tool_history.append({"tool_name": f"other_tool_{i}", "timestamp": 1000 + i})

    session = {"session_id": "sess-test-789", "tool_history": tool_history}

    result = await context_validator.validate_sequence(session, sample_request)

    # check_order is at position 0, which is 15th from end
    # Only last 10 are checked, so check_order should NOT be found
    assert result.decision == "DENY"
    assert "check_order" in result.reason.lower()


@pytest.mark.asyncio
async def test_required_tool_in_last_10_passes(context_validator, sample_request):
    """Test: Required tool in last 10 tools passes"""
    # Create history with 15 tools, check_order is at position 5 (10th from end)
    tool_history = []
    for i in range(5):
        tool_history.append({"tool_name": f"other_tool_{i}", "timestamp": 1000 + i})

    tool_history.append({"tool_name": "check_order", "timestamp": 6000})

    for i in range(6, 15):
        tool_history.append({"tool_name": f"other_tool_{i}", "timestamp": 1000 + i})

    session = {"session_id": "sess-test-789", "tool_history": tool_history}

    result = await context_validator.validate_sequence(session, sample_request)

    # check_order is at position 5, which is 10th from end
    # Should be found in last 10
    assert result.decision == "ALLOW"


@pytest.mark.asyncio
async def test_multiple_requirements_all_must_be_present(
    context_validator, sample_request
):
    """Test: Tool with multiple requirements - all must be present"""
    sample_request.tool_name = "complex_tool"

    # Missing tool_c
    session = {
        "session_id": "sess-test-789",
        "tool_history": [
            {"tool_name": "tool_a", "timestamp": 1000},
            {"tool_name": "tool_b", "timestamp": 2000},
        ],
    }

    result = await context_validator.validate_sequence(session, sample_request)
    assert result.decision == "DENY"
    assert "tool_c" in result.reason.lower()

    # All present
    session["tool_history"].append({"tool_name": "tool_c", "timestamp": 3000})
    result = await context_validator.validate_sequence(session, sample_request)
    assert result.decision == "ALLOW"


@pytest.mark.asyncio
async def test_empty_tool_history_denies_required_tools(
    context_validator, sample_request
):
    """Test: Empty tool history denies tools with requirements"""
    session = {"session_id": "sess-test-789", "tool_history": []}

    result = await context_validator.validate_sequence(session, sample_request)

    assert result.decision == "DENY"
    assert result.should_deny is True


@pytest.mark.asyncio
async def test_missing_tool_history_field_denies(context_validator, sample_request):
    """Test: Missing tool_history field denies tools with requirements"""
    session = {"session_id": "sess-test-789"}  # No tool_history field

    result = await context_validator.validate_sequence(session, sample_request)

    assert result.decision == "DENY"
    assert result.should_deny is True


@pytest.mark.asyncio
async def test_error_handling_returns_deny(context_validator, sample_request):
    """Test: Error handling returns DENY on exceptions (fail-secure)"""
    # Pass invalid session (None) to trigger exception
    session = None

    result = await context_validator.validate_sequence(session, sample_request)

    assert result.decision == "DENY"
    assert result.should_deny is True
    assert result.violation_type == "SYSTEM_ERROR"


@pytest.mark.asyncio
async def test_config_file_not_found_uses_empty_requirements():
    """Test: Config file not found uses empty requirements (no errors)"""
    validator = ContextValidator(config_path="/nonexistent/path.yaml")

    assert validator.requirements == {}

    # Should allow all tools since no requirements
    request = ValidationRequest(
        request_id="req-test",
        session_id="sess-test",
        agent_id="test-agent",
        tool_name="any_tool",
        tool_params={},
        user_input="test",
        timestamp="2025-01-18T10:00:00Z",
        operation_type="READ",
    )

    session = {"session_id": "sess-test", "tool_history": []}

    result = await validator.validate_sequence(session, request)
    assert result.decision == "ALLOW"


@pytest.mark.asyncio
async def test_order_not_checked_only_presence(context_validator, sample_request):
    """Test: Order not checked - only presence matters (MVP limitation)"""
    # check_order called AFTER other tools (wrong order)
    # But should still pass because we only check presence
    session = {
        "session_id": "sess-test-789",
        "tool_history": [
            {"tool_name": "query_orders", "timestamp": 1000},
            {"tool_name": "query_customers", "timestamp": 2000},
            {"tool_name": "check_order", "timestamp": 3000},  # Called last
        ],
    }

    result = await context_validator.validate_sequence(session, sample_request)

    # Should pass because check_order is present (order not checked in MVP)
    assert result.decision == "ALLOW"
