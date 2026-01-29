"""
Unit Tests for Payment Agent Tools
Sentra MVP - Workstream 7, Task 7

Tests all three payment agent tools with mocked DynamoDB
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from decimal import Decimal
from datetime import datetime

from app.tools.query_refund_status import query_refund_status
from app.tools.process_refund import process_refund
from app.tools.reverse_refund import reverse_refund
from app.security_integration import SecurityException, set_request_context


@pytest.fixture
def mock_request_context():
    """Set up request context for @secured_tool decorator"""
    set_request_context(
        request_id="test-req-001",
        session_id="test-session-001",
        user_input="Test query",
        context={"user_id": "test@sentra.com", "authorization_level": "manager"}
    )
    yield
    # Context cleanup happens automatically


@pytest.fixture
def mock_dynamodb_table():
    """Mock DynamoDB table"""
    with patch('boto3.resource') as mock_resource:
        mock_table = MagicMock()
        mock_resource.return_value.Table.return_value = mock_table
        yield mock_table


@pytest.fixture
def mock_security_controller():
    """Mock Security Controller to always ALLOW"""
    with patch('app.security_integration.call_security_controller') as mock_sc:
        mock_sc.return_value = {
            "decision": "ALLOW",
            "reason": "No policy violations detected",
            "request_id": "test-req-001",
            "session_id": "test-session-001"
        }
        yield mock_sc


# ==================== Test query_refund_status ====================

def test_query_refund_status_success(mock_request_context, mock_dynamodb_table, mock_security_controller):
    """Test querying refund status for a refunded order"""
    # Mock DynamoDB response
    mock_dynamodb_table.get_item.return_value = {
        'Item': {
            'order_id': 'ord-12345',
            'customer_id': 'cust-001',
            'customer_name': 'John Doe',
            'amount': Decimal('500.00'),
            'status': 'completed',
            'refund_amount': Decimal('150.00'),
            'refund_date': '2024-11-20T10:00:00Z',
            'refund_status': 'refunded',
            'transaction_id': 'txn-abc123'
        }
    }

    # Execute tool
    result = query_refund_status(order_id='ord-12345')

    # Assertions
    assert result['order_id'] == 'ord-12345'
    assert result['refund_amount'] == 150.00
    assert result['refund_status'] == 'refunded'
    assert result['transaction_id'] == 'txn-abc123'
    assert result['customer_name'] == 'John Doe'

    # Verify Security Controller was called
    mock_security_controller.assert_called_once()


def test_query_refund_status_not_refunded(mock_request_context, mock_dynamodb_table, mock_security_controller):
    """Test querying refund status for an order that hasn't been refunded"""
    # Mock DynamoDB response (no refund fields)
    mock_dynamodb_table.get_item.return_value = {
        'Item': {
            'order_id': 'ord-12345',
            'customer_id': 'cust-001',
            'customer_name': 'John Doe',
            'amount': Decimal('500.00'),
            'status': 'completed'
        }
    }

    # Execute tool
    result = query_refund_status(order_id='ord-12345')

    # Assertions
    assert result['order_id'] == 'ord-12345'
    assert result['refund_amount'] is None
    assert result['refund_status'] == 'not_refunded'
    assert result['transaction_id'] is None


def test_query_refund_status_order_not_found(mock_request_context, mock_dynamodb_table, mock_security_controller):
    """Test querying refund status for non-existent order"""
    # Mock DynamoDB response (no item)
    mock_dynamodb_table.get_item.return_value = {}

    # Execute tool
    result = query_refund_status(order_id='ord-nonexistent')

    # Assertions
    assert result['order_id'] == 'ord-nonexistent'
    assert result['status'] == 'not_found'
    assert 'not found' in result['message'].lower()


# ==================== Test process_refund ====================

def test_process_refund_success(mock_request_context, mock_dynamodb_table, mock_security_controller):
    """Test successfully processing a refund"""
    # Mock DynamoDB get_item response
    mock_dynamodb_table.get_item.return_value = {
        'Item': {
            'order_id': 'ord-12345',
            'customer_id': 'cust-001',
            'customer_name': 'John Doe',
            'amount': Decimal('500.00'),
            'status': 'completed'
        }
    }

    # Execute tool
    result = process_refund(
        order_id='ord-12345',
        amount=150.00,
        reason='Customer requested refund'
    )

    # Assertions
    assert result['status'] == 'success'
    assert result['order_id'] == 'ord-12345'
    assert result['refund_amount'] == 150.00
    assert result['reason'] == 'Customer requested refund'
    assert 'transaction_id' in result
    assert result['transaction_id'].startswith('txn-')

    # Verify DynamoDB update was called
    mock_dynamodb_table.update_item.assert_called_once()
    update_call = mock_dynamodb_table.update_item.call_args

    # Verify update expression includes refund fields
    assert 'refund_amount' in update_call[1]['UpdateExpression']
    assert 'refund_date' in update_call[1]['UpdateExpression']
    assert 'refund_status' in update_call[1]['UpdateExpression']
    assert 'transaction_id' in update_call[1]['UpdateExpression']


def test_process_refund_order_not_found(mock_request_context, mock_dynamodb_table, mock_security_controller):
    """Test processing refund for non-existent order"""
    # Mock DynamoDB response (no item)
    mock_dynamodb_table.get_item.return_value = {}

    # Execute tool - should raise ValueError
    with pytest.raises(ValueError, match="not found"):
        process_refund(
            order_id='ord-nonexistent',
            amount=150.00,
            reason='Test'
        )


def test_process_refund_invalid_status(mock_request_context, mock_dynamodb_table, mock_security_controller):
    """Test processing refund for order with invalid status"""
    # Mock DynamoDB response (order not completed)
    mock_dynamodb_table.get_item.return_value = {
        'Item': {
            'order_id': 'ord-12345',
            'customer_id': 'cust-001',
            'customer_name': 'John Doe',
            'amount': Decimal('500.00'),
            'status': 'pending'  # Not completed
        }
    }

    # Execute tool - should raise ValueError
    with pytest.raises(ValueError, match="must be 'completed'"):
        process_refund(
            order_id='ord-12345',
            amount=150.00,
            reason='Test'
        )


def test_process_refund_already_refunded(mock_request_context, mock_dynamodb_table, mock_security_controller):
    """Test processing refund for already refunded order"""
    # Mock DynamoDB response (already refunded)
    mock_dynamodb_table.get_item.return_value = {
        'Item': {
            'order_id': 'ord-12345',
            'customer_id': 'cust-001',
            'customer_name': 'John Doe',
            'amount': Decimal('500.00'),
            'status': 'completed',
            'refund_status': 'refunded'
        }
    }

    # Execute tool - should raise ValueError
    with pytest.raises(ValueError, match="already been refunded"):
        process_refund(
            order_id='ord-12345',
            amount=150.00,
            reason='Test'
        )


def test_process_refund_exceeds_order_amount(mock_request_context, mock_dynamodb_table, mock_security_controller):
    """Test processing refund that exceeds order total"""
    # Mock DynamoDB response
    mock_dynamodb_table.get_item.return_value = {
        'Item': {
            'order_id': 'ord-12345',
            'customer_id': 'cust-001',
            'customer_name': 'John Doe',
            'amount': Decimal('100.00'),
            'status': 'completed'
        }
    }

    # Execute tool - should raise ValueError
    with pytest.raises(ValueError, match="exceeds order total"):
        process_refund(
            order_id='ord-12345',
            amount=150.00,  # More than order amount
            reason='Test'
        )


def test_process_refund_negative_amount(mock_request_context, mock_dynamodb_table, mock_security_controller):
    """Test processing refund with negative amount"""
    # Mock DynamoDB response
    mock_dynamodb_table.get_item.return_value = {
        'Item': {
            'order_id': 'ord-12345',
            'customer_id': 'cust-001',
            'customer_name': 'John Doe',
            'amount': Decimal('500.00'),
            'status': 'completed'
        }
    }

    # Execute tool - should raise ValueError
    with pytest.raises(ValueError, match="must be positive"):
        process_refund(
            order_id='ord-12345',
            amount=-50.00,
            reason='Test'
        )


def test_process_refund_security_denial(mock_request_context, mock_dynamodb_table):
    """Test processing refund denied by Security Controller"""
    # Mock Security Controller to DENY
    with patch('app.security_integration.call_security_controller') as mock_sc:
        mock_sc.return_value = {
            "decision": "DENY",
            "reason": "Refund amount exceeds manager authorization limit",
            "request_id": "test-req-001",
            "session_id": "test-session-001",
            "matched_rules": [{"rule_id": "POLICY_REFUND_LIMIT"}]
        }

        # Mock DynamoDB response
        mock_dynamodb_table.get_item.return_value = {
            'Item': {
                'order_id': 'ord-12345',
                'customer_id': 'cust-001',
                'customer_name': 'John Doe',
                'amount': Decimal('10000.00'),
                'status': 'completed'
            }
        }

        # Execute tool - should raise SecurityException
        with pytest.raises(SecurityException, match="Security validation failed"):
            process_refund(
                order_id='ord-12345',
                amount=5000.00,  # Exceeds $200 manager limit
                reason='Large refund'
            )


# ==================== Test reverse_refund ====================

def test_reverse_refund_success(mock_request_context, mock_dynamodb_table, mock_security_controller):
    """Test successfully reversing a refund"""
    # Mock DynamoDB query response (find by transaction_id)
    mock_dynamodb_table.query.return_value = {
        'Items': [
            {
                'order_id': 'ord-12345',
                'customer_id': 'cust-001',
                'customer_name': 'John Doe',
                'amount': Decimal('500.00'),
                'status': 'completed',
                'refund_amount': Decimal('150.00'),
                'refund_date': '2024-11-20T10:00:00Z',
                'refund_status': 'refunded',
                'transaction_id': 'txn-abc123'
            }
        ]
    }

    # Execute tool
    result = reverse_refund(
        transaction_id='txn-abc123',
        reason='Accidental refund'
    )

    # Assertions
    assert result['status'] == 'reversed'
    assert result['order_id'] == 'ord-12345'
    assert result['transaction_id'] == 'txn-abc123'
    assert result['original_refund_amount'] == 150.00
    assert result['rollback_reason'] == 'Accidental refund'
    assert 'rollback_date' in result

    # Verify DynamoDB update was called
    mock_dynamodb_table.update_item.assert_called_once()
    update_call = mock_dynamodb_table.update_item.call_args

    # Verify update expression removes refund fields
    assert 'REMOVE refund_amount' in update_call[1]['UpdateExpression']
    assert 'refund_status' in update_call[1]['UpdateExpression']
    assert 'rollback_reason' in update_call[1]['UpdateExpression']


def test_reverse_refund_transaction_not_found(mock_request_context, mock_dynamodb_table, mock_security_controller):
    """Test reversing refund for non-existent transaction"""
    # Mock DynamoDB query response (no items)
    mock_dynamodb_table.query.return_value = {'Items': []}

    # Execute tool - should raise ValueError
    with pytest.raises(ValueError, match="not found"):
        reverse_refund(
            transaction_id='txn-nonexistent',
            reason='Test'
        )


def test_reverse_refund_not_refunded_status(mock_request_context, mock_dynamodb_table, mock_security_controller):
    """Test reversing refund for order not in refunded status"""
    # Mock DynamoDB query response (order not refunded)
    mock_dynamodb_table.query.return_value = {
        'Items': [
            {
                'order_id': 'ord-12345',
                'customer_id': 'cust-001',
                'customer_name': 'John Doe',
                'amount': Decimal('500.00'),
                'status': 'completed',
                'refund_status': 'not_refunded'  # Not refunded
            }
        ]
    }

    # Execute tool - should raise ValueError
    with pytest.raises(ValueError, match="not in 'refunded' status"):
        reverse_refund(
            transaction_id='txn-abc123',
            reason='Test'
        )


def test_reverse_refund_multiple_orders(mock_request_context, mock_dynamodb_table, mock_security_controller):
    """Test reversing refund when multiple orders found (data integrity issue)"""
    # Mock DynamoDB query response (multiple items - should never happen)
    mock_dynamodb_table.query.return_value = {
        'Items': [
            {'order_id': 'ord-12345', 'refund_status': 'refunded'},
            {'order_id': 'ord-67890', 'refund_status': 'refunded'}
        ]
    }

    # Execute tool - should raise ValueError
    with pytest.raises(ValueError, match="Multiple orders found"):
        reverse_refund(
            transaction_id='txn-abc123',
            reason='Test'
        )


# ==================== Integration Tests ====================

def test_refund_workflow_integration(mock_request_context, mock_dynamodb_table, mock_security_controller):
    """Test complete refund workflow: process → query → reverse"""
    
    # Step 1: Process refund
    mock_dynamodb_table.get_item.return_value = {
        'Item': {
            'order_id': 'ord-12345',
            'customer_id': 'cust-001',
            'customer_name': 'John Doe',
            'amount': Decimal('500.00'),
            'status': 'completed'
        }
    }

    refund_result = process_refund(
        order_id='ord-12345',
        amount=150.00,
        reason='Customer requested'
    )

    assert refund_result['status'] == 'success'
    transaction_id = refund_result['transaction_id']

    # Step 2: Query refund status
    mock_dynamodb_table.get_item.return_value = {
        'Item': {
            'order_id': 'ord-12345',
            'customer_id': 'cust-001',
            'customer_name': 'John Doe',
            'amount': Decimal('500.00'),
            'status': 'completed',
            'refund_amount': Decimal('150.00'),
            'refund_date': '2024-11-20T10:00:00Z',
            'refund_status': 'refunded',
            'transaction_id': transaction_id
        }
    }

    status_result = query_refund_status(order_id='ord-12345')
    assert status_result['refund_status'] == 'refunded'
    assert status_result['refund_amount'] == 150.00

    # Step 3: Reverse refund
    mock_dynamodb_table.query.return_value = {
        'Items': [
            {
                'order_id': 'ord-12345',
                'customer_id': 'cust-001',
                'customer_name': 'John Doe',
                'amount': Decimal('500.00'),
                'status': 'completed',
                'refund_amount': Decimal('150.00'),
                'refund_status': 'refunded',
                'transaction_id': transaction_id
            }
        ]
    }

    reverse_result = reverse_refund(
        transaction_id=transaction_id,
        reason='Accidental refund'
    )

    assert reverse_result['status'] == 'reversed'
    assert reverse_result['transaction_id'] == transaction_id
