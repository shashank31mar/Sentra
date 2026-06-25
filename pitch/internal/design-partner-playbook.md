# AegionAI — Design Partner Program

**Internal playbook | March 2026**

---

## What Is a Design Partner (and What It Is Not)

A design partner is not a beta user, a pilot customer, or a free trial account. A design partner is a company that co-builds the product alongside us — their production environment shapes what we build, their engineering team works directly with ours, and they commit real time and a token fee in exchange for the product being shaped around their specific infrastructure.

The distinction matters: beta users give feedback. Design partners give us their agent topology, their production failure modes, and their compliance requirements. In return, they get permanent preferred pricing, direct roadmap input, and a product that solves their exact problem — not a generic approximation of it.

Target: **3 design partners** by Month 4. No more — depth over breadth.

---

## Who Qualifies — The Three-Part Filter

Run every candidate through all three. If any one fails, move on.

**1. Urgency (is the pain active today?)**
- Running AI agents in production on 2 or more clouds — not planned, not piloting, running
- At least one of: post-M&A multi-cloud estate, EU AI Act enforcement exposure (August 2026), documented internal AI security incident, or regulatory audit trail requirement (HIPAA, PCI-DSS, RBI)
- The buyer says "we need to solve this before Q3" — not "this is on our roadmap"

**2. Capability (can they actually run this?)**
- Senior platform engineer available — not a junior dev, not a PM, someone who can deploy a Kubernetes sidecar
- Staging environment we can instrument without touching production
- Engineering-led buyer (VP Engineering or Platform Engineering Lead) — a CISO who can't get engineer time is not a design partner

**3. Representativeness (does solving their problem solve 100 others?)**
- Their agent topology should be a common pattern — not a bespoke one-off
- India fintech running payment agents on AWS = 40+ companies with the same problem
- EU HR SaaS running hiring AI on Azure = 200+ companies with identical compliance exposure
- Healthcare SaaS with HIPAA on-prem requirement = a segment SaaS competitors cannot serve

---

## What We Offer — What We Ask

Be explicit about this on the first call. Ambiguity here creates passive partners who never engage.

### What AegionAI Provides

| Commitment | Detail |
|---|---|
| **Free deployment, 6 months** | Full AegionAI control plane — policy enforcement, sequence validation, audit logs — at no license cost |
| **Founder-led weekly sync** | 1 hour/week, founders on the call (not a CSM). Direct feedback loop to roadmap |
| **Roadmap priority** | Their specific use case (e.g., payment sequence validation, HIPAA audit trail) is scheduled and shipped within 6 weeks of agreement |
| **Permanent preferred pricing** | Whatever commercial rate they lock in at Month 6 is theirs indefinitely — never subject to price increases |
| **Early access** | Every new capability (Azure connector, ML anomaly detection, compliance reports) reaches them 30 days before general availability |

### What We Ask

| Commitment | Why It Matters |
|---|---|
| **2 hours/week from a senior platform engineer** | Not a meeting attendee — someone who can instrument a sidecar and give architectural feedback |
| **Access to staging environment** | We need real agent traffic patterns — synthetic test data cannot replace this |
| **$5,000 design fee (upfront)** | Fully credited against first annual contract. This is not revenue — it filters out "AI tourists." A company that writes a $5K check has skin in the game; one that won't is unlikely to commit engineer time either. |
| **One internal reference call** | After Month 3, one 30-minute call where their VP Engineering speaks to a future AegionAI prospect. Optional for the first partner; expected for partners 2 and 3. |
| **Optional: case study** | Anonymized version always acceptable. Named version preferred. We will never publish anything without written sign-off. |

---

## The Outreach Sequence

### Step 1 — Identify the right person (not the CISO)

Target: **VP of Platform Engineering**, **Head of AI Infrastructure**, or **Director of ML Platform**. These are the people who own the Kubernetes clusters, understand what a sidecar does, and can approve a 6-month co-build without a 6-month procurement process.

The CISO is a secondary champion, not the primary contact. The CISO can block. The engineering leader can move.

### Step 2 — Warm intro before cold outreach

Priority order for intros:
- **IIT alumni network** — for India-based targets (Razorpay, Freshworks, Swiggy, Zomato), an IIT-to-IIT LinkedIn message has a 30-40% reply rate. Cold messages from IIT alumni to IIT alumni are a peer conversation, not a sales pitch.
- **Cloud partner teams** — AWS and Google Cloud have dedicated partner managers for named accounts. A "I'd like to show something to your customer's platform team" conversation with an AWS solutions architect is a warm door.
- **Community overlap** — SaaSBOOMi, HasGeek (Bangalore), Temporal Slack community, HIMSS (healthcare). Attend one event; follow up within 48 hours.

### Step 3 — The first message (3 sentences)

> "We're building an AI security control plane — a K8s sidecar that gives [Company] a single enforcement point across every AI agent fleet, regardless of which cloud they're on. We're recruiting 3 design partners to co-build with us; free for 6 months, permanent preferred pricing, and we ship your specific use case within 6 weeks. Given that [Agent Studio / CloudVerse / Nugget] is running [payment agents / multi-cloud agents / a 15M-interaction fleet], I think you have exactly the problem we're solving — 20 minutes?"

Do not pitch the company. Do not describe the whole product. State the problem they have, state what you offer, ask for 20 minutes.

### Step 4 — The 20-minute call

Agenda (strict):
1. **5 min** — Ask them to describe their agent topology. How many agents? On which clouds? What tools do they call? Let them talk.
2. **10 min** — Show the demo. AWS Bedrock live interception, sequence violation blocked in real time, audit log generated. Do not talk over the demo.
3. **5 min** — Describe the design partner offer explicitly. Emphasize the $5K filter and why: "We want partners who are serious about building this with us, not evaluating us."

Close with: "I'll send you a one-page design partner agreement. If it makes sense, we can have your staging environment instrumented within a week of signing."

### Step 5 — The agreement

Keep it to 1 page. Cover: free 6-month term, $5K design fee + credit, 2 hrs/week commitment, data confidentiality (their data never leaves their cluster — the sidecar does not exfiltrate logs), optional case study clause, preferred pricing formula.

Do not use a 20-page enterprise MSA. This kills momentum. Use a simple short-form agreement (Common Paper's Design Partner template is a good starting point).

---

## Onboarding (First 30 Days)

| Week | What Happens |
|---|---|
| **Week 1** | Agreement signed, $5K received. We schedule a 2-hour technical kickoff with their senior engineer. Sidecar deployed to their staging K8s cluster. |
| **Week 2** | First real agent traces captured. We review them together and identify the 3 most critical tool call sequences to govern. |
| **Week 3** | Sequence validation policies written in YAML. First enforcement rules running in staging. |
| **Week 4** | Full policy set in staging. Audit logs generating. We present a "State of Your Agent Fleet" report: X ungoverned agents discovered, Y policy violations blocked, Z cross-agent handoffs logged. |

The Month 1 report is the design partner's internal business case for moving to production — and our first real case study data.

---

## The Conversion (Month 6)

At Month 5, initiate the commercial conversation. By this point you have:
- 5 months of real agent telemetry
- A feature they requested, shipped and running
- A VP Engineering who has been in weekly contact with the founders

The commercial ask: annual subscription at the preferred rate locked at signing. Historical co-built product close rates: 70-80%. The $5K design fee offsets the first month.

Do not wait until Month 6 to start the commercial conversation.

---

## Priority Target List

| Priority | Company | The Specific Hook | Intro Path |
|---|---|---|---|
| 1 | **Razorpay** | Agent Studio built on Claude SDK on AWS; payment sequences need validation; CTO is IIT Bombay | IIT alumni network — direct peer outreach |
| 2 | **Freshworks** | CloudVerse on EKS; Freddy AI 50+ agentic workflows; deep IIT hiring pipeline | SaaSBOOMi community; IIT network |
| 3 | **Swiggy** | Databricks/AWS multi-agent; documented fraud urgency; multi-agent cross-handoff risk | Databricks India partner team; HasGeek Bangalore |
| 4 | **Gorgias** | 15K concurrent agent fleets; one injection = 15K merchants exposed; Temporal community overlap | YC network; Temporal Slack |
| 5 | **Waystar** | AWS + GCP confirmed dual-cloud; HIPAA audit trail mandatory; healthcare revenue cycle | AWS/Google Cloud partner managers |
| 6 | **Veeva Systems** | AWS Bedrock + Azure AI Foundry confirmed; 21 CFR Part 11 = validated audit trail; no SaaS competitor can serve GxP | AWS/Azure partner teams; Veeva Connect conference |
| 7 | **Personio** | AWS Bedrock EU; HR AI = EU AI Act Annex III high-risk; August 2026 is 5 months away | AWS EU partner ecosystem |

---

*AegionAI — The AI Security Control Plane*
*shashank31mar@gmail.com | aegionai.com*
