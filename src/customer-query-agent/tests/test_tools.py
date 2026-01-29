"""
Unit tests for Customer Query Agent Tools
Tests all 4 tools with mocked DynamoDB and Security Controller
"""

import pytest
from unittest.mock import patch, MagicMock
from decimal import Decimal

from app.tools.query_customers import query_customers
from app.tools.query_orders import query_orders
from app.tools.get_customer_by_id import get_customer_by_id
from app.tools.call_payment_agent import call_payment_agent
from app.security_integration import (
    set_request_context,
    set_multi_agent_context,
    clear_request_context,
    get_conversation_id,
    get_call_depth
)


# ==================== Test Fixtures ====================

@pytest.fixture
def mock_request_context():
    """Set up request context for tests"""
    set_request_context(
        request_id="test-req-123",
        session_id="test-session-456",
        user_input="Test query",
        context={"user_id": "test@sentra.com"}
    )
    yield
    clear_request_context()


@pytest.fixture
def mock_security_allow():
    """Mock Security Controller to always ALLOW"""
    with patch('app.security_integration.call_security_controller') as mock:
        mock.return_value = {
            "decision": "ALLOW",
            "reason": "No policy violations"
        }
        yield mock


# ==================== Tool 1: query_customers Tests ====================

@patch('app.tools.query_customers.boto3.resource')
def test_query_customers_by_state(mock_boto3, mock_request_context, mock_security_allow):
    """Test querying customers by state"""
    # Mock DynamoDB response
    mock_table = MagicMock()
    mock_table.scan.return_value = {
        'Items': [
            {'customer_id': 'C001', 'name': 'Acme Corp', 'state': 'CA', 'ssn': '123-45-6789'},
            {'customer_id': 'C002', 'name': 'TechStart Inc', 'state': 'CA', 'ssn': '987-65-4321'}
        ]
    }
    mock_boto3.return_value.Table.return_value = mock_table

    # Execute tool
    result = query_customers(filters={'state': 'CA'})

    # Verify results
    assert len(result) == 2
    assert result[0]['customer_id'] == 'C001'
    assert result[0]['state'] == 'CA'

    # Verify SSN is masked
    assert result[0]['ssn'] == 'XXX-XX-XXXX'
    assert result[1]['ssn'] == 'XXX-XX-XXXX'

    # Verify DynamoDB was called correctly
    assert mock_table.scan.called
    scan_args = mock_table.scan.call_args[1]
    assert scan_args['Limit'] == 100  # Default limit


@patch('app.tools.query_customers.boto3.resource')
def test_query_customers_with_limit(mock_boto3, mock_request_context, mock_security_allow):
    """Test querying customers with custom limit"""
    mock_table = MagicMock()
    mock_table.scan.return_value = {'Items': []}
    mock_boto3.return_value.Table.return_value = mock_table

    # Execute tool with custom limit
    query_customers(filters={'limit': 50})

    # Verify limit was applied
    scan_args = mock_table.scan.call_args[1]
    assert scan_args['Limit'] == 50


@patch('app.tools.query_customers.boto3.resource')
def test_query_customers_max_limit_enforced(mock_boto3, mock_request_context, mock_security_allow):
    """Test that max limit of 1000 is enforced"""
    mock_table = MagicMock()
    mock_table.scan.return_value = {'Items': []}
    mock_boto3.return_value.Table.return_value = mock_table

    # Try to query with limit > 1000
    query_customers(filters={'limit': 5000})

    # Verify limit was capped at 1000
    scan_args = mock_table.scan.call_args[1]
    assert scan_args['Limit'] == 1000


# ==================== Tool 2: query_orders Tests ====================

@patch('app.tools.query_orders.boto3.resource')
def test_query_orders_by_customer_id(mock_boto3, mock_request_context, mock_security_allow):
    """Test querying orders by customer_id using GSI"""
    # Mock DynamoDB response
    mock_table = MagicMock()
    mock_table.query.return_value = {
        'Items': [
            {
                'order_id': 'ORD-001',
                'customer_id': 'C001',
                'amount': Decimal('150.50'),
                'status': 'completed'
            }
        ]
    }
    mock_boto3.return_value.Table.return_value = mock_table

    # Execute tool
    result = query_orders(filters={'customer_id': 'C001'})

    # Verify results
    assert len(result) == 1
    assert result[0]['order_id'] == 'ORD-001'
    assert result[0]['customer_id'] == 'C001'

    # Verify Decimal was converted to float
    assert isinstance(result[0]['amount'], float)
    assert result[0]['amount'] == 150.50

    # Verify GSI was used
    assert mock_table.query.called
    query_args = mock_table.query.call_args[1]
    assert query_args['IndexName'] == 'customer-index'


@patch('app.tools.query_orders.boto3.resource')
def test_query_orders_by_status(mock_boto3, mock_request_context, mock_security_allow):
    """Test querying orders by status (scan operation)"""
    mock_table = MagicMock()
    mock_table.scan.return_value = {'Items': []}
    mock_boto3.return_value.Table.return_value = mock_table

    # Execute tool
    query_orders(filters={'status': 'completed'})

    # Verify scan was used (no customer_id)
    assert mock_table.scan.called


@patch('app.tools.query_orders.boto3.resource')
def test_query_orders_with_amount_filters(mock_boto3, mock_request_context, mock_security_allow):
    """Test querying orders with min/max amount filters"""
    mock_table = MagicMock()
    mock_table.scan.return_value = {'Items': []}
    mock_boto3.return_value.Table.return_value = mock_table

    # Execute tool
    query_orders(filters={'min_amount': 100.0, 'max_amount': 500.0})

    # Verify scan was called
    assert mock_table.scan.called


# ==================== Tool 3: get_customer_by_id Tests ====================

@patch('app.tools.get_customer_by_id.boto3.resource')
def test_get_customer_by_id_found(mock_boto3, mock_request_context, mock_security_allow):
    """Test getting customer by ID - customer exists"""
    # Mock DynamoDB response
    mock_table = MagicMock()
    mock_table.get_item.return_value = {
        'Item': {
            'customer_id': 'C001',
            'name': 'Acme Corp',
            'email': 'contact@acme.com',
            'ssn': '123-45-6789'
        }
    }
    mock_boto3.return_value.Table.return_value = mock_table

    # Execute tool
    result = get_customer_by_id(customer_id='C001')

    # Verify result
    assert result is not None
    assert result['customer_id'] == 'C001'
    assert result['name'] == 'Acme Corp'

    # Verify SSN is masked
    assert result['ssn'] == 'XXX-XX-XXXX'

    # Verify DynamoDB was called correctly
    assert mock_table.get_item.called
    get_args = mock_table.get_item.call_args[1]
    assert get_args['Key'] == {'customer_id': 'C001'}


@patch('app.tools.get_customer_by_id.boto3.resource')
def test_get_customer_by_id_not_found(mock_boto3, mock_request_context, mock_security_allow):
    """Test getting customer by ID - customer not found"""
    # Mock DynamoDB response (no Item)
    mock_table = MagicMock()
    mock_table.get_item.return_value = {}
    mock_boto3.return_value.Table.return_value = mock_table

    # Execute tool
    result = get_customer_by_id(customer_id='NONEXISTENT')

    # Verify result is None
    assert result is None


# ==================== Tool 4: call_payment_agent Tests ====================

@patch('app.tools.call_payment_agent.requests.post')
def test_call_payment_agent_success(mock_post, mock_request_context, mock_security_allow):
    """Test calling Payment Agent - successful response"""
    # Mock Payment Agent response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "response": "Refund processed successfully",
        "data": {"transaction_id": "txn-123"}
    }
    mock_post.return_value = mock_response

    # Execute tool
    result = call_payment_agent(
        message="Process refund of $150 for order ORD-001",
        session_id="test-session-456"
    )

    # Verify result
    assert result['response'] == "Refund processed successfully"
    assert result['data']['transaction_id'] == "txn-123"

    # Verify Payment Agent was called correctly
    assert mock_post.called
    call_args = mock_post.call_args

    # Verify URL
    assert "/v1/agents/payment/action" in call_args[0][0]

    # Verify payload
    payload = call_args[1]["json"]
    assert payload["message"] == "Process refund of $150 for order ORD-001"
    assert payload["session_id"] == "test-session-456"
    assert payload["context"]["caller_agent_id"] == "customer-query-agent"
    assert payload["context"]["parent_request_id"] == "test-req-123"


@pytest.fixture
def mock_multi_agent_request_context():
    """Set up multi-agent request context for tests"""
    set_request_context(
        request_id="test-req-123",
        session_id="test-session-456",
        user_input="Process refund for order 123",
        context={
            "user_id": "manager@sentra.com",
            "authorization_level": "manager"
        }
    )
    set_multi_agent_context(
        conversation_id="conv-test-789",
        parent_request_id=None,
        caller_agent_id=None,
        call_depth=0
    )
    yield
    clear_request_context()


@patch('app.tools.call_payment_agent.requests.post')
def test_call_payment_agent_propagates_conversation_id(
    mock_post, mock_multi_agent_request_context, mock_security_allow
):
    """Test that call_payment_agent propagates conversation_id to Payment Agent"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"response": "OK", "data": {}}
    mock_post.return_value = mock_response

    call_payment_agent(
        message="Process refund",
        session_id="test-session-456"
    )

    payload = mock_post.call_args[1]["json"]
    assert payload["context"]["conversation_id"] == "conv-test-789"


@patch('app.tools.call_payment_agent.requests.post')
def test_call_payment_agent_increments_call_depth(
    mock_post, mock_multi_agent_request_context, mock_security_allow
):
    """Test that call_payment_agent increments call_depth"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"response": "OK", "data": {}}
    mock_post.return_value = mock_response

    call_payment_agent(
        message="Process refund",
        session_id="test-session-456"
    )

    payload = mock_post.call_args[1]["json"]
    # Original call_depth is 0, should be incremented to 1
    assert payload["context"]["call_depth"] == 1


@patch('app.tools.call_payment_agent.requests.post')
def test_call_payment_agent_sets_parent_request_id(
    mock_post, mock_multi_agent_request_context, mock_security_allow
):
    """Test that call_payment_agent sets parent_request_id to current request_id"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"response": "OK", "data": {}}
    mock_post.return_value = mock_response

    call_payment_agent(
        message="Process refund",
        session_id="test-session-456"
    )

    payload = mock_post.call_args[1]["json"]
    assert payload["context"]["parent_request_id"] == "test-req-123"
    assert payload["context"]["caller_agent_id"] == "customer-query-agent"


@patch('app.tools.call_payment_agent.requests.post')
def test_call_payment_agent_propagates_user_context(
    mock_post, mock_multi_agent_request_context, mock_security_allow
):
    """Test that call_payment_agent propagates user_id and authorization_level"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"response": "OK", "data": {}}
    mock_post.return_value = mock_response

    call_payment_agent(
        message="Process refund",
        session_id="test-session-456"
    )

    payload = mock_post.call_args[1]["json"]
    assert payload["context"]["user_id"] == "manager@sentra.com"
    assert payload["context"]["authorization_level"] == "manager"


@patch('app.tools.call_payment_agent.requests.post')
def test_call_payment_agent_error_response(mock_post, mock_request_context, mock_security_allow):
    """Test calling Payment Agent - error response"""
    # Mock Payment Agent error response
    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.text = "Security policy violation"
    mock_post.return_value = mock_response

    # Execute tool
    result = call_payment_agent(
        message="Process refund of $5000",
        session_id="test-session-456"
    )

    # Verify error is returned
    assert 'error' in result
    assert result['status_code'] == 403


@patch('app.tools.call_payment_agent.requests.post')
def test_call_payment_agent_connection_error(mock_post, mock_request_context, mock_security_allow):
    """Test calling Payment Agent - connection error"""
    import requests

    # Mock connection error
    mock_post.side_effect = requests.exceptions.ConnectionError("Connection refused")

    # Execute tool
    result = call_payment_agent(
        message="Test message",
        session_id="test-session-456"
    )

    # Verify error is returned
    assert 'error' in result
    assert result['status_code'] == 503
    assert "Failed to communicate" in result['error']


# ==================== Integration Tests ====================

@patch('app.tools.query_customers.boto3.resource')
@patch('app.security_integration.call_security_controller')
def test_tool_with_security_controller_integration(mock_security, mock_boto3, mock_request_context):
    """Test tool execution with Security Controller integration"""
    # Mock Security Controller ALLOW
    mock_security.return_value = {
        "decision": "ALLOW",
        "reason": "No policy violations",
        "request_id": "test-req-123"
    }

    # Mock DynamoDB
    mock_table = MagicMock()
    mock_table.scan.return_value = {'Items': []}
    mock_boto3.return_value.Table.return_value = mock_table

    # Execute tool
    query_customers(filters={'state': 'CA'})

    # Verify Security Controller was called
    assert mock_security.called
    validation_request = mock_security.call_args[0][0]
    assert validation_request['tool_name'] == 'query_customers'
    assert validation_request['request_id'] == 'test-req-123'
    assert validation_request['session_id'] == 'test-session-456'
