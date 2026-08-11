# Santosh Nair (SVP Cyber Risk, Bank of America) — Conversation 1-Pager

**Warm intro by Randy (your advisor). Goal: DISCOVERY, not pitch.** Learn how a top-4 bank thinks about governing AI — and where a control layer would actually help. Don't sell. Smart questions earn a second meeting and make Randy look good.

**Him in one line:** 17 yrs BofA cyber/risk; ran **vendor-risk assessments** (knows the exact bar to get a startup inside a bank); now owns **AI Risk Governance**; deep SOC/threat background (will see through "we detect prompt injection"). Lens = **regulation + provable, auditable control**, not ML cleverness.

> **THE FRAME — read this first.** The pitch is NOT "we let you replace the human." CISOs are actively rejecting that. Per the **Splunk/Cisco CISO Report 2026** (Oxford Economics, **n=650 CISOs**, mid-2025): **60% of CISOs disagree that agentic AI will even replace L1 functions** — *"the objective is augmentation and collaboration"* (p18), human oversight is *"paramount"* (p24). So your position is: **AegionAI is the guardrail that lets a human + AI team work together safely — the AI acts within limits you enforce, the human stays accountable, and the audit trail proves the human-in-the-loop control held.** Complement + reduce fatigue + keep the human in charge. NOT replace.

---

## Fintech background you need in your head (true, defensible facts)
- **Banks run "copilots," not "agents" today.** Production AI *drafts and suggests*; a human still decides/acts (JPMorgan LLM Suite ~230k staff, Morgan Stanley assistant, Goldman's Claude). None take real actions alone.
- **Autonomous action is rare + cautious.** JPMorgan (June 2026): its agents only *"close to clearing"* governance. A survey of 340 FS firms: **only ~5%** grant agents high autonomy on critical actions. Some pulled back (Klarna reversed AI-support).
- **CISOs want human + AI TOGETHER, not replacement** — the report's headline finding (60% reject replacement; augmentation is the goal). Their **#2 agentic concern is "lack of human oversight," #3 is accountability** — *"who's accountable when an agent makes a mistake?"* (p20).
- **They're drowning — the fatigue is real and measured:** ~two-thirds of security teams strained; **98% high alert volume, 94% false alerts** (p26–27). This is the "reduce fatigue / raise decision quality" opening.
- **The governance gap:** existing controls (IAM, maker-checker, SR 11-7) were built for **humans**. Nobody owns *what an AI is allowed to do* when it acts alongside a human — and US regulators haven't written agent rules yet (excluded agentic AI from April-2026 guidance).
- **Your honest position:** real, regulator-adjacent, but **early** — you help in the human+AI phase happening *now*, not only a future autonomous phase.

**Glossary:** *maker-checker* = two-person approval. *SR 11-7* = Fed rule to validate/control any model affecting decisions. *IAM* = who's allowed to do what. *In-VPC* = runs inside the bank's walls, data never leaves. *L1* = tier-1 security analyst.

---

## The conversation flow (4 moves — and how to pivot)

### Move 1 — OPEN: signal you're not naive, and not here to "replace humans" *(2 min)*
> "Thanks for the time — Randy speaks highly of you. Upfront: I'm not pitching. I'm trying to understand how a bank thinks about AI that takes actions. What struck me in the Splunk CISO report is that ~60% of CISOs *don't* want AI replacing analysts — it's augmentation, human-in-the-loop. Does that match how BofA is approaching it?"

**Why:** disarms the sales guard AND the "you want to remove my people" fear in one line, using his peers' own data.
**PIVOT →** he'll validate/nuance augmentation → go to Move 2 to find where the human+AI seam strains.

### Move 2 — LOCATE: where does human + AI actually work together, and where does it strain? *(8 min — mostly listen)*
- "Where is AI already in the loop with your analysts today — and where's it still purely a human call?"
- "The report shows huge alert/fatigue load (98% high volume). Where does *quality of the human decision* break down under that load — and is AI helping or adding noise?"
- "As AI moves from *suggesting* to *doing* — even small actions — where does your human-built governance (IAM, maker-checker, SR 11-7) stop covering you?"

**Why:** finds the real seam — not "will you replace humans" (no) but "where does the human+AI team need a guardrail." That's your product.
**Clusters to listen for (where your pain lands):** employee copilots (low pain) · customer-service (Klarna reversed) · software-eng agents (supervised pilot) · **agentic SOC / insider-risk (his seat)** · **money-movement (high pain, not GA)** · **back-office AML/underwriting/recon (high pain, mostly pilots)**. The high-pain clusters are the least deployed — you're hunting which (if any) is crossing pilot→action in *his* shop.
**PIVOT →** when he names a strain/gap ("we don't have a clean answer for X when the AI acts"), go to Move 3.

### Move 3 — DEEPEN: get the product spec + the moat, from him *(8 min)*
- **(product spec)** "When an AI *does* take an action alongside the analyst — what would it have to **prove it can't do** before your risk function is comfortable, with the human still accountable?"
- **(audit)** "The report flags needing a 'repeatable chain of evidence when agents make decisions' (p20). Is proving to a regulator that the human-in-the-loop control actually held a solved problem for you, or open?"
- **(neutrality test)** "Your SOC/cloud vendors ship their own agent guardrails. Is a **neutral** layer over the bank's *own* agents a real need, or covered?"
- **(recursive risk — his seat specifically)** "A high-privilege security / insider-risk agent is itself an attack surface — prompt-injection / excessive-agency (OWASP LLM01/LLM06). Is that on your radar, or still theoretical?" *(Present as well-grounded inference — NOT an observed bank incident.)*
- **(moat — his unique value)** "You've run third-party risk. What's the bar for a startup to be trusted **inline** on agent actions in a bank — SOC 2, pen test, data-residency, model-risk docs? What actually gets a small vendor through?"

**Why:** first answer = your product requirements; audit = your wedge in his words; last = your moat + GTM checklist.
**PIVOT →** if a real gap surfaced + he's engaged → Move 4. If lukewarm/"not near-term," don't force — ask who else owns this, thank him, exit clean.

### Move 4 — SOFT CLOSE: earn the next step, don't pitch *(2 min)*
> "Really helpful. Would it be useful to show you what we've built — as a guardrail for the human+AI setup, not a replacement — and get your reaction, maybe a deeper look with your team if it's relevant?"

Two-step (show → maybe deeper). Never "buy / be a design partner" on this call.

---

## Questions to EXPECT — and your honest, augmentation-framed answers
- **"Are you trying to take humans out of the loop?"**
  → "No — the opposite. Your peers in the CISO report are clear they want human+AI together. We're the guardrail that makes that safe: the AI acts within limits you set, the human stays accountable, and we produce the audit proving the human control held. We keep the human in charge, not remove them."
- **"How are you different from Zenity / Noma / CrowdStrike / my cloud vendor's guardrails?"**
  → "Those govern *their own* agent on *their own* cloud. We're **neutral** — over the bank's *own* agents, any cloud, **inline**, deployable **in-VPC** so nothing leaves your walls, with a tamper-evident audit for exams. Blocking isn't the differentiator — neutral + stateful + in-boundary is." *(Don't claim you uniquely block.)*
- **"Do any banks run this in production?"**
  → Honest: "Not autonomous money-moving agents — nobody does yet, per JPMorgan's own June-2026 statement. That's exactly why I'm talking to people like you — to learn when that line moves and what you'd need first."
- **"You're seed-stage — why would a bank trust you inline?"**
  → "The real question, and why I'm asking about the vendor bar. SOC 2 Type II in progress; in-VPC means we never hold your data. What else would we need to clear?"
- **"Isn't a good fraud model + a human reviewer already enough?"**
  → "For today's flow, maybe. My question is what changes as the AI starts *acting* with the reviewer, not just scoring for them — what bounds what it can do, and how you prove the human stayed in control. Is that a near-term concern for you or still far off?" *(Tests your own thesis — let him answer.)*
- **"What exactly do you do?"** (if asked, THEN explain — one sentence)
  → "We sit in front of an AI agent's action, check what it's about to do — the parameters, the sequence, who authorized it — and block the harmful one before it runs, across any cloud, inside your environment — so a human+AI team can move faster without the AI doing something it shouldn't."

## Claims to AVOID (cost credibility instantly)
- Don't frame it as **replacing humans** (the report says CISOs reject that — this is the big one now).
- Don't call copilots "agents" (LLM Suite / Morgan Stanley / BNY Eliza = copilots).
- Don't say banks run autonomous money-moving agents in production — they don't.
- Don't cite Klarna as a win (reversed); don't present crypto/demo hacks as bank breaches.
- Don't claim any agent-security vendor is proven in a bank, that you *uniquely* block, or that US regulation already governs agent actions.
- Don't overclaim the CISO report backs your *mechanism* — it backs the human+AI thesis + oversight + audit need, NOT runtime action-blocking specifically. Cite it as "what your peers want," present blocking as your answer.

## Right after the call — write down:
1. Where does human+AI already work together at BofA, and where does it strain?
2. Is BofA in the ~5% letting agents act at all? Which workflow?
3. What must an AI *prove it can't do* to act alongside a human? *(= product spec)*
4. Is "prove the human-in-the-loop held, to a regulator" an open problem? *(= audit wedge)*
5. The vendor-risk bar to get inline in a bank. *(= moat + GTM)*
6. Did "neutral + in-VPC + augment-not-replace" land, or did he push back?

---
*Sources: Splunk/Cisco **CISO Report 2026** (Oxford Economics, n=650, mid-2025) — pp. 18–20, 24, 26–27, 32. Banking-adoption facts from the 14-agent banking brief (triangulated to bank press releases / Reuters/CNBC / OWASP / OCC-Fed). Honor the claims-to-avoid list — it's the credibility gate.*
