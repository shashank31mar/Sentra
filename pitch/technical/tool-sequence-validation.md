# Tool Call Sequence Validation: Technical Architecture
*For CTO / VP Engineering / Platform Engineering audiences*
*Research date: March 2026*

---

## The Problem in One Sentence

Every agent security vendor validates *individual* tool calls. Nobody validates *sequences* — whether the right tools were called in the right order before a sensitive action executed.

---

## Why Sequences Matter: The Swiggy Case

In November 2024, a customer used an AI-generated photo of "cracked eggs" to trigger Swiggy's automated refund agent. The agent approved the refund instantly. The technique went viral — now used at scale.

The prompt injection was the attack vector. But the *sequence violation* was what made it succeed: the agent called `approve_refund` without a preceding `verify_image: completed` check.

**With AgentPolicy:**
```yaml
rules:
  - tool: approve_refund
    requires:
      - verify_image: completed
        within: 300s
```
The sequence `approve_refund` without a fresh `verify_image` call is **blocked at the proxy level** — regardless of what any prompt injection instructed. The attack fails even if injection detection misses it.

This is why sequence validation is a *defense-in-depth* control, not a replacement for injection blocking.

---

## Why No Vendor Has Built This

Three structural barriers — confirmed by research across every major vendor (March 2026):

### 1. The Policy Engine Problem (the Cedar issue)

AWS AgentCore uses Cedar for policy evaluation. Cedar is **stateless by intentional design**. Each authorization decision is evaluated independently with no memory of prior actions. This tradeoff enables:
- Parallel policy evaluation (performance)
- Formal verification (provable correctness)
- Deterministic, predictable results

But it also means: **Cedar cannot express "action B is only allowed if action A completed in this session."**

AWS AgentCore has Cedar + formal verification + 99% accuracy. It has **no sequence validation** and cannot add it without architectural changes. This is confirmed in [AWS AgentCore policy documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html).

OPA (Open Policy Agent) is also stateless, but unlike Cedar, OPA can be fed session state as input. This is the right choice for sequences.

### 2. The Interception Problem (framework fragmentation)

Every agent framework has different tool call mechanisms:

| Framework | Tool call pattern | Has before/after hooks? | Session state? |
|---|---|---|---|
| LangChain | `wrap_tool_call` middleware | wrap only (no before/after) | ❌ |
| CrewAI | `@before_tool_call` / `@after_tool_call` | ✅ | ✅ via crew context |
| Anthropic MCP | JSON-RPC `tools/call` | ❌ | ❌ (multiple CVEs) |
| Google A2A | AgentCard + task request | ❌ | ❌ |
| Microsoft Agent Framework | Middleware chain | ✅ | ✅ session events |
| AWS Bedrock AgentCore | Cedar gateway | ✅ (policy-level) | ❌ (Cedar stateless) |

Building sequence validation as an SDK integration requires separate work for each framework. Nobody has done this.

**The unlock: sidecar proxy.** Instead of integrating with each framework's SDK, intercept ALL tool calls at the network level via a Kubernetes sidecar container — framework-agnostic. Same pattern as Istio service mesh for microservices.

### 3. The UX Problem

Even if the enforcement engine existed, clients need a way to define sequences without writing Rego policies or state machine specs. Nobody has designed this UX.

YAML prerequisites (proposed below) is the simplest viable solution.

---

## Architecture

### Core Pattern: Event-Sourced Session History + Policy Evaluation

```
┌─────────────────────────────────────────────────────────┐
│  Agent (LangChain / CrewAI / MCP / any framework)        │
└──────────────────┬──────────────────────────────────────┘
                   │  all outbound tool calls
                   ▼
┌─────────────────────────────────────────────────────────┐
│  SIDECAR PROXY  (Kubernetes mutating admission webhook)  │
│                                                          │
│  1. Intercept: tool_name, session_id, args               │
│  2. Load session history from Redis (<5ms)               │
│  3. OPA evaluate: prerequisites met?                     │
│  4a. Allowed → record to event log → forward call        │
│  4b. Denied → block → log violation → optional HitL      │
└──────────────────┬──────────────────────────────────────┘
                   │
         ┌─────────┴──────────┐
         ▼                    ▼
  Redis (session cache)  Postgres (audit log)
  Per session_id:        Append-only, immutable
  recent tool calls      EU AI Act compliance
  <5ms lookup            SHA-256 tamper evidence
```

### Components

**Sidecar Proxy**
- Deployed as Kubernetes sidecar via mutating admission webhook
- Intercepts MCP JSON-RPC `tools/call`, REST tool endpoints, SDK function calls
- Adds <5ms latency for session lookup + policy evaluation
- No changes to agent code required

**Session Event Store**
```sql
-- Schema: append-only, never update/delete
CREATE TABLE tool_call_events (
  id            UUID PRIMARY KEY,
  session_id    TEXT NOT NULL,
  timestamp     TIMESTAMPTZ NOT NULL,
  agent_id      TEXT NOT NULL,
  tool_name     TEXT NOT NULL,
  input_hash    TEXT,           -- SHA-256 of args (not raw args, for PII safety)
  result_status TEXT,           -- 'completed' | 'failed' | 'blocked'
  blocked       BOOLEAN DEFAULT FALSE
);

CREATE INDEX ON tool_call_events (session_id, timestamp);
```

Redis stores the hot path (last N calls per session_id, TTL = session duration).
Postgres stores the full immutable audit log.

**Policy Engine (OPA + OPAL)**
OPA evaluates sequence policies with session state injected as context:
```rego
# Compiled from YAML by Sentra policy compiler
allow_tool_call {
    input.tool_name == "approve_refund"
    session := data.sessions[input.session_id]
    verify_image_call := [c | c := session.calls[_]; c.tool == "verify_image"; c.status == "completed"]
    count(verify_image_call) > 0
    # freshness check: most recent verify_image was within 300s
    latest := max([c.timestamp | c := verify_image_call[_]])
    input.timestamp - latest < 300
}
```

OPAL syncs session state from Postgres into OPA's data store in real-time.

**AgentPolicy CRD (Kubernetes)**
```yaml
apiVersion: agent.sentra.io/v1
kind: AgentPolicy
metadata:
  name: refund-policy
  namespace: agents
spec:
  # Which agents this policy applies to (label selector)
  agentSelector:
    matchLabels:
      app: refund-agent

  rules:
    # approve_refund requires fresh verify_image + verify_order
    - tool: approve_refund
      requires:
        - verify_image: completed
          within: 300s        # check expires after 5 minutes
        - verify_order: completed

    # transfer_funds requires fresh balance check
    - tool: transfer_funds
      requires:
        - check_balance: completed
          within: 60s

  # Deployment mode: warn (log only) or enforce (block)
  mode: warn   # start here; switch to enforce after 30 days

  # What to do if session state is unavailable (Redis down)
  stateLossFallback: human-approval   # or: fail-open | fail-closed
```

The Kubernetes controller watches for AgentPolicy CRD changes and updates OPA bundle automatically. GitOps-friendly — policies committed to git, applied via kubectl.

---

## Handling Edge Cases

### Parallel Tool Calls
Modern agents (Claude, GPT-4) call tools in parallel. Example:
```
Agent calls simultaneously: get_account_info, get_user_risk_score
Then calls: approve_transfer
```

**Solution**: Parallel calls within one invocation step are grouped as a single "step". Prerequisites must come from a *previous* step. Step boundary = LLM inference boundary.

### Non-Deterministic Workflows
Agents don't always take the same path. A legitimate agent might skip `check_balance` if the caller passed the balance in context.

**Solution**: Default to **warn mode** for 30 days before enabling enforcement. Operators see real traffic patterns and tune policies to match actual workflows. This eliminates false positives before enforcement begins.

### Session Boundaries
"What is a session?" is genuinely ambiguous.

**Default**: Per `session_id` header propagated by the caller. If no `session_id` provided, fall back to per-conversation-turn.

**Override**: Client passes custom `session_id` (e.g., transaction ID) and Sentra tracks state within that scope.

### State Loss Tolerance
If Redis is unavailable and session history can't be loaded:

| Fallback | Behavior | Use case |
|---|---|---|
| `fail-open` | Allow the call, log warning | Non-critical workflows |
| `fail-closed` | Block the call, return error | High-security (banking, medical) |
| `human-approval` | Queue for human review (default) | Balanced approach |

---

## Deployment Lifecycle

### Phase 1: Warn Mode (Days 1-30)
- Deploy sidecar proxy in passive mode
- All tool calls are logged, no blocking
- Violations are surfaced in dashboard: "would have blocked X calls this week"
- Operators observe real traffic and tune YAML policies

### Phase 2: Tune Mode (Days 31-60)
- Work with design partners to refine policies
- Identify false positives before enabling enforcement
- Monthly check: "Does this policy generalize to 10 similar companies?"

### Phase 3: Enforce Mode (Day 61+)
- Switch `mode: enforce` in AgentPolicy CRD
- Real-time blocking with audit log
- Human-approval queue for edge cases
- Weekly violation report for compliance teams

---

## What This Defends Against

### 1. AI-Generated Fraud (Swiggy/DoorDash pattern)
Agent receives a prompt injection or manipulated image → tries to call `approve_refund` directly → **blocked: sequence violation, verify_image not completed**.

### 2. Privilege Escalation Sequences (GTG-1002 pattern)
Anthropic Threat Report (Sept 2025): Chinese state-sponsored actors used autonomous agents to chain `reconnaissance → vulnerability_discovery → exploitation → privilege_escalation → data_exfiltration`. Each step required the prior step's output. Tool sequence validation would have required explicit authorization at each escalation gate.

### 3. Agent Session Smuggling (Palo Alto Unit42, Sept 2025)
A malicious A2A agent injects hidden instructions into a trusted session, causing a victim agent to call sensitive tools out of sequence. Sequence validation detects and blocks the anomalous sequence even if the injection itself is not caught.

### 4. Confused Deputy / Cross-Agent Blast Radius
Agent A is compromised and tries to trigger Agent B to call `transfer_funds` without Agent B having completed `check_balance` in its own session. Cross-agent session tracking (shared `session_id` propagation) catches this.

---

## Competitive Position

| Capability | AWS AgentCore | Portkey | Lakera | **Sentra** |
|---|---|---|---|---|
| Per-call authorization | ✅ Cedar | ✅ Guardrails | ✅ Pattern match | ✅ Cedar |
| Tool sequence validation | ❌ (Cedar stateless) | ❌ | ❌ | **✅** |
| Framework-agnostic interception | ❌ AWS only | ⚠️ SDK | ⚠️ SDK | **✅ Sidecar** |
| Cross-cloud session tracking | ❌ | ❌ | ❌ | **✅** |
| Client YAML policy UX | ❌ | ❌ | ❌ | **✅** |
| Kubernetes-native CRD | ❌ | ❌ | ❌ | **✅** |
| EU AI Act audit log | ❌ | Partial | ❌ | **✅** |

---

## Build Estimates

| Component | Effort | Notes |
|---|---|---|
| Sidecar proxy (MCP + REST interception) | 3-4 weeks | Go/Rust for performance |
| Redis session store + Postgres audit log | 1-2 weeks | Standard infra |
| OPA policy compiler (YAML → Rego) | 2-3 weeks | Handles prerequisites + freshness |
| AgentPolicy CRD + controller | 1-2 weeks | Standard K8s operator pattern |
| Violation dashboard | 2-3 weeks | React + real-time events |
| Design partner validation + tuning | 4-8 weeks | Parallel with engineering |

**Total MVP: 8-12 weeks, 2 engineers.**

---

## Sources

- [AWS AgentCore Policy Documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html)
- [Cedar Policy Language — Stateless Design](https://aws.amazon.com/blogs/security/how-we-designed-cedar-to-be-intuitive-to-use-fast-and-safe/)
- [CrewAI Tool Hooks](https://docs.crewai.com/en/learn/tool-hooks)
- [MCP Specification](https://modelcontextprotocol.io/specification/2025-11-25)
- [MCP Security Vulnerabilities 2025-2026](https://www.practical-devsecops.com/mcp-security-vulnerabilities/)
- [Agent Session Smuggling — Palo Alto Unit42](https://unit42.paloaltonetworks.com/agent-session-smuggling-in-agent2agent-systems/)
- [Anthropic AI-Orchestrated Cyber Espionage (GTG-1002)](https://assets.anthropic.com/m/ec212e6566a0d47/original/Disrupting-the-first-reported-AI-orchestrated-cyber-espionage-campaign.pdf)
- [OPAL: Real-time OPA state synchronization](https://docs.opal.ac/)
- [Temporal.io for agentic workflows](https://intuitionlabs.ai/articles/agentic-ai-temporal-orchestration)
- [EU AI Act August 2026 Requirements](https://www.legalnodes.com/article/eu-ai-act-2026-updates-compliance-requirements-and-business-risks)
