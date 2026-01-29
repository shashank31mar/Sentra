"""
Unit Tests for Payment Agent Claude Processor
Sentra MVP - Workstream 7, Task 8

Tests Bedrock Claude integration and tool execution
"""

import pytest
import json
from unittest.mock import Mock, patch, MagicMock
from decimal import Decimal

from app.claude_processor import (
    process_with_claude,
    execute_tool,
    TOOL_REGISTRY,
    PAYMENT_TOOLS
)
from app.security_integration import SecurityException, set_request_context


@pytest.fixture
def mock_request_context():
    """Set up request context"""
    set_request_context(
        request_id="test-req-001",
        session_id="test-session-001",
        user_input="Test query",
        context={"user_id": "test@sentra.com"}
    )
    yield


@pytest.fixture
def mock_bedrock():
    """Mock Bedrock client"""
    with patch('boto3.client') as mock_client:
        mock_bedrock = MagicMock()
        mock_client.return_value = mock_bedrock
        yield mock_bedrock


@pytest.fixture
def mock_security_controller():
    """Mock Security Controller to always ALLOW"""
    with patch('app.security_integration.call_security_controller') as mock_sc:
        mock_sc.return_value = {
            "decision": "ALLOW",
            "reason": "No policy violations detected"
        }
        yield mock_sc


@pytest.fixture
def mock_dynamodb():
    """Mock DynamoDB"""
    with patch('boto3.resource') as mock_resource:
        mock_table = MagicMock()
        mock_resource.return_value.Table.return_value = mock_table
        yield mock_table


# ==================== Test Tool Registry ====================

def test_tool_registry_contains_all_tools():
    """Test that tool registry contains all expected tools"""
    assert "query_refund_status" in TOOL_REGISTRY
    assert "process_refund" in TOOL_REGISTRY
    assert "reverse_refund" in TOOL_REGISTRY
    assert len(TOOL_REGISTRY) == 3


def test_tool_schemas_defined():
    """Test that tool schemas are properly defined for Claude"""
    assert len(PAYMENT_TOOLS) == 3
    
    # Check each tool has required fields
    for tool in PAYMENT_TOOLS:
        assert "name" in tool
        assert "description" in tool
        assert "input_schema" in tool
        assert tool["input_schema"]["type"] == "object"
        assert "properties" in tool["input_schema"]


# ==================== Test execute_tool ====================

def test_execute_tool_query_refund_status(mock_request_context, mock_dynamodb, mock_security_controller):
    """Test executing query_refund_status tool"""
    # Mock DynamoDB response
    mock_dynamodb.get_item.return_value = {
        'Item': {
            'order_id': 'ord-12345',
            'customer_id': 'cust-001',
            'customer_name': 'John Doe',
            'amount': Decimal('500.00'),
            'status': 'completed',
            'refund_amount': Decimal('150.00'),
            'refund_status': 'refunded'
        }
    }

    # Execute tool
    result = execute_tool("query_refund_status", {"order_id": "ord-12345"})

    # Assertions
    assert result["order_id"] == "ord-12345"
    assert result["refund_status"] == "refunded"


def test_execute_tool_process_refund(mock_request_context, mock_dynamodb, mock_security_controller):
    """Test executing process_refund tool"""
    # Mock DynamoDB response
    mock_dynamodb.get_item.return_value = {
        'Item': {
            'order_id': 'ord-12345',
            'customer_id': 'cust-001',
            'customer_name': 'John Doe',
            'amount': Decimal('500.00'),
            'status': 'completed'
        }
    }

    # Execute tool
    result = execute_tool("process_refund", {
        "order_id": "ord-12345",
        "amount": 150.00,
        "reason": "Customer request"
    })

    # Assertions
    assert result["status"] == "success"
    assert result["refund_amount"] == 150.00
    assert "transaction_id" in result


def test_execute_tool_not_found():
    """Test executing non-existent tool"""
    with pytest.raises(ValueError, match="not found in registry"):
        execute_tool("nonexistent_tool", {})


# ==================== Test process_with_claude ====================

def test_process_with_claude_direct_response(mock_request_context, mock_bedrock):
    """Test Claude responding directly without using tools"""
    # Mock Bedrock response (no tool use)
    mock_response = {
        'body': Mock(read=lambda: json.dumps({
            'content': [
                {'type': 'text', 'text': 'I can help you with refund queries.'}
            ],
            'stop_reason': 'end_turn'
        }).encode())
    }
    mock_bedrock.invoke_model.return_value = mock_response

    # Process message
    result = process_with_claude(
        message="Hello, can you help me?",
        session_id="test-session-001",
        request_id="test-req-001"
    )

    # Assertions
    assert result["text"] == "I can help you with refund queries."
    assert result["data"] == {}


def test_process_with_claude_with_tool_use(mock_request_context, mock_bedrock, mock_dynamodb, mock_security_controller):
    """Test Claude using a tool"""
    # Mock DynamoDB response
    mock_dynamodb.get_item.return_value = {
        'Item': {
            'order_id': 'ord-12345',
            'refund_status': 'refunded',
            'refund_amount': Decimal('150.00')
        }
    }

    # Mock Bedrock responses
    # First response: Claude wants to use tool
    first_response = {
        'body': Mock(read=lambda: json.dumps({
            'content': [
                {
                    'type': 'tool_use',
                    'id': 'tool_001',
                    'name': 'query_refund_status',
                    'input': {'order_id': 'ord-12345'}
                }
            ],
            'stop_reason': 'tool_use'
        }).encode())
    }

    # Second response: Claude's final answer
    second_response = {
        'body': Mock(read=lambda: json.dumps({
            'content': [
                {'type': 'text', 'text': 'The refund of $150.00 has been processed.'}
            ],
            'stop_reason': 'end_turn'
        }).encode())
    }

    mock_bedrock.invoke_model.side_effect = [first_response, second_response]

    # Process message
    result = process_with_claude(
        message="Check refund status for order ord-12345",
        session_id="test-session-001",
        request_id="test-req-001"
    )

    # Assertions
    assert "refund" in result["text"].lower()
    assert "150" in result["text"]
    assert mock_bedrock.invoke_model.call_count == 2


def test_process_with_claude_security_denial(mock_request_context, mock_bedrock, mock_dynamodb):
    """Test Claude handling security denial gracefully"""
    # Mock Security Controller to DENY
    with patch('app.security_integration.call_security_controller') as mock_sc:
        mock_sc.return_value = {
            "decision": "DENY",
            "reason": "Refund amount exceeds authorization limit",
            "matched_rules": [{"rule_id": "POLICY_REFUND_LIMIT"}]
        }

        # Mock DynamoDB response
        mock_dynamodb.get_item.return_value = {
            'Item': {
                'order_id': 'ord-12345',
                'amount': Decimal('10000.00'),
                'status': 'completed'
            }
        }

        # Mock Bedrock responses
        first_response = {
            'body': Mock(read=lambda: json.dumps({
                'content': [
                    {
                        'type': 'tool_use',
                        'id': 'tool_001',
                        'name': 'process_refund',
                        'input': {
                            'order_id': 'ord-12345',
                            'amount': 5000.00,
                            'reason': 'Customer request'
                        }
                    }
                ],
                'stop_reason': 'tool_use'
            }).encode())
        }

        # Claude receives denial and explains it naturally
        second_response = {
            'body': Mock(read=lambda: json.dumps({
                'content': [
                    {
                        'type': 'text',
                        'text': "I'm unable to process that refund because it exceeds the authorization limit."
                    }
                ],
                'stop_reason': 'end_turn'
            }).encode())
        }

        mock_bedrock.invoke_model.side_effect = [first_response, second_response]

        # Process message
        result = process_with_claude(
            message="Process refund of $5000 for order ord-12345",
            session_id="test-session-001",
            request_id="test-req-001"
        )

        # Assertions
        assert "unable" in result["text"].lower()
        assert "authorization limit" in result["text"].lower()


def test_process_with_claude_tool_execution_error(mock_request_context, mock_bedrock, mock_dynamodb, mock_security_controller):
    """Test Claude handling tool execution error"""
    # Mock DynamoDB to return order not found
    mock_dynamodb.get_item.return_value = {}

    # Mock Bedrock responses
    first_response = {
        'body': Mock(read=lambda: json.dumps({
            'content': [
                {
                    'type': 'tool_use',
                    'id': 'tool_001',
                    'name': 'process_refund',
                    'input': {
                        'order_id': 'ord-nonexistent',
                        'amount': 150.00,
                        'reason': 'Test'
                    }
                }
            ],
            'stop_reason': 'tool_use'
        }).encode())
    }

    # Claude receives error and explains it
    second_response = {
        'body': Mock(read=lambda: json.dumps({
            'content': [
                {'type': 'text', 'text': 'I could not find that order.'}
            ],
            'stop_reason': 'end_turn'
        }).encode())
    }

    mock_bedrock.invoke_model.side_effect = [first_response, second_response]

    # Process message
    result = process_with_claude(
        message="Process refund for order ord-nonexistent",
        session_id="test-session-001",
        request_id="test-req-001"
    )

    # Assertions
    assert "could not find" in result["text"].lower()


def test_process_with_claude_multiple_tools(mock_request_context, mock_bedrock, mock_dynamodb, mock_security_controller):
    """Test Claude using multiple tools in sequence"""
    # Mock DynamoDB responses
    mock_dynamodb.get_item.return_value = {
        'Item': {
            'order_id': 'ord-12345',
            'amount': Decimal('500.00'),
            'status': 'completed',
            'refund_status': 'not_refunded'
        }
    }

    # Mock Bedrock responses
    # First: Claude wants to check status
    first_response = {
        'body': Mock(read=lambda: json.dumps({
            'content': [
                {
                    'type': 'tool_use',
                    'id': 'tool_001',
                    'name': 'query_refund_status',
                    'input': {'order_id': 'ord-12345'}
                }
            ],
            'stop_reason': 'tool_use'
        }).encode())
    }

    # Second: Claude provides answer
    second_response = {
        'body': Mock(read=lambda: json.dumps({
            'content': [
                {'type': 'text', 'text': 'The order has not been refunded yet.'}
            ],
            'stop_reason': 'end_turn'
        }).encode())
    }

    mock_bedrock.invoke_model.side_effect = [first_response, second_response]

    # Process message
    result = process_with_claude(
        message="Has order ord-12345 been refunded?",
        session_id="test-session-001",
        request_id="test-req-001"
    )

    # Assertions
    assert "not been refunded" in result["text"].lower()


def test_process_with_claude_bedrock_error(mock_request_context, mock_bedrock):
    """Test handling Bedrock API error"""
    # Mock Bedrock to raise exception
    mock_bedrock.invoke_model.side_effect = Exception("Bedrock API error")

    # Process message - should raise exception
    with pytest.raises(Exception, match="Bedrock API error"):
        process_with_claude(
            message="Test message",
            session_id="test-session-001",
            request_id="test-req-001"
        )
