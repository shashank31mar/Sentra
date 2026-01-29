# Architecture Deep Dive - Your Questions Answered

**Date**: November 30, 2025
**Context**: Milestone 9-1 Implementation

---

## Q1: Why not use the existing health check?

### Answer: **WE ARE using the existing health check!**

**There is ONLY ONE health check per agent service**: `/v1/health` in `main.py`

This was created in **Workstream 7** and we're **reusing it** (not creating a new one).

### What I Changed:
- ❌ **REMOVED**: `/v1/execute/health` (the redundant one I added)
- ✅ **KEPT**: `/v1/health` (the existing one from Workstream 7)

### Current Health Check (Already Exists):
```python
# src/customer-query-agent/app/main.py

@app.get("/v1/health")
async def health_check() -> JSONResponse:
    """
    Health check endpoint for ALB target group

    Checks:
    1. DynamoDB (demo-customers, demo-orders) - CRITICAL
    2. Security Controller - NON-CRITICAL (warns if down)
    3. Bedrock - NON-CRITICAL (warns if down)
    """
    # Returns 200 OK if healthy, 503 if critical dependencies down
```

### Why This Health Check Exists:
From **Workstream 7** (ECS deployment):
- ALB (Application Load Balancer) needs to know if ECS tasks are healthy
- ALB calls `/v1/health` every 30 seconds
- If DynamoDB is down → 503 → ALB marks task as unhealthy → ECS restarts container

**I did NOT create this health check. It was already there. I just removed my redundant one.**

---

## Q2: Is this Agent Service a separate ECS task?

### Answer: **NO - Same ECS task, just added a new endpoint**

### Current Deployment (from Workstream 7):

```
ECS Cluster: sentra-cluster
├── Service: customer-query-agent (1 ECS Task)
│   ├── Container: customer-query-agent
│   │   └── Listens on port 8080
│   │       ├── GET  /v1/health                          ← ALB health check
│   │       ├── GET  /                                   ← Root
│   │       ├── POST /v1/agents/customer-query/query     ← Claude-based (existing)
│   │       ├── POST /v1/agents/customer-query/action    ← Claude-based (existing)
│   │       └── POST /v1/execute                         ← NEW (added in Milestone 9-1)
│   │
│   └── ALB Target Group → Port 8080
│
├── Service: payment-agent (1 ECS Task)
│   └── Container: payment-agent
│       └── Same pattern (3 existing + 1 new endpoint)
│
├── Service: security-controller (1 ECS Task)
├── Service: dashboard (1 ECS Task)
```

### What Changed in Milestone 9-1:

| Before Milestone 9-1 | After Milestone 9-1 |
|---------------------|---------------------|
| Customer Query Agent had 3 endpoints | Customer Query Agent has 4 endpoints |
| - `/v1/health` | - `/v1/health` (same) |
| - `/v1/agents/customer-query/query` | - `/v1/agents/customer-query/query` (same) |
| - `/v1/agents/customer-query/action` | - `/v1/agents/customer-query/action` (same) |
| | - `/v1/execute` ← **NEW** |

**Same Docker image, same ECS task, same container - just added 1 new endpoint.**

---

## Q3: What's the difference between `/v1/query` and `/v1/execute`?

### Answer: **Two different execution flows**

Let me clarify the actual endpoint paths first:

**Actual Endpoints**:
- `/v1/agents/customer-query/query` ← Claude-based (not just `/v1/query`)
- `/v1/execute` ← Direct execution (new)

### Flow Comparison:

#### **Flow A: `/v1/agents/customer-query/query` (Claude-based)**

```
┌─────────────────────────────────────────────────────────────────┐
│ User sends NL message: "Show me customers from California"     │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Dashboard → POST /v1/agents/customer-query/query                │
│   {                                                              │
│     "message": "Show me customers from California"              │
│   }                                                              │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Agent: routes.py → handle_query()                               │
│   1. Calls Claude (Bedrock) with user message                   │
│   2. Claude decides: "I need to call query_customers tool"      │
│   3. Claude returns:                                             │
│      {                                                           │
│        "tool_use": {                                             │
│          "name": "query_customers",                              │
│          "input": {"filters": {"state": "CA"}}                   │
│        }                                                         │
│      }                                                           │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Agent: For EACH tool Claude wants to call:                      │
│   1. Call Security Controller /validate                         │
│      → If DENY: stop, return error                              │
│      → If ALLOW: execute tool                                   │
│   2. Execute tool: query_customers(filters={"state": "CA"})     │
│   3. Get results from DynamoDB                                  │
│   4. Send results back to Claude                                │
│   5. Claude formats final response for user                     │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Return to Dashboard:                                             │
│   {                                                              │
│     "response": "I found 150 customers from California..."       │
│   }                                                              │
└─────────────────────────────────────────────────────────────────┘
```

**Key Points**:
- ✅ Claude decides which tools to call
- ✅ Security validation happens inside agent
- ✅ Claude formats final response
- ✅ Supports multi-tool workflows (Claude can call multiple tools)

---

#### **Flow B: `/v1/execute` (Direct execution - NEW)**

```
┌─────────────────────────────────────────────────────────────────┐
│ User sends NL message: "Show me customers from California"     │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Dashboard: Parse user intent (simple NLP or rule-based)         │
│   Determines: tool = "query_customers"                          │
│              params = {"filters": {"state": "CA"}}              │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Dashboard → Security Controller /validate FIRST                 │
│   {                                                              │
│     "tool_name": "query_customers",                              │
│     "tool_params": {"filters": {"state": "CA"}}                  │
│   }                                                              │
│                                                                  │
│ Response:                                                        │
│   { "decision": "ALLOW" }  ✅                                    │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Dashboard → Agent POST /v1/execute                              │
│   {                                                              │
│     "tool_name": "query_customers",                              │
│     "tool_params": {"filters": {"state": "CA"}},                 │
│     "user_query": "Show me customers from California"           │
│   }                                                              │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Agent: routes.py → execute_tool()                               │
│   1. NO Claude call (tool already determined by Dashboard)      │
│   2. NO Security validation (already done by Dashboard)         │
│   3. Execute tool directly: query_customers()                   │
│   4. Get results from DynamoDB                                  │
│   5. Use LLM to format response (LLMResponseGenerator)          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Return to Dashboard:                                             │
│   {                                                              │
│     "status": "success",                                         │
│     "response": "I found 150 customers from California...",      │
│     "raw_data": [{...}, {...}],                                  │
│     "execution_time_ms": 245                                    │
│   }                                                              │
└─────────────────────────────────────────────────────────────────┘
```

**Key Points**:
- ✅ Dashboard (not Claude) decides which tool to call
- ✅ Security validation happens BEFORE calling agent
- ✅ Agent just executes + formats response
- ✅ Faster (no Claude tool selection overhead)
- ✅ Better for Dashboard workflows where user intent is clear

---

## Side-by-Side Comparison

| Aspect | `/v1/agents/customer-query/query` (Flow A) | `/v1/execute` (Flow B) |
|--------|-------------------------------------------|------------------------|
| **Tool Selection** | Claude decides | Dashboard decides |
| **Security Validation** | Inside agent (for each tool) | Before calling agent (Dashboard) |
| **Claude Involvement** | Yes (determines tools + formats) | No (only LLM for formatting) |
| **Best For** | Complex queries, multi-tool workflows | Simple, single-tool workflows |
| **Performance** | Slower (Claude overhead) | Faster (direct execution) |
| **Example Use Case** | "Show me high-value customers and their recent orders" (multi-tool) | "Show customers from CA" (single tool) |
| **Latency** | ~3-5 seconds | ~2-3 seconds |

---

## When to Use Which?

### Use `/v1/agents/customer-query/query` (Claude-based):

**Scenario 1**: Multi-step workflows
```
User: "Show me customers from CA who have orders over $1000"

Claude:
  1. Calls query_customers(state="CA")
  2. Calls query_orders(customer_ids=[...], min_amount=1000)
  3. Combines results and formats response
```

**Scenario 2**: Ambiguous user intent
```
User: "What's going on with John's account?"

Claude:
  1. Figures out: Need to find customer named John
  2. Calls get_customer_by_id or query_customers(name_contains="John")
  3. Then calls query_orders for that customer
  4. Formats comprehensive response
```

### Use `/v1/execute` (Direct):

**Scenario 1**: Dashboard knows exactly what to do
```
User clicks button: "View Customers from CA"

Dashboard:
  1. Knows: tool = query_customers, params = {state: "CA"}
  2. Validates with Security Controller
  3. Calls /v1/execute directly
  4. Fast response
```

**Scenario 2**: Simple, single-tool queries
```
User: "Show refund status for order ORD-123"

Dashboard:
  1. Parses: order_id = "ORD-123"
  2. Knows: tool = query_refund_status
  3. Validates + executes directly
```

---

## Why Add `/v1/execute` if `/query` Already Exists?

### Reasons:

1. **Performance**: Skip Claude tool selection when Dashboard knows what to do (saves 1-2 seconds)

2. **Cost**: `/v1/execute` only calls LLM once (formatting), `/query` calls Claude twice (tool selection + formatting)

3. **Dashboard Control**: Dashboard can validate first, then execute (better audit trail)

4. **Separation of Concerns**:
   - `/query` = Agentic workflow (Claude decides)
   - `/execute` = Deterministic workflow (Dashboard decides)

5. **Future**: Bedrock Agents will use `/v1/execute` after their guardrail validates (Milestone 3)

---

## Summary Answers:

**Q1**: ✅ We ARE using the existing health check (`/v1/health`). I removed the redundant one I added.

**Q2**: ✅ Same ECS task, just added 1 new endpoint (`/v1/execute`). No new infrastructure.

**Q3**: ✅ Different flows:
- `/v1/agents/customer-query/query` = Claude decides tools, agent validates
- `/v1/execute` = Dashboard decides tool, validates first, then agent executes

Both are valid, use cases differ. `/execute` is optimized for Dashboard-driven workflows.

---

## Visual: Same ECS Task, More Endpoints

```
Before Milestone 9-1:
┌──────────────────────────────────────┐
│ ECS Task: customer-query-agent       │
│ ┌──────────────────────────────────┐ │
│ │ Port 8080                        │ │
│ │ ├── GET  /v1/health              │ │
│ │ ├── POST /v1/.../query           │ │
│ │ └── POST /v1/.../action          │ │
│ └──────────────────────────────────┘ │
└──────────────────────────────────────┘

After Milestone 9-1:
┌──────────────────────────────────────┐
│ ECS Task: customer-query-agent       │  ← SAME TASK
│ ┌──────────────────────────────────┐ │
│ │ Port 8080                        │ │  ← SAME PORT
│ │ ├── GET  /v1/health              │ │  ← SAME
│ │ ├── POST /v1/.../query           │ │  ← SAME
│ │ ├── POST /v1/.../action          │ │  ← SAME
│ │ └── POST /v1/execute             │ │  ← NEW
│ └──────────────────────────────────┘ │
└──────────────────────────────────────┘
```

No infrastructure changes needed. Just deploy updated Docker image.
