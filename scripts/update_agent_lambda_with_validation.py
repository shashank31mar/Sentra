#!/usr/bin/env python3
"""
Update Bedrock Agent Lambda with Sentra Validation

This script updates the existing Bedrock Agent action group Lambda function
to call Sentra Security Controller before executing actions.

Correct Architecture (per AWS documentation):
1. Bedrock Agent receives user input
2. Agent calls Action Group Lambda
3. Lambda calls Sentra /validate API
4. If ALLOW: Execute action and return result
5. If DENY: Return blocked message

Reference:
- Workstream 9, Task 3.2 (Updated)
- AWS Bedrock Guardrails documentation 2025
- ApplyGuardrail API best practices

Usage:
    python scripts/update_agent_lambda_with_validation.py
"""

import boto3
import json
import sys

AWS_REGION = 'us-east-1'
AWS_PROFILE = 'sentra'
LAMBDA_FUNCTION_NAME = 'sentra-mvp-bedrock-agent-actions'
SENTRA_API_ENDPOINT = 'https://iw3limi4k7.execute-api.us-east-1.amazonaws.com/prod/v1/validate'
SENTRA_API_KEY = 'OXu1KiE3Xia26QQBgmfHe2SLWcVaNGV16QxwkVKf'

# New Lambda code with Sentra validation
LAMBDA_CODE = '''
import json
import boto3
import os
import requests
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
customers_table = dynamodb.Table(os.environ['CUSTOMERS_TABLE'])
orders_table = dynamodb.Table(os.environ['ORDERS_TABLE'])

# Sentra validation configuration
SENTRA_API_ENDPOINT = "''' + SENTRA_API_ENDPOINT + '''"
SENTRA_API_KEY = "''' + SENTRA_API_KEY + '''"

def decimal_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError

def validate_with_sentra(tool_name, tool_params, user_input, session_id):
    """
    Validate action with Sentra Security Controller.

    Returns:
        dict: {'decision': 'ALLOW'/'DENY', 'reason': str, ...}
    """
    try:
        payload = {
            "agent_id": "bedrock-customer-service-agent",
            "session_id": session_id,
            "user_input": user_input,
            "tool_name": tool_name,
            "tool_params": tool_params,
            "operation_type": "WRITE" if "refund" in tool_name else "READ"
        }

        headers = {
            "Content-Type": "application/json",
            "x-api-key": SENTRA_API_KEY
        }

        response = requests.post(
            SENTRA_API_ENDPOINT,
            json=payload,
            headers=headers,
            timeout=5
        )

        if response.status_code == 200:
            return response.json()
        else:
            # On error, default to DENY for safety
            return {
                "decision": "DENY",
                "reason": f"Validation service error: {response.status_code}"
            }

    except Exception as e:
        # On exception, default to DENY for safety
        return {
            "decision": "DENY",
            "reason": f"Validation service unavailable: {str(e)}"
        }

def query_customers(state):
    """Query customers by state"""
    try:
        response = customers_table.query(
            IndexName='state-index',
            KeyConditionExpression='#st = :state',
            ExpressionAttributeNames={'#st': 'state'},
            ExpressionAttributeValues={':state': state},
            Limit=10
        )
        return {
            'success': True,
            'data': response.get('Items', []),
            'count': len(response.get('Items', []))
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}

def get_order_details(order_id):
    """Get order details by ID"""
    try:
        response = orders_table.get_item(Key={'order_id': order_id})
        if 'Item' in response:
            return {'success': True, 'data': response['Item']}
        else:
            return {'success': False, 'error': 'Order not found'}
    except Exception as e:
        return {'success': False, 'error': str(e)}

def process_refund(order_id, amount):
    """Process refund (demo - just returns confirmation)"""
    return {
        'success': True,
        'message': f'Refund of ${amount} processed for order {order_id}',
        'refund_id': f'REF-{order_id}'
    }

def handler(event, context):
    """
    Lambda handler for Bedrock Agent action group with Sentra validation.

    Flow:
    1. Extract action details from event
    2. Validate with Sentra Security Controller
    3. If ALLOW: Execute action
    4. If DENY: Return blocked message
    """
    print(f"Received event: {json.dumps(event)}")

    # Extract request details
    api_path = event.get('apiPath', '')
    http_method = event.get('httpMethod', 'POST')
    session_id = event.get('sessionId', 'unknown')
    input_text = event.get('inputText', '')

    # Extract parameters
    params = {}
    request_body = event.get('requestBody', {})
    if request_body:
        content = request_body.get('content', {})
        app_json = content.get('application/json', {})
        properties = app_json.get('properties', [])
        params = {p['name']: p['value'] for p in properties}

    if not params:
        parameters = event.get('parameters', [])
        params = {p['name']: p['value'] for p in parameters}

    # Determine tool name from API path
    tool_name = api_path.replace('/', '')

    print(f"Tool: {tool_name}, Params: {params}, Session: {session_id}")

    # ===================================================================
    # SENTRA VALIDATION (NEW)
    # ===================================================================
    validation_result = validate_with_sentra(
        tool_name=tool_name,
        tool_params=params,
        user_input=input_text,
        session_id=session_id
    )

    print(f"Validation result: {json.dumps(validation_result)}")

    # Check if blocked
    if validation_result.get('decision') == 'DENY':
        reason = validation_result.get('reason', 'Request blocked by security policy')
        print(f"Request DENIED: {reason}")

        # Return blocked response
        return {
            'messageVersion': '1.0',
            'response': {
                'actionGroup': event.get('actionGroup'),
                'apiPath': api_path,
                'httpMethod': http_method,
                'httpStatusCode': 403,
                'responseBody': {
                    'application/json': {
                        'body': json.dumps({
                            'success': False,
                            'error': f'⚠️ {reason}',
                            'decision': 'DENY'
                        })
                    }
                }
            }
        }

    # ===================================================================
    # EXECUTE ACTION (ALLOW)
    # ===================================================================
    print(f"Request ALLOWED - Executing {tool_name}")

    # Route to appropriate handler
    if api_path == '/query_customers':
        result = query_customers(params.get('state'))
    elif api_path == '/get_order_details':
        result = get_order_details(params.get('order_id'))
    elif api_path == '/process_refund':
        result = process_refund(
            params.get('order_id'),
            float(params.get('amount', 0))
        )
    else:
        result = {'success': False, 'error': f'Unknown API path: {api_path}'}

    # Return success response
    return {
        'messageVersion': '1.0',
        'response': {
            'actionGroup': event.get('actionGroup'),
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
'''


def update_lambda_function():
    """Update Lambda function code with Sentra validation."""

    print("="*70)
    print("🔄 Updating Bedrock Agent Lambda with Sentra Validation")
    print("="*70)
    print(f"Function: {LAMBDA_FUNCTION_NAME}")
    print(f"Sentra API: {SENTRA_API_ENDPOINT}")
    print("="*70 + "\n")

    session = boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)
    lambda_client = session.client('lambda')

    try:
        # Update function code
        print("📝 Updating Lambda function code...")

        response = lambda_client.update_function_code(
            FunctionName=LAMBDA_FUNCTION_NAME,
            ZipFile=create_deployment_package(LAMBDA_CODE)
        )

        print(f"✅ Lambda function updated successfully!")
        print(f"   Function ARN: {response['FunctionArn']}")
        print(f"   Last Modified: {response['LastModified']}")
        print(f"   Code Size: {response['CodeSize']} bytes")

        # Add requests library as layer (if needed)
        print("\n📦 Checking for requests library...")
        print("   ℹ️  Note: You may need to add a Lambda layer with 'requests' library")
        print("   ℹ️  Or package 'requests' in the deployment zip")

        print("\n✅ Update complete!")
        print("\n📋 Next steps:")
        print("   1. Test the agent with a simple query")
        print("   2. Verify Sentra validation is being called")
        print("   3. Check CloudWatch logs for validation traces")

        return True

    except Exception as e:
        print(f"❌ Failed to update Lambda function: {e}")
        return False


def create_deployment_package(code: str) -> bytes:
    """Create a simple deployment package (inline code only)."""
    import zipfile
    import io

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr('index.py', code)

    return zip_buffer.getvalue()


if __name__ == '__main__':
    print("\n⚠️  WARNING: This will update the Lambda function code.")
    print("   Make sure you have tested the new code locally first.\n")

    response = input("Continue? (yes/no): ")
    if response.lower() != 'yes':
        print("Aborted.")
        sys.exit(0)

    success = update_lambda_function()
    sys.exit(0 if success else 1)
