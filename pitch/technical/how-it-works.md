# AegionAI — How It Works (Architecture Brief)

*Companion to the one-pager. For technical and security reviewers. Answers the questions everyone asks: where does the decision happen, how fast, what happens if you're down, what do you see, and what's actually built today.*

---

## The one-line answer

**We sit at the point where an AI agent's decision becomes a real action** — between the agent and the tool/API/database it's about to call. The action is checked *before* it runs. Allowed → it proceeds. Not allowed → it's blocked and logged; for already-committed multi-step writes we can also compensate (rollback), and we can pause the agent.

```
  AI agent decides: "call transfer_funds(acct=X, amount=Y)"
                    │
                    ▼
        ┌───────────────────────────┐
        │  CHECKPOINT (PEP)          │   ◄── SDK decorator, runs INSIDE the
        │  intercepts the action     │       customer's environment
        └───────────┬───────────────┘
                    │  POST /v1/validate  ── one network round-trip (today)
                    ▼
        ┌───────────────────────────┐
        │  POLICY ENGINE (PDP)       │   ◄── TODAY: server-side in the controller
        │  Cedar policy → Sigma      │       (AegionAI cloud for Serverless;
        │  detection (live) → ML     │        in-VPC for Dedicated/Self-Managed)
        │  (shadow) + trust + abuse  │
        └───────────┬───────────────┘
            allow ──┘   └── deny → blocked + logged (+ compensate / pause)
              ▼
        action actually executes

  ROADMAP: a local in-process deterministic tier (Cedar over a signed, cached
  policy bundle) answers the common case with no round-trip and keeps enforcing
  if the controller is unreachable. NOT in the shipping SDK yet.
```

## Vocabulary (used consistently below)

- **Checkpoint (PEP — Policy Enforcement Point):** the thing that intercepts and blocks/allows. **Runs inside the customer's environment** — today an SDK decorator (one wrapper per tool); network sidecar on the roadmap.
- **Policy engine (PDP — Policy Decision Point):** decides allow/deny. **Today it runs server-side in the controller** — every guarded call is a `POST /v1/validate`. It evaluates, in order: **Cedar policy** (tool / parameter / single-session sequence), **Sigma detection** (live), **ML classifier** (shadow/off by default), **cross-agent trust**, and **abuse/rate detection**. *Where the controller runs depends on the edition* (below).
- **Control plane:** authors, signs, and distributes policy and aggregates fleet telemetry — **never on the action path.** (Distinct from the *controller/PDP*, which **is** on the path today in Serverless.)

> **The honest split (today):** the *enforcement point* is local (the SDK decorator), but the *decision* is a **network call to the controller** — so today every guarded action round-trips to AegionAI's cloud (Serverless), and a controller outage **fail-secures** (blocks). The "local in-process deterministic floor that keeps agents running on outage, with no round-trip" is the **roadmap** that makes the latency and resilience story true; it is **not in the shipping SDK**. Read any claim of "local enforcement" as: **the PEP is local today; the local PDP floor is roadmap.**

## How we intercept (two modes) — orthogonal to the editions below

| Mode | What it is | Code change | Best for |
|---|---|---|---|
| **SDK (today)** | One wrapper per tool; POSTs to the controller before the tool body runs | One line per tool | Python agents, fast pilots, Bedrock/Azure/LangChain/MCP |
| **Sidecar (roadmap)** | Runs beside the agent, intercepts tool calls at the network level | None | Framework-agnostic, fleet-wide, non-cooperative enforcement |

**The biggest honest limitation today: SDK enforcement is cooperative.** It guards every tool you *wrap* — one line each. A tool left unwrapped, or an agent that calls the raw API/SDK directly, **bypasses the checkpoint.** Today the guarantee that "every action goes through us" rests on developer discipline (plus coverage tooling that flags unwrapped tools in CI). The **network sidecar closes this** by intercepting at the network layer regardless of cooperation — which is why it's on the roadmap, not a nicety.

**Mode ≠ edition.** *Mode* is **how** you intercept (SDK vs sidecar). *Edition* (next) is **where the controller runs** (Serverless / Dedicated / Self-Managed). It's a 2×3 space and not every cell is meaningful — e.g. the network sidecar is most relevant to Dedicated/Self-Managed.

## Deployment editions (where the controller runs)

The controller is the **policy engine** (the thing that decides). Editions differ only in where it runs:

| Edition | Where the decision (PDP) runs | What leaves the customer boundary | Status |
|---|---|---|---|
| **Serverless** (multi-tenant — runs in our cloud) | **AegionAI cloud** — every guarded call round-trips | **Prompt content** (needed for Cedar + Sigma server-side) — **unredacted today**; redaction is roadmap — plus metadata | **Today** |
| **Dedicated** (single-tenant — inside your own cloud network, managed by us) | **In your VPC** (the managed-OpenSearch model) | Only metadata (audit + trust signals) | **Roadmap** |
| **Self-Managed** (air-gapped — on-prem, you run it) | In your own environment | Nothing | **Roadmap** |

**The local floor that removes the round-trip is roadmap (across all editions):** the plan is a signed, versioned policy bundle **cached next to the checkpoint** so a local in-process tier answers the deterministic part (tool + parameter + single-session sequence) with **no network round-trip**, and **keeps enforcing if the controller is unreachable**. The shipping SDK does **not** do this yet — it round-trips to the controller for every decision. (See graceful degradation for today's actual outage behavior.)

## The decision (what happens on each action)

1. The checkpoint **POSTs the action** — *agent, tool, parameters, the user's request/prompt, session id* — to the controller (`/v1/validate`). *(Roadmap: a local tier answers the deterministic part without the round-trip.)*
2. **Cedar policy first:** is this agent allowed this tool? are parameters within policy? did the required prior steps happen *for this session*?
3. **Detection:** **Sigma signatures** (live) flag known injection/jailbreak patterns; the **ML classifier** escalates borderline cases for semantic judgment (shadow/off by default today); **cross-agent trust** and **abuse detection** also weigh in.
4. Returns **allow / deny** with a reason and the deciding source. A deny can trigger **quarantine** (pause the agent so later actions auto-deny) or, for an *already-committed* write, a **compensating rollback**.
5. Logged to a tamper-evident **audit trail** (off the response path). **On transport failure the SDK fail-secures** — DENY by default, or raises `SentraUnavailable` if the integrator set `fail_secure=False`.

**On rollback, precisely:** if we block *before* execution there is nothing to undo. Rollback is **compensation for writes that already committed** — earlier steps in a multi-step sequence, shadow-mode observations, or async paths — and only for **reversible** operations. It works **via per-action compensating adapters** (refunds today, more as we add them), with LIFO ordering — *not* a generic "undo any write" (the one-pager's Replit case is exactly the irreversible kind). Built single-cloud today.

**On shared state (even after the roadmap local tier ships):** only tool + parameter + **single-session** checks can be answered locally. **Cross-agent** trust and cross-session sequence are shared state and will still consult the controller. So the future local floor covers the single-session deterministic rules — not everything.

> **Engine status (honest):** the deterministic policy engine is **Cedar**, in **dev cutover (2026-06-13)** moving shadow→enforce — real and in the path on dev, not yet a long-proven production runtime. Detection: **Sigma-rule matching is live** (the always-on floor); the **ML classifier is shadow / disabled by default**, pending an eval-harness sign-off on precision/recall (WS19). So today's *running* detection is deterministic Sigma; the ML tier is being validated before it influences verdicts.

## Speed (today vs roadmap; measurement in progress)

**Today there is no in-process, no-network fast path.** Every guarded call is **one network round-trip** to the controller (`POST /v1/validate`), which runs Cedar policy + Sigma detection server-side; ML is shadow/off, so it doesn't add latency. Latency is therefore at minimum the round-trip to the PDP (AegionAI cloud for Serverless; in-VPC for Dedicated). Measured p50/p99 is being instrumented; we are not publishing a number we can't yet stand behind.

**Roadmap — what makes the latency story true:**
- **In-process local Cedar** over the cached policy bundle → sub-ms, **no round-trip** for the deterministic floor (clean traffic never leaves for a yes/no).
- **Distilled local classifier** (DeBERTa/DistilBert, <10ms CPU, in-process) so ML detection is on-box; target **<80ms end-to-end**; in Dedicated it runs in-VPC.
- **ML escalation only on borderline cases**, so clean traffic doesn't pay the model cost.

*"Latency scales with risk, not volume" is the target architecture, contingent on the local tier — not today's measured behavior.* (The earlier "sub-500ms"/"<80ms" figures are roadmap targets; today's number is round-trip-bound.)

## What happens if we're unreachable (graceful degradation)

**Today (shipping SDK): fail-secure.** Every guarded call is a POST to the controller. If the controller is unreachable, the SDK **fail-secure DENYs by default** (the action is **blocked**) — or, if the integrator sets `fail_secure=False`, raises `SentraUnavailable`. **There is no local cached-policy fallback today.** Honest implication: a controller outage **stops the guarded actions** (deny) rather than letting them run unguarded. That's the *secure* default — it never silently opens the gate — but it is **not** "agents keep running."

**Roadmap — what makes degradation graceful:** the in-process local deterministic tier (Cedar over the signed, cached bundle) **keeps enforcing the hard rules locally** when the controller is unreachable — so the deterministic floor holds and agents keep running, with only the advanced detection (Sigma/ML/trust) paused until reconnect. Per-agent config then chooses **fail-closed** (block — the right default for money movement) vs **degrade-to-floor** (keep running on cached hard rules).

- **The policy *control plane* is never on the path** (authoring/signing/distribution). What sits on the path today is the *decision controller (PDP)*; moving its deterministic floor in-process (roadmap) is precisely what takes it off the hot path.

## Security boundary & trust model  *(the CISO section)*

**The checkpoint runs inside your boundary and is fail-secure. Today the decision is made in the controller, so request content crosses to it — which is why the strict editions move the controller into your boundary.**

- **What leaves, exactly (Serverless, today):** every guarded call POSTs the action — *agent, tool, parameters, the user's prompt, session id* — to the controller, because Cedar **and** Sigma run **server-side**. So **prompt content leaves the customer boundary on every call, and today it is sent unredacted** — the redaction pipeline is **not yet implemented**. This is a material disclosure: until redaction ships (or you choose an in-VPC edition), Serverless sends raw prompt content to AegionAI's cloud. **Redaction (Presidio-based) is the *intended* boundary protection, in build — not a current guarantee.** **Dedicated** and **Self-Managed** keep content in your boundary.
- **Storage:** action content is **not persisted** by default — checks are ephemeral; only audit metadata is retained, encrypted in transit and at rest, with configurable retention.
- **Subprocessor disclosure:** when the ML escalation is enabled it calls a third-party LLM, which would see the (today-unredacted) prompt in Serverless — a subprocessor a CISO must vet. In Dedicated/Self-Managed the heavier model is self-hosted in-VPC, so there is no external subprocessor on the detection path.
- **Policy integrity:** policy bundles are **signed and versioned**; the audit log is tamper-evident. A compromised control plane **cannot make the SDK accept a malicious decision without a signed, versioned policy change — which is auditable.** (Residual risk: the signing key itself; key management/rotation is part of treating ourselves as a high-value target.) Note the today-default is already conservative: on any failure the SDK **denies**, so an outage or tampering that breaks validation blocks actions rather than permitting them.
- **Policy revocation latency:** when you remove a permission it takes effect at the controller immediately; cached artifacts (e.g. Sigma rules) refresh on a **poll interval (~5–10s)**. Tightening this — and the roadmap SDK cache's refresh/revocation window — is tracked.
- **Deployment editions (your choice):** Serverless (fastest), Dedicated (data stays in your cloud), Self-Managed/air-gapped (nothing leaves) — see [editions](#deployment-editions-where-the-controller-runs).
- **Fits your stack:** complements identity (who the agent is) and SIEM (alerts flow out); we add *what the action is allowed to do, enforced in real time.*

**Open items a reviewer will (rightly) raise:** SDK is **Python-only today** (other runtimes need the sidecar or a native SDK); the latency/resilience story depends on the **roadmap local tier**, not the shipping SDK; redaction is **not yet built**; multi-tenant isolation for Serverless is asserted, with **SOC 2 Type II in progress**. We'd rather you see these now than discover them in diligence.

## How the model improves (aligned with the ML strategy)

- **Base detector:** the live floor is **Sigma signatures** (deterministic, explainable, version-controlled); the **ML classifier** (Bedrock-hosted, in shadow today) adds semantic coverage; the **roadmap** detector is a distilled transformer (DeBERTa/DistilBert-class) fine-tuned on **public adversarial datasets** — no customer data required.
- **Per-deployment adaptation:** the behavioural-anomaly layer builds a **local baseline inside each deployment**; **no raw data is shared between customers**. Strict editions ("nothing leaves") therefore **trade away central learning by design** — they improve locally, not from the fleet.
- **Optional federation (post-seed):** deployments may opt into sharing **gradient updates only** (not data) with a global model — the standard federated pattern. This is the long-term moat, and it is **opt-in**.

## Coverage today vs roadmap (honest)

| | Status |
|---|---|
| SDK checkpoint (cooperative), **fail-secure on outage** (DENY/raise), tamper-evident audit trail | **Built** |
| Serverless (multi-tenant): SDK → controller round-trip per call | **Built** |
| Sigma-rule detection (injection/jailbreak; explainable, version-controlled) | **Built (live, always-on floor)** |
| ML classifier escalation (Bedrock Haiku/Sonnet) for borderline cases | **Built (shadow / off by default, pending precision-recall sign-off)** |
| Tool + parameter policy, single-session sequence, trust/quarantine | **Built (single-cloud; Cedar engine in dev cutover)** |
| Abuse / rate detection on action metadata | **Built (live)** |
| Compensating rollback (per-action adapters, LIFO; refunds today) | **Built (single-cloud)** |
| AWS Bedrock + Azure connectors; live cross-cloud demo | **Built** |
| **In-process local Cedar tier + signed cached-policy bundle (no-round-trip floor)** | **Roadmap** |
| **Degrade-to-cached-policy on outage (agents keep running on the floor)** | **Roadmap** |
| **PII detection / redaction pipeline (Presidio-based)** | **Roadmap (in build)** |
| Distilled local classifier (DeBERTa/DistilBert, CPU, in-process) | **Roadmap (hot-path target)** |
| Behavioural anomaly model (Isolation Forest — distinct from live abuse detection) | **Roadmap (design complete)** |
| Dedicated single-tenant controller (in-VPC) | **Roadmap** |
| GCP connector; multi-cloud blast-radius containment | **Roadmap** |
| Network sidecar (zero-code, non-cooperative enforcement) | **Roadmap** |
| Optional federated improvement | **Roadmap (post-seed)** |
| SOC 2 Type II | **In progress** |

*"Single-cloud" means the policy/sequence/trust logic is proven within one cloud; cross-cloud **trust propagation** is demonstrated (S2 scenario), but cross-cloud **blast-radius containment** is roadmap.*

---
*This brief is the "how"; pair it with the one-pager's "why." Where prose and the coverage table disagree, the table wins.*
