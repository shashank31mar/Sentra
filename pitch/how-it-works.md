# AegionAI — How It Works (Architecture Brief)

*Companion to the one-pager. For technical and security reviewers. Answers the four questions everyone asks: where do you sit, how fast, what happens if you're down, and what do you see.*

---

## The one-line answer

**We sit at the point where an AI agent's decision becomes a real action** — between the agent and the tool/API/database it's about to call. Every action is checked *before* it runs. Allowed → it proceeds. Not allowed → it's blocked, and we can undo it or pause the agent.

```
  AI agent decides: "call transfer_funds(acct=X, amount=Y)"
                    │
                    ▼
        ┌───────────────────────────┐
        │  AegionAI checkpoint       │   ◄── runs INSIDE the customer's
        │  is this action allowed?   │       environment (decorator/sidecar)
        └───────────┬───────────────┘
            allow ──┘   └── deny → blocked + logged (+ rollback / pause)
              ▼
        action actually executes
```

## How we intercept (two modes)

| Mode | What it is | Code change | Best for |
|---|---|---|---|
| **SDK (today)** | One wrapper per tool; calls our check before the tool body runs | One line per tool | Python agents, fast pilots, Bedrock/Azure/LangChain/MCP |
| **Sidecar (roadmap)** | Runs beside the agent, intercepts tool calls at the network level | None | Framework-agnostic, fleet-wide, non-cooperative enforcement |

Both make the **same decision**; the sidecar just removes the integration step. The decision logic, policies, and trust state are shared.

## The decision (what actually happens on each action)

1. The checkpoint sends the action — *agent, tool, parameters, the user's request, session id* — to the **policy engine**.
2. The engine evaluates, in order: **is this agent allowed this tool? are the parameters within policy? did the required prior steps happen (sequence)? does the user's request show injection/jailbreak? is the agent's trust still good?**
3. Returns **allow / deny** with a reason. Deny can also trigger **rollback** (undo a write) or **quarantine** (pause the agent so later actions auto-deny).
4. Everything is logged to an **audit trail**.

Detection (prompt-injection, PII) uses a fine-tuned classifier; sequence rules are authored as policy and evaluated against a per-session store; behavioural anomaly detection runs on action *metadata* only.

## Speed (target: sub-500ms)

- **Fast path for clean traffic:** policy is evaluated against a **locally cached copy** (no network round-trip), and the deterministic checks (tool + parameter rules, sequence) run in-process.
- **The ML model runs only on borderline cases** — clean requests never pay the model cost.
- **Telemetry and audit are written asynchronously**, off the response path — the decision returns the moment it's made, not after the logs are flushed.
- **Two modes:** synchronous (block before execute — default for money-moving actions) or shadow/observe (zero added latency) for low-risk tools or initial rollout.

*Hot-path optimization is in active progress to hold this budget under load.*

## What happens if we're unreachable (graceful degradation)

**Your agents never stop, and they're never left unguarded.**

- **Normal:** the full pipeline runs — policy + parameters + sequence + ML threat detection + cross-agent trust.
- **If our platform is unreachable:** the SDK falls back to the **locally cached policy** and keeps enforcing the hard rules — tool and parameter allow/deny — **in-process.** Agents keep running; the floor still holds. Only the advanced detection (ML threat, cross-agent trust) pauses until reconnect.
- **Configurable per agent:** money-movement agents can be set to **fail-closed** (block) instead of degrade, if the customer prefers.
- **The control plane is not in the critical path** — enforcement lives locally, so an outage degrades the *depth* of checks; it doesn't halt your agents or open the gate.

## Security Boundary & Trust Model  *(the CISO section)*

**The enforcement runs inside your boundary; we are the decision authority — not a place your data lives.**

- **Where each piece runs:** the *checkpoint* (the thing that blocks/allows) runs **inside the customer's environment**, next to the agent. AegionAI is the *policy decision point* it consults.
- **What we need vs. what we don't:** detection needs the **prompt and its context** (that's what catches manipulation) — *not* your sensitive values. The SDK **redacts account numbers, balances, and PII before anything leaves your environment** (use our redactor, or plug in your own DLP), so the engine sees the *shape* of the request, not the secrets. For the strictest environments, **on-prem means nothing leaves at all.**
- **Storage:** action **content is not persisted** by default — checks are ephemeral; only metadata needed for the audit trail is retained, encrypted in transit and at rest, with configurable retention.
- **Deployment models (CISO's choice):**
  1. **SaaS** (multi-tenant) — fastest to start.
  2. **Single-tenant in your VPC** — data stays in your cloud account.
  3. **On-prem / air-gapped** — for regulated workloads; **nothing leaves your boundary.**
- **We are a high-value target, and we treat it that way:** strict tenant isolation, least-privilege access, signed/versioned policies, and a tamper-evident audit log. Because the enforcement point is local and fail-secure, compromising the control plane cannot silently *permit* a malicious action.
- **Fits your stack, doesn't replace it:** complements identity (who the agent is) and SIEM/observability (alerts flow out); we add the missing layer — *what the action is allowed to do, enforced in real time.*

## Coverage today vs. roadmap (honest)

| | Status |
|---|---|
| SDK checkpoint, fail-secure, audit trail | **Built** |
| Prompt-injection / jailbreak + PII detection (ML) | **Built** |
| Tool + parameter policy, sequence enforcement, trust/quarantine | **Built (single-cloud)** |
| Behavioural anomaly (metadata-only) | **Built** |
| AWS Bedrock + Azure connectors; live cross-cloud demo | **Built** |
| GCP connector; multi-cloud blast-radius containment | **Roadmap** |
| Network sidecar (zero-code, framework-agnostic) | **Roadmap** |
| SOC2 Type II | **In progress** |

---
*Plain-English version of the product for the one-pager. This brief is the "how"; pair it with the one-pager's "why."*
