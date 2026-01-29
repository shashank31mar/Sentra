"""
Unit Tests for Conversation Service

Tests conversation timeline building and statistics calculation.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.conversation_service import ConversationService


@pytest.fixture
def conversation_service():
    """Create ConversationService with mocked audit logger"""
    with patch('app.services.conversation_service.AuditLogger') as MockAuditLogger:
        mock_audit_logger = MagicMock()
        MockAuditLogger.return_value = mock_audit_logger
        service = ConversationService()
        service.audit_logger = mock_audit_logger
        yield service


@pytest.fixture
def sample_logs():
    """Sample audit logs for a multi-agent conversation"""
    return [
        {
            "request_id": "req-cqa-001",
            "session_id": "sess-001",
            "agent_id": "customer-query-agent",
            "tool_name": "call_payment_agent",
            "decision": "ALLOW",
            "timestamp": "2025-01-01T00:00:00Z",
            "multi_agent_context": {
                "conversation_id": "conv-abc123",
                "parent_request_id": None,
                "caller_agent_id": None,
                "call_depth": 0
            }
        },
        {
            "request_id": "req-pay-001",
            "session_id": "sess-001",
            "agent_id": "payment-agent",
            "tool_name": "process_refund",
            "decision": "ALLOW",
            "timestamp": "2025-01-01T00:00:01Z",
            "multi_agent_context": {
                "conversation_id": "conv-abc123",
                "parent_request_id": "req-cqa-001",
                "caller_agent_id": "customer-query-agent",
                "call_depth": 1
            }
        }
    ]


# ==================== Timeline Building Tests ====================

@pytest.mark.asyncio
async def test_get_timeline_success(conversation_service, sample_logs):
    """Test getting timeline for a conversation"""
    conversation_service.audit_logger.query_logs_by_conversation = AsyncMock(
        return_value=sample_logs
    )

    result = await conversation_service.get_timeline("conv-abc123")

    assert result["conversation_id"] == "conv-abc123"
    assert result["total_requests"] == 2
    assert len(result["timeline"]) == 1  # One root request

    # Verify hierarchy
    root = result["timeline"][0]
    assert root["request_id"] == "req-cqa-001"
    assert root["agent_id"] == "customer-query-agent"
    assert len(root["children"]) == 1

    child = root["children"][0]
    assert child["request_id"] == "req-pay-001"
    assert child["agent_id"] == "payment-agent"


@pytest.mark.asyncio
async def test_get_timeline_empty(conversation_service):
    """Test getting timeline when no logs found"""
    conversation_service.audit_logger.query_logs_by_conversation = AsyncMock(
        return_value=[]
    )

    result = await conversation_service.get_timeline("conv-nonexistent")

    assert result["conversation_id"] == "conv-nonexistent"
    assert result["total_requests"] == 0
    assert result["timeline"] == []
    assert result["statistics"]["total_allowed"] == 0
    assert result["statistics"]["total_denied"] == 0


@pytest.mark.asyncio
async def test_get_timeline_multiple_roots(conversation_service):
    """Test timeline with multiple root requests (parallel calls)"""
    logs = [
        {
            "request_id": "req-001",
            "agent_id": "agent-a",
            "tool_name": "tool_a",
            "decision": "ALLOW",
            "timestamp": "2025-01-01T00:00:00Z",
            "multi_agent_context": {
                "conversation_id": "conv-123",
                "parent_request_id": None,
                "call_depth": 0
            }
        },
        {
            "request_id": "req-002",
            "agent_id": "agent-b",
            "tool_name": "tool_b",
            "decision": "ALLOW",
            "timestamp": "2025-01-01T00:00:01Z",
            "multi_agent_context": {
                "conversation_id": "conv-123",
                "parent_request_id": None,
                "call_depth": 0
            }
        }
    ]

    conversation_service.audit_logger.query_logs_by_conversation = AsyncMock(
        return_value=logs
    )

    result = await conversation_service.get_timeline("conv-123")

    assert result["total_requests"] == 2
    assert len(result["timeline"]) == 2  # Two root requests


@pytest.mark.asyncio
async def test_get_timeline_deep_hierarchy(conversation_service):
    """Test timeline with deep call hierarchy (3 levels)"""
    logs = [
        {
            "request_id": "req-level-0",
            "agent_id": "agent-a",
            "tool_name": "call_b",
            "decision": "ALLOW",
            "timestamp": "2025-01-01T00:00:00Z",
            "multi_agent_context": {
                "conversation_id": "conv-deep",
                "parent_request_id": None,
                "call_depth": 0
            }
        },
        {
            "request_id": "req-level-1",
            "agent_id": "agent-b",
            "tool_name": "call_c",
            "decision": "ALLOW",
            "timestamp": "2025-01-01T00:00:01Z",
            "multi_agent_context": {
                "conversation_id": "conv-deep",
                "parent_request_id": "req-level-0",
                "call_depth": 1
            }
        },
        {
            "request_id": "req-level-2",
            "agent_id": "agent-c",
            "tool_name": "final_action",
            "decision": "ALLOW",
            "timestamp": "2025-01-01T00:00:02Z",
            "multi_agent_context": {
                "conversation_id": "conv-deep",
                "parent_request_id": "req-level-1",
                "call_depth": 2
            }
        }
    ]

    conversation_service.audit_logger.query_logs_by_conversation = AsyncMock(
        return_value=logs
    )

    result = await conversation_service.get_timeline("conv-deep")

    assert result["total_requests"] == 3
    assert len(result["timeline"]) == 1  # One root

    # Verify 3-level hierarchy
    root = result["timeline"][0]
    assert root["request_id"] == "req-level-0"
    assert len(root["children"]) == 1

    level1 = root["children"][0]
    assert level1["request_id"] == "req-level-1"
    assert len(level1["children"]) == 1

    level2 = level1["children"][0]
    assert level2["request_id"] == "req-level-2"
    assert len(level2["children"]) == 0


# ==================== Statistics Tests ====================

@pytest.mark.asyncio
async def test_statistics_calculation(conversation_service, sample_logs):
    """Test statistics calculation"""
    conversation_service.audit_logger.query_logs_by_conversation = AsyncMock(
        return_value=sample_logs
    )

    result = await conversation_service.get_timeline("conv-abc123")

    stats = result["statistics"]
    assert stats["total_allowed"] == 2
    assert stats["total_denied"] == 0
    assert "customer-query-agent" in stats["agents_involved"]
    assert "payment-agent" in stats["agents_involved"]
    assert stats["max_call_depth"] == 1


@pytest.mark.asyncio
async def test_statistics_with_denials(conversation_service):
    """Test statistics with DENY decisions"""
    logs = [
        {
            "request_id": "req-001",
            "agent_id": "agent-a",
            "tool_name": "tool_a",
            "decision": "ALLOW",
            "timestamp": "2025-01-01T00:00:00Z",
            "multi_agent_context": {"call_depth": 0}
        },
        {
            "request_id": "req-002",
            "agent_id": "agent-b",
            "tool_name": "tool_b",
            "decision": "DENY",
            "timestamp": "2025-01-01T00:00:01Z",
            "multi_agent_context": {"call_depth": 1}
        },
        {
            "request_id": "req-003",
            "agent_id": "agent-a",
            "tool_name": "tool_c",
            "decision": "DENY",
            "timestamp": "2025-01-01T00:00:02Z",
            "multi_agent_context": {"call_depth": 0}
        }
    ]

    conversation_service.audit_logger.query_logs_by_conversation = AsyncMock(
        return_value=logs
    )

    result = await conversation_service.get_timeline("conv-123")

    stats = result["statistics"]
    assert stats["total_allowed"] == 1
    assert stats["total_denied"] == 2
    assert stats["max_call_depth"] == 1


# ==================== Summary Tests ====================

@pytest.mark.asyncio
async def test_get_conversation_summary(conversation_service, sample_logs):
    """Test getting conversation summary"""
    conversation_service.audit_logger.query_logs_by_conversation = AsyncMock(
        return_value=sample_logs
    )

    result = await conversation_service.get_conversation_summary("conv-abc123")

    assert result is not None
    assert result["conversation_id"] == "conv-abc123"
    assert result["total_requests"] == 2
    assert result["started_at"] == "2025-01-01T00:00:00Z"
    assert result["ended_at"] == "2025-01-01T00:00:01Z"


@pytest.mark.asyncio
async def test_get_conversation_summary_not_found(conversation_service):
    """Test getting summary for non-existent conversation"""
    conversation_service.audit_logger.query_logs_by_conversation = AsyncMock(
        return_value=[]
    )

    result = await conversation_service.get_conversation_summary("conv-nonexistent")

    assert result is None


# ==================== Edge Cases ====================

@pytest.mark.asyncio
async def test_timeline_with_missing_parent(conversation_service):
    """Test timeline when parent_request_id references non-existent request"""
    logs = [
        {
            "request_id": "req-orphan",
            "agent_id": "agent-a",
            "tool_name": "tool_a",
            "decision": "ALLOW",
            "timestamp": "2025-01-01T00:00:00Z",
            "multi_agent_context": {
                "conversation_id": "conv-123",
                "parent_request_id": "req-missing",  # Parent not in logs
                "call_depth": 1
            }
        }
    ]

    conversation_service.audit_logger.query_logs_by_conversation = AsyncMock(
        return_value=logs
    )

    result = await conversation_service.get_timeline("conv-123")

    # Orphan should be treated as root
    assert len(result["timeline"]) == 1
    assert result["timeline"][0]["request_id"] == "req-orphan"


@pytest.mark.asyncio
async def test_timeline_with_empty_multi_agent_context(conversation_service):
    """Test timeline when multi_agent_context is empty"""
    logs = [
        {
            "request_id": "req-001",
            "agent_id": "agent-a",
            "tool_name": "tool_a",
            "decision": "ALLOW",
            "timestamp": "2025-01-01T00:00:00Z",
            "multi_agent_context": {}  # Empty context
        }
    ]

    conversation_service.audit_logger.query_logs_by_conversation = AsyncMock(
        return_value=logs
    )

    result = await conversation_service.get_timeline("conv-123")

    assert len(result["timeline"]) == 1
    assert result["statistics"]["max_call_depth"] == 0
