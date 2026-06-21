# LLD 25 — Network Sidecar & In-Boundary Data Plane

> The **network sidecar** is the non-cooperative interception model for the in-boundary editions
> (Dedicated / Self-Managed). It runs **inside the customer's VPC** alongside their agents, captures
> agent actions at the network layer, and enforces the verdict from the policy engine (PDP) — which
> may run in-boundary (Dedicated/Self-Managed) or in AegionAI's cloud (Serverless hybrid).
> "AegionAI Guard" is the customer-facing brand; "Sentra" is the internal control-plane codename.

**Version**: 0.2 (draft for review — multiple options open per §15 Decision Register)
**Last Updated**: 2026-06-19
**Status**: Draft — design exploration; **no option is final**. Sections present 2–3 candidates with trade-offs.
**v0.2 changes**: added §1.3 brain/wires concept primer + PEP explainer; §1.4 metadata classification;
disambiguated serverless-edition vs serverless-hosted-agent; §3.4 multi-account brain placement;
§4.6 onboarding prerequisites/effort; tenets → list (+ progressive-onboarding); simplified triangle.
**Owner**: Shashank Gupta
**Prerequisites**:
[LLD 23 — Aegion Guard SDK](23-sentra-guard-sdk.md) (cooperative PEP, `/v1/validate` contract) ·
[LLD 18 — Deterministic Enforcement](18-deterministic-enforcement.md) ·
[LLD 19 — ML Threat Classifier](19-ml-threat-classifier.md) ·
[LLD 24 — Latency Optimization](24-latency-optimization.md) ·
[LLD 15 — Cross-Cloud Connectors](15-cross-cloud-connectors.md) ·
[LLD 17 — Validation Signal Store](17-validation-signal-store.md) ·
[ARCHITECTURE.md](ARCHITECTURE.md) §2.4 (editions), §2.7 (threat model)
**Maps to**: FR-1.5 (network sidecar), FR-1.7 (in-process local tier), FR-3.12 (distilled local model),
FR-3.13 (input-side redaction), FR-9.2/9.3 (Dedicated/Self-Managed), FR-10.3 (verified identity),
FR-11.1–11.3 (safe enforcement adoption), NFR-1/2/3/4/6/7/11.

## Table of Contents
1. Overview & Overall Approach
2. The PEP / PDP Split (the load-bearing decision)
3. Networking — how traffic flows in the customer VPC, and TLS
4. Customer Experience (the most important section)
5. Infrastructure — shipping binaries and model weights
6. IP Protection — code and weights
7. Security — posture and per-failure-point mitigations
8. Resilience
9. Scalability
10. Metering & Billing
11. APIs
12. Metrics & Instrumentation
13. Cloud-Specific Adjustments (AWS / Azure / GCP)
14. Coverage Reality (what the sidecar does and does not see)
15. Decision Register (open calls to settle)
16. Cross-References & Sources

---

## 1. Overview & Overall Approach

### 1.1 Purpose
Define the in-boundary data plane: the software that runs **inside the customer's cloud account/VPC**
to intercept agent actions at the network layer (zero-code, framework-agnostic, non-bypassable for
network egress) and enforce the policy engine's verdict — without the customer hand-wrapping every
tool with the SDK ([LLD 23](23-sentra-guard-sdk.md)).

### 1.2 Three reframes that shape every section
These correct common misconceptions and drive the options below:

1. **The "sidecar" is two components, not one.** The **PEP** (Policy Enforcement Point — capture +
   enforce) and the **PDP** (Policy Decision Point — Cedar + Sigma + distilled model + detectors)
   have opposite scaling and security profiles. We design them separately (§2).
2. **We do not tap *all* customer traffic.** Only **governed-agent** traffic is routed through the
   data plane (scoped egress, not a transparent account-wide tap). Everything else is untouched (§3).
3. **Network interception ≠ total coverage.** It captures the **network-egress subset** of actions
   (API/DB/tool/LLM calls, networked agent-to-agent). **In-process** tool calls and in-process
   multi-agent handoffs have no packet and need the SDK. Coverage = union of modes (§14).

### 1.3 Core concepts — the brain (PDP) and the wires (PEP)

Read this before the deep-dive; everything later assumes this model.

**Think of the system as a *brain* and *wires*.**

- **The brain = the PDP (Policy Decision Point).** A **running service** (a container/task fleet) that
  holds the policy engine (Cedar + Sigma), the distilled model, and the detectors, and answers
  **allow / deny** for each action. **The model and policies *always* run in the brain — never in a
  wire.** In the in-VPC editions the brain runs **inside the customer's cloud**.
- **A wire = a PEP (Policy Enforcement Point).** Whatever **carries an agent's action to the brain and
  enforces the answer.** There are **three wire types**, differing only in *how* they capture — the
  brain is identical behind all of them:

| Wire (PEP form) | What it is | Code change | Captures |
|---|---|---|---|
| **Network sidecar** | a proxy in the agent's outbound network path | **none** | network-egress actions |
| **SDK** ([LLD 23](23-sentra-guard-sdk.md)) | our library running **in-process inside the agent** (one wrapper per tool); on Lambda/Functions shipped as a **layer/extension** | small | in-process **and** network actions; effect-capture for rollback |
| **Connector** ([LLD 15](15-cross-cloud-connectors.md)) | a hook at the **cloud's tool-execution point** (Bedrock action-group Lambda / Azure Function) | **none** | platform-executed tool calls |

**How any PEP works (same four steps regardless of form):**
1. capture the outbound action + identity + destination (+ content if it can see it);
2. call the brain's `POST /v1/validate`;
3. **ALLOW** → let the action proceed; **DENY** → block it and return an error;
4. (optional) capture the result on ALLOW for rollback (effect-capture; SDK only).

**Why more than one wire if the brain is already in the customer's account?** Because **no single wire
reaches everything** (see §14): the network sidecar can't see *in-process* tool calls, in-process
multi-agent handoffs, content behind un-terminated TLS, or rollback handles — and it can't attach to a
**serverless-hosted agent** at all. The SDK/connector cover those gaps. **None of them run the model** —
they only feed the same brain. Which wire is even *possible* depends on where the agent runs:

| Agent hosting | Network sidecar possible? | Wire used |
|---|---|---|
| Pod / container (EKS / AKS / GKE / ECS-EC2) | yes | **sidecar** (or SDK) |
| Fargate / Container Apps / Cloud Run | explicit-proxy only (no eBPF / redirect) | explicit-proxy sidecar **or** SDK |
| **Lambda / Azure Functions** (serverless-hosted agent) | **no** | **SDK (layer/extension) or connector** |

> **Disambiguation — two unrelated uses of "serverless":**
> **Serverless-hosted agent** = the *customer's own* agent code running on serverless compute
> (Lambda / Azure Functions / Cloud Run); the customer builds and owns it. It can't host a sidecar
> container next to it, so its wire is the SDK or connector.
> **Serverless *edition*** = *our* hosting model (the brain runs in AegionAI's cloud, §1.5).
> Same word, unrelated things.

> **SDK-as-a-Lambda-layer / connector, concretely:**
> AWS Lambda **layers/extensions** load shared code into the function's runtime — we ship the SDK as
> that layer, the function calls our wrapper around each tool call, and the wrapper calls the brain.
> The PEP is then **our code inside the customer's Lambda process**, no separate container. The
> **connector** instead hooks the platform's tool-execution point (the action-group Lambda / Azure
> Function), leaving agent code unchanged.

### 1.4 What "metadata" means (and what is *content*)

The data-boundary promise ("only metadata leaves" for in-VPC editions) rests on this distinction:

| Tier | Examples | Leaves to AegionAI (in-VPC)? |
|---|---|---|
| **Identity** | `tenant_id`, `agent_id`, `session_id` | yes |
| **Decision** | verdict, deciding source, reason code, detector scores, versions, latency | yes |
| **Action** | tool name, destination host / endpoint, HTTP method, API operation | yes |
| **Network** | **source/destination IP**, SNI, port, byte volume, timing | yes (see IP note) |
| **Content** *(NOT metadata)* | parameter values, request / response bodies, **prompts** | **no — stays in-boundary** |

**Two honest caveats on "only metadata leaves":**
- **IP address is metadata and we need it** — destination IP/host → tool classification + egress
  allowlist; source IP → (weak) correlation + anomaly. But **an IP is "personal data" under GDPR**, so
  metadata is not automatically risk-free.
- **Some metadata can itself be sensitive** — a destination URL with query params, or a tool name that
  reveals business logic.

**"Only metadata leaves" describes the *uplink to AegionAI*, not what the engine sees.** The brain —
wherever it runs — **always gets the content it needs within its trust zone**:
- **In-VPC:** the brain has the **full prompt/request/response locally**; only metadata crosses to us.
- **Serverless:** the brain is in our cloud, so the prompt **does** go there — **redacted**. Redaction is
  **format-preserving** (masks secrets/PII, **keeps the attack-relevant text**) so injection/jailbreak
  detection still works. Redaction protects the *cross-boundary hop*; **it never starves the detector.**

### 1.5 Editions context (from ARCHITECTURE §2.4)
| Edition | Brain (PDP) runs | What leaves boundary | Primary PEP (wire) | This LLD |
|---|---|---|---|---|
| Serverless | AegionAI cloud | redacted content + metadata | SDK / connector | hybrid escalation only |
| **Dedicated** | **customer's cloud (managed by us)** | **metadata only** | **network sidecar** + SDK | **primary scope** |
| **Self-Managed** | customer's cloud (customer-operated) | nothing | network sidecar + SDK | **primary scope** |

> **"In-boundary" means in the customer's *cloud / org*, not necessarily the agent's VPC or account.**
> The brain can run in (i) the **same VPC** as the agent (localhost/mesh hop), (ii) a **different VPC in
> the same account** (VPC peering), or (iii) a **separate AegionAI-managed account inside the customer's
> AWS Org / Azure tenant / GCP org** (PrivateLink / PSC / peering) — often the cleanest for separation
> of duties. Connectivity per topology is detailed in §3.4.

### 1.6 Overall topology (block diagram)

```mermaid
flowchart LR
  subgraph CX["Customer Cloud / Org (BYOC)"]
    direction TB
    A1["Agent A (pod / container)"]
    A2["Agent B (pod / container)"]
    SVL["Serverless-hosted agent<br/>(customer-owned: Lambda / Func / Cloud Run)"]
    PEP["PEP wire — interceptor<br/>(sidecar / DaemonSet / SDK / connector)"]
    subgraph DP["Brain — Data Plane (PDP fleet, autoscaled)"]
      ENG["Policy engine: Cedar + Sigma"]
      ML["Distilled CPU model (FR-3.12)"]
      RED["Input-side redaction (FR-3.13)"]
      AUD["Audit store (in-boundary)"]
    end
    A1 --> PEP
    A2 --> PEP
    SVL -. SDK / connector .-> DP
    PEP -->|"/v1/validate"| DP
    PEP -->|enforce verdict| A1
  end

  subgraph AE["AegionAI Control Plane (per-cloud presence)"]
    POL["Policy authoring + signing (HSM)"]
    WTS["Signed weights + binary artifacts"]
    TEL["Telemetry / fleet view / SIEM export"]
    TLOG["Transparency log"]
  end

  DP <-->|"signed policy bundles + weights down;<br/>metadata + signals up<br/>via PrivateLink / PSC / mTLS"| AE
  POL --> TLOG
```

**What crosses the boundary (Dedicated/Self-Managed):** signed policy bundles + signed weights/binaries
**down**; de-identified metadata, decisions, trust signals, heartbeats **up**. **No raw content** leaves
(NFR-7). Self-Managed: nothing leaves; artifacts are side-loaded.

### 1.7 Design tenets
- **Fail-secure, never fail-open** — any failure denies, or degrades to the cached deterministic floor; it never silently permits.
- **Deny-by-default** — explicit allow only.
- **The data boundary is the customer's to set** — what leaves is an edition choice (§1.5).
- **Signed / verified everything** — policy, weights, binaries; tamper-evident audit.
- **On-by-default, customer-controllable** — disable per agent, per tool, or globally.
- **Progressive, low-friction onboarding** — zero-code and **monitor-first** by default; the
  security-driven friction (egress lockdown, fail-secure, CA install) is **opt-in and gradual**, never a
  day-one wall (§4). *Honest caveat: when ease and security genuinely conflict, security wins — so this
  is "minimize friction except where security demands it," not "easy at any cost."*

### 1.8 The trade-off triangle — and the scope of this LLD

A deployment can offer three properties; **you can pick at most two.** This defines the editions — it is
not a gap in the design:

```mermaid
flowchart TB
  A["(a) No customer infra"]
  B["(b) Data stays in boundary"]
  C["(c) Non-bypassable interception"]
  A --- B
  B --- C
  C --- A
```

**What each property means** (running example: a *refund agent* that calls a payments API to issue a $500 refund):

| Property | What it means — **✓** vs **✗** | The refund agent under the **in-VPC sidecar** |
|---|---|---|
| **(a) No customer infra** | Does AegionAI require a separate compute service (our brain/PDP) running in their account? **✓** = just a library/config, nothing new to run · **✗** = they provision and pay for our brain | **✗** — they run our brain as compute and pay for it (the price) |
| **(b) Data stays in boundary** | Does raw content (the prompt, the API body, the `$500`, the account #) leave their cloud for ours? **✓** = never leaves · **✗** = goes to our cloud (even if redacted) | **✓** — the refund body stays in their cloud; only metadata ("DENIED: over-limit") leaves |
| **(c) Non-bypassable** | Can the agent dodge the check (forgotten wrapper, raw call)? **✓** = still intercepted · **✗** = only if it goes through our wire | **✓** — network interception + egress lockdown; can't refund without passing |

**Which deployment keeps what** (no deployment gets all three):

| Deployment | (a) no customer infra | (b) data stays in boundary | (c) non-bypassable |
|---|---|---|---|
| **In-VPC sidecar — THIS LLD** | ✗ | ✓ | ✓ |
| Cloud-backed SDK / connector (Serverless) | ✓ | ✗ redacted content leaves | ✗ cooperative |
| Local-only SDK (in-process deterministic floor, no egress) | ✓ | ✓ | ✗ cooperative |
| Hosted egress proxy (SSE-style) | ✓ | ✗ content transits us | ✓ with egress lock |

**Key reads:**
- The **in-VPC sidecar is the only way to get (b)+(c) together** — full ML detection *and* content never leaving *and* non-bypassable — at the cost of (a). **This is why this LLD exists.**
- **Cloud-backed SDK/connector keeps only (a)** (content leaves *and* it's cooperative). The clean **(a)+(b)** is a **local-only SDK** — just a library that decides in-process on cached deterministic rules and never calls out (no ML, bypassable).

**Scope of this LLD: the (b)+(c) path only — infra in the *customer's* cloud (Dedicated / Self-Managed)**,
the residency-bound segment (banks, healthcare, government) where the sidecar is unavoidable. The
no-customer-infra alternatives below are **out of scope here** (a later doc); listed only to mark the boundary.

#### 1.8.1 The no-infra alternatives are deferred
The no-customer-infra rows in the matrix above — **cloud-backed SDK/connector**, **local-only SDK**, and
**hosted egress proxy** — plus **`ext_authz` on a customer's existing mesh/gateway** (Envoy `ext_authz` /
WASM / API-GW authorizer → our hosted brain; no *new* infra if they already run a mesh, keeps (a)+(c),
partial (b)) are the ways to govern *without* in-boundary compute. **All are deferred** — this LLD designs
the in-VPC (b)+(c) path; the no-infra family is a separate workstream tracked as **D8** (§15).

---

## 2. The PEP / PDP Split (the load-bearing decision)

The **PDP is heavy** (model weights = IP, CPU/RAM, must scale with QPS) → make it a **shared,
horizontally-scaled fleet per VPC/account**, not one-per-agent. The **PEP is light** (capture bytes,
call PDP, apply verdict) → it sits close to each agent. This split is assumed by all later sections.

### 2.0 Vocabulary — the two enforcement tiers (read first)
The engine has two kinds of check; the options below differ only in *where each runs*:

| Tier | What it is | Cost | Needs a model? |
|---|---|---|---|
| **Deterministic floor** | **Cedar policy** (tool allow/deny, parameter bounds, required-sequence) + **Sigma signatures** (known injection/jailbreak patterns, regex/string) + **rate/abuse limits** | µs–ms; same input → same output; explainable | **no** |
| **ML / deep tier** | **distilled CPU classifier** (catches *novel* attacks signatures miss, by semantics) + detection layers **D1–D7** | tens–hundreds of ms (inference) | **yes** |

**Baseline → target (so the options below are concrete):**
- **Today's shipped baseline (Serverless):** the *whole* engine runs in **AegionAI's cloud**; every guarded call is a network round-trip to us (SDK is the wire).
- **In-VPC baseline (2A):** a **shared PDP fleet inside the customer's cloud** runs *both* tiers; the PEP only forwards. Simplest first in-VPC step.
- **In-VPC target (2C):** the **floor runs in the PEP** (local, tens of ms, survives outage); the **ML/deep tier stays in the shared fleet** (one copy of the model, not per-agent). 2B is the only option that copies the model per agent — which we avoid.

### Option 2A — Thin PEP + shared PDP fleet (recommended baseline)
PEP forwards to a shared in-VPC PDP service (internal NLB / mesh service).
- **Pros:** one copy of weights (smaller IP exposure, cheaper), PDP scales independently, PEP is tiny
  and cheap to run per-agent, model hot-reload in one place.
- **Cons:** extra in-VPC network hop (PEP→PDP) adds latency; PDP is a shared failure domain; needs
  service discovery + mTLS between PEP and PDP.

### Option 2B — Fat sidecar (PEP + embedded PDP + weights per agent)
Each sidecar embeds the full engine and weights.
- **Pros:** no PEP→PDP hop (lowest latency, matches FR-1.7 in-process tier); no shared failure domain.
- **Cons:** N copies of weights = N× IP exposure + N× memory (distilled model × every agent); weight
  rollout touches every sidecar; expensive on serverless/limited-CPU; hardest to protect (§6).

### Option 2C — Hybrid: deterministic floor in PEP, ML/deep tier in shared fleet (recommended target)
The PEP runs the **deterministic floor only** (Cedar over a signed, cached policy bundle + Sigma + rate
limits) for tens-of-ms local allow/deny that also **keeps enforcing if the shared fleet or control plane
is unreachable** (FR-1.7). The **ML/deep tier stays in the shared PDP** (one model copy, not per-agent);
the PEP **escalates only borderline cases** to it. *(Aggressive sub-variant: also run the distilled model
in the PEP per FR-3.12 — deferred; conservative 2C keeps ML shared.)*

**How "borderline" is decided (deterministic routing, not a guess) — the exact PEP logic:**
```
v = cedar.evaluate(action)                          # tool / parameter / sequence
if v == DENY: return DENY                            # terminal — policy blocks
if sigma.match_blocking(action.content): return DENY # terminal — known-attack signature
escalate = ( policy.requires_ml(action.tool)         # tool flagged high-risk
          or action.has_untrusted_content()          # ingested doc / tool output / web page
          or sigma.soft_flag(action.content)         # matched a non-blocking "suspicious" rule
          or action.phase != "request" )             # content/output/memory need semantic detectors
return ESCALATE if escalate else ALLOW               # ESCALATE → shared PDP runs ML + D1–D7
```
**What each check means:**
- *Deterministic floor — gives a terminal verdict where it can* (full definitions in §2.0): **Cedar** — is
  the tool allowed for this agent, is the parameter in bounds (e.g. refund ≤ limit), was the required prior
  step done? **Sigma** — does the content match a *known*-attack pattern?
- *Escalation triggers — send to ML only when no terminal verdict AND one of these fires:*
  - **high-risk tool** (`policy.requires_ml`) — the policy marks this tool (e.g. money-movement, data
    export) to *always* get ML, regardless of the inputs.
  - **untrusted content** (`has_untrusted_content`) — the action carries data from an untrusted source (a
    retrieved document, a web page, another tool's output) where a *novel* injection could hide.
  - **soft-signal hit** (`sigma.soft_flag`) — a Sigma rule matched as *suspicious-but-not-conclusive* (flag,
    don't block) → worth a semantic second look.
  - **non-`request` phase** (`phase != "request"`) — the call inspects ingested content / emitted output /
    memory writes, which need the semantic detectors (D1–D7), not just rules.

The clear majority (allowed tool, in-bounds params, no untrusted content) is decided locally and never escalates.

- **Pros:** best latency for the common path; resilient (floor survives a PDP/control-plane outage);
  model centralized (IP + cost); escalation subset is small (matches LLD 24 "ML last").
- **Cons (each unpacked):**
  - **Two enforcement code paths to keep consistent** — the deterministic logic now runs in *two* places
    (PEP floor *and* the PDP's full pipeline, which also has Cedar+Sigma). If they diverge (PEP caches an
    older policy, or evaluates Cedar differently) the *same action can get different verdicts*. Mitigation:
    ship the **identical Cedar/Sigma evaluator** in both and version + content-hash the bundle.
  - **Cached-bundle freshness** — the PEP enforces from a **local cached copy** of the policy bundle, which
    can go **stale** when policy changes. The dangerous case is *stale-permissive* (policy was tightened, PEP
    still allows). This is the biggest risk of 2C and is designed out in **§2.1** below (push invalidation +
    force-central-on-tighten), not just bounded by TTL (Time-To-Live).
  - **Signature verification in the PEP** — the bundle is cryptographically **signed**, and the PEP verifies
    that signature against a trusted public key before loading it, so a compromised control plane or a
    **man-in-the-middle (MITM)** attacker **can't push an "allow-all" bundle**; unsigned/bad bundles are
    rejected (fail-secure). The signing private key is held in a **Hardware Security Module (HSM)** — a
    tamper-resistant device the key never leaves (AWS CloudHSM/KMS, Azure Key Vault Managed HSM, GCP Cloud
    HSM) — in a **separate trust domain** (an isolated account/role, *not* the control-plane app), so even a
    full control-plane breach cannot extract the key or forge a signature. Ties to threat **S4** (§7) + the
    transparency log.
  - **Partial coverage if PDP unreachable** — ML pauses; the floor keeps enforcing hard rules (acceptable,
    fail-secure).

**Lean:** start **2A** for simplicity (all freshness/signature/consistency handled once, centrally), evolve
to **2C** as FR-1.7 lands. **2B** only where a customer demands zero shared failure domain and accepts the
per-agent IP/cost penalty.

### 2.1 Policy freshness & cache invalidation (the stale-policy risk)
Only relevant to **2C** (the PEP holds a local policy cache). The risk is asymmetric:
- **Stale-permissive (dangerous):** policy was *tightened* (e.g. "block this tool after an incident") but the
  PEP still runs the old bundle and **ALLOWs** what should now be denied. This is the real security hole.
- **Stale-restrictive (benign):** old bundle blocks something now allowed — an availability annoyance,
  fail-secure in spirit, not a breach.

**We do not fetch per call**, and the always-current authority is the **in-VPC shared PDP** (in the
customer's own cloud), so a refresh is a cheap *local* hop — never a per-call round-trip to AegionAI.
Freshness is layered:

| Mechanism | What it does | Closes which gap |
|---|---|---|
| **1. Push invalidation (primary)** | the in-VPC PDP keeps a persistent channel to the control plane and receives new-bundle pushes; each PEP subscribes to the in-VPC PDP → `bundle vN available` reaches PEPs in ~sub-second–seconds | normal propagation lag |
| **2. Force-central-on-tighten** | on a *tightening*, the control plane flags the affected tools **"must escalate"** until **every** PEP acks vN; a stale PEP then **routes those actions to the always-current in-VPC PDP** instead of deciding locally | **the stale-permissive window** — tightening is effective *immediately*, before the floor cache catches up |
| **3. Short TTL backstop + reject-on-expiry** | TTL (Time-To-Live) bounds worst-case staleness if push is down; an expired bundle is rejected → PEP fails-secure (deny / force-central) | push-channel outage |
| **4. Version monitoring** | every PEP reports its bundle version on heartbeat (§12); alert if any lags the current version beyond the staleness SLO | silent drift / a stuck PEP |

**Net:** push is fast, **force-central makes a tightening take effect instantly**, TTL + fail-secure bound
the worst case — cache performance and outage-resilience **without** a stale-permissive hole and without
per-call fetches. *Open knob (D-fresh):* the exact staleness SLO and default TTL — see §15.

---

## 3. Networking — traffic flow in the customer VPC, and TLS

### 3.1 How an agent's traffic is made to go through us

**The goal, in one line:** when an onboarded agent calls a tool or API, that call must hit our checkpoint
(the **PEP**) **before** it runs. Two things make this hard: agents run on many platforms (Kubernetes, ECS,
EC2, Lambda…), and a **hijacked** agent may actively try to skip us. We solve it by borrowing two
battle-tested industry patterns, then adding one backstop.

#### Step 1 — attach a checkpoint to the agent (the "wire"). Two proven patterns:

- **Wire A — in-process auto-instrumentation (the *Datadog / New Relic* pattern).**
  - *What it is:* a small library loads **before** the agent's code (Java `-javaagent`, Python preload like
    `ddtrace-run`, Node `--require`) and automatically hooks the HTTP / tool-call libraries — so every call
    is captured with **no per-call code changes** (registration happens on the agent's "first line," for free).
  - *Why we'd use it:* the **richest** view — it sees **in-process** tool calls and content, and can capture
    results for rollback; lowest-friction to adopt (one startup flag).
  - *The catch:* it runs **inside the agent's own process**. A hijacked agent can spawn a subprocess, use an
    un-hooked path, or have the model write code that goes around it. **Great coverage, but NOT a hard
    security boundary** — this is the *cooperative* wire.
- **Wire B — transparent network capture (the *Istio / service-mesh* pattern).**
  - *What it is:* run the checkpoint as a **separate proxy next to the agent** and use OS-level rules
    (`iptables`) to **redirect all the agent's network traffic into it** — the agent doesn't cooperate or
    even know. On Kubernetes the proxy is auto-installed by an **admission webhook** (a hook Kubernetes calls
    when a new agent starts); on other platforms we attach it per-platform (§3.1.1).
  - *Why we'd use it:* the agent **can't bypass it** — capture is *outside* the agent's process, at the
    network level. This is the real **security boundary**.
  - *The catch:* it sees **network traffic only** (not in-process calls), and for encrypted traffic it needs
    §3.3 to read the body. The strong auto-install (admission webhook) is **Kubernetes-only**.

> We ship **both** wires and they compose: **Wire A** for rich in-process coverage and easy onboarding;
> **Wire B** for the can't-be-bypassed boundary. (Same as the SDK-vs-network-sidecar split in §1.3 — now
> named after the tools they're modelled on.)

#### Step 2 — make it a *guarantee*: the egress chokepoint (even Istio needs this)
- *What it is:* route the governed agents' outbound traffic so the **only way out is through our checkpoint**,
  and **deny by default** anything that arrives without a known, validated identity.
- *Why a hijacked agent can't skip it (the key point):* the chokepoint is **not something the agent chooses
  to call** — it's the **only network route out**, enforced by the **VPC route table** (controlled by the
  cloud admin, *not* the workload). The segment's route sends `0.0.0.0/0` to the egress firewall and there is
  **no direct internet route** (no IGW/NAT). So even a fully hijacked agent that ignores its wire and opens a
  raw socket to `evil.com` is **still routed to the chokepoint by the infrastructure** — it cannot route
  around it. *(How "deny" works there: the egress firewall is **default-deny** — only flows from an
  identified, validated governed agent to an allowed destination pass; anything else matches no allow-rule
  and is dropped.)*
- *What's ours vs. commodity (important — we are not reselling a firewall):* the **routing + a generic
  egress firewall (AWS Network Firewall / Azure Firewall / GCP Secure Web Proxy) is commodity plumbing the
  customer already has.** It only does coarse IP/domain allow-deny. **What we build is the agent-aware
  decision** (Cedar + Sigma + ML + identity + trust + rollback) that the chokepoint enforces — either we
  *are* the egress proxy the routing points to, or the customer's firewall **calls out to us for the
  verdict** (ext_authz). The firewall enforces; **we decide**.
- *Scoped, not blanket:* we do **not** route the whole account through us. Onboarded agents go into a
  **dedicated segment** (a subnet) whose route sends *its* egress through the checkpoint; all other traffic
  routes normally. → smaller blast radius, lighter security review, scoped latency/cost.

```mermaid
flowchart LR
  subgraph SEG["Governed segment (route table forces egress to chokepoint)"]
    AG["Agent + wire (A or B)"]
    PEP["PEP checkpoint"]
    AG --> PEP
  end
  PEP --> CHK["Egress chokepoint (commodity firewall)<br/>only route out; default-deny; asks us for verdict"]
  CHK -->|validated by us| NET["internet / tool / API"]
  CHK -. "unvalidated or unknown: DENY" .-> X["blocked"]
  AG -. "raw socket tries to skip wire - still routed here" .-> CHK
```

#### Step 3 — know the checkpoint is actually there (three-way reconciliation)
Three lists, each answering a different question:
- **Discovered** — every agent the **cloud APIs** say exists (pods / tasks / functions / instances) = *what is
  running.*
- **Onboarded** — agents registered in the **AegionAI control-plane registry** (from import, FR-7.7–7.9) =
  *what should be governed.*
- **Live check-ins** — wires that **announced themselves and heartbeat** = *what is actually guarded right now.*

*Registration mechanism:* on startup the wire makes an authenticated `POST /v1/register` (then periodic
`/v1/heartbeat`) call, authenticated by its **workload identity** (§3.5: SPIFFE SVID / IRSA token), carrying
`(tenant_id, agent_id, instance_id, version)`. No heartbeat ⇒ the guard is down or missing.

```mermaid
flowchart LR
  DISC["Discovered (cloud APIs): what is running"] --> R{reconcile}
  ONB["Onboarded (CP registry): what should be governed"] --> R
  LIVE["Live check-ins (register/heartbeat): actually guarded now"] --> R
  R -->|"discovered minus onboarded"| S["Shadow agents nobody onboarded - flag"]
  R -->|"onboarded minus live"| B["Guard missing or broken - alert; chokepoint denies"]
```
*Why it's necessary:* the CP registry tells us what to expect, the cloud APIs tell us what's really running,
and the check-ins prove the guard actually loaded — an onboarded agent whose wire failed to load looks fine
in the registry but is only caught by the missing check-in. *(On Kubernetes a **validating admission
webhook** can also reject an unguarded agent at deploy time; off-K8s we rely on detect + chokepoint-deny.)*

#### Why each step exists (one line each)
- **Wire** → so we can **see and act on** the action (and, with Wire A, see in-process calls).
- **Chokepoint + deny-by-default** → so **nothing reaches the outside without passing us**, even if a wire is missing.
- **Segment scoping** → so we inspect **only onboarded agents**, not the whole company's traffic.
- **Registration + reconciliation** → so we **know** which agents are guarded and catch the ones that aren't.

#### Catches (so no reviewer is misled)
- Wire A (in-process) is **bypassable by a hostile agent** → never rely on it alone as the boundary.
- The strong **auto-install (admission webhook) is Kubernetes-only**; other platforms are detect-fast +
  chokepoint-deny, not block-at-birth.
- The chokepoint needs the **customer to set the routing**, and **Lambdas must be VPC-attached** or they keep
  their own way out.
- Encrypted traffic: Wire B sees the destination but needs **§3.3** to read the body.
- The customer owns their cloud, so nothing is 100% against a malicious admin → we **attest** the
  webhook/routing are in place and alert on change (§12). Defense in depth, not an absolute.

#### 3.1.1 How Wire B attaches, per platform
A **variant** = the concrete way we physically insert the network-capture proxy into the agent's path. We
need several because **no single attach method works on every platform** (clouds restrict different things,
§13) — on a full K8s node you'd use 3B/3C, on Fargate you're forced to 3A, on Lambda you use the extension.

| Variant | How it attaches | Best where | Catch |
|---|---|---|---|
| **3A Explicit proxy** | set `HTTPS_PROXY` so the agent dials the PEP | **anywhere incl. Fargate** (no privilege) | cooperative-ish (app can ignore the env var) |
| **3B Transparent redirect** | `iptables`/eBPF redirect in the agent's network namespace | EKS-EC2 / AKS / GKE-Standard | needs privilege; **eBPF blocked on Fargate & GKE Dataplane V2** |
| **3C Mesh sidecar** | Envoy as a sidecar container (Istio-style) | EKS / AKS / GKE; Cloud Run / ACA multi-container | per-pod overhead; not for Lambda |

**Serverless agents (Lambda / Functions) can't host a sidecar** — they use an in-execution-environment
extension instead:

```mermaid
flowchart LR
  subgraph ENV["AWS Lambda execution environment (one per function)"]
    FN["Agent function code"]
    EXT["PEP = Runtime API proxy extension<br/>layer; intercepts events + egress"]
    FN -->|tool call| EXT
  end
  EXT -->|"validate, then forward on ALLOW"| API["tool / API"]
  EXT -. "DENY: block + return error" .-> FN
```

- **AWS Lambda → Runtime API proxy extension** (a layer; Rust/Go binary) that hooks the Lambda Runtime API to
  intercept/**block** the function's calls and route its egress — **no function code change** (AWS-documented).
- **GCP Cloud Run → 3C mesh sidecar** (Cloud Run supports multi-container).
- **Azure Functions → Wire A (SDK) or the connector** (no clean extension-proxy equivalent).

#### 3.1.2 Alternatives considered
- **eBPF / kernel capture (Cilium, Pixie):** capture at the kernel — most transparent, language-agnostic.
  *Catch:* needs privileged/kernel access → **blocked on Fargate & GKE Dataplane V2**.
- **Traffic mirroring (AWS VPC Traffic Mirroring / GCP Packet Mirroring):** copies traffic for **observation
  only**. *Catch:* can't block inline; Azure's vNet TAP is immature.
- **Ride the customer's existing egress proxy/firewall (§3.3, option 3T-D):** reuse what regulated orgs
  already run. *Catch:* depends on them already having it.

### 3.2 Traffic selection — deciding which connections to act on
A workload makes many outbound connections — some are agent *actions* we govern (a payment API call), many
are noise (package downloads, DNS, telemetry). "Traffic selection" answers, **per connection: (i) is this
from a governed agent, and (ii) is it an action we enforce on?** Four steps:

1. **Only governed agents reach the PEP at all.** We route *only* the agents we govern through the PEP (via
   3A/3B/3C). A workload the customer hasn't onboarded never touches us.
2. **Identify *who* is calling** — from signals the caller can't forge: a workload-identity credential
   (mTLS client cert / SPIFFE ID, §3.5), a pod label / Kubernetes service account, or — weakest, fallback
   only — source IP/subnet. This resolves to `(tenant_id, agent_id)` (FR-10.3; never a self-asserted field).
3. **Identify *what* it's doing** — by **destination** (the host/endpoint, e.g. `api.stripe.com/refunds`,
   matched against a known tool/API/LLM/DB list) and **protocol shape** (MCP JSON-RPC, OpenAI/Bedrock/Vertex
   API, SQL-over-wire, tool-call envelope).
4. **Decide whether to act** — matched governed tool → run the policy/floor (§2); a governed agent making an
   *unrecognized* call → configurable **monitor (log+allow)** by default, tightening to **deny** as
   confidence grows; non-governed traffic that slipped through → pass through untouched.

**Example:** a refund agent opens two connections — one to `api.stripe.com/refunds` (a recognized payment
tool → enforce policy) and one to `pypi.org` to fetch a library (not a governed action → pass through). The
PEP acts on the first and ignores the second.

#### 3.2.1 From tool names to endpoints — the binding, and two policy levels
Policy is written about a **tool** (`issue_refund`), but the PEP sees an **endpoint**
(`POST api.stripe.com/v1/refunds`). The customer does **not** type URLs — we resolve the **tool → endpoint
binding** from three sources:
- **Import-time introspection (primary):** a tool definition usually *includes its endpoint* — Bedrock
  action-group **OpenAPI schema** / Lambda ARN, the **MCP manifest** (`tool → server/endpoint`), OpenAI/Azure
  function schemas, the LangChain tool object. So `issue_refund` resolves to `POST /refunds` + the `amount`
  field automatically (FR-7.8).
- **Wire A observes it at runtime:** the in-process wire sits *at the tool boundary* and sees both the tool
  name **and** the outgoing HTTP call → it **tags the network call with the logical tool** and teaches the
  mapping to the network layer.
- **Learned association (Monitor mode):** observed traffic links a tool to the destinations it hits (FR-8.7).

This gives **two policy levels**, both supported:
- **Tool-level (logical)** — "`issue_refund` ≤ $1000." Needs the binding (introspection or Wire A).
- **Endpoint-level (physical)** — "allow `POST api.stripe.com/refunds`, deny other egress." Maps to traffic
  **directly, no binding needed** — this is **FR-2.9**, the primitive the network path / chokepoint enforces.

**The gap (be explicit):** a **generic "make an HTTP request" tool** where the agent builds the URL at
runtime *can't* be pre-bound. Wire A still tags it in-process; **network-only (Wire B / chokepoint) falls
back to endpoint-level rules (FR-2.9)** — coarser, but non-bypassable. Precise *tool-level* policy on such
tools needs Wire A.

### 3.3 TLS — what we must decrypt, and *who* decrypts it
Almost all agent egress is **HTTPS (encrypted)**. To check **parameters/content** (refund ≤ limit, injection
in the body) *someone* must **decrypt** the call; to check only destination/volume, nobody needs to.

**What "MITM" means, plainly, and why it's risky.** To decrypt HTTPS at a proxy, the proxy **pretends to be
the destination**: it presents its *own* certificate to the agent, signed by a **CA (Certificate Authority)
the agent is configured to trust**, decrypts, inspects, then re-encrypts onward to the real site. That's a
deliberate **man-in-the-middle (MITM)**. Three costs:
- **The CA private key is a crown jewel.** Whoever holds it can impersonate *any* website to those agents —
  if it leaks, an attacker can MITM the customer's traffic at will. A per-tenant CA key in the VPC is a
  serious thing to secure and rotate.
- **It breaks certificate pinning.** Some clients/SDKs "pin" the exact cert they expect and will **refuse**
  the proxy's substitute cert → the connection fails. Many cloud SDKs and security-sensitive APIs pin.
- **It's detectable.** The agent can tell it's talking to a proxy cert, not the real site.

**The realization that changes the calculus (verified across all three clouds):** large/regulated customers
usually **already run outbound TLS inspection** at a central egress point, *with their own internal CA
already trusted by every workload*:
- **AWS** — Network Firewall egress TLS inspection (decrypt → inspect → re-encrypt; NAT-GW + PrivateLink).
- **Azure** — **Azure Firewall Premium** TLS inspection (clients must trust the org Root/Intermediate CA).
- **GCP** — **Secure Web Proxy (SWP)** and/or **Cloud NGFW Enterprise** (HTTP CONNECT explicit proxy, L7
  inspection; certs via Certificate Authority Service + Certificate Manager).
- Or a third-party egress proxy (Squid SSL-bump, Zscaler).

In those environments **the CA and the MITM already exist and are the customer's responsibility** — so we
don't have to become a new CA; we **consume what they already decrypt** (3T-D).

| Option | Who decrypts | We see body? | CA liability |
|---|---|---|---|
| **3T-A We MITM (our CA)** | our PEP, our CA in the agent trust store | yes | **we hold the CA** — highest |
| **3T-B Metadata-only** | nobody (passthrough) | no — SNI/destination/volume only | none |
| **3T-C Hybrid: metadata + SDK for content** | the SDK, at the app layer (already plaintext) | yes, via SDK | none at the network layer |
| **3T-D Ride the customer's existing egress inspection** | the customer's egress firewall/proxy (their CA) | yes, from their decrypted feed | **customer's, not ours** |

**"Even inside the same infra, don't we still need the body (redacted)?"** Yes — to run parameter-bound
policy or content detection the PDP needs the **decrypted** body (redaction happens *after* decryption,
before anything leaves the boundary). The question is never "encrypted vs not" *inside* the boundary — it's
**who terminates the TLS**: our CA (3T-A), the app/SDK (3T-C), or the customer's existing egress proxy (3T-D).

**"With 3T-C we can't do anything" — not true.** With metadata + SDK, 3T-C still does **tool allow/deny,
egress allowlist, rate/abuse, volume anomaly, identity, cross-agent topology** at the network layer **and**
full content checks (parameter bounds, injection, DLP) **via the SDK** (which sees plaintext for free). The
*only* gap is reading the body of a call from an agent that has **neither SDK nor MITM** — exactly what 3T-A
or 3T-D fills.

**Never MITM our own channels** (PEP↔PDP, data-plane↔control-plane) — those are our mTLS with pinned certs (§3.5).

**Lean:** default **3T-B/3T-C** (metadata + SDK; no CA we own). Where a customer needs network-layer content
*without* the SDK, prefer **3T-D (ride their existing egress inspection)** over **3T-A (our own CA)** — most
regulated buyers already run egress TLS inspection, so we consume it rather than become a new CA liability.

### 3.4 Where the brain sits, and how things connect

**3.4.1 Agent ↔ brain (PEP → PDP), by brain placement.** "In-boundary" is the customer's cloud/org, not
necessarily the agent's VPC (§1.5). Three topologies, increasing isolation:

| Topology | Brain location | PEP → PDP connectivity | Notes |
|---|---|---|---|
| **Same VPC** | agent's VPC | localhost / cluster service / mesh | lowest latency; simplest; least isolation |
| **Different VPC, same account** | peer VPC | **VPC peering** / Transit Gateway / VNet peering | clean network separation |
| **Separate managed account** (recommended for Dedicated) | an **AegionAI-managed account inside the customer's Org/tenant/project** | **PrivateLink / PSC / Private Link** | best separation of duties; we operate our account; customer's agent account only exposes an endpoint |

**3.4.2 Brain ↔ control-plane (uplink to AegionAI).** Prefer **private** transport; fall back to public mTLS.
- AWS: **PrivateLink**. Azure: **Private Link**. GCP: **Private Service Connect**. All are **same-cloud
  only** — no cross-cloud private links exist, so the AegionAI control plane needs **presence in each
  cloud** (or accept public-internet mTLS egress).
- Self-Managed/air-gapped: **no uplink** — bundles/weights side-loaded; telemetry exported to the
  customer's own sink (their SIEM), optionally batched out manually.

```mermaid
sequenceDiagram
  participant Agent
  participant PEP
  participant PDP
  participant CP as Control Plane
  Agent->>PEP: outbound action over TLS
  PEP->>PEP: classify and run cached deterministic floor
  alt clear allow or deny locally
    PEP-->>Agent: enforce verdict in tens of ms
  else borderline - escalate per 2C routing
    PEP->>PDP: validate request
    PDP-->>PEP: decision reason source action
    PEP-->>Agent: enforce verdict
  end
  PEP-->>CP: async metadata off hot path
```

> **Escalation (per action) vs. refresh (per policy change) — two different "go to PDP" events, don't
> conflate them:** *Escalation* is decided **per request** by the §2C routing logic (high-risk tool /
> untrusted content / soft-flag / non-`request` phase) — **not** by any timer. *Bundle refresh* is the
> §2.1 freshness mechanism (push + TTL backstop) and happens **per policy change**, asynchronously, off
> the request path. A request never waits on a TTL.

### 3.5 Authentication & identity (every hop)
Every hop is **mutually authenticated** and uses **no static long-lived secrets**. Three trust boundaries:

**3.5.1 Agent → PEP (which agent is this?).** The PEP must bind each call to an authentic
`(tenant_id, agent_id)` — **never a self-asserted field** (FR-10.3). Sources, strongest first:
- **Workload identity (preferred):** the agent presents a **SPIFFE SVID** (Secure Production Identity
  Framework For Everyone — a short-lived X.509 cert, auto-rotated, issued by **SPIRE**) or a cloud workload
  identity (Kubernetes ServiceAccount token, AWS IRSA); the PEP verifies it via mTLS.
- **Platform identity:** pod label / service account from the orchestrator — trustworthy *because* the PEP
  was injected by admission control (§3.1).
- **Network identity (fallback only):** source IP/subnet — weak, supplements the above.

**3.5.2 PEP ↔ PDP (in-VPC, hot path) — mutual TLS.** Both sides present and verify certificates via
**SPIFFE/SPIRE**: SPIRE issues short-lived SVIDs to PEP and PDP; Envoy/our proxy consume them through the
**SDS (Secret Discovery Service)** API; certs auto-rotate and are never written to disk. This stops a rogue
in-VPC workload from impersonating the PDP (and feeding fake "ALLOW" verdicts) or impersonating a PEP.

**3.5.3 Data plane ↔ AegionAI control plane (the uplink).** Two phases:
- **Bootstrap / enrollment (once), with no pre-shared secret** — the data plane proves identity using
  **cloud workload identity federation (OIDC — OpenID Connect)**: **AWS IRSA** (IAM Roles for Service
  Accounts), **Azure Workload Identity**, or **GKE Workload Identity** mint a cloud-signed OIDC token, which
  the data plane exchanges with the control plane for a **per-tenant client certificate** + bootstrap token.
  (SPIRE can itself act as the OIDC issuer.) Optional **attestation** (TEE measurement, §6) gates this for
  high-assurance tenants.
- **Steady state — mTLS** with the per-tenant cert (auto-rotated). The control plane authenticates the data
  plane and binds it to `tenant_id`; the data plane authenticates the control plane via a **pinned** server
  cert **and** independently **verifies every policy bundle's signature** (§2C), so even a spoofed control
  plane can't push an "allow-all".

**3.5.4 Human / API access.** Console + management APIs use **OIDC + RBAC** (FR-8.5), federated to the
customer's IdP (Identity Provider).

```mermaid
sequenceDiagram
  participant DP as Data Plane
  participant Cloud as Cloud IdP
  participant CP as AegionAI Control Plane
  participant SPIRE
  DP->>Cloud: request workload-identity token
  Cloud-->>DP: signed OIDC token
  DP->>CP: present OIDC token plus optional attestation
  CP-->>DP: per-tenant mTLS cert plus bootstrap token
  SPIRE-->>DP: short-lived SVIDs auto-rotated
  DP->>CP: mTLS with cert and verify signed bundles
```

**Principles:** mutual auth on every hop; **no static long-lived secrets** (workload-identity federation +
short-lived SVIDs); auto-rotation; tenant binding from a **verified** credential, never a request field;
least-privilege per credential. *(Open: exact SVID lifetime + rotation cadence — D9, §15.)*

---

## 4. Customer Experience (the most important section)

Goal: **minimal touchpoints, monitor-first, reversible.** The customer should get an agent under
governance without rewriting it, and never be one config error away from an outage.

### 4.1 Integration model by interception choice
| Path | Customer does | Code change | Coverage | Best for |
|---|---|---|---|---|
| **SDK** ([LLD 23](23-sentra-guard-sdk.md)) | one wrapper per tool / framework hook | yes (small) | in-process **and** network actions, effect-capture for rollback | fastest start, in-process agents |
| **Connector** ([LLD 15](15-cross-cloud-connectors.md)) | point Bedrock action-group Lambda / Azure Function at us | no agent code | networked tool calls | Bedrock/Azure managed agents |
| **Network sidecar (this LLD)** | deploy data plane (Helm/Terraform) + route egress | **none** | network-egress actions, non-bypassable | scale, framework-agnostic, in-VPC editions |

### 4.2 Onboarding flow (network sidecar)

```mermaid
flowchart LR
  S1["1. Connect cloud account<br/>(read-only role)"] --> S2["2. Discover agents<br/>(FR-7.7)"]
  S2 --> S3["3. Deploy data plane<br/>(Helm / Terraform module)"]
  S3 --> S4["4. Seed starter policy<br/>Monitor mode (FR-8.4)"]
  S4 --> S5["5. Route a pilot agent's<br/>egress through PEP"]
  S5 --> S6["6. Observe (counterfactual<br/>FR-11.1) — no blocking"]
  S6 --> S7["7. Graduated enforce<br/>1%→10%→100% (FR-11.2)"]
```

### 4.3 Concrete touchpoints (what the customer actually configures)
1. **IAM/role**: a scoped role for the deploy automation + (Dedicated) a managed role we operate.
2. **Deploy artifact**: a **Helm chart** (K8s) or **Terraform module** (ECS/ACA/Cloud Run/VM) that
   stands up the PDP fleet + PEP. Pinned image digests; values for sizing, fail-mode, editions.
3. **Egress routing**: one of — set `HTTPS_PROXY` on the agent workload (3A), enable sidecar injection
   label (3C), or apply the netns redirect (3B). Plus the **egress-lockdown** SG/NSG/firewall rules.
4. **(Only if content visibility needed)** install the **proxy CA** into the agent's trust store (3T-A).
   We make this opt-in and per-destination, and loudly document the trade-off.
5. **Policy binding**: starter policy auto-seeded in **Monitor mode** (FR-8.4) so nothing is ever
   unpoliced and no wall of denials on day one.
6. **Console**: SOC dashboard shows discovered agents, decisions, counterfactual "what would block."

### 4.4 Day-2 experience
- **Promotion**: graduated rollout UI (FR-11.2) with auto-rollback on FP spike.
- **Override/appeal**: per-case "why blocked" + audited override (FR-11.3).
- **Off switch**: per agent / per tool / global disable (on-by-default but customer-controlled).
- **Upgrades**: ring rollout we operate (Dedicated) or a one-command bump (Self-Managed) — §8.

### 4.5 Effort / friction matrix
| Dimension | SDK | Connector | Network sidecar |
|---|---|---|---|
| Time-to-first-decision | minutes | ~1 hr | hours–1 day (infra deploy) |
| Code change | small | none | none |
| Infra to run | none (Serverless) | none | **data-plane compute in CX account** |
| Coverage | broadest | medium | network-egress (non-bypassable) |
| Latency | network RTT (Serverless) | RTT | local floor + in-VPC RTT |

**Principle:** lead onboarding with **SDK/connector** for instant value; introduce the sidecar when the
customer needs non-bypassable coverage or in-boundary data residency. They compose.

### 4.6 What it takes to onboard (prerequisites & effort)

**Prerequisites the customer must provide** (sidecar / in-VPC editions):
| Prerequisite | Why | Who |
|---|---|---|
| **Cloud account access** — a scoped deploy role (and, for Dedicated, a managed role we operate) | stand up the brain + PEP | customer cloud admin |
| **Compute budget in their account** — CPU by default; GPU only if opted in | run the brain (PDP) (§9) | customer (it's BYOC; they pay their cloud) |
| **Network-change capability** — set egress routing + **egress-lockdown** rules | route governed agents through the PEP and make it non-bypassable (§3.1, §7.3) | customer network/platform team |
| **(Optional) trust-store access** — install proxy CA | only if content visibility via MITM is wanted (§3.3) | customer — opt-in |
| **Identity source** — pod identity / mTLS / SPIFFE | verified agent identity (FR-10.3) | customer platform |

**Onboarding steps by edition:**
| Step | Serverless (no infra) | Dedicated (managed in-VPC) | Self-Managed (air-gapped) |
|---|---|---|---|
| 1. Connect | API key | read-only discovery role + managed account/VPC | offline package + signed license |
| 2. Discover agents | import (FR-7.7) | import (FR-7.7) | manual inventory |
| 3. Deploy brain | nothing (we host) | Helm / Terraform (we operate) | customer runs Helm / Terraform |
| 4. Route a wire | add SDK / connector | route pilot agent egress to PEP | route + side-load weights |
| 5. Seed policy | Monitor mode (FR-8.4) | Monitor mode | Monitor mode |
| 6. Observe | counterfactual (FR-11.1) | counterfactual | counterfactual (local) |
| 7. Enforce | graduated (FR-11.2) | graduated | graduated |

**Rough effort / time-to-value:**
| Edition | First decision (monitor) | First enforce | Heaviest task |
|---|---|---|---|
| Serverless | minutes (SDK) / ~1 hr (connector) | same day | none (we host) |
| Dedicated | hours–1 day | days (after observe period) | provisioning compute + egress routing |
| Self-Managed | 1–3 days | days–weeks | customer-run deploy + air-gap bundle handling |

**The friction-minimizing path (ties to the progressive-onboarding tenet §1.7):** start any customer on
**SDK/connector in Monitor mode** for instant, zero-risk value; stand up the sidecar in parallel; never
ask for egress-lockdown or CA install until the customer has already seen value and chosen to enforce.

---

## 5. Infrastructure — shipping binaries and model weights

### 5.1 Image build
- **OCI image**, multi-stage → **distroless / `scratch`** base, **single static Rust binary**, no shell,
  no package manager, stripped symbols. Aligns with "lightweight Rust/Go" (ARCHITECTURE tech stack).
- **Signed** with cosign/sigstore; **SBOM** attached; base pinned by digest; admission control verifies
  signature before run.
- Separate images: **PDP** (engine+runtime), **PEP** (thin proxy + cached floor), optional **redaction**.

### 5.2 Weights packaging — 3 options
| Option | Mechanism | Pros | Cons |
|---|---|---|---|
| **5A Baked into image** | weights as image layer | one artifact; simplest; works air-gapped | huge image; rebuild to rotate; weights sit in registry (IP) |
| **5B Pulled at startup (recommended)** | image has no weights; fetch **signed** weights from artifact store over mTLS, verify, cache on **encrypted volume** | small image; rotate without rebuild; **gate delivery on attestation** (§6); air-gap via side-load | startup dependency; needs artifact store + key mgmt |
| **5C Streamed/lazy** | memory-map from object store | minimal disk | runtime dependency on object store; complexity; weak air-gap |

**Lean:** **5B** (with **5A side-load** for air-gapped Self-Managed). Format: **ONNX (ONNX Runtime)** or
GGUF/safetensors (candle) for CPU; distilled model is tens–hundreds of MB so pull-at-startup is cheap.

### 5.3 Delivery & registry strategy
- **Dedicated**: we operate; images mirrored to a registry the customer's account can pull (ECR/ACR/AR)
  via a pull-through cache or replicated repo; weights from our signed artifact store via private link.
- **Self-Managed**: **signed bundle** (image tarball + weights + policy) delivered out-of-band; verified
  by signature against a key shipped via a separate trust channel.
- **Versioning**: semver on binary; content-hash on weights and policy bundles; **decouple** so a
  weight/policy update is **data (hot-reload)**, not an image swap (§8.2).

### 5.4 Bootstrap/enrollment flow

```mermaid
sequenceDiagram
  participant DP as Data Plane (PEP/PDP)
  participant CP as Control Plane
  participant KMS as KMS/HSM
  DP->>CP: enroll (instance identity doc / workload identity)
  CP->>DP: per-tenant mTLS cert + bootstrap token
  DP->>CP: (optional) attestation evidence (§6)
  CP->>KMS: authorize weight-decryption key release
  KMS-->>DP: wrapped key (to TEE or memory)
  CP-->>DP: signed policy bundle + signed weights ref
  DP->>DP: verify signatures, decrypt weights, warm model
```

---

## 6. IP Protection — code and weights

**Hard truth:** in an environment the customer fully controls (root, memory dumps, disk snapshots), you
**cannot guarantee** code/weights secrecy. You raise cost and/or use hardware TEEs. Strategy = **tier the
IP** + optional **confidential computing**.

### 6.1 IP tiering (do this regardless)
- Ship only the **distilled** model in-boundary (a lossy derivative — lower value if leaked).
- Keep **teacher model, training data/pipeline, Sigma-rule authoring, red-team corpus** in our cloud.
- Plan for the distilled model to possibly leak; ensure that is survivable (the moat is the *pipeline*
  + cross-customer signal flywheel, not the static weights — see STRATEGY §3).

### 6.2 Technical protection — 3 options
| Option | Mechanism | Protection | Cost / constraint |
|---|---|---|---|
| **6A Encrypted-at-rest + runtime decrypt** | weights encrypted; key released at startup (KMS), decrypted in memory | deters disk snapshot, registry scrape | **key + plaintext in RAM** → root can dump; weak vs determined CX |
| **6B Confidential computing (TEE)** | run PDP in AMD SEV-SNP / Intel TDX VM or Nitro Enclave; **attest** before **secure key release** (SKR); memory encrypted from host | strong — even host/root can't read memory | **CPU TEE on all 3 clouds; GPU TEE only Azure (preview)**; instance-type constraints (collides with §9 "no compute"); ops complexity; attestation maturity varies (GCP weakest) |
| **6C Obfuscation / split-model** | obfuscated binary; keep last layers/critical head server-side, run trunk in-boundary | marginal (6C-obfusc) / strong (6C-split, but re-adds egress) | obfuscation buys little vs experts; split re-introduces a network hop + content egress |

**Lean:** **6A as the floor everywhere**, **6B (CPU TEE)** as the opt-in "high-assurance IP protection"
tier for regulated buyers who *also* want it (note: they often care more about *their* data staying in
than *our* weights — the boundary already gives them that). Use Nitro Enclave (AWS), Confidential
VM/Container (Azure — most mature), Confidential VM (GCP, CPU-only). **Do not** promise GPU-TEE
cross-cloud. Combine with 6A tiering always.

### 6.3 Attestation + secure key release (6B detail)
Boot → measure (vTPM/PCRs or enclave measurement) → present evidence to control plane / Azure Attestation
/ Nitro attestation → control plane authorizes KMS to release the **weight-decryption key** *only* to an
attested, unmodified data plane. A tampered image fails attestation → no key → no weights → fail-secure.

---

## 7. Security — posture and per-failure-point mitigations

### 7.1 Posture summary
The data plane is a high-value asset in someone else's environment, on the critical path. Posture:
least-privilege, signed-everything, fail-secure, defense-in-depth, separate trust domains, no raw-content
retention.

### 7.2 Threat / failure-point matrix (every point + mitigation)
| # | Failure / threat point | Impact | Mitigation |
|---|---|---|---|
| S1 | **MITM CA private key stolen** (3T-A) | attacker impersonates any site to agents | avoid by default (3T-C metadata-only); when used: per-tenant short-lived CA in **KMS/HSM**, never egress, scoped to named destinations, rotation, monitoring |
| S2 | **Agent bypasses PEP** (direct socket) | unguarded action | **egress lockdown** (SG/NSG/firewall force-through), CI flags unwrapped tools, anomaly on unexpected direct egress; default-deny governed-agent egress not via PEP |
| S3 | **PEP/PDP compromised** (elevated caps) | tamper verdicts, read content | drop caps (seccomp/AppArmor); NET_ADMIN only where unavoidable; TEE (6B); minimal image (§5.1) |
| S4 | **Malicious/compromised control plane** pushes "allow-all" | mass permit | **policy-signing key in separate trust domain (HSM/dual-control)**; PEP verifies signature; **transparency log** of pushes; fail-secure floor (a CP can't forge a valid bundle) |
| S5 | **Weight/binary supply-chain tamper** | backdoored detection | cosign signatures + SBOM; attestation-gated key release (6B); pinned digests; admission control |
| S6 | **DoS on `/v1/validate` or proxy** | latency blowup / outage | per-agent rate/abuse limits, bounded queues, backpressure; **degrade to cached floor**; never fail-open |
| S7 | **Plaintext content exposure** (post-TLS-termination, or to AegionAI operator) | confidentiality breach | **in-boundary redaction (FR-3.13)**, no content retention (NFR-7), least-privilege operator + access audit; in-VPC editions keep content local |
| S8 | **Tenant cross-talk** (shared PDP fleet) | data leak across teams | strict `tenant_id` scoping (FR-10.1); per-tenant cert; optionally per-tenant PDP for hard isolation |
| S9 | **Identity spoofing** (agent claims another's id) | privilege escalation | verified identity from mTLS/SPIFFE, never self-asserted field (FR-10.3) |
| S10 | **Stale/rolled-back policy** served | enforce old rules | bundle version + freshness check; reject expired bundles; alert on staleness |
| S11 | **Update channel MITM** | bad image/weights | mTLS pinned; signature verify; private link where available |
| S12 | **Audit tampering** | lost forensics | tamper-evident (hash-chained) audit, written off the hot path (FR-6.1) |

### 7.3 Non-bypass is conditional (state it plainly)
The sidecar is "non-bypassable" **only with egress lockdown enforced**. Without it, it is a strong
default, not a guarantee. This must be a documented deployment requirement and verified at onboarding.

---

## 8. Resilience

### 8.1 Failure-scenario matrix
| Scenario | Without mitigation | Mitigation | Resulting behavior |
|---|---|---|---|
| **PDP unreachable** (PEP up) | escalations fail | **cached deterministic floor (FR-1.7)** keeps enforcing; ML pauses | agents keep running on hard rules (secure) |
| **PEP down** (3A explicit proxy) | agent egress fails (proxy unreachable) | health-checked PEP, multiple replicas, connection retry; fail-mode config | fail-secure (block) or degrade per `fail_mode` |
| **PEP down** (3C sidecar) | pod can't egress | readiness gating, restart, keep old until new healthy | brief local block; recovers |
| **Control plane unreachable** | no policy/weight updates, no telemetry uplink | run on last **signed cached** bundle+weights; buffer telemetry; never open | enforcement continues on cached state |
| **Bad image rollout** | fleet-wide outage | **ring + canary rollout, auto-rollback on SLO breach**, signed digests | blast radius capped to canary |
| **Bad weights/policy** | mass FP or FN | **shadow → graduated promote (FR-11.2)**, auto-rollback; data hot-reload independent of binary | revert in seconds, no restart |
| **Overload** | latency blowup | bounded queues + backpressure + fail-secure; autoscale | graceful degrade, never open |
| **Clock/cert expiry** | mTLS breaks | cert auto-rotation, expiry alerts, grace window | uninterrupted |

### 8.2 Update strategy (decouple data from binary)
- **Hot-reload** (no restart): policy bundles, Sigma rules, weights, thresholds, fail-mode.
- **Binary update** (restart): PEP/PDP image — done via **blue-green at the proxy** + ring rollout
  (canary VPC/agent slice → wider) + **auto-rollback** on latency/error/FP SLO breach.
- **Failure posture during restart:** cached floor (FR-1.7) keeps enforcing so a restart neither opens
  nor stalls the agent. Connection draining + readiness gates avoid dropped calls.

```mermaid
flowchart LR
  V1["v1 PEP/PDP (serving)"] --> CAN["canary slice on v2"]
  CAN -->|SLOs green| RAMP["ramp v2 fleet-wide"]
  CAN -->|SLO breach| RB["auto-rollback to v1"]
  RAMP --> DONE["v2 serving; drain v1"]
```

### 8.3 SLOs (inherited)
Enforcement availability (local, fail-secure) ≥ 99.99% — always returns a *safe* decision; control-plane
99.9%→99.99%. Latency budgets per [LLD 24](24-latency-optimization.md) / NFR-1/2.

---

## 9. Scalability

### 9.1 Scaling model
- **PDP fleet**: stateless workers behind an internal LB; **horizontal autoscale** on QPS / queue depth /
  CPU; distilled CPU model scales cheaply and horizontally (ARCHITECTURE §2.6). GPU only for
  escalation/offline re-scoring, **opt-in**.
- **PEP**: scales with the agent workload (per-pod/per-node); near-zero marginal cost.
- **Cascade**: cheap deterministic floor short-circuits; ML runs only on the borderline subset
  (LLD 24 "ML last"); FR-2.8 parallel-gather bounds latency as layers grow.
- **Multi-region/cloud**: data planes co-located with agents per region/cloud; control plane aggregates
  fleet-wide (and must be present per cloud for private connectivity, §3.4).

### 9.2 Capacity & the "no compute on CX side" problem (Q8)
- **Never require GPU for baseline** — distilled CPU model is the default (FR-3.12).
- **Degradation tiers** when CPU is also constrained:
  1. deterministic floor only (Cedar+Sigma) — cheap, always available;
  2. escalate borderline to **control plane / Serverless** for the heavy model (re-adds egress — a
     data-boundary trade-off the customer must accept);
  3. shadow/skip ML (reduced efficacy) with alerting.
- **No in-VPC compute at all → route the account to the Serverless edition** (SDK→our cloud) or a
  deterministic-only Dedicated install. Architecture↔GTM coupling: "no compute" picks an edition, it
  doesn't break the product.
- **Sizing**: requests/limits per QPS; if the customer caps resources, **backpressure + fail-secure**,
  never crash.

---

## 10. Metering & Billing

Billing basis (STRATEGY/ARCHITECTURE): **per governed agent (tiered), never per-action**; infra bundled
for Serverless, **customer-borne** for Dedicated/Self-Managed; we charge software subscription + managed
fee, **not** infra margin.

### 10.1 The hard part: metering when the data plane runs in the customer's account
We can't read their cloud bill; we meter **governed agents** and decision volume from our own telemetry.

| Option | Mechanism | Pros | Cons |
|---|---|---|---|
| **10A Control-plane metering** | data plane reports per-agent active counts + decision volume (metadata) to CP | accurate, central, tamper-evidenced | needs uplink (not air-gapped) |
| **10B Signed local meter (air-gapped)** | data plane keeps a **hash-chained, signed** usage ledger exported periodically | works offline / Self-Managed | reconciliation lag; trust the export |
| **10C License entitlement** | signed license caps N agents; enforced locally | simple; offline | coarse (entitlement, not true usage) |

**Lean:** **10A** for Dedicated (uplink exists), **10B + 10C** for Self-Managed/air-gapped (signed ledger
+ entitlement license). Meter = **distinct governed `agent_id`s active in a period** + decision counts;
GPU opt-in is *their* infra cost, surfaced for transparency, not our line item.

### 10.2 Tamper-resistance
Usage ledger is hash-chained and signed by the data plane's enrolled key; the control plane reconciles;
material drift between license entitlement and reported usage raises a commercial flag, not an outage.

---

## 11. APIs

Grouped by channel. (Contracts sketched; full schemas to follow the chosen options.)

### 11.1 PEP ↔ PDP (in-VPC, hot path, mTLS)
- `POST /v1/validate` — action validation (reuse [LLD 21/23](21-api-inventory-for-ux.md) contract);
  `phase ∈ {request, content, output, memory}`; body = metadata or redacted content.
- `POST /v1/effect` — effect-capture handle on ALLOW path for rollback (best-effort at network layer; see
  §14 / ARCHITECTURE "effect capture").
- `GET /healthz` `/readyz` — liveness/readiness for rollout gating.

### 11.2 Data plane ↔ Control plane (management, mTLS / private link)
- `POST /v1/enroll` — bootstrap identity → per-tenant mTLS cert + token (§5.4).
- `POST /v1/attest` — attestation evidence → authorize key release (6B).
- `GET /v1/policy/bundle?since=` — pull signed, versioned policy bundle (deterministic floor).
- `GET /v1/weights/manifest` + signed artifact fetch — model weights ref + integrity.
- `POST /v1/telemetry` (batch) — metadata, decisions, signals (off hot path, no content).
- `POST /v1/usage` — signed metering ledger (§10).
- `POST /v1/heartbeat` — liveness + version + coverage stats (no-data detection, §12).

### 11.3 Admin / management plane
- Agent discovery/import (FR-7.7–7.9), policy CRUD + bind (FR-8.x), fail-mode + off-switch config,
  graduated-rollout control (FR-11.2), override/appeal (FR-11.3), SIEM/SOAR export config (FR-6.7).

### 11.4 API design notes
Versioned (`/v1`); idempotent telemetry/usage with client-side buffering + retry; deny-by-default on any
validate error; all admin actions audited.

---

## 12. Metrics & Instrumentation (exhaustive governance)

### 12.1 Per-decision (the governance record)
decision (ALLOW/DENY/REDACT/HOLD/QUARANTINE), **deciding source** (trust/policy/Sigma/ML/D1–D7/abuse),
reason code, `tenant_id`, `agent_id`, session, tool/destination, phase, **latency per stage**, detector
scores, policy+bundle+weights+binary versions, edition, fail-mode. (Content only in-boundary; metadata up.)

### 12.2 Coverage & efficacy (the "is it working" view)
- enforcement coverage (% guarded actions validated pre-exec, target 100%);
- **shadow/counterfactual** would-block counts + FP rate per policy/detector/agent (FR-11.1);
- missed-attack proxy via red-team replays; detector precision/recall/F1 (gates releases);
- per-agent decision-volume baseline → **no-data / silence detection** (PEP down vs bypassed vs idle);
- **synthetic canary** action success (end-to-end path health).

### 12.3 USE / RED (operations)
PDP CPU/mem/queue-depth/saturation; request rate, error rate, duration histograms (p50/p95/p99);
autoscale signals; cache hit-rate (deterministic floor); model inference time; backpressure events.

### 12.4 Distributed tracing & audit
Trace keyed to **request-id correlation (FR-7.5)** extended to PEP→PDP→CP; tamper-evident audit off the
hot path (FR-6.1); SIEM/SOAR/ITSM export (FR-6.7).

### 12.5 Fleet & drift
Per-VPC/region fleet health; version skew across the fleet; model/score drift vs baseline
(FR-3.11 metadata-only); policy-staleness alerts.

---

## 13. Cloud-Specific Adjustments (AWS / Azure / GCP)

### 13.1 Feasibility matrix
| Capability | AWS | Azure | GCP |
|---|---|---|---|
| K8s sidecar PEP | EKS ✓ | AKS ✓ | GKE ✓ |
| Serverless container sidecar | **Fargate**: sidecar ✓ but **no eBPF / NET_ADMIN / GPU**; **Lambda**: no sidecar | **Container Apps / App Service**: sidecar ✓; **Functions**: no sidecar | **Cloud Run**: multi-container sidecar ✓ (≤10, shared netns); GKE ✓ |
| Transparent redirect (iptables) | EC2 nodes ✓; Fargate ✗ | AKS nodes ✓ | GKE Standard ✓ |
| **Custom eBPF interception** | EC2 ✓; **Fargate ✗** | AKS (Cilium managed) — limited | **GKE Dataplane V2 forbids custom eBPF** |
| Explicit proxy (HTTPS_PROXY) | ✓ (only option on Fargate) | ✓ (Container Apps via UDR → Azure Firewall) | ✓ (note: GKE proxy `httpsProxy` field needs `http://` scheme) |
| **Serverless-agent interception** | **Lambda Runtime API proxy extension** (layer, no code change) | Functions → SDK/connector | Cloud Run → 3C mesh sidecar |
| **Egress TLS inspection to ride (3T-D)** | **Network Firewall** egress TLS inspection | **Azure Firewall Premium** (client trusts org CA) | **Secure Web Proxy** / **Cloud NGFW Enterprise** (CAS + Cert Manager) |
| **Workload identity (auth, §3.5)** | **IRSA** (IAM Roles for Service Accounts) | **Entra Workload Identity** federation | **GKE Workload Identity** |
| Traffic mirroring (observe) | VPC Traffic Mirroring **GA** | vNet TAP **Preview**, limited regions, no filtering | Packet Mirroring **GA** |
| Private CP connectivity | **PrivateLink** | **Private Link** | **Private Service Connect** (all same-cloud only) |
| CPU confidential computing | **Nitro Enclaves** (no GPU TEE) | Confidential VM/Containers (most mature) | Confidential VM (AMD SEV, weak attestation) |
| GPU confidential computing | ✗ | **Preview (H100)** | ✗ |

*All rows verified against vendor docs / current write-ups (June 2026); sources in §16. Cross-cloud
constant: **SPIFFE/SPIRE** is the portable workload-identity + mTLS standard (Istio, Cilium, Linkerd all
build on it), so PEP↔PDP mTLS (§3.5.2) is identical on all three clouds; only the **bootstrap** identity
provider differs (IRSA / Entra WI / GKE WI).*

### 13.2 Per-cloud implications
- **AWS**: full power on **EKS-EC2/ECS-EC2** (redirect/eBPF/mesh all viable; Nitro Enclave for 6B).
  **Fargate forces explicit-proxy (3A) only** — no transparent capture, no eBPF, no NET_ADMIN. **Lambda
  agents** → use the **Lambda Runtime API proxy extension** (3.1.1) or SDK/connector, never a sidecar.
  Auth bootstrap via **IRSA**; ride **Network Firewall** egress TLS inspection for 3T-D.
- **Azure**: strongest **confidential** story (6B); **Container Apps/App Service** support sidecars, egress
  controlled via **UDR → Azure Firewall** (note: Container Apps' Envoy edge terminates TLS at its boundary);
  AKS+Cilium for L7. Auth via **Entra Workload Identity**; ride **Azure Firewall Premium** for 3T-D. vNet
  TAP too immature → don't build on mirroring here.
- **GCP**: Cloud Run multi-container makes the **mesh-sidecar (3C)** clean for serverless-ish workloads;
  **GKE Dataplane V2 blocks custom eBPF** → use Envoy sidecar / explicit proxy. Auth via **GKE Workload
  Identity**; ride **Secure Web Proxy / Cloud NGFW Enterprise** for 3T-D. CVM is CPU-only with weaker
  attestation (temper 6B claims).

### 13.3 Portability principle
Pick mechanisms available on **all three**: **explicit proxy (3A)** + **mesh sidecar (3C)** as the
portable core; **transparent redirect/eBPF (3B)** as an EC2/AKS/GKE-Standard optimization only. Never
make the baseline depend on Fargate-forbidden or GKE-DPv2-forbidden features.

---

## 14. Coverage Reality (what the sidecar sees / misses)
| Action type | Network PEP | Needs SDK/connector |
|---|---|---|
| Agent → external API / DB / tool (network) | ✓ | — |
| Agent → LLM (network, TLS) | ✓ (metadata; body only if 3T-A) | content via SDK |
| Agent → agent over network (A2A / bus) | ✓ | — |
| **In-process tool call** (local fn/subprocess/file) | ✗ (no packet) | ✓ |
| **In-process multi-agent handoff** (LangGraph/CrewAI in one process) | ✗ | ✓ |
| **Effect-capture for rollback** (side-effect handle) | ✗ (sees bytes, not app handles) | ✓ |

**Coverage = union of modes.** Sidecar = non-bypassable for **network egress**; SDK = in-process +
effect-capture. Sell them as complementary, not either/or.

---

## 15. Decision Register (open calls to settle)
| # | Decision | Options | Lean |
|---|---|---|---|
| D1 | PEP/PDP topology | 2A thin+shared / 2B fat / 2C hybrid | **2C** (2A first) |
| D2 | Interception placement | host-agnostic **egress chokepoint** (base) vs per-workload **adapter** (3A explicit / 3B redirect-eBPF / 3C mesh / Lambda extension) | **chokepoint as the general base; adapters for richer coverage where available** |
| D3 | TLS handling | 3T-A MITM / 3T-B metadata-only / 3T-C hybrid | **3T-C** |
| D4 | Weights packaging | 5A baked / 5B pull-at-startup / 5C streamed | **5B (+5A air-gap)** |
| D5 | IP protection | 6A encrypt / 6B TEE / 6C obfusc-split | **6A floor + 6B opt-in + tiering** |
| D6 | Metering | 10A CP / 10B signed-ledger / 10C license | **10A (Dedicated) + 10B/10C (air-gap)** |
| D7 | CP connectivity | private link per cloud / public mTLS | **private where available; CP per cloud** |
| D8 | No-in-boundary-compute alternatives (§1.8.1) | Serverless-SDK / connector / ext_authz on existing mesh / hosted egress proxy | **deferred — separate workstream after the in-VPC path lands** |
| D9 | Workload-identity stack (§3.5) | self-hosted **SPIFFE/SPIRE** / native per-cloud (IRSA · Entra WI · GKE WI) / hybrid | **SPIFFE/SPIRE portable core + native bootstrap per cloud** |
| D-fresh | Policy cache staleness (§2.1) | exact TTL + staleness SLO; push-channel transport | **push primary + force-central-on-tighten; TTL/SLO TBD** |

**These are explicitly unresolved — to be re-evaluated together before build.** D8 is intentionally
out of scope for this LLD (see §1.8) and revisited later.

---

## 16. Cross-References & Sources
**Internal:** [ARCHITECTURE.md](ARCHITECTURE.md) (editions §2.4, threat model §2.7, latency §2.6) ·
[PRD.md](../PRD.md) (FR-1.5/1.7, 3.12/3.13, 9.2/9.3, 10.3, 11.1–11.3; NFR-1/2/3/4/6/7/11) ·
[LLD 23 SDK](23-sentra-guard-sdk.md) · [LLD 18 Deterministic](18-deterministic-enforcement.md) ·
[LLD 19 ML](19-ml-threat-classifier.md) · [LLD 24 Latency](24-latency-optimization.md) ·
[LLD 15 Connectors](15-cross-cloud-connectors.md) · [LLD 17 Signal Store](17-validation-signal-store.md) ·
[STRATEGY.md §3](../pitch/STRATEGY.md) (value floor / in-boundary intelligence model).

**External (cloud feasibility, June 2026):**
- AWS Fargate eBPF/capabilities: [containers-roadmap #1027](https://github.com/aws/containers-roadmap/issues/1027), [Fargate security considerations](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-security-considerations.html)
- GKE Dataplane V2 custom-eBPF limit: [GKE Dataplane V2 docs](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/dataplane-v2)
- Cloud Run sidecars: [Cloud Run multi-container](https://cloud.google.com/blog/products/serverless/cloud-run-now-supports-multi-container-deployments)
- Azure Container Apps sidecars: [Containers in Azure Container Apps](https://learn.microsoft.com/en-us/azure/container-apps/containers); confidential containers: [AKS Confidential Containers](https://learn.microsoft.com/en-us/azure/aks/confidential-containers-overview)
- Traffic mirroring: [AWS VPC Traffic Mirroring](https://docs.aws.amazon.com/vpc/latest/mirroring/what-is-traffic-mirroring.html), [GCP Packet Mirroring](https://docs.cloud.google.com/vpc/docs/packet-mirroring), [Azure vNet TAP (preview)](https://arnav.au/2025/05/05/azure-virtual-network-tap-overview/)
- Private connectivity: [AWS PrivateLink for SaaS](https://aws.amazon.com/blogs/networking-and-content-delivery/extend-saas-capabilities-across-aws-accounts-using-aws-privatelink-support-for-vpc-resources)
- Confidential computing GPU status: [Azure confidential GPUs](https://thomasvanlaere.com/posts/2025/03/azure-confidential-computing-confidential-gpus-and-ai/), [Nitro Enclaves](https://aws.amazon.com/confidential-computing/)
- TLS interception patterns: [Squid SSL-Bump](https://wiki.squid-cache.org/ConfigExamples/Intercept/SslBumpExplicit), Envoy egress TLS.
- **Egress TLS inspection to ride (3T-D):** [AWS Network Firewall egress TLS inspection](https://aws.amazon.com/blogs/security/tls-inspection-configuration-for-encrypted-egress-traffic-and-aws-network-firewall/) · [Azure Firewall Premium TLS inspection](https://learn.microsoft.com/en-us/azure/firewall/premium-features) (and [cert requirements](https://learn.microsoft.com/en-us/azure/firewall/premium-certificates)) · [GCP Cloud NGFW TLS inspection](https://docs.cloud.google.com/firewall/docs/about-tls-inspection) + [Secure Web Proxy](https://cloud.google.com/security/products/secure-web-proxy)
- **Lambda agent interception:** [AWS Lambda Runtime API proxy extension](https://aws.amazon.com/blogs/compute/enhancing-runtime-security-and-governance-with-the-aws-lambda-runtime-api-proxy-extension/)
- **Auth / workload identity (§3.5):** [SPIFFE/SPIRE concepts](https://spiffe.io/docs/latest/spire-about/spire-concepts/) · [Azure Entra Workload Identity federation](https://learn.microsoft.com/en-us/entra/workload-id/workload-identity-federation) · service-mesh mTLS (Istio/Linkerd/Cilium all build on SPIFFE)
- **Non-bypass / admission control:** [Kubernetes admission webhooks](https://kubernetes.io/docs/reference/access-authn-authz/admission-controllers/); Istio note that it "cannot securely enforce all egress flows through the gateway"
- **Native agent governance (validation):** [Amazon Bedrock AgentCore Policy → Cedar](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html) — AWS intercepts every tool call at the boundary, NL→Cedar (AWS-only; confirms our model + the cross-cloud gap)
- **Container Apps / Cloud Run egress:** [ACA outbound via UDR/Azure Firewall](https://learn.microsoft.com/en-us/azure/container-apps/user-defined-routes) · [Securing ACA egress](https://techcommunity.microsoft.com/blog/azurepaasblog/securing-network-egress-in-azure-container-apps/3915548)

---
*Draft for review. Per LLD standards: update HLD/ADR/flow/demo on changes; no option here is final until §15 is resolved.*
