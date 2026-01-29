"""
Bedrock Agent Direct Tools Lambda (NO Sentra Validation)

This Lambda function executes tools directly WITHOUT security validation.
Used by the unsecured Bedrock agent for demo comparison purposes.

INTENTIONALLY UNSECURED - For demo only!

Reference: Workstream 13, Task 2.1
"""

import json
import boto3
import os
from decimal import Decimal

# Initialize clients
dynamodb = boto3.resource('dynamodb')

# Cache for performance
_customers_table = None
_orders_table = None


def get_customers_table():
    """Get customers table (cached)"""
    global _customers_table
    if _customers_table is None:
        _customers_table = dynamodb.Table(os.environ['CUSTOMERS_TABLE'])
    return _customers_table


def get_orders_table():
    """Get orders table (cached)"""
    global _orders_table
    if _orders_table is None:
        _orders_table = dynamodb.Table(os.environ['ORDERS_TABLE'])
    return _orders_table


def decimal_default(obj):
    """JSON serializer for Decimal types"""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def query_customers(state):
    """
    Query customers by state - NO ACCESS CONTROL
    Returns all customer data including PII
    """
    try:
        customers_table = get_customers_table()
        response = customers_table.query(
            IndexName='state-index',
            KeyConditionExpression='#st = :state',
            ExpressionAttributeNames={'#st': 'state'},
            ExpressionAttributeValues={':state': state},
            Limit=10
        )
        items = response.get('Items', [])
        print(f"[UNSECURED] Found {len(items)} customers in state {state}")
        
        # NO PII REDACTION - Returns SSN, credit card, etc.
        return {
            'success': True,
            'data': items,
            'count': len(items),
            'warning': 'UNSECURED: Full PII returned without redaction'
        }
    except Exception as e:
        print(f"Error querying customers: {str(e)}")
        return {'success': False, 'error': str(e)}


def get_order_details(order_id):
    """
    Get order details by ID - NO ACCESS CONTROL
    """
    try:
        orders_table = get_orders_table()
        response = orders_table.get_item(Key={'order_id': order_id})
        if 'Item' in response:
            print(f"[UNSECURED] Found order: {order_id}")
            return {
                'success': True,
                'data': response['Item'],
                'warning': 'UNSECURED: No access control applied'
            }
        else:
            print(f"Order not found: {order_id}")
            return {'success': False, 'error': 'Order not found'}
    except Exception as e:
        print(f"Error getting order details: {str(e)}")
        return {'success': False, 'error': str(e)}


def process_refund(order_id, amount):
    """
    Process refund - NO LIMIT CHECK, NO VALIDATION
    Accepts ANY refund amount without security checks
    """
    print(f"[UNSECURED] Processing refund: ${amount} for order {order_id}")
    print(f"[UNSECURED] WARNING: No refund limit enforced!")
    
    # NO REFUND LIMIT CHECK
    # NO PROMPT INJECTION DETECTION
    # NO POLICY VALIDATION
    
    return {
        'success': True,
        'message': f'Refund of ${amount} processed for order {order_id}',
        'refund_id': f'REF-{order_id}',
        'amount': amount,
        'warning': 'UNSECURED: No refund limit enforced - any amount accepted'
    }


def get_customer_data(customer_id):
    """
    Get customer data by ID - NO PII REDACTION
    Returns full customer record including sensitive data
    """
    try:
        customers_table = get_customers_table()
        response = customers_table.get_item(Key={'customer_id': customer_id})
        if 'Item' in response:
            customer = response['Item']
            print(f"[UNSECURED] Returning full customer data for: {customer_id}")
            
            # NO PII REDACTION - Returns everything
            return {
                'success': True,
                'data': {
                    'customer_id': customer.get('customer_id'),
                    'name': customer.get('name'),
                    'email': customer.get('email'),
                    'phone': customer.get('phone'),
                    'address': customer.get('address'),
                    'ssn': customer.get('ssn'),  # EXPOSED!
                    'credit_card': customer.get('credit_card'),  # EXPOSED!
                    'state': customer.get('state'),
                },
                'warning': 'UNSECURED: SSN and credit card exposed without redaction'
            }
        else:
            return {'success': False, 'error': 'Customer not found'}
    except Exception as e:
        print(f"Error getting customer data: {str(e)}")
        return {'success': False, 'error': str(e)}


def handler(event, context):
    """
    Bedrock Agent Action Group handler - NO SECURITY VALIDATION
    
    This handler executes tools directly without any Sentra validation.
    Used for demo comparison to show what happens without security.
    
    Event Format (from Bedrock Agent):
    {
        "messageVersion": "1.0",
        "agent": {...},
        "inputText": "User's original message",
        "sessionId": "session-123",
        "actionGroup": "customer_tools",
        "apiPath": "/query_customers",
        "httpMethod": "POST",
        "parameters": [...],
        "requestBody": {...}
    }
    """
    print(f"[UNSECURED AGENT] Received event: {json.dumps(event)}")
    print("[UNSECURED AGENT] WARNING: No security validation applied!")

    # Extract request details
    api_path = event.get('apiPath', '')
    action_group = event.get('actionGroup', 'unknown')
    http_method = event.get('httpMethod', 'POST')

    # Extract parameters from requestBody (preferred) or parameters array
    params = {}
    request_body = event.get('requestBody', {})
    if request_body:
        content = request_body.get('content', {})
        app_json = content.get('application/json', {})
        properties = app_json.get('properties', [])
        params = {p['name']: p['value'] for p in properties}

    # Fallback to parameters array
    if not params:
        parameters = event.get('parameters', [])
        params = {p['name']: p['value'] for p in parameters}

    tool_name = api_path.replace('/', '')
    print(f"[UNSECURED] Tool invocation: {tool_name}, Params: {params}")

    # ========================================================================
    # DIRECT EXECUTION - NO SECURITY VALIDATION
    # ========================================================================
    
    # Route to appropriate tool handler
    if tool_name == 'query_customers':
        result = query_customers(params.get('state'))
    elif tool_name == 'get_order_details':
        result = get_order_details(params.get('order_id'))
    elif tool_name == 'process_refund':
        result = process_refund(
            params.get('order_id'),
            float(params.get('amount', 0))
        )
    elif tool_name == 'get_customer_data':
        result = get_customer_data(params.get('customer_id'))
    else:
        print(f"Unknown tool: {tool_name}")
        result = {'success': False, 'error': f'Unknown tool: {tool_name}'}

    print(f"[UNSECURED] Execution complete: {result.get('success', False)}")

    # Return success response (200 OK) - Always succeeds without security
    return {
        'messageVersion': '1.0',
        'response': {
            'actionGroup': action_group,
            'apiPath': api_path,
            'httpMethod': http_method,
            'httpStatusCode': 200,
            'responseBody': {
                'application/json': {
                    'body': json.dumps(result, default=decimal_default)
                }
            }
        }
    }
