# AegionAI Guard — Architecture

**Version:** 1.0 (Draft for Review)
**Last Updated:** 2026-06-15
**Owner:** Shashank Gupta (Founder/CEO)
**Companion docs:** [PRD.md](PRD.md) (the "what" — requirements by ID) · [vision.md](vision.md) (vision & pillars) · [STRATEGY.md](STRATEGY.md) (market / GTM / roadmap) · LLDs in [lld/](lld/)

> This document describes **how** we build AegionAI Guard to satisfy the requirements in the [PRD](PRD.md). It references requirements by ID (FR-x / NFR-x) rather than restating them. It is honest about **today vs roadmap** — where they differ, this doc and the PRD's status column win over any aspirational prose.

---

## 1. Context

### 1.1 Background — the current situation

AI agents have moved from generating text to **taking actions** — calling tools, APIs, and databases that move money, change records, and send messages. Enterprises run these agents across more than one cloud (AWS Bedrock, Azure OpenAI/Foundry, GCP Vertex) and increasingly want them to run with little human supervision. The operational reality today:

- Agents act at machine speed; a wrong or manipulated action causes real damage before a human notices.
- Existing tooling **detects and warns** at the per-call level; nothing **enforces** at the action level across a fleet and across clouds.
- The team that must approve this (the CISO) cannot accept a design that adds latency, becomes a single point of failure, or exfiltrates sensitive data.

### 1.2 Problem statement

**Sit in front of every consequential agent action and decide — in real time, before it runs — whether it is allowed, across any cloud, without (a) adding unacceptable latency, (b) becoming a single point of failure, or (c) seeing data the customer won't let leave their boundary.**

These three constraints (latency, availability, data boundary) are the architecture's hardest forcing functions; most decisions below trace back to them.

### 1.3 Goals & Tenets

Goals are the PRD's three pillars: **Stop harm before it happens · Make autonomy safe · Trusted on every cloud.** The architecture is built to these **tenets** (design principles that break ties):

1. **Enforcement is local; the control plane is never on the action path.** The decision authority may be remote, but the *enforcement point* lives in the customer's environment.
2. **Fail secure, never fail open.** Any failure denies (or degrades to the cached hard-rule floor) — it never silently permits.
3. **Deny-by-default, explainable.** Every verdict names its deciding source and is auditable.
4. **Defense in depth.** Independent layers; evading one is caught by another; no single point of detection failure.
5. **Latency scales with risk, not volume.** Cheap deterministic checks first; expensive models only on borderline cases.
6. **The data boundary is the customer's to set.** What leaves is a deployment choice (edition), and sensitive values are redacted or never leave.
7. **Multi-tenant and multi-cloud from the foundation**, not retrofitted.
8. **Honest staging.** Ship deterministic floors first; layer ML and deeper detection behind shadow-then-enforce gates.

### 1.4 Requirements (by reference)

This architecture satisfies the [PRD](PRD.md) requirements; key anchors:
- Interception & enforcement: **FR-1.x**; Policy decision engine: **FR-2.x**; Threat detection (D1–D7, phases): **FR-3.x**; Trust & containment: **FR-4.x**; Rollback: **FR-5.x**; Audit/observability: **FR-6.x**; Integration & connectors: **FR-7.x**; Management plane: **FR-8.x**; Deployment editions: **FR-9.x**; Tenancy & identity: **FR-10.x**.
- Non-functional: latency **NFR-1/2**, availability **NFR-3**, resilience **NFR-4**, scalability **NFR-5**, tenant isolation **NFR-6**, data boundary **NFR-7**, compliance **NFR-8**, integrity **NFR-9**, observability **NFR-10**, portability **NFR-11**.

---

## 2. Architecture

### 2.1 System context

```
        ┌──────────────────────── Customer environment ────────────────────────┐
        │                                                                       │
        │   AI agent ──▶ CHECKPOINT (PEP) ──▶ tool / API / database             │
        │   (Bedrock,        │ intercepts          (only if ALLOWED)            │
        │    Azure, …)       │ the action                                       │
        └────────────────────┼──────────────────────────────────────────────────┘
                             │ POST /v1/validate   (decision request)
                             ▼
        ┌──────────────── AegionAI Guard ────────────────┐     ┌─────────────────┐
        │  CONTROLLER (PDP)  ── decides allow/deny        │     │  CONTROL PLANE  │
        │  policy + detection + trust + abuse             │◀────│ policy authoring│
        │                                                 │     │ signing/dist.,  │
        │  SIGNAL STORE  (audit: DynamoDB + CloudWatch)   │     │ fleet telemetry,│
        └──────────────────────┬──────────────────────────┘     │ SOC console     │
                              decisions + signals                └─────────────────┘
                                     ▼
                          SOC console / dashboards / SIEM export
```

- **Checkpoint (PEP)** — in the customer's environment (SDK decorator today; connector interceptor; network sidecar roadmap). FR-1.x.
- **Controller (PDP)** — decides each action (policy + detection + trust + abuse). Where it runs depends on the **edition** (§2.4).
- **Control plane** — authoring, signing/distribution, fleet telemetry, console. **Never on the action path** (tenet 1).
- **Signal store** — the audit system of record (LLD 17): DynamoDB for fast/recent reads, CloudWatch as the long-term compliance archive.

### 2.2 The decision flow (one action)

One endpoint, `POST /v1/validate`, branches on a `phase` field (`request` | `content` | `output` | `memory`; FR-3.4). For the common `request` phase:

```
checkpoint ──POST /v1/validate──▶ controller
                                     │
   1) cheap-deterministic frontier (≈1–5 ms each, short-circuit on DENY):
        trust ▸ policy (Cedar: tool/param/sequence) ▸ sigma signatures
        ▸ taint gate ▸ abuse/rate ▸ context
                                     │  (all ALLOW?)
   2) expensive-model fan-out IN PARALLEL (max, not sum):
        ML classifier ▸ trajectory(D1) ▸ content/output models
                                     │
   3) combiner: deny-overrides + priority ──▶ ALLOW / DENY (+ reason, source)
                                     │
   4) async, off the response path: audit signals + metrics
        on transport failure → FAIL-SECURE (deny / raise)
```

- **Sigma DENY short-circuits before any model is invoked** — preserving the "cheap-deny skips the ~600 ms model cost" property (tenet 5). FR-3.1.
- **The combiner** is deny-overrides with explainable priority (FR-2.7); it produces the dashboard's `winning_source`.
- **Audit is fire-and-forget** off the response path (FR-6.1) so the decision returns immediately.
- Today the pipeline is sequential short-circuit; the **parallel-gather scheduler is the WS20.0 prerequisite (FR-2.8)** that keeps latency bounded as layers grow (§2.6).

### 2.3 Components

| Component | Role | Reference |
|---|---|---|
| **Checkpoint / SDK** | PEP — intercepts the action, calls the controller, enforces the verdict (fail-secure) | FR-1.x, `lld/18`, `lld/23` |
| **Policy decision engine** | Cedar evaluation of tool / parameter / single-session sequence | FR-2.x, `features/cedar-policy`, `lld/18` |
| **Detectors** | Sigma (live), ML classifier (shadow), D1–D7 layers across phases | FR-3.x, `lld/19`, `lld/20` |
| **Trust & containment** | Per-agent/session trust, quarantine, cross-agent filtering, abuse/rate | FR-4.x, `lld/12` |
| **Rollback coordinator** | Per-action compensating adapters, LIFO, reversibility checks | FR-5.x |
| **Signal store** | DynamoDB (fast/recent) + CloudWatch (archive); request-id correlation | FR-6.x, `lld/17` |
| **Connectors / Import** | Bedrock, Azure (GCP roadmap); Connect & Discover → auto-seed policy | FR-7.x, `features/multicloud-agent-import` |
| **Management plane** | Agent registry, policy CRUD, multi-format authoring (YAML/JSON→Cedar), monitor-mode seeding | FR-8.x, `features/agent-policy-management` |
| **Control plane / console** | Policy signing/distribution, fleet telemetry, SOC console | FR-6.4, `lld/21` |

### 2.4 Deployment models (where the controller runs)

The control plane is always remote and off the path; the **controller (PDP)** location is the edition (FR-9.x). This is the central lever for the latency/availability/boundary constraints.

| Edition | Controller runs | What leaves the boundary | Interception | Status |
|---|---|---|---|---|
| **Serverless** (multi-tenant) | AegionAI cloud | Prompt content (unredacted today; redaction roadmap) + metadata | SDK decorator / connector + **in-process local tier** (roadmap, FR-1.7) | **Today** |
| **Dedicated** (single-tenant) | In the customer's VPC (managed by us) | Only metadata (audit + trust) | SDK + **network sidecar** (FR-1.5) | Roadmap |
| **Self-Managed** (air-gapped) | In the customer's environment, customer-operated | Nothing | SDK + sidecar | Roadmap |

**Honest today:** in Serverless every guarded call is a network round-trip to the controller, and content leaves the boundary (Cedar + Sigma run server-side). The **in-process local tier** (FR-1.7) — signed cached policy evaluated locally with no round-trip — is the roadmap that delivers the latency and "keep running on outage" story. The **in-VPC editions** move the whole controller into the customer's boundary.

### 2.5 Connectivity & Security

**(a) Interception — how the action is captured.** *Options considered → decision.*

| Option | Pros | Cons | Decision |
|---|---|---|---|
| **SDK decorator** (one wrapper per tool) | Trivial install; precise; catches in-process tools | Cooperative — unwrapped tools/raw calls bypass; Python-only today | **Today's default** (FR-1.2) |
| **Connector interceptor** (Bedrock action-group Lambda / Azure Function) | No agent code change; cloud-native | Per-cloud; catches network tool calls only | **Built for Bedrock/Azure** (FR-7.1/7.2) |
| **Network sidecar** | Zero-code, framework-agnostic, non-bypassable, default-on (customer-controllable) | Needs in-boundary infra | **Roadmap — for Dedicated/Self-Managed** (FR-1.5) |

> Honest limitation: today's enforcement is **cooperative** — it guards what's wired through it. The sidecar (in-boundary editions) closes this by intercepting at the network layer, **on by default and fully under the customer's control** (off per agent/tool/globally).

**(b) Agent identity — who is calling.** Today the controller trusts a self-asserted `agent_id` behind a *shared* API-Gateway key — any key-holder can claim any agent (acceptable for the seeded demo; not for a real customer). Decision (FR-10.3): issue a **per-agent credential at import** and resolve the authoritative `(tenant_id, agent_id)` from the *verified* credential, never the request body. Credential mechanism (signed per-agent token vs cloud workload identity) is an [open question](PRD.md#10-open-questions).

**(c) Tenant isolation.** Every connection, agent, policy, credential, and signal is keyed by `tenant_id` (FR-10.1). *Options:* row-level tenant scoping (chosen for Serverless — `TENANCY_V2` tenant-scoped tables, cutover in flight) → single-tenant **deployment** isolation for Dedicated/Self-Managed (the strongest boundary). NFR-6.

**(d) Data boundary & integrity.** Policy bundles are **signed and versioned** (NFR-9); the audit log is tamper-evident. Because enforcement is local and fail-secure, a compromised control plane **cannot make the checkpoint permit a malicious action without a signed, versioned, auditable policy change** (residual risk: the signing key — managed/rotated). What crosses the boundary is covered in §2.8.

### 2.6 Scalability

The decision path must scale from one agent to a fleet, and stay within budget as detection layers multiply (NFR-5).

| Concern | Approach → decision |
|---|---|
| **Layer count vs latency** | Sequential short-circuit (today) → **parallel-gather scheduler over a cost-annotated DAG** (FR-2.8 / WS20.0): cheap-deterministic frontier first (short-circuits DENYs *before* any model), then expensive models in parallel — total latency `max(models)`, not `sum`. `fail_fast` (prod default) vs `evaluate_all` (shadow/forensics). |
| **Round-trip cost** | In-process policy/sigma caches (signed bundles); the in-process local tier (FR-1.7) removes the round-trip for the deterministic floor on the common ALLOW path. |
| **Stateless decision path** | Controller is a stateless, horizontally-scaled service (singleton in-process caches per task); shared state (sessions, trust, sigma version) lives in DynamoDB/Redis with version-row invalidation so a policy change propagates fleet-wide in **seconds**, not "up to the TTL." |
| **Audit write volume** | Off-path fire-and-forget writes; DynamoDB on-demand for fast reads + CloudWatch archive; ~rounding-error cost even at 10× MVP traffic (LLD 17). |
| **Latency budgets (measured/targeted, WS24)** | Deterministic ≤ 500 ms p99 at load; ML hot ≤ 900 ms; deep-model ≤ 2.5 s; distilled-local model < 100 ms (roadmap). NFR-1/2. |

### 2.7 Reliability & Resiliency

Tenet 2: fail secure, never fail open. The failure matrix:

| Failure | What breaks | What still holds | Agent impact |
|---|---|---|---|
| **Control plane unreachable** | Policy updates, dashboards, fleet telemetry pause | Controller keeps deciding; cached signed policy | None (control plane is off-path) |
| **Controller unreachable (Serverless, today)** | The decision call fails | SDK **fail-secure**: DENY by default, or raise if `fail_secure=False` | Guarded actions **blocked** (secure, but not "keep running") |
| **Controller unreachable (with in-process local tier, roadmap)** | Advanced detection pauses | Local deterministic floor (Cedar over cached bundle) keeps enforcing | Agents **keep running** on the hard rules |
| **ML / deep models unavailable** | Semantic detection degrades | Deterministic floor + Sigma unaffected; ML is shadow/off by default anyway | Decisions on hard rules; flagged for shadow re-scan |
| **Stale policy** | Running on older bundle | Versioned + signed; version-row invalidation propagates in seconds; max-staleness fail-closed for money-movement (roadmap) | Bounded, configurable |

Per-agent fail mode (fail-closed vs degrade-to-floor) is configurable (FR-1.4); money-movement defaults to fail-closed. NFR-3/4.

### 2.8 Data, Privacy & Compliance

**What crosses the boundary (Serverless, today, honest):** every guarded call sends the action — agent, tool, parameters, the user's prompt, session id — to the controller, because Cedar and Sigma run server-side. **Content leaves, unredacted today.** Mitigations on the roadmap and by edition:

- **Input-side redaction** (FR-3.13): redact PII/secrets before content leaves; the engine sees the shape, not the secrets.
- **Output-side DLP** (FR-3.7 / Layer D5): detect and REDACT/HOLD sensitive data the agent is about to emit.
- **In-VPC / air-gapped editions** (FR-9.2/9.3): content never leaves the customer boundary.
- **Storage:** action content is **not persisted** by default; only audit metadata is retained (DynamoDB 90-day window + CloudWatch archive), encrypted in transit and at rest, with configurable retention. The CloudWatch dual-write is the compliance archive and is mandatory (LLD 17).
- **Subprocessor:** when ML escalation is enabled it calls a hosted model (a subprocessor a CISO must vet); in-VPC editions self-host it. NFR-7.
- **Compliance:** tamper-evident audit + the signal store support SOC 2 / HIPAA / GDPR / EU AI Act evidence; SOC 2 Type II in progress. NFR-8.

### 2.9 Operations

- **Infrastructure as code:** AWS CDK (stacks per concern — network/storage/compute/api/monitoring); see `cdk/` and best-practices §1.
- **Deploys:** scripted, milestone-tagged immutable Docker images (`build_and_push_image.py`), rollback by re-tagging (best-practices §5).
- **Feature gating & safe rollout:** capabilities ship behind flags and **shadow-then-enforce** gates — `CEDAR_ENABLED`/`CEDAR_SHADOW_MODE`, `ML_CLASSIFIER_ENABLED`/`ML_CLASSIFIER_SHADOW_MODE`, `TENANCY_V2_ENABLED`, `fail_secure`, `fail_fast`/`evaluate_all`. A detector runs in shadow (records signals, no verdict effect) until its precision/recall is signed off (FR-3.3), then is promoted.
- **Observability (NFR-10):** per-validator metrics, decision-source attribution, latency timing logs; the **signal store** powers the SOC console (per-session timeline, decision sources) and SIEM export.
- **SLOs:** enforcement availability ≥ 99.99% (local, fail-secure); control-plane availability 99.9% → 99.99%; latency budgets per §2.6.

### 2.10 Metering & Billing

We sit on every action, so usage is directly observable. *Options → leaning:*

| Basis | What it counts | Fit |
|---|---|---|
| **Per validation / action** | Each `/v1/validate` decision | Truest to value; aligns with the north-star ("actions protected"); usage-based for **Serverless** |
| **Per agent under management** | Active governed agents | Simple to forecast; good list-price anchor |
| **Per deployment / subscription** | A Dedicated/Self-Managed fleet | Fits in-VPC editions (we don't meter their internal traffic) |

**Leaning:** usage-based (per validation, tiered) for Serverless; **subscription** for Dedicated/Self-Managed (the customer runs the data plane). Exact basis is an open business decision in [STRATEGY.md](STRATEGY.md). Metering reuses the audit pipeline (count decisions off the signal store) — no separate metering path.

---

## 3. Key Architecture Decisions (ADR summary)

| # | Decision | Why | Status |
|---|---|---|---|
| AD-1 | **Control plane off the action path; PEP local** | Latency, availability, no single point of failure (tenets 1–2) | Today (PEP local; PDP remote in Serverless) |
| AD-2 | **Cedar** as the policy engine | Fast, formally-grounded, embeddable (enables the in-process local tier) | Dev cutover; shadow→enforce |
| AD-3 | **One `/v1/validate` endpoint, `phase` field** | Three moments = three round-trips regardless of URL count; keeps the surface small | request live; content/output/memory roadmap |
| AD-4 | **Deterministic-first, parallel models** (DAG scheduler) | Latency scales with risk; cheap DENY skips model cost (tenet 5) | Sequential today → WS20.0 parallel-gather |
| AD-5 | **Sigma (live) floor + ML (shadow) escalation** | Explainable, version-controlled deterministic floor; ML behind eval gate | Today |
| AD-6 | **Edition = where the controller runs** | The data-boundary lever; lets regulated buyers keep content in-boundary | Serverless today; in-VPC roadmap |
| AD-7 | **Verified per-agent identity over self-asserted id** | A shared key can't prove *which* agent; required before "this policy governs your agent" | Roadmap (FR-10.3) |
| AD-8 | **Multi-tenant from the foundation** (`tenant_id` keys) | Onboarding customer #2 is a data op, not a re-architecture | In build (TENANCY_V2) |
| AD-9 | **Fail-secure, audit off-path, signed policy** | Never fail open; decision returns immediately; tamper-evident | Today |

---

## 4. Open Architecture Questions

Tracked against the PRD's [Open Questions](PRD.md#10-open-questions):
1. **Verified agent-identity mechanism** (AD-7) — signed per-agent token vs cloud workload identity; issuance/rotation.
2. **Sidecar feature parity** — how the network sidecar delivers the multi-phase (`content`/`output`/`memory`) coverage the SDK decorators provide.
3. **Distilled-local-model path** — packaging the < 100 ms in-process classifier (FR-3.12) for the in-VPC editions.

---
*This is the "how"; pair it with the [PRD](PRD.md) ("what") and [vision.md](vision.md) ("why"). Where this doc and the PRD's status column disagree, the PRD status wins.*
