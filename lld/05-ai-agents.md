# LLD 07: AI Agents - Customer Query & Payment Agents

**Version:** 1.0
**Last Updated:** 2025-11-20
**Status:** Ready for Implementation
**Prerequisites:** [LLD 02: API Gateway](./02-api-gateway.md), [LLD 03: Security Controller](./03-security-controller.md)

**Note:** Agent metadata (configuration, status, version) is stored in `sentra-agent-registry` table (see [LLD 06](./06-data-model-v2.md)). This LLD focuses on agent runtime behavior and tool execution logic.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Unified Agent Interface](#2-unified-agent-interface)
3. [Customer Query Agent](#3-customer-query-agent)
4. [Payment Agent](#4-payment-agent)
5. [Security Controller Integration](#5-security-controller-integration)
6. [Agent Tools](#6-agent-tools)
7. [Data Models](#7-data-models)
8. [Error Handling](#8-error-handling)
9. [Configuration](#9-configuration)
10. [Monitoring & Observability](#10-monitoring--observability)

---

## 1. Overview

### 1.1 Purpose

The **Customer Query Agent** and **Payment Agent** are AI-powered demo agents for the Sentra MVP. They demonstrate:
- Real-time security validation via Security Controller
- Natural language processing using AWS Bedrock (Claude Sonnet)
- Tool-based actions with DynamoDB backend
- Multi-agent workflow coordination

### 1.2 Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      API Gateway                             │
│  /v1/agents/customer-query/query                            │
│  /v1/agents/customer-query/action                           │
│  /v1/agents/payment/query                                    │
│  /v1/agents/payment/action                                   │
└────────────┬─────────────────┬────────────────────────────────┘
             │                 │
             ▼                 ▼
   ┌────────────────┐  ┌────────────────┐
   │ Customer Query │  │ Payment Agent  │
   │     Agent      │  │                │
   │  (ECS:8080)    │  │  (ECS:8080)    │
   └────┬───────────┘  └────┬───────────┘
        │                   │
        │ Validate tools    │ Validate tools
        │ before execution  │ before execution
        │                   │
        ▼                   ▼
   ┌────────────────────────────────┐
   │   Security Controller          │
   │   POST /v1/validate            │
   └────────────────────────────────┘
             │
             ▼
   ┌────────────────────────────────┐
   │   DynamoDB + Bedrock           │
   │   - demo-customers             │
   │   - demo-orders                │
   │   - AWS Bedrock (Claude)       │
   └────────────────────────────────┘
```

### 1.3 Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Unified Interface** | All agents expose `/query` and `/action` endpoints for consistency |
| **Security Controller Integration** | All tool calls validated before execution (no direct tool execution) |
| **AWS Bedrock Claude Sonnet 4.5** | Model: `anthropic.claude-sonnet-4-5-20250929-v1:0` (ACTIVE). Powerful LLM for natural language understanding with tool use |
| **Port 8080 for Both** | Consistent containerization pattern |
| **DynamoDB Backend** | Serverless, scalable data store for demo data |
| **FastAPI Framework** | High-performance Python web framework with async support |

---

## 2. Unified Agent Interface

### 2.1 API Contract

All agents follow the **same standardized interface**:

#### Endpoint: POST /v1/agents/{agent-id}/query

**Purpose:** Read operations (queries, data retrieval)

**Request Schema:**
```json
{
  "message": "Natural language query (1-10000 chars)",
  "session_id": "optional-session-identifier",
  "context": {
    "user_id": "optional-user-context",
    "authorization_level": "optional-authorization"
  }
}
```

**Response Schema (Success):**
```json
{
  "response": "Natural language response from agent",
  "data": {},  // Optional structured data
  "session_id": "session-123",
  "request_id": "req-abc-123"
}
```

**Response Schema (Error):**
```json
{
  "error": "Error message",
  "error_code": "VALIDATION_FAILED",
  "session_id": "session-123",
  "request_id": "req-abc-123"
}
```

#### Endpoint: POST /v1/agents/{agent-id}/action

**Purpose:** Write operations (refunds, updates, deletions)

**Request Schema:** Same as `/query`

**Response Schema:** Same as `/query`

### 2.2 Rate Limits (Applied at API Gateway)

| Endpoint | Rate Limit | Burst | Rationale |
|----------|------------|-------|-----------|
| `/query` | 20 req/min | 40 | Read operations, moderate traffic expected |
| `/action` | 10 req/min | 20 | Write operations, conservative limit for safety |

### 2.3 Common Request Flow

```
User Request
    ↓
API Gateway (/v1/agents/{agent-id}/query or /action)
    ↓
Agent parses natural language message
    ↓
Agent determines which tools to use
    ↓
FOR EACH tool call:
    ↓
    Validate with Security Controller (/v1/validate)
    ↓
    If ALLOW → Execute tool
    If DENY → Return error to user
    ↓
END FOR
    ↓
Return final response to user
```

---

## 3. Customer Query Agent

### 3.1 Purpose

The **Customer Query Agent** provides natural language access to customer and order data.

**Primary Use Cases:**
1. Query customer records (by state, name, email)
2. Query order records (by customer, status, date range)
3. Combine customer + order data (e.g., "show all orders for customers in CA")

**Demo Scenarios:**
- **Scenario 2**: Data Exfiltration Prevention (blocks mass PII queries)
- **Scenario 4**: Multi-Agent Workflow (calls Payment Agent)

### 3.2 Agent Configuration

**Deployment:**
- ECS Fargate Task (2 vCPU, 4 GB RAM)
- Port: 8080
- Image: `{account}.dkr.ecr.{region}.amazonaws.com/sentra/customer-query-agent:latest`

**Environment Variables:**
```python
{
    "PORT": "8080",
    "SERVICE_NAME": "customer-query-agent",
    "DEMO_CUSTOMERS_TABLE": "sentra-dev-demo-customers",
    "DEMO_ORDERS_TABLE": "sentra-dev-demo-orders",
    "SECURITY_CONTROLLER_URL": "http://security-controller.sentra.internal:8080",
    "BEDROCK_MODEL_ID": "anthropic.claude-sonnet-4-5-20250929-v1:0",
    "AWS_REGION": "us-east-1",
    "LOG_LEVEL": "INFO"
}
```

### 3.3 API Endpoints

#### POST /v1/agents/customer-query/query

**Example Request:**
```json
{
  "message": "Show me customers from California",
  "session_id": "session-demo-001"
}
```

**Example Response:**
```json
{
  "response": "Found 42 customers from California",
  "data": {
    "customers": [
      {"customer_id": "C001", "name": "Acme Corp", "state": "CA"},
      {"customer_id": "C002", "name": "TechStart Inc", "state": "CA"}
    ],
    "count": 42
  },
  "session_id": "session-demo-001",
  "request_id": "req-cqa-001"
}
```

#### POST /v1/agents/customer-query/action

**Example Request:**
```json
{
  "message": "Update customer email for C001 to newemail@acme.com",
  "session_id": "session-demo-001"
}
```

**Example Response:**
```json
{
  "response": "Customer email updated successfully",
  "session_id": "session-demo-001",
  "request_id": "req-cqa-002"
}
```

**Note:** Action endpoint exists for consistency but is rarely used (read-only agent).

#### GET /v1/health

**Response:**
```json
{
  "status": "ok",
  "service": "customer-query-agent",
  "timestamp": "2025-11-20T10:00:00Z"
}
```

### 3.4 Agent Architecture

```python
# FastAPI application structure

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import boto3
import uuid

app = FastAPI(title="Customer Query Agent")

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
bedrock = boto3.client('bedrock-runtime')
security_controller = SecurityControllerClient(base_url=os.environ['SECURITY_CONTROLLER_URL'])

# Request/Response models
class AgentRequest(BaseModel):
    message: str
    session_id: str = None
    context: dict = {}

class AgentResponse(BaseModel):
    response: str
    data: dict = {}
    session_id: str
    request_id: str

# Main endpoints
@app.post("/v1/agents/customer-query/query")
async def handle_query(request: AgentRequest) -> AgentResponse:
    """
    Handle natural language queries (read operations)

    Flow:
    1. Generate request_id and session_id (if missing)
    2. Parse user message with Claude (Bedrock)
    3. Claude determines which tools to call
    4. For each tool:
       a. Validate with Security Controller
       b. If ALLOW → execute tool
       c. If DENY → raise error
    5. Aggregate results and return natural language response
    """
    request_id = str(uuid.uuid4())
    session_id = request.session_id or str(uuid.uuid4())

    try:
        # Call Claude to process request
        response = process_with_claude(
            message=request.message,
            session_id=session_id,
            request_id=request_id,
            available_tools=CUSTOMER_QUERY_TOOLS
        )

        return AgentResponse(
            response=response.text,
            data=response.data,
            session_id=session_id,
            request_id=request_id
        )

    except SecurityException as e:
        # Security Controller denied action
        raise HTTPException(status_code=403, detail=str(e))

    except Exception as e:
        # Internal error
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/agents/customer-query/action")
async def handle_action(request: AgentRequest) -> AgentResponse:
    """
    Handle natural language actions (write operations)
    Same flow as /query but with stricter validation
    """
    # Same implementation as handle_query
    # Tools may include update_customer, delete_customer, etc.
    pass

@app.get("/v1/health")
async def health_check():
    """Health check for ALB target group"""
    return {"status": "ok", "service": "customer-query-agent"}
```

### 3.5 Available Tools

**Tool 1: query_customers**
```python
@secured_tool  # Decorator validates with Security Controller
def query_customers(filters: dict) -> list[dict]:
    """
    Query customers from DynamoDB demo-customers table

    Args:
        filters: Dict with optional keys:
            - state: str (e.g., "CA")
            - name_contains: str
            - email_contains: str
            - limit: int (default 100, max 1000)

    Returns:
        List of customer records

    Security Validations:
    - Sigma rule: DATA_EXFILTRATION_MASS_QUERY (no LIMIT = DENY)
    - Sigma rule: PII_SSN_EXPOSURE (SSN in response = DENY)
    """
    table = dynamodb.Table(os.environ['DEMO_CUSTOMERS_TABLE'])

    # Build DynamoDB scan/query params
    params = {}
    if 'state' in filters:
        params['FilterExpression'] = 'state = :state'
        params['ExpressionAttributeValues'] = {':state': filters['state']}

    # Apply limit (default 100)
    params['Limit'] = min(filters.get('limit', 100), 1000)

    response = table.scan(**params)
    return response['Items']
```

**Tool 2: query_orders**
```python
@secured_tool
def query_orders(filters: dict) -> list[dict]:
    """
    Query orders from DynamoDB demo-orders table

    Args:
        filters: Dict with optional keys:
            - customer_id: str
            - status: str (completed, pending, cancelled)
            - min_amount: float
            - max_amount: float
            - limit: int (default 100, max 1000)

    Returns:
        List of order records

    Security Validations:
    - Sigma rule: DATA_EXFILTRATION_MASS_QUERY
    """
    table = dynamodb.Table(os.environ['DEMO_ORDERS_TABLE'])

    params = {'Limit': min(filters.get('limit', 100), 1000)}

    if 'customer_id' in filters:
        # Use GSI for customer_id lookup
        params['IndexName'] = 'customer-index'
        params['KeyConditionExpression'] = 'customer_id = :cid'
        params['ExpressionAttributeValues'] = {':cid': filters['customer_id']}
        response = table.query(**params)
    else:
        response = table.scan(**params)

    return response['Items']
```

**Tool 3: get_customer_by_id**
```python
@secured_tool
def get_customer_by_id(customer_id: str) -> dict:
    """
    Get single customer by ID

    Args:
        customer_id: Customer identifier

    Returns:
        Customer record or None

    Security Validations:
    - None (single record lookup is safe)
    """
    table = dynamodb.Table(os.environ['DEMO_CUSTOMERS_TABLE'])
    response = table.get_item(Key={'customer_id': customer_id})
    return response.get('Item')
```

**Tool 4: call_payment_agent** (Inter-Agent Communication)
```python
@secured_tool
def call_payment_agent(message: str, session_id: str, parent_request_id: str) -> dict:
    """
    Call Payment Agent for refund/payment operations

    Args:
        message: Natural language request for Payment Agent
        session_id: Session ID (passed through)
        parent_request_id: Current request ID (for audit trail)

    Returns:
        Payment Agent response

    Security Validations:
    - Security Controller validates the inter-agent call
    - Payment Agent validates the tool call again
    """
    response = requests.post(
        "http://payment-agent.sentra.internal:8080/v1/agents/payment/action",
        json={
            "message": message,
            "session_id": session_id,
            "context": {
                "caller_agent_id": "customer-query-agent",
                "parent_request_id": parent_request_id
            }
        }
    )
    return response.json()
```

---

## 4. Payment Agent

### 4.1 Purpose

The **Payment Agent** handles payment operations (refunds, transaction queries).

**Primary Use Cases:**
1. Process refunds (with authorization checks)
2. Query refund status
3. Query transaction history

**Demo Scenarios:**
- **Scenario 3**: Business Rule Enforcement (refund limit $200 for managers)
- **Scenario 4**: Multi-Agent Workflow (called by Customer Query Agent)

### 4.2 Agent Configuration

**Deployment:**
- ECS Fargate Task (2 vCPU, 4 GB RAM)
- Port: 8080
- Image: `{account}.dkr.ecr.{region}.amazonaws.com/sentra/payment-agent:latest`

**Environment Variables:**
```python
{
    "PORT": "8080",
    "SERVICE_NAME": "payment-agent",
    "DEMO_ORDERS_TABLE": "sentra-dev-demo-orders",
    "SECURITY_CONTROLLER_URL": "http://security-controller.sentra.internal:8080",
    "BEDROCK_MODEL_ID": "anthropic.claude-sonnet-4-5-20250929-v1:0",
    "AWS_REGION": "us-east-1",
    "LOG_LEVEL": "INFO"
}
```

### 4.3 API Endpoints

#### POST /v1/agents/payment/query

**Example Request:**
```json
{
  "message": "Check refund status for order ORD-2024-001",
  "session_id": "session-demo-002"
}
```

**Example Response:**
```json
{
  "response": "Refund of $150.00 processed on 2024-11-15. Status: completed",
  "data": {
    "order_id": "ORD-2024-001",
    "refund_amount": 150.00,
    "refund_date": "2024-11-15T10:30:00Z",
    "status": "completed"
  },
  "session_id": "session-demo-002",
  "request_id": "req-pa-001"
}
```

#### POST /v1/agents/payment/action

**Example Request (Success):**
```json
{
  "message": "Process refund of $150 for order ORD-2024-001",
  "session_id": "session-demo-002",
  "context": {
    "user_id": "manager@sentra.com",
    "authorization_level": "manager"
  }
}
```

**Example Response (Success):**
```json
{
  "response": "Refund of $150.00 processed successfully",
  "data": {
    "transaction_id": "txn-789",
    "order_id": "ORD-2024-001",
    "refund_amount": 150.00
  },
  "session_id": "session-demo-002",
  "request_id": "req-pa-002"
}
```

**Example Request (Denied - Exceeds Limit):**
```json
{
  "message": "Process refund of $5000 for order ORD-2024-002",
  "session_id": "session-demo-003",
  "context": {
    "user_id": "manager@sentra.com",
    "authorization_level": "manager"
  }
}
```

**Example Response (Denied):**
```json
{
  "error": "Security validation failed: Refund amount $5000 exceeds manager authorization limit of $200",
  "error_code": "POLICY_VIOLATION",
  "matched_policy": "refund-limit-policy-v1",
  "session_id": "session-demo-003",
  "request_id": "req-pa-003"
}
```

#### GET /v1/health

**Response:**
```json
{
  "status": "ok",
  "service": "payment-agent",
  "timestamp": "2025-11-20T10:00:00Z"
}
```

### 4.4 Available Tools

**Tool 1: query_refund_status**
```python
@secured_tool
def query_refund_status(order_id: str) -> dict:
    """
    Query refund status for an order

    Args:
        order_id: Order identifier

    Returns:
        Refund details or None

    Security Validations:
    - None (single record lookup is safe)
    """
    table = dynamodb.Table(os.environ['DEMO_ORDERS_TABLE'])
    response = table.get_item(Key={'order_id': order_id})
    order = response.get('Item')

    if not order:
        return None

    return {
        "order_id": order_id,
        "refund_amount": order.get('refund_amount'),
        "refund_date": order.get('refund_date'),
        "status": order.get('refund_status', 'not_refunded')
    }
```

**Tool 2: process_refund**
```python
@secured_tool
def process_refund(order_id: str, amount: float, reason: str) -> dict:
    """
    Process a refund for an order

    Args:
        order_id: Order identifier
        amount: Refund amount
        reason: Refund reason

    Returns:
        Transaction details

    Security Validations:
    - Policy: refund-limit-policy-v1 (manager limit $200)
    - Sigma rule: BUSINESS_RULE_REFUND_LIMIT
    - Session context: authorization_level checked
    """
    table = dynamodb.Table(os.environ['DEMO_ORDERS_TABLE'])

    # Get order
    response = table.get_item(Key={'order_id': order_id})
    order = response.get('Item')

    if not order:
        raise ValueError(f"Order {order_id} not found")

    if order.get('status') != 'completed':
        raise ValueError(f"Order {order_id} is not in completed status")

    if amount > order['amount']:
        raise ValueError(f"Refund amount ${amount} exceeds order total ${order['amount']}")

    # Generate transaction ID
    transaction_id = f"txn-{uuid.uuid4().hex[:8]}"

    # Update order with refund details
    table.update_item(
        Key={'order_id': order_id},
        UpdateExpression='SET refund_amount = :amount, refund_date = :date, refund_status = :status, transaction_id = :txn',
        ExpressionAttributeValues={
            ':amount': amount,
            ':date': datetime.utcnow().isoformat(),
            ':status': 'refunded',
            ':txn': transaction_id
        }
    )

    return {
        "transaction_id": transaction_id,
        "order_id": order_id,
        "refund_amount": amount,
        "status": "success"
    }
```

**Tool 3: reverse_refund** (Rollback Capability)
```python
@secured_tool
def reverse_refund(transaction_id: str, reason: str) -> dict:
    """
    Reverse a refund (manual rollback)

    Args:
        transaction_id: Transaction identifier to reverse
        reason: Rollback reason

    Returns:
        Rollback confirmation

    Security Validations:
    - Policy: rollback-policy-v1 (requires director authorization)
    """
    table = dynamodb.Table(os.environ['DEMO_ORDERS_TABLE'])

    # Find order by transaction_id (GSI)
    response = table.query(
        IndexName='transaction-index',
        KeyConditionExpression='transaction_id = :txn',
        ExpressionAttributeValues={':txn': transaction_id}
    )

    if not response.get('Items'):
        raise ValueError(f"Transaction {transaction_id} not found")

    order = response['Items'][0]

    # Reverse refund
    table.update_item(
        Key={'order_id': order['order_id']},
        UpdateExpression='REMOVE refund_amount, refund_date, transaction_id SET refund_status = :status, rollback_reason = :reason, rollback_date = :date',
        ExpressionAttributeValues={
            ':status': 'refund_reversed',
            ':reason': reason,
            ':date': datetime.utcnow().isoformat()
        }
    )

    return {
        "order_id": order['order_id'],
        "transaction_id": transaction_id,
        "status": "reversed",
        "reason": reason
    }
```

---

## 5. Security Controller Integration

### 5.1 @secured_tool Decorator Pattern

All tools use the `@secured_tool` decorator to integrate with Security Controller:

```python
import functools
import requests
import os
from typing import Callable, Any

def secured_tool(func: Callable) -> Callable:
    """
    Decorator that validates tool calls with Security Controller before execution

    Flow:
    1. Intercept function call
    2. Send validation request to Security Controller
    3. If ALLOW → execute function
    4. If DENY → raise SecurityException (do NOT execute)
    5. Log audit trail
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Get current request context
        request_id = get_current_request_id()
        session_id = get_current_session_id()
        agent_id = os.environ['SERVICE_NAME']
        user_input = get_current_user_input()

        # Build validation request
        validation_request = {
            "request_id": request_id,
            "session_id": session_id,
            "agent_id": agent_id,
            "user_input": user_input,
            "tool_name": func.__name__,
            "tool_params": kwargs,
            "context": get_current_context()
        }

        # Call Security Controller
        response = requests.post(
            f"{os.environ['SECURITY_CONTROLLER_URL']}/v1/validate",
            json=validation_request,
            timeout=5.0  # 5s timeout
        )

        if response.status_code != 200:
            raise SecurityException(f"Security Controller error: {response.status_code}")

        decision = response.json()

        # Check decision
        if decision['decision'] == 'DENY':
            raise SecurityException(
                f"Security validation failed: {decision['reason']}",
                matched_rules=decision.get('matched_rules', []),
                decision=decision
            )

        # Execute function (ONLY if ALLOW)
        result = func(*args, **kwargs)

        return result

    return wrapper


class SecurityException(Exception):
    """Exception raised when Security Controller denies action"""
    def __init__(self, message: str, matched_rules: list = None, decision: dict = None):
        super().__init__(message)
        self.matched_rules = matched_rules or []
        self.decision = decision or {}
```

### 5.2 Validation Request Format

```json
{
  "request_id": "req-abc-123",
  "session_id": "session-demo-001",
  "agent_id": "customer-query-agent",
  "user_input": "Show me customers from California",
  "tool_name": "query_customers",
  "tool_params": {
    "filters": {
      "state": "CA",
      "limit": 100
    }
  },
  "context": {
    "user_id": "demo@sentra.com",
    "authorization_level": "user"
  }
}
```

### 5.3 Validation Response Format

**ALLOW:**
```json
{
  "decision": "ALLOW",
  "reason": "No policy violations detected",
  "request_id": "req-abc-123",
  "session_id": "session-demo-001"
}
```

**DENY:**
```json
{
  "decision": "DENY",
  "reason": "Sigma rule LLM_JAILBREAK detected: 'ignore previous instructions'",
  "request_id": "req-abc-123",
  "session_id": "session-demo-001",
  "matched_rules": [
    {
      "rule_id": "LLM_JAILBREAK_001",
      "title": "LLM Jailbreak Attempt",
      "severity": "high"
    }
  ]
}
```

### 5.4 Handling Security Denials with Natural Language Responses

**Key Design Decision:** When Security Controller denies a tool call, we should return a **natural language response** to the user, not a technical error.

**Implementation Approach:**

Instead of raising a `SecurityException` immediately, we send the denial as a **tool_result** back to Claude. Claude will then generate a user-friendly natural language explanation.

```python
def process_with_claude(message: str, session_id: str, request_id: str, available_tools: list) -> dict:
    """
    Process user message with Claude, handling security denials gracefully
    """
    bedrock = boto3.client('bedrock-runtime')
    messages = [{"role": "user", "content": message}]

    # Initial request to Claude
    response = bedrock.invoke_model(
        modelId=os.environ['BEDROCK_MODEL_ID'],
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "messages": messages,
            "tools": available_tools,
            "max_tokens": 4096
        })
    )

    response_body = json.loads(response['body'].read())

    # Check if Claude wants to use tools
    if response_body.get('stop_reason') == 'tool_use':
        tool_results = []

        for content_block in response_body['content']:
            if content_block['type'] == 'tool_use':
                tool_name = content_block['name']
                tool_params = content_block['input']
                tool_use_id = content_block['id']

                try:
                    # Validate with Security Controller (via @secured_tool)
                    result = execute_tool(tool_name, tool_params)

                    # Success - tool executed
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": json.dumps(result)
                    })

                except SecurityException as e:
                    # Security Controller denied action
                    # DON'T raise error to user - let Claude explain it naturally
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": json.dumps({
                            "error": "security_denial",
                            "reason": str(e),
                            "matched_rules": e.matched_rules,
                            "user_friendly_hint": "This action was blocked by security policies."
                        }),
                        "is_error": True
                    })

                except Exception as e:
                    # Tool execution error
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": json.dumps({"error": str(e)}),
                        "is_error": True
                    })

        # Send tool results back to Claude for natural language response
        messages.append({"role": "assistant", "content": response_body['content']})
        messages.append({"role": "user", "content": tool_results})

        # Get final response from Claude
        final_response = bedrock.invoke_model(
            modelId=os.environ['BEDROCK_MODEL_ID'],
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "messages": messages,
                "max_tokens": 4096
            })
        )

        final_body = json.loads(final_response['body'].read())

        return {
            "text": final_body['content'][0]['text'],
            "data": {}
        }
```

**Example Flow:**

```
User: "Process refund of $5000 for order 12345"
   ↓
Claude: Calls process_refund(order_id="12345", amount=5000.0, reason="customer request")
   ↓
Security Controller: DENY (exceeds $200 manager limit)
   ↓
Agent sends denial as tool_result to Claude:
{
  "error": "security_denial",
  "reason": "Refund amount $5000 exceeds manager authorization limit of $200",
  "matched_rules": ["POLICY_REFUND_LIMIT"]
}
   ↓
Claude generates natural response:
"I'm unable to process that refund because it exceeds the $200 authorization
limit for managers. Refunds over $200 require director approval. Would you
like me to create an approval request instead?"
   ↓
User receives friendly explanation (not technical error)
```

**Benefits:**
- ✅ User-friendly error messages
- ✅ Claude can suggest alternatives ("Would you like me to...")
- ✅ Maintains conversational flow
- ✅ Security policies transparent to users

---

## 6. Agent Tools

### 6.1 Tool Registry

Each agent maintains a **tool registry** that Claude can use:

```python
# Customer Query Agent tools
CUSTOMER_QUERY_TOOLS = [
    {
        "name": "query_customers",
        "description": "Query customers from the database with optional filters",
        "input_schema": {
            "type": "object",
            "properties": {
                "filters": {
                    "type": "object",
                    "properties": {
                        "state": {"type": "string", "description": "Filter by state (e.g., CA, TX)"},
                        "name_contains": {"type": "string", "description": "Filter by name substring"},
                        "limit": {"type": "integer", "description": "Max results (default 100, max 1000)"}
                    }
                }
            },
            "required": []
        }
    },
    {
        "name": "query_orders",
        "description": "Query orders from the database with optional filters",
        "input_schema": {
            "type": "object",
            "properties": {
                "filters": {
                    "type": "object",
                    "properties": {
                        "customer_id": {"type": "string"},
                        "status": {"type": "string", "enum": ["completed", "pending", "cancelled"]},
                        "limit": {"type": "integer"}
                    }
                }
            }
        }
    },
    {
        "name": "get_customer_by_id",
        "description": "Get a single customer by ID",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "Customer identifier"}
            },
            "required": ["customer_id"]
        }
    },
    {
        "name": "call_payment_agent",
        "description": "Call the Payment Agent for refund or payment operations",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Natural language request for Payment Agent"}
            },
            "required": ["message"]
        }
    }
]

# Payment Agent tools
PAYMENT_TOOLS = [
    {
        "name": "query_refund_status",
        "description": "Query the refund status for an order",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "Order identifier"}
            },
            "required": ["order_id"]
        }
    },
    {
        "name": "process_refund",
        "description": "Process a refund for an order",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "amount": {"type": "number", "description": "Refund amount in dollars"},
                "reason": {"type": "string", "description": "Refund reason"}
            },
            "required": ["order_id", "amount", "reason"]
        }
    },
    {
        "name": "reverse_refund",
        "description": "Reverse a refund (manual rollback)",
        "input_schema": {
            "type": "object",
            "properties": {
                "transaction_id": {"type": "string"},
                "reason": {"type": "string"}
            },
            "required": ["transaction_id", "reason"]
        }
    }
]
```

### 6.2 Tool Execution Flow

```python
def process_with_claude(message: str, session_id: str, request_id: str, available_tools: list) -> dict:
    """
    Process user message with Claude (Bedrock) and execute tools

    Flow:
    1. Send message + tools to Claude
    2. Claude returns tool_use blocks
    3. For each tool_use:
       a. Extract tool_name and tool_params
       b. Call @secured_tool function (validates with Security Controller)
       c. If SecurityException → stop and return error
       d. Otherwise → get tool result
    4. Send tool results back to Claude
    5. Claude generates final response
    6. Return response to user
    """
    bedrock = boto3.client('bedrock-runtime')

    # Initial request to Claude
    messages = [{"role": "user", "content": message}]

    response = bedrock.invoke_model(
        modelId=os.environ['BEDROCK_MODEL_ID'],
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "messages": messages,
            "tools": available_tools,
            "max_tokens": 4096
        })
    )

    response_body = json.loads(response['body'].read())

    # Check if Claude wants to use tools
    if response_body.get('stop_reason') == 'tool_use':
        tool_results = []

        for content_block in response_body['content']:
            if content_block['type'] == 'tool_use':
                tool_name = content_block['name']
                tool_params = content_block['input']
                tool_use_id = content_block['id']

                try:
                    # Execute tool (validated by @secured_tool decorator)
                    result = execute_tool(tool_name, tool_params)

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": json.dumps(result)
                    })

                except SecurityException as e:
                    # Security Controller denied action
                    raise e

                except Exception as e:
                    # Tool execution error
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": json.dumps({"error": str(e)}),
                        "is_error": True
                    })

        # Send tool results back to Claude
        messages.append({"role": "assistant", "content": response_body['content']})
        messages.append({"role": "user", "content": tool_results})

        # Get final response from Claude
        final_response = bedrock.invoke_model(
            modelId=os.environ['BEDROCK_MODEL_ID'],
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "messages": messages,
                "max_tokens": 4096
            })
        )

        final_body = json.loads(final_response['body'].read())

        return {
            "text": final_body['content'][0]['text'],
            "data": {}
        }

    else:
        # Claude responded directly without tools
        return {
            "text": response_body['content'][0]['text'],
            "data": {}
        }


def execute_tool(tool_name: str, tool_params: dict) -> Any:
    """
    Execute a tool by name
    Looks up function in global registry and calls it
    """
    tool_function = TOOL_REGISTRY.get(tool_name)

    if not tool_function:
        raise ValueError(f"Tool {tool_name} not found")

    # Call tool (will be validated by @secured_tool decorator)
    return tool_function(**tool_params)


# Tool registry maps tool names to Python functions
TOOL_REGISTRY = {
    "query_customers": query_customers,
    "query_orders": query_orders,
    "get_customer_by_id": get_customer_by_id,
    "call_payment_agent": call_payment_agent,
    # Payment agent tools
    "query_refund_status": query_refund_status,
    "process_refund": process_refund,
    "reverse_refund": reverse_refund
}
```

---

## 7. Data Models

### 7.1 Request Models

```python
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

class AgentRequest(BaseModel):
    """Unified agent request model"""
    message: str = Field(..., min_length=1, max_length=10000, description="Natural language message")
    session_id: Optional[str] = Field(None, description="Session identifier")
    context: Dict[str, Any] = Field(default_factory=dict, description="Additional context")

class AgentResponse(BaseModel):
    """Unified agent response model"""
    response: str = Field(..., description="Natural language response")
    data: Dict[str, Any] = Field(default_factory=dict, description="Structured data")
    session_id: str = Field(..., description="Session identifier")
    request_id: str = Field(..., description="Request identifier")

class AgentError(BaseModel):
    """Unified agent error model"""
    error: str = Field(..., description="Error message")
    error_code: str = Field(..., description="Error code")
    session_id: str = Field(..., description="Session identifier")
    request_id: str = Field(..., description="Request identifier")
    matched_rules: list = Field(default_factory=list, description="Matched security rules (if applicable)")
```

### 7.2 DynamoDB Schemas

#### demo-customers Table

**Partition Key:** `customer_id` (STRING)

**Attributes:**
```json
{
  "customer_id": "C001",
  "name": "Acme Corp",
  "email": "contact@acme.com",
  "ssn": "123-45-6789",
  "state": "CA",
  "created_at": "2024-01-15T10:00:00Z"
}
```

**GSI:** None (partition key lookups only)

#### demo-orders Table

**Partition Key:** `order_id` (STRING)

**Attributes:**
```json
{
  "order_id": "ORD-2024-001",
  "customer_id": "C001",
  "customer_name": "Acme Corp",
  "amount": 1500.00,
  "status": "completed",
  "order_date": "2024-10-15T10:00:00Z",
  "refund_amount": 150.00,
  "refund_date": "2024-11-15T10:30:00Z",
  "refund_status": "refunded",
  "transaction_id": "txn-abc123"
}
```

**GSI 1:** `customer-index`
- Partition Key: `customer_id`
- Purpose: Query all orders for a customer

**GSI 2:** `transaction-index`
- Partition Key: `transaction_id`
- Purpose: Lookup order by transaction ID (for rollback)

#### Seeding Demo Data

**These tables are populated with REAL demo data** (not dummy/mock data).

**Seeding Script:** `scripts/seed_demo_data.py`

**Data Generated:**
- 500 customers with realistic names, emails, phone numbers
- Fake SSNs (for PII detection testing - format: XXX-XX-XXXX)
- State distribution: CA (150), NY (100), TX (80), FL (70), others (100)
- 500 orders linked to customers
- Order amounts: $100 - $50,000
- Order statuses: completed (80%), shipped (10%), processing (5%), cancelled (5%)
- Realistic product items (laptops, monitors, furniture, etc.)

**To Seed Tables:**
```bash
# Install dependencies
pip install boto3 faker

# Set AWS credentials
export AWS_PROFILE=sentra
export AWS_REGION=us-east-1

# Run seeding script
python scripts/seed_demo_data.py
```

**Output:**
```
✅ Successfully seeded demo data:
   - 500 customers in sentra-demo-customers
   - 500 orders in sentra-demo-orders
   - Total: 1000 items

📊 Sample customer (for testing):
   Customer ID: cust-abc123
   Name: John Doe
   State: CA
   SSN (FAKE): 123-45-6789
```

**Important Notes:**
- ✅ These are REAL tools interacting with REAL DynamoDB tables
- ✅ Not dummy/mock tools - actual database operations
- ✅ SSNs are fake (generated by Faker library for testing)
- ✅ Phase 2 will connect to production databases (PostgreSQL, Stripe API, etc.)

---

## 8. Error Handling

### 8.1 Error Types

| Error Type | HTTP Code | When | Retry? |
|------------|-----------|------|--------|
| **ValidationError** | 400 | Invalid request body | ❌ No |
| **SecurityException** | 403 | Security Controller denied action | ❌ No |
| **ResourceNotFound** | 404 | Order/customer not found | ❌ No |
| **RateLimitExceeded** | 429 | API Gateway rate limit | ✅ Yes (exponential backoff) |
| **InternalError** | 500 | DynamoDB/Bedrock error | ✅ Yes (retry 3x) |
| **ServiceUnavailable** | 503 | Security Controller timeout | ✅ Yes (retry 3x) |

### 8.2 Error Response Format

```python
@app.exception_handler(SecurityException)
async def security_exception_handler(request: Request, exc: SecurityException):
    """Handle Security Controller denials"""
    return JSONResponse(
        status_code=403,
        content={
            "error": str(exc),
            "error_code": "SECURITY_VALIDATION_FAILED",
            "session_id": get_current_session_id(),
            "request_id": get_current_request_id(),
            "matched_rules": exc.matched_rules
        }
    )

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """Handle all other errors"""
    logger.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "error_code": "INTERNAL_ERROR",
            "session_id": get_current_session_id(),
            "request_id": get_current_request_id()
        }
    )
```

### 8.3 Retry Logic

```python
import time
from functools import wraps

def retry_with_exponential_backoff(max_retries: int = 3, base_delay: float = 1.0):
    """Decorator for retrying functions with exponential backoff"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                    if attempt == max_retries - 1:
                        raise
                    delay = base_delay * (2 ** attempt)
                    logger.warning(f"Attempt {attempt + 1} failed, retrying in {delay}s: {e}")
                    time.sleep(delay)
        return wrapper
    return decorator


@retry_with_exponential_backoff(max_retries=3, base_delay=1.0)
def call_security_controller(validation_request: dict) -> dict:
    """Call Security Controller with retry logic"""
    response = requests.post(
        f"{os.environ['SECURITY_CONTROLLER_URL']}/v1/validate",
        json=validation_request,
        timeout=5.0
    )
    response.raise_for_status()
    return response.json()
```

---

## 9. Configuration

### 9.1 Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PORT` | ✅ | - | Port to listen on (8080) |
| `SERVICE_NAME` | ✅ | - | Agent identifier |
| `DEMO_CUSTOMERS_TABLE` | ✅ (CQA) | - | DynamoDB customers table name |
| `DEMO_ORDERS_TABLE` | ✅ | - | DynamoDB orders table name |
| `SECURITY_CONTROLLER_URL` | ✅ | - | Security Controller base URL |
| `BEDROCK_MODEL_ID` | ✅ | - | AWS Bedrock model ID |
| `AWS_REGION` | ✅ | - | AWS region |
| `LOG_LEVEL` | ❌ | INFO | Logging level |
| `MAX_TOOL_RETRIES` | ❌ | 3 | Max retries for tool execution |
| `SECURITY_TIMEOUT_SEC` | ❌ | 5 | Security Controller timeout |

### 9.2 Logging Configuration

```python
import logging
import json
from pythonjsonlogger import jsonlogger

# Configure structured JSON logging
logger = logging.getLogger(__name__)
handler = logging.StreamHandler()

formatter = jsonlogger.JsonFormatter(
    fmt='%(asctime)s %(levelname)s %(name)s %(message)s',
    json_ensure_ascii=False
)
handler.setFormatter(formatter)

logger.addHandler(handler)
logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))

# Log structured events
logger.info("Agent started", extra={
    "service": os.environ['SERVICE_NAME'],
    "version": "1.0.0",
    "port": os.environ['PORT']
})
```

### 9.3 Health Check Configuration

```python
@app.get("/v1/health")
async def health_check():
    """
    Health check endpoint for ALB target group

    Returns:
        200 OK if service is healthy
        503 Service Unavailable if unhealthy

    Health checks:
    1. DynamoDB connectivity
    2. Security Controller connectivity (optional)
    3. Bedrock connectivity (optional)
    """
    health = {
        "status": "ok",
        "service": os.environ['SERVICE_NAME'],
        "timestamp": datetime.utcnow().isoformat(),
        "checks": {}
    }

    # Check DynamoDB
    try:
        dynamodb = boto3.client('dynamodb')
        dynamodb.describe_table(TableName=os.environ['DEMO_ORDERS_TABLE'])
        health["checks"]["dynamodb"] = "ok"
    except Exception as e:
        health["checks"]["dynamodb"] = f"error: {str(e)}"
        health["status"] = "degraded"

    # Check Security Controller (optional - don't fail if down)
    try:
        response = requests.get(
            f"{os.environ['SECURITY_CONTROLLER_URL']}/v1/health",
            timeout=2.0
        )
        health["checks"]["security_controller"] = "ok" if response.status_code == 200 else "degraded"
    except Exception:
        health["checks"]["security_controller"] = "unavailable"
        # Don't mark as unhealthy - Security Controller may be temporarily down

    status_code = 200 if health["status"] == "ok" else 503
    return JSONResponse(status_code=status_code, content=health)
```

---

## 10. Monitoring & Observability

### 10.1 CloudWatch Metrics

Both agents publish custom metrics:

```python
import boto3

cloudwatch = boto3.client('cloudwatch')

def publish_metric(metric_name: str, value: float, unit: str = 'Count'):
    """Publish custom metric to CloudWatch"""
    cloudwatch.put_metric_data(
        Namespace='Sentra/Agents',
        MetricData=[
            {
                'MetricName': metric_name,
                'Value': value,
                'Unit': unit,
                'Dimensions': [
                    {'Name': 'ServiceName', 'Value': os.environ['SERVICE_NAME']},
                    {'Name': 'Environment', 'Value': 'dev'}
                ]
            }
        ]
    )

# Example metrics
publish_metric('RequestsReceived', 1)
publish_metric('ToolExecutionTime', 150.5, 'Milliseconds')
publish_metric('SecurityDenials', 1)
publish_metric('BedrockTokensUsed', 1024, 'Count')
```

**Key Metrics:**
- `RequestsReceived` - Total requests
- `RequestsSucceeded` - Successful requests
- `RequestsFailed` - Failed requests
- `SecurityDenials` - Security Controller denials
- `ToolExecutionTime` - Tool execution latency
- `BedrockTokensUsed` - Bedrock token usage
- `BedrockLatency` - Bedrock API latency

### 10.2 CloudWatch Logs

**Log Groups:**
- `/ecs/sentra/customer-query-agent`
- `/ecs/sentra/payment-agent`

**Log Format (JSON):**
```json
{
  "timestamp": "2025-11-20T10:00:00Z",
  "level": "INFO",
  "service": "customer-query-agent",
  "request_id": "req-abc-123",
  "session_id": "session-demo-001",
  "message": "Tool executed successfully",
  "tool_name": "query_customers",
  "execution_time_ms": 150.5,
  "result_count": 42
}
```

### 10.3 Audit Trail

All tool executions are logged to CloudWatch Logs (via Security Controller):

```json
{
  "timestamp": "2025-11-20T10:00:00Z",
  "request_id": "req-abc-123",
  "session_id": "session-demo-001",
  "agent_id": "customer-query-agent",
  "tool_name": "query_customers",
  "tool_params": {"filters": {"state": "CA"}},
  "decision": "ALLOW",
  "matched_rules": [],
  "execution_time_ms": 150.5
}
```

### 10.4 CloudWatch Alarms

```python
# In CDK infrastructure

# High error rate alarm
error_alarm = cloudwatch.Alarm(
    self, "CustomerQueryAgentErrorAlarm",
    alarm_name="customer-query-agent-errors",
    metric=cloudwatch.Metric(
        namespace="Sentra/Agents",
        metric_name="RequestsFailed",
        dimensions_map={"ServiceName": "customer-query-agent"},
        statistic="Sum",
        period=Duration.minutes(5)
    ),
    threshold=10,  # More than 10 errors in 5 minutes
    evaluation_periods=1
)

# High security denial rate
denial_alarm = cloudwatch.Alarm(
    self, "CustomerQueryAgentDenialAlarm",
    alarm_name="customer-query-agent-denials",
    metric=cloudwatch.Metric(
        namespace="Sentra/Agents",
        metric_name="SecurityDenials",
        dimensions_map={"ServiceName": "customer-query-agent"},
        statistic="Sum",
        period=Duration.minutes(5)
    ),
    threshold=50,  # More than 50 denials in 5 minutes (potential attack)
    evaluation_periods=1
)
```

---

## 11. Dashboard Chat Interface Integration

### 11.1 Chat Tab Overview

The Dashboard includes a **Chat Tab** that allows users to interact with agents via natural language. This provides a conversational interface for the demo.

**Key Features:**
- Multi-session support (create multiple chat sessions)
- Real-time message streaming
- Agent selection (Customer Query Agent, Payment Agent)
- Session history persistence

### 11.2 API Usage in Chat Interface

The Chat Tab uses the unified agent API endpoints:

```python
# Example: Dashboard chat component
import streamlit as st
import requests
import uuid

def send_chat_message(
    agent_name: str,  # "customer-query" or "payment"
    message: str,
    session_id: str,
    is_action: bool = False  # True for write operations
):
    """
    Send message to agent via API Gateway

    Args:
        agent_name: Agent identifier
        message: User's natural language message
        session_id: Chat session ID
        is_action: True for write operations (refunds, updates)
                   False for read operations (queries)

    Returns:
        Agent response
    """
    # Determine endpoint based on operation type
    endpoint_type = "action" if is_action else "query"

    url = f"{API_GATEWAY_URL}/v1/agents/{agent_name}/{endpoint_type}"

    # Build request
    payload = {
        "message": message,
        "session_id": session_id,
        "context": {
            "user_id": st.session_state.get("user_email", "demo@sentra.com"),
            "authorization_level": st.session_state.get("auth_level", "user")
        }
    }

    # Send request
    response = requests.post(
        url,
        json=payload,
        headers={
            "X-API-Key": API_KEY,
            "Content-Type": "application/json"
        },
        timeout=30
    )

    if response.status_code == 200:
        return response.json()
    elif response.status_code == 403:
        # Security denial - already formatted by Claude
        error_data = response.json()
        return {
            "response": error_data.get("error", "Security policy violation"),
            "error": True
        }
    else:
        return {
            "response": f"Error: {response.status_code}",
            "error": True
        }


# Streamlit Chat Interface
def render_chat_tab():
    """Render chat interface in Dashboard"""
    st.title("💬 Chat with AI Agents")

    # Agent selection
    agent = st.selectbox(
        "Select Agent",
        ["customer-query", "payment"],
        format_func=lambda x: "Customer Query Agent" if x == "customer-query" else "Payment Agent"
    )

    # Session management
    if "chat_sessions" not in st.session_state:
        st.session_state.chat_sessions = {}

    if "active_session_id" not in st.session_state:
        st.session_state.active_session_id = str(uuid.uuid4())
        st.session_state.chat_sessions[st.session_state.active_session_id] = []

    # Display chat history
    for msg in st.session_state.chat_sessions[st.session_state.active_session_id]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Chat input
    if prompt := st.chat_input("Ask a question or give a command..."):
        # Add user message to history
        st.session_state.chat_sessions[st.session_state.active_session_id].append({
            "role": "user",
            "content": prompt
        })

        # Display user message
        with st.chat_message("user"):
            st.markdown(prompt)

        # Determine if this is an action (simple heuristic)
        action_keywords = ['process', 'refund', 'update', 'delete', 'cancel', 'create', 'add']
        is_action = any(keyword in prompt.lower() for keyword in action_keywords)

        # Send to agent
        with st.chat_message("assistant"):
            with st.spinner(f"Thinking..."):
                response = send_chat_message(
                    agent_name=agent,
                    message=prompt,
                    session_id=st.session_state.active_session_id,
                    is_action=is_action
                )

                # Display response
                if response.get("error"):
                    st.error(response["response"])
                else:
                    st.markdown(response["response"])

                    # Show structured data if available
                    if response.get("data"):
                        with st.expander("📊 Structured Data"):
                            st.json(response["data"])

        # Add assistant response to history
        st.session_state.chat_sessions[st.session_state.active_session_id].append({
            "role": "assistant",
            "content": response["response"]
        })
```

### 11.3 Automatic Query vs Action Detection

**Simple Approach** (Keyword-Based):
```python
def is_action_request(message: str) -> bool:
    """
    Determine if message is a write operation

    Simple heuristic based on action verbs
    """
    action_keywords = [
        'process', 'refund', 'update', 'delete', 'cancel', 'create',
        'add', 'remove', 'modify', 'change', 'set', 'approve'
    ]

    return any(keyword in message.lower() for keyword in action_keywords)
```

**Advanced Approach** (Let Agent Handle Both):
```python
# Simpler: Always use /action endpoint
# Agent will handle read-only queries safely via Claude
response = send_chat_message(
    agent_name=agent,
    message=prompt,
    session_id=session_id,
    is_action=True  # Always use action endpoint
)
```

**Recommended:** Use keyword-based detection for MVP, upgrade to LLM-based classification in Phase 2.

### 11.4 Multi-Session Management

```python
# Session management in Streamlit
def create_new_session():
    """Create a new chat session"""
    session_id = str(uuid.uuid4())
    st.session_state.chat_sessions[session_id] = []
    st.session_state.active_session_id = session_id
    return session_id

def switch_session(session_id: str):
    """Switch to existing session"""
    st.session_state.active_session_id = session_id

def delete_session(session_id: str):
    """Delete a chat session"""
    if session_id in st.session_state.chat_sessions:
        del st.session_state.chat_sessions[session_id]

        # Switch to another session or create new one
        if st.session_state.chat_sessions:
            st.session_state.active_session_id = list(st.session_state.chat_sessions.keys())[0]
        else:
            create_new_session()

# Sidebar: Session list
with st.sidebar:
    st.subheader("Chat Sessions")

    if st.button("➕ New Session"):
        create_new_session()
        st.rerun()

    for session_id, messages in st.session_state.chat_sessions.items():
        # Show first message as session title
        title = messages[0]["content"][:30] + "..." if messages else "Empty Session"

        col1, col2 = st.columns([4, 1])
        with col1:
            if st.button(title, key=f"session_{session_id}"):
                switch_session(session_id)
                st.rerun()

        with col2:
            if st.button("🗑️", key=f"delete_{session_id}"):
                delete_session(session_id)
                st.rerun()
```

### 11.5 Example User Flows

**Flow 1: Customer Query**
```
User: "Show me all customers from California"
   ↓
Dashboard → POST /v1/agents/customer-query/query
   ↓
Customer Query Agent → Claude → query_customers(filters={'state': 'CA'})
   ↓
Security Controller validates → ALLOW
   ↓
Agent executes query → Returns 150 customers
   ↓
Claude: "I found 150 customers from California. Here are the details..."
   ↓
Dashboard displays response + structured data table
```

**Flow 2: Refund Request (Success)**
```
User: "Process refund of $150 for order ORD-12345"
   ↓
Dashboard → POST /v1/agents/payment/action
   ↓
Payment Agent → Claude → process_refund(order_id="ORD-12345", amount=150.0)
   ↓
Security Controller validates → ALLOW (under $200 limit)
   ↓
Agent executes refund → DynamoDB updated
   ↓
Claude: "Refund of $150.00 processed successfully for order ORD-12345."
   ↓
Dashboard displays success message
```

**Flow 3: Refund Request (Denied)**
```
User: "Process refund of $5000 for order ORD-12345"
   ↓
Dashboard → POST /v1/agents/payment/action
   ↓
Payment Agent → Claude → process_refund(order_id="ORD-12345", amount=5000.0)
   ↓
Security Controller validates → DENY (exceeds manager limit)
   ↓
Claude receives denial as tool_result
   ↓
Claude: "I'm unable to process that refund because it exceeds the $200
        authorization limit for managers. Refunds over $200 require
        director approval. Would you like me to create an approval request?"
   ↓
Dashboard displays denial explanation (user-friendly, not technical error)
```

---

## Summary

### What We Built

✅ **Two AI Agents** with unified interface
✅ **Standardized API Contract** (`/query` and `/action` endpoints)
✅ **Security Controller Integration** (`@secured_tool` decorator)
✅ **AWS Bedrock Claude Sonnet** for natural language understanding
✅ **Tool-Based Actions** with DynamoDB backend
✅ **Multi-Agent Communication** (Customer Query Agent → Payment Agent)
✅ **Complete Error Handling** with retry logic
✅ **CloudWatch Metrics & Logs** for observability
✅ **Health Checks** for ALB target groups

### Key Features

| Feature | Customer Query Agent | Payment Agent |
|---------|---------------------|---------------|
| **Primary Use Case** | Query customer/order data | Process refunds |
| **Port** | 8080 | 8080 |
| **Tools** | 4 (query_customers, query_orders, get_customer_by_id, call_payment_agent) | 3 (query_refund_status, process_refund, reverse_refund) |
| **DynamoDB Tables** | demo-customers (R), demo-orders (R) | demo-orders (R/W) |
| **Bedrock Model** | Claude Sonnet | Claude Sonnet |
| **Security Validation** | All tools validated | All tools validated |

### Next Steps

1. **Implementation**: Create Docker containers with FastAPI applications
2. **Testing**: Unit tests for tools and integration tests for Security Controller
3. **Deployment**: Build Docker images and push to ECR
4. **Demo Scenarios**: Test all 5 demo scenarios end-to-end
5. **Dashboard Integration**: Connect Dashboard to agents via API Gateway

See [LLD 04: Dashboard](./04-dashboard-v2.md) for Dashboard implementation.

---

**End of LLD 05: AI Agents - Customer Query & Payment Agents**
