# YC Application Draft — AegionAI (Winter 2027 / late-Fall 2026)

**Author:** Shashank Gupta · **Date:** 2026-08-04 · **Status:** DRAFT for founder review → paste into apply.ycombinator.com
**Positioning source of truth:** [pitch/share/STRATEGY.md](../share/STRATEGY.md), [pitch/share/AegionAI-pitch.md](../share/AegionAI-pitch.md). **Competitive basis:** [pitch/internal/yc-2025-2026-competitive-scan.md](yc-2025-2026-competitive-scan.md).

> **How to use this doc.** Answers to the **idea / product / competitor / market / monetization** questions are written and ready. Answers that depend on **your private facts** — founder background, team, revenue, users, equity, runway, video — are marked **`⟨FOUNDER: …⟩`** with guidance; only you can fill these truthfully. Do not ship a placeholder. Question wording is YC's current standard form (verified 2026-08-04); confirm live wording when you open the form. **I cannot submit the form for you** — it's login-gated and identity-bound. See the submit checklist at the bottom.

> **Two framing rules baked into every answer (do not break):**
> 1. **Lead with the two things the entire YC agent-security cohort left empty:** neutral cross-vendor *as a moat* + the in-VPC → air-gapped deployment ladder. NOT "we block the action" — that's now consensus (Salus W26, Golf, Alter) and reads as me-too.
> 2. **Name the competition as validation, not threat.** YC funded ~11 agent-security cos; that proves the category. Our edge is the *combination they can't assemble*.

---

## COMPANY

### Describe what your company does in 50 characters or less.
> *(hard 50-char limit — pick one; all verified ≤50)*
- **`One neutral control plane to govern AI agents`** *(45 chars — recommended)*
- `Cross-cloud control plane for AI agent actions` *(46)*
- `The safety layer for AI agents, on every cloud` *(46)*

### What is your company going to make? Please describe your product and what it does or will do.
AegionAI is a neutral, cross-vendor control plane that governs what AI agents are *allowed to do* — across AWS, Azure, GCP, and on-prem, from one place.

When an enterprise's AI agent tries to take an action (move money, delete infrastructure, change a customer record, call another agent), we intercept it the instant before it executes and decide: allow, block, or quarantine. We judge the *action itself* — its parameters, the sequence it's part of, the caller's identity and authorization, and the session's accumulated trust — not just whether a prompt "looks" malicious. A deterministic policy floor (exact parameters, step order, caller identity) runs first — the part a cleverly-worded prompt can't talk past — with a probabilistic detector adding depth behind it.

The reason it's a *company* and not a feature: no single cloud can be the neutral layer that governs agents running on a rival's cloud, and regulated buyers (banks, healthcare) can't route their agents' actions through anyone's SaaS. So we run the same enforcement engine in three editions — our cloud, inside the customer's VPC, or fully air-gapped — and every action produces a tamper-evident record that stands up as compliance evidence (SOC 2 / HIPAA / EU AI Act).

It's live today, not a plan: a working system enforcing on real agents across two clouds (AWS Bedrock + Azure), the same engine behind an SDK wrapper and a cloud connector.

### If you have a demo, what's the url?
> `⟨FOUNDER: demo URL or a 2-min Loom of the live block-before-execute on the refund/terraform-destroy flow. If none public yet, link the architecture-brief PDF or say "private demo on request".⟩`

### Where do you live now, and where would the company be based after YC?
> `⟨FOUNDER — THE LOAD-BEARING ANSWER. Be honest, be specific. YC needs a founder physically in SF for the batch. Draft to adapt:⟩`
>
> *"The team is in India. For the batch, ⟨name⟩ will be in San Francisco full-time; ⟨CTO name⟩ will continue leading engineering from India, where our team is. Post-batch we'll incorporate as a Delaware C-corp with a US HQ and keep the engineering team in India."*
>
> `⟨Only claim SF presence you will actually commit to. This is the real gate — see the "should we apply" decision. If no founder can be in SF, do not submit; the answer can't be faked.⟩`

---

## FOUNDERS

### 1-minute founder video (unlisted YouTube).
> `⟨FOUNDER: effectively REQUIRED now (standard field). 60s, founders on camera, talking (not slides). Script skeleton:⟩`
> - 0–10s: who you are + one line: "We govern what AI agents are allowed to do, across every cloud."
> - 10–35s: why you two — the specific credential that makes you the right team (see "impressive thing" below).
> - 35–55s: what's live — "enforcing on real agents across AWS and Azure today."
> - 55–60s: the ask / why now.
> `⟨Energy > production value. Look at the camera. No jargon.⟩`

### Who writes code / does technical work? Was any done by a non-founder?
> `⟨FOUNDER: name who built the security-controller (Python PDP), CDK infra, React console, connectors. Be honest about any non-founder/contractor contribution. If the CTO built the engine, say so plainly — it's a strength.⟩`

### How long have the founders known one another and how did you meet?
> `⟨FOUNDER: factual. If any co-founder hasn't met in person, YC asks — disclose it.⟩`

### An interesting project two+ of you created together (outside class/work).
> `⟨FOUNDER: pick something concrete you built together. If AegionAI is the first thing, describe an earlier joint hack. YC weights "have these people shipped together."⟩`

### One or two sentences on something impressive each founder has built or achieved.
> `⟨FOUNDER: one crisp sentence each. Lead with the most legible-to-a-US-partner proof (shipped systems at scale, prior exits, domain depth in security/fintech/infra). Portable, verifiable achievements beat titles.⟩`
>
> *Draft frame (edit with real facts): "⟨Founder A⟩ built and shipped ⟨production system at scale⟩ …; ⟨Founder B / CTO⟩ built the live cross-cloud enforcement engine now running on AWS + Azure, stdlib-only so it drops into a Lambda or Azure Function unchanged."*

### The time you most successfully hacked some (non-computer) system to your advantage.
> `⟨FOUNDER: a real story — resourcefulness/persuasion, not code. YC uses this to read scrappiness.⟩`

---

## PROGRESS

### How far along are you?
Working product, live on two clouds. We enforce agent actions today via two of our three "wires": an SDK decorator and a cloud connector (AWS Bedrock action-group Lambda + Azure Function). The engine ships a deterministic policy floor (Cedar policy + parameter bounds + sequence integrity), deterministic prompt-injection signatures (blocking), trust-score-driven quarantine, cross-agent filtering, and an append-only tamper-evident audit store. A machine-learning detector runs in shadow mode (~57% recall on the InjecAgent/AgentDojo public corpora) and graduates to enforcement once it clears our shadow→enforce bar. Roadmap: the in-VPC and air-gapped editions, input-side redaction/DLP, and bounded rollback.

> `⟨FOUNDER: add design-partner / pilot status if any — "in pilot with ⟨N⟩ design partners" is a strong line if true. Don't overclaim.⟩`

### How long have each of you worked on this? How much full-time?
> `⟨FOUNDER: honest months + full-time split. Context we can note: the July build sprint was investor-directed to hit a "product ready" gate.⟩`

### When will you have a prototype or beta?
Beta exists now (live enforcement on two clouds). The next milestone is the in-VPC edition — the deployment regulated buyers require — targeted for ⟨FOUNDER: quarter⟩.

### How many active users / customers? How many paying?
> `⟨FOUNDER: real numbers or "pre-revenue, in design-partner conversations." YC prefers honest small numbers over vague big ones. If zero paying, say so and pivot to pipeline.⟩`

### Revenue over the last several months (not cumulative, not GMV).
> `⟨FOUNDER: monthly figures or "pre-revenue." Do not inflate.⟩`

### Same idea as a previous batch / prior accelerator?
> `⟨FOUNDER: almost certainly "No" — confirm. Disclose any prior accelerator/pre-accelerator.⟩`

---

## IDEA

### Why did you pick this idea? Do you have domain expertise?
> `⟨FOUNDER: 1–2 sentences of personal domain proof up front (security / infra / fintech background), then:⟩`
>
> Enterprises are deploying autonomous agents into production faster than anyone can govern them, and the moment an agent can *act* — move money, change infrastructure, touch a customer record — a wrong or hijacked action is a direct financial and compliance loss, not a bad chat reply. We watched the industry build detection for what an agent *says* (prompt-injection scanners, observability) while nobody governed what an agent *does*, neutrally, in the place a regulated enterprise can actually deploy. We know how enterprise security controls and multi-cloud infrastructure actually work, so we built the enforcement layer we couldn't buy.

### What's new about what you're making? What substitutes do people resort to?
Two things nobody else combines. **First, neutrality as a control plane, not just visibility:** every alternative is either single-cloud (AWS/Azure/Google each govern only their own cloud and won't sit inline to block on a rival's) or a single-stack point tool. Enforcing agent actions *neutrally across every cloud* is a position the cloud vendors are structurally conflicted to take. **Second, deployment where regulated buyers live:** the same enforcement engine runs in the customer's own VPC or fully air-gapped — every close competitor is SaaS-only.

Today, teams resort to: hand-rolled if/else guards inside each agent (brittle, per-app, no audit); prompt-injection scanners (catch bad *input*, miss the bad *action* with clean input); cloud-native guardrails (only govern agents built on that one cloud's rails); or nothing — they deploy the agent and hope. None gives a regulated enterprise one neutral, in-VPC, tamper-evidently-audited chokepoint over what every agent is allowed to do.

### Who are your competitors? What do you understand that they don't?
The category is real and funded — which is our validation, not our problem. The closest players cluster three ways, and each holds one leg of the problem, never all of them:
- **Action-blocking startups** (Salus, Golf, Alter, Silmaril — several YC-backed): they proved "govern the action, not the prompt," but every one is SaaS-only, model-agnostic rather than *cloud*-neutral, and pitched at developer/reliability buyers — not the regulated buyer who can't use a SaaS proxy.
- **Cross-vendor security platforms** (Zenity, CrowdStrike, Straiker): strong at cross-vendor *visibility and detection*, but they detect and report; they don't sit inline as a neutral, in-VPC enforcement chokepoint over the action.
- **Agent-identity vendors** (Okta, CyberArk, Microsoft Entra Agent ID, plus YC's Multifactor/Clawvisor): they answer *who the agent is*. That's complementary to us — we answer *what the action may do*. We partner with that layer, we don't compete with it.

What we understand that they don't: **the defensible thing isn't the enforcement mechanism — it's the combination.** Stateful action-level enforcement + neutral across every vendor + deployable inside the regulated customer's boundary + a cross-vendor threat-data flywheel, held together. Point tools race each other on "block the action" while the regulated, multi-cloud enterprise — the buyer who pays most and churns least — still has no one who can deploy neutrally, in their VPC, with audit that satisfies a regulator. That buyer is who we're built for, and it's the seat no SaaS-only or single-cloud player can take.

### How do / will you make money? How much could you make?
Enterprise SaaS + self-hosted licensing, priced per governed agent / action volume, tiered by edition (our cloud → in-VPC → air-gapped, ascending price for the residency and control the regulated tier requires). We land engineering-led ("govern our infra/automation agents") on a fast, low-blast-radius sale, then expand to the high-value seat — agents that move money at mid-market fintechs — where a single wrong action justifies the platform on its own. The audit/compliance system-of-record is a buy-regardless-of-enforcement value floor that pulls in the regulated buyer even before they turn blocking on.
> `⟨FOUNDER: add TAM one-liner from STRATEGY §1 if you want a number; keep it sourced, not invented.⟩`

### How do users find your product? How did you get current users? CAC if paid ads?
> `⟨FOUNDER: honest. Likely "founder-led outreach + design-partner conversations; no paid ads yet." Note the augment-portfolio VC-outreach motion if relevant. If no users yet, describe the pipeline.⟩`

---

## EQUITY / LEGAL / FINANCIAL
> `⟨FOUNDER — all private facts; fill exactly. YC verifies these.⟩`
- Formed any legal entity yet? `⟨Y/N + entity list + state/country each⟩`
- Equity breakdown (%): `⟨per founder/employee/other + titles⟩`
- Taken any investment yet? `⟨Y/N + terms⟩`
- Monthly spend: `⟨$⟩` · Cash in bank: `⟨$⟩` · Runway: `⟨months⟩`
- Anything else about the company we should know? `⟨e.g., India-based team + planned US C-corp flip; patent pending — mention as a footnote, NOT a moat⟩`

---

## OTHERS / CURIOUS

### Other ideas you considered applying with.
> `⟨FOUNDER: YC sometimes funds a team on a listed alternate. Honest — but keep AegionAI clearly primary. If genuinely all-in on this, say "None — we're all-in on AegionAI."⟩`

### Something surprising or amusing one of you discovered.
> `⟨FOUNDER: real, short, human. A surprising finding from building the product works well (e.g., a class of agent action nobody expected to be dangerous).⟩`

### What convinced you to apply to YC? Encouraged by anyone? Been to YC events?
> `⟨FOUNDER: genuine. If a specific YC company/essay/founder prompted it, name it.⟩`

### How did you hear about Y Combinator?
> `⟨FOUNDER: factual.⟩`

---

## SUBMIT CHECKLIST (I can't submit for you — this is yours to do)
- [ ] **Resolve the SF-presence gate first** (the "where based after YC" answer) — if no founder can be in SF for the batch, stop here.
- [ ] Fill every `⟨FOUNDER: …⟩` with a real, honest answer — no placeholders shipped.
- [ ] Record + upload the 1-min video as **unlisted (not private)** YouTube; paste the URL.
- [ ] Confirm the 50-char line renders ≤50 in the live field.
- [ ] Sanity-check every number (revenue, users, equity, runway) against reality — YC verifies.
- [ ] Decide the Amazon-employment disclosure question (founder background / current employment) — your call; be consistent with what's public.
- [ ] Open **apply.ycombinator.com**, paste section-by-section, confirm live question wording matches, submit (late-Fall 2026 or Early Decision → Winter 2027).
- [ ] After submit: the one-pager ([yc-differentiation-onepager.md](yc-differentiation-onepager.md)) is your leave-behind / interview-prep for the "why not Salus?" question.

## Cross-references
- Positioning: [pitch/share/STRATEGY.md](../share/STRATEGY.md), [pitch/share/AegionAI-pitch.md](../share/AegionAI-pitch.md), [pitch/share/architecture-brief.md](../share/architecture-brief.md)
- Competitive basis (Salus twin verdict, cohort white-space): [pitch/internal/yc-2025-2026-competitive-scan.md](yc-2025-2026-competitive-scan.md)
- Product truth (built-vs-roadmap): [CLAUDE.md](../../CLAUDE.md), [lld/ARCHITECTURE.md](../../lld/ARCHITECTURE.md)
