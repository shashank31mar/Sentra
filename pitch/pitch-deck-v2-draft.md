# Sentra — The Governance Layer for AI Agents
**Seed Pitch Deck · March 2026**

---

## Section 1: One Chatbot. Real Consequences.

In February 2024, a Canadian court ruled that Air Canada was legally liable for a refund policy its chatbot invented. The policy did not exist. The company had to pay. The judge's reasoning: *"A company is responsible for what its AI says."* ([CBC News](https://www.cbc.ca/news/canada/british-columbia/air-canada-chatbot-lawsuit-1.7116416))

This was not a one-off.

- **Swiggy, Nov 2024.** A customer used AI to generate a fake photo of cracked eggs. The automated refund agent approved the claim immediately. The technique went viral. ([India Today](https://www.indiatoday.in/trending-news/story/x-user-claims-swiggy-instamart-customer-used-ai-to-fake-cracked-eggs-for-refund-2826172-2025-11-26))
- **Microsoft Copilot EchoLeak, Aug 2024.** A zero-click vulnerability let attackers steal corporate data through Copilot. No user action required. ([Windows News AI](https://windowsnews.ai/article/echoleak-how-microsoft-365-copilots-zero-click-vulnerability-threatens-enterprise-data-security.370013))
- **Drift/Salesloft breach, Aug 2025.** One compromised AI chatbot token exposed data across 700+ companies, including Palo Alto Networks and Cloudflare. ([Trend Micro](https://www.trendmicro.com/en_us/research/25/i/ai-app-breach.html))

The common thread: **AI agents are making consequential decisions with no one watching.**

---

## Section 2: This Is Happening Everywhere

| Stat | Number | Source |
|------|--------|--------|
| Enterprises now running AI agents | 82% | [SailPoint, May 2025](https://www.sailpoint.com/press-releases/sailpoint-ai-agent-adoption-report) |
| Enterprises with security policies in place | 44% | Same |
| **Enterprises with AI agents and zero governance** | **38%** | Derived |
| E-commerce return fraud annually (AI-doctored claims +15% YoY) | $76.5B | [NRF, 2025](https://www.foxnews.com/tech/ai-takes-return-fraud-holiday-returns-surge) |
| Food delivery refund abuse globally | $103B | [Incognia](https://www.getcraver.com/blog/delivery-app-refund-abuse/) |
| EU AI Act fines (starts Aug 2, 2026) | Up to 7% of global revenue | EU Official |

More than one in three enterprises has deployed AI agents with no governance. Those agents are taking actions, making commitments, and handling sensitive data right now. In five months, regulators start issuing fines.

---

## Section 3: Let's Replay Air Canada — With Governance

Here is what should have happened.

1. Customer asks about bereavement fares.
2. Governance checks: Is this agent authorized to make refund commitments? **No** — flagged.
3. Agent attempts to describe a policy that doesn't exist. Governance compares the response against the actual policy database. Hallucination detected.
4. Response is blocked. Agent replies: *"I can't help with that directly — let me connect you to a human."*
5. Full incident is logged: the query, the attempted response, the policy rule it violated — feeds directly into compliance reports.

**This is what Sentra's working prototype does today:**

| Capability | Result |
|------------|--------|
| Prompt injection block rate | 97% (485/500 attacks stopped) |
| PII detection accuracy | 94% across 8 data types |
| Latency (p99) | <80ms — production-ready |
| False positives | Zero in 500-request clean dataset |
| Cross-agent attacks blocked | 12/12 |

The cost of the Air Canada incident: legal fees, a forced refund, and lasting brand damage.

**The cost of prevention: less than 80 milliseconds.**

---

## Section 4: What Sentra Does

### The Vision

When companies deployed thousands of containers in 2015, everything broke. No standardized security, no policy enforcement, no visibility across servers. Kubernetes solved this — a single control plane that governed container behavior across any cloud.

AI agents in 2026 are in the same chaos. Every agent is built differently. Every cloud has different rules. Nobody has a single view across all of them. **Sentra is the Kubernetes for AI agents.**

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
│                    Sequence valid. Audit trails  │
│                    Cross-agent     EU AI Act     │
│                    containment     reports       │
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

### Feature Journey: B2C → B2B → Enterprise

| Tier | Who Buys | The Problem They Have | What Sentra Does |
|------|-----------|-----------------------|------------------|
| **B2C — Year 1** | Food delivery, e-commerce (Swiggy, Gorgias, GoPuff) | AI agents approve fraudulent refunds, get tricked by fake images, get jailbroken by users | AI image fraud detection, prompt injection blocking, refund policy enforcement |
| **B2B SaaS — Year 2** | Intercom, Zendesk, Salesforce-tier (their AI serves thousands of their customers) | One compromised agent = breach across all of their customers | Multi-agent blast-radius containment, cross-agent attack blocking |
| **Enterprise — Year 2-3** | Fortune 500 running agents across AWS + Azure + GCP | No single governance layer across clouds, EU AI Act compliance gap | Cross-cloud unified policy, Kubernetes-native deployment, automated compliance reports |

---

## Section 5: Why Nobody Can Beat Sentra

### The Competitive Landscape

Every competitor sits in one of four boxes. The most valuable box — fleet-level security that works across every cloud — is empty.

```
                     SINGLE-CLOUD ONLY   │   CLOUD-AGNOSTIC
                                         │
 FLEET-LEVEL       AWS AgentCore         │   ← SENTRA
 SECURITY          Azure Entra Agent ID  │     (empty today)
 (governs agent    OpenAI Frontier        │
 fleets +          Microsoft Purview      │
 workflows)                              │
─────────────────────────────────────────┼────────────────────
 CALL-LEVEL                              │   Portkey.ai
 SECURITY          [No notable players]  │   LiteLLM / Helicone
 (one API call                           │
 at a time)                              │
```

**The top-right quadrant is empty because it's genuinely hard.** You need to intercept agents across AWS, Azure, GCP, and on-prem simultaneously — and enforce policies that span multiple steps of a workflow, not just single calls. No single-cloud vendor has the incentive to do this. No call-level gateway has the architecture to do it.

### Why Each Competitor Can't Close the Gap

| Competitor | What They Do | Why They Can't Beat Sentra |
|------------|--------------|----------------------------|
| **AWS AgentCore** | Best single-cloud security — 99% policy accuracy, formal verification | AWS-only by design. Will never govern Azure or GCP agents. That is their business model, not a bug. |
| **Lakera → Check Point** | Pattern-matching for prompt injection — 80M attack patterns | Acquired April 2025. Now a feature buried in a CISO's security suite. No fleet governance, no sequence validation, no cross-cloud. |
| **Portkey.ai** | LLM gateway — routes calls, applies per-call guardrails, 1,600+ providers | Governs individual API calls, not agent fleets. No cross-agent security, no Kubernetes-native deployment, no sequence validation. |
| **Microsoft Purview / Entra Agent ID** | Identity governance for agents on Azure | Azure-only. Identity layer only — no runtime enforcement, no cross-cloud. |

### Sentra's 3 Structural Moats

**1. Cross-cloud by design** — AWS, Azure, and GCP each lock you in. Sentra works across all three simultaneously. 82% of enterprises are already multi-cloud. This is a permanent structural gap no single-cloud vendor can fill.

**2. Tool call sequence validation** — No vendor can enforce "Step A must happen before Step B in this session." AWS's Cedar policy engine is stateless by design — it literally cannot track sequences. This is architectural, not a product gap. We built the first production approach: sidecar proxy + OPA + session event store. Confirmed March 2026: zero vendors have this.

**3. USPTO patent pending** — Core governance architecture for AI agents. Prior art search found zero existing patents in this exact space. 18–24 month barrier to entry.

---

## Section 6: The Market

### Size

| | 2025 | 2030 | Growth |
|--|------|------|--------|
| AI Agent Market | $7.84B | $52.62B | 46.3% CAGR |
| AI Governance TAM | $890M | $5.8B | 45.3% CAGR |

Source: [MarketsandMarkets](https://www.marketsandmarkets.com/Market-Reports/ai-agents-market-15761548.html), internal research March 2026

**96% of enterprises are expanding AI agent deployments in the next 12 months** — with half aiming for organization-wide expansion. ([Cloudera, April 2025](https://www.cloudera.com/about/news-and-blogs/press-releases/2025-04-16-96-percent-of-enterprises-are-expanding-use-of-ai-agents-according-to-latest-data-from-cloudera.html))

The governance gap is widening faster than anyone is filling it.

### Why Now — Four Forcing Functions

**1. Legal liability is case law** — Air Canada (Feb 2024) established that companies are responsible for what their AI agents say and do. Every company with a customer-facing AI is now legally exposed.

**2. Regulation goes live in 5 months** — EU AI Act full enforcement starts August 2, 2026. Penalty: up to 7% of global revenue. Companies can't wait — they need governance infrastructure now.

**3. The independent alternatives were acquired** — Lakera → Check Point (April 2025). CalypsoAI → F5 (Sept 2025). The market is validated but there is no independent, purpose-built platform left.

**4. The window is 12–18 months** — AWS, Azure, and GCP will each build governance into their own clouds. But they will only govern their own clouds. The company that establishes the multi-cloud standard before that happens owns the category permanently.

---

## Section 7: Five-Year Plan

### The Strategy in One Sentence

Start where the pain is obvious and the sales cycle is short (B2C fraud). Prove the product works. Then sell the real vision (multi-cloud agent security) to enterprises who need it most.

### Year-by-Year Roadmap

| Year | Theme | Target Customers | ARR Target | Key Milestone |
|------|-------|-----------------|------------|---------------|
| **2026** | Revenue validation — sell the fraud story | Swiggy, Zomato, Gorgias, GoPuff, Intercom | $150K–$300K | 3–5 paying customers; prototype → production |
| **2027** | Enterprise wedge — multi-cloud security narrative | Post-M&A tech, financial services, healthcare SaaS | $3M–$5M | Series A ($10–15M); 15–20 enterprise customers |
| **2028** | Category leadership — define the standard | Fortune 500 financial services, large SaaS, EU enterprises | $12M–$18M | CNCF sandbox submission; Series B ($30–50M) |
| **2029** | Global expansion — sell through channels | APAC, EU enterprises, mid-market via partners | $35M–$50M | AWS/Azure Marketplace; FedRAMP authorization |
| **2030** | Category dominance | Any company with 50+ AI agents | $75M–$100M | AgentPolicy CRD = industry standard; IPO or acquisition $500M–$1B+ |

### Why This Order

**Year 1 — B2C fraud first.** Enterprise sales take 90–180 days. B2C companies like Swiggy make decisions in 6–12 weeks. The viral egg fraud incident created real, documented urgency. India network gives direct access. Quick wins = investor proof points.

**Year 2 — Enterprise pivot.** With 3–5 customer stories, the narrative shifts: *"We started with fraud because it's the visible tip. The real problem is enterprises running agent fleets across three clouds with no governance."* Post-M&A companies (AWS + Azure by accident) are the ideal first enterprise targets — multi-cloud by accident, urgency by necessity.

**Year 3+ — Standards play.** Submit AgentPolicy CRD to CNCF. Open-source the policy engine. Follow HashiCorp's Terraform playbook: when you own the spec, you own the ecosystem. AWS couldn't beat Kubernetes with ECS. Nobody beats a standard once it's adopted at scale.

### The Ask

| | |
|--|--|
| **Raising** | $2M seed |
| **Use of funds** | 50% engineering (3 backend + 1 frontend + 1 PM) · 25% GTM · 10% compliance & patent · 15% ops & buffer |
| **Runway** | 24 months (India-based team) |
| **12-month milestone** | 3–5 paying customers, $150K–$300K ARR, SOC2 Type II in progress |

---

## The Team

**Shashank Gupta — Founder & CEO**

IIT alumnus. At Amazon, led a 50+ person team to build a new observability vertical across OpenSearch and CloudWatch — shipping profitable products across two orgs. Pioneered AI-native features including semantic search and conversational interfaces for OpenSearch used by millions of developers.

**Why this:** Witnessed firsthand how enterprises struggle to govern AI at scale. Filed USPTO patent on the core governance architecture. Built working prototype to 97% block rate at <80ms — without burning investor capital.

**On funding close:** Resigns from Amazon (14-day notice), transitions full-time Day 1.

---

*AI without governance is just liability at scale.*

*Sentra — [sentra.io needs rename before external use]*
