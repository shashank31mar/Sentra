# Sentra — The Governance Layer for AI Agents
**Seed Pitch Deck · March 2026**

---

## Section 1: One Chatbot. Real Consequences.

In February 2024, a Canadian court ruled that Air Canada was legally liable for a refund policy its chatbot invented. The policy did not exist. The company had to pay. The judge's reasoning: *"A company is responsible for what its AI says."*
→ [CBC News](https://www.cbc.ca/news/canada/british-columbia/air-canada-chatbot-lawsuit-1.7116416)

This was not a one-off.

- **Swiggy, November 2025.** A customer used AI to generate a fake photo of cracked eggs. The automated refund agent approved the claim instantly. The technique went viral — now used at scale.
→ [India Today](https://www.indiatoday.in/trending-news/story/x-user-claims-swiggy-instamart-customer-used-ai-to-fake-cracked-eggs-for-refund-2826172-2025-11-26)

- **Microsoft Copilot EchoLeak, August 2024.** A zero-click vulnerability let attackers steal corporate data through Copilot. No user action required.
→ [Windows News AI](https://windowsnews.ai/article/echoleak-how-microsoft-365-copilots-zero-click-vulnerability-threatens-enterprise-data-security.370013)

- **Drift/Salesloft breach, August 2025.** One compromised AI chatbot token exposed data across 700+ companies — including Palo Alto Networks and Cloudflare. A single AI integration became the entry point to breach the security industry itself.
→ [Trend Micro](https://www.trendmicro.com/en_us/research/25/i/ai-app-breach.html)

**The common thread: AI agents are making consequential decisions with no one watching.**

---

## Section 2: The Scale of the Problem

| Stat | Number | Source |
|------|--------|--------|
| Enterprises now running AI agents | 82% | [SailPoint, May 2025](https://www.sailpoint.com/press-releases/sailpoint-ai-agent-adoption-report) |
| Enterprises with security policies in place | Only 44% | Same |
| **Enterprises with agents and zero governance** | **38%** | Derived from same |
| E-commerce return fraud annually (AI-doctored claims +15% YoY) | $76.5B | [NRF 2025](https://www.foxnews.com/tech/ai-takes-return-fraud-holiday-returns-surge) |
| Additional breach cost per company when AI is ungoverned | +$670K | [IBM Cost of Data Breach 2025](https://www.ibm.com/reports/data-breach) |
| EU AI Act fines starting August 2, 2026 | Up to 7% of global revenue | EU Official |

More than one in three enterprises has AI agents running right now with zero governance. Those agents are making decisions, committing to policies, and handling sensitive data. The legal and financial exposure is not theoretical — it is active.

---

## Section 3: Why This Has to Be Solved Now

Four things are happening at once. Any one of them is enough urgency. All four together make this the must-build infrastructure of the next 18 months.

**1. Legal liability is now case law.**
Air Canada (February 2024) established that companies are liable for what their AI says. Every company with a customer-facing AI agent is legally exposed today.

**2. Regulation starts in 5 months.**
The EU AI Act begins full enforcement on August 2, 2026 — with penalties up to 7% of global revenue. Companies that don't have AI governance infrastructure in place will face fines. There is no time to wait.

**3. The independent alternatives were acquired.**
Lakera was acquired by Check Point in April 2025. CalypsoAI was acquired by F5 in September 2025. The market is validated — but these are now features buried inside enterprise security suites, not purpose-built platforms. There is no independent, standalone solution.

**4. The window is 12–18 months.**
AWS, Azure, and GCP will each build governance into their own clouds — but only for their own clouds. The company that establishes the cross-cloud standard before that happens owns the category permanently.

---

## Section 4: How It Should Have Worked — A Replay

Let's walk back through the Air Canada incident with proper governance in place.

1. Customer asks about bereavement fares.
2. Governance checks: Is this agent authorized to make refund commitments? **No** — flagged immediately.
3. Agent tries to describe a refund policy. Governance compares the response against the actual policy database. The policy doesn't exist — hallucination detected.
4. Response is blocked. Agent says: *"I can't confirm that policy directly — let me connect you to a human who can help."*
5. The entire interaction is logged — query, attempted response, policy rule violated — and fed into compliance reports.

No lawsuit. No refund. No viral screenshot.

**Sentra's working prototype already does this.** *Test methodology: 500-request closed-environment dataset, attacks curated from OWASP LLM Top 10 and published jailbreak catalogs.*

| Capability | Prototype Result |
|------------|-----------------|
| Prompt injection block rate | 97% (485/500 attacks stopped) |
| PII detection accuracy | 94% across 8 data types |
| Latency (p99) | <80ms — production-ready |
| False positives on clean requests | Zero in 500-request dataset |
| Cross-agent attacks blocked | 12/12 |

**The cost of the Air Canada incident: legal fees, a forced refund, lasting brand damage.**
**The cost of prevention: less than 80 milliseconds.**

---

## Section 5: What Sentra Builds

### The Vision

When companies deployed thousands of containers in the mid-2010s, everything broke. No standardized security, no policy enforcement, no visibility across servers. Kubernetes solved it — a single control plane that governed container behavior across any cloud.

AI agents in 2026 are in the same chaos. Every agent is built differently. Every cloud has its own rules. Nobody has a single view across all of them.

**Sentra is to AI agents what Kubernetes was to containers** — a control plane that governs every agent, across every cloud, from one place.

Think of it as the "rules engine" that sits between your AI agents and the outside world. Every action goes through Sentra first. Sentra checks: Is this allowed? Is this the right sequence of steps? Is this agent who it says it is? If yes — let it through. If no — block it, log it, alert the team.

```
┌─────────────────────────────────────────────────┐
│                 YOUR AI AGENTS                  │
│   (Chatbots • Refund Agents • Copilots • Bots)  │
└─────────────────────┬───────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────┐
│              SENTRA CONTROL PLANE               │
│                                                 │
│  POLICY            SECURITY        COMPLIANCE   │
│  ENFORCEMENT       ENFORCEMENT     + VISIBILITY │
│  ───────────────   ─────────────   ──────────── │
│  Block before      Prompt inject.  Real-time    │
│  it executes       PII detection   monitoring   │
│                    Step-sequence   Audit trails  │
│                    validation      EU AI Act     │
│                    Cross-agent     reports       │
│                    containment                   │
└─────────────────────┬───────────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
   ┌─────────┐   ┌─────────┐   ┌─────────┐
   │  AWS    │   │ Azure   │   │  GCP    │
   │ Bedrock │   │ OpenAI  │   │ Vertex  │
   └─────────┘   └─────────┘   └─────────┘
          + On-premise / air-gapped
```

### Feature Journey: How Sentra Grows With Customers

Sentra starts where the pain is clearest and the sales cycle is shortest, then expands upmarket as reference cases compound.

| Stage | Who Buys | Their Specific Problem | What Sentra Does |
|-------|-----------|------------------------|-----------------|
| **B2C — Year 1** | Food delivery, e-commerce platforms (Swiggy, Gorgias, GoPuff) | AI agents approve fraudulent refund claims; users trick bots with fake images | AI image fraud detection, prompt injection blocking, refund policy enforcement |
| **B2B SaaS — Year 2** | Customer service platforms (Intercom, Zendesk) whose AI product serves thousands of their business customers | One of their customers' agents gets compromised → blast radius hits all their customers | Cross-agent attack containment: stops a breach in one agent from spreading to others |
| **Enterprise — Year 2-3** | Fortune 500 companies running AI agents on AWS AND Azure AND GCP simultaneously | No single governance layer spans all three clouds; EU AI Act compliance gap; audit teams can't explain what AI did | Unified cross-cloud policy engine, automated compliance reports (EU AI Act, SOC2, HIPAA) |

### Pricing

| Tier | Who | Price |
|------|-----|-------|
| **Starter** | B2C platforms, <50 agents | $5K–$15K/month flat |
| **Business** | B2B SaaS, 50–500 agents | $15K–$50K/month + per-agent fee |
| **Enterprise** | Fortune 500, multi-cloud, compliance reports | $150K–$750K/year (custom contract) |

*Year 1 target: $60K average ACV. Year 2 target: $200–300K average ACV.*

---

## Section 6: Why Nobody Can Beat Sentra

### The Competitive Landscape

Every existing player sits in one of four boxes. The most valuable box — fleet-level security that works across every cloud — is empty.

```
                     SINGLE-CLOUD ONLY   │   CLOUD-AGNOSTIC
                                         │
 FLEET-LEVEL       AWS AgentCore         │   ← SENTRA
 SECURITY          Azure Entra Agent ID  │     (empty today)
 (governs entire   OpenAI Frontier       │
 agent fleets +    Microsoft Purview     │
 multi-step                              │
 workflows)                              │
─────────────────────────────────────────┼────────────────────
 CALL-LEVEL                              │   Portkey.ai
 SECURITY          [No notable players]  │   LiteLLM / Helicone
 (checks one                             │
 API call at                             │
 a time)                                 │
```

**The top-right quadrant is genuinely empty** — not because nobody thought of it, but because it requires both a cross-cloud architecture and the ability to govern entire agent workflows (not just single calls). Single-cloud vendors have no incentive to go cross-cloud. Call-level gateways lack the architecture to enforce across multiple steps of a workflow. Both gaps are structural, not fixable with a product sprint.

### Why Each Competitor Can't Close the Gap

| Competitor | What They Do | Why They Can't Beat Sentra |
|------------|--------------|----------------------------|
| **AWS AgentCore** | Best single-cloud agent security — 99% policy accuracy using formal verification | AWS-only by design. This is a feature, not a bug — vendor lock-in is their revenue model. They will never govern Azure or GCP agents. |
| **Lakera → Check Point** | Pattern-matching for prompt injection — 80M attack patterns | Acquired April 2025. Now a feature inside a CISO's security suite, not a purpose-built platform. No fleet governance, no step-sequence validation, no cross-cloud. |
| **Portkey.ai** | LLM gateway — routes calls, per-call guardrails, 1,600+ providers | Governs individual API calls, not agent fleets. No cross-agent security, no multi-step workflow enforcement. Their stated goal is "LLM governance" — ours is "agent fleet governance." Different level of abstraction. |
| **Microsoft Purview / Entra Agent ID** | Identity governance for agents on Azure | Azure-only. Identity layer only — no runtime enforcement, no cross-cloud, no workflow-level control. |

### Sentra's 3 Structural Moats

**1. Cross-cloud is a permanent gap — not a temporary one.**
82% of enterprises run workloads across multiple clouds ([CNCF 2026 survey](https://www.cncf.io)). AWS, Azure, and GCP each govern their own agents — and will only ever govern their own. The company that governs agents across all three simultaneously fills a hole that every cloud vendor is structurally prevented from filling. This moat grows every year that enterprises deepen their multi-cloud commitments.

**2. Step-by-step workflow validation — nobody has built this.**
Think of it this way: a bank's AI agent should never transfer money without first checking the account balance. Current security tools check whether a specific action is "allowed" — but they can't enforce the *order* of steps. It's the difference between checking if someone has a car key and checking if they actually unlocked the door before starting the engine.

Competitors like AWS AgentCore use a policy engine called Cedar — which is intentionally stateless (it checks each step independently with no memory). This is the right design for fast access control, but it means Cedar **structurally cannot** enforce step sequences. Confirmed March 2026 review of Lakera, Portkey, AWS AgentCore, Palo Alto Prisma AIRS, and Microsoft Purview: zero vendors have production-grade step-sequence validation.

**3. USPTO patent pending — first mover IP.**
Core governance architecture for AI agents. Attorney-conducted prior art search found zero existing patents in this exact space. Creates an 18–24 month barrier to entry for direct replication.

---

## Section 7: The Market

### Market Size

| | 2025 | 2030 | CAGR |
|--|------|------|------|
| AI Agent Market | $7.84B | $52.62B | 46.3% |
| AI Governance TAM | $890M | $5.8B | 45.3% |

Sources: [MarketsandMarkets](https://www.marketsandmarkets.com/Market-Reports/ai-agents-market-15761548.html) · Internal research, March 2026

**96% of enterprises plan to expand AI agent deployments in the next 12 months** — half targeting organization-wide rollout.
→ [Cloudera, April 2025](https://www.cloudera.com/about/news-and-blogs/press-releases/2025-04-16-96-percent-of-enterprises-are-expanding-use-of-ai-agents-according-to-latest-data-from-cloudera.html)

The governance gap is widening faster than anyone is closing it. Every new AI agent deployment without governance is a new liability.

### Sentra's Reachable Market (First 3 Years)

| Year | Target Segment | Companies in Segment | Realistic Win Rate | ARR |
|------|---------------|----------------------|--------------------|-----|
| 2026 | B2C fraud — food delivery + e-commerce platforms | ~500 globally, ~50 in India | 1% | $150K–$300K |
| 2027 | Enterprise — post-M&A multi-cloud, financial services | ~200–500 companies with active multi-cloud agent pain | 3–5% | $3M–$5M |
| 2028 | Category expansion — Fortune 500, healthcare, EU compliance | ~2,000 companies | 2–3% | $12M–$18M |

---

## Section 8: Five-Year Plan

### Strategy in One Sentence

Start where urgency is immediate and sales cycles are short (B2C fraud) — use those wins to prove the product works — then sell the full platform to enterprises who need multi-cloud agent governance.

### Year-by-Year Roadmap

| Year | Theme | Who We Sell To | ARR | Key Milestone |
|------|-------|---------------|-----|---------------|
| **2026** | Revenue validation | Swiggy, Zomato, Gorgias, GoPuff, Intercom | $150K–$300K | 3–5 paying customers; production-grade MVP |
| **2027** | Enterprise wedge | Post-M&A tech companies, financial services, healthcare SaaS | $3M–$5M | Series A ($10–15M); 15–20 enterprise customers; SOC2 Type II |
| **2028** | Category leadership | Fortune 500 finance, large SaaS, EU enterprises | $12M–$18M | CNCF sandbox submission; Series B ($30–50M) |
| **2029** | Global expansion | APAC, EU, mid-market via partners | $35M–$50M | AWS/Azure Marketplace; FedRAMP authorization |
| **2030** | Standard dominance | Any company with 50+ AI agents | $75M–$100M | AgentPolicy CRD = industry standard; IPO or acquisition $500M–$1B+ |

### Why This Order — The Logic

**Year 1 — B2C fraud first.**
Enterprise sales take 90–180 days and require security certifications we're building toward. B2C companies like Swiggy make product decisions in 6–12 weeks. The viral egg fraud incident (November 2025) means their pain is documented and urgent. Direct access via India and Amazon network. Quick wins build the reference cases that unlock enterprise doors.

**Year 2 — Enterprise pivot.**
With 3–5 paying customers and real performance data, the narrative shifts to its natural endpoint: *"We started with fraud because it's the visible tip. The real problem is enterprises running agent fleets across three clouds with no single governance layer."* Post-M&A companies — those who acquired their way into AWS on one side and Azure on the other — are the ideal first enterprise targets. Multi-cloud by accident. Urgency by necessity.

**Year 3+ — Standards play.**
Submit AgentPolicy CRD specification to CNCF (the standards body that governs Kubernetes). Open-source the core policy engine — follow the HashiCorp Terraform playbook. When you define the spec, you own the ecosystem. AWS could not beat Kubernetes with ECS. Azure could not beat it with Service Fabric. Nobody beats a standard once it is adopted. The open-source core also blocks Portkey from owning this specification.

### GTM Mechanics (How We Get The First 5 Customers)

- **Direct outreach via IIT + Amazon network** — warm introductions to Head of Fraud, VP Product at Swiggy, Zomato, and Gorgias-tier companies
- **EU AI Act whitepaper** — "AI Agent Governance for EU AI Act Compliance" — outbound hook for enterprise outreach, August 2026 deadline creates forced urgency
- **KubeCon EU presence** (March 2026) — platform engineering buyer venue; first conference appearance
- **Technical blog series** — "How AI Fraud Works and How to Stop It" — drives inbound from the same buyer profile

---

## Section 9: The Ask

| | |
|--|--|
| **Raising** | $2M seed |
| **Use of funds** | 50% engineering (3 backend + 1 frontend + 1 PM) · 25% GTM · 10% compliance & patent prosecution · 15% ops & buffer |
| **Runway** | 24 months (India-based team) |
| **12-month milestone** | 3–5 paying customers · $150K–$300K ARR · SOC2 Type II initiated · Patent prosecution underway |

---

## Section 10: Team

**Shashank Gupta — Founder & CEO**

IIT alumnus. At Amazon, led a 50+ person team to build a new observability vertical across OpenSearch and CloudWatch — shipping profitable products across two organizations. Built and launched semantic search and conversational interfaces for OpenSearch, now used by enterprise developer teams worldwide.

**Why this problem:** Witnessed firsthand at Amazon how enterprises struggle to govern AI systems at scale. After the Air Canada, Swiggy, and Microsoft Copilot incidents, recognized the missing layer: a governance control plane for AI agents — not a security feature, but core infrastructure. Filed USPTO patent, built working prototype, now assembling the team.

**Current status:** Employed at Amazon while building the prototype and securing IP — a deliberate approach to de-risk the technical and IP foundation without burning investor capital. On funding close: resign (14-day notice), full-time Day 1.

**Co-founder / CTO:** Actively recruiting from AWS infrastructure, Confluent, and Datadog engineering backgrounds. Two conversations in late stages. Will not close the round without naming a technical co-founder.

**Phase 1 hires (post-funding):**
- 2 Backend Engineers — platform core, policy engine, cloud integrations
- 1 Frontend Engineer — real-time dashboard, compliance reports UI
- 1 Product Manager — customer discovery, roadmap, pilot deployments
- 1 UX Designer — operator experience across the control plane

---

## Appendix: EU AI Act — What Sentra Specifically Delivers

For enterprises asking "what does Sentra actually do for EU AI Act compliance":

| EU AI Act Requirement | What It Means in Plain English | Sentra's Answer |
|-----------------------|-------------------------------|-----------------|
| Article 9: Risk management system | Document how your AI agent makes decisions | Automated audit trail of every agent action, policy applied, and outcome |
| Article 10: Data governance | Know what data your agents access and process | PII detection and redaction logs; data access inventory per agent |
| Article 13: Transparency and traceability | Explain what your AI did when asked | Full chain-of-custody log exportable for regulator review |
| Article 17: Quality management system | Systematic approach to AI quality and safety | Policy enforcement framework with SOC2 Type II certification |

Full enforcement: August 2, 2026. Penalty: up to €35M or 7% of global annual revenue, whichever is higher.

---

*"AI without governance is just liability at scale."*

*— Sentra, March 2026*

> **Note:** Company operating under working name "Sentra." Rename required before external activity — sentra.io is an unrelated $30M Series A company (AI data security). New name in selection.
