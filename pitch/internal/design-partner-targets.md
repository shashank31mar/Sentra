# AegionAI / Sentra — Design-Partner Target Companies (researched)

**Generated:** 2026-07-07 · **Method:** 19-agent web-research sweep (9 cells = fintech/infra/regulated × US/EU/India), each finder paired with an adversarial verifier; 96 companies checked, **81 kept**, 15 dropped. Every company carries a real source URL; **CONFIRMED** = action-in-prod proven, **PLAUSIBLE** = action-execution asserted/beta.

> **ICP:** a company **running an action-taking AI agent in production** (moves money / mutates records / changes infra), reachable via an **engineering-led** buyer (VP/Head Platform Eng, Head of AI Infra — never CISO-first), on a **common topology** (solving them solves 40-200 similar cos). Beachhead = financial-action fintech; wedge = infra/DevOps. Excludes Harness (target its customers) + identity vendors + the 7 already on our list.
>
> **Companion to** [outreach-tracker.md](outreach-tracker.md) (once you start contacting, move a target into the tracker) and the [design-partner-playbook.md](design-partner-playbook.md) (how to run the conversation + the $5K offer).

---

## The 5 to contact THIS WEEK
Biased to (warm path) + (beachhead-fintech or wedge-infra) + CONFIRMED → maps to "3 partners by Month 4."

1. **bunq** (NL fintech) — **warmest + highest fit.** "Finn" executes account transactions **on AWS Bedrock**; Sentra's live Bedrock connector installs at the action-group Lambda → native-integration pitch, not rip-replace. Door: AWS Bedrock partner team. *[AWS ML blog "How bunq handles 97% of support with Amazon Bedrock", 2026-01; bunq press 2025-12-16]*
2. **Qonto** (FR fintech, exact beachhead) — "The Operator" prepares bulk supplier transfers across 600k SMEs; its own human-confirm gate is the surface you harden (a poisoned invoice batch survives a rubber-stamp). Door: AWS France FSI. *[qonto.com/en/ai]*
3. **Traversal** (US infra-wedge, beachhead-adjacent) — autonomous SREs roll back deploys / reroute **payment** traffic unprompted; **Amex Ventures** strategic investor = warm path into FS SRE orgs. *[traversal.com; Fortune 2025-06-18]*
4. **Cast AI** (US infra-wedge, multi-cloud) — autonomous node kill/provision on live **EKS/AKS/GKE** proves the cross-vendor thesis. Door: AWS Karpenter partner team. *[cast.ai]*
5. **Gnani.ai** (India fintech-beachhead) — voice agent **completes UPI collections during a live call** (strongest India action-fit); warm via AWS/Azure India ISV + Razorpay integration + founder→CTO. *[gnani.ai; Analytics India Mag]*

---

## Tier 1 — reach out first (ICP 5, warm path, CONFIRMED)

| Company | Geo | Segment | Action-agent | Cloud / trigger | Persona | Intro path | Hook |
|---|---|---|---|---|---|---|---|
| **bunq** | NL | fintech | "Finn" executes account transactions, 82% automated | AWS Bedrock / EU-AI-Act, GDPR | Head of AI Infra | AWS Bedrock partner team (native connector) | Finn moves funds on Bedrock — Sentra blocks the injected off-policy transaction at your action-group Lambda before it executes |
| **Qonto** | FR | fintech | "The Operator" bulk supplier transfers, mints cards | PI license / PCI, GDPR, EU-AI-Act | VP/Head Platform Eng | AWS France FSI | A poisoned invoice batch redirects a 50-supplier run even after a human confirm — Sentra validates IBAN/amount/sequence |
| **Traversal** | US | infra | AI SREs roll back deploys / reroute payment traffic unprompted | multi-cloud / payments SRE | VP SRE / Head Prod Eng | Amex Ventures (strategic investor) | An autonomous rollback off a poisoned RCA hits the wrong service — Sentra governs the action with a tamper-evident trail |
| **Cast AI** | US | infra | APA autoscaler kills/provisions nodes on live EKS/AKS/GKE | **all 3 clouds** | Head of Platform Eng | AWS EKS/Karpenter partner | A mis-scoped mass-terminate evacuates a prod workload — Sentra blocks it, neutral across all 3 clouds |
| **Klarna** | SE | fintech | LangGraph assistant issues refunds + processes payments, 85M users | bank license / PCI, PSD2, GDPR | Head of AI / platform lead | LangChain/LangGraph ecosystem (named ref) | Injection-driven or duplicate refund over caps to an attacker payee — Sentra sits on the action path |
| **Gnani.ai** | IN | fintech | Razorpay voice agent completes UPI collections in-call, 10M+ calls/day | AWS/Azure / RBI | VP Eng (voice) / Head AI Infra | AWS/Azure India ISV; Razorpay mutual; founder→CTO | The in-call pay-out fires to the wrong VPA/amount — Sentra blocks inline before execution |
| **Commure** | US | healthcare | Autonomous Coding + bulk claim-resubmit writes to billing (Mount Sinai, HCA) | AWS / HIPAA | VP/Head Platform Eng | AWS healthcare ISV SA (co-host webinars) | A resubmit batch drifting outside policy before it hits the payer — Sentra blocks with HIPAA-grade audit |
| **Infinitus** | US | healthcare | Voice agents transact with payors (benefit verify, PA, enrollment), 8M+ calls | **Google Cloud** / HIPAA | Head of AI Infra / VP Eng | Google Cloud healthcare partner team | A hallucinated enrollment/PA write with wrong member params — Sentra governs the committed action |
| **Swiggy** | IN | cx | Databricks agent fires "action signals" executing refund/CRM writes | Databricks-on-AWS / DPDP | Head of AI Platform | Databricks field team (co-authored case study) | The GenAI-faked cracked-egg refund write — Sentra blocks the injected write without adding to your <500ms budget |
| **Taktile** | DE | fintech-infra | Decision agents approve/deny credit + AML/fraud (Mercury, Monzo, Allianz) | / EU-AI-Act Annex III | VP/Head Platform Eng | Index/Tiger portfolio; Berlin | An auto-approve breaching a credit-limit or a manipulated fraud override — Sentra enforces parameter/fair-lending bounds |
| **Credgenics** | IN | fintech | "Swara" voicebot auto-shares settlement/payment links mid-recovery-call | / RBI, DPDP | VP Eng / Head Platform Eng | WestBridge portfolio; AWS/Azure India FSI | A settlement beyond band, or re-contact past RBI limits — Sentra blocks before the link is sent |
| **Skit.ai** | IN/US | fintech | Outbound collections agent negotiates PTPs + settlements autonomously | / RBI + US FDCPA/TCPA | VP/Head ML Platform | WestBridge/Kalaari lineage; AWS India; founder→CTO | A discount beyond policy or a dial outside permitted hours — Sentra blocks, neutral across India+US stacks |

---

## Tier 2 — strong fit, cold or partial path (ICP 4 CONFIRMED, or ICP 5 weak path)

| Company | Geo | Segment | Action-agent | Persona | Intro path | Hook |
|---|---|---|---|---|---|---|
| **Brex** | US | fintech | Prod expense-audit + fraud agents; built CrabTrap to secure agents | Head of AI / VP Eng | Cold-high-signal (agent-security authors on brex.com/journal); Anthropic partner | You built CrabTrap to secure prod agents — Sentra is the neutral action-layer version, blocking the spend action |
| **Ramp** | US | fintech | Procurement agent fleet (Zero-Touch Sourcing) atop card/bill-pay rails | Head of AI / VP Platform | Anthropic/AWS ecosystem; ramp.com/engineering authors | A compromised sourcing agent approves a fraudulent payout — Sentra blocks before money leaves |
| **Sedai** | US | infra | Autopilot executes rightsizing/remediation with **zero approval** (Palo Alto, HP) | VP Cloud Platform / Dir SRE | VC network; shared-customer platform team | Autopilot's own no-approval framing is the opener — Sentra is the fail-secure gate across every cloud |
| **Rillet** | US | fintech | "Aura" reads+writes live GL; auto GL/bank recon | Head of AI Infra / VP Platform | AWS Marketplace partner; Anthropic; a16z/Sequoia | Aura writes to the GL of record — Sentra blocks an unauthorized JE before it commits |
| **Firefly** | IL/US | infra | Thinkerbell agents rewrite Terraform, rollback live infra | Dir Cloud Platform | HashiCorp/Terraform community; HPE ref | An agent "fixing drift" deletes a prod resource — Sentra governs each IaC apply/destroy |
| **Komodor** | US/IL | infra | "Klaudia" autonomous K8s self-healing across multi-cluster | Dir Platform Eng | CNCF/KubeCon; shared EKS/AKS customer | An autonomous bad rollout cascading across a hybrid estate — Sentra is the action gate |
| **NeuBird** | US | infra | Production Operations Agent executes automated rollbacks (DeepHealth) | VP Cloud / Head SRE | Healthcare-AI infra community | An automated rollback reintroduces a vulnerable build — Sentra sits in front with the audit record |
| **Doctor Droid** | IN | infra | ACT-phase auto-remediation runbooks; air-gapped/in-VPC | Head Platform Eng / SRE | YC network (founder-to-founder); TrueFoundry mutual | An auto-fired runbook drains the wrong node — Sentra checks blast radius before it fires |
| **Atomicwork** | IN/US | infra | DevOps Coworker triggers rollbacks; provisions access (Zuora, Pepper Money) | VP Platform / Head IT Eng | Khosla/Matrix India portfolio | A compromised Coworker grants over-broad access — Sentra governs the action + parameters |
| **Facets.cloud** | IN/US | infra | "Praxis" turns chat into deployed terraform/kubectl on customer clouds | Head Platform Eng / VP Eng | Bengaluru platform-eng community | A Praxis plan deletes a stateful resource — Sentra governs generated action before apply |
| **Middleware.io** | IN/US | infra | OpsAI "Auto Fix" applies remediation directly to K8s | Head SRE / Head Platform | CNCF/KubeCon; founder/CTO | A confident-but-wrong fix deletes a PVC — Sentra is the gate in front of the apply |
| **Sarvam AI** | IN | fintech | BFSI voice agents run loan servicing + policy renewals (Tata Capital, SBI Life) | Head AI Infra / VP Platform | Lightspeed/Peak XV; NVIDIA/MS | A renewal/claim change with out-of-bounds params — Sentra blocks + runs air-gapped for IRDAI/RBI |
| **Tennr** | US | healthcare | Agents auto-submit prior auths + write charts/orders to EHR | VP Eng / Head Platform | Cold (June-25 raise); NYC healthcare-AI | An order/chart write diverging from source before it commits to the EHR — Sentra intercepts |
| **Adonis** | US | healthcare | RCM agents act on denials/AR across payer portals | VP Eng / Head ML Platform | Cold (Series C); RCM-AI community | A claim-edit with out-of-policy amount/CPT — Sentra blocks before it reaches the payer |
| **Cohere Health** | US | healthcare | "Unify" auto-approves ~85% of prior auths real-time (Humana, Geisinger) | Head AI/ML Platform / VP Eng | Cold; their "full auditability" stance is the fit | Enforce that an auto-approve never fires outside policy — Sentra turns "auditability" into an enforced control |
| **Decagon** | US | fintech | Concierge agents adjust card limits, replace cards, change account info (Bilt, Rippling) | Head of AI / VP Eng | a16z/Accel network; **also target its fintech customers** | A social-engineered agent raises a limit / reroutes a deposit — Sentra blocks the change |
| **Vic.ai** | US/NO | fintech | VicAgents process invoices + pay bills (VicPay) into ERPs | VP Eng / Head AI Platform | Mid-market ERP ecosystem; AWS partner | A duplicate-invoice agent pays a fraudulent bill before the ACH leaves — Sentra blocks |
| **AppZen** | US | fintech | Agents auto-approve 70%+ of expense reports + code AP (Intuit, Databricks) | VP Platform / Head AI Infra | AWS enterprise partner | Auto-approval of a fraudulent report past your policy floor — Sentra governs the auto-approve |
| **incident.io** | UK | infra | "Investigations" agent opens PRs from Slack ("Code it up") | VP Eng / Head Platform | Ex-Monzo/SRE community (SREcon) | A prompt-injected alert makes it open a PR that ships a backdoor — Sentra governs the write/PR |
| **Digits** | US | fintech | "Agentic Close" posts categorizations/accruals to the GL | VP Eng / Head AI | Applied-AI community; small org = fast cycle | A mis-inferred agent posts an entry that misstates the books — Sentra blocks the write |
| **Eve (eve.legal)** | US | legal | Agents sign clients live, propound/respond to discovery (1,200+ firms) | VP Eng / Head AI Platform | Cold; lead with HIPAA (injury medical records) | A binding client sign-up outside firm policy — Sentra governs the consequential action |
| **Eleos Health** | US | healthcare | Workflow agents complete RCM/compliance work, write to any web EHR | VP Eng / Head Platform | Cold; lead on ISO 42001/HITRUST | Enforce "execute under org rules" as a runtime control — block a policy-violating claim-creation |

---

## Tier 3 — watchlist / needs validation (PLAUSIBLE, or fit uncertain)

- **BILL (Bill.com)** [CONFIRMED, ICP 4, but large public co] — Reconciliation Agent auto-codes across $1T+ AP/AR. Off Tier 2 for size, not fit.
- **Numeric** [CONFIRMED, ICP 4] — posts JEs to NetSuite via MCP; Brex/Plaid/Wealthfront double as refs. Borderline Tier 2 (cold only).
- **Payhawk** [CONFIRMED, "early access", ICP 4] — Travel Agent books+pays; pre-GA = ideal DP timing.
- **Starling Bank** [CONFIRMED, ICP 4] — best angle = the **Engine** platform (propagates to every licensee bank).
- **Pleo** [PLAUSIBLE, ICP 3] — action agents in **July-2026 beta**; the beta window is the timing — reach now.
- **Decagon customers, Camunda customers (e.g. Wellpointe)** — the truer partner is often the *customer*, not the platform.
- **India CX** (MakeMyTrip / Myntra / PharmEasy / Meesho / Cars24 / Zomato) [PLAUSIBLE] — action-execution asserted, not proven; warm vendor paths exist (Nurix→Myntra, Divyam→PharmEasy, ElevenLabs→Meesho, Gupshup→Cars24). Confirm the agent *executes* before outreach.
- **PB Fintech (Policybazaar) / Perfios / Sarvam-adjacent** [PLAUSIBLE, ICP 4] — lead with IRDAI/RBI audit trigger; confirm agent-vs-ML-pipeline.
- **Shift Technology / DeepOpinion / Sixfold** [CONFIRMED/mix, ICP 4] — EU insurance claims agents (AXA, Allianz); EU-regulated already well-covered.
- **Dust** [CONFIRMED, ICP 4] — action-taking agents on internal tools; Anthropic/MCP-native, Sequoia. Clean wedge; named prod customers not surfaced.
- **Basis / Auditoria / Zeni / Digits-adjacent** [CONFIRMED, ICP 3] — bookkeeping/tax agents; smaller, faster cycles.

### ⚠️ Competitor-adjacent — approach as partner/complement or target THEIR customers, not a straight sale
**Qovery · Tines · Spacelift · n8n** (each ships its own single-platform action guardrails — Sentra's wedge is neutrality *across* platforms they don't govern) · **Cognigy / Parloa** (CX agent platforms, NICE-owned/Azure co-sell — target their enterprise customers) · partly **Camunda / Dust / Adyen / Worldline**.

### ⚠️ Verify viability / gate before outreach
- **Saarthi.ai** — primary domains dead/hijacked, last funding Seed 2022; confirm the company still operates.
- **Revolut (AIR)** — may be advisory-only; **gate outreach on confirming it executes money-movement**.
- **Nordea** — ran a single issuer-side pilot, not a fleet.

---

## By geography — the read

- **US — deepest pool; lead with infra-wedge + healthcare-regulated (~20 strong).** Fintech (Ramp, Brex, Rillet, Decagon) + infra (Cast AI, Sedai, Traversal, Firefly, Komodor, NeuBird) both rich, plus a HIPAA-triggered healthcare cluster (Commure, Infinitus, Tennr, Adonis, Cohere Health, Eleos, Eve). **First move: work the AWS/Google-Cloud partner-SA channel** — bunq, Commure, Infinitus, Cast AI, Rillet all have a named cloud-partner door; the Bedrock connector makes it a native-integration conversation.
- **Europe — strongest beachhead-fintech fit + hardest triggers (EU AI Act, DORA, PSD2) (~12 strong).** Money-movement agents are concrete: bunq, Qonto, Klarna, Taktile. **First move: bunq via AWS Bedrock partner team** — warmest, highest-fit door in the whole list; Qonto (AWS France FSI) second.
- **India — collections/voice-fintech + infra-wedge, mostly warm via investors/YC/vendor co-sell (~10 strong).** Voice agents that *execute* UPI/settlement (Gnani, Credgenics, Skit) are unusually strong fits; infra (Doctor Droid, Facets, Atomicwork, Middleware) is a clean wedge with YC/portfolio paths. CX is evidence-strong but action-execution often asserted. **First move: Gnani.ai** (in-call UPI pay-out, Razorpay + AWS/Azure India door), or Swiggy via the Databricks co-author relationship.

---

## Coverage honesty (what this sweep likely missed)
- **GCP-native shops** under-covered (pool is AWS/Azure-heavy; only Infinitus/Camunda touch GCP) — a Vertex-AI-Agent-Builder-customer pass is a gap.
- **US mid-market neobanks/BaaS running their OWN agents** (Mercury-tier) surfaced mostly as *customers* of others — a dedicated pass would sharpen the exact beachhead.
- **EU-regulated is PLAUSIBLE-heavy** — many are decision-support (Unique, Robin, Legora, Sixfold, Tengai) not autonomous money/infra mutation; needs a second pass to confirm action-execution.
- **India CX cell is almost entirely PLAUSIBLE** — confirm the agent *fires* the refund vs surfaces status before outreach.

**DROPPED after verification (checked + rejected — don't re-spend time):** Spendesk, Juspay, CollectAI.in, Deductive AI, Aiven, Humanitec, Zenduty (Xurrent IMR), Amnic, TrueFoundry, EvolutionIQ, Candid Health, Retorio, Bharti Airtel, Cleartrip, Tata 1mg.
