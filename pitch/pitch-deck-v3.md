# Sentra *(placeholder)* — The AI Security Control Plane
**March 2026**

---

## 1. The Incident

In early 2026, a popular open-source AI agent framework called OpenClaw — used by over 135,000 developers — was found to contain 1,184 malicious packages in its skill marketplace. Roughly one in five packages was compromised. Attackers used these skills to silently hijack AI agents, steal data, and pivot across enterprise systems. More than 21,000 agent deployments were exposed before the incident was contained.
→ [SecurityWeek: OpenClaw vulnerability allowed malicious websites to hijack AI agents](https://www.securityweek.com/openclaw-vulnerability-allowed-malicious-websites-to-hijack-ai-agents/)

This is not the first time. And it will not be the last.

**A pattern of incidents, each one larger than the last:**

- **Air Canada, February 2024.** A company chatbot invented a refund policy that didn't exist and committed to it in writing. A court ruled Air Canada liable. First legal precedent: *companies are responsible for what their AI says.*
→ [CBC News](https://www.cbc.ca/news/canada/british-columbia/air-canada-chatbot-lawsuit-1.7116416)

- **Microsoft Copilot EchoLeak, August 2024.** A zero-click vulnerability allowed attackers to steal corporate data through Copilot without any user interaction.
→ [Windows News AI](https://windowsnews.ai/article/echoleak-how-microsoft-365-copilots-zero-click-vulnerability-threatens-enterprise-data-security.370013)

- **Drift/Salesloft, August 2025.** One compromised AI chatbot credential became the entry point to breach 700+ companies simultaneously — including Palo Alto Networks and Cloudflare.
→ [Trend Micro](https://www.trendmicro.com/en_us/research/25/i/ai-app-breach.html)

> **★ The example Sentra is built to prevent:**
>
> **Swiggy, November 2025.** A customer used AI to generate a fake photo of cracked eggs and submitted it to Swiggy's automated refund agent. The agent approved the refund immediately — no verification step was enforced. The technique spread widely on social media and has been replicated across food delivery platforms, per India Today reporting and subsequent industry coverage.
> → [India Today](https://www.indiatoday.in/trending-news/story/x-user-claims-swiggy-instamart-customer-used-ai-to-fake-cracked-eggs-for-refund-2826172-2025-11-26)
>
> This attack succeeded not because the fraud detection failed — it succeeded because the agent skipped a required verification step. A governance layer that enforces *the order of actions* would have blocked it, regardless of how convincing the fake image was.

**The common thread across every incident: it is not the AI that failed. It is the missing governance layer.**

---

## 2. The Scale

These are not edge cases. They reflect a structural gap across the industry.

| Stat | Number | Source |
|------|--------|--------|
| Enterprises now running AI agents | 82% | [SailPoint, May 2025](https://www.sailpoint.com/press-releases/sailpoint-ai-agent-adoption-report) |
| Enterprises with formal AI security policies | 44% | [SailPoint, May 2025](https://www.sailpoint.com/press-releases/sailpoint-ai-agent-adoption-report) |
| **The governance gap** | **38 percentage points — nearly 4 in 10 enterprises** | Derived: 82% − 44% = 38%. Source data above. |
| Additional cost per breach when AI systems are ungoverned | +$670,000 per incident | [IBM Cost of Data Breach 2025](https://www.ibm.com/reports/data-breach) |
| E-commerce return fraud annually; AI-generated fraud claims up 15% year-over-year | $76.5 billion | [NRF, 2025](https://www.foxnews.com/tech/ai-takes-return-fraud-holiday-returns-surge) |
| EU AI Act — full enforcement date | August 2, 2026 | [EU Official Journal, Regulation 2024/1689](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:L_202401689) |
| EU AI Act — maximum fine | 7% of global annual revenue or €35M, whichever is higher | Same |

**The governance gap is larger than it looks.** 82% of enterprises are deploying AI agents. Only 44% have any security policy in place — that is the obvious 38-point gap. But even that 44% has a blind spot: their security policies govern each cloud separately. Having an AWS policy and an Azure policy is not cross-cloud governance. AWS AgentCore governs AWS agents. Azure Entra Agent ID governs Azure agents. Neither governs the other's cloud. No company today has a single governance layer that enforces unified policy across AWS, Azure, and GCP agents simultaneously — because no such product exists.

**The multi-cloud governance gap is not a subset of the 38%. It spans the full 82%.** Every enterprise running AI agents on more than one cloud has this problem — regardless of how mature their existing security posture is. That is the problem Sentra solves.

And on August 2, 2026, the EU starts fining companies that haven't addressed this at all.

---

## 3. Why This Keeps Happening

Every incident above is different on the surface — a food delivery refund, a corporate data breach, a supply chain compromise. But they share one underlying cause.

When companies deployed thousands of containers in 2015, they ran into the same wall: no standardized security, no consistent policy enforcement, no single view of what was running and what it was doing. Docker gave engineers a way to package software, but there was no control plane to govern containers at scale. The result was chaos — containers running with excessive permissions, no audit trails, no way to contain a breach.

**Kubernetes solved that problem.** It became the control plane for containers — a single layer that governed how containers were deployed, what they could access, and what happened when they went wrong. Every major cloud adopted it. It became the industry standard.

**AI agents are in that same pre-Kubernetes moment today.** Agents are being deployed at scale, across multiple clouds, with no standardized policy enforcement, no way to validate that actions happen in the right sequence, and no single layer that governs what happens when one agent compromises another.

The result: the incidents above. And more to come.

Docker needed Kubernetes. AI agents need a security control plane.

---

## 4. Why Now

The window for building the AI security control plane is not 2023 and it will not be 2028 — it is precisely now. Six irreversible forces converged in the 12 months between mid-2025 and mid-2026.

| Signal | What Happened | Why It Creates the Window |
|--------|--------------|--------------------------|
| **Regulatory deadline — 5 months away** | EU AI Act high-risk enforcement begins **August 2, 2026**. Penalties reach 7% of global revenue. AI agents operating in finance, HR, healthcare, and critical infrastructure are in scope. | Enterprise sales cycles run 6–9 months. The buying decision is happening now, or it's too late. → [EU Official Journal, Art. 99](https://artificialintelligenceact.eu/article/99/) |
| **Cloud providers just made agents production-grade** | AWS Bedrock AgentCore GA: October 2025. Azure AI Foundry Agent Service GA: May 2025. Both within an 8-month window. | GA means production SLAs, compliance obligations, and real data. Enterprises are now contractually committed to these platforms — and discovering that each vendor's security ends at their cloud boundary. → [AWS AgentCore GA](https://aws.amazon.com/about-aws/whats-new/2025/10/amazon-bedrock-agentcore-available/) · [Azure Agent Service GA](https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/announcing-general-availability-of-azure-ai-foundry-agent-service/4414352) |
| **Cross-cloud agent communication became a standard** | Google launched the A2A (Agent-to-Agent) Protocol in April 2025. Donated to the Linux Foundation in June 2025. AWS, Microsoft, Google, Salesforce, Cisco all founding members. 150+ organizations. | A2A defines how agents communicate across clouds. It defines nothing about what they are *allowed to do*. The protocol created the attack surface; no vendor has built the governance layer on top of it. → [Linux Foundation, June 2025](https://www.linuxfoundation.org/press/linux-foundation-launches-the-agent2agent-protocol-project-to-enable-secure-intelligent-communication-between-ai-agents) |
| **Enterprise adoption crossed the production threshold** | Gartner (Aug 2025): AI agents will be in 40% of enterprise apps by end of 2026 — up from under 5% in 2025. That is an 8x increase in one year. IBM (July 2025): Of enterprises already breached via AI, **97% had no AI access controls in place**. | You cannot sell a security control plane to companies with nothing to secure. In 2024 they were piloting. In 2026 they are in production — with real data, real SLAs, and real incidents. → [Gartner Aug 2025](https://www.gartner.com/en/newsroom/press-releases/2025-08-26-gartner-predicts-40-percent-of-enterprise-apps-will-feature-task-specific-ai-agents-by-2026-up-from-less-than-5-percent-in-2025) · [IBM July 2025](https://newsroom.ibm.com/2025-07-30-ibm-report-13-of-organizations-reported-breaches-of-ai-models-or-applications,-97-of-which-reported-lacking-proper-ai-access-controls) |
| **MCP became the universal integration layer — with documented, unpatched vulnerabilities** | MCP launched Nov 2024. OpenAI adopted it Mar 2025. Microsoft and GitHub joined the steering committee May 2025. Now a Linux Foundation standard. CVE-2025-6514 (critical OS command injection in mcp-remote) disclosed. Anthropic acknowledges MCP security vulnerabilities — no vendor has a fix. | MCP is now the standard by which AI agents connect to tools across all major platforms. The attack surface is universal. The security layer does not exist yet. → [Anthropic MCP launch](https://www.anthropic.com/news/model-context-protocol) · [MCP attack vectors — Palo Alto Unit42](https://unit42.paloaltonetworks.com/model-context-protocol-attack-vectors/) |
| **The market validated AI security as a category — and revealed what's missing** | Check Point acquired Lakera (~$300M, Q4 2025). F5 acquired CalypsoAI ($180M, Nov 2025). Both in a 30-day window. | Two $300M+ acquisitions confirm the budget is real. Neither acquired company governed cross-cloud workflows or multi-agent blast radius. The gap that remains — cross-cloud, Kubernetes-native, orchestration-layer governance — was not filled. → [Check Point / Lakera](https://www.checkpoint.com/press-releases/check-point-acquires-lakera-to-deliver-end-to-end-ai-security-for-enterprises/) · [F5 / CalypsoAI](https://www.f5.com/company/news/press-releases/f5-to-acquire-calypsoai-to-bring-advanced-ai-guardrails-to-large-enterprises) |

Every one of these forces arrived simultaneously. None of them will wait.

---

## 5. Why This Is Hard to Solve

Three specific problems make this structurally unsolved — not missing from the roadmap of existing players, but architecturally blocked.

| Gap | Why It's Structurally Unsolved | Evidence |
|-----|-------------------------------|----------|
| **Agents run across AWS, Azure, and GCP simultaneously** | Every cloud vendor's governance solution only governs their own cloud. AWS will not govern Azure agents — that would undermine their competitive model. This is not a gap they will fill. | AWS AgentCore is AWS-only by design. Azure Entra Agent ID is Azure-only. No cross-cloud player exists. |
| **Step-by-step workflow enforcement** | AWS AgentCore uses Cedar as its dedicated agent policy engine — separate from AWS IAM, which governs resource access. Cedar is stateless by intentional design: it evaluates each action independently, with no memory of prior steps. This is the right tradeoff for speed and formal verification, but it means *sequences cannot be enforced*. It is an architectural constraint, not a missing feature. | Cedar's stateless design is confirmed in AWS AgentCore policy documentation. Sentra evaluated APIs, docs, and GitHub repos of Lakera, Portkey, AWS AgentCore, Palo Alto Prisma AIRS, Microsoft Purview, and LiteLLM (Feb–March 2026). None expose session-aware sequence validation. |
| **Cross-agent blast radius** | When one AI agent is compromised, it can instruct other agents — including those on different clouds — to take unauthorized actions. No vendor has a mechanism to contain this cross-cloud cascade. | Palo Alto Unit42, Sept 2025: published "Agent Session Smuggling" as a new attack class. No vendor response at time of writing. |

**Why Sentra?** These three gaps define the boundaries of Sentra's unique position. USPTO patent pending on core governance architecture. Attorney-conducted prior art search found zero existing patents in this exact space.

---

## 6. What Sentra Builds

> **Vision:** Sentra is the AI security control plane — the layer that governs every agent action, across every cloud, from a single point of control.

Sentra is to AI agents what Kubernetes is to containers — the same architectural role, applied one layer up the stack.

In plain terms: **Sentra sits between your AI agents and the systems they interact with.** Every action an agent tries to take passes through Sentra first. Sentra checks whether it is allowed, whether it follows the required sequence of steps, and whether this agent is who it claims to be. If yes — it goes through. If no — it is blocked, logged, and flagged.

**How it integrates:** Sentra deploys as a Kubernetes sidecar — the same pattern Istio uses for service mesh. No changes to existing agent code. No new SDK to adopt. Integration time: under one engineering sprint. It intercepts all agent tool calls at the network level, making it framework-agnostic — works with LangChain, CrewAI, AutoGen, and any other agent framework simultaneously.

```
┌──────────────────────────────────────────────────────┐
│                   YOUR AI AGENTS                     │
│  (Customer chatbots · Refund agents · Copilots · Bots)│
└──────────────────────┬───────────────────────────────┘
                       │ every action passes through here
                       ▼
┌──────────────────────────────────────────────────────┐
│               SENTRA CONTROL PLANE                   │
│                                                      │
│  Is this action     Did the required    Is this      │
│  allowed by         steps happen        agent who     │
│  policy?            first?              it claims?   │
│  ──────────────     ──────────────────  ──────────── │
│  BLOCK or ALLOW     BLOCK or ALLOW      VERIFY       │
│                                                      │
│  Full audit trail · Real-time alerts · Compliance    │
└──────────────────────┬───────────────────────────────┘
                       │ governs agents across
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
    ┌─────────┐   ┌─────────┐   ┌─────────┐
    │  AWS    │   │ Azure   │   │   GCP   │
    │ Bedrock │   │ OpenAI  │   │ Vertex  │
    └─────────┘   └─────────┘   └─────────┘
             + On-premise / air-gapped
```

**Sentra's capabilities grow with each customer segment:**

| Stage | Who | What Sentra Does for Them |
|-------|-----|--------------------------|
| **Year 1 — B2C Fraud Protection** | Food delivery, e-commerce, customer service platforms (Swiggy, Gorgias, GoPuff) | Blocks AI-generated fraud claims · Enforces verification step sequences · Stops jailbreaks and prompt injection |
| **Year 2 — Cross-Cloud Security Orchestration** | B2B SaaS companies and enterprises running agents on multiple clouds | Single governance layer across AWS + Azure + GCP · Contains a breach in one agent before it reaches others · Unified policy across all agent types |
| **Year 3 — Enterprise Compliance Governance** | Fortune 500, regulated industries, EU-facing companies | Automated compliance reports (EU AI Act, SOC2, HIPAA) · Agent identity and access management · Full audit trail for regulators |

Each tier is built on the same control plane. The customer graduates — Sentra does not need to be replaced.

---

## 7. Where Every Player Sits Today

The market for AI agent security has four positions. Three are occupied. One is empty.

```
                        SINGLE-CLOUD ONLY    │   CLOUD-AGNOSTIC
                                             │
  INLINE                AWS AgentCore        │   ← SENTRA
  ENFORCEMENT           Azure Entra Agent ID │     (empty today)
  blocks before         OpenAI Frontier      │
  execution             Microsoft Purview    │
                        Anthropic (MCP)      │
─────────────────────────────────────────────┼──────────────────
  OBSERVE /                                  │   Wiz (now Google)¹
  ALERT ONLY OR         [no players here]    │   Datadog² · Aqua²
  PER-CALL ONLY                              │   Portkey.ai
                                             │   LiteLLM · Helicone
                                             │   Snyk Evo³
```

¹ Wiz acquired by Google ($32B, EU approved Feb 2026). Posture management + alerting only — no inline enforcement. Google-owned = structural credibility gap for AWS/Azure customers.
² Datadog: cloud-agnostic fleet observability — surfaces execution graphs, anomaly alerts, and audit trails, but does not block. Right buyer (Platform Engineering), wrong capability (observe ≠ enforce). Aqua: secures the *container* an agent runs in (syscall, network, filesystem), not the *decisions* the agent makes.
³ Snyk Evo (Oct 2025, experimental): developer SDLC security sidecar. Different buyer (DevSecOps), different problem (securing AI development pipelines), no cross-cloud fleet governance. Still experimental.

**The top-right inline-enforcement quadrant is empty — and structurally hard to fill:**

Per-call and observe-only players (Portkey, LiteLLM, Snyk Evo, Datadog, Wiz, Aqua) either check individual actions or surface alerts after the fact. None of them intercept and block an agent action *before it executes* across a multi-cloud fleet. Moving to fleet-level inline enforcement requires a fundamentally different architecture — an inline sidecar in the agent's execution path — which none of them have built.

Single-cloud players (AWS, Azure, Anthropic) govern agents within their own ecosystem. Going cross-cloud would require them to help customers run agents on competitors' infrastructure — directly against their commercial interest.

Adjacent security platforms (Wiz, Datadog, Aqua) observe, alert, and surface posture insights. Their architecture is fundamentally incompatible with inline enforcement — they scan snapshots and APIs; they do not sit in the agent's execution path.

**What each player does — and why they stay in their quadrant:**

| Player | What They Do | Why They Cannot Move to Top-Right |
|--------|--------------|----------------------------------|
| **AWS AgentCore** | Best single-cloud agent security — 99% policy accuracy via formal verification | AWS-only by commercial design. Governing Azure or GCP agents would send customers' workloads to competitors. This will not change. |
| **Lakera → Check Point** | Pattern-matching for prompt injection — 80M attack patterns | Acquired April 2025. Now a CISO-facing feature inside Check Point. No fleet governance, no sequence validation, no cross-cloud. |
| **Microsoft Purview / Entra Agent ID** | Identity governance for agents on Azure | Azure-only. Identity layer only — no runtime enforcement, no cross-cloud reach, no workflow-level control. |
| **Anthropic / Claude + MCP** | Claude agents + Model Context Protocol for tool access | MCP has documented, unresolved security vulnerabilities (rug pull, confused deputy, cross-server injection). Anthropic acknowledged these; no vendor has a fix. Single-provider ecosystem. |
| **Portkey.ai** ($18M Series A) | LLM gateway — routes calls to 1,600+ providers, per-call guardrails | Stateless per call — no session state, no step-sequence enforcement. Their stated Series A roadmap reaches fleet governance in 12–18 months as managed SaaS. Regulated markets require on-prem K8s-native deployment that SaaS cannot serve. **This is a race, not a wall — Sentra must define the AgentPolicy CRD standard before Portkey ships.** |
| **Wiz (now Google Cloud)** | Cloud security posture management + AI-SPM — discovers AI agents, surfaces risk dashboards | Agentless architecture (snapshot + API scanning) is structurally incompatible with inline enforcement. Wiz alerts *after* the fact; it cannot intercept an agent action *before* it executes. Post-Google acquisition, AWS/Azure customers will rationally distrust a Google-owned governance tool over their competitor workloads — same structural problem that limits AWS AgentCore. → [Wiz AI-SPM](https://www.wiz.io/blog/wiz-ai-spm-secures-ai-agents) |
| **Datadog** | Observability platform — AI Agent Monitoring, LLM telemetry, detection | Right buyer (Platform Engineering), but observe ≠ enforce. Datadog surfaces execution graphs, anomaly alerts, and audit trails. No declarative policy engine, no stateful session enforcement, no cross-cloud blocking. Their strength makes them a natural *monitoring complement* to Sentra, not a replacement. → [Datadog AI Agent announcement, June 2025](https://www.datadoghq.com/about/latest-news/press-releases/datadog-expands-llm-observability-with-new-capabilities-to-monitor-agentic-ai-accelerate-development-and-improve-model-performance/) |
| **Aqua Security** | Kubernetes-native container workload protection — eBPF sensors, KSPM, AI workload coverage | Closest architectural cousin (K8s-native, eBPF sidecar, runtime enforcement). But Aqua secures the *container* an agent runs in — syscall behavior, network calls, file system access — not the *decisions* an agent makes. No cross-cloud unified policy plane, no stateful workflow enforcement. → [Aqua Secure AI, April 2025](https://www.globenewswire.com/news-release/2025/04/28/3069229/0/en/Aqua-Security-Unveils-Industry-First-Full-Lifecycle-Security-for-AI-Applications.html) |
| **Snyk Evo** (Oct 2025, experimental) | Agentic security orchestration — runtime sidecar for AI-native development, natural language policies | Developer/DevSecOps buyer, not Platform Engineering. Snyk Evo secures *how AI is used during development* — AI code generation, SDLC pipelines, developer tool security. It does not govern a production fleet of 50 agents running across AWS Bedrock and Azure OpenAI simultaneously. No Kubernetes CRDs, no cross-cloud fleet policy model, no formally verifiable policy language (natural language ≠ auditable compliance). Still experimental. → [Snyk Evo launch](https://www.globenewswire.com/news-release/2025/10/22/3171061/0/en/Evo-by-Snyk-The-World-s-First-Agentic-Security-Orchestration-System.html) |

**Feature-by-feature: what each player can and cannot do:**

| Capability | Sentra | AWS AgentCore | Portkey.ai | Wiz (Google) | Datadog | Snyk Evo | Lakera / Check Point | Azure Entra |
|---|---|---|---|---|---|---|---|---|
| Cross-cloud governance (AWS + Azure + GCP) | ✅ | ❌ AWS-only | ❌ routing only, not governance | ❌ posture only | ❌ observability only | ❌ no fleet model | ❌ | ❌ Azure-only |
| Inline enforcement — block before action executes | ✅ | ✅ AWS-only | ⚠️ per-call only, no fleet | ❌ alert only | ❌ alert only | ⚠️ experimental, SDLC scope | ✅ per-call only, no fleet | ❌ |
| Tool call sequence / workflow validation | ✅ | ❌ Cedar stateless | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Cross-agent blast-radius containment | ✅ | ✅ AWS-only | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Kubernetes-native CRDs + operators | ✅ | ❌ | ❌ SaaS only | ❌ | ❌ | ❌ | ❌ | ❌ |
| On-prem / air-gapped deployment | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Agent identity (non-human, task-scoped) | ✅ | ✅ AWS-only | ❌ API keys | ❌ | ❌ | ❌ | ❌ | ✅ Azure-only |
| Prompt injection / PII guardrails | ✅ | ✅ | ✅ | ✅ posture | ✅ detection | ✅ | ✅ | ❌ |
| Automated compliance reports (EU AI Act, SOC2) | ✅ (roadmap) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

**The gap Sentra fills is durable, not temporary.** Cloud vendors are structurally prevented from going cross-cloud — it contradicts their commercial model. Posture and observability players alert; they do not enforce. Developer-security players (Snyk) secure the build process, not the production fleet. Regulated markets are permanently outside the reach of managed-SaaS architectures. No acquisition closes the gap — every acquirer inherits the same single-cloud, single-call, or observe-only limitation. The one competitive race is Portkey moving upmarket: Sentra wins by defining the open standard first.

---

## 8. The Market

### How Big Is the Prize?

| Market | 2025/2026 | 2030 | CAGR | Source |
|--------|-----------|------|------|--------|
| AI Agent Market (broad TAM) | $7.84B | $52.62B | 46.3% | [MarketsandMarkets](https://www.marketsandmarkets.com/Market-Reports/ai-agents-market-15761548.html) |
| AI Governance Software (total — all governance tooling) | ~$5B | $15.8B | 30% | [Forrester, 2024](https://www.forrester.com/blogs/ai-governance-software-spend-will-see-30-cagr-from-2024-to-2030/) |
| AI Governance Platforms (dedicated — Sentra's SAM) | $492M | $1B+ | ~30% | [Gartner, Feb 2026](https://www.gartner.com/en/newsroom/press-releases/2026-02-17-gartner-global-ai-regulations-fuel-billion-dollar-market-for-ai-governance-platforms) |
| Multi-cloud AI Agent Security (Sentra's SOM) | ~$900M | ~$5.8B | 45.3% | Bottoms-up: ~7,500 enterprises × $120K avg governance spend (derived — see footnote below) |
| % of enterprises expanding AI agents in next 12 months | 96% | — | — | [Cloudera, April 2025](https://www.cloudera.com/about/news-and-blogs/press-releases/2025-04-16-96-percent-of-enterprises-are-expanding-use-of-ai-agents-according-to-latest-data-from-cloudera.html) |

> **$120K derivation (three independent inputs that triangulate to the same range):**
> (1) Gartner's $492M AI governance market ÷ ~5,000 adopting enterprises = **~$98K per company today**. (2) Comparable enterprise security platform ACVs: Datadog median ~$93K across all 29,000 customers; $100K+ enterprise cohort averages $654K (Datadog FY2024 10-K). Enterprise security platforms benchmark at $156K–$180K median ACV ([Optifai SaaS benchmark, 939 companies](https://optif.ai/learn/questions/b2b-saas-acv-benchmark/)). (3) Enterprises spending ~$755K/year on AI infrastructure (CloudZero 2025) allocating 10–15% to governance = **$75K–$113K** in governance tooling. With governance budgets growing 24–30% annually (CSA/Forrester), **$120K represents the 2027 trajectory** — conservative relative to benchmarks for comparable platform-level security tools. ([Datadog FY2024](https://investors.datadoghq.com/news-releases/news-release-details/datadog-announces-fourth-quarter-and-fiscal-year-2024-financial) · [CSA AI Security Report, Dec 2025](https://www.helpnetsecurity.com/2025/12/24/csa-ai-security-governance-report/) · [CloudZero AI Costs 2025](https://www.cloudzero.com/state-of-ai-costs/))

### Sentra's Realistic Addressable Market

Bottoms-up view — each row shows the math:

| Year | Target Segment | Qualifying Companies | Avg ACV | Addressable Pool | Deals to Close | Sentra ARR |
|------|---------------|---------------------|---------|-----------------|----------------|------------|
| **2026** | B2C platforms with AI refund/fraud agents (food delivery, e-commerce CX) | ~250 globally | $80K | ~$20M | 3–5 | **$150K–$300K** |
| **2027** | Enterprises with active agents on 2+ clouds (post-M&A, financial services, healthcare SaaS) | ~400–600 companies | $300K | ~$150M | 15–20 | **$3M–$5M** |
| **2028** | Fortune 500 + EU-regulated + large SaaS with 50+ agents under governance | ~2,000 companies | $400K | ~$500M | 30–45 | **$12M–$18M** |

### The Market Trajectory

Today, enterprise AI agents are concentrated on one or two cloud providers per company. Gartner projects that by 2030, **more than 60% of enterprises will conduct intensive AI model activity across multiple clouds** — and separately, that over 80% of enterprises will deploy industry-specific AI agents in support of critical business objectives by 2030, up from less than 10% today. ([Gartner, Sept 2025](https://www.gartner.com/en/newsroom/press-releases/2025-09-24-ai-enabling-cloud-services-are-the-future-of-cloud))

This shift is being actively standardized: the A2A (Agent-to-Agent) Protocol — donated to the Linux Foundation in June 2025 with AWS, Microsoft, Google, Salesforce, and Cisco as founding members — makes cross-cloud agent communication a vendor-neutral open standard, not a niche configuration. Multi-cloud agent deployments are not theoretical; they are being built now. ([Linux Foundation, June 2025](https://www.linuxfoundation.org/press/linux-foundation-launches-the-agent2agent-protocol-project-to-enable-secure-intelligent-communication-between-ai-agents))

Sentra's window is 12–18 months to become the governance standard before this is mainstream. The companies that define the standard at the inflection point own the category. AWS did not beat Kubernetes. Nobody will beat this standard once it's adopted.

---

## 9. The Go-To-Market Journey

The strategy is a three-stage progression where each stage funds and unlocks the next.

### Stage 1 — Year 1: Win Where the Pain Is Visible (B2C Fraud)

**Why B2C first?**

Enterprise sales cycles run 90–180 days and require security certifications (SOC2 Type II) we are building toward. B2C companies with AI fraud exposure make purchasing decisions in 6–12 weeks. Their pain is documented in public incidents (Swiggy, Gorgias customers), measurable in dollars, and urgent.

The India network gives direct, warm access to the right decision-makers at Swiggy, Zomato, and similar companies without a cold outbound campaign.

**Target customers and why:**

| Company | Specific Pain | Estimated Annual Exposure | Why Now |
|---------|--------------|--------------------------|---------|
| Swiggy / Zomato | Viral egg-fraud technique, now used at scale | $33–42M | Public incident = documented urgency |
| Gorgias | Refund agents across 30K merchants exposed | $150–300K ACV | US-anchored, fast decision cycle |
| GoPuff | Automated refund approvals, speed pressure | $150–300K ACV | High volume, measurable ROI |
| Intercom (Fin AI) | GPT-4 agent serving 25K businesses | $300–600K ACV | Premium price, highest exposure |

**The ROI story:** Blocking one $42M fraud exposure pays for multiple years of Sentra. The conversation sells itself.

---

**Parallel Track — Year 1: 3 Enterprise Design Partners**

Alongside B2C sales, we are recruiting 3 enterprise companies to co-build the platform with us. These are not paying customers yet — they contribute engineering access, real agent topologies, and production use cases. In return, they get the product shaped around their infrastructure and first-mover pricing in Year 2.

**What we look for in a design partner (all three must be true):**
- Running AI agents on 2+ clouds today — not planned, active
- Engineering-led buyer (Platform Engineering Lead or VP Engineering, not just a CISO)
- Real urgency: post-M&A, EU AI Act exposure, or a recent incident

**What we build with them (only these three, no scope creep):**
- Step-sequence validation on their actual agent workflows
- Cross-agent blast radius containment on their real agent topology
- Cross-cloud unified policy on their specific AWS + Azure estate

**Conversion:** 9-month co-build → commercial proposal → 70–80% historical close rate for co-built products. These become the first 2–3 enterprise paying customers in Year 2 — guaranteed pipeline, not cold outbound.

**Warm path:** IIT + Amazon network → former colleagues at post-M&A fintechs and healthcare SaaS companies.

---

### Stage 2 — Year 2: Pivot to Enterprise (Multi-Cloud Security Narrative)

**Why enterprise in Year 2?**

With 3–5 B2C reference cases and real performance data in hand, the narrative shifts to its natural conclusion: *"We started with food delivery fraud because it's the most visible tip of the problem. The root cause — agents taking consequential actions without governance — is the same problem enterprises face at 100x the scale."*

Two types of enterprise buyer are ready in 2027:

**Post-M&A companies:** A company that acquired its way into AWS on one side and Azure on the other now runs AI agents on two clouds with no single governance layer. This is multi-cloud by accident, and the urgency is immediate — the CISO has a gap that neither AWS nor Azure will fill.

**Regulated industries under EU AI Act:** August 2, 2026 starts enforcement. Companies facing 7% revenue penalties are not waiting for a perfect solution — they need a governance layer that generates audit-ready reports now. SOC2 Type II (in progress during Year 1) is our enterprise entry ticket.

**Target enterprise customers and why each is ready:**

| Company Profile | Specific Pain | Sentra's Entry Point |
|----------------|--------------|---------------------|
| **Post-M&A fintech** (Brex / Chime tier — recently acquired or merged, now running AWS + Azure agents across two entities) | Inherited multi-cloud AI estate with no unified governance; CISO has an unresolved security gap | Cross-cloud policy unification — one policy, two clouds, immediate risk reduction |
| **WealthTech / regional bank** running Bedrock + Azure OpenAI | SOX audit pressure + EU AI Act compliance deadline; AI agents touching financial data with no audit trail | Automated audit trail + EU AI Act compliance report generation |
| **Healthcare SaaS** with on-prem requirement (clinical documentation vendors) | HIPAA requires on-prem data residency; AWS/Azure SaaS governance tools structurally cannot deploy on-prem | On-prem Kubernetes deployment — structural moat, no SaaS competitor can serve this segment |
| **Customer service platform** with 10K+ business customers (Intercom / Zendesk tier) | One compromised agent in their fleet = breach visible to all their customers | Multi-agent blast radius containment — contain a breach before it crosses customer boundaries |

**Target ACV Year 2:** $200K–$500K. Target: 15–20 enterprise customers (including 2–3 converted design partners). Series A trigger: $3–5M ARR.

---

### Stage 3 — Year 3+: Define the Standard (CNCF Play)

**Why open-source the core?**

HashiCorp built Terraform into the standard for infrastructure-as-code by open-sourcing the specification. Nobody beats a standard once it's adopted. Sentra's `AgentPolicy` CRD — the specification for how AI agent governance policies are defined — gets submitted to CNCF (the standards body that governs Kubernetes) in Year 3.

Open-source core: `AgentPolicy` CRD specification + basic policy evaluation engine.
Proprietary: multi-cloud connectors, enterprise dashboard, compliance report templates, support SLA.

This blocks Portkey from owning the spec. It also means that AWS, Azure, and GCP — when they eventually build out governance tooling — build against Sentra's standard.

---

## 10. Five-Year Roadmap

| Year | Theme | Who We Sell To | ARR | Key Milestone That Unlocks the Next Stage |
|------|-------|---------------|-----|------------------------------------------|
| **2026** | B2C fraud wins | Swiggy, Zomato, Gorgias, GoPuff, Intercom | $150K–$300K | 3–5 paying customers; SOC2 Type II initiated; working prototype → production |
| **2027** | Enterprise wedge | Post-M&A tech, financial services, healthcare SaaS | $3M–$5M | Series A ($10–15M); 15–20 enterprise customers; SOC2 Type II certified |
| **2028** | Category leadership | Fortune 500, large SaaS, EU-regulated enterprises | $12M–$18M | CNCF sandbox submission; first vertical compliance edition; Series B ($30–50M) |
| **2029** | Global expansion | APAC, EU enterprises, mid-market via channel partners | $35M–$50M | AWS + Azure Marketplace listings; FedRAMP authorization; CNCF incubating status |
| **2030** | Category standard | Any company with 50+ AI agents | $75M–$100M | AgentPolicy CRD = industry standard. IPO or strategic acquisition at $500M–$1B+ |

---

## 11. The Ask — and Who Is Executing This

### The Ask

| | |
|--|--|
| **Raising** | $5M seed |
| **Revenue model** | Per-agent subscription — **Free** (up to 5 agents, single cloud, prompt injection + PII blocking) · **Growth** ($6–9K/yr, up to 50 agents, single cloud, sequence validation, audit logs) · **Scale** ($36–60K/yr, up to 500 agents, cross-cloud governance, blast-radius containment, compliance templates) · **Enterprise** (custom $120K–$500K/yr, unlimited agents, on-prem/air-gapped, dedicated SE, SOC2 audit support). Cross-cloud governance unlocks at Scale tier and above. |
| **Use of funds** | 45% engineering (4 backend + 2 frontend + 1 PM + 1 security specialist + 1 ML engineer) · 25% go-to-market · 10% compliance and patent prosecution · 10% cloud infrastructure and tooling · 10% operations and buffer |
| **Runway** | ~50 months (tentative) — $1.2M/year blended burn (team + infra + operations), India-based team |
| **18-month milestones** | 3–5 B2C paying customers · 3 enterprise design partners live · $300K–$500K ARR · SOC2 Type II certified · Patent prosecution underway · 10–15 qualified enterprise pipeline |
| **30-month milestone** | 15–20 enterprise customers · $3–5M ARR · Series A ready |

### The Patent

**USPTO patent pending** on Sentra's core governance architecture for AI agents. This was filed before any external market activity — before the raise, before the first customer conversation.

Attorney-conducted prior art search found **zero existing patents** in this exact space. The patent covers the multi-cloud agent orchestration and governance architecture that defines Sentra's approach.

**What this means in practice:** Direct architectural replication requires either designing around the patent (significant engineering effort) or licensing from Sentra. This creates an 18–24 month barrier during the most critical category-formation window.

### The Team

**Shashank Gupta — Founder & CEO**

IIT alumnus. At Amazon, led a 50+ person team building a new observability vertical across OpenSearch and CloudWatch — shipping profitable products used by enterprise developer teams worldwide. Built and launched semantic search and conversational AI interfaces for OpenSearch, now in production at scale.

**Why this:** After the Air Canada ruling and the Swiggy fraud incident, the missing layer became clear — not another security scanner, but a governance control plane for AI agents. Filed USPTO patent on core architecture, built working prototype to 97% attack block rate at <80ms latency. Committed full-time to Sentra from Day 1 of funding.

**Phase 1 hires (Months 1–12):**
- 4 Backend Engineers (SDE2) — control plane core, policy engine, cloud connectors (AWS/Azure/GCP), sequence validation engine
- 2 Frontend Engineers (SDE2) — real-time monitoring dashboard, compliance reports UI
- 1 Security Specialist (SDE3 — Backend + Security) — threat detection, vulnerability research, SOC2 audit, security architecture
- 1 ML Engineer — AI fraud detection models, anomaly detection for agent behavior
- 1 Product Manager — customer discovery, pilot deployments, roadmap

**Phase 2 hires (Months 13–24):**
- 2 Enterprise AEs — outbound sales for enterprise segment
- 1 Solutions Engineer — pilot deployment and design partner success

**Total team at 30 months:** 13 people including the founder.

---

*"AI without governance is just liability at scale."*

---

> **Note on company name:** Operating under the working name "Sentra." A rename is required before any external activity — sentra.io is an unrelated company (AI data security, $30M Series A). New name selection in progress.

