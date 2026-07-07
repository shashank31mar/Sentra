# Security Co-Founder — Cold Outreach Drafts

**For:** AegionAI / Sentra founder · **Companion to:** [cofounder-search.md](../../cofounder-search.md) (profile, pools, search strings, vetting rubric)
**Date:** 2026-07-07 · **Status:** working drafts — never auto-send; personalize line 1 with a *specific* proof point before every send.

> **The one rule that makes or breaks these:** line 1 must reference something *they* did that you actually read — a merged PR, a named CVE, a conference talk, a Sigma/Cedar rule. Generic = ignored. The whole point of sourcing on GitHub/CVE/CFP archives first ([cofounder-search.md §3](../../cofounder-search.md)) is that you arrive with a real proof point, not a title match.

## The pattern (every draft obeys this)
- **Proof, not hype.** No "revolutionary / AI-native / next-gen." One concrete thing you built + one concrete thing they built.
- **Name the gap they'd own**, not a job description: detection science + the data flywheel + buyer credibility a bank CISO accepts.
- **Soft ask:** ~25 min, easy out, no pressure.
- **Sign "Founder, AegionAI."** No title inflation, no employer name-drop.
- **Honest staging.** What's live today = block-before-execute + deterministic Cedar/Sigma floor + append-only audit. ML is shadow. Don't claim more.
- **Never lead with "we block inline"** — that's the retired differentiator and an anti-signal to a real detection engineer.
- **Trial before equity.** The first call is a conversation, not a proposal. Equity talk only after a paid trial.

---

## 1 — Cold email: detection / threat-research engineer (the top archetype)

**Subject:** the detection layer of an agent-action firewall

> Hi [First name],
>
> I read your [Sigma PR to `rules/cloud/...` / write-up on behavioral detection of {technique}] — [one specific, honest sentence on why it stood out: e.g. "the way you scoped the condition to cut FPs without losing the TTP is exactly the discipline I'm missing"].
>
> I'm building AegionAI — a control plane that governs what AI *agents* are allowed to *do* (the parameters, the sequence, the identity behind an action), neutral across AWS/Azure/GCP. The enforcement floor is live: block-before-execute, a Cedar policy layer, deterministic signatures, append-only audit. It runs today.
>
> The layer I can't build alone is yours: the detection science. My signature corpus is small, the ML classifier is still shadow, and the "does the data flywheel actually compound" question is unmeasured. I'm a platform/infra builder — I'm looking for a **co-founder & CTO with a security background** who owns the corpus, the shadow→enforce graduation, and the continuous red-teaming, and who a bank's security team will actually believe.
>
> Not pitching a job — exploring whether the problem is interesting enough to you to talk. 25 min this/next week? If it's not your thing, no worries at all, and I'd still value a pointer to anyone you'd trust with it.
>
> — [Name]
> Founder, AegionAI

---

## 2 — Cold email: fintech / payments appsec lead (regulated-buyer credibility)

**Subject:** stopping the agent that wires $2M when policy says $50k

> Hi [First name],
>
> Your work on [product-security at {Razorpay/PhonePe/Stripe...} / the {specific talk or post}] is why I'm reaching out — you've lived the money-movement + [PCI / RBI / SOC 2] side that I haven't.
>
> I'm building AegionAI: a runtime control plane that governs AI-agent *actions* — evaluating what an action does (amount, destination, sequence, the identity behind it) and blocking the harmful one before it executes, neutral across clouds. The deterministic floor is live today; the audit trail is append-only.
>
> Two gaps I'm looking for a **co-founder & CTO** to own, and both are yours: (1) the detection/enforcement depth that makes this trustworthy on real money movement, and (2) the credibility a regulated buyer's security team signs off on — something a solo platform builder can't self-assert. This is a full-time co-founder conversation, not a hire.
>
> Worth 25 minutes to see if the problem grabs you? Happy to show the live interception. Easy no if the timing's wrong.
>
> — [Name]
> Founder, AegionAI

---

## 3 — Warm-intro request (send to the mutual, with a forwardable blurb)

**Subject:** intro to [Target]?

> Hi [Mutual],
>
> Quick one — do you know [Target Name] ([role] at [Company]) well enough to intro me? I'm looking for a **co-founder & CTO with a security background** and their [detection work / appsec background] is close to exactly what I need.
>
> Forwardable blurb below so it's zero effort — and total fine if it's not a strong enough tie.
>
> — [Name]
>
> ---
> *Forwardable:*
> *[Name] is building AegionAI, a control plane that governs what AI agents are allowed to* do *across any cloud — the enforcement floor is already live in production. He's looking for a co-founder & CTO (security background) to own the detection science and carry the buyer credibility. Thought of you given [Target]'s work on [X]. Worth a 25-min intro call?*

---

## 4 — Follow-up #1 (5–7 days after silence; softer, one *new* proof point)

**Subject:** re: [original subject]

> Hi [First name],
>
> Following up once, then I'll leave you be. Since I wrote, [one concrete new proof point — e.g. "we ran the deterministic floor against real Bedrock traffic on two clouds; the sequence-integrity check held" / "closed a cross-tenant authz gap and tightened the audit contract"]. The detection layer is still the open seat.
>
> If a 25-min conversation is interesting, I'll work around your schedule. If not, a name you'd trust with this would mean a lot.
>
> — [Name]

---

## 5 — Follow-up #2 (graceful close; keep the door open)

**Subject:** re: [original subject]

> Hi [First name],
>
> I'll stop here so I'm not a pest. If the timing's ever right — or you know the right person — my door's open. Genuinely admire [the specific work again]; thanks for building in the open.
>
> — [Name]

---

## 6 — Post-first-call: propose a scoped, paid trial (BEFORE any equity)

**Subject:** a small paid project before we talk equity

> Hi [First name],
>
> Really enjoyed that. Before either of us talks numbers, I'd like to actually build something together — it tells us both more than three more calls would.
>
> Proposal: a scoped 2–4 week paid project on a real slice. Pick one — (a) design + run a shadow→enforce graduation on the current pipeline and report the recall/FP readout, (b) expand the signature corpus against a held-out set and report the numbers, or (c) red-team the live pipeline and write up what gets through. The deliverable is a number + a judgment, not a doc. Paid at [rate], IP-assigned via a short consulting agreement.
>
> If it clicks for both of us, that's when the co-founder + equity conversation makes sense — with real signal behind it. Want me to write up the one-pager for whichever slice interests you?
>
> — [Name]
> Founder, AegionAI

---

## Before you send — 60-second checklist
- [ ] Line 1 names a **specific** thing they built (PR/CVE/talk/rule) — not their title.
- [ ] Credential **verified at primary source** already (NVD / contributor graph / CFP archive) — you're spending a real conversation, per [the rubric](../../cofounder-search.md).
- [ ] No overstated claims (ML is shadow; rollback is roadmap; "prod" is a demo account governing synthetic agents — don't imply live enterprise customers).
- [ ] Signed **"Founder, AegionAI"** — no employer, no inflated title.
- [ ] Logged in a per-person tracking sheet: name · archetype · proof-URL · status · next step.
