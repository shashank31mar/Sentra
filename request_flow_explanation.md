> ⚠️ **DEPRECATED (2026-06-28) — historical, not maintained.** Superseded by [flow.md](flow.md). Do not rely on this document for current architecture, requirements, or positioning; kept for historical reference only.

# Request Flow Explanation: First vs Second Request

## What Happens When User Asks "list all orders"

### Step 1: User → Payment Agent
User sends: `POST /v1/agents/payment/query` with message "list all orders"

### Step 2: Payment Agent → Claude (Bedrock)
Payment agent calls Claude with:
- User message: "list all orders"
- Available tools: [list_orders, process_refund, etc.]
- System prompt: "You are a payment assistant..."

### Step 3: Claude → Tool Use
Claude responds with **TWO validation requests**:

**Request 1** (happens at 10:55:52):
```json
{
  "tool_use": "list_orders",
  "parameters": {}
}
```
Payment agent intercepts this → calls Security Controller `/v1/validate`

**✅ Result**: Security Controller returns 200 OK + ALLOW
- Logs show: "ALLOW: tool=list_orders, trust_score=100.0"

**Request 2** (happens at 10:55:55):
```json
{
  "tool_use": "list_orders",  
  "parameters": {}
}
```
Payment agent intercepts again → calls Security Controller `/v1/validate`

**❌ Result**: Security Controller returns 422 (schema validation error)
- Missing fields: `timestamp`, `operation_type`
- Agent treats 422 as "DENY"
- Claude receives tool_result with error

### Step 4: Claude → User Response
Since the tool call failed (422 error), Claude cannot get order data.
Claude generates response: "I apologize, but I don't have access..."

## Why Two Requests?

**Theory 1**: Claude tries the tool twice due to conversation flow
- First call validates the tool is available
- Second call actually executes it

**Theory 2**: There are two different code paths calling the validation
- One succeeds (has all fields)
- One fails (missing fields)

## The Core Problem

**You're absolutely right**: If ANY part of the request fails, the overall status should be DENY.

Currently:
- Dashboard shows "ALLOW" (because it only logs successful validations)
- User gets error message
- Inconsistent state

**What SHOULD happen**:
1. **ALL** validation requests must succeed (200 OK + ALLOW)
2. If **ANY** validation fails (422, 500, or DENY), the entire operation should fail
3. Dashboard should show the final state, not just successful attempts

## Current Bug

The issue is that the Security Controller is logging successful validations, but the agent is also making malformed validation requests that fail with 422.

**The 422 error happens AFTER the ALLOW**, so:
- Security Controller thinks: "I allowed this" ✅
- Payment agent thinks: "Request failed" ❌
- Dashboard shows: "ALLOW" (misleading)
- User sees: "Request blocked" (correct outcome, wrong reason)

## Fix Required

1. **Fix schema** - Add `timestamp` and `operation_type` to all validation requests
2. **Better logging** - Log both successful and failed validations in dashboard
3. **Atomic validation** - If any validation in a request flow fails, mark entire request as DENIED
