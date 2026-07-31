# AegionAI — Design-Partner Reachout Batch 2 (week of 2026-07-27)

**Next 10 uncontacted targets** — verified contact + calibrated outreach (what they do · agent action · contact · warm path · connect note + InMail). Excludes the 20 already in [outreach-tracker.md](outreach-tracker.md). Same discipline as batch 1: idea-led subjects (no 'design partner' in subject; no 'guardrails'), explicit-but-soft ask, honest staging, sourced hooks.

> **Verify-before-send flags:** contacts marked *likely/unverified* on the LinkedIn URL need a 30-sec confirm on click. Two contacts have NO verified slug (Taktile, Vic.ai) — find + confirm before sending.

---

## 1. Commure · priority: **high** · contact-confidence: verified-2026

**What they do:** AI-native healthcare revenue-cycle-management and clinical-ops platform ("turn labor into software") formed by the 2023 Commure–Athelas merger; ~$70M raise at a ~$7B valuation (General Catalyst-led), integrates 60+ EHRs, ~$25B+ annual claims, customers include Mount Sinai and Yale New Haven [commure.com; merger reporting; Wikipedia/Crunchbase leadership].

**Agent action we'd govern:** Commure RCM's Denial Management agent bulk-resubmits corrected denied/rejected claims to payers (a "Bulk Resubmit" action; a "Denial Copilot" that auto-corrects future claims), plus Autonomous Coding that assigns ICD-10/CPT and writes charges — actions that write to billing/EHR and push claims out to payers at ~$25B+ annual claim volume. Degree of unattended execution is not fully confirmed (marketing mixes "auto-corrects"/"set it and forget it" with "Copilot" framing).

**Contact:** Dhruv Parthasarathy — Chief Technology Officer, Commure & Athelas  ·  https://www.linkedin.com/in/dhruv-parthasarathy-0b29b658
  *Buyer note:* Yes — as CTO of the combined entity with an ML/computer-vision background (Athelas), Dhruv owns both engineering and the AI-agent stack, so he's the right eng-led first contact for a runtime action-layer conversation. A secondary buyer, if one exists, would be a Head of AI Platform or Head of RCM Engineering; CEO/co-founder Tanay Tandon (linkedin.com/in/tanaytandon) is a fallback but less technical-first for this pitch.

**Warm path:** cold — no verified warm intro. Possible (unverified) investor/community paths: Commure is backed by General Catalyst, Sequoia, NVIDIA, Y Combinator, 8VC; if AegionAI shares any investor or a YC tie, that could warm it. Do not claim one without confirming.

**① Connect note:**
> Dhruv — Commure's denial agent bulk-resubmits corrected claims straight to payers, writing to billing at real volume. I'm building a neutral runtime layer that checks each agent action (codes, params, resubmit) before it executes — worth comparing notes? — Shashank, Founder AegionAI

**② InMail** — subject: `A per-action check before the bulk-resubmit writes to billing`

Hi Dhruv,

Commure's RCM denial agent bulk-resubmits corrected claims straight to payers, and the Denial Copilot auto-corrects future claims — actions that write to billing/EHR and push claims out at real volume across systems like Mount Sinai and Yale New Haven. As that moves further toward autonomy, the failure mode isn't a bad prompt — it's a wrong *action* committing: a miscoded charge, a claim resubmitted at the wrong amount or to the wrong payer, a bulk op that fans out wider than intended. Content/prompt filters don't catch that; it lives in the action's parameters, sequence, and identity.

I'm building AegionAI Guard: a neutral runtime control plane that governs the actions agents take — a per-action check on parameters, sequence, and identity that runs at the enforcing point right before the action commits (block-before-execute), with a tamper-evident audit trail. Neutral across vendors (AWS and Azure today), which matters if any coding/claims work runs off your primary cloud.

Honest on where it is: the deterministic action-layer checks and append-only audit are live; ML detection is still in shadow; and I don't have enterprise logos yet — I'm early and looking for a couple of design partners to build this with.

Would Commure be a fit, or worth 20 minutes to find out? Easy no if the timing's off.

— Shashank / Founder, AegionAI
aegionai.ai

*Do-not-claim: Don't claim Commure's coding/claims agents run fully unattended — bulk-resubmit and auto-correct are advertised but the human-in-the-loop degree is unconfirmed (Copilot framing). · Don't claim Dhruv Parthasarathy is a co-founder — only CEO Tanay Tandon and COO Deepika Bodapati are labeled founders in sources; Dhruv is CTO. · Don't claim AegionAI has any healthcare/enterprise customers, HIPAA/SOC 2 certification complete, or PHI-handling attestation — none exist yet. · Don't claim GCP support or in-VPC/air-gapped editions are live — roadmap only (AWS + Azure today).*

---

## 2. Infinitus Systems · priority: **high** · contact-confidence: verified-2026

**What they do:** Healthcare voice AI (agent branded "Eva") that automates phone calls between providers, payors, and patients — benefit verification, prior authorization, claims, and enrollment/patient-support — running on Google Cloud. 8M+ calls / 200M+ minutes automated; knowledge graph built from 4M+ calls. Raised $102.9M total (Series C $51.5M led by a16z, Oct 23 2024, "on the strength of AI guardrails," with GV, Kleiner Perkins, Coatue, Memorial Hermann). Products: AI agents + copilots, Studio (no-code agent builder), Lens (conversation analysis), Clinical Escalations. [Sources: infinitus.ai; prnewswire Series C release; mobihealthnews; prnewswire Google Cloud release Aug 2023; Neo4j customer story]

**Agent action we'd govern:** Eva places and conducts outbound payor/provider phone calls — navigating hundreds of conversational turns over hour-long calls — to collect and relay benefit-verification, prior-authorization, and claims data, with the outcome fed back for the provider's reimbursement workflow. Honest on autonomy: Infinitus uses "human-in-the-loop guardrails" and a copilot model; e.g., FastTrack "waits on hold on behalf of reimbursement specialists" then drops a human in "once a live payor agent answers." So NOT fully unattended end-to-end today. The consequential "wrong action" risk (sharper as calls move toward autonomy): confirming the wrong plan/coverage or submitting a prior-auth with the wrong member ID/parameters — an action-level failure distinct from a wrong spoken word.

**Contact:** Shyam Rajagopalan — Co-founder & CTO (site title: "Founder + Technology Lead")  ·  https://www.linkedin.com/in/shyamsundarr
  *Buyer note:* Yes — Shyam Rajagopalan (co-founder/CTO) is the right eng-led first contact for a founder-to-founder cold note. NOTE: the task's guess "Ankit Gupta?" is wrong on two counts — the CEO/co-founder is Ankit JAIN (not Gupta), and the technical buyer is Shyam Rajagopalan. A strong alternate technical entry is Gurudutta Ramanathaiah ("Guru"), Engineering Lead and author of the GhostEdit post — most topic-matched, good for a follow-up or if Shyam doesn't respond.

**Warm path:** Cold. Possible investor-warm paths if Shashank has any connection: a16z (Series C lead) or GV/Google Ventures (existing investor). No confirmed warm intro identified — treat as cold.

**① Connect note:**
> Shyam — GhostEdit nails that voice-agent safety is a runtime problem, not a prompt one. I'm building the adjacent piece: a neutral runtime layer for the *action* Eva takes — the parameters/sequence when a call resolves into a benefit or prior-auth outcome. Worth comparing notes? — Shashank

**② InMail** — subject: `Governing the action Eva takes on a payor call, not just the words`

Shyam —

Your team's GhostEdit write-up — a real-time layer checking each spoken response against grounded knowledge before the caller hears it — is the clearest statement I've seen that voice-agent safety is a runtime problem, not a prompt one. (You were upfront that it's still a controlled test, not live in conversations — but the framing is right.)

I'm building the adjacent piece: a neutral runtime layer that governs what the agent *does*, not what it says. When an Eva call resolves into a benefit-verification or prior-auth outcome — a value confirmed back to a payor, a record written into a provider system — that action has parameters, a sequence, and an identity behind it. GhostEdit catches a wrong spoken copay; a wrong *action* (confirming the wrong plan, submitting a prior-auth with the wrong member ID) is a different failure — and it gets sharper as these calls move from copilot toward autonomy.

What we do: a deterministic per-action check — parameter bounds, sequence integrity, identity — that blocks before execute, plus a tamper-evident audit trail. It runs as an in-process check inside your own environment, neutral across clouds. Honest on stage: the deterministic floor and the append-only audit are live; ML-based detection is still in shadow; and we don't have enterprise logos yet — this is early, running on design-partner accounts.

I'm looking for a couple of design partners to build this with. Would Infinitus be a fit, or worth 20 minutes to find out? Totally fine if it's not the right time.

— Shashank / Founder, AegionAI
aegionai.ai

*Do-not-claim: Do NOT say Eva executes fully unattended / autonomously end-to-end — Infinitus uses 'human-in-the-loop guardrails' and a copilot model (bunq 'Finn moves money' lesson); frame as 'moving toward autonomy'. · Do NOT claim GhostEdit is live/in production — Infinitus explicitly states it is 'not in deployment for our live conversations' (a controlled experiment). · Do NOT use the word 'guardrails' anywhere — even though Infinitus and the press use it heavily. · Do NOT claim we run natively on Google Cloud or have a GCP connector — GCP is roadmap; only the in-process SDK path is cloud-agnostic. Infinitus runs on Google Cloud.*

---

## 3. Taktile · priority: **high** · contact-confidence: verified-2026

**What they do:** Taktile is an "agentic decision platform" for financial institutions (customers include Mercury, Monzo, Brex, Finom, Kueski) whose AI agents automate credit underwriting, AML/fraud investigation, and KYC/KYB onboarding — explicitly "blending AI speed with human oversight" rather than running fully autonomously. Sourced: taktile.com/about + Taktile articles (Agentic AML, Financial Spreading Agent, Onboarding Agents).

**Agent action we'd govern:** Specialist agents that triage AML alerts, draft SARs, run adverse-media/transaction-monitoring checks, spread borrower financials into credit underwriting, and disposition onboarding/KYB cases. Honest on autonomy: Taktile is human-in-the-loop by design ("Accountable by design," "zero black boxes," configurable human touch-points), so today the agents recommend/prepare and accelerate the work rather than unilaterally approving/denying credit or closing alerts unattended — but their own content frames the live question as "how [institutions] can still control decisions as agents increasingly automate them." The wrong-action risk (a mis-dispositioned alert, an auto-closed case, a bad credit push) grows precisely as these move toward autonomy — the action layer, not the reasoning, is where it bites.

**Contact:** Dr. Maximilian Eber — Co-Founder & CPTO (Chief Product & Technology Officer)  ·  ⚠️ LinkedIn unverified — find + confirm before send
  *Buyer note:* Yes — right eng/technical-led first contact. No separate CTO exists; Eber is the co-founder who owns product + technology (CPTO), so he's the correct first touch for an architecture / design-partner conversation. If no response, escalate to eng leadership listed on taktile.com/about: Dr. Robin Raymond (Principal Engineer) or Adrian Buzgar (Engineering Director). CEO Maik Taro Wehmeyer is the alternative co-founder but less fit for a technical enforcing-point discussion.

**Warm path:** cold — no verified warm path found. Possible angle worth checking on your side: Taktile is a Y Combinator alum (S20) and Index/Tiger/Balderton-backed; if AegionAI has any YC or shared-investor connection, that would beat a cold InMail. Do not assert one without confirming.

**① Connect note:**
> Maximilian — Taktile's agents now triage AML alerts, draft SARs and spread financials into credit decisions. As those actions get more autonomous, I'm building a neutral runtime check on what an agent is allowed to do + a tamper-evident audit, independent of the reasoning layer. Worth 20 min?

**② InMail** — subject: `An independent check on the action your agents take, not the reasoning`

Hi Maximilian,

Taktile's agents now triage AML alerts and draft SARs, spread borrower financials into credit underwriting, and disposition KYB onboarding for the likes of Mercury and Brex — work that used to be fully manual, now increasingly automated with human oversight. Your own writing frames the open question for institutions as how they keep control of decisions as agents automate more of them. That control question is exactly what I'm working on.

I'm building AegionAI Guard: a neutral runtime control plane that governs the action an agent takes — checking the parameters, sequence, identity and authorization of each action and stopping a bad one before it executes, with a tamper-evident audit trail underneath. It sits independent of the reasoning layer — not another model second-guessing the decision, but a deterministic enforcing point on what the agent is allowed to do — and it's cross-vendor by design rather than tied to one cloud. Different problem from content/prompt filtering, and complementary to identity — it's about the action itself.

Honest on stage: the deterministic action-layer checks and the append-only audit are live today; the ML detection is still running in shadow; and there are no enterprise logos yet — right now it's demo and design-partner accounts running against synthetic agents. That's the whole reason I'm reaching out this early.

I'm looking for a couple of design partners to build this with — ideally someone whose agents already act on the money-movement and compliance path, which is squarely you. Would Taktile be a fit, or worth 20 minutes to find out? If it's not for you, no worries at all — even a pointer to the right person on your team would help.

— Shashank / Founder, AegionAI
aegionai.ai

*Do-not-claim: Do NOT claim Taktile's agents autonomously approve/deny credit or close AML alerts/SARs without a human — their model is explicitly human-in-the-loop ('blending AI speed with human oversight'). Frame as moving toward autonomy, not already unattended (the bunq/Finn lesson). · Do NOT imply Mercury, Monzo, or Brex are AegionAI customers — they are Taktile's customers, named only to source Taktile's real deployments. · Do NOT claim AegionAI has enterprise logos or production traffic — 'prod' is demo/design-partner accounts on synthetic agents. · Do NOT claim GCP support or in-VPC/air-gapped editions are live — roadmap only. AWS + Azure today.*

---

## 4. incident.io · priority: **high** · contact-confidence: verified-2026

**What they do:** Incident-management platform (on-call, incident response, status pages) built by an ex-Monzo team; its "Investigations" AI SRE agent triages alerts, finds root cause, pinpoints the breaking PR, and drafts a fix + opens a pull request from Slack via a "Code it up" button. [incident.io/investigations, incident.io/ai, incident.io/building-with-ai]

**Agent action we'd govern:** The Investigations / AI SRE agent generates a code fix and opens a pull request from Slack when a human clicks "Code it up"; it also recommends the command to run and who to escalate to (recommends — does not execute commands, doesn't merge/deploy). So today it's human-in-the-loop: the PR-open is user-triggered and the PR still needs human review + merge. But incident.io's published "timeline to fully automated incident response" states the roadmap explicitly moves from "AI agents that investigate WITH you" (this year) to "resolve incidents FOR you" (next year) — offering to "do the next steps on your behalf at the click of a button." The wrong-action risk lives in the fix/PR contents (wrong repo/service/params) and the future auto-resolve steps — not in the prompt. Do NOT claim it merges code or runs prod commands unattended today.

**Contact:** Lawrence Jones — Product Engineer (hands-on builder of the AI SRE / Investigations agent; also a founding engineer) — title from secondary sources, current employer verified live  ·  https://www.linkedin.com/in/lawrence2jones
  *Buyer note:* Lawrence is the ideal engineer-to-engineer FIRST touch: he's the hands-on builder of the AI SRE agent, blogs publicly on LLM prompt latency and their AI tooling, and has a verified, reachable LinkedIn. He is an IC, not the economic buyer. The AI-architecture owner / decision-maker is CTO Pete Hamilton (authored "Weaving AI into the fabric of incident.io") — but I could NOT verify his LinkedIn slug, so I did not guess one. Co-founder & Field CTO Chris Evans (verified https://www.linkedin.com/in/evnsio) owns the "ironies of automation" thesis and is another strong door with a verified profile. Recommended play: open engineer-to-engineer with Lawrence to earn a champion, then escalate to Pete Hamilton / Chris Evans for the actual buying conversation.

**Warm path:** Cold. Investors: Insight Partners (led the $62M Series B, Apr 2025, ~$400M valuation), Index Ventures, Point Nine, Mantis VC, plus angel Mike Krieger — no personal connection identified. Note: Lawrence publicly offers intros ("can introduce you to 10+ people at incident.io") and is highly responsive, so a cold engineer-to-engineer note has a decent shot — but there is no actual warm intro.

**① Connect note:**
> Lawrence — the 'Code it up' button opening a PR from Slack is the moment I keep circling: what checks that action before it lands? I'm building a neutral runtime layer for agent actions — parameter/sequence/identity checks, block-before-execute. Worth swapping notes? — Shashank, Founder @ AegionAI

**② InMail** — subject: `The runtime check behind 'Code it up'`

Hi Lawrence,

Your Investigations agent doesn't just summarize — it writes a fix and opens a PR straight from Slack when someone hits "Code it up." Reading your "timeline to fully automated incident response," the direction is clear: from investigating *with* you toward resolving *for* you. That shift changes the risk surface — the question stops being "is the prompt safe?" and becomes "is *this action* safe?": the right repo/service, the right parameters, the right command against the right environment.

I'm building AegionAI Guard: a neutral runtime control plane that governs the *actions* agents take. Per-action parameter/sequence/identity checks, block-before-execute, and a tamper-evident audit trail — sitting at the enforcing point, not the prompt. Deliberately not a content filter (commoditized) and not identity (complementary — that's *who*, not *what the action does*). Neutral across vendors: AWS and Azure today, GCP and in-VPC next.

Honest on stage: the deterministic action-layer checks and append-only audit are live; ML detection is still in shadow; and we've got no enterprise logos yet — we're building with a couple of early design partners on synthetic agents, which is exactly why I'm reaching out now rather than later.

I'm looking for a couple of design partners to build this with — infra/automation agents that take real actions are the sharp end. Would incident.io be a fit, or worth 20 min to find out? Completely fine if the timing's off, or if you're building this in-house.

— Shashank / Founder, AegionAI
aegionai.ai

*Do-not-claim: Don't claim the agent merges/deploys code or runs prod commands autonomously — today the PR is opened on a human 'Code it up' click and still needs human review/merge; 'resolve incidents for you' is their STATED roadmap, not shipped. · Don't claim AegionAI has enterprise customers/logos — 'prod' is demo/design-partner accounts on synthetic agents. · Don't claim ML detection is enforcing — it's in shadow; only the deterministic floor + append-only audit are live. · Don't claim GCP, in-VPC, or air-gapped editions are live — they're roadmap (AWS + Azure only today).*

---

## 5. NeuBird · priority: **high** · contact-confidence: verified-2026

**What they do:** NeuBird builds Hawkeye, an AI "Production Operations Agent" (AI SRE teammate) that detects, investigates, and resolves production incidents across hybrid/multi-cloud stacks — powered by its "Falcon engine." Founded late 2023 by ex-Portworx repeat founders; ~$63.8M raised across three rounds (latest $19.3M led by Xora Innovation, Apr 2026). [neubird.ai; TechCrunch 2024-04-17; Businesswire 2026-04-06]

**Agent action we'd govern:** Hawkeye executes remediation on live infra: its own demo shows it rolling back a deploy (#4821) and scaling a pool 20→60 to cut MTTR; Runbook Automation performs scale/rollback/restart/hand-off. This is a consequential write-path action on production — the "wrong action" risk is rolling back the wrong deploy, scaling/restarting the wrong resource, or a remediation that worsens the incident, on infra it can reach across clouds.

**Contact:** Vinod Jayaraman — Co-founder & CTO, NeuBird  ·  https://www.linkedin.com/in/vinodjayaraman
  *Buyer note:* Yes — CTO Vinod Jayaraman is the right eng/AI-led first contact for an action-layer/runtime-control conversation. Alternative: CEO Gou Rao is also deeply technical (was Portworx CTO) and is the public voice/decision-maker, so a good fallback if Vinod doesn't respond — but the CTO owns the enforcement-point architecture, so lead with him.

**Warm path:** cold — no verified warm intro. (Shared-investor angles exist but aren't a real path for me: Mayfield backs both NeuBird and many infra startups; Xora Innovation/Temasek led their latest. No YC/personal tie found.)

**① Connect note:**
> Vinod — with the Falcon engine, Hawkeye is moving toward rolling back deploys and scaling pools without a human in the loop. That's where the risk shifts from the prompt to the action itself. I'm building a neutral runtime check that vets an agent's action before it executes. Worth 20 min?

**② InMail** — subject: `When Hawkeye rolls back a deploy on its own, what vets the action?`

Vinod — with the Falcon engine, Hawkeye is moving toward executing remediation across a hybrid/multi-cloud stack without a human in the loop; the demo already shows it rolling back deploy #4821 and scaling a pool 20→60 to pull MTTR under five minutes. That's the exact point where the risk stops being "was the prompt bad" and becomes "was that the right action, on the right resource, in the right order."

I'm building AegionAI Guard — a neutral, cross-vendor runtime control plane that governs the actions an agent takes, not the text it reads. Before a remediation executes, it runs a deterministic check on the action's parameters, sequence, and identity (right deploy? right pool? allowed to touch prod?), stops the harmful one before it runs, and writes a tamper-evident record of every action — which pairs with the audit trail you already expose. Neutral across clouds matters here because Hawkeye reaches across a customer's whole stack, and no single cloud's controls will govern a rival's.

Honest on stage: the deterministic action-layer checks and append-only audit run today; the ML detection is still in shadow, and I don't have enterprise logos yet. I'd rather show you what actually runs than pitch a roadmap.

I'm looking for a couple of design partners to build this with as agents like Hawkeye move toward unattended execution — would NeuBird be a fit, or worth 20 minutes to find out? No worries at all if the timing's off.

— Shashank / Founder, AegionAI
aegionai.ai

*Do-not-claim: Don't claim Hawkeye executes fully unattended in production TODAY — NeuBird's site cites human-in-the-loop and an audit trail; 'without human intervention' is press-coverage framing of the Falcon-engine trajectory, so frame it as 'moving toward' autonomy (bunq lesson). · Don't claim AegionAI Guard has any enterprise customers/logos — 'prod' is demo/design-partner accounts on synthetic agents. · Don't claim the ML detection is enforcing — it is in shadow only. · Don't claim GCP support or in-VPC/air-gapped editions are live — AWS+Azure live, those are roadmap.*

---

## 6. Vic.ai · priority: **high** · contact-confidence: likely

**What they do:** AI-first accounts payable automation, positioned as an "autonomous finance platform": VicInbox/VicAgents triage and code invoices, and VicPay initiates and executes vendor payments (ACH, check, virtual card) on its own rails into major ERPs (NetSuite, Sage Intacct, Workday, SAP S/4HANA). [Sourced: vic.ai homepage + vic.ai/blog Q2 launch, dated Jun 3, 2025.]

**Agent action we'd govern:** The consequential executed action is a vendor payment release: VicPay "initiates and executes payments directly within the platform" (ACH/check/virtual card) tied to approval workflows; VicInbox "autonomously triages, categorizes and routes" AP email and drafts replies; a Contract Agent (beta) cross-references invoices to contract terms and auto-routes compliance questionnaires. Wrong-action risk = a payment released to a wrong/redirected account, a duplicate paid, or a manipulated invoice pushed through the invoice→approval→pay sequence. HONEST: payment release is approval-gated today (85% no-touch by month 6 = hybrid; framing is "amplify, not replace"), so frame "as it moves toward autonomy" — do NOT claim unattended money movement (the bunq Finn lesson).

**Contact:** Kevin Dotzenrod — VP, Engineering and Products  ·  ⚠️ LinkedIn unverified — find + confirm before send
  *Buyer note:* Kevin Dotzenrod (VP, Eng and Products) is the right eng-led first contact — confirmed current on the live vic.ai/about page (© 2026). He owns both engineering and product, so the action-governance conversation lands in one seat. Alternates: (a) CEO/co-founder Alexander Hagerup for a founder-to-founder path given company size; (b) a "Brett Norton, SVP of Engineering (ex-CTO Provenir)" appeared in one search snippet — conflicts with the about page and is unverified/possibly stale, so treat as a maybe, not a target.

**Warm path:** cold — no known warm intro identified (no shared investor/YC/community path surfaced this session).

**① Connect note:**
> Kevin — VicPay now initiates & executes payments (ACH/check/vcard) in-platform, and VicInbox autonomously routes AP email. I'm building a neutral runtime check that validates each payment action — payee, amount, the invoice→approval→pay sequence — before it releases, across any cloud. Worth comparing notes?

**② InMail** — subject: `Checking the payment action before VicPay releases funds`

Hi Kevin,

Since the Q2 launch, VicPay initiates and executes payments — ACH, check, virtual card — directly inside Vic.ai, and VicInbox autonomously triages and routes the AP inbox. So the platform is increasingly the thing that moves the money, not just the human clicking approve.

As those agents move from approval-gated toward more autonomy, the moment that matters is the action itself: is this payment going to the right payee and account, is the amount within bounds, and was the invoice→approval→pay sequence tampered with along the way? Prompt/content filtering won't catch a perfectly-worded payment to a redirected account, and identity only tells you which agent is acting — not whether this specific action is safe to execute.

I'm building AegionAI — a neutral runtime control plane that validates each action at the enforcing point: parameters (amount/payee/account), sequence integrity, and authorization, blocking before execute, with a tamper-evident audit trail. It's cross-vendor by design (AWS and Azure today; GCP and in-VPC/air-gapped on the roadmap), so it isn't tied to one cloud's stack.

Honest on stage: the deterministic checks and append-only audit are live; ML detection is still in shadow; we're early and working on synthetic agents with design partners — no enterprise logos yet.

I'm looking for a couple of design partners to build this with — would Vic.ai be a fit, or worth 20 min to find out? Totally fine if the timing's off.

— Shashank / Founder, AegionAI
aegionai.ai

*Do-not-claim: Don't claim VicAgents/VicPay release payments fully autonomously or unattended — payment release is approval-gated/hybrid today (85% no-touch by month 6; 'amplify, not replace'). Frame 'as it moves toward autonomy.' · Don't claim GCP, in-VPC, or air-gapped deployment is live — all roadmap. · Don't claim ML detection is enforcing — it's in shadow; only deterministic floor + append-only audit are live. · Don't claim enterprise customers/logos — 'prod' is demo/design-partner accounts on synthetic agents.*

---

## 7. Doctor Droid · priority: **high** · contact-confidence: verified-2026

**What they do:** DrDroid (YC W23, Bengaluru) builds an AI SRE agent — "your best friend in production" — that auto-triages incidents from a self-learning knowledge graph of the customer's stack (80+ integrations across AWS/GCP/Azure/K8s, Datadog, PagerDuty), runs read-only diagnostics, delivers fixes as hotfix PRs, and executes commands on prod hosts via SSH with writes gated by RBAC approval [drdroid.io; YC company page].

**Agent action we'd govern:** Executes commands on production hosts via SSH and queries Kubernetes clusters. Read commands "execute without approval (safe exploration)"; write/state-changing commands "require RBAC approval per your policy" and dangerous ops require senior approval; code fixes ship as hotfix PRs a human merges. So it truly runs commands on prod, but state-changing remediation is human-in-the-loop today. Investigations run autonomously (alert fires -> investigation starts). The RBAC-gated action seam is the direct fit for a deterministic action-layer check.

**Contact:** Siddarth Jain — Co-Founder & CEO  ·  https://www.linkedin.com/in/siddarth-jain227
  *Buyer note:* Yes — at an 8-person YC startup, founder-to-founder to the CEO is the right first contact; Siddarth is technical (ex-Data Scientist, IIT-Delhi EE, leads the DS team) and the more publicly reachable co-founder (active on X as @TheBengaluruGuy, 22K followers). If the conversation goes deep-architecture, Dipesh Mittal (co-founder / architect, ex-Shadowfax+PayPal, linkedin.com/in/dipesh-mittal) is the better technical counterpart.

**Warm path:** Cold. No confirmed warm intro. Both founders are YC W23 and ex-Shadowfax — if AegionAI is in the YC network, a batch-Slack / YC founder-directory intro is the strongest warm path (unverified whether that applies).

**① Connect note:**
> Siddarth — DrDroid's agent SSHes into prod: reads run free, writes gated by RBAC per policy. I'm building a neutral runtime check on the action itself (params, sequence, identity) before a write executes, as agents move toward autonomy. Founder to founder, worth 20 min? — Shashank

**② InMail** — subject: `Checking the agent's write command before it executes on prod`

Hi Siddarth,

DrDroid already draws the line where it matters: the agent SSHes into prod hosts and runs commands, with reads executing freely for safe exploration and writes gated behind RBAC approval per the customer's policy (and senior approval for anything dangerous). That split — auto for reads, a gate for anything state-changing — is exactly the seam I've been building around.

I'm building AegionAI Guard: a neutral, cross-vendor runtime control plane that governs the actions an agent takes. Not prompt/content filtering (commoditized) and not identity (complementary) — a deterministic check on the action itself before it executes: the actual command and its parameters, the sequence it belongs to, and the identity behind it. Block-before-execute, with a tamper-evident record of every decision.

As agents move from "here's a suggested fix / here's a PR" toward executing writes with less human review, that RBAC gate becomes the thing regulated customers will want to reason about: not just who may act, but whether this specific action, with these parameters, in this sequence, is safe to run — and proof it was checked.

Honest on stage: the deterministic action-layer floor and the append-only audit are live; ML detection is running in shadow, not enforcing; and I don't have enterprise logos yet — this is early. AWS and Azure are wired; GCP and in-VPC / air-gapped are on the roadmap.

I'm looking for a couple of design partners to build this with — teams whose agents actually execute on production. Would DrDroid be a fit, or worth 20 minutes to find out? Completely fine if the timing's off.

— Shashank / Founder, AegionAI
aegionai.ai

*Do-not-claim: Do NOT claim the agent autonomously restarts pods, scales, drains nodes, or rolls back deploys — writes require RBAC approval and dangerous ops need senior approval today (investigate-and-suggest, human-in-the-loop for state changes). · Do NOT claim it auto-deploys fixes — code fixes ship as hotfix PRs a human merges. · Do NOT imply SSH keys are exposed to the agent — DrDroid states keys are not exposed to the agent. · Do NOT assert Siddarth's exact title from LinkedIn alone (the guest-view role field was blank); 'Co-Founder & CEO' comes from the YC company page, not the profile.*

---

## 8. Credgenics · priority: **high** · contact-confidence: verified-2026

**What they do:** SaaS debt-collections and loan-recovery platform for banks, NBFCs, fintechs and ARCs (India, RBI/DPDP context), spanning digital, calling, field and legal channels; its "Swara" GenAI voicebot runs borrower recovery calls [credgenics.com].

**Agent action we'd govern:** Swara conducts recovery calls that share payment and settlement links, send settlement offers, and auto-initiate follow-ups across channels — so the consequential executed action is the settlement amount/discount and the payment link it generates and sends to a specific borrower mid-call. The "wrong action" risk is a wrong amount, an unauthorized discount, or a link sent to the wrong borrower — not just "did it say something off." Money-adjacent (borrower completes payment via the link; Swara does not itself move funds).

**Contact:** Anand Agrawal — Co-Founder & CPTO (Chief Product & Technology Officer)  ·  https://in.linkedin.com/in/anandagrawal3
  *Buyer note:* Yes — Anand Agrawal is CPTO, owning both product and technology, so he is the right single eng/AI-led first contact for an action-layer conversation. Alternative if he is unresponsive: co-founder & CEO Rishabh Goel (in.linkedin.com/in/goelrishabh), but he is less technical; no separately named VP Eng or Head of AI/ML surfaced publicly.

**Warm path:** cold

**① Connect note:**
> Anand — Swara now sends payment + settlement links and offers mid recovery-call. As more of that runs unattended, the risk moves from what it says to the settlement amount/link it actually sends. I'm building a neutral runtime check for exactly that action layer — worth comparing notes?

**② InMail** — subject: `Checking the settlement amount + link Swara sends, not just what it says`

Hi Anand,

Credgenics' Swara now runs recovery calls that share payment and settlement links, send settlement offers, and auto-initiate follow-ups across channels — increasingly with the human agent stepping back.

As more of that call runs unattended, the security question shifts. It's no longer "did the bot say something off?" — content filtering is largely commoditized now. It's "was the settlement amount, the discount, and the link Swara actually sent correct, authorized, and to the right borrower?" That's an action, not a prompt. And under RBI/DPDP you also need a tamper-evident record of every one.

I'm building AegionAI Guard: a neutral runtime control plane that checks the action an AI agent takes before it executes — the parameters (settlement amount, link), the sequence, the identity — blocks the bad one, and writes an append-only audit trail. It sits as an enforcing point in front of the action, works across AWS and Azure (GCP and in-VPC/air-gapped are on the roadmap), and is deliberately not identity or content filtering — it's the deterministic check on what the agent does.

Honest on stage: the deterministic action-layer checks and the audit trail are live today; the ML-based detection is still running in shadow, and we don't have enterprise logos yet — which is exactly why I'm looking for a couple of design partners to build this with against a real money-adjacent agent like Swara.

Would Credgenics be a fit, or worth 20 min to find out? If it's not the moment, no worries at all — a "not now" is a perfectly good answer.

— Shashank / Founder, AegionAI
aegionai.ai

*Do-not-claim: Don't claim Swara moves money itself — it shares payment/settlement links and offers; the borrower completes payment via the link (Billzy) · Don't claim Swara is fully autonomous/unattended — sources show a hybrid model with human agents still in the loop; frame 'as it moves toward autonomy' · Don't claim Credgenics is a customer or that we have enterprise logos — 'prod' is demo/design-partner accounts on synthetic agents · Don't claim GCP or in-VPC/air-gapped editions are live — roadmap*

---

## 9. 10x Banking · priority: **high** · contact-confidence: likely

**What they do:** Cloud-native "meta core" banking platform for established financial institutions (100M+ accounts; customers include Chase UK, Westpac, Old Mutual, The Co-operative Bank, Constantinople, Remara), now adding AI: "AI Migrate" GenAI tooling that automates legacy data mapping/transformation for core migration, plus a broader AI product roadmap.

**Agent action we'd govern:** Their "AI Migrate" agent maps and transforms legacy banking data into the target core during migration — i.e. it generates the data mappings/transformations that populate a live core banking system (balances, product configs). The "wrong action" risk is an agent producing an incorrect mapping/transformation that lands bad data in a live core, or (per their AI product roadmap) a future agent acting on product configuration. Sourced only as "automating data mapping and transformation" — 10x does not publicly state the autonomy/human-review level, so I frame it as moving toward autonomy, not as executing unattended.

**Contact:** Okan Ozaltin — Chief Product Officer (owns the AI product roadmap; ex-JPMorgan ~10 yrs, ex-Signifyd, ex-Fiserv)  ·  https://www.linkedin.com/in/okan-ozaltin-b67b48
  *Buyer note:* Okan Ozaltin (CPO) is a strong eng/AI-led first contact: he owns 10x's AI product roadmap and has a JPMorgan engineering-adjacent background. But two others are arguably equal-or-better: (1) CISO Richard Moore, who has publicly written that AI "abuses the access humans already have" and "changes scale, not accountability" — the most security-aligned buyer, ideal for the control-plane framing; (2) CEO/founder Antony Jenkins (ex-Barclays CEO) for a founder-to-founder path. There is no publicly-named sitting CTO — former CTO Neil Drennan left to become ClearBank's CTO — so do NOT target a "CTO" seat. Recommended play: open with Okan on the product/roadmap angle, cite Moore's writing, and be ready to loop in Moore.

**Warm path:** cold — no verifiable warm intro found. Resonance-only angles (not actual intros): Okan is ex-JPMorgan and Chase UK is a 10x customer; Antony Jenkins (founder, ex-Barclays CEO) is the founder-to-founder route if a warm path opens.

**① Connect note:**
> Okan — Richard Moore's line that AI "abuses the access humans already have" is the exact problem I'm building for: a neutral runtime check on what an AI agent does — parameters, sequence — before it writes into a live core like yours. Founder, AegionAI — worth 20 min to find out if it's a fit?

**② InMail** — subject: `A runtime check on what AI agents do inside the core`

Hi Okan,

Richard Moore's piece on AI-driven security risk made your team's stance clear — "AI doesn't need special access; it abuses the access humans already have," and "AI changes scale, not accountability." That's the exact gap I'm building for.

As 10x leans into agentic core banking — AI Migrate already automating legacy data mapping and transformation, with more on the AI product roadmap — the question shifts from "is the prompt bad?" to "what did the agent just do?" An agent mapping legacy data into a live core, or acting on a product configuration, is a high-consequence action long before it ever gets near money movement.

I'm building AegionAI Guard: a neutral runtime control plane that governs the actions AI agents take — checking parameters, sequence, and identity per action and blocking before execute, with a tamper-evident audit trail. It sits as an enforcing point in front of the action, neutral across AWS and Azure (GCP and in-VPC/air-gapped on the roadmap), so it isn't tied to any one cloud's own stack. This is deliberately not prompt/content filtering (commoditized) and not identity (complementary) — it's the deterministic action layer.

Honest on stage: the deterministic action-layer checks and the append-only audit are live today; ML-based detection runs in shadow, not enforcing; and my current deployments are design-partner and demo accounts on synthetic agents — no enterprise logos yet. I'd rather say that now than oversell it.

I'm looking for a couple of design partners to build this with — teams who already take AI action-risk seriously, which your CISO's writing says you do. Would 10x be a fit, or worth 20 minutes to find out? Completely fine if the timing's off.

— Shashank / Founder, AegionAI
aegionai.ai

*Do-not-claim: Don't claim AI Migrate is fully autonomous or moves/touches money unattended — it is sourced only as automating data mapping/transformation for migration; 10x doesn't state the autonomy or human-review level (the bunq 'Finn moves money' lesson). · Don't address Okan as CTO or imply 10x has a sitting CTO — former CTO Neil Drennan left for ClearBank; no current CTO is publicly named. · Don't claim GCP support or in-VPC/air-gapped deployment is live — both are roadmap; only AWS + Azure are current. · Don't claim ML detection is enforcing — it's in shadow.*

---

## 10. Atomicwork · priority: **high** · contact-confidence: verified-2026

**What they do:** AI-native ITSM/ESM platform whose "AI Coworkers" own IT roles end-to-end — the DevOps Specialist Coworker triggers production rollbacks "before downtime hits production," the Access Coworker grants/revokes access across Okta/Entra/Workday, plus remediating misconfigs and quarantining phishing — across ServiceNow/Jira/Slack/Teams, "governed by IT." Series A $25M (Khosla Ventures + Z47/ex-Matrix India, Jan 2025); SF + Bengaluru; customers include Zuora and Pepper Money.

**Agent action we'd govern:** Atomicwork's AI Coworkers execute real IT actions, not just answers: the DevOps Specialist Coworker triggers production rollbacks; the Access Coworker provisions/revokes access across Okta, Microsoft Entra, and Workday; other Coworkers remediate misconfigurations and quarantine/dismiss phishing. Today these run under IT governance — role-based access, approvals, and pre-deploy testing of each Coworker's operating procedure — so it is action-taking-with-oversight, moving toward autonomy, not fully unattended execution.

**Contact:** Kiran Darisi — Co-Founder & CTO  ·  https://in.linkedin.com/in/kirandarisi
  *Buyer note:* Yes — Kiran Darisi (Co-Founder & CTO, ex-Freshworks founding team) is the right eng-led first contact for a technical action-layer conversation. CEO Vijay Rayapati (note: he is CEO, NOT CTO — the brief's guess was inverted) is a viable founder-to-founder alternative, but the CTO is the better fit for the enforcement/architecture pitch. At Series-A size there is likely no separate Head of Security/Platform yet; if outreach to Kiran stalls, Vijay is the fallback.

**Warm path:** Cold. No confirmed warm intro. Ecosystem paths worth checking: Khosla Ventures / Z47 (ex-Matrix India), Peak XV, Battery, Blume portfolio networks, and the large Freshworks/Zoho alumni network (Kiran's roots) — if any of those overlap the founder's network, that is the strongest warm route.

**① Connect note:**
> Kiran — your DevOps Coworker triggers prod rollbacks and the Access Coworker grants/revokes access across Okta/Entra. I'm building a neutral runtime layer that checks each action (parameters, identity, sequence) before it executes, across clouds. Worth comparing notes? — Shashank

**② InMail** — subject: `A runtime check before your Coworker rolls back prod`

Hi Kiran,

Your DevOps Specialist Coworker triggers production rollbacks before downtime hits, and the Access Coworker grants and revokes access across Okta, Entra and Workday. Those executed actions — not the chat answer in front of them — are where the real risk sits: a rollback to the wrong version, an access grant with too-wide scope, or steps that run out of sequence.

I'm building AegionAI Guard: a neutral runtime control plane that governs the actions agents take. It runs a deterministic check on each action — parameters, sequence, identity/authorization — and can block before execute, with a tamper-evident audit trail of every decision. It's not another prompt/content filter (that's commoditized), and it's not identity — it sits above your Okta/Entra plumbing, checking what the action actually does after identity says who's asking. Neutral across vendors is the point: it's one layer over AWS and Azure today, which matters when your Coworkers act across ServiceNow, Slack, and both clouds.

Honest on stage: the deterministic action-layer check and append-only audit are live; the ML detection piece is still running in shadow; and I don't have enterprise logos yet — this is early, running on demo and design-partner accounts. As your Coworkers move from approval-gated toward more autonomy, this is the enforcing point that could sit under them.

I'm looking for a couple of design partners to build this with — would Atomicwork be a fit, or worth 20 minutes to find out? Completely fine if it's not the right time or not a priority right now.

— Shashank / Founder, AegionAI
aegionai.ai

*Do-not-claim: Do NOT call Vijay Rayapati the CTO — he is Co-Founder & CEO; Kiran Darisi is the CTO. · Do NOT claim Atomicwork's Coworkers run fully autonomous / unattended — they are 'governed by IT' with approvals and pre-deploy testing today; frame as moving toward autonomy. · Do NOT claim AegionAI has enterprise customers or logos — 'prod' is demo/design-partner accounts on synthetic agents. · Do NOT claim GCP support or in-VPC/air-gapped editions are live — AWS+Azure live, those are roadmap.*

---
