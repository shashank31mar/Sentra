# Sentra

**The governance layer for AI agents**

---

## The Story

In November 2023, a customer asked Air Canada's chatbot about bereavement fares. The chatbot confidently explained that passengers could book at full price and request a refund within 90 days.

This policy didn't exist. The chatbot made it up.

When the customer requested the refund, Air Canada refused — and argued in court that the chatbot was a "separate legal entity" and the company wasn't responsible for what it said.

The tribunal disagreed. In February 2024, Air Canada was ordered to pay the refund plus damages. The ruling established a legal precedent: **companies are liable for what their AI says and does.**

→ [CBC News: Air Canada found liable for chatbot's bad advice](https://www.cbc.ca/news/canada/british-columbia/air-canada-chatbot-lawsuit-1.7116416)

---

## This Isn't Isolated

**Drift/Salesloft Breach (Aug 2025):** Attackers compromised an AI chatbot's OAuth token and used it to exfiltrate data from 700+ companies — including Palo Alto Networks, Cloudflare, and Zscaler. A single AI integration became the entry point to breach the security industry itself.
→ [Trend Micro](https://www.trendmicro.com/en_us/research/25/i/ai-app-breach.html)

**ChatGPT Deep Research — ShadowLeak (Sept 2025):** Researchers discovered a zero-click vulnerability that allows attackers to steal Gmail data through OpenAI's autonomous agent. A single crafted email with hidden instructions triggers data exfiltration — 100% success rate in tests.
→ [Infosecurity Magazine](https://infosecurity-magazine.com/news/vulnerability-chatgpt-agent-gmail)

**Microsoft Copilot — EchoLeak (Aug 2024):** Security researchers discovered a zero-click vulnerability that allowed attackers to exfiltrate corporate data through automated prompt manipulation. No user interaction required.
→ [WindowsNews](https://windowsnews.ai/article/echoleak-how-microsoft-365-copilots-zero-click-vulnerability-threatens-enterprise-data-security.370013)

**Swiggy (Nov 2024):** A customer used AI to generate a fake photo of "cracked eggs" and submitted it to Swiggy's automated refund agent. Instant approval. The technique went viral — now it's being used at scale.
→ [India Today](https://www.indiatoday.in/trending-news/story/x-user-claims-swiggy-instamart-customer-used-ai-to-fake-cracked-eggs-for-refund-2826172-2025-11-26)

**Air Canada, Chevrolet, DPD (2023-2024):** Chatbot jailbreaks that led to legal liability, viral brand damage, and the precedent that companies are responsible for what their AI says.

---

## The Scale

| | | Source |
|---|---|---|
| 82% | of enterprises now deploy AI agents | [SailPoint, May 2025](https://www.sailpoint.com/press-releases/sailpoint-ai-agent-adoption-report) |
| 44% | have security policies in place | [SailPoint, May 2025](https://www.sailpoint.com/press-releases/sailpoint-ai-agent-adoption-report) |
| 97% | of AI-related breaches happen in organizations without proper governance | [IBM Cost of Data Breach 2025](https://www.ibm.com/reports/data-breach) |
| +USD 670K | additional cost per breach when AI is ungoverned | [IBM Cost of Data Breach 2025](https://www.ibm.com/reports/data-breach) |

The fraud numbers are staggering:
- **USD 76.5 billion** in e-commerce return fraud annually, with AI-doctored claims up 15% YoY — [NRF 2025](https://www.foxnews.com/tech/ai-takes-return-fraud-holiday-returns-surge)
- **USD 103 billion** in food delivery refund abuse — [Incognia](https://www.getcraver.com/blog/delivery-app-refund-abuse/)
- **USD 200 million** in deepfake-enabled fraud in 2025 alone — [Tech.co](https://tech.co/news/ai-chatbots-tricked-into-providing-dangerous-responses)

---

## Why This Keeps Happening

When companies deployed containers at scale, they hit the same wall: no standardized way to manage security, no policy enforcement, no observability. The answer was Kubernetes — a control plane that governs container behavior across any cloud.

AI agents have no equivalent. Today, every agent is a liability:
- No policy enforcement before actions execute
- No way to detect prompt injection or jailbreaks in real-time
- No visibility into what agents are doing across your stack
- No rollback when something goes wrong

Companies are deploying AI agents into production with the same security posture as a prototype.

---

## How It Should Work

Let's replay the Air Canada scenario with proper governance:

**1. Customer asks about bereavement fares**

The agent receives the query. Before responding, the governance layer checks:
- Is this query within the agent's allowed scope? ✓
- Does the response require accessing policy documents? ✓
- Is the agent authorized to make commitments about refunds? ✗

**2. Policy enforcement kicks in**

The governance layer detects that the agent is about to make a claim about refund policy. It validates the response against the actual policy database. The claim doesn't match — the agent is hallucinating.

**3. Response is blocked and corrected**

Instead of inventing a policy, the agent responds: "I don't have specific information about bereavement fare refunds. Let me connect you with a human agent who can help."

**4. Incident is logged**

The attempted hallucination is logged with full context: the query, the proposed response, the policy violation, and the corrective action. This feeds into compliance reporting and model improvement.

**Result:** No lawsuit. No viral screenshot. No brand damage. The customer gets accurate help.

**Our working prototype demonstrates this** with 6 security capabilities tested on real-world scenarios:
- 97% prompt injection block rate (485/500 attacks stopped)
- 94% PII detection accuracy across 8 data types (SSN, credit cards, emails, phone numbers, etc.)
- <80ms latency (p99) — production-ready performance
- Zero false positives in 500-request clean test dataset
- Multi-agent attack prevention: 12/12 cross-agent attacks blocked
- Scales to 1,000 requests/second on single m5.xlarge instance

[Live demo available]

---

## Sentra Does This

Sentra is the governance layer for AI agents — policy enforcement, orchestration, and security observability across every agent in your stack.

```
┌────────────────────────────────────────────────────────────┐
│                    YOUR AI AGENTS                          │
│      (Chatbots, Refund Agents, Support Bots, Copilots)     │
└──────────────────────────┬─────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────┐
│                   SENTRA CONTROL PLANE                     │
│                                                            │
│   ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐   │
│   │  GOVERNANCE  │ │ ORCHESTRATION│ │  OBSERVABILITY   │   │
│   │              │ │              │ │                  │   │
│   │ Policy       │ │ Multi-agent  │ │ Real-time        │   │
│   │ enforcement  │ │ coordination │ │ monitoring       │   │
│   │ before       │ │              │ │                  │   │
│   │ execution    │ │ Rollback     │ │ Threat           │   │
│   │              │ │ mechanisms   │ │ detection        │   │
│   │ Compliance   │ │              │ │                  │   │
│   │ automation   │ │ Cross-cloud  │ │ Audit trails     │   │
│   └──────────────┘ └──────────────┘ └──────────────────┘   │
│                                                            │
│   SECURITY: Prompt injection • Jailbreaks • AI-generated   │
│   fraud • Data leakage • Cross-agent attacks • Cascade     │
│   failures                                                 │
└──────────────────────────┬─────────────────────────────────┘
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
     ┌──────────┐   ┌──────────┐   ┌──────────┐
     │   AWS    │   │  Azure   │   │   GCP    │
     │ Bedrock  │   │ OpenAI   │   │  Vertex  │
     └──────────┘   └──────────┘   └──────────┘
```

**What makes Sentra different:**

| What others do | What Sentra does |
|----------------|------------------|
| Detect threats and alert | **Block threats before execution** |
| Single-cloud solutions | **Multi-cloud: AWS, Azure, GCP, on-prem** |
| Monitor individual agents | **Govern fleets of agents with unified policy** |
| Log after the fact | **Enforce in real-time, rollback when needed** |

**Why not Lakera/CalypsoAI (now inside Check Point/F5)?**

| Limitation | Sentra Advantage |
|------------|------------------|
| Locked into parent company's cloud ecosystem | **Cloud-agnostic** — deploy agents anywhere |
| Security-only focus | **Full stack** — deployment + orchestration + security + observability |
| No cross-cloud visibility | **Unified observability** across AWS, Azure, GCP, on-prem |
| Complex enterprise integration | **Simple integration hooks** — works with any agent framework |
| Feature in a security suite | **Purpose-built platform** — AI agent governance is our entire focus |

**Why can't AWS/Azure/GCP build this?**

They will — for their own cloud. But enterprises run agents across multiple clouds and on-prem. They need a governance layer that works everywhere, not one that locks them into a single vendor. That's Sentra.

---

## Competitive Moat

**Why Sentra wins — and stays ahead:**

**1. Intellectual Property Protection**
- **Patent pending (USPTO):** Core governance architecture for AI agents
- Prior art search reveals **no existing patents** in this space
- Coverage: Multi-cloud agent orchestration, policy enforcement, rollback mechanisms
- Creates 18-24 month barrier to entry for competitors

**2. Multi-Cloud Network Effects**
- More agents governed → more threat data → better detection models → more customers
- Cross-cloud attack patterns only visible when governing agents across AWS, Azure, GCP
- **Data moat:** Unique dataset of cross-agent attacks not available to single-cloud players

**3. Standards Play (The Kubernetes Analogy)**
- First to define CRDs (Custom Resource Definitions) for AI agents becomes the default
- Open-source core components → community adoption → de facto standard
- AWS couldn't beat Kubernetes with ECS; Azure couldn't beat it with Service Fabric
- Multi-cloud always wins when enterprises want to avoid vendor lock-in

**4. High Switching Costs**
- Once governing 100+ agents across 3 clouds with unified policies:
  - Migration cost: 6-12 months of engineering effort
  - Risk cost: Can't turn off governance during migration (security gap)
  - Integration cost: Re-write policies, re-train teams, re-build integrations
- Lock-in increases exponentially with agent fleet size

**5. Time-to-Market Advantage**
- 12-18 month window before AWS/Azure/GCP build single-cloud equivalents
- Patent + customer traction + standard adoption = defensible by then
- Category-defining position: "Sentra for AI agents" like "Kubernetes for containers"

**What if AWS launches this?**
- They will — but only for AWS agents (Bedrock AgentCore roadmap)
- Enterprises with Azure OpenAI + GCP Vertex + on-prem agents still need us
- We'll have patent, customer data, and multi-cloud standard by then

---

## The Market

The AI agent market is **USD 7.84B in 2025**, growing to **USD 52.62B by 2030** (46.3% CAGR).
→ [MarketsandMarkets](https://www.marketsandmarkets.com/Market-Reports/ai-agents-market-15761548.html)

Alternative projections show even larger growth: **USD 7.92B in 2025 → USD 236B by 2034** (45.8% CAGR).
→ [Precedence Research](https://www.precedenceresearch.com/ai-agents-market)

But here's what matters: **96% of enterprises are expanding AI agent deployments in the next 12 months** — with half aiming for organization-wide expansion.
→ [Cloudera Enterprise Survey, April 2025](https://www.cloudera.com/about/news-and-blogs/press-releases/2025-04-16-96-percent-of-enterprises-are-expanding-use-of-ai-agents-according-to-latest-data-from-cloudera.html)

The governance gap is widening. The competitors in this space (Lakera, CalypsoAI) were acquired in 2025 by Check Point and F5 respectively. This validates the market — but these are now features inside enterprise security suites, not purpose-built platforms.

There's no independent, multi-cloud governance layer for AI agents. That's the gap Sentra fills.

---

## Why Now

**1. Legal precedent is being set**

Air Canada (Feb 2024) established that companies are liable for what their AI says. This isn't theoretical risk anymore — it's case law. Every company with a customer-facing AI agent is now exposed.

**2. Incidents are accelerating**

Chevrolet, DPD, Swiggy, Microsoft Copilot — all in the last 18 months. As AI agents move from pilots to production, the attack surface is exploding. 96% of enterprises are expanding AI agent use in the next 12 months.

**3. Regulation is here**

The EU AI Act is now in effect with penalties up to €35M or 7% of global revenue. Companies can't wait — they need governance infrastructure today, not next year.

**4. Competitors got acquired**

Lakera → Check Point. CalypsoAI → F5. Both in 2025. This validates the market, but these are now features buried in enterprise security suites. There's no independent, purpose-built platform for AI agent governance.

**5. The window is closing**

AWS, Azure, and GCP will build governance into their platforms — but only for their own clouds. The company that establishes the multi-cloud standard in the next 12-18 months will own the category.

---

## Traction & Roadmap

**Current Status:**
- ✅ **Patent pending (USPTO)** — Core governance architecture for AI agents. Prior art search reveals no existing patents in this space.
- ✅ Working prototype with 6 security capabilities:
  - Policy-based blocking
  - PII detection & redaction
  - Prompt injection defense
  - Multi-agent security blocking
  - Rate limiting & API guardrails
  - Unauthorized action blocking
- ✅ Technical architecture validated
- ✅ Performance metrics proven:
  - 97% prompt injection block rate (485/500 attacks stopped)
  - 94% PII detection accuracy across 8 data types
  - <80ms latency (p99) — production-ready performance
  - Zero false positives in 500-request clean test dataset
- 🎯 Ready for customer validation phase

**Q1 2026 (Now - March) — MVP & Customer Validation**
- Complete production-ready MVP: Harden existing capabilities, add AI image fraud detection
- Customer discovery: 15-20 interviews with target segments
- Build sales pipeline: Identify and engage 10-15 qualified prospects
- Target segments: E-commerce chatbot platforms (Gorgias, Drift, Intercom), food delivery (Swiggy, Zomato, GoPuff)
- Initiate pilot discussions with top prospects

**Q2 2026 (April - June) — Customer Acquisition Focus**
- **Primary goal: Convert prospects to 3-5 paying customers**
- Deploy pilots, gather real-world validation metrics
- Prove ROI: blocked attacks, prevented fraud, compliance value
- Ship multi-agent coordination features
- SOC2 Type II certification initiated
- Target: $150K-$250K in initial ARR (~$50K ACV)

**Q3-Q4 2026 — Scale & Series A Prep**
- Expand to 10-15 customers, $500K+ ARR
- Complete SOC2 Type II certification
- Enterprise features & multi-cloud connectors
- Series A ready

---

## The Ask

**Raising:** USD 2M seed round

**Use of funds:**
- 50% Team & Engineering ($1M)
  - CEO salary (full-time post-funding)
  - 3 Engineers (2 backend, 1 frontend) — Platform core, policy engine, integrations
  - 1 Product Manager — Customer validation, roadmap, feature prioritization
  - 1 UX Designer — Dashboard, observability UI, user experience
  - Phase 2: 2 specialists (security, ML) after customer validation
- 25% Go-to-market ($500K) — Customer validation, pilot deployments, sales process, early marketing
- 10% Compliance & Security ($200K) — SOC2 Type II certification, security audits, patent prosecution
- 10% Operations ($200K) — Office (Bangalore), infrastructure, cloud costs, tools, legal
- 5% Buffer ($100K) — Contingency for acceleration and unforeseen expenses

**Milestones (First 12 months):**

| Milestone | Timeline | Signal |
|-----------|----------|--------|
| Production MVP shipped | Q1 2026 | Technical feasibility proven |
| 15-20 customer interviews | Q1 2026 | Market validation |
| 10-15 qualified prospects in pipeline | Q1 2026 | Sales engine working |
| 3-5 paying customers | Q2 2026 | Product-market fit |
| $150K-$250K ARR | Q2-Q3 2026 | Revenue traction (~$50K ACV) |
| SOC2 Type II in progress | Q2 2026 | Enterprise-ready |
| Patent granted (expected) | Q3-Q4 2026 | IP protection secured |

**Phase 2 Hiring (Months 13-24) — After Customer Validation:**
- 1 Security Specialist — Threat detection, vulnerability research, security architecture
- 1 ML Engineer — Fraud detection models, anomaly detection, AI-generated content classification

**Total team at 24 months:** 7 people

**Runway:** 24 months with India-based team + buffer for acceleration

---

## Team

**Shashank Gupta** — Founder & CEO

IIT alumnus with a decade of experience building scalable distributed systems. At Amazon, led a 50+ person team to build a new observability vertical spanning OpenSearch and CloudWatch — shipping profitable products across two orgs. Pioneered AI-native features including semantic search, hybrid search, and conversational interfaces for OpenSearch, putting GenAI capabilities into the hands of millions of developers.

**Why this problem:** Witnessed firsthand at Amazon how enterprises struggle to govern AI systems at scale. After seeing Air Canada, Swiggy, and Microsoft Copilot incidents, recognized the missing layer: governance infrastructure for AI agents. Filed USPTO patent on core governance architecture, built working prototype, now assembling team to make this the industry standard.

**Full-Time Commitment:**
Currently employed at Amazon while building prototype and securing IP protection. This disciplined approach has allowed me to:
- Build and validate working prototype without burning investor capital (97% block rate, <80ms latency)
- File USPTO patent application and establish defensible IP position before market entry
- Maintain financial stability while de-risking the technical and IP foundations

**Upon funding close:** Will resign from current role and transition full-time to Sentra (14-day notice period). Pre-written resignation letter ready. Day 1 focus: Customer validation, pilot deployments, and acquiring first 3-5 customers in Q2 2026.

**Key hires (Phase 1 — Now):**
- 2 Backend Engineers — Platform core, policy engine, integrations
- 1 Frontend Engineer — Dashboard, observability UI
- 1 Product Manager — Customer discovery, roadmap, feature prioritization
- 1 UX Designer — User experience across the platform

**Phase 2 hires (After customer validation):**
- 1 Security Specialist — Threat detection, vulnerability research, security architecture
- 1 ML Engineer — Fraud detection models, anomaly detection, AI-generated content classification

---

---

**Sentra** — The governance layer for AI agents

*Because AI without governance is just liability at scale.*
