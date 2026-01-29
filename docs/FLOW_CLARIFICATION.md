# Flow Clarification - Dashboard to Agents

**Date**: November 30, 2025
**Context**: Your question about "Dashboard calls /v1/execute then agent?"

---

## The Confusion (My Fault!)

I explained it incorrectly. Let me clarify with the ACTUAL design from LLD 09.

---

## Key Concept: There are TWO different deployment scenarios

### Scenario 1: Self-Hosted Agents (Sentra ECS)
- Customer Query Agent (ECS task)
- Payment Agent (ECS task)
- **Agent owns validation** - Agent calls Security Controller internally

### Scenario 2: External Agents (AWS Bedrock, Vertex AI, etc.)
- AWS Bedrock Agents
- Azure OpenAI Agents
- **External validation hook** - Bedrock Guardrail calls Security Controller

---

## ACTUAL FLOWS (Corrected)

### Flow 1: Dashboard → Self-Hosted Agent (query endpoint)

```
┌─────────────────────────────────────────────────────────────────┐
│ User types: "Show customers from CA"                           │
└─────────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────────┐
│ Dashboard                                                       │
│   • User sends message via Streamlit UI                        │
└─────────────────────────────────────────────────────────────────┘
                        ↓
                        │
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│ ONE CALL: Dashboard → Agent                                     │
│   POST http://customer-query-agent:8080/v1/agents/customer-query/query
│   {                                                             │
│     "message": "Show customers from CA"                         │
│   }                                                             │
└─────────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────────┐
│ Customer Query Agent Service (ECS)                             │
│                                                                 │
│ 1. Receives request at /v1/agents/customer-query/query         │
│ 2. Calls Claude (Bedrock) for tool selection                   │
│ 3. Claude decides: "Use query_customers tool"                  │
│ 4. Agent calls Security Controller /validate                   │
│    ├─ If DENY → return error to Dashboard                      │
│    └─ If ALLOW → continue                                      │
│ 5. Agent executes query_customers(state="CA")                  │
│ 6. Agent gets DDB results                                      │
│ 7. Agent calls Claude to format response                       │
│ 8. Agent returns NLP response                                  │
└─────────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────────┐
│ Dashboard                                                       │
│   • Displays NLP response to user                              │
└─────────────────────────────────────────────────────────────────┘
```

**Key Points**:
- ✅ Dashboard makes ONE call to agent
- ✅ Agent handles everything (validation, execution, formatting)
- ✅ This is the EXISTING flow (from Workstream 7)

---

### Flow 2: Dashboard → Self-Hosted Agent (execute endpoint - NEW)

**Design Intent from LLD 09**:
The `/v1/execute` endpoint is for when validation has ALREADY happened.

**BUT** - I now realize there are TWO interpretations:

#### Interpretation A: Dashboard validates first (what I explained)

```
User → Dashboard
         ↓
     Dashboard parses intent:
       tool = "query_customers"
       params = {"state": "CA"}
         ↓
     CALL 1: Dashboard → Security Controller /validate
         ↓
     If ALLOW:
         ↓
     CALL 2: Dashboard → Agent /v1/execute
         ↓
     Agent executes + formats
         ↓
     Dashboard displays result
```

**Total calls**: 2 (Dashboard → Security, Dashboard → Agent)

#### Interpretation B: Agent still validates (simpler - RECOMMENDED)

```
User → Dashboard
         ↓
     Dashboard knows what to do:
       tool = "query_customers"
       params = {"state": "CA"}
         ↓
     ONE CALL: Dashboard → Agent /v1/execute
         ↓
     Agent:
       1. Validates with Security Controller (like /query does)
       2. If ALLOW: executes tool
       3. Formats with LLM
       4. Returns result
         ↓
     Dashboard displays result
```

**Total calls**: 1 (Dashboard → Agent)

---

## Which Interpretation is Correct?

Looking at LLD 09 Section 6.2 (Dashboard Integration):

```python
# From LLD 09 - Pseudocode
if decision == 'ALLOW':
    # Execute agent action
    execution_result = execute_agent_action(
        agent_id=session['agent_id'],
        tool_name=tool_name,
        tool_params=tool_params,
        user_query=user_message
    )
```

This suggests **Interpretation A**: Dashboard validates FIRST, then calls `/execute`.

---

## Revised Understanding: The Difference

### `/v1/agents/customer-query/query` (Existing)

**Who decides tool**: Claude
**Who validates**: Agent → Security Controller
**Dashboard work**: Just send user message
**Agent work**: Everything (tool selection, validation, execution, formatting)

```
Dashboard → Agent /query
              ↓
            Agent does EVERYTHING:
              - Claude decides tools
              - Validate with Security Controller
              - Execute tools
              - Format response
              ↓
            Dashboard ← Response
```

**Use case**: Complex queries where Claude should decide

---

### `/v1/execute` (NEW)

**Who decides tool**: Dashboard (or external system)
**Who validates**: Dashboard → Security Controller (BEFORE calling agent)
**Dashboard work**: Parse intent, validate, then call agent
**Agent work**: Just execute and format (validation already done)

```
Dashboard → Security Controller /validate
              ↓
            If ALLOW:
              ↓
            Dashboard → Agent /execute
              ↓
            Agent:
              - Execute tool (NO validation needed - already done)
              - Format response
              ↓
            Dashboard ← Response
```

**Use case**: Dashboard-driven workflows where tool is known

---

## So to Answer Your Questions:

### Q: "Dashboard will call /v1/execute first and then will call agent?"

**A**: NO! Let me correct this:

1. Dashboard calls **Security Controller** `/validate` FIRST
2. If ALLOW, Dashboard calls **Agent** `/v1/execute`

The `/v1/execute` endpoint IS ON THE AGENT.

There are only 2 services in the call:
- Dashboard
- Agent (which has the `/v1/execute` endpoint)

(Security Controller is called by Dashboard before step 2)

---

### Q: "What API will it call for agent?"

**A**:
```
POST http://customer-query-agent:8080/v1/execute
{
  "tool_name": "query_customers",
  "tool_params": {"filters": {"state": "CA"}},
  "user_query": "Show customers from CA"
}
```

This endpoint is ON the agent service itself.

---

### Q: "Did we create to have difference between dashboard calls and external agents calls on AWS?"

**A**: YES! That's EXACTLY the design:

**Self-Hosted Agents** (Customer Query, Payment):
- Use `/v1/agents/{agent}/query` for Claude-based workflows
- Use `/v1/execute` for Dashboard-driven workflows (Dashboard validates first)

**External Agents** (Bedrock Agents, Vertex AI):
- Bedrock Guardrail calls Security Controller `/validate`
- Bedrock Agent executes if ALLOW
- Sentra Dashboard can monitor via audit logs

---

## Visual: The Two Scenarios

### Scenario 1: Self-Hosted Agents

```
Sentra Dashboard
       ↓
  ┌────────┬──────────┐
  │        │          │
  ▼        ▼          ▼
Query   Execute   Security
           ↓      Controller
           ↓          ↑
           └──────────┘
                ↓
        Customer Query Agent (ECS)
        ├── /v1/agents/customer-query/query   ← Claude decides
        └── /v1/execute                        ← Dashboard decides
```

### Scenario 2: External Agents

```
Sentra Dashboard               Bedrock Console
       │                              │
       └──────────┬───────────────────┘
                  ▼
          AWS Bedrock Agent
                  │
                  ├── Guardrail Hook
                  │   ↓
                  │   Sentra Security Controller /validate
                  │   ↓
                  │   ALLOW/DENY
                  ↓
          Execute if ALLOW
```

---

## Summary

**For Self-Hosted Agents** (Customer Query, Payment):

| Endpoint | Who decides tool | Who validates | Dashboard calls |
|----------|-----------------|---------------|-----------------|
| `/v1/agents/{agent}/query` | Claude | Agent → Security | 1 (Dashboard → Agent) |
| `/v1/execute` | Dashboard | Dashboard → Security | 2 (Dashboard → Security, Dashboard → Agent) |

**For External Agents** (Bedrock, Vertex):
- Guardrail/Extension calls Security Controller
- Sentra Dashboard monitors via audit logs
- Can also trigger via Dashboard (Flow A in LLD 09)

---

## Implementation Needed (Milestone 2)

For `/v1/execute` to work as designed:

1. **Dashboard** needs:
   - Parse user intent (determine tool + params)
   - Call Security Controller `/validate` FIRST
   - If ALLOW: Call Agent `/v1/execute`

2. **Agent `/v1/execute`** (already implemented):
   - Receives tool_name + params
   - Executes tool (NO validation - already done)
   - Formats response with LLM
   - Returns to Dashboard

The agent endpoint is ready. Dashboard integration is Milestone 2.

---

## My Mistake in Explanation

I kept saying "Agent validates" for `/v1/execute`, but the DESIGN INTENT is:
- Dashboard validates FIRST
- Agent just executes (validation already done)

This makes sense because:
- Cleaner audit trail (validation logged separately)
- Dashboard has more control
- Agent is simpler (just execute + format)

Sorry for the confusion! The LLD 09 design is clear - I just explained it wrong.
