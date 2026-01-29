"""
Unit Tests for Rollback Coordinator

Tests the manual rollback functionality for reversible actions.
"""
import pytest
import json
from unittest.mock import Mock, patch, AsyncMock, MagicMock

from app.utils.rollback_coordinator import RollbackCoordinator


@pytest.fixture
def rollback_coordinator():
    """Create RollbackCoordinator with mocked dependencies"""
    with patch('app.utils.rollback_coordinator.boto3') as mock_boto3:
        with patch('app.utils.rollback_coordinator.AuditLogger') as mock_audit_logger_class:
            # Mock CloudWatch Logs client
            mock_logs_client = Mock()
            mock_dynamodb_resource = Mock()
            mock_table = Mock()
            
            # Setup boto3 mocks
            mock_boto3.client.return_value = mock_logs_client
            mock_boto3.resource.return_value = mock_dynamodb_resource
            mock_dynamodb_resource.Table.return_value = mock_table
            
            # Setup AuditLogger mock
            mock_audit_logger = MagicMock()
            mock_audit_logger_class.return_value = mock_audit_logger
            
            coordinator = RollbackCoordinator()
            coordinator.cloudwatch_logs = mock_logs_client
            coordinator.orders_table = mock_table
            coordinator.audit_logger = mock_audit_logger
            
            yield coordinator


@pytest.mark.asyncio
async def test_rollback_unsupported_action_type(rollback_coordinator):
    """Test rollback with unsupported action type"""
    result = await rollback_coordinator.rollback_action(
        action_id="act-unknown-123",
        action_type="unsupported_action",
        reason="Test",
        operator_id="admin@sentra.com"
    )
    
    assert result['success'] is False
    assert 'not reversible' in result['message'].lower()


@pytest.mark.asyncio
async def test_rollback_action_not_found(rollback_coordinator):
    """Test rollback when action doesn't exist in logs"""
    # Mock CloudWatch query returning no results
    rollback_coordinator.cloudwatch_logs.start_query.return_value = {'queryId': 'query-123'}
    rollback_coordinator.cloudwatch_logs.get_query_results.return_value = {
        'status': 'Complete',
        'results': []
    }
    
    result = await rollback_coordinator.rollback_action(
        action_id="act-nonexistent",
        action_type="process_refund",
        reason="Test",
        operator_id="admin@sentra.com"
    )
    
    assert result['success'] is False
    assert 'not found' in result['message'].lower()


@pytest.mark.asyncio
async def test_rollback_already_rolled_back(rollback_coordinator):
    """Test rollback when action already rolled back"""
    # Mock CloudWatch query returning already rolled back action
    log_data = {
        "action_id": "act-refund-123",
        "tool_name": "process_refund",
        "rollback_status": "ROLLED_BACK"
    }
    
    rollback_coordinator.cloudwatch_logs.start_query.return_value = {'queryId': 'query-123'}
    rollback_coordinator.cloudwatch_logs.get_query_results.return_value = {
        'status': 'Complete',
        'results': [[
            {'field': '@message', 'value': json.dumps(log_data)}
        ]]
    }
    
    result = await rollback_coordinator.rollback_action(
        action_id="act-refund-123",
        action_type="process_refund",
        reason="Test",
        operator_id="admin@sentra.com"
    )
    
    assert result['success'] is False
    assert 'already rolled back' in result['message'].lower()


@pytest.mark.asyncio
async def test_rollback_refund_success(rollback_coordinator):
    """Test successful refund rollback"""
    # Mock CloudWatch query returning valid action
    log_data = {
        "action_id": "act-refund-123",
        "tool_name": "process_refund",
        "tool_params": {"order_id": "ORD-123", "amount": 5000},
        "reversible": True,
        "rollback_status": "NOT_ROLLED_BACK",
        "timestamp": "2025-11-19T10:00:00Z"
    }
    
    rollback_coordinator.cloudwatch_logs.start_query.return_value = {'queryId': 'query-123'}
    rollback_coordinator.cloudwatch_logs.get_query_results.return_value = {
        'status': 'Complete',
        'results': [[
            {'field': '@message', 'value': json.dumps(log_data)}
        ]]
    }
    
    # Mock DynamoDB update
    rollback_coordinator.orders_table.update_item.return_value = {}
    
    # Mock CloudWatch put_log_events for rollback logging
    rollback_coordinator.cloudwatch_logs.put_log_events.return_value = {}
    
    result = await rollback_coordinator.rollback_action(
        action_id="act-refund-123",
        action_type="process_refund",
        reason="Suspicious activity",
        operator_id="admin@sentra.com"
    )
    
    assert result['success'] is True
    assert 'rollback_id' in result
    assert result['action_id'] == "act-refund-123"
    assert rollback_coordinator.orders_table.update_item.called


@pytest.mark.asyncio
async def test_rollback_dynamodb_error_handling(rollback_coordinator):
    """Test error handling when DynamoDB update fails"""
    log_data = {
        "action_id": "act-refund-123",
        "tool_name": "process_refund",
        "tool_params": {"order_id": "ORD-123", "amount": 5000},
        "reversible": True,
        "rollback_status": "NOT_ROLLED_BACK",
        "timestamp": "2025-11-19T10:00:00Z"
    }
    
    rollback_coordinator.cloudwatch_logs.start_query.return_value = {'queryId': 'query-123'}
    rollback_coordinator.cloudwatch_logs.get_query_results.return_value = {
        'status': 'Complete',
        'results': [[
            {'field': '@message', 'value': json.dumps(log_data)}
        ]]
    }
    
    # Mock DynamoDB error
    rollback_coordinator.orders_table.update_item.side_effect = Exception("DynamoDB error")
    
    result = await rollback_coordinator.rollback_action(
        action_id="act-refund-123",
        action_type="process_refund",
        reason="Test",
        operator_id="admin@sentra.com"
    )
    
    assert result['success'] is False
    assert 'failed' in result['message'].lower()


@pytest.mark.asyncio
async def test_get_action_from_logs_timeout(rollback_coordinator):
    """Test CloudWatch query timeout handling"""
    rollback_coordinator.cloudwatch_logs.start_query.return_value = {'queryId': 'query-123'}
    rollback_coordinator.cloudwatch_logs.get_query_results.return_value = {
        'status': 'Running'  # Never completes
    }
    
    result = await rollback_coordinator._get_action_from_logs("act-timeout")
    
    assert result is None


@pytest.mark.asyncio
async def test_get_action_from_logs_query_failed(rollback_coordinator):
    """Test CloudWatch query failure handling"""
    rollback_coordinator.cloudwatch_logs.start_query.return_value = {'queryId': 'query-123'}
    rollback_coordinator.cloudwatch_logs.get_query_results.return_value = {
        'status': 'Failed'
    }
    
    result = await rollback_coordinator._get_action_from_logs("act-failed")
    
    assert result is None


# ==================== Conversation Rollback Tests (Workstream 12) ====================

@pytest.mark.asyncio
async def test_rollback_conversation_success(rollback_coordinator):
    """Test successful conversation rollback with multiple actions"""
    # Mock audit logs for conversation
    logs = [
        {
            "request_id": "req-001",
            "action_id": "act-refund-001",
            "tool_name": "process_refund",
            "operation_type": "WRITE",
            "decision": "ALLOW",
            "reversible": True,
            "rollback_status": "NOT_ROLLED_BACK",
            "timestamp": "2025-01-01T00:00:00Z",
            "tool_params": {"order_id": "ORD-123", "amount": 100}
        },
        {
            "request_id": "req-002",
            "action_id": "act-order-001",
            "tool_name": "create_order",
            "operation_type": "WRITE",
            "decision": "ALLOW",
            "reversible": True,
            "rollback_status": "NOT_ROLLED_BACK",
            "timestamp": "2025-01-01T00:00:01Z",
            "tool_params": {"order_id": "ORD-456"}
        }
    ]
    
    rollback_coordinator.audit_logger.query_logs_by_conversation = AsyncMock(return_value=logs)
    rollback_coordinator.orders_table.update_item.return_value = {}
    rollback_coordinator.orders_table.delete_item.return_value = {}
    rollback_coordinator.cloudwatch_logs.put_log_events.return_value = {}
    rollback_coordinator.cloudwatch_logs.create_log_stream.return_value = {}
    
    result = await rollback_coordinator.rollback_conversation(
        conversation_id="conv-abc123",
        reason="Test rollback",
        operator_id="admin@sentra.com"
    )
    
    assert result["success"] is True
    assert result["conversation_id"] == "conv-abc123"
    assert result["rolled_back_count"] == 2
    assert result["failed_count"] == 0


@pytest.mark.asyncio
async def test_rollback_conversation_no_logs(rollback_coordinator):
    """Test conversation rollback when no logs found"""
    rollback_coordinator.audit_logger.query_logs_by_conversation = AsyncMock(return_value=[])
    
    result = await rollback_coordinator.rollback_conversation(
        conversation_id="conv-nonexistent",
        reason="Test",
        operator_id="admin"
    )
    
    assert result["success"] is True
    assert result["rolled_back_count"] == 0
    assert "No logs found" in result["message"]


@pytest.mark.asyncio
async def test_rollback_conversation_no_reversible_actions(rollback_coordinator):
    """Test conversation rollback when no reversible actions"""
    logs = [
        {
            "request_id": "req-001",
            "tool_name": "query_customers",
            "operation_type": "READ",  # Not WRITE
            "decision": "ALLOW",
            "timestamp": "2025-01-01T00:00:00Z"
        }
    ]
    
    rollback_coordinator.audit_logger.query_logs_by_conversation = AsyncMock(return_value=logs)
    
    result = await rollback_coordinator.rollback_conversation(
        conversation_id="conv-readonly",
        reason="Test",
        operator_id="admin"
    )
    
    assert result["success"] is True
    assert result["rolled_back_count"] == 0
    assert "No reversible actions" in result["message"]


@pytest.mark.asyncio
async def test_rollback_conversation_lifo_order(rollback_coordinator):
    """Test that conversation rollback executes in LIFO order"""
    logs = [
        {
            "request_id": "req-001",
            "action_id": "act-first",
            "tool_name": "create_order",
            "operation_type": "WRITE",
            "decision": "ALLOW",
            "reversible": True,
            "rollback_status": "NOT_ROLLED_BACK",
            "timestamp": "2025-01-01T00:00:00Z",
            "tool_params": {"order_id": "ORD-001"}
        },
        {
            "request_id": "req-002",
            "action_id": "act-second",
            "tool_name": "create_order",
            "operation_type": "WRITE",
            "decision": "ALLOW",
            "reversible": True,
            "rollback_status": "NOT_ROLLED_BACK",
            "timestamp": "2025-01-01T00:00:01Z",
            "tool_params": {"order_id": "ORD-002"}
        }
    ]
    
    rollback_coordinator.audit_logger.query_logs_by_conversation = AsyncMock(return_value=logs)
    rollback_coordinator.orders_table.delete_item.return_value = {}
    rollback_coordinator.cloudwatch_logs.put_log_events.return_value = {}
    rollback_coordinator.cloudwatch_logs.create_log_stream.return_value = {}
    
    # Track order of delete calls
    delete_calls = []
    def track_delete(Key):
        delete_calls.append(Key['order_id'])
        return {}
    
    rollback_coordinator.orders_table.delete_item.side_effect = track_delete
    
    result = await rollback_coordinator.rollback_conversation(
        conversation_id="conv-lifo",
        reason="Test LIFO",
        operator_id="admin"
    )
    
    assert result["success"] is True
    # Second action (later timestamp) should be rolled back first
    assert delete_calls[0] == "ORD-002"
    assert delete_calls[1] == "ORD-001"


@pytest.mark.asyncio
async def test_rollback_conversation_partial_failure(rollback_coordinator):
    """Test conversation rollback with partial failure"""
    logs = [
        {
            "request_id": "req-001",
            "action_id": "act-success",
            "tool_name": "create_order",
            "operation_type": "WRITE",
            "decision": "ALLOW",
            "reversible": True,
            "rollback_status": "NOT_ROLLED_BACK",
            "timestamp": "2025-01-01T00:00:00Z",
            "tool_params": {"order_id": "ORD-001"}
        },
        {
            "request_id": "req-002",
            "action_id": "act-fail",
            "tool_name": "create_order",
            "operation_type": "WRITE",
            "decision": "ALLOW",
            "reversible": True,
            "rollback_status": "NOT_ROLLED_BACK",
            "timestamp": "2025-01-01T00:00:01Z",
            "tool_params": {"order_id": "ORD-002"}
        }
    ]
    
    rollback_coordinator.audit_logger.query_logs_by_conversation = AsyncMock(return_value=logs)
    rollback_coordinator.cloudwatch_logs.put_log_events.return_value = {}
    rollback_coordinator.cloudwatch_logs.create_log_stream.return_value = {}
    
    # First delete succeeds, second fails
    call_count = [0]
    def mock_delete(Key):
        call_count[0] += 1
        if call_count[0] == 1:
            raise Exception("DynamoDB error")
        return {}
    
    rollback_coordinator.orders_table.delete_item.side_effect = mock_delete
    
    result = await rollback_coordinator.rollback_conversation(
        conversation_id="conv-partial",
        reason="Test partial",
        operator_id="admin"
    )
    
    assert result["success"] is False
    assert result["rolled_back_count"] == 1
    assert result["failed_count"] == 1


@pytest.mark.asyncio
async def test_rollback_conversation_skips_already_rolled_back(rollback_coordinator):
    """Test that already rolled back actions are skipped"""
    logs = [
        {
            "request_id": "req-001",
            "action_id": "act-already",
            "tool_name": "create_order",
            "operation_type": "WRITE",
            "decision": "ALLOW",
            "reversible": True,
            "rollback_status": "ROLLED_BACK",  # Already rolled back
            "timestamp": "2025-01-01T00:00:00Z",
            "tool_params": {"order_id": "ORD-001"}
        },
        {
            "request_id": "req-002",
            "action_id": "act-pending",
            "tool_name": "create_order",
            "operation_type": "WRITE",
            "decision": "ALLOW",
            "reversible": True,
            "rollback_status": "NOT_ROLLED_BACK",
            "timestamp": "2025-01-01T00:00:01Z",
            "tool_params": {"order_id": "ORD-002"}
        }
    ]
    
    rollback_coordinator.audit_logger.query_logs_by_conversation = AsyncMock(return_value=logs)
    rollback_coordinator.orders_table.delete_item.return_value = {}
    rollback_coordinator.cloudwatch_logs.put_log_events.return_value = {}
    rollback_coordinator.cloudwatch_logs.create_log_stream.return_value = {}
    
    result = await rollback_coordinator.rollback_conversation(
        conversation_id="conv-skip",
        reason="Test skip",
        operator_id="admin"
    )
    
    assert result["success"] is True
    assert result["rolled_back_count"] == 1  # Only one action rolled back
    # Verify only one delete was called
    assert rollback_coordinator.orders_table.delete_item.call_count == 1


@pytest.mark.asyncio
async def test_rollback_conversation_skips_denied_actions(rollback_coordinator):
    """Test that DENIED actions are not rolled back"""
    logs = [
        {
            "request_id": "req-001",
            "action_id": "act-denied",
            "tool_name": "process_refund",
            "operation_type": "WRITE",
            "decision": "DENY",  # Was denied, never executed
            "reversible": True,
            "timestamp": "2025-01-01T00:00:00Z"
        }
    ]
    
    rollback_coordinator.audit_logger.query_logs_by_conversation = AsyncMock(return_value=logs)
    
    result = await rollback_coordinator.rollback_conversation(
        conversation_id="conv-denied",
        reason="Test denied",
        operator_id="admin"
    )
    
    assert result["success"] is True
    assert result["rolled_back_count"] == 0
    assert "No reversible actions" in result["message"]
