# LLD 12: Multi-Agent Workflow & Rollback (Updated)

**Version:** 2.0
**Last Updated:** 2025-01-18
**Status:** Draft (Updated after codebase review)
**Prerequisites:** [LLD 03: Security Controller](./03-security-controller.md), [LLD 05: AI Agents](./05-ai-agents.md)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Findings from Codebase Review](#2-findings-from-codebase-review)
3. [Multi-Agent Context Propagation](#3-multi-agent-context-propagation)
4. [Cross-Agent Validation](#4-cross-agent-validation)
5. [Rollback Mechanism](#5-rollback-mechanism)
6. [Enhanced Audit Logs](#6-enhanced-audit-logs)
7. [Conversation Timeline API](#7-conversation-timeline-api)
8. [Implementation Plan](#8-implementation-plan)

---

## 1. Overview

### 1.1 Goals

**MVP (This Workstream):**

1. **Multi-Agent Workflow Security**
   - Track parent-child relationships in cross-agent calls
   - Prevent privilege escalation via agent delegation
   - Validate `allowed_agents` policy for inter-agent calls

2. **Transaction Rollback**
   - Roll back all actions in a conversation when any agent fails
   - Demonstrate 2 WRITEs on different agents: 1 succeeds, 1 fails → both rolled back
   - Support both self-hosted and AWS Bedrock agents

3. **Enhanced Observability**
   - Link audit logs by `conversation_id`
   - Show complete timeline of tool calls and agent invocations
   - Dashboard visualization of conversation flow

**Phase 2 (Future):**
- Post-processing anomaly detection
- Automatic rollback triggers based on patterns
- ML-based fraud detection

---

## 2. Findings from Codebase Review

### 2.1 What Already Exists ✅

#### Context Management (Both Agents)
**File:** `src/{agent}/app/security_integration.py`

```python
# Lines 20-26: Existing context variables
_request_id: ContextVar[Optional[str]] = ContextVar('request_id', default=None)
_session_id: ContextVar[Optional[str]] = ContextVar('session_id', default=None)
_user_input: ContextVar[Optional[str]] = ContextVar('user_input', default=None)
_request_context: ContextVar[Optional[Dict]] = ContextVar('request_context', default=None)

# Lines 31-36: Context setter
def set_request_context(request_id: str, session_id: str, user_input: str, context: Dict = None):
    _request_id.set(request_id)
    _session_id.set(session_id)
    _user_input.set(user_input)
    _request_context.set(context or {})

# Lines 54-56: Context getter
def get_current_context() -> Dict:
    return _request_context.get() or {}
```

**✅ WE ALREADY HAVE:** Context manager with `_request_context` for arbitrary data

#### Validation Context (Security Controller)
**File:** `src/security-controller/app/validators/policy_engine.py`

```python
# Lines 172-197: Already validates invoke_agent!
if request.tool_name == "invoke_agent":
    target_agent = request.tool_params.get("agent_id")
    allowed_agents = policy.get('allowed_agents', [])

    if target_agent not in allowed_agents:
        return ValidationResult(
            decision="DENY",
            reason=f"Agent '{request.agent_id}' cannot invoke '{target_agent}'",
            violation_type="UNAUTHORIZED_AGENT_INVOCATION",
            penalty=-15,
            should_deny=True
        )
```

**✅ ALREADY VALIDATES:** `allowed_agents` in agent policy

#### Audit Log Structure
**From actual CloudWatch logs:**

```json
{
  "request_id": "req-cqa-a57a4999a15b",
  "session_id": "sess-customer-query-agent-1766463411",
  "agent_id": "customer-query-agent",
  "tool_name": "query_customers",
  "operation_type": "READ",
  "decision": "ALLOW",
  "timestamp": "2025-12-23T04:16:55.971732Z",
  "latency_ms": 652.17,
  "trust_score_before": 100.0,
  "trust_score_after": 100.0,
  "trust_delta": 0.0,
  "user_input": "Show me customers from California",
  "action_id": "act-process_refund-20251223041701-fdcba5",  // For WRITE operations
  "reversible": true,
  "rollback_status": "NOT_ROLLED_BACK"
}
```

**✅ ALREADY HAS:** `action_id`, `reversible`, `rollback_status` for rollback support

#### Tool: call_payment_agent
**File:** `src/customer-query-agent/app/tools/call_payment_agent.py`

```python
# Lines 39-60: Already passes parent_request_id and caller_agent_id!
parent_request_id = get_current_request_id()

payload = {
    "message": message,
    "session_id": session_id,
    "context": {
        "caller_agent_id": "customer-query-agent",
        "parent_request_id": parent_request_id
    }
}
```

**✅ ALREADY PASSES:** `parent_request_id`, `caller_agent_id`

### 2.2 What's Missing ❌

| Feature | Status | Location |
|---------|--------|----------|
| **conversation_id** generation/propagation | ❌ Missing | Agents, Security Controller |
| **call_depth** tracking | ❌ Missing | Agents |
| **Cross-agent validator** in validation pipeline | ❌ Missing | Security Controller |
| **Audit log with multi_agent_context** | ❌ Missing | AuditLogger |
| **GET /v1/logs/conversation/{id}** API | ❌ Missing | Security Controller |
| **Rollback coordinator** | ❌ Missing | Security Controller |
| **Timeline view** in dashboard | ❌ Missing | Dashboard |

### 2.3 Design Decisions

Based on code review:

| Decision | Rationale |
|----------|-----------|
| **Extend existing context manager** | Already have `_request_context` ContextVar - use it! |
| **Use `allowed_agents` policy** | Already validated in policy_engine.py:174 |
| **Reuse action_id/rollback_status** | Already in audit logs - just need coordinator |
| **Add conversation_id to context** | Store in existing `_request_context` dict |
| **New API endpoint required** | `/v1/logs/conversation/{id}` doesn't exist |

---

## 3. Multi-Agent Context Propagation

### 3.1 Extended Context Schema

**Update existing `_request_context` to include:**

```python
# src/{agent}/app/security_integration.py
# Existing ContextVar (line 26)
_request_context: ContextVar[Optional[Dict]] = ContextVar('request_context', default=None)

# NEW: Helper to add multi-agent fields
def set_multi_agent_context(
    conversation_id: str,
    parent_request_id: Optional[str] = None,
    caller_agent_id: Optional[str] = None,
    call_depth: int = 0
):
    """Add multi-agent fields to existing request context"""
    context = get_current_context()
    context['conversation_id'] = conversation_id
    context['parent_request_id'] = parent_request_id
    context['caller_agent_id'] = caller_agent_id
    context['call_depth'] = call_depth
    _request_context.set(context)


def get_conversation_id() -> Optional[str]:
    """Get conversation_id from context"""
    return get_current_context().get('conversation_id')


def get_call_depth() -> int:
    """Get call depth from context (default 0)"""
    return get_current_context().get('call_depth', 0)
```

### 3.2 Agent Route Initialization

**Update both Customer Query Agent and Payment Agent:**

**File:** `src/customer-query-agent/app/api/routes.py`

```python
# Lines 109-153 (handle_query endpoint)
@router.post("/v1/agents/customer-query/query", response_model=AgentResponse)
async def handle_query(request: AgentRequest) -> AgentResponse:
    # Generate IDs
    request_id = _generate_request_id()
    session_id = request.session_id or _generate_session_id()

    # NEW: Extract or generate conversation_id
    conversation_id = request.context.get('conversation_id')
    if not conversation_id:
        conversation_id = f"conv-{uuid.uuid4().hex[:12]}"

    # NEW: Extract multi-agent context (if called by another agent)
    parent_request_id = request.context.get('parent_request_id')
    caller_agent_id = request.context.get('caller_agent_id')
    call_depth = request.context.get('call_depth', 0)

    try:
        # Set request context (EXISTING)
        set_request_context(
            request_id=request_id,
            session_id=session_id,
            user_input=request.message,
            context=request.context  # Pass full context
        )

        # NEW: Set multi-agent context
        set_multi_agent_context(
            conversation_id=conversation_id,
            parent_request_id=parent_request_id,
            caller_agent_id=caller_agent_id,
            call_depth=call_depth
        )

        # Process with Claude (EXISTING)
        result = process_with_claude(...)

        return AgentResponse(
            response=result['text'],
            data=result.get('data', {}),
            session_id=session_id,
            request_id=request_id
        )
```

**Same changes for Payment Agent** (`src/payment-agent/app/api/routes.py`)

### 3.3 Updated call_payment_agent Tool

**File:** `src/customer-query-agent/app/tools/call_payment_agent.py`

```python
# Lines 18-60: Update payload to include conversation_id and call_depth
@secured_tool
def call_payment_agent(message: str, session_id: str) -> Dict:
    # Get current context (EXISTING)
    parent_request_id = get_current_request_id()

    # NEW: Get conversation_id and call_depth
    conversation_id = get_conversation_id()
    call_depth = get_call_depth()

    # NEW: Get original user context to propagate
    current_context = get_current_context()
    user_id = current_context.get('user_id')
    auth_level = current_context.get('authorization_level', 'manager')

    # Build request payload
    payload = {
        "message": message,
        "session_id": session_id,
        "context": {
            # Multi-agent tracking (EXISTING + NEW)
            "caller_agent_id": "customer-query-agent",
            "parent_request_id": parent_request_id,
            "conversation_id": conversation_id,  # NEW
            "call_depth": call_depth + 1,        # NEW

            # Propagate user context (NEW)
            "user_id": user_id,
            "authorization_level": auth_level
        }
    }

    # Call Payment Agent (EXISTING)
    response = requests.post(...)
    return response.json()
```

---

## 4. Cross-Agent Validation

### 4.1 Updated @secured_tool Decorator

**File:** `src/{agent}/app/security_integration.py`

```python
# Lines 217-236: Update validation_context to include multi-agent fields
@secured_tool
def wrapper(*args, **kwargs):
    context = get_current_context()

    # Build validation context with multi-agent fields
    validation_context = {
        # User context (EXISTING)
        "authorization_level": context.get("authorization_level", "standard"),
        "user_id": context.get("user_id"),
        "ip_address": context.get("ip_address"),

        # Multi-agent context (NEW)
        "conversation_id": context.get("conversation_id"),
        "parent_request_id": context.get("parent_request_id"),
        "caller_agent_id": context.get("caller_agent_id"),
        "call_depth": context.get("call_depth", 0)
    }

    # Build validation request (send to Security Controller)
    validation_request = {
        "request_id": request_id,
        "session_id": session_id,
        "agent_id": agent_id,
        "tool_name": func.__name__,
        "tool_params": kwargs,
        "user_input": user_input,
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        "operation_type": operation_type,
        "context": validation_context  # Includes multi-agent fields
    }
```

### 4.2 New Cross-Agent Validator

**File:** `src/security-controller/app/validators/cross_agent_validator.py` (NEW)

```python
"""
Cross-Agent Validator - Step 2.5 of Validation Pipeline

Validates inter-agent calls to prevent privilege escalation and infinite recursion.

Checks:
1. Call depth limit (prevent infinite loops)
2. Caller authorization (is caller in target's allowed_agents?)
"""
import logging
from typing import Optional

from app.api.models import ValidationRequest, ValidationResult
from app.validators.policy_engine import PolicyEngine

logger = logging.getLogger(__name__)


class CrossAgentValidator:
    """
    Validates cross-agent calls.

    Runs AFTER PolicyEngine but uses same policy data.
    """

    MAX_CALL_DEPTH = 5

    def __init__(self):
        self.policy_engine = PolicyEngine()

    async def validate(self, request: ValidationRequest) -> ValidationResult:
        """
        Validate cross-agent call.

        Args:
            request: Validation request with context

        Returns:
            ValidationResult (ALLOW if valid, DENY if invalid)
        """
        # Extract multi-agent context
        caller_agent_id = request.context.get('caller_agent_id')
        parent_request_id = request.context.get('parent_request_id')
        call_depth = request.context.get('call_depth', 0)

        # No cross-agent call - skip validation
        if not caller_agent_id or not parent_request_id:
            return ValidationResult(
                decision="ALLOW",
                reason="Not a cross-agent call",
                should_deny=False
            )

        # Check 1: Call depth limit
        if call_depth > self.MAX_CALL_DEPTH:
            logger.warning(
                f"Call depth {call_depth} exceeds maximum {self.MAX_CALL_DEPTH}",
                extra={
                    "request_id": request.request_id,
                    "caller": caller_agent_id,
                    "target": request.agent_id,
                    "call_depth": call_depth
                }
            )
            return ValidationResult(
                decision="DENY",
                reason=f"Max call depth exceeded ({call_depth} > {self.MAX_CALL_DEPTH})",
                violation_type="MAX_CALL_DEPTH_EXCEEDED",
                penalty=-20,
                should_deny=True
            )

        # Check 2: Is caller authorized to invoke this agent?
        # Load target agent's policy
        try:
            policy = await self.policy_engine.get_agent_policy(request.agent_id)
        except Exception as e:
            logger.exception(f"Failed to load policy for {request.agent_id}")
            return ValidationResult(
                decision="DENY",
                reason="Failed to load agent policy",
                violation_type="POLICY_LOAD_ERROR",
                penalty=-15,
                should_deny=True
            )

        # Get allowed callers (inverse of allowed_agents)
        # If target agent has allowed_agents=['*'], any agent can call it
        # If target agent has allowed_agents=['customer-query-agent'], only CQA can call it
        allowed_callers = policy.get('allowed_callers', [])

        # Empty list = allow all (backward compatible)
        if not allowed_callers:
            logger.info(
                f"Cross-agent call allowed (open policy)",
                extra={
                    "caller": caller_agent_id,
                    "target": request.agent_id
                }
            )
            return ValidationResult(
                decision="ALLOW",
                reason="Cross-agent call authorized (open policy)",
                should_deny=False
            )

        # Check if caller is in allowed list
        if caller_agent_id in allowed_callers or '*' in allowed_callers:
            logger.info(
                f"Cross-agent call authorized",
                extra={
                    "caller": caller_agent_id,
                    "target": request.agent_id
                }
            )
            return ValidationResult(
                decision="ALLOW",
                reason="Cross-agent call authorized",
                should_deny=False
            )

        # Caller not authorized
        logger.warning(
            f"Unauthorized cross-agent call",
            extra={
                "caller": caller_agent_id,
                "target": request.agent_id,
                "allowed_callers": allowed_callers
            }
        )
        return ValidationResult(
            decision="DENY",
            reason=f"Agent '{caller_agent_id}' not authorized to invoke '{request.agent_id}'",
            violation_type="UNAUTHORIZED_CROSS_AGENT_CALL",
            penalty=-25,
            should_deny=True
        )
```

### 4.3 Update Validation Pipeline

**File:** `src/security-controller/app/services/validation_service.py`

```python
# Lines 44-55: Add cross_agent_validator
def __init__(self):
    self.session_manager = SessionManager()

    # Existing validators
    from app.validators.trust_checker import TrustChecker
    from app.validators.policy_engine import PolicyEngine
    from app.validators.sigma_engine import SigmaEngine
    from app.validators.context_validator import ContextValidator
    from app.validators.abuse_detector import AbuseDetector

    # NEW: Cross-agent validator
    from app.validators.cross_agent_validator import CrossAgentValidator

    self.trust_checker = TrustChecker()
    self.policy_engine = PolicyEngine()
    self.cross_agent_validator = CrossAgentValidator()  # NEW
    self.sigma_engine = SigmaEngine()
    self.context_validator = ContextValidator()
    self.abuse_detector = AbuseDetector()


async def _run_validation_pipeline(self, request: ValidationRequest, session: Dict) -> ValidationResult:
    """
    Run 6-step validation pipeline (added cross-agent validator).
    """
    # Step 1: Trust Score Check
    result = await self.trust_checker.validate(session)
    if result.should_deny:
        return result

    # Step 2: Policy Engine
    result = await self.policy_engine.validate(request)
    if result.should_deny:
        return result

    # Step 2.5: Cross-Agent Validator (NEW)
    result = await self.cross_agent_validator.validate(request)
    if result.should_deny:
        return result

    # Step 3: Sigma Rules
    result = await self.sigma_engine.match_rules(request.user_input)
    if result.should_deny:
        return result

    # Step 4: Context Validator
    result = await self.context_validator.validate(request, session)
    if result.should_deny:
        return result

    # Step 5: Abuse Detector
    result = await self.abuse_detector.validate(session)
    if result.should_deny:
        return result

    # All checks passed
    return ValidationResult(decision="ALLOW", reason="All validation checks passed", should_deny=False)
```

---

## 5. Rollback Mechanism

### 5.1 Design Principles

**Current State (Already Implemented):**
- ✅ `POST /v1/rollback` exists (single action rollback by `action_id`)
- ✅ `RollbackCoordinator` class exists (src/security-controller/app/utils/rollback_coordinator.py)
- ✅ `reverse_refund` tool exists in Payment Agent
- **Limitation:** Only supports manual rollback of individual actions

**New Requirement:** Conversation-wide rollback when any agent fails

**MVP Demo Scenario: Multi-Step Failure (One WRITE Fails)**

```
User Request: "Create order ORD-123 and process refund of $10,000"
  ↓
Payment Agent: create_order(ORD-123, amount=500) → ALLOWED ✅
  ↓
Payment Agent: process_refund(ORD-123, amount=10000) → DENIED ❌ (exceeds limit)
  ↓
TRIGGER: Auto-rollback conversation (1 action failed)
  ↓
RESULT: create_order reversed (prevents orphaned order)
```

**Solution:** Compensating transactions with conversation-level coordination

| Tool | Rollback Action | Post-Processing Trigger |
|------|----------------|-------------------------|
| `create_order` | Delete order from DynamoDB | Always reversible |
| `process_refund` | Call `reverse_refund` with transaction_id | Always reversible |
| `update_customer` | Restore previous state from snapshot | Fraud detection |
| `query_customers` | No rollback needed (READ operation) | N/A |

**Architecture:**

```
Rollback Coordinator (Enhanced)
  ↓
1. Query audit logs for conversation_id
2. Filter for WRITE operations with action_id
3. Reverse order: last action first (LIFO)
4. For each action:
   - Call agent's rollback tool (e.g., reverse_refund)
   - Update rollback_status in audit log
5. Return rollback summary
```

### 5.2 Rollback Coordinator

**File:** `src/security-controller/app/services/rollback_coordinator.py` (NEW)

```python
"""
Rollback Coordinator - Compensating Transaction Manager

Rolls back all WRITE actions in a conversation when requested.

Design:
- Fetches all audit logs for conversation_id
- Filters for reversible WRITE operations
- Executes rollback in reverse chronological order (LIFO)
- Updates rollback_status in audit log
"""
import logging
from typing import List, Dict, Optional
import requests

from app.utils.audit_logger import AuditLogger

logger = logging.getLogger(__name__)


class RollbackCoordinator:
    """
    Coordinates rollback of failed multi-agent transactions.
    """

    # Mapping: tool_name → rollback_tool_name
    ROLLBACK_TOOLS = {
        'process_refund': 'reverse_refund',
        'update_customer': 'restore_customer',
        'delete_order': 'restore_order',
    }

    # Agent URLs
    AGENT_URLS = {
        'customer-query-agent': 'http://customer-query-agent.sentra.internal:8080',
        'payment-agent': 'http://payment-agent.sentra.internal:8080'
    }

    def __init__(self):
        self.audit_logger = AuditLogger()

    async def rollback_conversation(
        self,
        conversation_id: str,
        reason: str = "Agent failure"
    ) -> Dict:
        """
        Roll back all WRITE operations in a conversation.

        Args:
            conversation_id: Conversation to roll back
            reason: Reason for rollback

        Returns:
            Dict with success status and rollback details
        """
        logger.info(
            f"Starting rollback for conversation {conversation_id}",
            extra={"conversation_id": conversation_id, "reason": reason}
        )

        # Step 1: Fetch all audit logs for conversation
        logs = await self._fetch_conversation_logs(conversation_id)

        # Step 2: Filter for reversible WRITE operations
        reversible_actions = [
            log for log in logs
            if log.get('operation_type') == 'WRITE'
            and log.get('decision') == 'ALLOW'
            and log.get('reversible') is True
            and log.get('rollback_status') == 'NOT_ROLLED_BACK'
        ]

        if not reversible_actions:
            logger.info(f"No reversible actions found for conversation {conversation_id}")
            return {
                "success": True,
                "rolled_back_count": 0,
                "message": "No reversible actions to roll back"
            }

        # Step 3: Reverse order (LIFO - last action first)
        reversible_actions.reverse()

        logger.info(
            f"Found {len(reversible_actions)} reversible actions to roll back",
            extra={"conversation_id": conversation_id, "count": len(reversible_actions)}
        )

        # Step 4: Execute rollback for each action
        rolled_back = []
        failed = []

        for log in reversible_actions:
            result = await self._rollback_action(log)

            if result['success']:
                rolled_back.append(log['action_id'])
                # Update audit log
                await self._update_rollback_status(
                    log['action_id'],
                    'ROLLED_BACK',
                    result.get('rollback_action_id')
                )
            else:
                failed.append({
                    'action_id': log['action_id'],
                    'error': result.get('error')
                })
                logger.error(
                    f"Failed to roll back action {log['action_id']}",
                    extra={"action_id": log['action_id'], "error": result.get('error')}
                )

        # Step 5: Return summary
        return {
            "success": len(failed) == 0,
            "conversation_id": conversation_id,
            "rolled_back_count": len(rolled_back),
            "failed_count": len(failed),
            "rolled_back_actions": rolled_back,
            "failed_actions": failed,
            "reason": reason
        }

    async def _fetch_conversation_logs(self, conversation_id: str) -> List[Dict]:
        """
        Fetch all audit logs for a conversation from CloudWatch.

        Args:
            conversation_id: Conversation identifier

        Returns:
            List of audit log entries
        """
        # Query CloudWatch Logs for conversation_id
        # (Implementation depends on how we store conversation_id in logs)
        # For now, return mock data
        return await self.audit_logger.query_logs_by_conversation(conversation_id)

    async def _rollback_action(self, log: Dict) -> Dict:
        """
        Execute rollback for a single action.

        Args:
            log: Audit log entry for the action

        Returns:
            Dict with success status and rollback_action_id
        """
        tool_name = log['tool_name']
        agent_id = log['agent_id']
        tool_params = log.get('tool_params', {})

        # Get rollback tool name
        rollback_tool = self.ROLLBACK_TOOLS.get(tool_name)

        if not rollback_tool:
            logger.warning(f"No rollback tool defined for {tool_name}")
            return {
                "success": False,
                "error": f"No rollback tool defined for {tool_name}"
            }

        # Get agent URL
        agent_url = self.AGENT_URLS.get(agent_id)

        if not agent_url:
            return {
                "success": False,
                "error": f"Unknown agent: {agent_id}"
            }

        # Build rollback request
        # For process_refund → reverse_refund, pass same order_id
        rollback_params = self._build_rollback_params(tool_name, tool_params)

        # Call agent to execute rollback tool
        try:
            response = requests.post(
                f"{agent_url}/v1/agents/{agent_id.replace('-agent', '')}/action",
                json={
                    "message": f"Roll back {tool_name}: {rollback_params}",
                    "session_id": log['session_id'],
                    "context": {
                        "rollback_mode": True,
                        "original_action_id": log['action_id']
                    }
                },
                timeout=10.0
            )

            if response.status_code == 200:
                result = response.json()
                return {
                    "success": True,
                    "rollback_action_id": result.get('request_id')
                }
            else:
                return {
                    "success": False,
                    "error": f"Rollback request failed: {response.status_code}"
                }

        except Exception as e:
            logger.exception(f"Error executing rollback for {tool_name}")
            return {
                "success": False,
                "error": str(e)
            }

    def _build_rollback_params(self, tool_name: str, original_params: Dict) -> Dict:
        """
        Build parameters for rollback tool based on original params.

        Args:
            tool_name: Original tool name
            original_params: Original tool parameters

        Returns:
            Parameters for rollback tool
        """
        if tool_name == 'process_refund':
            # reverse_refund needs order_id and refund_id
            return {
                "order_id": original_params.get('order_id'),
                "refund_id": original_params.get('refund_id')  # Assuming refund creates ID
            }

        elif tool_name == 'update_customer':
            # restore_customer needs customer_id and snapshot
            return {
                "customer_id": original_params.get('customer_id'),
                "snapshot": original_params.get('previous_state')  # Stored in action metadata
            }

        # Default: return original params
        return original_params

    async def _update_rollback_status(
        self,
        action_id: str,
        status: str,
        rollback_action_id: Optional[str] = None
    ):
        """
        Update rollback_status in audit log.

        NOTE: CloudWatch Logs are immutable, so we append a new log entry
        indicating rollback status change.
        """
        rollback_log = {
            "event_type": "ROLLBACK_STATUS_UPDATE",
            "action_id": action_id,
            "rollback_status": status,
            "rollback_action_id": rollback_action_id,
            "timestamp": "..."
        }

        await self.audit_logger.write_log(rollback_log)
```

### 5.3 Rollback API Endpoints

**Current Endpoint (Already Exists):**

```python
# File: src/security-controller/app/api/routes.py (line 630)
@router.post("/rollback")
async def rollback_action(request: Dict) -> Dict:
    """
    Manually rollback a single reversible action.

    Request Body:
        action_id: Unique action identifier
        action_type: Type of action (e.g., "process_refund")
        reason: Reason for rollback
        operator_id: Operator performing rollback

    Returns:
        Success response with rollback details
    """
    # Implementation exists in rollback_coordinator.py
```

**New Endpoint (Conversation-Wide Rollback):**

```python
# NEW endpoint for conversation-wide rollback
@router.post("/rollback/conversation/{conversation_id}")
async def rollback_conversation(
    conversation_id: str,
    reason: str = "Manual rollback requested",
    operator_id: str = "system"
) -> Dict:
    """
    Roll back ALL WRITE operations in a conversation.

    Path Parameters:
        conversation_id: Conversation to roll back

    Query Parameters:
        reason: Reason for rollback (optional)
        operator_id: Operator performing rollback (default: "system")

    Returns:
        Rollback summary with success status

    Example Response:
    {
        "success": true,
        "conversation_id": "conv-abc-123",
        "rolled_back_count": 2,
        "failed_count": 0,
        "rolled_back_actions": [
            "act-refund-001",
            "act-order-002"
        ],
        "reason": "Post-processing fraud detection"
    }
    """
    from app.utils.rollback_coordinator import RollbackCoordinator

    coordinator = RollbackCoordinator()
    result = await coordinator.rollback_conversation(
        conversation_id=conversation_id,
        reason=reason,
        operator_id=operator_id
    )

    return result
```

---

## 6. Enhanced Audit Logs

### 6.1 Updated Audit Log Schema

**File:** `src/security-controller/app/utils/audit_logger.py`

Add `multi_agent_context` to audit logs:

```python
async def write_log(self, log_entry: Dict):
    """
    Write audit log to CloudWatch with multi-agent context.
    """
    # Extract multi-agent context from request
    multi_agent_context = {
        "conversation_id": log_entry.get('conversation_id'),
        "parent_request_id": log_entry.get('parent_request_id'),
        "caller_agent_id": log_entry.get('caller_agent_id'),
        "call_depth": log_entry.get('call_depth', 0)
    }

    # Build enhanced log entry
    enhanced_log = {
        # Core fields (EXISTING)
        "request_id": log_entry['request_id'],
        "session_id": log_entry['session_id'],
        "agent_id": log_entry['agent_id'],
        "tool_name": log_entry['tool_name'],
        "operation_type": log_entry['operation_type'],
        "decision": log_entry['decision'],
        "timestamp": log_entry['timestamp'],
        "latency_ms": log_entry['latency_ms'],
        "trust_score_before": log_entry['trust_score_before'],
        "trust_score_after": log_entry['trust_score_after'],
        "trust_delta": log_entry['trust_delta'],
        "user_input": log_entry['user_input'],

        # Multi-agent context (NEW)
        "multi_agent_context": multi_agent_context,

        # DENY fields (if applicable)
        "reason": log_entry.get('reason'),
        "violation_type": log_entry.get('violation_type'),
        "threat_type": log_entry.get('threat_type'),
        "matched_rule": log_entry.get('matched_rule'),
        "severity": log_entry.get('severity'),

        # Rollback fields (EXISTING)
        "action_id": log_entry.get('action_id'),
        "reversible": log_entry.get('reversible'),
        "rollback_status": log_entry.get('rollback_status', 'NOT_ROLLED_BACK'),

        # Tool parameters
        "tool_params": log_entry.get('tool_params', {})
    }

    # Write to CloudWatch
    await self._put_log_event(enhanced_log)
```

---

## 7. Conversation Timeline API

### 7.1 New Endpoint

**File:** `src/security-controller/app/api/routes.py`

```python
@router.get("/logs/conversation/{conversation_id}")
async def get_conversation_timeline(conversation_id: str) -> Dict:
    """
    Get complete timeline of a conversation (cross-agent).

    Returns hierarchical tree of requests showing parent-child relationships.

    Path Parameters:
        conversation_id: Conversation identifier

    Returns:
        {
            "conversation_id": str,
            "total_requests": int,
            "timeline": [...]  # Hierarchical tree
        }
    """
    from app.services.conversation_service import ConversationService

    service = ConversationService()
    return await service.get_timeline(conversation_id)
```

### 7.2 Conversation Service

**File:** `src/security-controller/app/services/conversation_service.py` (NEW)

```python
"""
Conversation Service - Query and analyze conversation timelines
"""
import logging
from typing import List, Dict
import time

from app.utils.audit_logger import AuditLogger

logger = logging.getLogger(__name__)


class ConversationService:
    """
    Provides conversation-level queries and analytics.
    """

    def __init__(self):
        self.audit_logger = AuditLogger()

    async def get_timeline(self, conversation_id: str) -> Dict:
        """
        Get complete timeline for a conversation with hierarchical structure.

        Args:
            conversation_id: Conversation identifier

        Returns:
            Dict with timeline tree
        """
        # Query CloudWatch Logs for all entries with this conversation_id
        logs = await self.audit_logger.query_logs_by_conversation(conversation_id)

        if not logs:
            return {
                "conversation_id": conversation_id,
                "total_requests": 0,
                "timeline": [],
                "error": "No logs found for this conversation"
            }

        # Build hierarchical timeline
        timeline = self._build_timeline_tree(logs)

        return {
            "conversation_id": conversation_id,
            "total_requests": len(logs),
            "timeline": timeline
        }

    def _build_timeline_tree(self, logs: List[Dict]) -> List[Dict]:
        """
        Build hierarchical tree showing parent-child relationships.

        Args:
            logs: Flat list of audit log entries

        Returns:
            List of root requests with nested children
        """
        # Index logs by request_id
        log_map = {log['request_id']: log for log in logs}

        # Find root requests (no parent)
        roots = []

        for log in logs:
            parent_id = log.get('multi_agent_context', {}).get('parent_request_id')

            if not parent_id:
                # Root request
                log['children'] = []
                roots.append(log)
            else:
                # Child request - attach to parent
                if parent_id in log_map:
                    if 'children' not in log_map[parent_id]:
                        log_map[parent_id]['children'] = []
                    log['children'] = []
                    log_map[parent_id]['children'].append(log)

        return roots
```

### 7.3 AuditLogger Enhancement

**File:** `src/security-controller/app/utils/audit_logger.py`

```python
async def query_logs_by_conversation(self, conversation_id: str) -> List[Dict]:
    """
    Query all audit logs for a conversation using CloudWatch Logs Insights.

    Args:
        conversation_id: Conversation identifier

    Returns:
        List of log entries sorted by timestamp
    """
    import boto3
    import time

    logs_client = boto3.client('logs', region_name='us-east-1')

    # Build CloudWatch Logs Insights query
    query = f"""
    fields @timestamp, @message
    | filter multi_agent_context.conversation_id = "{conversation_id}"
    | sort @timestamp asc
    """

    # Start query
    start_time = int(time.time()) - 3600  # Last hour
    end_time = int(time.time())

    response = logs_client.start_query(
        logGroupName='/sentra/audit-logs',
        queryString=query,
        startTime=start_time,
        endTime=end_time
    )

    query_id = response['queryId']

    # Wait for query to complete
    while True:
        result = logs_client.get_query_results(queryId=query_id)
        status = result['status']

        if status == 'Complete':
            break
        elif status == 'Failed':
            raise Exception("CloudWatch Logs query failed")

        time.sleep(0.5)

    # Parse results
    logs = []
    for row in result['results']:
        message_field = next((f for f in row if f['field'] == '@message'), None)
        if message_field:
            import json
            logs.append(json.loads(message_field['value']))

    return logs
```

---

## 8. Future Enhancements (Phase 2)

### 8.1 Post-Processing and Anomaly Detection

**Status:** Not in current scope (Phase 2)

**Concept:** Some attacks cannot be detected at validation time. Need async analysis after execution.

**Examples:**
1. **Distributed attack:** Single refund looks normal, but 50 refunds in 5 minutes is fraud
2. **Data exfiltration:** Query looks benign, but user downloads 10,000 records in sequence
3. **Privilege escalation:** User updates their own email to admin domain

**Planned Solution:**
- Post-processor runs every 5 minutes
- Analyzes patterns: bulk operations, escalation, velocity anomalies
- Triggers automatic rollback if anomaly detected

**Anomaly Detection Rules (Planned):**

| Rule | Pattern | Action |
|------|---------|--------|
| **Bulk Refunds** | >5 refunds in same conversation | Rollback conversation |
| **Data Exfiltration** | >1000 records queried in 5 min | Rollback + quarantine session |
| **Privilege Escalation** | `update_user_role` followed by high-value action | Rollback conversation |
| **Velocity Limit** | Same tool called >20 times in 1 min | Rollback + rate limit |

**Implementation:** Deferred to Phase 2

---

## 9. Implementation Plan

**See tasks/workstream-12-multi-agent-workflow.md for detailed task breakdown with milestones.**

---

## 10. Answers to Your Questions

#### Q1: Schema and function params - did you review code?
**Answer:** ✅ YES - Reviewed all code:
- **Existing context manager:** `_request_context` in both agents (`security_integration.py:26`)
- **Function signature:** `set_request_context(request_id, session_id, user_input, context)` - already accepts arbitrary dict
- **Updated LLD:** Extended existing context instead of creating new one

#### Q2: Rollback scenario for failed agent?
**Answer:** ✅ YES - Section 5:
- **Rollback Coordinator** queries conversation logs, reverses WRITE actions (LIFO)
- **Supports both:** Self-hosted (ECS) and Bedrock agents via HTTP API
- **Compensating transactions:** `process_refund` → `reverse_refund`

#### Q3: How do we validate allowed agents?
**Answer:** ✅ ALREADY IMPLEMENTED + ENHANCED:
- **Current:** `policy_engine.py:174` validates `allowed_agents` for `invoke_agent` tool
- **New:** Added `allowed_callers` in target agent policy (inverse relationship)
- **Example policy:**
  ```yaml
  # payment-agent policy
  allowed_callers:
    - customer-query-agent  # Only CQA can call Payment Agent
  ```

#### Q4: Will audit logs show all tool calls distinctly?
**Answer:** ✅ YES - Section 6:
- **Enhanced audit log** includes `multi_agent_context` with `parent_request_id`, `conversation_id`
- **Timeline API** builds hierarchical tree showing all tool calls and agent invocations
- **Example:** Can trace Customer Query → Payment Agent chain

#### Q5: Did you review agent/tool code?
**Answer:** ✅ YES:
- **Reviewed:** `call_payment_agent.py` (already passes `parent_request_id`)
- **Reviewed:** `security_integration.py` (already has context manager)
- **Reviewed:** `routes.py` (both agents) - already set context
- **Updated LLD:** Based on actual implementation

#### Q6: Why new Context Manager? Can't extend existing?
**Answer:** ✅ CORRECT - No new manager needed:
- **Existing:** `_request_context: ContextVar[Optional[Dict]]` at line 26
- **Solution:** Add helper `set_multi_agent_context()` to populate dict
- **No duplication:** Reuse existing ContextVar

#### Q7: Do we need to create `/v1/logs/conversation` API?
**Answer:** ✅ YES - Confirmed:
- **Current:** Only `GET /v1/logs` (filters by session/agent, not conversation)
- **New:** `GET /v1/logs/conversation/{id}` returns hierarchical timeline
- **Implementation:** Section 7 - ConversationService + CloudWatch Logs Insights query

---

**End of Updated LLD**
