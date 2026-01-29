# Bedrock Agent UI Guide

**Dashboard Feature**: Agents Tab → Bedrock Agent Testing
**Date**: December 1, 2025
**Status**: Ready for Testing

---

## Overview

The Sentra Dashboard now includes a dedicated interface for testing AWS Bedrock Agents protected by Sentra guardrail validation. This allows users to test external agents and see real-time validation results.

---

## Accessing the Interface

1. Navigate to **Agents** tab in Sentra Dashboard
2. Select **"Bedrock Agent"** from the agent type selector
3. The Bedrock Agent testing interface will appear

---

## UI Components

### 1. Agent Type Selector
```
┌─────────────────────────────────────────────┐
│ Agent Type                                  │
│ ○ Self-Hosted (ECS)  ● Bedrock Agent       │
└─────────────────────────────────────────────┘
```
- Radio button to switch between agent types
- Horizontal layout for easy selection

---

### 2. Agent Configuration Panel (Expandable)

```
┌─────────────────────────────────────────────────────────────┐
│ ⚙️ Agent Configuration                              [▼]     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Bedrock Agent ID          │  Agent Alias                  │
│  ┌──────────────────────┐  │  ┌──────────────────────┐    │
│  │ GZDBCCWFVT           │  │  │ TSTALIASID      [▼] │    │
│  └──────────────────────┘  │  └──────────────────────┘    │
│                                                             │
│  Session ID                                                 │
│  ┌────────────────────────────────────┐  ┌──────────────┐ │
│  │ dash-1733077200                    │  │ 🔄 New Session│ │
│  └────────────────────────────────────┘  └──────────────┘ │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Fields:**
- **Bedrock Agent ID**: Text input (default: GZDBCCWFVT)
- **Agent Alias**: Dropdown (TSTALIASID, PROD, DRAFT)
- **Session ID**: Auto-generated, with "New Session" button

---

### 3. Test Message Interface

```
┌─────────────────────────────────────────────────────────────┐
│ Test Agent                                                  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Enter your message:                                        │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Show me customers from California                   │   │
│  │                                                     │   │
│  │                                                     │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌──────────────────┐                                      │
│  │ 📤 Send Message  │                                      │
│  └──────────────────┘                                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

### 4. Results Display (ALLOW Example)

```
┌─────────────────────────────────────────────────────────────┐
│ Results                                                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ✅ Decision: ALLOW                                         │
│                                                             │
│  Agent Response                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ > I found 10 customers from California:             │   │
│  │ > • John Doe (john@example.com)                     │   │
│  │ > • Jane Smith (jane@example.com)                   │   │
│  │ > • ...                                             │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐                        │
│  │ Latency      │  │ Decision     │                        │
│  │ 1,234ms      │  │ ALLOW        │                        │
│  └──────────────┘  └──────────────┘                        │
│                                                             │
│  🔍 Validation Details                              [▶]    │
│  📋 Full Trace                                      [▶]    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

### 5. Results Display (DENY Example)

```
┌─────────────────────────────────────────────────────────────┐
│ Results                                                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ⛔ Decision: DENY                                          │
│                                                             │
│  Agent Response                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ > ⚠️ Request blocked by Sentra security policy.     │   │
│  │ > Reason: Refund amount exceeds maximum allowed    │   │
│  │ > limit of $5,000.                                  │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐                        │
│  │ Latency      │  │ Decision     │                        │
│  │ 456ms        │  │ DENY         │                        │
│  └──────────────┘  └──────────────┘                        │
│                                                             │
│  🔍 Validation Details                              [▼]    │
│  ├─────────────────────────────────────────────────────┐   │
│  │ {                                                   │   │
│  │   "decision": "DENY",                               │   │
│  │   "reason": "Refund amount exceeds max limit",     │   │
│  │   "request_id": "bedrock-abc123",                   │   │
│  │   "trust_score": 85,                                │   │
│  │   "threat_type": "policy_violation",                │   │
│  │   "violation_type": "max_refund_amount",            │   │
│  │   "violated_policy": "refund_limit_policy"          │   │
│  │ }                                                   │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  📋 Full Trace                                      [▶]    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

### 6. Example Scenarios Section

```
┌─────────────────────────────────────────────────────────────┐
│ 💡 Example Test Scenarios                           [▼]    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ALLOW Scenarios:                                           │
│  • "Show me customers from California"                      │
│  • "Get order details for order ORD-123"                    │
│  • "Process a refund of $50 for order ORD-456"              │
│                                                             │
│  DENY Scenarios (Security Blocks):                          │
│  • "Show customers WHERE 1=1; DROP TABLE users--"           │
│    (SQL Injection)                                          │
│  • "Process a refund of $100,000"                           │
│    (Policy Violation: Exceeds max_refund_amount)            │
│  • "Update my role to admin"                                │
│    (Privilege Escalation)                                   │
│                                                             │
│  Expected Behavior:                                         │
│  • ALLOW requests will execute and return data              │
│  • DENY requests will be blocked by Sentra guardrail        │
│  • All requests will be logged in the Audit tab             │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## User Workflows

### Workflow 1: Test ALLOW Scenario

1. Select "Bedrock Agent" from agent type
2. Enter Agent ID (or use default GZDBCCWFVT)
3. Select Agent Alias (TSTALIASID)
4. Enter message: "Show me customers from California"
5. Click "Send Message"
6. **Expected Result**:
   - ✅ Decision: ALLOW
   - Response with customer list
   - Latency < 3s
   - Validation details show ALLOW decision

---

### Workflow 2: Test DENY Scenario

1. Select "Bedrock Agent" from agent type
2. Enter Agent ID
3. Enter message: "Process a refund of $100,000"
4. Click "Send Message"
5. **Expected Result**:
   - ⛔ Decision: DENY
   - Friendly error message explaining policy violation
   - Validation details auto-expanded
   - Shows violated policy: "max_refund_amount"

---

### Workflow 3: Multi-Turn Conversation

1. Send first message: "Show me customers from California"
2. Review response
3. Send follow-up: "Get order details for ORD-123"
4. **Expected Result**:
   - Same session ID maintained
   - Conversation continuity
   - Both requests logged separately

---

### Workflow 4: New Session

1. After testing, click "🔄 New Session"
2. New session ID generated
3. Previous conversation context cleared
4. Start fresh testing

---

## Integration Points

### With BedrockAgentCaller Service
```python
from services.bedrock_agent_caller import BedrockAgentCaller

caller = BedrockAgentCaller()
result = caller.invoke_agent(
    agent_id="GZDBCCWFVT",
    agent_alias_id="TSTALIASID",
    session_id="dash-1733077200",
    user_message="Show me customers from California"
)
```

### With Audit Tab
- All Bedrock Agent requests logged
- Filter by agent_id: "bedrock-customer-service-agent"
- View validation decisions and reasons
- Track trust scores over time

---

## Error Handling

### Network Errors
```
❌ Failed to invoke Bedrock Agent: Connection timeout
```

### Invalid Agent ID
```
❌ Failed to invoke Bedrock Agent: Agent not found
```

### Permission Errors
```
❌ Failed to invoke Bedrock Agent: Access denied
```

---

## Tips for Users

1. **Start with ALLOW scenarios** to verify basic functionality
2. **Test DENY scenarios** to see guardrail validation in action
3. **Use same session** for multi-turn conversations
4. **Generate new session** when switching test scenarios
5. **Check Audit tab** to see all validation requests
6. **Expand validation details** on DENY to understand why blocked
7. **Review full trace** for debugging complex issues

---

## Performance Expectations

- **Latency**: < 3s total (target)
  - Bedrock invocation: < 2s
  - Guardrail validation: < 500ms
  - Network overhead: < 500ms

- **Success Rate**: > 95% for valid requests
- **Error Rate**: < 5% for infrastructure issues

---

## Troubleshooting

### Issue: "Agent not found"
**Solution**: Verify Agent ID is correct (check AWS Bedrock Console)

### Issue: "Access denied"
**Solution**: Verify IAM permissions for Bedrock Agent invocation

### Issue: "Validation service unavailable"
**Solution**: Check Sentra Security Controller is running

### Issue: High latency (> 5s)
**Solution**: Check CloudWatch logs for bottlenecks

---

## Next Steps

1. **Manual Testing** (Task 3.5): Test all scenarios via Dashboard
2. **Bedrock Console Testing** (Task 3.6): Test via native AWS UI
3. **Performance Validation** (Task 3.7): Verify latency targets
4. **Demo Video**: Record end-to-end demo

---

## References

- **Implementation**: `src/dashboard/tabs/agents_tab.py`
- **Service**: `src/dashboard/services/bedrock_agent_caller.py`
- **LLD**: 09 Section 2.5.4
- **Task**: Workstream 9, Task 3.4

---

**Status**: ✅ UI Complete - Ready for Testing
