# Architecture Simplification - Customer Query & Payment Agents

**Date**: November 30, 2025
**Issue**: Redundant files and duplicate health checks
**Resolution**: Consolidated into clean, minimal architecture

---

## Problem Statement

### Original Issues:

1. **Duplication**: `execution_service.py` duplicated router pattern from `routes.py`
2. **Multiple Health Checks**:
   - `/v1/health` in `main.py` (ALB health checks)
   - `/v1/execute/health` in `execution_service.py` (redundant)
3. **Unclear Separation**: Why have both `routes.py` and `execution_service.py`?

---

## New Architecture (Simplified)

### File Structure

```
src/customer-query-agent/
├── app/
│   ├── main.py                  # FastAPI app bootstrap, logging, middleware
│   ├── api/
│   │   └── routes.py            # ALL endpoints (query, action, execute)
│   ├── tools/                   # Tool implementations
│   ├── claude_processor.py      # Claude integration
│   └── security_integration.py  # Security Controller integration

src/payment-agent/
├── app/
│   ├── main.py                  # FastAPI app bootstrap
│   ├── api/
│   │   └── routes.py            # ALL endpoints (query, action, execute)
│   └── tools/                   # Payment tools
```

### Removed Files:
- ❌ `src/customer-query-agent/app/execution_service.py` (consolidated into routes.py)
- ❌ `src/payment-agent/app/execution_service.py` (consolidated into routes.py)

---

## Roles & Responsibilities

### `main.py` (Application Bootstrap)
**Purpose**: FastAPI app initialization and infrastructure concerns

**Responsibilities**:
- Create FastAPI app instance
- Configure logging (JSON structured logging)
- Environment variables
- Middleware (request logging)
- **ONE health check** endpoint (`/v1/health`) for ALB target groups
- Include routers
- Startup events

**Does NOT contain**: Business logic, endpoint handlers

---

### `routes.py` (Business Logic)
**Purpose**: All API endpoint handlers

**Endpoints**:

1. **`POST /v1/agents/{agent}/query`** - Claude-based query endpoint
   - User sends natural language message
   - Claude determines which tools to call
   - Security Controller validates each tool call
   - Returns NLP response

2. **`POST /v1/agents/{agent}/action`** - Claude-based action endpoint
   - Same as query (write operations)

3. **`POST /v1/execute`** - Direct tool execution (NEW)
   - Called AFTER Security Controller validation passes
   - Executes tool directly (no Claude)
   - Returns NLP-formatted response using LLM

**Why consolidated?**
- All endpoints are business logic
- `/execute` is just another endpoint (no special treatment needed)
- Easier to maintain (one file instead of two)
- No duplication

---

## Health Check Strategy

### Single Health Check: `/v1/health`

**Location**: `main.py`

**Checks**:
- ✅ DynamoDB connectivity (critical)
- ✅ Security Controller availability (non-critical, warns if down)
- ✅ Bedrock availability (non-critical, warns if down)

**Why only one?**
- ALB target groups only need one health endpoint
- No need for separate `/execute/health` - if LLM generator fails, it's logged but doesn't break health check
- Simpler monitoring

**Response**:
```json
{
  "status": "ok",
  "service": "customer-query-agent",
  "checks": {
    "dynamodb_customers": "ok",
    "dynamodb_orders": "ok",
    "security_controller": "ok",
    "bedrock": "ok"
  }
}
```

---

## Endpoint Comparison

### Before (Redundant)
```
main.py:
  GET /v1/health

routes.py:
  POST /v1/agents/customer-query/query
  POST /v1/agents/customer-query/action

execution_service.py:
  POST /v1/execute
  GET /v1/execute/health  ← REDUNDANT
```

### After (Clean)
```
main.py:
  GET /v1/health  ← Single health check

routes.py:
  POST /v1/agents/customer-query/query
  POST /v1/agents/customer-query/action
  POST /v1/execute  ← Consolidated here
```

---

## Request Flow

### Flow 1: Claude-Based Query (via Dashboard)
```
User → Dashboard → Agent /v1/agents/customer-query/query
                    ↓
                    Claude determines tools
                    ↓
                    For each tool:
                      → Security Controller /validate
                      → If ALLOW: execute tool
                    ↓
                    Return NLP response
```

### Flow 2: Direct Execution (Dashboard → Execute)
```
User → Dashboard → Security Controller /validate
                    ↓
                    If ALLOW:
                      → Agent /v1/execute
                      → Execute tool
                      → LLM format response
                    ↓
                    Return NLP response
```

**Key difference**: Flow 2 skips Claude decision-making (validation already done)

---

## Why This is Better

### 1. **No Duplication**
- ✅ One router per agent (not two)
- ✅ One health check (not two)
- ✅ Less code to maintain

### 2. **Clear Separation of Concerns**
```
main.py       → Infrastructure (app, logging, middleware)
routes.py     → Business logic (all endpoints)
tools/        → Tool implementations
processors/   → Helper modules (Claude, Security)
```

### 3. **Easier to Understand**
- New developers: "Where are the endpoints?" → `routes.py`
- Operations: "Where's the health check?" → `main.py`
- No confusion about when to use which file

### 4. **FastAPI Best Practice**
This follows standard FastAPI patterns:
- `main.py` = app factory
- `routers/` or `api/` = endpoint handlers
- Routers are included in main, not duplicated

---

## Migration Notes

### Changes Made:

1. **Customer Query Agent**:
   - ✅ Moved `/v1/execute` from `execution_service.py` → `routes.py`
   - ✅ Removed `execution_service.py`
   - ✅ Removed `/v1/execute/health`
   - ✅ Updated `main.py` to only include `api_router`

2. **Payment Agent**:
   - ✅ Same changes as Customer Query Agent

3. **No Breaking Changes**:
   - ✅ All existing endpoints still work
   - ✅ `/v1/health` unchanged
   - ✅ API contracts unchanged

---

## Testing

### Verify Health Check
```bash
curl http://localhost:8080/v1/health
```

Expected:
```json
{
  "status": "ok",
  "service": "customer-query-agent",
  "checks": {
    "dynamodb_customers": "ok",
    "dynamodb_orders": "ok",
    "security_controller": "ok",
    "bedrock": "ok"
  }
}
```

### Verify Execute Endpoint
```bash
curl -X POST http://localhost:8080/v1/execute \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "query_customers",
    "tool_params": {"filters": {"state": "CA"}},
    "user_query": "Show customers from California"
  }'
```

Expected: NLP-formatted response

---

## Summary

**Before**: 3 files per agent (main.py, routes.py, execution_service.py)
**After**: 2 files per agent (main.py, routes.py)

**Before**: 2 health checks (`/v1/health`, `/v1/execute/health`)
**After**: 1 health check (`/v1/health`)

**Result**: Simpler, cleaner, follows FastAPI best practices ✅

---

## References

- FastAPI Best Practices: https://fastapi.tiangolo.com/tutorial/bigger-applications/
- Sentra Best Practices: `best-practices.md` (Section 1: Code Organization)
