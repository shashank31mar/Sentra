# Paul Rix — Call Prep (TODAY, 2026-07-07)

**Track:** Investor / connector (warm — via Randy) · **Artifact OK to share:** [AegionAI pitch](../share/AegionAI-pitch.md) + the 3-mode architecture slide.
**Companion prep:** the objection cheat-sheet [investor-qa-objection-handling.md](investor-qa-objection-handling.md) is the doc to skim (Part B = investor grill). [rutvik-call-prep.md](rutvik-call-prep.md) is Zafar-specific (a *response to his critique*) — NOT for Paul; only borrow its crisp answers.

---

## Who is Paul (so you walk in informed)
- **Serial tech entrepreneur, 25+ yrs**, based Markham, Ontario (LinkedIn says US — likely both). *[me.sh, LinkedIn]*
- **Founder & CEO of Zanaris** (since 2015) — **managed services, cloud management, DevOps**. *[zanaris; podcast]*
- **Founder of Global Private Cloud Network (GPCN)** — "connects a trusted network of **private cloud providers**, secure compute from **Tier-3 data centers, 99.99%** guarantees." Theme: **private cloud + data sovereignty** (incl. Canadian data-residency). Speaking at **#DTX Jan 2026**. *[knightzgroup.com/gpcn; GPCN LinkedIn]*
- **Investor status:** no confirmed personal angel/VC track record — engages with startup-investing content. **Treat as operator-exec / potential angel / connector**, same as Randy. He + Randy + Jeff are one **Charlotte/GPCN/COO-Forum operator cluster.**

**What this means:** he is a **cloud-infrastructure operator**, not a security specialist and not an institutional VC. He'll evaluate you on *"is this real, does it fit how enterprises actually run infra, and do I know people who'd want it or back it."* Speak infra + data-sovereignty, not detection science.

---

## The angle that lands with HIM (lead here)
His whole world — GPCN, private cloud, Tier-3, data sovereignty, Canadian residency — **is your in-VPC / air-gapped / "data never leaves the boundary" story.** Most agent-security tools are SaaS-only and structurally can't do that. Open on the overlap:

> "You've built GPCN on the idea that regulated data should stay in the customer's own boundary — private cloud, sovereign, not someone else's SaaS. That's *exactly* the constraint that makes securing AI agents hard: the agent takes real actions on sensitive systems, and the tools that govern it are all SaaS that phone home. We run **in the customer's VPC and air-gapped** — nothing leaves. And we're neutral across AWS/Azure/GCP/on-prem, which no cloud vendor will ever be."

That one paragraph puts you on his home turf and states the differentiator he'll instinctively value.

---

## How to start (first 3 minutes)
1. **Warm open:** "Randy spoke highly of you — thanks for making time." (Randy is the tie; honor it.)
2. **One line on why you're talking:** "Randy thought our worlds overlap — you run private-cloud infrastructure for people who can't put data in public SaaS; I'm building the security layer for AI agents that has to run *in* that kind of boundary."
3. **The data-sovereignty bridge** (above).
4. **Then the 60-sec spine** (from [pitch-narrative.md](pitch-narrative.md), cleaned): agents now take real actions → nothing checks the *action + its parameters* → we're the enforcement layer that **blocks it before it executes**, neutral across every cloud. Use the concrete attack: *"a payments agent tricked into `process_refund(amount=5000, account=ATTACKER-99)` — the tool's allowed, RBAC says yes, money's gone. We check the action, not just the text."*

Keep it conversational — he's an operator, not a panel. Let him interrupt.

---

## Questions to KEEP READY (ask him — this is discovery, not just pitch)
These pull real signal AND flatter his expertise:
1. **"When your GPCN customers start running AI agents on their private cloud — what's their biggest fear about what the agent could actually *do*?"** ← free customer-discovery from someone close to your regulated buyer.
2. **"Are any of your customers already deploying agents that take real actions — deploys, data changes, payments — or is it still chatbots for them?"** ← gauges whether GPCN itself is a design-partner *channel*.
3. **"In your world, who owns this decision — the platform/infra team or the security team?"** ← validates your engineering-led-buyer thesis.
4. **"Does 'nothing leaves the boundary' actually move deals for your customers, or is it a nice-to-have?"** ← tests how load-bearing your in-VPC differentiator really is.
5. **(soft, near the end)** "Given what you see across your network — who should I be talking to, and would something like this interest you to be involved in?"

---

## The ASK (soft, 3 tiers — let him self-select)
1. **Validation:** "Does this resonate with what you see in the private-cloud world?"
2. **Involvement:** "Would you want to be involved — as an angel or an advisor?"
3. **Intros (always close on this):** "Who else in your network — GPCN customers, COO Forum, Randy's circle — should I be talking to?" A warm network only compounds if you keep pulling.
- **Bonus if he's technical enough:** feel out a **GPCN design-partner / channel** angle — could a GPCN customer running action-agents be an in-VPC design partner?

---

## Honesty guardrails (hold these live — you just fixed them in the docs)
- Say **"block before it executes,"** NOT "roll back" — rollback is roadmap (B7 in the cheat-sheet).
- **Don't imply live enterprise customers** — "prod" is a demo governing synthetic agents; you're **pre-revenue, actively recruiting design partners**. Randy saw the real docs → stay consistent.
- **In-VPC <100ms / air-gapped is the TARGET/design**, not a deployed benchmark — describe it as the architecture, honestly. (Today's Serverless path is ~0.6-1.2s.)
- **Solo-founder question** (if it comes up): own it — *"They won't trust a solo founder intercepting transactions yet — that's why my #1 use of this round is a security co-founder with the credentials a bank accepts. I build the plane; I need the credentialed co-pilot."* (B11.)
- **Don't lead with the patent** as the moat (B10) — neutrality + data-residency + switching cost is the real story.

---

## Do / Don't
- **Do** lead with data-sovereignty/in-VPC — it's his language and your genuine edge.
- **Do** run it as a two-way conversation; ask his read of the private-cloud buyer.
- **Do** end on a concrete next step: "Can I send the one-pager, and would you point me to anyone in your network?"
- **Don't** dive into detection science / ML internals — not his domain, not the hook for him.
- **Don't** overclaim (rollback, live customers, latency-as-shipped).
- **Don't** treat him as an institutional VC with a full diligence pitch — he's an operator/connector; keep it high-level and relational.

## After the call — capture in [outreach-tracker.md](outreach-tracker.md) #12
Interest level · does he invest personally · names he'd intro · any GPCN-customer design-partner angle · his read on whether "data never leaves the boundary" moves deals.
