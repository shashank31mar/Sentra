# API Gateway Endpoints Documentation

**API Base URL**: `https://b511tspnsa.execute-api.us-east-1.amazonaws.com/prod/`  
**API Key Required**: Yes (except /v1/health)  
**Authentication**: X-API-Key header

---

## Table of Contents

1. [Security Controller Endpoints](#security-controller-endpoints)
2. [AI Agent Endpoints](#ai-agent-endpoints)
3. [Rate Limits](#rate-limits)
4. [Error Codes](#error-codes)
5. [Testing Examples](#testing-examples)

---

## Security Controller Endpoints

### 1. GET /v1/health

Health check endpoint for monitoring.

**Authentication**: None required  
**Rate Limit**: 1000 req/min  

**Request**:
```bash
curl -X GET "https://b511tspnsa.execute-api.us-east-1.amazonaws.com/prod/v1/health"
```

**Response** (200 OK):
```json
{
  "status": "ok",
  "timestamp": "2025-11-17T20:00:00Z"
}
```

---

### 2. POST /v1/validate

Validate agent actions before execution.

**Authentication**: API key required  
**Rate Limit**: 100 req/min  

**Request**:
```bash
curl -X POST "https://b511tspnsa.execute-api.us-east-1.amazonaws.com/prod/v1/validate" \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "session-123",
    "agent_id": "customer-query-agent",
    "action": {
      "type": "query",
      "tool": "query_database",
      "parameters": {"query": "SELECT * FROM customers"}
    }
  }'
```

**Request Schema**:
- `session_id` (string, required): Session identifier
- `agent_id` (string, required): Agent identifier
- `action` (object, required): Action to validate

**Response** (200 OK):
```json
{
  "decision": "allow",
  "reason": "No policy violations detected",
  "session_id": "session-123",
  "threat_detected": false
}
```

**Response** (403 Forbidden - Policy Violation):
```json
{
  "decision": "deny",
  "reason": "Refund amount exceeds limit of $5000",
  "session_id": "session-123",
  "threat_detected": true,
  "matched_rules": ["max-refund-amount"]
}
```

---

### 3. GET /v1/logs

Query audit logs with filters.

**Authentication**: API key required  
**Rate Limit**: 50 req/min  

**Query Parameters**:
- `session_id` (optional): Filter by session
- `start_time` (optional): ISO 8601 timestamp
- `end_time` (optional): ISO 8601 timestamp
- `limit` (optional): Max results (default 100, max 1000)

**Request**:
```bash
curl -X GET "https://b511tspnsa.execute-api.us-east-1.amazonaws.com/prod/v1/logs?limit=10&session_id=session-123" \
  -H "X-API-Key: YOUR_API_KEY"
```

**Response** (200 OK):
```json
{
  "logs": [
    {
      "timestamp": "2025-11-17T20:00:00Z",
      "session_id": "session-123",
      "agent_id": "customer-query-agent",
      "decision": "allow",
      "action": "query_database"
    }
  ],
  "count": 10,
  "next_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

---

### 4. POST /v1/rollback

Manual rollback of agent actions.

**Authentication**: API key required  
**Rate Limit**: 10 req/min  

**Request**:
```bash
curl -X POST "https://b511tspnsa.execute-api.us-east-1.amazonaws.com/prod/v1/rollback" \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "action_id": "action-456",
    "reason": "Fraudulent transaction detected",
    "operator_id": "admin@example.com"
  }'
```

**Request Schema**:
- `action_id` (string, required): Action to rollback
- `reason` (string, required): Rollback reason
- `operator_id` (string, optional): Operator identifier

**Response** (501 Not Implemented - MVP):
```json
{
  "message": "Rollback functionality planned for future release",
  "status": "not_implemented"
}
```

---

## AI Agent Endpoints

### Standardized Agent Interface

All agents follow the same interface pattern:
- `/query` - Read operations (20 req/min)
- `/action` - Write operations (10 req/min)

---

### 5. POST /v1/agents/customer-query/query

Query customer/order data (read operations).

**Authentication**: API key required  
**Rate Limit**: 20 req/min  

**Request**:
```bash
curl -X POST "https://b511tspnsa.execute-api.us-east-1.amazonaws.com/prod/v1/agents/customer-query/query" \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Show customers from California",
    "session_id": "session-123"
  }'
```

**Request Schema**:
- `message` (string, required, 1-10000 chars): Natural language query
- `context` (object, optional): Additional context
- `session_id` (string, optional): Session identifier

**Response** (200 OK):
```json
{
  "response": "Found 42 customers from California",
  "data": [...],
  "session_id": "session-123"
}
```

---

### 6. POST /v1/agents/customer-query/action

Update customer/order data (write operations).

**Authentication**: API key required  
**Rate Limit**: 10 req/min  

**Request**:
```bash
curl -X POST "https://b511tspnsa.execute-api.us-east-1.amazonaws.com/prod/v1/agents/customer-query/action" \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Update customer email for customer 12345 to newemail@example.com",
    "session_id": "session-123"
  }'
```

**Response** (200 OK):
```json
{
  "response": "Customer email updated successfully",
  "session_id": "session-123"
}
```

---

### 7. POST /v1/agents/payment/query

Query payment/refund data (read operations).

**Authentication**: API key required  
**Rate Limit**: 20 req/min  

**Request**:
```bash
curl -X POST "https://b511tspnsa.execute-api.us-east-1.amazonaws.com/prod/v1/agents/payment/query" \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Check refund status for order 12345",
    "session_id": "session-123"
  }'
```

**Response** (200 OK):
```json
{
  "response": "Refund of $150.00 processed on 2025-11-15",
  "session_id": "session-123"
}
```

---

### 8. POST /v1/agents/payment/action

Process refunds and payments (write operations).

**Authentication**: API key required  
**Rate Limit**: 10 req/min  

**Request**:
```bash
curl -X POST "https://b511tspnsa.execute-api.us-east-1.amazonaws.com/prod/v1/agents/payment/action" \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Process refund of $150 for order 12345",
    "session_id": "session-123"
  }'
```

**Response** (200 OK):
```json
{
  "response": "Refund of $150.00 processed successfully",
  "transaction_id": "txn-789",
  "session_id": "session-123"
}
```

---

## Rate Limits

| Endpoint | Rate Limit | Burst | API Key Required |
|----------|------------|-------|------------------|
| `/v1/health` | 1000/min | 2000 | ❌ No |
| `/v1/validate` | 100/min | 200 | ✅ Yes |
| `/v1/logs` | 50/min | 100 | ✅ Yes |
| `/v1/rollback` | 10/min | 20 | ✅ Yes |
| `/v1/agents/*/query` | 20/min | 40 | ✅ Yes |
| `/v1/agents/*/action` | 10/min | 20 | ✅ Yes |

**Global Limits (Usage Plan)**:
- Burst: 200 requests
- Quota: 100,000 requests/month

---

## Error Codes

### 400 Bad Request
Invalid request body or missing required fields.

```json
{
  "message": "Invalid request body"
}
```

### 403 Forbidden
Missing or invalid API key.

```json
{
  "message": "Forbidden"
}
```

### 429 Too Many Requests
Rate limit exceeded.

```json
{
  "message": "Too Many Requests"
}
```

### 500 Internal Server Error
Server-side error.

```json
{
  "message": "Internal server error"
}
```

### 501 Not Implemented
Feature not yet implemented (e.g., rollback in MVP).

```json
{
  "message": "Not implemented"
}
```

---

## Testing Examples

### Get API Key

```bash
# Get API Key ID from CloudFormation
API_KEY_ID=$(aws cloudformation describe-stacks \
  --stack-name Sentra-DEV-API-Stack \
  --profile sentra \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiKeyId`].OutputValue' \
  --output text)

# Get API Key value
API_KEY=$(aws apigateway get-api-key \
  --api-key $API_KEY_ID \
  --include-value \
  --profile sentra \
  --query 'value' \
  --output text)

echo "API Key: $API_KEY"
```

### Test All Endpoints

```bash
API_URL="https://b511tspnsa.execute-api.us-east-1.amazonaws.com/prod/"

# 1. Health check (no auth)
curl -X GET "${API_URL}v1/health"

# 2. Validate (with auth)
curl -X POST "${API_URL}v1/validate" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"session_id":"test","agent_id":"test","action":{}}'

# 3. Query logs (with auth)
curl -X GET "${API_URL}v1/logs?limit=10" \
  -H "X-API-Key: $API_KEY"

# 4. Rollback (with auth)
curl -X POST "${API_URL}v1/rollback" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"action_id":"test","reason":"test"}'

# 5. Customer query agent
curl -X POST "${API_URL}v1/agents/customer-query/query" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"message":"Show customers"}'

# 6. Payment agent
curl -X POST "${API_URL}v1/agents/payment/query" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"message":"Check refund status"}'
```

---

## Troubleshooting

### Common Errors

**Error**: `{"message":"Missing Authentication Token"}`  
**Solution**: Check that you're using the correct API URL with `/prod/` stage.

**Error**: `{"message":"Forbidden"}`  
**Solution**: Verify API key is included in `X-API-Key` header.

**Error**: `{"message": "Invalid request body"}`  
**Solution**: Check request body matches the required JSON schema.

**Error**: `{"message":"Too Many Requests"}`  
**Solution**: You've exceeded the rate limit. Wait and retry.

---

**Last Updated**: November 17, 2025  
**API Version**: v1  
**Stack**: Sentra-DEV-API-Stack
