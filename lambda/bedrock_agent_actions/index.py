"""
Bedrock Agent Action Group Lambda with Sentra Validation

This Lambda function:
1. Receives tool invocation requests from Bedrock Agent
2. Validates requests with Sentra Security Controller /validate API
3. If DENY: Returns 403 error with reason
4. If ALLOW: Executes tool and returns result

Reference: Workstream 9, Task 3.2
"""

import json
import boto3
import os
import urllib3
from decimal import Decimal
from datetime import datetime
import uuid

# Initialize clients
dynamodb = boto3.resource('dynamodb')
secrets_client = boto3.client('secretsmanager')
http = urllib3.PoolManager()

# Cache for performance
_api_key_cache = None
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


def get_sentra_api_key():
    """Fetch API key from Secrets Manager (cached)"""
    global _api_key_cache
    if _api_key_cache:
        return _api_key_cache

    secret_name = os.environ['SENTRA_API_KEY_SECRET']
    response = secrets_client.get_secret_value(SecretId=secret_name)
    raw = response['SecretString']
    # Tolerate both secret shapes: JSON {"key": "..."} (the console key's
    # convention) and a plain-string key (the dedicated /v1/validate key is a
    # CDK-generated plain string). Either way we end up with the raw API key.
    try:
        parsed = json.loads(raw)
        _api_key_cache = parsed['key'] if isinstance(parsed, dict) and 'key' in parsed else raw
    except (json.JSONDecodeError, TypeError):
        _api_key_cache = raw
    return _api_key_cache


_DEFAULT_AGENT_ID = "sentra-mvp-customer-service-agent"


def validate_with_sentra(tool_name, tool_params, user_input, session_id, agent_id=None, supplied_request_id=None):
    """
    Validate action with Sentra Security Controller.

    Args:
        tool_name: Name of the tool being invoked
        tool_params: Parameters for the tool
        user_input: Original user input text
        session_id: Session ID for tracking
        agent_id: Bedrock agent name (extracted from the action group event by
            handler()). When None, falls back to the legacy default. This is
            critical for cross-cloud demos that use multiple Bedrock agents
            (secured / unsecured / naive) sharing the same Lambda — without
            this every invocation would report under the same agent_id and the
            audit log would lose the distinction (Workstream 15 M5 fix).
        supplied_request_id: Caller-originated request_id (Workstream 17 /
            LLD 17 §9.1). When the runner generates a request_id and threads
            it via Bedrock sessionAttributes, the Lambda echoes it back here
            so every Sentra signal + connector edge signal correlates to one
            logical invocation. None → Lambda generates a UUID (legacy path).

    Returns:
        dict: {'decision': 'ALLOW'/'DENY', 'reason': str, ...}
    """
    try:
        # Build payload matching Sentra ValidationRequest schema.
        # request_id: prefer the runner-threaded value from sessionAttributes
        # (Workstream 17 / LLD 17 §9.1) so every signal emitted by Sentra +
        # connectors correlates to one logical agent invocation. Falls back to
        # a Lambda-generated UUID for callers that don't thread it yet
        # (e.g. the demo orchestrator's `prompts:` block).
        request_id = supplied_request_id or f"bedrock-{uuid.uuid4().hex[:12]}"
        payload = {
            "request_id": request_id,
            "session_id": session_id,
            "agent_id": agent_id or _DEFAULT_AGENT_ID,
            "tool_name": tool_name,
            "tool_params": tool_params,
            "user_input": user_input,
            "timestamp": datetime.utcnow().isoformat() + 'Z',
            "operation_type": "WRITE" if "refund" in tool_name else "READ"
        }

        headers = {
            "Content-Type": "application/json",
            "x-api-key": get_sentra_api_key()
        }

        response = http.request(
            'POST',
            os.environ['SENTRA_API_ENDPOINT'],
            body=json.dumps(payload).encode('utf-8'),
            headers=headers,
            # Cold-start tolerance (WS18 follow-up 2026-05-30): 5s was tight
            # — first invoke of the day paid container init + Secrets Manager
            # fetch + first HTTPS connection in series, regularly exceeding 5s
            # and forcing fail-secure DENY on legitimate baseline probes.
            # 15s comfortably covers cold-start; warm calls still return in
            # <1s so end-user latency is unchanged. SnapStart (Python 3.12+)
            # will reduce cold-start to ~200ms — tracked as a follow-up
            # workstream so we can ship behind a versioned alias model.
            timeout=15.0
        )

        if response.status == 200:
            result = json.loads(response.data.decode('utf-8'))
            print(f"Sentra validation: {result}")
            return result
        else:
            # Fail secure: DENY on error
            print(f"Sentra validation error: HTTP {response.status}")
            return {
                "decision": "DENY",
                "reason": f"Validation service error: {response.status}"
            }

    except Exception as e:
        # Fail secure: DENY on exception
        print(f"Sentra validation exception: {str(e)}")
        return {
            "decision": "DENY",
            "reason": f"Validation service unavailable: {str(e)}"
        }


def query_customers(state):
    """Query customers by state"""
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
        print(f"Found {len(items)} customers in state {state}")
        return {
            'success': True,
            'data': items,
            'count': len(items)
        }
    except Exception as e:
        print(f"Error querying customers: {str(e)}")
        return {'success': False, 'error': str(e)}


def get_order_details(order_id):
    """Get order details by ID"""
    try:
        orders_table = get_orders_table()
        response = orders_table.get_item(Key={'order_id': order_id})
        if 'Item' in response:
            print(f"Found order: {order_id}")
            return {'success': True, 'data': response['Item']}
        else:
            print(f"Order not found: {order_id}")
            return {'success': False, 'error': 'Order not found'}
    except Exception as e:
        print(f"Error getting order details: {str(e)}")
        return {'success': False, 'error': str(e)}


def process_refund(order_id, amount):
    """Process refund (demo - returns confirmation)"""
    print(f"Processing refund: ${amount} for order {order_id}")
    return {
        'success': True,
        'message': f'Refund of ${amount} processed for order {order_id}',
        'refund_id': f'REF-{order_id}',
        'amount': amount
    }


def handler(event, context):
    """
    Bedrock Agent Action Group handler with Sentra validation.

    Flow:
    1. Extract tool call details from event
    2. Validate with Sentra Security Controller
    3. If DENY: Return 403 error with reason
    4. If ALLOW: Execute tool and return result

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
    print(f"Received event: {json.dumps(event)}")

    # Extract request details
    api_path = event.get('apiPath', '')
    session_id = event.get('sessionId', 'unknown')
    input_text = event.get('inputText', '')
    action_group = event.get('actionGroup', 'unknown')
    # Pull the invoking Bedrock agent's name from the event. Bedrock passes
    # `agent: {"name": "<agent-name>", "id": "...", ...}` for every action
    # group invocation. Forwarding the real name to Sentra means the audit
    # log distinguishes secured/naive/etc. — critical when one Lambda backs
    # multiple agents (WS15 M5 naive-agent demo).
    agent_block = event.get('agent') or {}
    invoking_agent_id = agent_block.get('name') or _DEFAULT_AGENT_ID

    # Workstream 17 / LLD 17 §9.1.3 — pull the runner-threaded request_id from
    # sessionAttributes. Bedrock Agent forwards sessionAttributes to every
    # Action Group invocation in the session. Without this, every tool call
    # within an invocation would get a Lambda-generated UUID and the
    # connector's bedrock_guardrail signal would have no matching row to
    # group with — the multi-signal substrate would be useless.
    session_attrs = event.get('sessionAttributes') or {}
    supplied_request_id = session_attrs.get('sentra_request_id')
    print(
        f"request_id source: "
        f"{'sessionAttributes' if supplied_request_id else 'generated'}"
    )

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
    print(f"Tool invocation: {tool_name}, Params: {params}, Session: {session_id}")

    # ========================================================================
    # SENTRA VALIDATION
    # ========================================================================
    validation_result = validate_with_sentra(
        tool_name=tool_name,
        tool_params=params,
        user_input=input_text,
        session_id=session_id,
        agent_id=invoking_agent_id,
        supplied_request_id=supplied_request_id,
    )

    print(f"Validation decision: {validation_result.get('decision')}")

    # Check if request was blocked
    if validation_result.get('decision') == 'DENY':
        reason = validation_result.get('reason', 'Request blocked by security policy')
        print(f"❌ REQUEST DENIED: {reason}")

        # Return 403 Forbidden response
        return {
            'messageVersion': '1.0',
            'response': {
                'actionGroup': action_group,
                'apiPath': api_path,
                'httpMethod': 'POST',
                'httpStatusCode': 403,
                'responseBody': {
                    'application/json': {
                        'body': json.dumps({
                            'success': False,
                            'error': f'⚠️ {reason}',
                            'decision': 'DENY',
                            'request_id': validation_result.get('request_id')
                        })
                    }
                }
            }
        }

    # ========================================================================
    # EXECUTE ACTION (ALLOWED)
    # ========================================================================
    print(f"✅ REQUEST ALLOWED - Executing {tool_name}")

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
    else:
        print(f"Unknown tool: {tool_name}")
        result = {'success': False, 'error': f'Unknown tool: {tool_name}'}

    # Return success response (200 OK)
    return {
        'messageVersion': '1.0',
        'response': {
            'actionGroup': action_group,
            'apiPath': api_path,
            'httpMethod': 'POST',
            'httpStatusCode': 200,
            'responseBody': {
                'application/json': {
                    'body': json.dumps(
                        result,
                        default=lambda x: float(x) if isinstance(x, Decimal) else str(x)
                    )
                }
            }
        }
    }
