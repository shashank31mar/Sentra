"""
Integration Tests for Payment Agent
Sentra MVP - Workstream 7, Task 7 & 8

These tests verify end-to-end functionality with mocked AWS services
"""

import pytest
from unittest.mock import patch, MagicMock
from decimal import Decimal
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    """Create test client"""
    return TestClient(app)


@pytest.fixture
def mock_aws_services():
    """Mock all AWS services (DynamoDB, Bedrock, Security Controller)"""
    with patch('boto3.resource') as mock_dynamodb_resource, \
         patch('boto3.client') as mock_boto_client, \
         patch('app.security_integration.call_security_controller') as mock_sc:
        
        # Mock DynamoDB table
        mock_table = MagicMock()
        mock_dynamodb_resource.return_value.Table.return_value = mock_table
        
        # Mock Bedrock client
        mock_bedrock = MagicMock()
        
        # Configure boto3.client to return appropriate mocks
        def client_side_effect(service_name, **kwargs):
            if service_name == 'bedrock-runtime':
                return mock_bedrock
            elif service_name == 'bedrock':
                mock_bedrock_service = MagicMock()
                mock_bedrock_service.list_foundation_models.return_value = {}
                return mock_bedrock_service
            elif service_name == 'dynamodb':
                mock_ddb_client = MagicMock()
                mock_ddb_client.describe_table.return_value = {'Table': {'TableStatus': 'ACTIVE'}}
                return mock_ddb_client
            return MagicMock()
        
        mock_boto_client.side_effect = client_side_effect
        
        # Mock Security Controller to ALLOW by default
        mock_sc.return_value = {
            "decision": "ALLOW",
            "reason": "No policy violations detected"
        }
        
        yield {
            'dynamodb_table': mock_table,
            'bedrock': mock_bedrock,
            'security_controller': mock_sc
        }


# ==================== Integration Test: Query Refund Status ====================

def test_integration_query_refund_status(client, mock_aws_services):
    """Test complete flow: API → Claude → Tool → DynamoDB"""
    import json
    from unittest.mock import Mock
    
    # Setup DynamoDB mock
    mock_aws_services['dynamodb_table'].get_item.return_value = {
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
    
    # Setup Bedrock mock responses
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
    
    second_response = {
        'body': Mock(read=lambda: json.dumps({
            'content': [
                {
                    'type': 'text',
                    'text': 'The refund of $150.00 for order ord-12345 was processed on November 20, 2024. The transaction ID is txn-abc123 and the status is completed.'
                }
            ],
            'stop_reason': 'end_turn'
        }).encode())
    }
    
    mock_aws_services['bedrock'].invoke_model.side_effect = [first_response, second_response]
    
    # Make API request
    response = client.post(
        "/v1/agents/payment/query",
        json={
            "message": "What's the refund status for order ord-12345?",
            "session_id": "integration-test-001"
        }
    )
    
    # Assertions
    assert response.status_code == 200
    data = response.json()
    assert "150" in data["response"]
    assert "txn-abc123" in data["response"]
    assert data["session_id"] == "integration-test-001"
    
    # Verify Security Controller was called
    mock_aws_services['security_controller'].assert_called()
    
    # Verify DynamoDB was queried
    mock_aws_services['dynamodb_table'].get_item.assert_called_once()


# ==================== Integration Test: Process Refund ====================

def test_integration_process_refund_success(client, mock_aws_services):
    """Test complete flow: API → Claude → Tool → Security Controller → DynamoDB"""
    import json
    from unittest.mock import Mock
    
    # Setup DynamoDB mock
    mock_aws_services['dynamodb_table'].get_item.return_value = {
        'Item': {
            'order_id': 'ord-12345',
            'customer_id': 'cust-001',
            'customer_name': 'John Doe',
            'amount': Decimal('500.00'),
            'status': 'completed'
        }
    }
    
    # Setup Bedrock mock responses
    first_response = {
        'body': Mock(read=lambda: json.dumps({
            'content': [
                {
                    'type': 'tool_use',
                    'id': 'tool_001',
                    'name': 'process_refund',
                    'input': {
                        'order_id': 'ord-12345',
                        'amount': 150.00,
                        'reason': 'Customer not satisfied'
                    }
                }
            ],
            'stop_reason': 'tool_use'
        }).encode())
    }
    
    second_response = {
        'body': Mock(read=lambda: json.dumps({
            'content': [
                {
                    'type': 'text',
                    'text': "I've successfully processed a refund of $150.00 for order ord-12345. The transaction ID is txn-abc123."
                }
            ],
            'stop_reason': 'end_turn'
        }).encode())
    }
    
    mock_aws_services['bedrock'].invoke_model.side_effect = [first_response, second_response]
    
    # Make API request
    response = client.post(
        "/v1/agents/payment/action",
        json={
            "message": "Process a refund of $150 for order ord-12345 because customer was not satisfied",
            "session_id": "integration-test-002",
            "context": {
                "user_id": "manager@sentra.com",
                "authorization_level": "manager"
            }
        }
    )
    
    # Assertions
    assert response.status_code == 200
    data = response.json()
    assert "successfully processed" in data["response"].lower()
    assert "150" in data["response"]
    
    # Verify Security Controller was called
    mock_aws_services['security_controller'].assert_called()
    
    # Verify DynamoDB update was called
    mock_aws_services['dynamodb_table'].update_item.assert_called_once()


# ==================== Integration Test: Refund Denied by Policy ====================

def test_integration_process_refund_denied(client, mock_aws_services):
    """Test refund denied by Security Controller (exceeds limit)"""
    import json
    from unittest.mock import Mock
    
    # Mock Security Controller to DENY
    mock_aws_services['security_controller'].return_value = {
        "decision": "DENY",
        "reason": "Refund amount $5000 exceeds manager authorization limit of $200",
        "matched_rules": [{"rule_id": "POLICY_REFUND_LIMIT"}]
    }
    
    # Setup DynamoDB mock
    mock_aws_services['dynamodb_table'].get_item.return_value = {
        'Item': {
            'order_id': 'ord-12345',
            'customer_id': 'cust-001',
            'customer_name': 'John Doe',
            'amount': Decimal('10000.00'),
            'status': 'completed'
        }
    }
    
    # Setup Bedrock mock responses
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
                        'reason': 'Large refund request'
                    }
                }
            ],
            'stop_reason': 'tool_use'
        }).encode())
    }
    
    # Claude receives denial and explains naturally
    second_response = {
        'body': Mock(read=lambda: json.dumps({
            'content': [
                {
                    'type': 'text',
                    'text': "I'm unable to process that $5000 refund because it exceeds the $200 authorization limit for managers. Refunds over $200 require director approval. Would you like me to create an approval request?"
                }
            ],
            'stop_reason': 'end_turn'
        }).encode())
    }
    
    mock_aws_services['bedrock'].invoke_model.side_effect = [first_response, second_response]
    
    # Make API request
    response = client.post(
        "/v1/agents/payment/action",
        json={
            "message": "Process a refund of $5000 for order ord-12345",
            "session_id": "integration-test-003",
            "context": {
                "user_id": "manager@sentra.com",
                "authorization_level": "manager"
            }
        }
    )
    
    # Assertions
    assert response.status_code == 200
    data = response.json()
    assert "unable" in data["response"].lower()
    assert "authorization limit" in data["response"].lower()
    assert "director approval" in data["response"].lower()
    
    # Verify Security Controller was called
    mock_aws_services['security_controller'].assert_called()
    
    # Verify DynamoDB update was NOT called (refund denied)
    mock_aws_services['dynamodb_table'].update_item.assert_not_called()


# ==================== Integration Test: Reverse Refund ====================

def test_integration_reverse_refund(client, mock_aws_services):
    """Test complete flow for reversing a refund"""
    import json
    from unittest.mock import Mock
    
    # Setup DynamoDB mock for query (find by transaction_id)
    mock_aws_services['dynamodb_table'].query.return_value = {
        'Items': [
            {
                'order_id': 'ord-12345',
                'customer_id': 'cust-001',
                'customer_name': 'John Doe',
                'amount': Decimal('500.00'),
                'status': 'completed',
                'refund_amount': Decimal('150.00'),
                'refund_status': 'refunded',
                'transaction_id': 'txn-abc123'
            }
        ]
    }
    
    # Setup Bedrock mock responses
    first_response = {
        'body': Mock(read=lambda: json.dumps({
            'content': [
                {
                    'type': 'tool_use',
                    'id': 'tool_001',
                    'name': 'reverse_refund',
                    'input': {
                        'transaction_id': 'txn-abc123',
                        'reason': 'Accidental refund'
                    }
                }
            ],
            'stop_reason': 'tool_use'
        }).encode())
    }
    
    second_response = {
        'body': Mock(read=lambda: json.dumps({
            'content': [
                {
                    'type': 'text',
                    'text': "I've successfully reversed the refund for transaction txn-abc123. The original refund amount of $150.00 has been reversed."
                }
            ],
            'stop_reason': 'end_turn'
        }).encode())
    }
    
    mock_aws_services['bedrock'].invoke_model.side_effect = [first_response, second_response]
    
    # Make API request
    response = client.post(
        "/v1/agents/payment/action",
        json={
            "message": "Reverse the refund for transaction txn-abc123 because it was accidental",
            "session_id": "integration-test-004",
            "context": {
                "user_id": "director@sentra.com",
                "authorization_level": "director"
            }
        }
    )
    
    # Assertions
    assert response.status_code == 200
    data = response.json()
    assert "reversed" in data["response"].lower()
    assert "txn-abc123" in data["response"]
    
    # Verify DynamoDB query and update were called
    mock_aws_services['dynamodb_table'].query.assert_called_once()
    mock_aws_services['dynamodb_table'].update_item.assert_called_once()


# ==================== Integration Test: Health Check ====================

def test_integration_health_check(client, mock_aws_services):
    """Test health check endpoint"""
    response = client.get("/v1/health")
    
    # Assertions
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "payment-agent"
    assert data["status"] == "ok"
    assert "checks" in data
    assert "dynamodb_orders" in data["checks"]
