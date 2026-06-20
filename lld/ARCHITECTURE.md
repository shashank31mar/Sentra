# AegionAI Guard — Architecture

**Version:** 1.2 (Draft for Review)
**Last Updated:** 2026-06-17
**Owner:** Shashank Gupta (Founder/CEO)
**Companion docs:** [PRD.md](../PRD.md) (the "what" — requirements by ID) · [vision.md](../vision.md) (vision & pillars) · [STRATEGY.md](../pitch/STRATEGY.md) (market / GTM / roadmap) · LLDs in [lld/](./)

> This document describes **how** we build AegionAI Guard to satisfy the requirements in the [PRD](../PRD.md). It references requirements by ID (FR-x / NFR-x) rather than restating them. It is honest about **today vs roadmap** — where they differ, this doc and the PRD's status column win over any aspirational prose.

---

## 1. Context

### 1.1 Background — the current situation

AI agents have moved from generating text to **taking actions** — calling tools, APIs, and databases that move money, change records, and send messages. Enterprises run these agents across more than one cloud (AWS Bedrock and Azure OpenAI/Foundry today; GCP Vertex on the roadmap) and increasingly want them to run with little human supervision. The operational reality today:

- Agents act at machine speed; a wrong or manipulated action causes real damage before a human notices.
- Existing tooling **detects and warns** at the per-call level; nothing **enforces** at the action level across a fleet and across clouds.
- The team that must approve this (the CISO) cannot accept a design that adds latency, becomes a single point of failure, or exfiltrates sensitive data.

### 1.2 Problem statement

**AI agents now take consequential actions on their own — moving money, changing records, deleting infrastructure — across more than one cloud, and nothing stops a harmful action in the moment.** Today the only real safeguard is a human re-validating each action — which doesn't scale and defeats the purpose of autonomy. Existing tools *detect and warn* at the per-call level; none *enforce* at the action level, contain a compromised agent before it cascades, or do so across clouds and on-prem. The job is to **replace that human checkpoint with an automated one** that's safe enough to trust.

The hard part is doing this within the constraints the buyer won't compromise — **sub-500ms latency, no new single point of failure, and a customer-controlled data boundary** (what leaves, if anything, is the customer's choice). The architecture carries these as **tenets (§1.4)** and **non-functional requirements (PRD §8)**, and most decisions below trace back to them. (Today's latency reality and the path to the sub-500ms target are in **§2.6** — it is a target, not yet met.)

### 1.3 Goals

The architecture serves the product's three pillars (defined in [vision.md](../vision.md) and [PRD.md](../PRD.md)) — **Stop harm before it happens · Make autonomy safe · Trusted on every cloud** — and does not restate them here.

### 1.4 Tenets (design principles that break ties)

1. **Enforcement is local; the control plane is never on the action path.** The decision authority may be remote, but the *enforcement point* lives in the customer's environment.
2. **Fail secure, never fail open.** Any failure denies (or degrades to the cached hard-rule floor) — it never silently permits.
3. **Deny-by-default, explainable.** Every verdict names its deciding source and is auditable.
4. **Defense in depth.** Independent layers; evading one is caught by another; no single point of detection failure.
5. **Latency scales with risk, not volume.** Cheap deterministic checks first; expensive models only on borderline cases.
6. **The data boundary is the customer's to set.** What leaves is a deployment choice (edition); sensitive values are redacted or never leave.
7. **Multi-tenant and multi-cloud from the foundation**, not retrofitted.
8. **Honest staging.** Ship deterministic floors first; layer ML and deeper detection behind shadow-then-enforce gates.

### 1.5 Requirements

This architecture satisfies the requirements defined in the [PRD](../PRD.md); the sections below cite the relevant **FR-/NFR-** IDs inline rather than restating them.

---

## 2. Architecture

### 2.1 System context — logical view

This is the **logical** architecture — the components and the action flow, independent of *where* each piece physically runs. Physical placement per deployment edition (which side of the customer boundary each box sits on) is in **§2.4**.

```mermaid
flowchart TB
  CP["<b>Control plane</b> (AegionAI-operated)<br/>authoring · signing · policy distribution<br/>fleet telemetry · threat-data flywheel · SOC console<br/><i>never on the action path</i>"]
  AG(["AI agent"])
  PEP["<b>Checkpoint (PEP)</b><br/>always in the customer's environment"]
  PDP{"<b>Policy Engine (PDP)</b><br/>full validator pipeline<br/>location = edition (§2.4)"}
  TOOL["Tool / API / database"]
  BLK["Blocked<br/>(+ rollback / quarantine)"]
  AUD[("Audit store<br/>recent + archive")]
  SOC["SOC console / SIEM"]

  AG -->|"① about to call a tool"| PEP
  PEP -->|"② ask"| PDP
  PDP -->|"③ decision: allow/deny + reason + action"| PEP
  PEP -->|"④ allow"| TOOL
  PEP -->|"④ deny"| BLK
  PDP -.->|"⑤ audit (metadata)"| AUD
  CP -.->|"signed policy (out-of-band)"| PDP
  AUD --> SOC
```

**Where each piece runs = the deployment EDITION (§2.4):** the **checkpoint (PEP)** is always in the customer's environment; the **policy engine (PDP) + audit store** run in AegionAI cloud (Serverless), the customer's VPC (Dedicated), or on-prem / air-gapped (Self-Managed); the **control plane** is always AegionAI-operated and off the action path.

- **Checkpoint (PEP)** — runs in the customer's environment; intercepts the action, asks the engine, and **enforces the returned verdict**. SDK decorator today; connector interceptor; network sidecar roadmap. FR-1.x.
- **Policy engine (PDP)** — runs the **full validator pipeline** and returns a **decision + reason + deciding source + action**: trust → policy (Cedar: tool/parameter/sequence) → signature (Sigma) → ML classifier → detection layers (trajectory, indirect/**multimodal** content, output/DLP, taint, memory, network/egress, provenance — D1–D7) → cross-agent trust → abuse/rate, combined by a deny-overrides combiner. A DENY can carry an **action** the checkpoint enforces: block, compensating rollback, or quarantine. *Where the engine runs depends on the edition* (§2.4). FR-2.x/3.x/4.x/5.x.
- **Control plane** — policy authoring, signing, distribution, fleet telemetry, SOC console, and the cross-cloud threat-data flywheel. **Never on the action path** (tenet 1).
- **Audit store** *(a role, not a fixed product)* — a **low-latency recent-decision store** + an **append-only long-term compliance archive**. Today implemented as DynamoDB + CloudWatch on AWS; **pluggable per cloud / on-prem** (LLD 17). Feeds the SOC console, SIEM export, and the threat-data flywheel.

### 2.2 The decision flow (one action)

One endpoint, `POST /v1/validate`, branches on a `phase` field (`request` | `content` | `output` | `memory`; FR-3.4). For the common `request` phase:

```mermaid
flowchart TB
  REQ["checkpoint → POST /v1/validate"]
  F["① cheap-deterministic frontier (~1–5 ms each)<br/>trust · policy (tool/param/sequence) · signature detection ·<br/>taint gate · abuse/rate · context<br/><i>a DENY here short-circuits before any model</i>"]
  M["② expensive models — in parallel (latency = max, not sum)<br/>ML classifier · trajectory (multi-turn) · content/output models"]
  COMB["③ combiner: deny-overrides + priority"]
  OUT(["ALLOW / DENY (+ reason, source, action)"])
  AUD["④ record the decision to the audit trail"]
  FS["transport failure → FAIL-SECURE (deny / raise)"]
  REQ --> F
  F -->|all ALLOW| M
  F -->|any DENY| COMB
  M --> COMB
  COMB --> OUT
  OUT --> AUD
  REQ -.-> FS
```

- **A signature DENY short-circuits before any model is invoked** — preserving "cheap-deny skips the model cost" (tenet 5). FR-3.1.
- The combiner is **deny-overrides with explainable priority** (FR-2.7) — it names the deciding source.
- **Every decision is recorded to the tamper-evident audit trail** (FR-6.1) — a recent-decision store plus a long-term archive (§2.8) — with **at-least-once delivery** (durable local buffer + retry), so no decision is lost off the response path.
- **Today the pipeline runs sequentially**; the **parallel-gather scheduler (FR-2.8) is a prerequisite** before more detection layers are added — see the critical-path note in §2.6.
- **`content` is multimodal** — text *and* images (e.g., a fraudulent or altered photo in an **insurance/claims** submission). Image-borne injection and image-fraud detection run here (FR-3.6 / FR-3.15) — the surface behind **claims fraud** (and B2C refund fraud).

### 2.3 Components

| Component | Role | Reference |
|---|---|---|
| **Checkpoint / SDK** | PEP — intercepts the action, calls the controller, enforces the verdict (fail-secure) | FR-1.x, `lld/18`, `lld/23` |
| **Policy decision engine** | Cedar evaluation of tool / parameter / single-session sequence | FR-2.x, `features/cedar-policy`, `lld/18` |
| **Detectors** | Sigma (live), ML classifier (shadow), D1–D7 layers across phases, **multimodal/image** threats (fraud photos, adversarial/image-borne injection) | FR-3.x, `lld/19`, `lld/20` |
| **Trust & containment** | Per-agent/session trust, quarantine, cross-agent filtering, abuse/rate | FR-4.x, `lld/12` |
| **Rollback coordinator** | Per-action compensating adapters keyed by the captured effect handle; dependency-ordered; reversibility checks (never implies the irreversible can be undone) | FR-5.x |
| **Audit store** | Recent-decision store + append-only compliance archive (today DynamoDB + CloudWatch; pluggable per cloud / on-prem); request-id correlation | FR-6.x, `lld/17` |
| **Connectors / Import** | Bedrock, Azure (GCP roadmap); Connect & Discover → auto-seed policy | FR-7.x, `features/multicloud-agent-import` |
| **Management plane** | Agent registry, policy CRUD, multi-format authoring (YAML/JSON→Cedar), monitor-mode seeding | FR-8.x, `features/agent-policy-management` |
| **Control plane / console** | Policy signing/distribution, fleet telemetry, SOC console | FR-6.4, `lld/21` |

**Effect capture (how rollback knows what to reverse).** Rollback is *compensation for already-committed writes*, so it needs two things the pre-execution checkpoint doesn't have: confirmation the action ran, and the **side-effect handle** to reverse (e.g., the transaction / refund id). The **SDK checkpoint captures the tool's result on the ALLOW path** (it wraps the call) and reports the handle back, keyed to the action; the rollback coordinator stores it and dispatches the matching per-action reverser. This is **natural in SDK mode and limited at the network-sidecar layer** (which sees bytes, not app-level handles), so rollback is scoped to SDK-integrated, reversible, handle-returning actions. Compensation is **ordered by recorded dependency, not naive LIFO**, so concurrent tool calls reverse correctly.

### 2.4 Deployment models (where the controller runs)

The control plane is always remote and off the path; the **controller (PDP)** location is the edition (FR-9.x). This is the central lever for the latency/availability/boundary constraints.

| Edition | Controller runs | What leaves the boundary | Interception | Status |
|---|---|---|---|---|
| **Serverless** (multi-tenant) | AegionAI cloud | Prompt content (unredacted today; redaction roadmap) + metadata | SDK decorator / connector + **in-process local tier** (roadmap, FR-1.7) | **Today** |
| **Dedicated** (single-tenant) | In the customer's VPC (managed by us) | Only metadata (audit + trust) | SDK + **network sidecar** (FR-1.5) | Roadmap |
| **Self-Managed** (air-gapped) | In the customer's environment, customer-operated | Nothing | SDK + sidecar | Roadmap |

**Honest today:** in Serverless every guarded call is a network round-trip to the controller, and content leaves the boundary (Cedar + Sigma run server-side). The **in-process local tier** (FR-1.7) — signed cached policy evaluated locally with no round-trip — is the roadmap that delivers the latency and "keep running on outage" story. The **in-VPC editions** move the whole engine into the customer's boundary.

#### Per-edition topology (network & security boundary)

**Serverless (multi-tenant — today).** *Security: TLS in transit, per-tenant API key + usage plan + WAF, encryption at rest, strict multi-tenant isolation. Trade-off: request content crosses to AegionAI cloud (redaction is roadmap).*
```mermaid
flowchart TB
  subgraph CUST["Customer environment"]
    AG["AI agent + SDK (PEP) — enforces the verdict"]
    TOOL["tool / API / DB"]
    AG --> TOOL
  end
  subgraph AEG["AegionAI cloud — multi-tenant (tenant-isolated)"]
    GW["API gateway — per-tenant key · usage plan · WAF"]
    PDP["Policy engine (PDP) + detectors"]
    AUD[("Audit store — recent + archive")]
    GW --> PDP --> AUD
  end
  AG -->|"HTTPS/TLS — POST (prompt content leaves)"| GW
  GW -->|"decision"| AG
```

**Dedicated (single-tenant — managed by us, inside the customer's cloud).** *Security: the whole PDP runs in the customer's VPC — private subnets, security groups/NACLs, KMS-encrypted store, no public ingress, egress only to the control plane. Only audit metadata + trust signals leave; prompt content never leaves the VPC.*
```mermaid
flowchart TB
  subgraph CUST["Customer cloud account — their VPC"]
    AG["Agent + SDK / sidecar (PEP)"]
    subgraph PRIV["private subnets · SG/NACL · KMS · no public ingress"]
      PDP["DATA PLANE (single-tenant, managed by us):<br/>Policy engine (PDP) + detectors + audit store"]
    end
    AG -->|"in-VPC call (no public internet)"| PDP
  end
  subgraph AEG["AegionAI control plane"]
    CP["authoring · signing · distribution · telemetry · SOC console"]
  end
  PDP <-.->|"signed policy in · audit metadata out only<br/>(PrivateLink / Private Service Connect)"| CP
```

**Self-Managed (air-gapped — customer-operated).** *Security: fully isolated — no outbound to AegionAI; signed/verified update supply chain. Everything (enforcement, detection, control plane) runs inside the customer's boundary.*
```mermaid
flowchart TB
  subgraph CUST["Customer environment — on-prem / air-gapped (NOTHING LEAVES)"]
    AG["Agent + SDK / sidecar (PEP)"]
    PDP["DATA PLANE (customer-operated):<br/>Policy engine + detectors (self-hosted model) + audit store"]
    CP["CONTROL PLANE (local install):<br/>authoring · console"]
    AG --> PDP
    CP -.->|"signed policy"| PDP
  end
  UPD["Signed release bundles<br/>(customer pulls — no push)"] -.->|"verified update supply chain"| CP
```

#### Ownership, billing & IP — Dedicated and Self-Managed

Both editions run the data plane **in the customer's own cloud account and VPC** (the BYOC — *bring-your-own-cloud* — model), ideally the same VPC where their agents already run. Ownership splits cleanly:

| Concern | Customer | AegionAI |
|---|---|---|
| Cloud account, VPC, compute/storage | **Owns & pays the cloud bill directly** | — |
| Data (prompts, actions, audit content) | **Owns; stays in their account** | — |
| Data-plane software, deploy automation, model weights | — | **Owns (licensed)** |
| Operations, updates, SLA | **Self-Managed: customer** | **Dedicated: AegionAI (managed)** |

**Why BYOC (the rationale):**
1. **Data residency** — request content never leaves the customer's account; only audit metadata leaves (Dedicated), or nothing (Self-Managed).
2. **Their cloud, their cost control** — the customer pays their own provider for compute, applying committed-spend discounts and keeping full cost visibility (no infra margin stacked on top).
3. **Co-located with the agents** — the agent→PDP call is an in-VPC hop (low latency, no public internet).
4. **A clean trust boundary** regulated buyers (banks, healthcare, defense) can actually accept.

**Billing.** The customer pays their cloud provider for the data-plane compute (it runs in their account); **AegionAI charges a software subscription + management fee** — *not* infrastructure. (Serverless is usage-priced because we host it; Self-Managed adds the customer's own operations cost.) We keep the data plane lean (distilled CPU model by default; GPU only on opt-in) so the customer's infra bill stays low.

**Provisioning & access.** Lead with **pull-based** deploy — the customer's cluster pulls signed images/config (Helm + GitOps) and a management agent reports health — so we hold **no standing push-access** into their account (a scoped cross-account role is an alternative). This also draws the Dedicated/Self-Managed line: **Dedicated = AegionAI operates it (connected); Self-Managed = the customer operates it (air-gappable).**

**IP protection (software running in the customer's environment).** The moat is **cross-cloud + in-boundary deployment + the threat-data flywheel + patent — not binary secrecy** (a copied snapshot is stale plumbing with no updates, no data, and a license/patent breach). We still raise the bar: **compiled** (non-interpretable) artifacts, **encrypted model weights**, optional **confidential-computing enclaves** (AWS Nitro Enclaves · Azure Confidential VMs · GCP Confidential VMs) so even the customer's own admins can't read the running model, **signed + licensed** releases, and crown-jewel models kept cloud-side for connected editions.

### 2.5 Threat Model & Security

We are a high-value target; security is designed **adversary-first**. *(Maturity per capability is in the [PRD](../PRD.md) status columns, §7.)*

**Adversaries → primary control:**

| Adversary | What they attempt | Primary control |
|---|---|---|
| **Malicious / manipulated agent** | exceed policy; run a destructive or money-moving action | deterministic policy (tool / param / sequence) + detection, enforced *before* execution |
| **Hijacked / compromised agent** | pivot, attack other agents, cascade | trust scoring + quarantine; cross-agent message filtering; blast-radius containment (roadmap) |
| **Attacker on the detection layer itself** | evade the classifier (adversarial prompts, obfuscation); flood `/v1/validate` (DoS) | **defense in depth** — independent layers, so evading one is caught by another; rate-limit + backpressure + fail-secure on overload |
| **Malicious tenant** (multi-tenant Serverless) | reach another tenant's data or policies | tenant context enforced at the data layer; isolation tests; single-tenant boundary (Dedicated/Self-Managed) removes the surface |
| **Network attacker** | intercept or tamper with the decision path | TLS; private subnets / PrivateLink for in-VPC editions; signed policy + tamper-evident audit |
| **Compromised control plane / malicious insider** (integrity) | push a malicious "allow-all" policy | signing key in a **separate trust domain** (below); fail-secure floor; transparency log of policy pushes |
| **Curious / malicious AegionAI operator** (confidentiality) | read unredacted Serverless request content (live exposure today — content leaves; redaction is roadmap) | least-privilege operator access + access auditing; input-side redaction (roadmap); **in-VPC / air-gapped editions remove the exposure entirely** |
| **Supply chain** | tamper with our software or updates | signed, versioned releases; customers verify signatures (air-gapped pulls) |
| **Spoofed caller** | impersonate another agent to inherit its policy | verified per-agent credential — authoritative identity from the credential, not a self-asserted field |

**Critical aspects → how we address each:**

| Critical aspect | How we address it |
|---|---|
| **No-bypass / interception integrity** | *(roadmap-gated)* today's SDK interception is **cooperative** — an unwrapped tool or a raw call escapes it (CI tooling flags unwrapped tools as a weak compensating control). The **network sidecar (FR-1.5, roadmap)** makes coverage **non-bypassable** for in-boundary editions — that's the property that truly closes this; it is **not enforceable today.** |
| **Agent identity / anti-spoofing** | every managed agent presents a credential (issued at import); the controller derives the authoritative `(tenant_id, agent_id)` from the **verified credential**, never a self-asserted field (FR-10.3) |
| **Tenant isolation** | tenant context **enforced at the data layer, not just in app code**, with cross-tenant isolation tests and per-tenant encryption (Serverless — the only shipping edition, so this is where it matters most); single-tenant **deployment** isolation removes the surface entirely for Dedicated/Self-Managed (NFR-6) |
| **Data boundary / confidentiality** | redaction before egress; in-VPC / air-gapped editions keep content in-boundary; action content not persisted by default (§2.8, NFR-7) |
| **Policy & supply-chain integrity** | signed + versioned policy bundles; signed, licensed software releases; tamper-evident audit log (NFR-9) |
| **Fail-secure** | any validation failure denies (or degrades to the cached deterministic floor); never fails open (tenet 2) |
| **Denial-of-service / self-protection** | per-agent rate/abuse limits; controller backpressure and bounded queues; under overload the latency target degrades gracefully and the system fail-secures — it never opens |
| **Key & secret management** | the **policy-signing key lives in a separate trust domain** (HSM / offline root, dual-control to publish), so a compromised control plane cannot mint a valid malicious policy; KMS-encrypted stores; no long-lived secrets in plaintext |
| **Network security** | private subnets, PrivateLink / Private Service Connect, no public ingress (per edition, §2.4) |
| **IP / model protection** | compiled artifacts, encrypted weights, confidential-computing enclaves (§2.4) |

**Interception modes — how every action is captured:**

| Mode | What it is | Fits |
|---|---|---|
| **SDK decorator** | one wrapper per tool; calls `/v1/validate` before the tool body runs | fast pilots; Python agents |
| **Connector interceptor** | hooks the cloud's own tool-execution point — the **Bedrock action-group Lambda** or **Azure Function** that backs a tool — so the agent's own code is unchanged | Bedrock / Azure agents |
| **Network sidecar** | intercepts tool calls at the network layer; zero-code, framework-agnostic, **non-bypassable**, on-by-default and customer-controllable | in-boundary editions (Dedicated / Self-Managed) |

**On control-plane compromise.** Because (a) enforcement is local and fail-secure and (b) the **policy-signing key is held outside the control plane** (HSM / dual-control), a compromised control plane cannot make the checkpoint permit a malicious action — it can't produce a validly-signed policy, and every policy push is recorded in a **customer-visible transparency log** so an unexpected change is detectable. The residual risk is the signing key itself — hence the separate trust domain and rotation.

### 2.6 Scalability

We must scale along several independent dimensions; the approach to each. *(Maturity per capability is in the [PRD](../PRD.md) status columns, §7.)*

| Scale dimension | How we plan to achieve it |
|---|---|
| **Per-decision latency under concurrency** | stateless workers; async / non-blocking model calls; in-process policy + signature cache; the **in-process local tier** removes the network round-trip for the deterministic floor |
| **Throughput (actions / sec)** | horizontally-scaled, stateless controller; cheap deterministic checks short-circuit before any model |
| **More detection layers over time (without latency blow-up)** | a **parallel-gather scheduler over a cost-annotated DAG** — cheap-deterministic frontier first (a DENY short-circuits before models), then expensive models in parallel → latency = `max(models)`, not `sum` (FR-2.8) |
| **Model inference** | distilled CPU model on the hot path (scales cheaply, horizontally); heavier model only on the borderline subset (cascade); GPU autoscaling for escalation / offline re-scoring |
| **Fleet size (# agents)** | indexed per-agent policy lookup + caching; agent registry |
| **Tenants (# customers)** | tenant-scoped data and quotas (Serverless); single-tenant-per-deployment scaling (Dedicated / Self-Managed) |
| **Audit / telemetry volume** | writes are off the response path with **at-least-once delivery** (durable buffer + retry); hot recent-store + long-term archive; pluggable shipper |
| **Multi-region / multi-cloud** | data planes co-located with agents per region/cloud; control plane aggregates fleet-wide |
| **Policy propagation at scale** | signed, cached bundles + version-row invalidation → a change takes effect fleet-wide in **seconds**, not "up to the TTL" |

**Latency — targets vs today (be precise).** These are *targets*, not current measurements: deterministic path **≤ 500 ms p99** at load · fast-ML hot path **≤ 900 ms** · deep-model escalation bounded **≤ 2.5 s** · distilled local model **< 100 ms** (NFR-1/2). **Today (Serverless) it is ~0.6–1.2 s deterministic / ~0.9 s with ML**, because every call is a network round-trip and the pipeline runs sequentially. **Meeting the money-movement bar is gated on two roadmap items — the in-process local tier (removes the round-trip) and the parallel-gather scheduler (FR-2.8)** — which is the central technical risk to the synchronous-on-money-movement use case.

**Critical-path note.** Defense-in-depth is *double-gated*: each new detection layer needs (a) its phase wired (only `request` is live; `content` / `output` / `memory` are roadmap) **and** (b) the parallel-gather scheduler so layers run in parallel rather than stacking latency — plus, for non-`request` phases, the sidecar. The scheduler therefore ships **before** new layers go active.

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
- **Storage & audit:** action content is **not persisted by default**; only audit metadata is retained — a recent-decision store plus a long-term archive (the compliance system of record) — encrypted in transit and at rest, with configurable retention. Every decision is recorded to this tamper-evident trail with **at-least-once delivery** (durable buffer + retry).
- **Subprocessor:** the canonical detector is an **owned, self-hostable model** (AD-10); a hosted model is an **optional extra signal in Serverless only** (a subprocessor a CISO must vet). In-VPC / air-gapped editions self-host the model — **no external subprocessor on the detection path.** NFR-7.
- **Compliance & certifications:** **SOC 2 Type II (in progress)** is table-stakes, then ISO 27001 and (per vertical) HIPAA / PCI-DSS; the tamper-evident audit trail supports GDPR / EU AI Act evidence. **Certifications + redaction + a DPA make Serverless acceptable for most customers and many bank workloads** (only redacted, ephemeral content is processed, none retained by default); **residency-bound workloads use the in-VPC / air-gapped editions** — a certification does not override a data-residency mandate. NFR-8.
- **Moat vs. residency (the honest tension).** The cross-cloud threat-data flywheel is strongest in Serverless and weakest exactly where customers are most sensitive (Dedicated leaks only metadata; Self-Managed nothing). We resolve it by sharing **detections / signatures and opt-in model-gradient updates — never content — from in-boundary editions**, and those editions still *receive* improved models through the update channel. The flywheel runs on Serverless volume + a public-data base + opt-in federation; strict editions trade central learning for total residency, by design.

### 2.9 Operations

- **Infrastructure as code:** AWS CDK (stacks per concern — network/storage/compute/api/monitoring); see `cdk/` and best-practices §1.
- **Deploys:** scripted, milestone-tagged immutable Docker images (`build_and_push_image.py`), rollback by re-tagging (best-practices §5).
- **Feature gating & safe rollout:** capabilities ship behind flags and **shadow-then-enforce** gates — `CEDAR_ENABLED`/`CEDAR_SHADOW_MODE`, `ML_CLASSIFIER_ENABLED`/`ML_CLASSIFIER_SHADOW_MODE`, `TENANCY_V2_ENABLED`, `fail_secure`, `fail_fast`/`evaluate_all`. A detector runs in shadow (records signals, no verdict effect) until its precision/recall is signed off (FR-3.3), then is promoted.
- **Observability (NFR-10):** per-validator metrics, decision-source attribution, latency timing logs; the **signal store** powers the SOC console (per-session timeline, decision sources) and SIEM export.
- **SLOs:** enforcement availability ≥ 99.99% — meaning we always return a *safe* decision (today: **deny** when the controller is unreachable; once the in-process local tier ships: **keep enforcing the cached floor**), not "the agent keeps working." Control-plane availability 99.9% → 99.99%; latency budgets per §2.6.

### 2.10 Metering & Billing

**Principle: we charge per *governed agent* (tiered), not per action.** Metering per validation would tax coverage — customers would wrap fewer tools to cut cost, which is exactly the wrong incentive for a safety product. Per-agent pricing rewards full coverage and gives clean land-and-expand (the bill grows as the customer puts more agents under governance). What differs by edition is **who bears the infrastructure cost**:

| Edition | AegionAI charges | Who pays infrastructure | Notes |
|---|---|---|---|
| **Serverless** | per-agent subscription (tiered); **infra bundled in** | **AegionAI** (we host the multi-tenant cloud) | simplest to buy; our hosting cost is absorbed into the per-agent price |
| **Dedicated** | per-agent / per-fleet subscription **+ managed-service premium** | **Customer** — the data plane runs in their account, so their cloud bills them directly (they apply committed-spend discounts) | we charge for the software **and** operating it; opt-in GPU/self-hosted model is *their* infra cost, not our margin |
| **Self-Managed** | annual **license** (per-agent / per-fleet / site) **+ support** | **Customer** — their infrastructure **and** their operations | highest per-agent rate (offsets no recurring infra/ops involvement + IP exposure) |

So the **revenue basis is consistent (per governed agent) across editions**; only infra ownership shifts (we bear it in Serverless → customer bears it in Dedicated/Self-Managed). Metering reuses the audit pipeline (count of governed agents off the signal store) — no separate metering path. For **air-gapped Self-Managed** (nothing leaves), agent count for licensing is established by **periodic signed attestation** the customer exports, not live telemetry.

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
| AD-9 | **Fail-secure, signed policy, tamper-evident audit** | Never fail open; complete, tamper-evident decision trail | Today |
| AD-10 | **Self-hostable owned model as the canonical detector** | Proprietary API models can't run in a customer VPC / air-gapped env and aren't uniform across clouds; an owned, self-hostable model (off-the-shelf → fine-tuned) gives identical behavior in every edition. Proprietary models are an optional extra signal in Serverless only | Roadmap |

---

## 4. Open Architecture Questions

Tracked against the PRD's [Open Questions](../PRD.md#10-open-questions):
1. **Verified agent-identity mechanism** (AD-7) — signed per-agent token vs cloud workload identity; issuance/rotation.
2. **Sidecar feature parity** — how the network sidecar delivers the multi-phase (`content`/`output`/`memory`) coverage the SDK decorators provide.
3. **Distilled-local-model path** — packaging the < 100 ms in-process classifier (FR-3.12) for the in-VPC editions.

---
*This is the "how"; pair it with the [PRD](../PRD.md) ("what") and [vision.md](../vision.md) ("why"). Where this doc and the PRD's status column disagree, the PRD status wins.*
