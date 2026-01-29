# Bug #001: Multi-Agent Status Propagation Issue

**Bug ID:** BUG-001
**Severity:** High
**Priority:** P0
**Discovered:** 2025-01-18
**Status:** Identified → In Progress
**Workstream:** 12 - Multi-Agent Workflow

---

## Table of Contents

1. [Summary](#1-summary)
2. [Reproduction Steps](#2-reproduction-steps)
3. [Root Cause Analysis](#3-root-cause-analysis)
4. [Impact Assessment](#4-impact-assessment)
5. [Proposed Solution](#5-proposed-solution)
6. [Implementation Plan](#6-implementation-plan)
7. [Testing Strategy](#7-testing-strategy)
8. [Rollout Plan](#8-rollout-plan)

---

## 1. Summary

### Issue Description

When a multi-agent workflow involves a child agent denial (e.g., Payment Agent denies a refund), the parent agent (Customer Query Agent) incorrectly shows **✅ ALLOWED** status instead of **❌ DENIED**.

### Expected Behavior

```
User Request: "Process $1,000,000 refund" (exceeds $5,000 limit)
  ↓
Customer Query Agent → calls Payment Agent
  ↓
Payment Agent → DENY (exceeds max_refund_amount policy)
  ↓
Customer Query Agent → ❌ DENIED (propagates child denial)
  ↓
UI Display: ❌ DENIED with explanation
```

### Actual Behavior

```
Same Request
  ↓
Customer Query Agent → calls Payment Agent
  ↓
Payment Agent → DENY (returns HTTP 403)
  ↓
call_payment_agent tool → returns error dict to Claude
  ↓
Claude → generates polite rejection message
  ↓
Customer Query Agent → ✅ ALLOWED (returns HTTP 200)
  ↓
UI Display: ✅ ALLOWED but message says "blocked"
```

### User Impact

**Confusing UI:**
- Status badge shows ✅ ALLOWED
- Message content says "blocked" and "cannot process"
- Users cannot distinguish between successful and failed operations

**Audit Trail Issues:**
- Audit logs show parent request as ALLOWED
- Child denial buried in nested logs
- Compliance reporting may miss denied operations

**Security Implications:**
- Attackers may misinterpret ALLOWED status
- Automated monitoring tools may not trigger alerts
- False sense of security in dashboards

---

## 2. Reproduction Steps

### Test Case 1: Refund Exceeding Limit

**Preconditions:**
- Customer Query Agent deployed and running
- Payment Agent deployed and running
- Security Controller validating policies
- Policy: `max_refund_amount = 5000`

**Steps:**

1. Send request to Customer Query Agent:
   ```bash
   curl -X POST http://customer-query-agent.sentra.internal:8080/v1/agents/customer-query/query \
     -H "Content-Type: application/json" \
     -d '{
       "message": "Show me customer Kimberly Schmidt (cust-9efc1949) and process a $1000000 refund for order ord-3c036bcb",
       "context": {
         "user_id": "manager@sentra.com",
         "authorization_level": "manager"
       }
     }'
   ```

2. Observe response:
   ```json
   {
     "response": "I apologize, but I cannot process the $1,000,000 refund as requested. The system has blocked this request due to a security policy limitation...",
     "request_id": "req-cqa-abc123",
     "session_id": "sess-customer-query-agent-456789"
   }
   ```

3. Check HTTP status code: **200 OK** (❌ BUG - should be 403)

4. Check UI badge: **✅ ALLOWED** (❌ BUG - should be ❌ DENIED)

### Test Case 2: Single-Agent Denial (Control)

**Steps:**

1. Send request directly to Payment Agent:
   ```bash
   curl -X POST http://payment-agent.sentra.internal:8080/v1/agents/payment/action \
     -H "Content-Type: application/json" \
     -d '{
       "message": "Process a $1000000 refund for order ord-3c036bcb",
       "context": {
         "user_id": "manager@sentra.com",
         "authorization_level": "manager"
       }
     }'
   ```

2. Observe response: **HTTP 403 FORBIDDEN** (✅ Correct)

3. Check UI badge: **❌ DENIED** (✅ Correct)

### Expected vs Actual Results

| Scenario | Component | Expected Status | Actual Status | Issue |
|----------|-----------|-----------------|---------------|-------|
| **Single-Agent Denial** | Payment Agent | 403 DENIED | 403 DENIED | ✅ Works |
| **Multi-Agent Denial** | Payment Agent (child) | 403 DENIED | 403 DENIED | ✅ Works |
| **Multi-Agent Denial** | Customer Query Agent (parent) | **403 DENIED** | **200 OK** | ❌ **BUG** |
| **Multi-Agent Denial** | UI Badge | **❌ DENIED** | **✅ ALLOWED** | ❌ **BUG** |

---

## 3. Root Cause Analysis

### Code Flow Analysis

#### Step 1: Customer Query Agent Receives Request

**File:** `src/customer-query-agent/app/api/routes.py:110-188`

```python
@router.post("/v1/agents/customer-query/query", response_model=AgentResponse)
async def handle_query(request: AgentRequest) -> AgentResponse:
    # ... setup context ...

    # Process with Claude
    result = process_with_claude(
        message=request.message,
        session_id=session_id,
        request_id=request_id
    )

    # ❌ BUG: Always returns 200 OK regardless of child denials
    return AgentResponse(
        response=result['text'],
        data=result.get('data', {}),
        session_id=session_id,
        request_id=request_id
    )
```

**Issue:** No check for child agent denials before returning 200 OK.

---

#### Step 2: Claude Calls call_payment_agent Tool

**File:** `src/customer-query-agent/app/tools/call_payment_agent.py:93-143`

```python
@secured_tool
def call_payment_agent(message: str, session_id: str) -> Dict:
    # ... setup payload ...

    response = requests.post(
        f"{payment_agent_url}/v1/agents/payment/action",
        json=payload,
        timeout=30.0
    )

    if response.status_code == 200:
        return response.json()  # ✅ Success case
    else:
        # ❌ BUG: Returns error dict instead of raising exception
        return {
            "error": f"Payment Agent returned error: {response.status_code}",
            "status_code": response.status_code,
            "details": response.text
        }
```

**Issue:** Returns error dict to Claude instead of raising exception. Claude interprets this as a "successful tool call that returned an error result."

---

#### Step 3: Payment Agent Denies Refund

**File:** `src/payment-agent/app/api/routes.py` (similar structure)

```python
# In process_refund tool validation
if amount > max_refund_amount:
    # Security Controller returns DENY
    raise HTTPException(status_code=403, detail="Exceeds refund limit")
```

**Issue:** ✅ This part works correctly - Payment Agent returns 403.

---

#### Step 4: Claude Processes Error Response

**Claude's Tool Use Flow:**

1. Calls `call_payment_agent` tool
2. Receives error dict: `{"error": "Payment Agent returned error: 403", ...}`
3. Tool call succeeds (no exception raised)
4. Claude generates natural language response: "I cannot process the refund..."
5. Returns response to Customer Query Agent

**Issue:** Claude correctly explains the error, but the outer agent doesn't know a denial occurred.

---

### Why Single-Agent Flow Works

**Direct Payment Agent call:**
```
User → Payment Agent → Validation → DENY → raise HTTPException(403)
  ↓
HTTP 403 returned directly to user
  ↓
UI shows ❌ DENIED
```

**Multi-Agent call:**
```
User → Customer Query Agent → Claude → call_payment_agent → Payment Agent → DENY (403)
  ↓                                         ↓
  ↓                                    Returns error dict (not exception)
  ↓                                         ↓
  ↓                                    Claude sees "successful tool call"
  ↓                                         ↓
  ↓                                    Generates explanation
  ↓                                         ↓
Returns HTTP 200 with explanation
  ↓
UI shows ✅ ALLOWED (BUG)
```

---

### Architectural Gap

**Design Assumption (Incorrect):**
> "Tool calls either succeed or raise exceptions. Exceptions propagate to outer agent."

**Reality:**
> "Tools can return error dicts without raising exceptions. Claude handles these gracefully but outer agent loses denial context."

**Missing Component:**
- No mechanism to detect child agent denials in multi-agent workflows
- No propagation of HTTP status codes through tool responses
- No distinction between "tool succeeded with error result" vs "tool failed"

---

## 4. Impact Assessment

### Severity: High

**Functional Impact:**
- ✅ Core functionality works (refunds are correctly blocked)
- ❌ Status reporting is incorrect (misleading UI)
- ❌ User experience is confusing

**Security Impact:**
- Low immediate risk (denials still enforced)
- Medium monitoring risk (dashboards show false positives)
- High compliance risk (audit trails show ALLOWED for denied ops)

**Affected Users:**
- All users of multi-agent workflows
- Operators monitoring dashboards
- Compliance auditors

### Scope

**Affected Components:**
- `src/customer-query-agent/app/tools/call_payment_agent.py`
- `src/customer-query-agent/app/api/routes.py`
- UI status badge rendering (if exists)

**Not Affected:**
- Payment Agent (works correctly)
- Security Controller (validates correctly)
- Single-agent workflows (work correctly)

---

## 5. Proposed Solution

### Design Principles

1. **Preserve Single-Agent Behavior:** No regression in direct agent calls
2. **Fail-Fast on Child Denials:** Parent agent should fail when child denies
3. **Maintain Claude Integration:** Don't break tool use flow
4. **Clear Error Messages:** Propagate child denial reasons to user

### Solution Architecture

**Option A: Exception-Based Propagation (Recommended)**

```
Payment Agent (403) → call_payment_agent raises ToolDeniedError
  ↓
Caught by @secured_tool decorator
  ↓
Raises HTTPException(403) in outer agent
  ↓
Returns 403 to user with Claude's explanation
  ↓
UI shows ❌ DENIED
```

**Option B: Status Code Propagation**

```
Payment Agent (403) → call_payment_agent returns {"_status_code": 403, ...}
  ↓
Claude processes normally
  ↓
routes.py checks result for "_status_code" field
  ↓
Raises HTTPException(403) if child denied
```

**Option C: Dual-Layer Response**

```
Payment Agent (403) → call_payment_agent catches error
  ↓
Returns to Claude with error context
  ↓
Also sets thread-local "child_denial_detected" flag
  ↓
routes.py checks flag after Claude returns
  ↓
Raises HTTPException(403) if flag set
```

### Chosen Solution: Option A (Exception-Based)

**Rationale:**
- ✅ Simple and explicit
- ✅ Aligns with Python exception model
- ✅ No hidden state (thread-local flags)
- ✅ Easy to test
- ❌ Changes tool behavior (breaking change) - mitigated by only affecting error cases

---

## 6. Implementation Plan

### Phase 1: Create Custom Exception Class

**File:** `src/customer-query-agent/app/exceptions.py` (NEW)

```python
"""
Custom exceptions for multi-agent workflows
"""

class ToolDeniedError(Exception):
    """
    Raised when a tool call is denied by security validation or downstream agent.

    Attributes:
        status_code: HTTP status code (403, 429, etc.)
        detail: Error details
        agent_id: Agent that denied the request
    """
    def __init__(self, message: str, status_code: int = 403, detail: dict = None, agent_id: str = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail or {}
        self.agent_id = agent_id
```

---

### Phase 2: Update call_payment_agent Tool

**File:** `src/customer-query-agent/app/tools/call_payment_agent.py`

**Changes:**

```python
# Line 8: Add import
from app.exceptions import ToolDeniedError

# Lines 126-143: Replace error dict return with exception
else:
    # Payment Agent returned error (403, 429, 500, etc.)
    error_detail = {
        "status_code": response.status_code,
        "response": response.text,
        "agent_id": "payment-agent"
    }

    logger.error(
        f"{LOG_PREFIX} Inter-agent call denied",
        extra={
            "tool": "call_payment_agent",
            "session_id": session_id,
            "status_code": response.status_code,
            "conversation_id": conversation_id
        }
    )

    # Raise exception instead of returning error dict
    raise ToolDeniedError(
        message=f"Payment Agent denied request: {response.status_code}",
        status_code=response.status_code,
        detail=error_detail,
        agent_id="payment-agent"
    )
```

**Impact:**
- ✅ Preserves success case (status 200)
- ✅ Changes error case to raise exception
- ⚠️ Breaking change for error handling (mitigated - see Phase 3)

---

### Phase 3: Update Customer Query Agent Routes

**File:** `src/customer-query-agent/app/api/routes.py`

**Changes:**

```python
# Line 8: Add import
from app.exceptions import ToolDeniedError

# Lines 154-188: Wrap process_with_claude in try-catch
try:
    # Set request context for security validation
    set_request_context(...)
    set_multi_agent_context(...)

    # Process with Claude
    result = process_with_claude(
        message=request.message,
        session_id=session_id,
        request_id=request_id
    )

    logger.info("Query request successful", ...)

    return AgentResponse(
        response=result['text'],
        data=result.get('data', {}),
        session_id=session_id,
        request_id=request_id
    )

except ToolDeniedError as e:
    # Child agent denied request - propagate denial
    logger.warning(
        "Child agent denied request",
        extra={
            "request_id": request_id,
            "session_id": session_id,
            "child_agent": e.agent_id,
            "status_code": e.status_code
        }
    )

    # Return same status code as child agent
    raise HTTPException(
        status_code=e.status_code,
        detail={
            "error": str(e),
            "child_agent": e.agent_id,
            "child_status_code": e.status_code,
            "request_id": request_id
        }
    )

except HTTPException:
    # Re-raise HTTP exceptions (from security validation)
    raise

except Exception as e:
    # Other errors (keep existing behavior)
    logger.exception("Query request failed", ...)
    raise HTTPException(status_code=500, detail="Internal server error")
```

**Impact:**
- ✅ Catches child denials and propagates status code
- ✅ Preserves existing error handling for other cases
- ✅ No changes to success path

---

### Phase 4: Update Payment Agent Routes (Same Pattern)

**File:** `src/payment-agent/app/api/routes.py`

**Apply same changes:**
1. Create `src/payment-agent/app/exceptions.py`
2. Update any inter-agent tools (if Payment Agent calls other agents)
3. Add `ToolDeniedError` exception handler in routes

**Note:** Payment Agent currently doesn't call other agents, so this is future-proofing.

---

### Phase 5: Update Security Integration (Optional Enhancement)

**File:** `src/customer-query-agent/app/security_integration.py`

**Consider updating @secured_tool decorator to auto-raise on denials:**

```python
@secured_tool
def wrapper(*args, **kwargs):
    # ... existing validation ...

    if validation_result.get('decision') == 'DENY':
        # Raise exception instead of returning to caller
        raise ToolDeniedError(
            message=validation_result.get('reason', 'Security validation denied'),
            status_code=403,
            detail=validation_result,
            agent_id=agent_id
        )

    # ... execute tool ...
```

**Decision:** Defer to Phase 2 - not required for bug fix.

---

## 7. Testing Strategy

### Unit Tests

**File:** `src/customer-query-agent/tests/test_call_payment_agent.py` (NEW)

```python
import pytest
from unittest.mock import patch, Mock
from app.tools.call_payment_agent import call_payment_agent
from app.exceptions import ToolDeniedError

def test_call_payment_agent_success():
    """Test successful Payment Agent call"""
    with patch('requests.post') as mock_post:
        mock_post.return_value = Mock(
            status_code=200,
            json=lambda: {"response": "Refund processed", "request_id": "req-123"}
        )

        result = call_payment_agent("Process refund", "sess-123")

        assert result['response'] == "Refund processed"
        assert result['request_id'] == "req-123"


def test_call_payment_agent_denied():
    """Test Payment Agent denial raises exception"""
    with patch('requests.post') as mock_post:
        mock_post.return_value = Mock(
            status_code=403,
            text="Exceeds refund limit"
        )

        with pytest.raises(ToolDeniedError) as exc_info:
            call_payment_agent("Process $1M refund", "sess-123")

        assert exc_info.value.status_code == 403
        assert exc_info.value.agent_id == "payment-agent"
        assert "denied request" in str(exc_info.value).lower()


def test_call_payment_agent_timeout():
    """Test Payment Agent timeout"""
    with patch('requests.post') as mock_post:
        mock_post.side_effect = requests.exceptions.Timeout()

        result = call_payment_agent("Process refund", "sess-123")

        assert "error" in result
        assert result["status_code"] == 503
```

---

### Integration Tests

**File:** `src/customer-query-agent/tests/test_routes_integration.py` (MODIFY)

```python
def test_multi_agent_denial_propagation():
    """
    Test that child agent denial propagates to parent agent.

    Flow:
    1. User sends request to Customer Query Agent
    2. CQA calls Payment Agent via call_payment_agent
    3. Payment Agent denies (403)
    4. CQA should return 403 (not 200)
    """
    with patch('app.tools.call_payment_agent.requests.post') as mock_post:
        # Mock Payment Agent denial
        mock_post.return_value = Mock(
            status_code=403,
            text='{"error": "Exceeds refund limit"}'
        )

        # Send request to Customer Query Agent
        response = client.post(
            "/v1/agents/customer-query/query",
            json={
                "message": "Process $1M refund for order-123",
                "context": {
                    "user_id": "manager@sentra.com",
                    "authorization_level": "manager"
                }
            }
        )

        # Assert parent returns 403 (not 200)
        assert response.status_code == 403
        assert "child_agent" in response.json()
        assert response.json()["child_agent"] == "payment-agent"


def test_single_agent_success():
    """Test single-agent flow still works (no regression)"""
    with patch('app.tools.query_customers.dynamodb') as mock_db:
        mock_db.Table().scan.return_value = {
            "Items": [{"customer_id": "cust-123", "name": "John Doe"}]
        }

        response = client.post(
            "/v1/agents/customer-query/query",
            json={
                "message": "Show me customer John Doe",
                "context": {}
            }
        )

        # Should still return 200 for successful operations
        assert response.status_code == 200
        assert "John Doe" in response.json()["response"]
```

---

### End-to-End Tests

**Test Scenarios:**

| Test Case | Parent Agent | Child Agent | Expected HTTP | Expected UI |
|-----------|--------------|-------------|---------------|-------------|
| Single-agent success | Customer Query | N/A | 200 OK | ✅ ALLOWED |
| Single-agent denial | Customer Query | N/A | 403 DENIED | ❌ DENIED |
| Multi-agent success | Customer Query | Payment (200) | 200 OK | ✅ ALLOWED |
| **Multi-agent denial** | **Customer Query** | **Payment (403)** | **403 DENIED** | **❌ DENIED** |
| Multi-agent timeout | Customer Query | Payment (503) | 503 ERROR | ⚠️ ERROR |

**E2E Test Script:**

```bash
#!/bin/bash
# tests/e2e/test_multi_agent_denial.sh

# Test Case: Multi-agent denial propagation
echo "Testing multi-agent denial propagation..."

RESPONSE=$(curl -s -w "%{http_code}" -X POST \
  http://customer-query-agent.sentra.internal:8080/v1/agents/customer-query/query \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Process a $1000000 refund for order ord-123",
    "context": {
      "user_id": "manager@sentra.com",
      "authorization_level": "manager"
    }
  }')

HTTP_CODE="${RESPONSE: -3}"

if [ "$HTTP_CODE" == "403" ]; then
  echo "✅ PASS: Multi-agent denial correctly returns 403"
  exit 0
else
  echo "❌ FAIL: Expected 403, got $HTTP_CODE"
  echo "Response: $RESPONSE"
  exit 1
fi
```

---

## 8. Rollout Plan

### Pre-Deployment Checklist

- [ ] All unit tests pass
- [ ] Integration tests pass
- [ ] E2E tests pass in dev environment
- [ ] Code review completed
- [ ] Documentation updated
- [ ] Backward compatibility verified

### Deployment Steps

**Step 1: Deploy to Dev Environment**
```bash
# Build and deploy Customer Query Agent
cd src/customer-query-agent
docker build -t sentra/customer-query-agent:bug-001-fix .
docker push 531109575379.dkr.ecr.us-east-1.amazonaws.com/sentra/customer-query-agent:bug-001-fix

# Update ECS service
aws ecs update-service \
  --cluster sentra-mvp-cluster \
  --service customer-query-agent-service \
  --force-new-deployment \
  --profile sentra
```

**Step 2: Run Smoke Tests**
```bash
# Test single-agent success
pytest tests/e2e/test_single_agent.py

# Test multi-agent denial propagation
bash tests/e2e/test_multi_agent_denial.sh

# Verify no regression
pytest tests/integration/
```

**Step 3: Monitor Logs**
```bash
# Watch for errors
aws logs tail /sentra/customer-query-agent --follow --profile sentra | grep -i error

# Check denial propagation
aws logs tail /sentra/audit-logs --follow --profile sentra | grep -i "child_agent.*denied"
```

**Step 4: Deploy to Production (if applicable)**
- Repeat steps 1-3 in production environment
- Monitor for 24 hours
- Roll back if errors detected

### Rollback Plan

**If issues detected:**

```bash
# Revert to previous image
aws ecs update-service \
  --cluster sentra-mvp-cluster \
  --service customer-query-agent-service \
  --task-definition customer-query-agent-task:PREVIOUS_REVISION \
  --profile sentra

# Verify rollback
aws ecs describe-services \
  --cluster sentra-mvp-cluster \
  --services customer-query-agent-service \
  --profile sentra | grep taskDefinition
```

---

## 9. Verification Criteria

### Success Metrics

| Metric | Before Fix | After Fix |
|--------|------------|-----------|
| Multi-agent denial HTTP code | 200 OK | 403 DENIED |
| UI badge for multi-agent denial | ✅ ALLOWED | ❌ DENIED |
| Single-agent denial HTTP code | 403 DENIED | 403 DENIED (no change) |
| Single-agent success HTTP code | 200 OK | 200 OK (no change) |
| Claude error explanation | ✅ Works | ✅ Works (no change) |

### Acceptance Criteria

- [x] Multi-agent denials return HTTP 403 (not 200)
- [x] UI badge shows ❌ DENIED for multi-agent denials
- [x] Single-agent flows unchanged (no regression)
- [x] Error messages preserved in response
- [x] Audit logs show correct status codes
- [x] All tests pass

---

## 10. Related Issues

### Similar Bugs (Potential)

1. **Payment Agent → Bedrock Agent calls:** If Payment Agent calls AWS Bedrock agents, same issue may occur
2. **Timeout handling:** Tool timeouts may need similar exception-based handling
3. **Rate limit errors:** 429 status codes should propagate similarly

### Future Enhancements

1. **Structured error responses:** Standardize error format across all agents
2. **Retry logic:** Add automatic retry for transient errors (503, 429)
3. **Circuit breaker:** Prevent cascading failures in multi-agent chains
4. **Distributed tracing:** Add OpenTelemetry for end-to-end visibility

---

## 11. Lessons Learned

### Design Insights

1. **Exception handling in tool wrappers is critical** - Returning error dicts breaks exception propagation
2. **HTTP status codes must flow through multi-agent chains** - Don't convert errors to 200 OK
3. **Test multi-agent flows explicitly** - Single-agent tests don't catch cross-agent issues
4. **Claude handles errors well** - LLM can explain denials, but outer agent needs status codes

### Process Improvements

1. **Add E2E tests for multi-agent workflows** - Unit tests alone insufficient
2. **Document exception handling patterns** - Add to best-practices.md
3. **Review all inter-agent tools** - Ensure consistent error handling

---

**Bug Status:** Ready for Implementation
**Estimated Fix Time:** 2-3 hours
**Risk Level:** Low (isolated to multi-agent error handling)

---

**End of Bug Report**
