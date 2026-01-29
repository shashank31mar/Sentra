# AI Agents API Reference

**Version:** 1.0  
**Last Updated:** November 2025

---

## Table of Contents

1. [Unified Agent Interface](#1-unified-agent-interface)
2. [Customer Query Agent](#2-customer-query-agent)
3. [Payment Agent](#3-payment-agent)
4. [Error Codes](#4-error-codes)
5. [Tool Schemas](#5-tool-schemas)

---

## 1. Unified Agent Interface

All agents follow the same standardized API contract.

### Base Request Schema

```json
{
  "message": "string (1-10000 chars, required)",
  "session_id": "string (optional, auto-generated if missing)",
  "context": {
    "user_id": "string (optional)",
    "authorization_level": "string (optional: user|manager|director)"
  }
}
```

### Base Response Schema (Success)

```json
{
  "response": "string - Natural language response",
  "data": {},
  "session_id": "string",
  "request_id": "string"
}
```

### Base Response Schema (Error)

```json
{
  "error": "string - Error message",
  "error_code": "string - Error code",
  "session_id": "string",
  "request_id": "string",
  "matched_rules": []
}
```

---

## 2. Customer Query Agent

### POST /v1/agents/customer-query/query

Query customers and orders (read operations).

**Request:**
```json
{
  "message": "Show me all customers from California",
  "session_id": "session-001",
  "context": {
    "user_id": "user@example.com",
    "authorization_level": "user"
  }
}
```

**Response (200 OK):**
```json
{
  "response": "I found 150 customers from California. Here are the first 10...",
  "data": {
    "customers": [...],
    "count": 150
  },
  "session_id": "session-001",
  "request_id": "req-cqa-abc123"
}
```

### POST /v1/agents/customer-query/action

Perform actions (same interface, used for inter-agent calls).

**Request:**
```json
{
  "message": "Process a refund of $150 for order ORD-001",
  "session_id": "session-001",
  "context": {
    "user_id": "manager@example.com",
    "authorization_level": "manager"
  }
}
```

**Response (200 OK):**
```json
{
  "response": "I've processed the refund of $150 for order ORD-001. Transaction ID: txn-xyz789",
  "data": {
    "transaction_id": "txn-xyz789",
    "refund_amount": 150.00
  },
  "session_id": "session-001",
  "request_id": "req-cqa-def456"
}
```

### GET /v1/health

Health check endpoint.

**Response (200 OK):**
```json
{
  "status": "ok",
  "service": "customer-query-agent",
  "timestamp": "2025-11-25T10:00:00Z",
  "checks": {
    "dynamodb_customers": "ok",
    "dynamodb_orders": "ok",
    "security_controller": "ok",
    "bedrock": "ok"
  }
}
```

---

## 3. Payment Agent

### POST /v1/agents/payment/query

Query refund status (read operations).

**Request:**
```json
{
  "message": "Check refund status for order ORD-001",
  "session_id": "session-002"
}
```

**Response (200 OK):**
```json
{
  "response": "Order ORD-001 has a refund of $150.00 processed on 2025-11-20. Status: completed.",
  "data": {
    "order_id": "ORD-001",
    "refund_amount": 150.00,
    "refund_status": "refunded",
    "refund_date": "2025-11-20T10:30:00Z"
  },
  "session_id": "session-002",
  "request_id": "req-pa-abc123"
}
```

### POST /v1/agents/payment/action

Process refunds (write operations).

**Request:**
```json
{
  "message": "Process a refund of $100 for order ORD-002 reason: customer request",
  "session_id": "session-002",
  "context": {
    "user_id": "manager@example.com",
    "authorization_level": "manager"
  }
}
```

**Response (200 OK - Success):**
```json
{
  "response": "Refund of $100.00 processed successfully for order ORD-002.",
  "data": {
    "transaction_id": "txn-abc123",
    "order_id": "ORD-002",
    "refund_amount": 100.00,
    "status": "success"
  },
  "session_id": "session-002",
  "request_id": "req-pa-def456"
}
```

**Response (200 OK - Denied by Policy):**
```json
{
  "response": "I'm unable to process that $5000 refund because it exceeds the $200 authorization limit for managers. Refunds over $200 require director approval. Would you like me to create an approval request?",
  "data": {},
  "session_id": "session-002",
  "request_id": "req-pa-ghi789"
}
```

### GET /v1/health

Health check endpoint.

**Response (200 OK):**
```json
{
  "status": "ok",
  "service": "payment-agent",
  "timestamp": "2025-11-25T10:00:00Z",
  "checks": {
    "dynamodb_orders": "ok",
    "security_controller": "ok",
    "bedrock": "ok"
  }
}
```

---

## 4. Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `SECURITY_VALIDATION_FAILED` | 403 | Security Controller denied the request |
| `VALIDATION_ERROR` | 400 | Invalid request parameters |
| `INTERNAL_ERROR` | 500 | Internal server error |
| `POLICY_VIOLATION` | 403 | Business policy violated (e.g., refund limit) |
| `UNAUTHORIZED_TOOL` | 403 | Tool not authorized for agent |
| `SESSION_SUSPENDED` | 403 | Session suspended due to low trust score |

### Error Response Example

```json
{
  "error": "Security validation failed: Refund amount $5000 exceeds manager authorization limit of $200",
  "error_code": "SECURITY_VALIDATION_FAILED",
  "session_id": "session-002",
  "request_id": "req-pa-xyz123",
  "matched_rules": [
    {
      "rule_id": "POLICY_REFUND_LIMIT",
      "title": "Refund Limit Policy"
    }
  ]
}
```

---

## 5. Tool Schemas

### Customer Query Agent Tools

#### query_customers

```json
{
  "name": "query_customers",
  "description": "Query customers from the database with optional filters",
  "input_schema": {
    "type": "object",
    "properties": {
      "filters": {
        "type": "object",
        "properties": {
          "state": {"type": "string", "description": "US state code (e.g., CA, TX)"},
          "name_contains": {"type": "string"},
          "email_contains": {"type": "string"},
          "limit": {"type": "integer", "default": 100, "maximum": 1000}
        }
      }
    }
  }
}
```

#### query_orders

```json
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
          "status": {"type": "string", "enum": ["completed", "pending", "cancelled", "shipped"]},
          "min_amount": {"type": "number"},
          "max_amount": {"type": "number"},
          "limit": {"type": "integer", "default": 100, "maximum": 1000}
        }
      }
    }
  }
}
```

#### get_customer_by_id

```json
{
  "name": "get_customer_by_id",
  "description": "Get detailed information about a specific customer",
  "input_schema": {
    "type": "object",
    "properties": {
      "customer_id": {"type": "string", "description": "Customer identifier"}
    },
    "required": ["customer_id"]
  }
}
```

#### call_payment_agent

```json
{
  "name": "call_payment_agent",
  "description": "Call Payment Agent for refund/payment operations",
  "input_schema": {
    "type": "object",
    "properties": {
      "message": {"type": "string", "description": "Request for Payment Agent"},
      "session_id": {"type": "string", "description": "Current session ID"}
    },
    "required": ["message", "session_id"]
  }
}
```

### Payment Agent Tools

#### query_refund_status

```json
{
  "name": "query_refund_status",
  "description": "Query refund status for an order",
  "input_schema": {
    "type": "object",
    "properties": {
      "order_id": {"type": "string", "description": "Order identifier"}
    },
    "required": ["order_id"]
  }
}
```

#### process_refund

```json
{
  "name": "process_refund",
  "description": "Process a refund for an order (subject to authorization limits)",
  "input_schema": {
    "type": "object",
    "properties": {
      "order_id": {"type": "string"},
      "amount": {"type": "number", "description": "Refund amount in dollars"},
      "reason": {"type": "string", "description": "Refund reason"}
    },
    "required": ["order_id", "amount", "reason"]
  }
}
```

#### reverse_refund

```json
{
  "name": "reverse_refund",
  "description": "Reverse a previously processed refund (requires director authorization)",
  "input_schema": {
    "type": "object",
    "properties": {
      "transaction_id": {"type": "string"},
      "reason": {"type": "string", "description": "Rollback reason"}
    },
    "required": ["transaction_id", "reason"]
  }
}
```

---

## Rate Limits

| Endpoint | Rate Limit | Burst |
|----------|------------|-------|
| `/query` | 20 req/min | 40 |
| `/action` | 10 req/min | 20 |
| `/health` | 60 req/min | 100 |

---

## Related Documentation

- [AI Agents Deployment Guide](./ai-agents-deployment.md)
- [AI Agents Operations Guide](./ai-agents-operations.md)
