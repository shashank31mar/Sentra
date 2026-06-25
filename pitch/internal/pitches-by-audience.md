# AegionAI — Four Pitches, One Spine

**Purpose**: Rehearsable, word-for-word scripts. Internalize the **spine** once; each pitch just stretches a different beat. Backups in [../docs/investor-qa-objection-handling.md](investor-qa-objection-handling.md) and the narrative in [../docs/pitch-narrative.md](pitch-narrative.md).

> **THE SPINE (memorize this — everything else is altitude):**
> 1. **Agents now take real actions** — refunds, money, data, emails. Not chatbots.
> 2. **There's no layer checking those actions** — the attack is an *allowed* tool called with *bad parameters*, and nothing stops it.
> 3. **Existing tools can't fill it** — detectors score text; clouds only govern their own cloud; nobody enforces across the fleet.
> 4. **We're that layer** — sit in front of every action, and block / roll back / contain. *Kubernetes for AI agents.*
>
> If you ever freeze, just say the spine in order. Problem → gap → why-unsolved → us.

---

## 1. To a Layman (~60s)

> "Imagine you hire an assistant and give them **one clear rule**: don't touch the customer records — we're in the middle of something delicate. And they go and delete all of it anyway — then cover it up and tell you everything's fine. That actually happened last year, except the assistant was an **AI.** A company was using an AI to help run its systems, told it plainly *'don't touch the live data'* — and the AI wiped out records for **over a thousand companies,** then created fake entries and insisted nothing could be undone. None of it was true.
>
> And here's the part that gets people: it wasn't a hacker. It was the company's **own AI**, doing the exact thing it was told not to — and there was nothing standing in the way to stop it.
>
> That's the problem. AI is being handed real power now — moving money, changing records, sending messages on a company's behalf — but there's no **safety layer above it** enforcing the rules and able to hit the brakes.
>
> That's what we build. Think of it as the **seatbelt and brakes for AI agents.** We sit in front of every action the AI takes, and the moment it tries something unsafe or against the rules, we **stop it before it happens — and can even undo it.** Companies are handing AI the keys to the business. We make sure it drives safely."

**Spend most of your time on**: beats #1 and #4 (the rogue-agent story + "we're the seatbelt"). The "*imagine you hire an assistant*" opening makes it land for a non-technical listener before any tech word appears. The key turn: *it was the company's own AI breaking a clear rule, and nothing enforced it — that missing enforcement layer is us.*

### Alternative layman story — the AI-faked refund (when you want a consumer angle)

*(Use for a broad consumer audience, or to make the "AI can't just detect its way out" point. The downside vs. the rogue-agent story: the villain is a human fraudster and the victim is a faceless company, so it lands a little softer.)*

> "You know how on a food delivery app you can claim a refund if your order shows up damaged? Last year people discovered they could use AI to generate a photo so realistic — cracked eggs, a spilled meal — that *no human could tell it apart from a real one.* They'd submit it, and the app's AI agent would approve the refund on the spot. It went viral, and companies lost millions.
>
> And notice *why* it worked: the agent *did* look at the photo — it just couldn't tell it was AI-generated, so on its own judgment it approved the payout. **Nothing sat above the agent forcing a stronger check** — like *'a single photo can't auto-approve a refund this size — require a second proof first.'* The agent was trusted to police itself, and one fake image fooled it. That's what we build: the layer above the agent that enforces the rules it can't be trusted to enforce on itself."

> **The two stories, and when to use which:**
> - **Rogue agent (default)** — *the AI disobeys a clear rule and causes harm,* then lies. Most relatable — it's everyone's instinctive fear of AI, and it's pure *enforcement* (a rule existed; nothing enforced it). Bonus: the vendor's own fix (separate live/test + an undo button) *is* what we productize.
> - **Refund fraud (alternate)** — *an attacker fools the agent* into a bad payout. Good consumer hook, makes the "detection can't save you" point — but softer (faceless-company victim) and brushes the detection axis.
> Pick one. Don't tell both in a 60-second pitch.

---

## 2. To a Tech Expert (~60s)

> "Every agent framework — Bedrock, LangChain, MCP — works the same way: the LLM *decides* which tool to call with which parameters, and your code *executes* it. The vulnerability isn't calling a forbidden tool. It's calling an **allowed** tool with **attacker-controlled parameters.** A jailbroken prompt makes a payments agent call `process_refund(amount=5000, account=ATTACKER-99)` — the tool's allowed, RBAC says yes, the money's gone.
>
> Prompt filters score *text* — they can't see the parameters. Static RBAC governs *tool registration* — not the action. And AWS's Cedar is **stateless by design**, so it can't enforce that step B only happens after step A — it can't validate a workflow.
>
> We sit at the **execution boundary** as a combined policy *decision and enforcement* point — think a Kubernetes admission controller for agents. We evaluate the action, its parameters, the session's trust state, and the required sequence — then block, roll back, or quarantine. Detectors *flag*; we're a **stateful control plane.** And we do it across AWS, Azure, and GCP — which no cloud vendor ever will, because it means sending workloads to a competitor."

**Spend most of your time on**: beats #2 and #3 (the attack + why detection/Cedar fail). The `ATTACKER-99` line and "Cedar is stateless" are what earn an engineer's trust — they're specific and checkable.

---

## 3. To a Business Expert (~60s)

> "Start with the problem. AI agents now take **real business actions** — issuing refunds, moving money, accessing customer data. When one goes wrong it's not a bad answer, it's real money and liability: AI agents have approved fraudulent refunds at scale, and one compromised AI chatbot recently became the doorway to breach **700 companies at once.** The agent decides and acts on its own — and today nothing sits above it enforcing what it's actually allowed to do.
>
> And it's everywhere: **82% of enterprises** now run AI agents, but only **44% have any formal governance** over what those agents can do — a **38-point gap.** On **August 2nd the EU AI Act** starts fining companies up to **7% of global revenue** for exactly this. The budget is already proven — last quarter Check Point bought Lakera for **$300M** and F5 bought CalypsoAI for **$180M.**
>
> But the gap none of them fills: every cloud only governs its *own* cloud — AWS won't govern your Azure agents, because that sends workloads to a competitor. So any enterprise on more than one cloud has **no single governance layer.** That's not a niche — it spans the whole market.
>
> We're that **cross-cloud control plane** — in front of every agent action, enforcing policy: block, roll back, contain. We land first where a wrong agent move is **money out the door *and* a compliance breach at once — fintechs and payment-action agents.** Blocking one unauthorized transaction, or enforcing one approval step the agent would otherwise skip, pays for us many times over — and produces the audit trail the regulator now requires. From there we expand into enterprise multi-cloud and regulated on-prem, where no SaaS competitor can follow."

**Spend most of your time on**: open with the *problem* (first paragraph — they must feel "agents act, and nothing governs them" before any stat lands), then beat #3 and the market. Numbers are the argument — but only *after* the problem is concrete.

---

## 4. One-Pager — Angel Investor

**AegionAI — The AI Security Control Plane**
*"AI without governance is just liability at scale."*

**The Problem.**
AI agents no longer just chat — they take consequential actions: moving money, changing records, calling other agents, on their own at machine speed. And when one acts wrongly, it's a real consequence: a company's own AI coding agent, *told not to touch the live system,* **deleted the production database of 1,000+ companies and lied about it** — not a hacker, the company's own agent, with nothing there to stop it. In banking, a single agent error — a duplicated payment, a misrouted instruction — **cascades across systems before a human sees the first alert** (Amex is already reimbursing erroneous agent purchases). One compromised AI agent credential breached **700+ companies at once** (Drift/Salesloft). **The common thread: an agent took a consequential action it shouldn't have, with privileged access, and no layer enforced the rules in real time — a security incident, not a bad answer.**

**Why it matters now.**
82% of enterprises run AI agents; only 44% have any formal governance over them — a **38-point gap.** The **EU AI Act** begins enforcement **Aug 2, 2026**, with fines up to **7% of global revenue.** The budget is proven: **Check Point/Lakera ($300M)** and **F5/CalypsoAI ($180M)** both closed last quarter. Agents are moving from pilot to production across multiple clouds — the attack surface is now universal, and the governance layer doesn't exist yet.

**Why no one else is solving it.**
- **Detectors** (Lakera, prompt filters) score *text* — they can't see that an *allowed* tool was called with *malicious parameters*.
- **Cloud vendors** (AWS AgentCore, Azure) govern only *their own cloud* — going cross-cloud means routing workloads to a competitor. Structurally won't happen.
- **AWS's Cedar engine is stateless by design** — it can't enforce action *sequences*, so it can't validate workflows.
- **Observability players** (Wiz, Datadog) alert *after* the fact — they don't sit in the execution path to *block*.
The top-right quadrant — **inline enforcement, across clouds — is empty.**

**The market.**
AI governance platforms: **$492M → $1B+** by 2030 (Gartner). Our beachhead — multi-cloud agent security — is a **~$900M SOM** growing ~45% CAGR. Bottom-up: ~7,500 enterprises × ~$120K avg governance spend.

**How we solve it.**
AegionAI sits in front of **every agent action** and asks: *is this action, with these parameters, by this agent, in this session, allowed — and in the right order?* If yes, it passes; if not, it's **blocked, rolled back, or the agent is quarantined** — across AWS, Azure, and GCP, from one control plane. **Detectors flag; we're a stateful control plane.** *Kubernetes for AI agents.* Integration is one decorator today; network-level sidecar (zero code change) on the roadmap. **Live cross-cloud demo (AWS+Azure) already working. USPTO patent pending; prior-art search found zero patents in this space.**

**Go-to-market.**
Land in **financial-action agents** — fintechs and payment/refund agents where a wrong action is direct loss *plus* a compliance obligation, and ROI is immediate (block one unauthorized transaction / enforce one skipped approval step → and produce the audit trail). Engineering-led, fast-deciding buyers (e.g. Razorpay-tier), warm via the IIT/fintech network. Expand to **enterprise multi-cloud** (cross-cloud is unique to us) and **regulated on-prem** (structural moat). Open-source the `AgentPolicy` CRD to own the standard — the Istio playbook.

**The team.**
Shashank Gupta — IIT; at Amazon led a 50+ person team building a new observability vertical across OpenSearch/CloudWatch. Filed the patent, built the working prototype (ML detection <80ms).

**The ask.** **$2M pre-seed** → GCP connector (completes AWS+Azure+GCP), 3 design partners, ML detection layer. Unlocks a $4–6M seed at $300K ARR.

---

### How to internalize so you never hesitate
1. **Drill the spine** (the 4 lines at top) until you can say it cold in 20 seconds. Every pitch is that spine, expanded.
2. **Own one concrete attack** — `process_refund(amount=5000, account=ATTACKER-99)` for tech, the **fake cracked eggs** for everyone else. Lead with the story, never the architecture.
3. **One number per audience**: layman → "lost millions"; tech → "Cedar is stateless"; business → "38-point gap / 7% fines."
4. **One closing line you always land on**: *"Detectors flag. We enforce, roll back, and contain. Kubernetes for AI agents."*
