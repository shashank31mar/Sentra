# AegionAI — Design-Partner Reachout Batch (week of 2026-07-20)

**10 targets, each grounded in what the company does + how AegionAI Guard fits.** Deeply cross-verified (product, agent action, contact currency, warm path — triangulated across 2+ sources). Two-step per target: **connect note** (get the accept) → **follow-up** (the pitch, once connected). Companion to [outreach-tracker.md](outreach-tracker.md) rows #20–29.

> **Warm path (verified):** a16z is an investor in **Rillet, Tennr, Decagon** only — use that intro path for those three; for the rest, warm paths are noted per company.
> **Channel:** connect note ≤300 chars for a raw request; follow-up = InMail/DM after they accept (drop the subject on a DM).
> **Honesty:** every message respects the verified autonomy boundary — no claim that an agent moves money / posts to the GL / denies care fully autonomously where a human gate exists.
>
> **✅ Contact verification (done 2026-07-20):**
> - **Rillet / Stelios Modes** — ✅ CTO confirmed. **SENT 2026-07-20.**
> - **Ramp / Rahul Sengottuvelu** — ✅ CTO confirmed (4 sources; his X bio reads "cto @ ramp"). ⚠️ **LinkedIn slug unverified** (bot-block) — send via **X DM @rahulgs** (verified) OR confirm his LinkedIn slug off Ramp's team page first. Message content is correct.
> - **Klarna / Yaron Shaer** — ✅ **still CTO** (Wikipedia 2026 + Klarna's own Oct-2025 post). Handle `se.linkedin.com/in/yaron-shaer-1938103`. Send as drafted.
> - **Tennr / Tyler Johnson** — ✅ Co-founder & CTO confirmed; slug `linkedin.com/in/tyler-johnson-482a42158` verified as the right person (Tennr + Stanford). Send as drafted.
> - **Decagon / Sahib Pandori** — ✅ verified (IC, infra) `linkedin.com/in/sahibpandori`. **Optional exec upgrade:** Ashwin Sreenivas — **Co-founder & President (NOT "CTO"** — do not mis-title); handle `linkedin.com/in/sreenivasashwin` **unverified**, confirm before use. Send Sahib now; hold Ashwin as escalation.
> - The other 5 (Sedai, Komodor, Cohere, Qonto, Firefly) — verified-2026, slugs confirmed, send as drafted.

---

## 1. Rillet

**What they do:** AI-native ERP / accounting platform (a NetSuite/Intacct replacement). "Aura" agent reads and writes the live general ledger — proposes journal entries, auto-matches bank recon, runs the monthly close.

**How we fit:** Aura acts on the GL of record → we check the write (parameters, sequence, identity) and block a mis-posted/duplicated/fabricated entry before it commits.

**Contact + warm path:** **a16z** (Series B lead, Aug 2025) via Seema Amble / Marc Andrusko / Alex Rampell. Secondary: Sequoia (Julien Bek). CTO Stelios Modes is the buyer.

**① Connect note** (send with the request):

> Hi Stelios — Aura writing straight to the live GL is exactly the frontier I work on: I'm building a runtime layer that checks an agent's action before it commits. Would love to connect and compare notes, founder to founder.

**② Follow-up** (once connected) — subject: `Design partner — runtime guardrails for Aura's GL writes`

Stelios — Aura acts directly on the live general ledger: proposing journal entries, auto-matching reconciliations, running the close. Once an agent touches the system of record, the failure that matters isn't a wrong answer on screen — it's a mis-posted or duplicated entry reaching the ledger.

I'm building AegionAI Guard: a runtime layer that checks each agent action — parameters, sequence, identity — and can block a write before it commits, with a tamper-evident record of every decision. Neutral across whatever infra you run (AWS and Azure today). Honest stage: the deterministic checks and audit are live; ML detection is in shadow; no enterprise logos yet.

I take on a few design partners at a time, and an agent posting to a real GL is exactly the case I want. Worth 20 minutes? Easy no if not.

— Shashank
Founder, AegionAI
aegionai.ai

---

## 2. Ramp

**What they do:** All-in-one spend platform — corporate cards, expense, AP/bill-pay, procurement — for 40,000+ businesses, increasingly delivered via finance agents ("Agents for AP").

**How we fit:** AP agents code, fraud-check and complete card payments (money-move human-confirmed today) → we check the action itself as that gate loosens toward autonomy.

**Contact + warm path:** **Not a16z** (lead = Founders Fund). CTO Rahul Sengottuvelu (named ~Jun 2026). ⚠️ verify DM handle (X @rahulgs likely, single-source).

**① Connect note** (send with the request):

> Hi Rahul — congrats on the CTO role. Ramp's AP agents taking real finance actions is the exact problem I'm building for — checking what an agent does before it runs. Would love to connect.

**② Follow-up** (once connected) — subject: `Runtime guardrails for Ramp's agent actions — a design-partner ask`

Rahul — congrats on the CTO role. Ramp's Agents for AP already code, fraud-check and complete card payments end-to-end, with a human confirming money movement. As that gate loosens toward the "autonomous back office" your team describes, the question shifts from "is this prompt bad" to "should this specific action run" — right vendor, right amount, right sequence, right identity.

I'm building AegionAI Guard — a neutral runtime layer that checks each agent action against exactly those bounds and blocks before it executes, with a tamper-evident trail. Honest stage: deterministic checks and audit are live (AWS + Azure today), ML detection is in shadow, no enterprise logos yet — which is why I'm taking on a few design partners to shape it against real agent workflows.

Worth 20 minutes? Easy no if the timing's off.

— Shashank
Founder, AegionAI
aegionai.ai

---

## 3. Sedai

**What they do:** Autonomous cloud-optimization platform ("self-driving cloud") — RL agents rightsize, scale and self-heal production workloads. Copilot = human approves; Autopilot = fully autonomous.

**How we fit:** Autopilot executes prod infra changes with no approval → we govern what the autonomous action does (params, sequence, identity) and block a mis-scoped one, with an audit trail regulated customers can show an auditor.

**Contact + warm path:** Investor intro: AVP (Manish Agarwal), Norwest, Sierra, Uncorrelated. CTO Benji Thomas — linkedin.com/in/benjamin-thomas-97691a8 (verified).

**① Connect note** (send with the request):

> Hi Benji — Autopilot executing prod changes with no approval is precisely the surface I'm building guardrails for. Would love to connect and swap notes, founder to founder.

**② Follow-up** (once connected) — subject: `Design partner — guardrails for Sedai's Autopilot actions`

Benji — Sedai's Autopilot makes and executes production changes — rightsizing, scaling, remediation — with no manual approval, and you lead with a clean incident record. That's exactly the surface I'm building for: a neutral, cross-vendor layer that governs what an autonomous agent is allowed to do — per-action parameter, sequence and identity checks, blocked before execute, with a tamper-evident audit trail your regulated customers can point an auditor at.

Honest stage: the deterministic floor and append-only audit are live across AWS and Azure today; ML detection is in shadow; in-VPC/on-prem is roadmap. No enterprise logos yet — I take on a few design partners at a time.

Worth 20 minutes, founder to founder? Easy no if the timing's off.

— Shashank
Founder, AegionAI
aegionai.ai

---

## 4. Komodor

**What they do:** Kubernetes operations platform; its "Klaudia" agentic engine autonomously detects, investigates and remediates K8s incidents (an "AI SRE").

**How we fit:** Klaudia remediates live clusters with/without a human → we add the action gate: check the remediation (target, blast radius, sequence) before it fires, alongside their guardrails.

**Contact + warm path:** No verified warm intro. Investors for a VC path: Tiger Global (Series B lead), Accel, Felicis. CTO Itiel Shwartz — linkedin.com/in/itielshwartz (verified).

**① Connect note** (send with the request):

> Hi Itiel — Klaudia remediating clusters with or without a human is the exact moment I think agents need an action gate. Building that layer — would love to connect.

**② Follow-up** (once connected) — subject: `Design partner — an action gate for Klaudia's autonomous remediations`

Itiel — since November, Klaudia remediates Kubernetes failures with or without a human in the loop. That's the exact moment the question changes from "is the diagnosis right" to "should this specific remediation run right now" — the right target, blast radius, sequence.

I'm building AegionAI Guard: a neutral runtime layer that checks each agent action before it executes and can block an off-policy or injected one, alongside your own guardrails, with a tamper-evident record. Neutral across clouds (AWS and Azure today). Honest stage: deterministic checks and audit are live, ML detection is in shadow, no enterprise logos yet.

I take on a few design partners at a time — an autonomous K8s remediator is squarely the case. Worth 20 minutes, founder to founder? Easy no if not.

— Shashank
Founder, AegionAI
aegionai.ai

---

## 5. Tennr

**What they do:** Agentic healthcare patient-orchestration platform — its RaeLM document model reads inbound referrals/faxes, then runs front-office workflows (prior auths, eligibility, orders).

**How we fit:** Agents submit prior auths and touch orders → we check the action (params, identity, sequence) before it commits to a payer or record, with a HIPAA-grade audit trail.

**Contact + warm path:** **a16z** (Series A lead, Mar 2024) via Bio+Health partners (Kristina Shen / Zeya Yang). CTO Tyler Johnson — linkedin.com/in/tyler-johnson-482a42158 (likely).

**① Connect note** (send with the request):

> Hi Tyler — agents submitting prior auths and touching orders is high-stakes ground. I'm building a runtime check on what an agent does before it commits. Would love to connect.

**② Follow-up** (once connected) — subject: `Design partner: governing what your agents submit to payers`

Tyler — Tennr's agents read a referral and then act on it — submitting prior auths, making eligibility determinations, updating orders. The failure that matters in healthcare isn't a wrong sentence; it's a misread or injected fax driving an off-policy submission to a payer or a write to the record.

I'm building AegionAI Guard: a runtime layer that checks each agent action — parameters, identity, sequence — before it commits, alongside your own quality controls, with a tamper-evident trail for HIPAA-grade audit. Honest stage: deterministic checks and audit are live (AWS + Azure), ML detection in shadow, no enterprise logos yet.

I take on a few design partners at a time. Worth 20 minutes? Easy no if the timing's off.

— Shashank
Founder, AegionAI
aegionai.ai

---

## 6. Cohere Health

**What they do:** Sells "Cohere Unify" to health plans — agentic AI that automates utilization management / prior-authorization intake and decisions.

**How we fit:** Unify auto-APPROVES ~85% of prior auths in real time (denials always human) → we enforce that an auto-approval only fires inside policy, turning "auditability" into an enforced control.

**Contact + warm path:** **Not a16z** (Series C led by Temasek). Chief Data & AI Officer Gigi Yuen-Reed — linkedin.com/in/gigiyuen (verified).

**① Connect note** (send with the request):

> Hi Gigi — Unify auto-approving prior auths at scale is exactly where I think enforcement matters most. Building a layer that keeps an auto-approval inside policy. Would love to connect.

**② Follow-up** (once connected) — subject: `Design partner — a control layer for Unify's auto-approvals`

Gigi — Unify auto-approves the majority of prior-auth requests in real time, at scale. Approvals are where speed lives — and where an off-policy or manipulated input approving something it shouldn't is the failure that matters (denials rightly stay with your clinicians).

I'm building AegionAI Guard: a runtime layer that enforces that an auto-approval only fires inside policy — checking parameters, sequence and identity per action, blocking before commit, with a tamper-evident record. It turns "full auditability" into an enforced control. Honest stage: deterministic checks and audit are live (AWS + Azure), ML detection in shadow, no enterprise logos yet.

I take on a few design partners at a time. Worth 20 minutes? Easy no if not.

— Shashank
Founder, AegionAI
aegionai.ai

---

## 7. Decagon

**What they do:** Conversational "AI concierge" support agents across chat/email/voice/SMS; via backend integrations they execute account-mutating support workflows for enterprise + fintech clients.

**How we fit:** Agents execute account changes (resets, disputes, fraud handling, autopay) → we check the action before it commits and block a social-engineered/injected one.

**Contact + warm path:** **a16z** (seed lead + Series C co-lead) via partners Kimberly Tan / Jeff Silverstein. Also target Decagon's own fintech customers. Contact: Sahib Pandori (MTS-Infra) — linkedin.com/in/sahibpandori (likely).

**① Connect note** (send with the request):

> Hi Sahib — support agents that actually change accounts (resets, disputes, autopay) are the surface I'm building guardrails for. Would love to connect and compare notes.

**② Follow-up** (once connected) — subject: `AegionAI — governing the actions your support agents take`

Sahib — Decagon's agents don't just answer — they execute account workflows through backend integrations (disputes, resets, fraud handling, autopay). Once an agent can change an account, the failure that matters is a social-engineered or injected turn executing a change it shouldn't.

I'm building AegionAI Guard: a neutral runtime layer that checks each agent action — parameters, identity, sequence — and blocks an off-policy one before it commits, with a tamper-evident record. Neutral across clouds (AWS + Azure today). Honest stage: deterministic checks and audit are live, ML detection in shadow, no enterprise logos yet.

I take on a few design partners at a time. Worth 20 minutes? Easy no if the timing's off.

— Shashank
Founder, AegionAI
aegionai.ai

---

## 8. Qonto

**What they do:** Paris-based B2B business-banking platform for 600k+ European SMEs; went "AI-native" in Apr 2026 with embedded agents ("The Operator") + an official Qonto MCP server.

**How we fit:** The Operator prepares bulk transfer drafts + issues cards (money-move human-confirmed + 2FA) → we validate the action (IBAN, amount, sequence) so a poisoned invoice batch can't ride a rubber-stamped run.

**Contact + warm path:** **Not a16z** (backers: Tiger, TCV, Valar, Insight). CTO Aymeric Augustin — linkedin.com/in/aaugustin (verified, CTO since 2020); champions the agent/MCP surface.

**① Connect note** (send with the request):

> Hi Aymeric — The Operator + Qonto MCP taking write actions on live accounts is exactly what I work on: checking the action itself (IBAN, amount, sequence). Would love to connect, engineer to engineer.

**② Follow-up** (once connected) — subject: `Design partner: action-layer checks for the Operator + Qonto MCP`

Aymeric — with The Operator and the Qonto MCP server, an agent now prepares supplier-transfer batches and card actions on live business accounts (with human confirm + 2FA on money movement). Even with that gate, a poisoned invoice batch can redirect a 50-supplier run the human rubber-stamps — so the check that matters is on the action itself: IBAN, amount, sequence.

I'm building AegionAI Guard: a neutral runtime layer that validates each agent action against those bounds and blocks before it commits, with a tamper-evident trail. Honest stage: deterministic checks and audit are live (AWS + Azure), ML in shadow, no enterprise logos yet; in-VPC is roadmap for EU residency.

Engineer to engineer — worth 20 minutes? Easy no if not.

— Shashank
Founder, AegionAI
aegionai.ai

---

## 9. Klarna

**What they do:** Swedish fintech + licensed digital bank (NYSE: KLAR); BNPL + shopping app, 100M+ active consumers. OpenAI-built assistant handles support at scale.

**How we fit:** Assistant manages refunds/returns tied to real accounts (human-AI hybrid) → we check the refund/reversal itself (amount, payee, sequence) and block an injected/duplicate one.

**Contact + warm path:** **Not a16z** (board chair Michael Moritz / Sequoia = warmest node). CTO Yaron Shaer — se.linkedin.com/in/yaron-shaer-1938103 (⚠️ verify still CTO).

**① Connect note** (send with the request):

> Hi Yaron — an assistant handling refunds and returns at Klarna's scale is the exact action-layer I'm building for. Would love to connect and compare notes.

**② Follow-up** (once connected) — subject: `Design partner: guardrails for your agent's refund/payment actions`

Yaron — Klarna's assistant handles refunds and returns across a huge consumer base, now in a human-AI hybrid. Even with oversight, the action that matters is the refund/reversal itself — an injected or duplicate refund over caps, to the wrong payee, is a direct-loss failure a good transcript won't catch.

I'm building AegionAI Guard: a runtime layer that checks each agent action — amount, payee, sequence, identity — and blocks an off-policy one before it executes, with a tamper-evident record. Neutral across clouds (AWS + Azure today). Honest stage: deterministic checks and audit are live, ML detection in shadow, no enterprise logos yet.

I take on a few design partners at a time. Worth 20 minutes? Easy no if not.

— Shashank
Founder, AegionAI
aegionai.ai

---

## 10. Firefly

**What they do:** Tel Aviv cloud asset-management / IaC platform ("Automated Cloud Resilience"); Thinkerbell AI agents inventory multi-cloud estates and generate/modify Terraform.

**How we fit:** Agents generate + drive Terraform apply/destroy on real resources (PR-gated today) → we govern the apply/destroy action (resource, blast radius, sequence) as autonomy increases.

**Contact + warm path:** **Not a16z** (lead = Vertex Ventures Israel; + SoftBank, Hanaco). Co-founder & CPTO Eran Bibi — il.linkedin.com/in/eran-bibi (verified); publicly champions autonomous ops.

**① Connect note** (send with the request):

> Hi Eran — your point that IaC is the foundation autonomous ops needs really landed. I'm building the enforcement layer for exactly that — agent apply/destroy. Would love to connect.

**② Follow-up** (once connected) — subject: `Design partner — the enforcement layer for AgentOps`

Eran — you've been making the case that IaC is the foundation autonomous ops needs, and Firefly's agents already generate and modify Terraform that creates, changes and deletes real resources. As that moves past PR-gated GitOps toward more autonomy, the question becomes "should this apply/destroy run" — right resource, blast radius, sequence.

I'm building AegionAI Guard: a neutral runtime layer that governs each agent action — checking it and blocking an off-policy or injected apply/destroy before it executes, with a tamper-evident record. Neutral across clouds (AWS + Azure today). Honest stage: deterministic checks and audit are live, ML in shadow, no enterprise logos yet.

Worth 20 minutes, founder to founder? Easy no if the timing's off.

— Shashank
Founder, AegionAI
aegionai.ai

---
