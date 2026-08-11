# YC 2025–2026 Competitive Scan + Fintech Niche Startup Map

**Author:** Shashank Gupta · **Date:** 2026-08-03 · **Status:** Internal reference (cross-referencing artifact)
**Purpose:** Durable record of two research passes — (A) which AI-agent-security / governance ideas got funded by YC across the six public batches W25→Spring26 (+ what YC *asked for* via RFS), and the closest-analog/twin verdict vs. our pitch; (B) which startups actually deal in each of the 5 fintech AI-agent-security niches surfaced by the fintech landscape research, scored by directness, tied back to AegionAI build-vs-roadmap.

---

## 0. Method, boundary & confidence (read first)

- **YC publishes only *accepted* companies.** Rejected or merely-submitted applications are **not public anywhere**. So "ideas submitted" is observable only two ways: **what got funded** (revealed demand) and **what YC asked for** — the published **Requests for Startups** (the funnel YC steered applicants toward). Both are captured here. There is no way to enumerate a submitted-but-rejected set; none was invented.
- **Batch naming.** YC moved to 4 batches/yr in 2025: **W25** (Winter 2025), **Spring25** (a.k.a. "X25"), **S25** (Summer 2025), **F25** (Fall 2025), then **W26**, **Spring26**. Summer 2026 (S26) / Fall 2026 are newer and flagged where they appear.
- **Sourcing.** Roster enumerated from the `yc-oss.github.io/api` mirror of YC's official directory (1,018 companies across the six batches), with close matches re-verified on their own `ycombinator.com/companies/<slug>` pages and company sites. RFS from `ycombinator.com/rfs` (current batch, high confidence) + reputable secondary aggregators for prior batches (medium/low).
- **[CONFIDENCE CAVEAT — load-bearing]** In both passes, general search engines (DuckDuckGo/Bing/Google) were **CAPTCHA-blocked**, so the niche map leaned on **direct vendor-page reads**. Every capability judgment below is **self-reported vendor copy unless noted** — asserted, not independently audited. Compliance / tamper-evidence / funding claims warrant Trust-Center or filing verification before use in investor materials. A mid-tier startup marketing an exact capability could be under-detected in the long tail.
- **Data freshness:** all fetches **2026-08-03**.

---

## PART A — YC 2025–2026: what got funded, the twin verdict, the patterns

### A.1 Our positioning (the yardstick)
Sourced from [pitch/share/AegionAI-pitch.md](../share/AegionAI-pitch.md), [pitch/share/architecture-brief.md](../share/architecture-brief.md), [pitch/share/STRATEGY.md](../share/STRATEGY.md). Four load-bearing legs used to score overlap:
1. **Neutral cross-vendor** — one plane across AWS/Azure/GCP/on-prem (the clouds structurally can't hold this). *Our own docs downgrade bare neutrality: cross-vendor visibility is no longer open ground (Zenity/CrowdStrike span vendors) — so "only neutral one" is NOT the moat.*
2. **Action-level governance with session state** — params, sequence integrity, identity/authorization, injection signals, accumulated trust — not stateless prompt/content scoring. *Inline blocking is explicitly "no longer the differentiator."*
3. **In-VPC → Dedicated → air-gapped** deployment ladder for regulated residency.
4. **Deterministic enforcement floor** beneath a probabilistic ML/behavioral layer.
Plus: **cross-vendor threat-data flywheel** (CrowdStrike pattern) and **tamper-evident audit / system-of-record**.

### A.2 Funded roster — Tier 1: core (govern/block what an agent *does* at runtime)

| Company | Batch | What it does | Source |
|---|---|---|---|
| **Salus** | W26 | API guardrails that **inspect & validate the agent's action at runtime and block before execute** (refund-without-order-ID example). Policy in YAML/plain-English → version-controlled, shadow-testable checks. Keeps session state (evidence cache + full conversation history). **Closest analog to us.** | ycombinator.com/companies/salus |
| **Golf** | Spring25 | Agentic AI security/governance at the **MCP layer** — discover every agent/MCP connection, enforce per-tool/data policy real-time, **90-day audit trail** pre-mapped to SOC2/ISO/NIST/FINRA. OSS GolfMCP + hosted Gateway. | golf.dev |
| **truthsystems** | S25 | Firm policies → **runtime guardrails that block non-compliant GenAI actions**; regulated beachhead (law firms, ~1,500 attorneys). | ycombinator.com/companies/truthsystems |
| **Agentic Fabriq** | W26 | "**Control plane for AI agents**" — per-agent identity, routes every call through a hub, real-time allow/block ("drive.delete blocked"), audit. Self-describes "Okta for Agents." | agenticfabriq.com |
| **ContextFort** | S25 | OS/kernel-level monitoring + blocking for **browser/coding agents** (Cursor, Claude Code). | ycombinator.com/companies/contextfort |
| **Silmaril** | Spring26 | Self-improving **runtime security** for agent frameworks (LangGraph, ~5 lines); classifier blocks threats (self-reported 2x block / 10x lower latency). | ycombinator.com/companies/silmaril |
| **Alter** | S25 | Zero-trust **identity + parameter-level authorization** on every tool call; ephemeral scoped creds; blocks "rogue DROP TABLE / over-limit payment." SOC2/HIPAA/GDPR + CISO dashboard. | ycombinator.com/companies/alter |
| **Multifactor** | F25 | Zero-trust authN/authZ/audit for agents; creds never exposed to agent; markets prompt-injection protection. Uses the **Wiz/Okta/Cloudflare framing**. | multifactor.com |
| **Clawvisor** | Spring26 | "Authorization layer for AI agents" — per-request enforcement; agents use Gmail/Slack/Drive without seeing creds. | ycombinator.com/companies/clawvisor |
| **OneCLI** | S26 | Identity gateway / **credential isolation** — agents see placeholder tokens; real keys injected at network layer. | ycombinator.com/companies/onecli |
| **LogosGuard** | F25 | On-device **PII redaction** before a prompt leaves for ChatGPT/Claude/Gemini + enterprise AI governance. | ycombinator.com/companies/logosguard |

### A.3 Funded roster — Tier 2: adjacent (governance/compliance, gateways, memory, observability-with-teeth)

- **Governance/compliance lifecycle:** TectoAI (S25), TrustAI (S26), Clarm (Spring25 — build *fully-governed* no-code agents for regulated teams; deterministic primitives, per-action audit, **on-prem**, BYO-model), Confident AI (W25, DeepEval).
- **Gateways / MCP infra with permissions:** Capacitive (Spring25), Metorial (F25), Executor (S26), Manufact (S25), Decawork (S26 — "agent control plane for IT teams").
- **"Control plane" naming collisions (NOT security):** Omnara (S25, ops/orchestration), Pentagon (Spring26, workspace).
- **Agent memory/context:** Wato (Spring26), Egoist Machines (S26 "AI Passport"), Memory Store (Spring26), Nessie (F25), Airweave (Spring25).
- **Observability / reliability (NOT compliance evidence):** Sentrial (W26), Lemma (F25), The Context Company (F25), TraceRoot (S25), Bluejay (Spring25).
- **Runtime app-protection / privacy:** RASPIRE (Spring26, RASP-style), Tinfoil (Spring25, confidential-compute enclaves).
- **New demand-side signal — AI-agent liability *insurance*:** Mount & Klaimee (both Spring26), citing EU AI Act / AB 316.

**Context-only (AI *doing* security work — NOT securing agents; don't confuse for competitors):** Cotool (agentic SOC, ~$7.4M a16z seed), Veria Labs (AI pentesting), Tolmo (AI AppSec), Candor (agentic DLP).

### A.4 What YC *asked for* (RFS = the submission funnel)
**Across all six batches, YC never named an explicit "AI-agent security" / "runtime action-governance" / "guardrails" RFS theme.** Nearest asks:
- **"A Secure AI App Store"** (Spring 2025) — trust/privacy/shared-memory distribution layer for agents. *Closest YC ever came to naming agent-security.*
- **"Compliance & Audit"** (Spring 2025) → **"AI-Native Compliance Infrastructure"** (Fall 2026) — compliance automation, finance-flavored, not runtime control.
- **"Infrastructure for Multi-Agent Systems / Kubernetes for AI agents"** (Fall 2025, Pete Koomen) & **"Software for Agents"** (Summer 2026) — fleet coordination/reliability, adjacent to a control plane but framed as orchestration.

The through-line YC pushed: **build agents / agent infra / compliance automation** — *not* governance-of-agent-actions.

### A.5 Twin verdict — **no direct twin exists** (web-verified vs. our 4-leg thesis)

| Analog | Batch | Overlap | Why it's not a twin |
|---|---|---|---|
| **Salus** | W26 | **58/100** | Near-twin **on the mechanism** ("inspect an action as it's about to execute"; deterministic-flavored policy; session state). **Misses BOTH moats:** pure SaaS (pip-install, no in-VPC/air-gap), *model*-agnostic ≠ *cloud*-neutral, no flywheel; pitched as agent *correctness/reliability* for dev-tools buyers. **The trajectory risk to watch.** |
| **Alter** | S25 | 42 | Identity-first ("who the agent is") — the *complementary partner* lane, not a competitor. |
| **Agentic Fabriq** | W26 | 35 | "Okta for Agents" — identity/authz; shares "control plane" label only. |
| **Silmaril** | Spring26 | 30 | Our *probabilistic ML-detector* analog, not the deterministic-floor/control-plane analog. |
| **truthsystems** | S25 | 30 | Blocks non-compliant *content/usage* in one vertical, not tool-call actions with params/state. |
| **Clarm** | Spring25 | 28 | Only one touching deterministic + on-prem + regulated together — but a *builder* for governed agents, not a neutral plane over *others'* agents. |

**Verdict:** no YC 25-26 company combines neutral-cross-vendor + stateful-action-governance + in-VPC/air-gapped + deterministic-floor + flywheel. Salus proves the "action-not-prompt" wedge is real and being built well — **validates the thesis while eroding any "unique on the enforcement mechanism" claim** (which STRATEGY.md already concedes).

### A.6 The patterns
**Macro (what YC bet on):**
1. Dominant bet is *building* agents, not *governing* them (coding agents, vertical agents, infra/sandboxes, memory/context are the highest-volume themes every batch). Governance is a thin trailing layer.
2. RFS repeatedly pushed **full-stack AI service companies** ("sell the completed work, not the tool").
3. **Compliance automation ≠ AI governance** — every "AI compliance" YC funded (Cardamon, ComplyDo, Probo) is *AI applied to regulatory paperwork*, not governance of AI systems. Naming hazard for our category.

**Niche / emergent (the useful part):**
4. **"Control plane for agents" is now contested vocabulary** (Agentic Fabriq, Decawork, Omnara, Pentagon — all different meanings). Can't own the phrase; own the mechanism.
5. **Agent security is arriving through the *identity* door, not the action door** — densest cluster is Alter/Multifactor/Clawvisor/OneCLI/Agentic Fabriq. Validates our "identity vendors are complementary partners" thesis, but several creep into parameter-level authz.
6. **"Block the action, not the prompt" crossed thesis→consensus in ~12 months:** Golf (Spring25) → truthsystems/Alter (S25) → Salus/Agentic Fabriq (W26) → Silmaril (Spring26). A timeline of the wedge commoditizing.
7. **Two structural white-spaces the whole cohort left empty:** (a) **cloud-neutrality as a moat** — everyone is model-agnostic or tool-neutral, nobody AWS/Azure/GCP-neutral-as-a-plane; (b) the **in-VPC → air-gapped ladder** — every verified analog is SaaS/hosted; only Clarm even says "on-prem." Plus the **flywheel** — absent from the entire set.
8. **Demand validating from insurance** — Mount & Klaimee underwriting AI-agent liability = third-party proof that "wrong agent action = quantifiable loss," our beachhead's premise.

**Strategic takeaway:** defend on the *combination + deployment ladder*, not the enforcement mechanism.

---

## PART B — Fintech niche startup map (the 5 niches)

Scored: **direct** (squarely addresses the niche as defined) · **partial** · **adjacent** · **tangential**. Contestedness: **empty → thinly-contested → partially-covered → crowded**.

### B.1 Niche 1 — Tamper-evident audit trail as compliance **system-of-record** for agent decisions
**Verdict: partially-covered · closest player: Golf.** Market splits three ways, nobody holds the combined artifact:

| Player | Funding | Directness | Falls short |
|---|---|---|---|
| **Golf** (YC Spring25) | YC | partial | 90-day compliance-mapped per-action log; **no tamper-evidence, no decision-chain schema, short retention** |
| **Alter** (S25), **Clarm** (YC) | YC | partial | Audit is a byproduct of authz / agent-builder; no append-only/cryptographic integrity |
| **Fiddler AI** | ~$45M+ | adjacent | Most "system-of-record" language (Mastercard/DTCC); but core is observability; "decision lineage" = debugging, not a durable compliance record |
| **Credo AI** (Agent Governor, Jul 2026), **Holistic AI**, **Monitaur** | ~$20–40M+ | adjacent | Model/org-level framework-mapped GRC evidence, not per-action tamper-evident agent-decision records |
| **Vanta** (~$2.45B), **Drata** (~$2B) | late-stage | tangential | Org/control-level continuous compliance; not per-action agent runtime records |
| **immudb / Codenotary** | infra VC | adjacent | Crypto append-only ledger substrate with **zero agent-decision schema** — the primitive, not the product |

**True white-space:** the *vertically-integrated* agent-decision ledger fusing an inline PDP's own verdict/signal data (policy→signals→verdict→action→outcome) + immudb-grade tamper-evidence + GRC-grade evidence export. **Only an inline PDP has the decision data.** Fragile though — immudb commoditizes the crypto; ~6–12 month window.

### B.2 Niche 2 — Memory-poisoning defense (inline pre-commit memory-WRITE gate)
**Verdict: thinly-contested (emptiest) · closest player: Straiker (names it, doesn't gate it).**

| Player | Funding | Directness | Falls short |
|---|---|---|---|
| **Straiker (Defend AI)** | ~$85M | partial | *Only* named vendor listing "memory poisoning" as a runtime-block category — but **no write-gate mechanism described** (likely recall-path detection); SaaS-only → no seam into the customer's store |
| **Zep** | seed/early | adjacent | Governs *access* (ABAC) + provenance, not write-integrity; stores user statements AS facts (traceable, not rejected) |
| **mem0** | ~$24M | tangential | Storage/extraction infra; `.add()` has no validation hook |
| **Zenity / Lasso / Prisma AIRS (Palo Alto/Protect AI) / HiddenLayer** | funded/incumbent | tangential | Detect on recall / posture / red-team / model-supply-chain — not the memory-commit plane |

**True white-space:** inline, **pre-commit validation of the memory WRITE itself** (RAG upsert / embedding persist / tool-output cache / history append) at a self-hosted store-wrapper seam. Threat settled (OWASP **ASI06**, renumbered from T1 ~2025-12-09; MITRE ATLAS AML.T0080.000; attacks: AgentPoison, MINJA); **defense category only forming.** Caveat: emptiest partly because production demand is still forming.

### B.3 Niche 3 — Maker-checker protocol for mixed human + agent workflows
**Verdict: partially-covered (least underserved of the "niche" ideas — already built) · closest player: Veto.**

| Player | Funding | Directness | Note |
|---|---|---|---|
| **Veto (by Plaw)** | unfunded OSS | **direct** | Names maker-checker AND uniquely supports **agent-as-checker** (2nd agent, different identity/policy/model). Single closest to the idea as written. |
| **MakerChecker.ai** | unfunded (~51★) | **direct** | Self-hosted, fail-closed four-eyes gate, **Ed25519 hash-chained audit**, payment-release/journal-posting. **Near-twin of our own thesis** (in-VPC + deterministic gate + tamper-evident audit). Checker is a *human* only (covers the niche halfway). |
| **Alter** (S25), **Salus** (W26) | YC | partial/adjacent | Generic real-time approval hooks; no requester≠approver segregation-of-duties or maker/checker role semantics |
| **ERP incumbents** (Oracle NetSuite SuiteApprovals, SAP, Workday) | public | adjacent | Own human maker-checker + journal/payment-release semantics; treat agents only as **drafters**, not first-class maker OR checker |
| **HumanLayer** | pivoted | tangential | Was the HITL approval-gate API; pivoted to an AI coding IDE as of 2026 |

**True white-space:** *enterprise-grade, ERP-native, agent-as-checker at scale* (lands approvals in the customer's existing SAP/Oracle approval queue, SOX/SOC2 certified). **Not the concept — that's taken by two unfunded SDKs.**

### B.4 Niche 4 — Per-action cryptographic attestation (deepfake-proof authorization)
**Verdict: partially-covered · closest player: ScrambleID · NOT our lane (identity/authentication).**

| Player | Funding | Directness | Note |
|---|---|---|---|
| **ScrambleID** | ~$544K seed (FJ Labs) | **direct** | Device-bound key, "Per-Action Proof" (early-access Q2 2026); explicitly anti-cloned-voice/CFO fraud. Attests *presence/approval*, not transaction-parameter binding |
| **COSIGN** | unverifiable | **direct** | Targets the exact deepfake-wire problem ("can't fake a cosign"); barely verifiable beyond marketing site |
| **OneSpan/Cronto**, **Entrust** | public/PE | partial | Parameter-bound "what-you-see-is-what-you-sign" transaction signing — but consumer/retail-banking only, never ported to enterprise wires |
| **W3C Secure Payment Confirmation** | standard (CR 2026-07-02) | partial | Standardized device-bound + transaction-binding primitive; scoped to card-checkout |
| **Reality Defender / Pindrop / BioCatch** | funded | adjacent | Deepfake **detection** / behavioral signals — probabilistic, no cryptographic proof |
| **Yubico / Okta FastPass / Entra / CyberArk / Prove / Nametag** | public/funded | adjacent/tangential | Device-bound auth / identity — the "who the actor is" layer, not per-action transaction binding |

**True white-space:** the full stack (device-bound FIDO2 + THIS-transaction parameter binding + out-of-band confirm + behavioral context) packaged for **enterprise treasury/AP high-value wires** (the Arup $25.6M scenario). But this is the **identity/authentication layer we treat as a complementary partner** — pursuing it is a category error for us.

### B.5 Niche 5 — Cross-agent trust & blast-radius containment
**Verdict: thinly-contested · closest player: CapiscIO · maps to what we already ship.**

| Player | Funding | Directness | Falls short |
|---|---|---|---|
| **CapiscIO** | pre-seed (5 design partners) | **direct** | Runtime A2A **delegation-authority** enforcement (Ed25519, monotonic narrowing). Governs *who-delegated-what-scope* — **not** action-semantics, response-trust, or **containment** |
| **Straiker** | ~$85M | partial | Multi-agent attack-chain *research/detection*, not runtime inter-agent enforcement |
| **Okta Cross App Access / CyberArk Secure AI Agents / Entra Agent ID** | public | adjacent | Scope agent identity; never inspect the inter-agent *action* (complementary) |
| **Google A2A protocol** (Linux Foundation, GA Apr-2026) | standard | adjacent | The thing that *needs* governing ("unmapped attack surface"), not a governor |
| **Omnara / Decawork** | YC | tangential | Route/orchestrate/monitor; don't enforce a trust boundary |

**True white-space:** action-semantic inter-agent inspection (what B may ask C given session/trust state) + behavioral cross-agent trust scoring + **blast-radius quarantine**, neutral across vendors. **Maps directly onto our live `cross_agent_validator` + trust-quarantine.** Caveat: near-empty partly because production multi-agent A2A demand is still forming.

---

## PART C — Synthesis: contestedness ranking + AegionAI fit

### C.1 Ranking (emptiest → most contested) & AegionAI build-vs-roadmap

| Niche | Contestedness | Closest player | AegionAI status | Note |
|---|---|---|---|---|
| **Memory-poisoning** | thinly-contested (emptiest) | Straiker (names only) | **not-in-product** | 4th PEP seam / known wedge; a feature, not a market. Demand still forming. |
| **Cross-agent trust** | thinly-contested | CapiscIO (authority only) | **partial** | Literally our live `cross_agent_validator` + quarantine; mesh-wide containment is roadmap |
| **Audit-trail SoR** | partially-covered | Golf | **partial** | We already emit the decision chain (nobody else has it); crypto hash-chain + evidence export + long retention is roadmap. **Strongest strategic fit.** |
| **Deepfake attestation** | partially-covered | ScrambleID | **not-in-lane** | Identity/authentication layer = complementary partner; pursuing = category error |
| **Maker-checker** | partially-covered | Veto | **not-in-product** | A Cedar policy pattern on our inline gate + hash-chained audit; MakerChecker.ai is a near-twin of our thesis |

### C.2 Contrarian flags (decision-useful)
1. **"Thinly-contested" often = "the only direct players are pre-product"** (CapiscIO, MakerChecker.ai, COSIGN). Validates *weak demand* as much as a gap. Empty ≠ ownable.
2. **Four of five are FEATURES of our existing plane, not standalone companies:** audit-SoR = a PDP module; cross-agent-trust = our live validator + quarantine; maker-checker = a Cedar policy pattern; memory-write = a 4th PEP seam. Framing them as five "markets" over-fragments one control plane.
3. **Maker-checker & deepfake are the *least* underserved** — both "port a solved primitive to a new buyer," which incumbents do fast (OneSpan/Entrust/W3C SPC; Veto/MakerChecker.ai). A time-boxed window, not durable white-space.
4. **"Empty" can mean "no demand yet."** Multi-agent A2A and memory-poisoning *defense* are nascent — verify buyer pull before treating emptiness as opportunity.
5. **Audit-SoR gap is fragile** — immudb commoditizes the crypto; Golf/Fiddler add a hash-chain quickly; Vanta/Drata have distribution to bolt on. ~6–12 month window.
6. **Real threat is horizontal, not per-niche** — Straiker appears in 2 niches, Zenity in 3. A funded horizontal agent-security platform adds each as a feature — same logic that makes them features for us.
7. **Our durable differentiation stays the neutral-cross-vendor + in-VPC + inline-PDP combo**, not ownership of any single niche.

### C.3 Recommendation
[REC] Treat audit-SoR and cross-agent-trust as the **strongest incremental modules on the existing plane** (audit-SoR first — we already own the decision data nobody else has; cross-agent-trust second — partly built). Maker-checker = a demo-able Cedar policy pattern. Memory-write = build as a PEP-seam feature only if demand proves out. **Deepfake attestation = leave to identity partners.**

---

## Cross-references
- **Grounds against:** [pitch/share/STRATEGY.md](../share/STRATEGY.md) §2 (moat/landscape), [pitch/share/AegionAI-pitch.md](../share/AegionAI-pitch.md), [pitch/share/architecture-brief.md](../share/architecture-brief.md)
- **Sibling research:** [pitch/internal/fintech-ai-security-landscape.md](fintech-ai-security-landscape.md) (the 10-stage fintech research that surfaced the 5 niches)
- **Product truth (build-vs-roadmap):** [CLAUDE.md](../../CLAUDE.md) "Core Security Features", [lld/ARCHITECTURE.md](../../lld/ARCHITECTURE.md); `cross_agent_validator` + quarantine live in [src/security-controller/app/validators/](../../src/security-controller/app/validators/)
- **Prior competitor intel (extend, don't duplicate):** memories `competitor-straiker`, `competitor-ent-endpoint-intent`, `competitor-tenable-apex`, `competitor-autonomous-security-a16y`, `agentcore-gateway-bound-only`, `memory-write-governance-whitespace`
- **Watch-list added by this scan:** Salus (W26, near-twin on mechanism), Veto + MakerChecker.ai (maker-checker near-twins), CapiscIO (cross-agent authority), Golf (agent-audit), ScrambleID/COSIGN (deepfake attestation — partner lane)

## Sources (self-reported vendor/YC pages unless noted; all fetched 2026-08-03)
YC directory mirror `yc-oss.github.io/api`; `ycombinator.com/companies/<slug>` + `/rfs`; golf.dev; agenticfabriq.com; multifactor.com; getzep.com; trust.mem0.ai; straiker.ai; zenity.io; hiddenlayer.com; paloaltonetworks.com/ai-security/prisma-airs; lasso.security; prompt.security; fiddler.ai; credo.ai; holisticai.com; monitaur.ai; vanta.com; drata.com; immudb.io; norm.ai; veto.so; makerchecker.ai; scrambleid.com; usecosign.com; onespan.com; w3.org/TR/secure-payment-confirmation; proof.com; realitydefender.com; pindrop.com; biocatch.com; capisc.io; okta.com/newsroom; cyberark.com/solutions/secure-agentic-ai; microsoft.com/security (Entra Agent ID); a2a-protocol.org. Arup $25.6M deepfake incident corroborated via FT/Fortune/WEF/CFO.com. OWASP Agentic ASI06; MITRE ATLAS AML.T0080.000; AgentPoison (arXiv:2407.12784), MINJA (arXiv:2503.03704).
