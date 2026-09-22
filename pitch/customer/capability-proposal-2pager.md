# AegionAI Guard — Capability Proposal

**2026-09-21** · current build state, verified against source · a detailed annex and POC plan are available for your reviewers

A runtime control plane that governs **what an AI agent is allowed to do**, not what it says. A checkpoint sits in your own agent code — a decorator or a cloud connector — and calls a policy engine **before** a tool, API, database or payment call executes. The engine returns allow/deny naming the control that decided; on deny, the call never runs. Two properties are architectural, not configurable: **deny-by-default** — a tool with no policy is denied, an unreachable engine denies, a masking failure denies, and no fail-open mode exists anywhere in the product — and **the checkpoint is always yours**, so interception and PII masking run inside your process in every deployment model below.

## Status against your requirements

**Now** = deployed today · **Partial** = works with the stated limit · **Build** = committed, 0–6 months · **Roadmap** = 6–18 months

| # | Requirement | Where we are | |
|---|---|---|---|
| 1 | **Customer-environment deployment** | Checkpoint, PII masking, fail-secure enforcement and policy evaluation already run **inside your environment**. The **decision engine** is hosted by us today; single-tenant in your own AWS/Azure account is the next edition, fully disconnected follows. Deterministic controls need no external model; the model-based detection tier is a hosted call today and its local replacement is trained, not yet deployed. | **Partial** |
| 2 | **PII / PHI / PCI protection** | 10 validated structured detectors (Luhn+IIN card, SSN issuance rules, card security data, email, URL, IP, phone, dates, labelled MRN/account/licence IDs, secrets), masked **in your process before egress**, on every guarded call, no flag, irreversibly — we hold no reverse map. Not covered: model responses (not inspected at all), documents (blocked rather than redacted), free-text narrative, non-US identifiers. | **Partial** |
| 3 | **Security documentation** | Now: customer OpenAPI contract, SDK integration guide, field-level "what leaves your boundary" table, retention and deletion tables, deployment diagrams. Being consolidated into one pack: data-flow with trust boundaries, STRIDE threat model, key management, network requirements, SBOM, incident response, sub-processor list. No SOC 2 report, pen-test report or DPA/BAA yet. | **Build** |
| 4 | **Platform support** | **AWS Bedrock Agents:** pre-execution interception at the action-group boundary, deployed. **Custom agents:** Python decorator, one line per action; other stacks integrate over one HTTPS call, Node SDK next. **Microsoft AI Foundry:** enforced wherever the tool runs in *your* code — no plugin inside the Foundry runtime, and Foundry-hosted tools (Bing grounding, file search, code interpreter) cannot be gated by any third party. **Copilot Studio:** not built; a custom connector / MCP server is the pattern, scoped as joint pilot work, never claimable as non-bypassable. **Salesforce:** roadmap. | **Partial** |
| | **Multi-agent enforcement** | Enforcing today: delegation depth ceiling, per-agent peer allow-lists, and cross-cloud sequence preconditions — e.g. an AWS refund denied unless an Azure identity check occurred in the same session within 300s. Cross-agent taint propagation is not built. | **Partial** |
| 5 | **Performance** | Deterministic controls short-circuit before any model call; the model tier is hard-capped at 2.0s/call and 2.5s aggregate, and abstains rather than delays. Our only published figure is the **hosted worst case** — e2e p99 3.45s at concurrency 20 (n=150, WAN client, every request reaching the model tier); the deterministic-only path is not yet separately measured. The latency fix and the residency fix are the same project: that number is dominated by a WAN hop plus a hosted model call, both removed by in-environment deployment. Stateless and scale-out ready, demonstrated only to concurrency 20. | **Partial** |
| | **Measurable benchmarks** | A paired with/without measurement from inside your environment, with deterministic-floor and model-tier latency reported separately, is POC deliverable #1. | **Build** |
| 6 | **Identity & least privilege** | Each agent holds its own P-256 key and signs every call (ES256, 15-minute token ceiling) — you generate it, we hold only the public half, so we cannot mint an agent's token. Register/revoke with ~10s fleet propagation. Per-agent **tool** and **peer-agent** allow-lists, default-deny, open-source Cedar. **Governed at the tool boundary only:** no row/column/table/path/host rules yet, so databases, files and applications are covered only as reached through a named tool. | **Partial** |
| | **Enterprise IAM / Entra ID** | No Entra ID integration exists today. Pluggable OIDC federation with Entra as identity provider, group→role mapping and enforced MFA is scoped. | **Build** |
| 7 | **AI threat protection** | **Injection and jailbreak:** 9 enforceable signature rule sets, 161 compiled matchers, blocking, runtime-editable, plus an enforcing LLM threat classifier. **RAG / indirect injection:** three-pass detector built, enforce-flagged, fails closed; active once your retrieval sites are instrumented. Measured recall **0.565–0.601** (n=809) — roughly four in ten known attempts missed, which is exactly why your deterministic rules are the floor and detection is depth behind them. **Exfiltration:** we judge the *call that would ship the data* (recall 0.968, n=741); we do **not** inspect outbound payloads, response bodies or destinations. **Unauthorized tool execution:** default-deny allow-list, the strongest control in the product. **Excessive autonomy:** trust decay with automatic quarantine, rate and velocity ceilings, required-prior-step enforcement — all session-scoped, so server-side session generation is required for the boundary to hold. | **Partial** |
| 8 | **Monitoring & audit** | One record per decision: request, session, agent, tool and parameters, decision, reason, deciding control, threat type, matched rule, severity, latency, trust before and after, caller IP, cloud and region, full multi-agent call chain, per-validator breakdown. Four-bucket decision trail per request — which controls ran, abstained, errored, did not run, and which one blocked. **Append-only**, not tamper-evident: no hash chain today. 90-day default retention, 1-year ceiling. | **Partial** |
| | **SIEM / SOC incl. Sentinel** | No SIEM integration exists today, Sentinel included. The record already carries the fields Sentinel wants; file and syslog first, then a Sentinel Data Collection Rule. | **Build** |

## Where the engine runs

| | **Hosted (today)** | **In your network** | **Fully disconnected** |
|---|---|---|---|
| Availability | **Available now** | **In build** | **Committed roadmap** |
| In your environment | Checkpoint + masking | Checkpoint + **engine** | Engine + console + audit |
| What leaves you | Masked action values | Operational counts only | **Nothing** |
| Detection depth | Full, incl. hosted model tier | Full | Deterministic floor + local model |
| Your integration | One line in your code | **Identical** | **Identical** |

The integration you build for hosted is the integration you keep — only the engine's address changes. We would rather tell you now that in-network and disconnected have no deployable artifact yet than have your reviewer find it in week six.

## What we are building now (0–6 months)

Ordered so each unblocks the next; items 1–5 turn "runs in your environment" from partial into complete.

1. **Storage and telemetry portability** — configurable endpoints and a local on-disk source for policies and detection rules, so the engine runs against customer-controlled stores.
2. **Self-hosted endpoint hardening** — caller authentication and rate limiting inside the application, where today they sit in the cloud gateway in front of it. Non-negotiable before any self-hosted engine ships.
3. **Local classification tier** — the CPU classifier already trained, deployed beside the engine. Removes the external model dependency and is the largest latency reduction available.
4. **Signed content bundles** — one signing and verification primitive covering detection rules, policy bundles and licensing, with an operator import path for zero-egress sites.
5. **Packaged deployment** — Compose topology, then Helm chart, plus an offline image bundle with a signature manifest.
6. **International PII pack** — Aadhaar, India PAN, IBAN, NHS, passport, non-US phone and date formats, and PII in numeric-typed parameters.
7. **SIEM export** — file and syslog, then Microsoft Sentinel via Data Collection Rule. **8. Enterprise IAM federation** — pluggable OIDC with Entra ID, group→role mapping, console login, enforced MFA. **9. Security documentation pack and CI security gates** — whitepaper, threat model, network requirements, SBOM, dependency and static analysis scanning, artifact signing. **10. Benchmark publication** — paired with/without latency, deterministic floor separated from model tier, throughput and saturation.

## Roadmap (6–18 months)

**Output and egress control** — response inspection, output DLP, destination-level egress policy; the largest capability gap today, and we will not describe it as partial. · **Resource-level authorization** — database, table, column, file and endpoint entities, so least privilege is expressible below the tool boundary. · **Tamper-evident audit** — hash chaining, signed evidence export, multi-year retention. · **Platform connectors** — Copilot Studio, Salesforce Agentforce, GCP Vertex, MCP tool-call interception, Node/TypeScript SDK. · **Cross-agent taint propagation.** · **Compliance** — SOC 2 Type II, third-party penetration test, executed DPA and BAA, customer-managed keys. · **Governance** — maker-checker on policy change, agent-level quarantine, multi-region resilience.

## What we will not claim

We do **not** inspect model responses or outbound payloads. The audit trail is **append-only**, not tamper-evident. Masking covers **structured identifiers** — not free-text narrative, not non-US identifiers. Indirect-injection recall is **0.565–0.601**, not the 0.968 figure that belongs to exfiltration-attempt detection; we will not blur them. **No SIEM and no Entra ID integration exist today.** No SOC 2 report, pen-test report, BAA or customer-managed keys. In-network and air-gapped editions have **no deployable artifact yet**. Our controls are **cooperative**: an uninstrumented tool, or a maker who routes around the checkpoint, is not governed — what we can evidence is reconciliation, that every declared tool has decisions in the record.

**Shashank Gupta**, Founder · shashank31mar@gmail.com
