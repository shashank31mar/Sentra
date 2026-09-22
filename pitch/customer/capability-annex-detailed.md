# AegionAI Guard — Detailed Capability Annex

**Prepared for:** end-customer security / architecture / compliance reviewers
**Date:** 2026-09-21 · **Status:** current build state, verified against source
**Companion to:** the two-page capability proposal. This annex is the line-by-line status behind it.

---

## 1. What AegionAI Guard is

A runtime control plane that governs **what an AI agent is allowed to do** — not what it says. A checkpoint sits in your own agent code (a decorator, or a cloud connector) and calls a policy engine **before** a tool, API, database or payment call executes. The engine returns allow/deny with a named deciding control. On deny, the call never runs.

Two properties are architectural, not configurable:

- **Deny-by-default.** A tool with no policy is denied. An unreachable engine denies. A masking failure denies. There is no fail-open mode anywhere in the product.
- **The checkpoint is always yours.** Interception and PII masking run inside your process, before any payload is formed. That property holds in every deployment model below.

---

## 2. Capability status against your requirements

Status key — **Now**: in the deployed product today. **Partial**: works with a stated limit or only on one integration path. **Build**: committed, in progress, 0–6 months. **Roadmap**: designed, 6–18 months.

| # | Your requirement | What exists today | Status |
|---|---|---|---|
| **1** | Deploy in customer environment (on-prem / private cloud / your Azure or AWS) | Checkpoint + PII masking + fail-secure enforcement run **inside your environment on every model**. Policy authorization itself is computed in-process (embedded Cedar). The **decision engine** is hosted by us today. | **Partial** |
| | Customer data must not leave | Structured identifiers are masked in your process **before egress**; masking failure blocks rather than sends raw. Free-text narrative is **not** masked and does reach us on the hosted model. | **Partial** |
| | No mandatory external dependency for core controls | Deterministic controls (policy, signature rules, trust, sequence, rate, cross-agent) need no external model. The ML classifier tier is a hosted model call today; the local replacement model is trained and in-repo, not yet deployed. | **Build** |
| **2** | Real-time PII / PHI / PCI detection | 10 structured detectors with real validation (Luhn + IIN card, SSN issuance rules, card security data, email, URL, IPv4/6, phone, dates, labelled MRN/account/licence IDs, high-entropy secrets). Runs on **every** guarded call, no flag. | **Now** |
| | Masking / redaction / tokenization | Irreversible typed-token masking (`⟦AEGR:nonce:CARD:411111:1111⟧`). We hold no reverse map — you cannot be re-identified from our records. Reversible tokenization with a vault is deliberately **not** offered. | **Now** |
| | Coverage: prompts · tool params · context | Masked unconditionally on the SDK and Azure-connector paths. | **Now** |
| | Coverage: responses · documents · logs · agent-to-agent | **Responses/outputs: not inspected at all** — the output phase is refused, deny-by-default. Documents/images are **blocked, not redacted**. Audit records are re-scanned before storage. A2A traffic is masked only where the calling agent is instrumented. | **Build / Roadmap** |
| | Non-US identifiers (Aadhaar, PAN, IBAN, NHS, passport) | Not covered today. Verified by execution. Pure-arithmetic checks, first item in the build queue. | **Build** |
| **3** | Architecture / data-flow / encryption / storage / integration docs | Available now: customer OpenAPI contract (34 paths), SDK integration guide, field-level "what leaves your boundary" transmission table, retention and deletion tables, deployment diagrams. | **Now** |
| | Sufficient for security / privacy / compliance review | Being consolidated into one security whitepaper pack: data-flow diagram with trust boundaries, STRIDE threat model, key-management, network/port requirements, SBOM, incident response, vulnerability policy, sub-processor list. No SOC 2 report exists (planned, not started); no pen-test report yet; no DPA/BAA executed. | **Build** |
| **4** | AWS agents | Bedrock Agents: pre-execution interception at the action-group boundary, deployed; denies with 403 before dispatch. Any AWS Lambda/service tool can be guarded with the SDK. | **Now** |
| | Custom agents | Python decorator on the tool function — one line per guarded action. Node/TypeScript SDK is next; every other stack integrates over one HTTPS call today. | **Now** (Python) |
| | Microsoft AI Foundry | Enforcement works where the tool executes **in your code** (your function, your connector target, your API) — that is covered today. There is **no plugin inside the Foundry Agent Service runtime**, and Foundry-hosted tools (Bing grounding, file search, code interpreter) cannot be gated by any third party. Read-only agent discovery exists and needs live validation. | **Partial** |
| | Copilot Studio | Not built. The mechanism is a custom connector / MCP server wrapping your checkpoint; scoped as joint pilot engineering. It can never be claimed non-bypassable — a maker can add another connector. | **Build** |
| | Salesforce / Agentforce | Not built. Apex callout / External Service to the checkpoint is the intended path. | **Roadmap** |
| | Multi-agent environments · enforcement layer | Enforcing today: delegation depth ceiling, per-agent peer allow-lists, and **cross-cloud sequence preconditions** (e.g. an AWS refund is denied unless an Azure identity verification occurred in the same session within 300s). Taint/data-flow propagation across agents is not built. | **Partial** |
| **5** | Minimal latency / performance impact | Deterministic controls short-circuit before any model call. The model tier is hard-capped (2.0s per call, 2.5s aggregate, no retries) and abstains rather than delays. Our only published measurement is the **hosted worst case**: e2e p99 3.45s / server p99 2.85s at concurrency 20 (n=150, 2026-07-02, WAN client, 100% of requests reaching the model tier). The deterministic-only path has not been separately measured. | **Partial** |
| | Measurable benchmarks | We will publish a **paired with/without benchmark from inside your environment** as POC deliverable #1. Note the latency fix and the residency fix are the same project: today's number is dominated by a WAN round trip plus a hosted model call, both of which the in-environment deployment removes. | **Build** |
| | Scalable for enterprise workloads | Stateless engine, on-demand storage, architecturally scale-out. Currently one engine task, no autoscaling policy, max concurrency exercised 20. Honest status: scale-out ready, not yet demonstrated. | **Partial** |
| **6** | Agent identity | Each agent holds its own P-256 private key and signs every call (ES256, 15-min token ceiling). You generate the key; we hold only the public half, so we cannot mint an agent's token. Register / revoke supported; revocation propagates fleet-wide in ~10s. | **Now** |
| | Least-privilege over tools and peer agents | Per-agent tool allow-list and peer-agent allow-list, default-deny, evaluated by open-source Cedar. Unlisted tool or peer = denied. | **Now** |
| | Access control over databases, files, APIs, applications | **Governed at the tool boundary only.** We authorize `query_customers`; we cannot yet express row/column/table/path/host-level rules — there is no database or file entity in the authorization model. First resource family is a ~2–3 month build. | **Roadmap** |
| | Integration with enterprise IAM / Entra ID | Not built. Operator login is Cognito OIDC today. Pluggable OIDC federation (Entra as IdP, group→role mapping) and accepting an Entra-issued agent token are both scoped. | **Build** |
| **7** | Prompt injection / jailbreak | Deterministic signature layer: 9 enforceable rule sets, 161 compiled matchers, blocking, editable at runtime, ~10s fleet propagation. Plus an LLM threat classifier (enforcing, structured verdict, temperature 0). | **Now** |
| | RAG / indirect prompt injection | A three-pass detector (signature → classifier → instruction-density / zero-width / homoglyph / base64 heuristics) is built, enforce-flagged and fails **closed**. It becomes active once your retrieval call sites are instrumented — it has decided no production traffic yet. Measured recall on the hosted path: **0.565 unmasked / 0.601 masked** (n=809). We put that number in the room ourselves: roughly four in ten known attempts are missed, which is exactly why your own deterministic rules are the floor and detection is depth behind them. | **Partial** |
| | Prevention of data exfiltration | We judge **the call that would ship the data** — parameters, caller authority, session history — before it runs; measured recall 0.968 at that point (n=741). We do **not** inspect outbound payloads, response bodies or network destinations. Never read this as egress DLP. | **Partial** |
| | Unauthorized tool / API execution | Default-deny Cedar allow-list, evaluated before any model, fail-secure on every error path. The strongest control in the product. | **Now** |
| | Excessive agent autonomy | Trust decay with automatic quarantine and suspension, per-session rate/velocity ceilings, required-prior-step sequence enforcement, delegation depth ceiling. Limit to state: these are **session-scoped**, and the session id comes from your application — server-side session generation is required for the boundary to hold. | **Partial** |
| **8** | End-to-end agent activity logging | One audit record per decision, dual-written: request id, session, agent, tool and parameters, decision, reason, deciding control, threat type, matched rule, severity, latency, trust before/after, caller IP, cloud/region, full multi-agent call chain, per-validator breakdown. Four-bucket decision trail per request: which controls ran, abstained, errored, did not run — and which one blocked. | **Now** |
| | Audit integrity | **Append-only** compliance archive (no delete grant) plus a mutable fast-read store. We will not use the words tamper-evident, immutable or WORM: there is no hash chain today. Hash-chaining + signed evidence export is a committed build item. 90-day default retention, 1-year ceiling. | **Partial** |
| | Visibility of users / agents / models / tools / APIs / data access | Per-agent, per-tool, per-session, per-parameter. End-user id and *your* agent's own model/deployment are not yet persisted on the decision record. | **Partial** |
| | SIEM / SOC integration incl. Microsoft Sentinel | **Not built — no outbound integration to any SIEM today.** The record already carries the fields Sentinel wants. Committed path: file/syslog sink for self-hosted deployments, and a Sentinel custom table via Data Collection Rule for cloud deployments. First destination is weeks, not months. | **Build** |

---

## 3. Deployment models — where the engine runs

| | **Hosted (today)** | **In your network** | **Fully disconnected / air-gapped** |
|---|---|---|---|
| Availability | **Available now** | **In build** | **Committed roadmap** |
| Runs in your environment | Checkpoint + masking | Checkpoint + **engine** | Checkpoint + engine + console + audit |
| What leaves you | Masked action values | Operational counts only | **Nothing** |
| Detection depth | Full, incl. hosted model tier | Full | Deterministic floor + local model; hosted model tier unavailable by definition |
| Your integration | One line in your code | **Identical** | **Identical** |

The integration you build for hosted is the integration you keep — only the engine's address changes. We would rather tell you now that in-network and disconnected are not yet deployable artifacts than have your reviewer discover it in week six.

---

## 4. What we are building now (0–6 months)

Ordered so each item unblocks the next. Items 1–5 are what turn "runs in your environment" from partial into complete.

1. **Storage and telemetry portability** — configurable endpoints and a local on-disk source for policies and detection rules, so the engine runs against customer-controlled stores instead of managed cloud services.
2. **Self-hosted enforcement-endpoint hardening** — caller authentication and rate limiting inside the application (today they live in the cloud gateway in front of it). Non-negotiable before any self-hosted engine ships.
3. **Local classification tier** — a CPU classifier (trained, in-repo, ~465MB) deployed alongside the engine. This removes the external model dependency and is simultaneously the largest latency reduction available.
4. **Signed content bundles** — one signing and verification primitive covering detection rules, policy bundles and licensing, with an operator import path for environments with no egress.
5. **Packaged deployment** — Compose topology, then Helm chart, plus an offline image bundle with a checksum/signature manifest.
6. **International PII pack** — Aadhaar, India PAN, IBAN, NHS, passport, non-US phone and date formats; plus PII in numeric-typed parameters.
7. **SIEM export** — file/syslog first, then Microsoft Sentinel via Data Collection Rule.
8. **Enterprise IAM federation** — pluggable OIDC (Entra ID as identity provider), group→role mapping, console login, enforced MFA.
9. **Security documentation pack and CI security gates** — whitepaper, STRIDE threat model, network requirements, SBOM, dependency and static analysis scanning, artifact signing.
10. **Benchmark publication** — paired with/without latency measurement, deterministic-floor latency separated from model-tier latency, throughput and saturation figures.

---

## 5. Roadmap (6–18 months)

- **Output and egress control** — response inspection, output DLP, and destination-level egress policy. This is the largest single capability gap in the product today and we will not describe it as partial.
- **Resource-level authorization** — database / table / column / file / endpoint entities in the policy model, so least privilege is expressible below the tool boundary.
- **Tamper-evident audit** — per-partition hash chaining, signed evidence export packages, multi-year retention tier.
- **Platform connectors** — Copilot Studio, Salesforce Agentforce, GCP Vertex, MCP tool-call interception, Node/TypeScript SDK.
- **Cross-agent taint propagation** — tracking whether untrusted retrieved content reached an outbound action.
- **Compliance** — SOC 2 Type II, third-party penetration test, executed DPA/BAA, customer-managed encryption keys.
- **Maker-checker on policy change**, agent-level (not only session-level) quarantine, and multi-region resilience.

---

## 6. What we will not claim

Included deliberately, because your reviewers will test each one.

- We do **not** inspect model responses or outbound payloads. Exfiltration is judged at the request point.
- The audit trail is **append-only**, not tamper-evident. No hash chain, no WORM, no object lock today.
- PII masking covers **structured identifiers**; free-text narrative and non-US identifiers are not covered today.
- Indirect prompt-injection recall is **0.565–0.601**, not the 0.968 figure that belongs to exfiltration-attempt detection. We will not blur them.
- **No SIEM integration exists today**, including Sentinel.
- **No Entra ID integration exists today.**
- No SOC 2 report, no penetration-test report, no BAA, no customer-managed keys.
- In-network and air-gapped editions have **no deployable artifact yet**.
- Our controls are **cooperative**: a tool that is not instrumented, or a maker who adds a route around the checkpoint, is not governed. What we can evidence is reconciliation — every declared tool should have decisions in the record.

---

## 7. Proposed POC

**Shape:** one agent, one high-value action, three weeks, nothing blocked until you say so.

| Week | Activity |
|---|---|
| 0 | Pick the agent and the action. Confirm which platform, and whether the action executes in your code (30 min). |
| 1 | You install the library and make one test call. We stand up the environment and a paired latency measurement (half a day of your engineer's time). |
| 1–2 | We judge and record every action and **block nothing**. You get the decision trail and the list of what would have been stopped. |
| 3 | You agree the rule, enforcement goes on for that one tool, and we test with a deliberate violation. |

**Demonstrable in the POC today:** prompt injection blocked before execution · unauthorized tool/API execution blocked (default-deny) · policy enforcement with a named deciding control · PII masked inside your process before egress · trust decay and quarantine on repeated attempts · cross-cloud sequence enforcement · the full decision trail and audit record · measured latency impact from inside your environment.

**Requires build before it can be demonstrated honestly:** malicious RAG content in a realistic retrieval flow (the detector is built; the agent-level instrumentation and a poisoned-document corpus are not) · SIEM/Sentinel forwarding · output-side data-exfiltration blocking · fully disconnected operation.

If the list of would-be denials after two weeks is empty, you have learned something worth knowing. If it is not, you have the business case.

---

**Contact:** Shashank Gupta, Founder · shashank31mar@gmail.com
