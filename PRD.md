# AegionAI Guard — Product Requirements Document (PRD)

**Product:** AegionAI Guard — the runtime safety & governance layer for AI agents
**Version:** 1.1
**Last Updated:** 2026-06-15
**Status:** Draft for Review
**Owner:** Shashank Gupta (Founder/CEO)
**Companion docs:** [ARCHITECTURE.md](ARCHITECTURE.md) (the "how") · [STRATEGY.md](STRATEGY.md) (market / GTM / roadmap) · [vision.md](vision.md) (vision & pillars) · [pitch/one-pager.md](pitch/one-pager.md) (the "why")

> This PRD defines **what** AegionAI Guard is — the product requirements and how they map to the strategic roadmap. (Market, GTM, and business targets live in [STRATEGY.md](STRATEGY.md); the "how we build it" lives in [ARCHITECTURE.md](ARCHITECTURE.md), which references this PRD by requirement ID.)

---

## Glossary (terms used throughout)

*New readers can skip to the Overview below and refer back here.*

- **PEP (checkpoint):** Policy Enforcement Point — intercepts/blocks the action; runs in the customer's environment.
- **PDP (policy engine / controller):** Policy Decision Point — decides allow/deny.
- **Control plane:** authors / signs / distributes policy and aggregates telemetry; never on the action path.
- **Deterministic tier:** tool / parameter / sequence checks (Cedar).
- **Detection layers (D1–D7):** the phased defense-in-depth detectors (trajectory, indirect injection, memory integrity, taint/information-flow, output/DLP, network/egress, provenance) — see `lld/20`.
- **Phase:** which moment of the agent loop a `/v1/validate` call covers — `request` (action), `content` (ingested data), `output` (emitted data), `memory` (memory write).
- **Editions:** Serverless (multi-tenant cloud) / Dedicated (in-customer-VPC, managed) / Self-Managed (air-gapped).
- **Shadow mode:** a detector or policy records signals without affecting the verdict.
- **Monitor mode:** a seeded default policy that observes (doesn't block) so a freshly imported agent is governed without a wall of denials.

---

## 1. Overview

AegionAI Guard is the **runtime safety and governance layer for AI agents**. It sits where an agent's decision becomes a real action — a tool, API, or database call — and decides, in real time, whether that action may run. Unlike tools that only *detect and warn*, it **enforces**: it blocks unsafe actions before they execute, rolls back already-committed reversible writes, and quarantines a misbehaving agent **or session**.

It spans a **control plane** (policy, trust, audit, fleet view) and an **in-boundary data plane** (the enforcement and detection that run inside the customer's environment for the Dedicated and Self-Managed editions) — protecting every agent across AWS, Azure, GCP, and on-prem, including cross-agent and cross-cloud.

**Enforcement is mechanical, not advisory:** on a deny, the checkpoint blocks the tool from running — it does not merely flag it. Today the checkpoint is installed by the customer at the call site (one line per tool, or via a cloud connector); a network sidecar will extend this to automatic coverage that is **on by default and fully under the customer's control** (turn off per agent, per tool, or globally).

**The Kubernetes analogy — but more than a control plane.** Like Kubernetes for AI agents: a control plane *and* an in-boundary data plane that together deliver policy enforcement, observability, containment, and governance across single- and multi-agent systems — multi-cloud, with cross-agent and cross-cloud containment. Cloud providers can't match this: each governs only the agents on its own cloud.

**Why this matters (the bigger picture).** Today, keeping agents safe means a human watching over them — the very thing that stops agents from being useful at scale. AegionAI Guard is the automated safeguard that does the watching, so agents can run on their own and people step in only for the rare exceptions. **Our vision: make hands-off AI autonomy safe enough to trust — on any cloud.**

### Positioning
The only platform that governs AI-agent **actions** across AWS, Azure, GCP, and on-prem simultaneously — with real-time enforcement (not just detection), cross-agent blast-radius containment, and a deployment model that fits regulated buyers (in-VPC and air-gapped). Cloud providers structurally cannot do this: each protects only agents on its own cloud.

---

## 2. Problem & Context

AI agents have moved from *answering questions* to *taking actions* — moving money, changing records, sending messages — at machine speed. When an agent acts wrongly, it is not a bad answer; it is real damage, and today **nothing stops the harmful action in the moment**:

- An AI assistant told explicitly not to touch a production system deleted 1,000+ companies' records anyway, fabricated data, and misreported it as irreversible. ([Fortune, 2025](https://fortune.com/2025/07/23/ai-coding-tool-replit-wiped-database-called-it-a-catastrophic-failure/))
- In banking, a single agent error (double payment, wrong transfer) propagates across systems before a human notices; AmEx has begun refunding AI-agent purchase errors. ([The Financial Brand, 2026](https://thefinancialbrand.com/news/payments-trends/when-ai-agents-make-incorrect-purchases-whos-responsible-197147))
- A single hijacked agent became the entry point to breach 700+ companies at once (Drift/Salesloft). ([Trend Micro, 2025](https://www.trendmicro.com/en_us/research/25/i/ai-app-breach.html))

**Why it isn't solved:** existing tools (Lakera, CalypsoAI, HiddenLayer, Portkey-class gateways) **watch and warn** at the per-call level. None *enforce* at the action level across a fleet and across clouds, and none provide cross-agent containment or rollback.

**Why now:** 82% of enterprises use AI agents; only ~26–44% govern them. The EU AI Act (enforcement **Aug 2, 2026**) treats financial AI agents as high-risk with penalties up to 7% of global revenue. Two AI-security startups were just acquired ($300M, $180M). The market is forming now.

---

## 3. Goals & Success Metrics

### 3.1 Guiding Pillars

Three pillars guide everything we build (mirrored in [vision.md](vision.md)). Every requirement in this document ladders up to one of them.

#### Pillar 1 — Stop harm before it happens
- **Enforce, don't just detect** — block unsafe actions before they execute, not after.
- **Defense in depth** — independent layers (deterministic policy, Sigma detection, ML, trust, abuse); evading one is caught by another.
- **Contain blast radius** — quarantine a misbehaving agent or session; stop cross-agent and cross-cloud cascade.
- **Continuously adapt** — get better as attacks evolve, via automated red-teaming, model retraining, and retrospective re-scoring (the compounding moat).

#### Pillar 2 — Make autonomy safe
- **Take the human off the hot path** — handle agent decisions automatically; escalate only the genuine exceptions.
- **Always-on, low overhead** — fast enough to leave on synchronously, even for money-moving actions.
- **Observability & analytics** — real-time visibility into threats and decisions, so humans can trust the system and oversee the exceptions.

#### Pillar 3 — Trusted on every cloud
- **Multi-cloud & cross-cloud** — govern agents on AWS, Azure, GCP, and on-prem under one model, including cross-agent containment across clouds.
- **Deploy in the customer's boundary** — in-VPC (Dedicated) or air-gapped (Self-Managed); sensitive data never leaves.
- **Regulator-ready** — tamper-evident audit and compliance mapping (SOC 2, HIPAA, GDPR, EU AI Act).

### 3.2 Success Metrics

**North-star:** *how many agents we protect — and how much human oversight we take off their plate* (the decisions we handle automatically that would otherwise need a person). These are **product** metrics; business/growth KPIs (ARR, customers, ACV) live in [STRATEGY.md](STRATEGY.md).

**Security efficacy.** *Defense in depth means several independent layers (policy, signature detection, machine-learning detection, trust, abuse). We track how much gets caught — and, the real point, how little gets through all of them.*

| Metric | Target |
|---|---|
| Detection rate — share of attacks we catch (all layers combined) | high; tracked over time |
| Missed-attack rate ("false negatives") — attacks that got past *every* layer | near zero on known attack types |
| False-alarm rate ("false positives") — legitimate actions wrongly blocked | < 2% |
| Detector accuracy — precision, recall, and F1 score (the combined precision/recall measure), per detector | measured automatically before every release; a regression blocks the release |
| Time-to-detect / Time-to-Quarantine a compromised agent | < 5 seconds |
| Cross-agent cascade prevention — share of agent-to-agent attacks contained | 100% |

**Enforcement & reliability:**

| Metric | Target |
|---|---|
| Enforcement coverage — % of guarded actions validated pre-execution | 100% |
| **Enforcement availability** (local, fail-secure — agents never left unguarded) | ≥ 99.99% |
| Control-plane availability (policy updates, dashboards, advanced detection) | 99.9% → 99.99% |
| Rollback success (reversible ops) | > 95% |
| Compliance report generation | < 5 min |

**Performance** (validated against the latency work — Workstream 24 / [lld/24](lld/24-latency-optimization.md)). *Latency depends on how deep a check the action needs — fast for routine actions, more for the ones that need the machine-learning model.*

| Path | Target (99th-percentile, "p99") |
|---|---|
| Deterministic only — policy/signature check, no ML model invoked | ≤ 500 ms at load (≈ 0.6–1.2 s today) |
| With the fast ML model (hot path) | ≤ 900 ms |
| With deep-model escalation (rare, hardest cases) | bounded ≤ 2.5 s; reduced in follow-up |
| Roadmap — distilled local ML model (in-process, CPU; replaces the hosted classifier) | < 100 ms |
| Roadmap — in-process local enforcement (no network round-trip) | low tens of milliseconds for the deterministic path |

**Adoption & value (the north-star, in plain terms):**

| Metric | Meaning |
|---|---|
| Agents protected | reach — how widely we're deployed |
| **Decisions handled automatically** ("oversight taken off the human") | the autonomy value — decisions that would otherwise need a person |
| Harm prevented (count, and $ for money-movement) | ROI |
| Time-to-first-value (install → first enforcement) | onboarding speed |

---

## 4. Personas

| Persona | Role | What they need |
|---|---|---|
| **CISO / Head of AI Governance** | Economic buyer | Real-time enforcement, audit trail, compliance mapping (SOC 2, HIPAA, GDPR, EU AI Act), and a guarantee that sensitive data stays inside their boundary. |
| **Platform / DevOps Engineering Lead** | Champion | Kubernetes-native experience (CRDs, Helm), easy integration, low operational burden. |
| **AI/ML Engineer / Agent Developer** | Integrator/user | Low-effort integration (one wrapper per tool with the SDK today), clear reasons when an action is denied, shadow mode for safe rollout, minimal latency. |
| **Fraud / Risk Lead (beachhead)** | Buyer (financial-action agents) | Stop wrong refunds/transfers instantly; quantifiable loss prevention + regulator-ready logs. |
| **Compliance / Auditor** | Consumer of output | Forensic, queryable, immutable decision records. |

---

## 5. Key Use Cases

1. **Block a manipulated money-movement action.** A refund/transfer agent is prompt-injected to exceed limits; AegionAI denies before execution and logs the attempt with reason.
2. **Enforce required sequence.** An action that must follow an approval/KYC step is blocked if the prior step didn't happen for that session.
3. **Contain a compromised agent.** A misbehaving agent's trust drops; it is quarantined so subsequent actions auto-deny, and cross-agent messages from it are filtered — no cascade.
4. **Compensate a committed, reversible write.** When a step in a multi-step flow has already run and *can* be reversed, AegionAI Guard issues its reversing action (e.g., a refund-reversal request) in last-in-first-out order. *Many financial actions are not reversible once settled — for those, the safeguard is prevention (blocking before execution), not rollback.*
5. **One model across clouds and runtimes.** Agents on different platforms (AWS Bedrock and Azure today; GCP, on-prem, and AegionAI-hosted agents on the roadmap) are governed under one policy, trust, and audit model.
6. **Compliance evidence.** A regulator asks for "all DENYs in May"; the audit store answers from the compliance archive.
7. **Safe rollout.** A new policy/detector runs in shadow mode (records, doesn't block) until it proves out, then is promoted.

---

## 6. Scope

### In scope (the product)
AegionAI Guard **acts on agent actions** — it doesn't only watch them. In scope:
- **Enforcement (several kinds, not just policy):** block before execution on — tool allow/deny, parameter bounds, required-sequence, threat detection (signature + machine-learning), information-flow / taint rules, output / data-loss rules, cross-agent trust, and rate/abuse limits.
- **Containment & recovery:** quarantine an agent or session; compensating rollback of reversible actions.
- **Detection in depth:** layered detectors across the agent's loop — the action it takes, the untrusted content it ingests, the output it emits, and the memory it writes.
- **Visibility:** tamper-evident audit trail, real-time threat/decision analytics, compliance reporting.
- **Onboarding & management:** connect cloud accounts, discover and import agents, author policies, manage the fleet — multi-tenant.
- **Deployment:** the three editions below (multi-tenant cloud, in-customer-network, on-prem / air-gapped).

### Out of scope (explicit non-goals)
- **Not** an LLM (Large Language Model) gateway/router (Portkey-class per-call routing, caching, cost tracking) — we govern *actions*, not route model calls.
- **Not** a model-training or fine-tuning platform.
- **Not** an identity provider — we *complement* the customer's identity system (which proves who the agent is) and their SIEM (Security Information and Event Management) system (where alerts are aggregated).
- **Not** a replacement for the customer's own DLP (Data Loss Prevention) tooling — we integrate with it, and add our own redaction layer.

---

## 7. Functional Requirements

Priority: **P0** = MVP/now, **P1** = next, **P2** = later. Status reflects the shipping codebase as of 2026-06-15. *(See ARCHITECTURE.md for today-vs-roadmap detail; where status and prose disagree, status wins.)*

### 7.1 Interception & Enforcement (the checkpoint / PEP) — `lld/23`
| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-1.1 | Intercept every guarded agent action (tool/API/DB call) before execution | P0 | Built (SDK, cooperative) |
| FR-1.2 | One-line-per-tool SDK integration (Python) | P0 | Built |
| FR-1.3 | Fail-secure on validation failure (deny by default; configurable raise) | P0 | Built |
| FR-1.4 | Per-agent fail mode (fail-closed vs degrade) | P1 | Roadmap |
| FR-1.5 | Network sidecar interception — the interception model for the **in-boundary editions (Dedicated / Self-Managed)**; zero-code, framework-agnostic, non-cooperative | P1 | Roadmap |
| FR-1.6 | Non-Python SDKs (Node / Java / Go) | P2 | Roadmap |
| FR-1.7 | In-process local enforcement (**Serverless**) — evaluate the deterministic floor against a signed, cached policy bundle with no network round-trip, and keep enforcing if the controller is unreachable (the latency + resilience story) | P1 | Roadmap |

### 7.2 Policy Decision Engine — runtime decisions (PDP) — `lld/18`, `features/cedar-policy`
*This is the runtime engine that decides allow/deny on each action. Authoring and managing those policies is a different concern (and audience) — the **management plane**, §7.8.*

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-2.1 | Tool allow/deny per agent | P0 | Built |
| FR-2.2 | Parameter-bound policy (e.g., refund ≤ limit) | P0 | Built |
| FR-2.3 | Single-session sequence enforcement (required prior steps) | P0 | Built |
| FR-2.4 | Cedar as the authoritative policy engine | P0 | Built (dev cutover; shadow→enforce) |
| FR-2.5 | Evaluate **versioned, signed policy bundles** (the artifact the engine runs) | P0/P1 | Built (bundle) / signing P1 |
| FR-2.6 | `AgentPolicy` / `AgentTrust` CRDs (Kubernetes-native) | P2 | Roadmap |
| FR-2.7 | Deny-by-default combiner with explainable, prioritized decision sources | P0 | Built |
| FR-2.8 | Parallel-gather scheduler over a cost-annotated dependency graph (cheap checks short-circuit; models run in parallel) — bounds latency as detection layers grow | P1 | Roadmap (Workstream 20.0) |

### 7.3 Threat Detection (defense in depth) — `lld/19`, `lld/20`
*Detectors run across the four moments of an agent's loop, addressed via one endpoint with a `phase` field: the action it takes (`request`), untrusted content it ingests (`content`), the output it emits (`output`), and the memory it writes (`memory`). The deterministic signature floor is live; the deeper layers (D1–D7 in `lld/20`) are phased roadmap.*

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-3.1 | Signature (Sigma-rule) detection for injection / jailbreak — explainable, version-controlled | P0 | Built (live floor) |
| FR-3.2 | Machine-learning threat classifier (semantic) as the escalation tier | P1 | Built (shadow / off by default, pending precision-recall sign-off) |
| FR-3.3 | Shadow mode for any detector or policy (record signals, don't affect the verdict) | P0 | Built |
| FR-3.4 | Multi-phase validation surface (`request` / `content` / `output` / `memory`) — ship SDK decorators for **all** phases at release so signal data flows from day one (sidecar provides the same coverage in the in-boundary editions) | P1 | Partial (`request` live) / Roadmap |
| FR-3.5 | Conversation-trajectory detection — multi-turn manipulation, stateful (Layer D1) | P1 | Roadmap |
| FR-3.6 | Indirect / second-order injection detection for ingested content (retrieval documents, tool output, web pages), incl. spotlighting + taint tagging (Layer D2) | P1 | Roadmap |
| FR-3.7 | Output & effect validation — data-loss / PII detection, exfiltration-channel and volume-anomaly checks; can ALLOW / DENY / **REDACT** / HOLD-for-human (Layer D5) | P1 | Roadmap |
| FR-3.8 | Taint tracking / information-flow control — gate actions that would act on untrusted data (Layer D4) | P2 | Roadmap |
| FR-3.9 | Long-term memory-integrity guards — anti-poisoning on memory writes (Layer D3) | P2 | Roadmap |
| FR-3.10 | Network / egress validation and provenance checks (Layers D6 / D7) | P2 | Roadmap |
| FR-3.11 | Behavioural anomaly detection (per-deployment baseline, metadata-only) | P2 | Roadmap (design complete) |
| FR-3.12 | Distilled local classifier (in-process, CPU; target < 100 ms) to remove the hosted classifier's network/model latency | P1 | Roadmap |
| FR-3.13 | Input-side PII redaction — redact sensitive values before request content leaves the customer boundary | P1 | Roadmap (in build) |
| FR-3.14 | Continuous improvement — automated red-teaming, model retraining, retrospective re-scoring of past traffic | P2 | Roadmap |

### 7.4 Cross-Agent Trust & Containment — `lld/12`
| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-4.1 | Per-agent trust scoring from violations | P0 | Built (single-cloud) |
| FR-4.2 | Automatic quarantine of an agent **or session** (subsequent actions auto-deny) | P0 | Built (single-cloud) |
| FR-4.3 | Inter-agent message filtering / privilege-escalation block | P1 | Partial / Roadmap |
| FR-4.4 | Cross-cloud trust propagation | P1 | Demonstrated (S2) |
| FR-4.5 | Cross-cloud blast-radius containment | P2 | Roadmap |
| FR-4.6 | Rate-limit / abuse detection — deny when an agent or session exceeds its policy-defined action rate (pipeline Step 5) | P0 | Built (live) |

### 7.5 Rollback / Compensation
| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-5.1 | Per-action compensating adapters (e.g., refund reverser) | P0 | Built (single-cloud) |
| FR-5.2 | LIFO multi-step rollback within a session/conversation | P0 | Built |
| FR-5.3 | Reversibility checks (never imply irreversible can be undone) | P0 | Built |
| FR-5.4 | Expanded adapter library (more action types) | P1 | Roadmap |

### 7.6 Audit, Observability & Compliance — `lld/17`
| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-6.1 | Tamper-evident audit trail of every decision, written off the response path | P0 | Built |
| FR-6.2 | Fast per-session/recent decision reads (DDB) | P0 | Built |
| FR-6.3 | Long-term compliance archive + cross-cutting queries (CloudWatch) | P0 | Built |
| FR-6.4 | SOC console / dashboard: inventory, activity, violations, decision sources | P0 | Built |
| FR-6.5 | Compliance reports (SOC2 / HIPAA / GDPR / EU AI Act) generated < 5 min | P2 | Roadmap |
| FR-6.6 | Agent SBOM (models, tools, policies; signed) | P2 | Roadmap |

### 7.7 Integration & Multi-Cloud Connectors — `lld/15`, `lld/16`, `lld/22`, `lld/23`, `features/multicloud-agent-import`
*Goal: make getting an agent under governance as low-friction as possible — connect an account, discover the agents, onboard them with a starter policy and an interception path.*

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-7.1 | AWS Bedrock connector | P0 | Built |
| FR-7.2 | Azure (OpenAI / Foundry) connector | P0 | Built |
| FR-7.3 | One policy / trust / audit model across clouds (live cross-cloud demo) | P0 | Built |
| FR-7.4 | GCP Vertex connector | P1 | Roadmap |
| FR-7.5 | Request-id correlation across connectors | P0 | Built |
| FR-7.6 | SDK packaging for low-effort install (AWS Lambda layer, Azure Functions, generic Python) | P0 | Built |
| FR-7.7 | Connect a cloud account (AWS / Azure / GCP, read-only) and **discover** the agents running in it | P1 | Roadmap |
| FR-7.8 | Tool introspection on import (action-group / function / tool definitions → tool list) → **auto-seed a starter policy** | P1 | Roadmap |
| FR-7.9 | Import lifecycle tracking (`discovered → policy-seeded → intercepting / governed`) | P1 | Roadmap |
| FR-7.10 | Framework integrations (LangChain, CrewAI, MCP) for one-step instrumentation | P1/P2 | Roadmap |

### 7.8 Management Plane — agents, policies, onboarding — `lld/05`, `lld/11`, `features/agent-policy-management`, `features/multi-format-policy-authoring`
*The authoring/management side: how customers define and manage what the runtime engine (§7.2) enforces. Distinct from §7.2 — that one decides at runtime; this one is how policies and agents are created, bound, and operated.*

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-8.1 | Agent registry / inventory & lifecycle | P0 | Built |
| FR-8.2 | Policy authoring & CRUD (create/read/update/delete) APIs; bind policies to agents | P0 | Built |
| FR-8.3 | Multi-format policy authoring — structured YAML / JSON normalized to Cedar (customers don't hand-write Cedar) | P0/P1 | Built (YAML → Cedar) / JSON first-class P1 |
| FR-8.4 | Default starter policy seeded in **Monitor mode** on import, so no agent is ever unpoliced | P1 | Roadmap |
| FR-8.5 | Authentication & authorization (OIDC — OpenID Connect) for the console and APIs | P0 | Built |
| FR-8.6 | Self-service onboarding | P2 | Roadmap |

### 7.9 Deployment Models
| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-9.1 | **Serverless** — multi-tenant SaaS, controller in AegionAI cloud | P0 | Built |
| FR-9.2 | **Dedicated** — single-tenant managed fleet inside customer's cloud network (VPC); only metadata leaves | P1 | Roadmap |
| FR-9.3 | **Self-Managed / air-gapped** — customer-operated; nothing leaves | P2 | Roadmap |

### 7.10 Tenancy & Agent Identity — `features/multicloud-agent-import`
*Multi-tenancy is foundational, not a later add-on: every record and lookup is scoped to the owning customer. Verified agent identity stops one caller from impersonating another agent.*

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-10.1 | Multi-tenant isolation — every connection, agent, policy, credential, and signal scoped to `tenant_id`; onboarding a new customer is a data operation, not a re-architecture | P0 | In build (tenant-scoped tables; `TENANCY_V2` cutover in flight) |
| FR-10.2 | Tenant-scoped APIs, data stores, and dashboards | P0/P1 | Partial / Roadmap |
| FR-10.3 | **Verified agent identity** — per-agent credential issued at import; the controller resolves the authoritative `(tenant_id, agent_id)` from the verified credential, never from a self-asserted request field | P1 | Roadmap (today: shared API key only — `agent_id` is self-asserted) |
| FR-10.4 | Per-tenant configuration (policies, detectors, fail modes, retention) | P1 | Partial / Roadmap |

---

## 8. Non-Functional Requirements

| ID | Requirement | Target |
|---|---|---|
| NFR-1 | **Latency** — deterministic path (no ML model invoked) | ≤ 500 ms p99 at load (≈ 0.6–1.2 s today; Workstream 24 / [lld/24](lld/24-latency-optimization.md)). Roadmap in-process local enforcement targets low-tens-of-ms. |
| NFR-2 | **Latency** — detection path | Fast ML model ≤ 900 ms p99; deep-model escalation bounded ≤ 2.5 s. ML is invoked only on borderline cases, so routine actions take the faster deterministic path. |
| NFR-3 | **Availability** — enforcement (local, fail-secure) ≥ 99.99%; control plane | 99.9% → 99.99% |
| NFR-4 | **Resilience** — fail-secure | Validation failure denies by default; control-plane outage never silently permits; degrade-to-cached-floor (roadmap) keeps agents running on hard rules |
| NFR-5 | **Scalability** | Horizontal; single agent → fleet; stateless decision path where possible |
| NFR-6 | **Security** — tenant isolation | Strict isolation (Serverless); single-tenant boundary (Dedicated/Self-Managed) |
| NFR-7 | **Data boundary** | Redaction before egress (roadmap); Dedicated/Self-Managed keep content in-boundary; content not persisted by default |
| NFR-8 | **Compliance** | SOC 2 Type II (in progress); designed for HIPAA/GDPR/EU AI Act |
| NFR-9 | **Integrity** | Signed/versioned policies; tamper-evident audit; signing-key management/rotation |
| NFR-10 | **Observability** | Metrics, traces, decision-source attribution; SLO dashboards |
| NFR-11 | **Portability** | AWS, Azure, GCP, on-prem; no single-cloud lock-in |

---

## 9. Release Phasing

| Phase | Theme | Key requirements | Outcome |
|---|---|---|---|
| **P0 — MVP (now)** | Enforce on single cloud, prove cross-cloud, multi-tenant foundation | FR-1.1–1.3, 2.1–2.7, 3.1–3.3, 4.1/4.2/4.6, 5.1–5.3, 6.1–6.4, 7.1–7.3/7.5/7.6, 8.1–8.3/8.5, 9.1, 10.1/10.2 | Live demo: block injection, quarantine, rollback, cross-cloud; design-partner pilots |
| **P1 — Enterprise hardening** | Make latency, resilience, boundary, and identity real | FR-1.4/1.5/1.7, 2.8, 3.4–3.7/3.12/3.13, 4.3/4.4, 5.4, 7.4/7.7–7.10, 8.4, 9.2, 10.3/10.4; NFR-1/4/6/7 | In-VPC Dedicated, local cached enforcement, redaction, distilled model, sidecar, Connect & Import, verified agent identity; first paying enterprises; SOC 2 |
| **P2 — Platform & scale** | Category standard | FR-2.6, 3.8–3.11/3.14, 4.5, 6.5/6.6, 8.6, 9.3; CRDs / CNCF | Self-Managed / air-gapped, deep detection layers (D3/D4), compliance reports, blast-radius containment, Kubernetes CRDs |

**Phases are capability tiers gated by milestones and funding — not calendar commitments.** Dates and the year-by-year plan live in [STRATEGY.md](STRATEGY.md). (Roughly: P0 = validation, P1 = enterprise launch, P2 = category scale.)

---

## 10. Open Questions

*(Business/GTM questions — open-source core, pricing, beachhead emphasis — live in [STRATEGY.md](STRATEGY.md). These are product-level.)*

1. **Verified agent-identity mechanism** — the credential type and how it is issued/rotated for FR-10.3 (per-agent credential). *Open.*
2. **How the sidecar delivers the multi-phase features** — the SDK ships decorators for all phases (FR-3.4); how the sidecar (FR-1.5) provides the same `content` / `output` / `memory` coverage in the in-boundary editions is to be worked out. *To discuss later.*

---

*Living document. Update as requirements evolve; keep the ARCHITECTURE.md cross-references and statuses in sync.*
