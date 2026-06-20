# AegionAI Guard — Strategy, GTM & Market Analysis

**Version:** 1.1
**Last Updated:** 2026-06-19
**Status:** Draft for Review
**Owner:** Shashank Gupta (Founder/CEO)
**Companion docs:** [PRD.md](../PRD.md) (the "what") · [vision.md](../vision.md) (vision & pillars) · [ARCHITECTURE.md](../lld/ARCHITECTURE.md) (the "how") · [pitch/one-pager.md](one-pager.md) (the "why")

> **The single strategy doc.** Part I is the strategy (the investor read, ~3 pages). Part II is the market & industry analysis that backs it (evidence, named targets, sources). Decisions live in Part I; Part II only supplies facts. The PRD stays product-only and references this doc for anything business/growth.

---

# PART I — STRATEGY

## 1. Market & Why Now

- **TAM (Total Addressable Market):** AI-governance spend ~$5B (2026) → ~$16B (2030); the cloud-agnostic, fleet-level slice (our segment) grows from ~$0.9B (2025) to ~$5.8B by 2030 at ~45% CAGR (Compound Annual Growth Rate); near-term beachhead (money-moving agents) ~$500M. ([Forrester](https://www.forrester.com/blogs/ai-governance-software-spend-will-see-30-cagr-from-2024-to-2030/), [Gartner](https://www.gartner.com/en/newsroom/press-releases/2026-02-17-gartner-global-ai-regulations-fuel-billion-dollar-market-for-ai-governance-platforms), [MarketsandMarkets](https://www.marketsandmarkets.com/Market-Reports/ai-agents-market-15761548.html); beachhead bottoms-up. Corroboration + full sourcing in Appendix.)
- **Adoption gap:** ~82% of enterprises use AI agents; only ~26–44% govern them; ~31% have an agent in production.
- **The pain is here:** prompt-injection attacks rose **340% year-over-year** ([OWASP 2026](https://www.helpnetsecurity.com/2026/06/11/owasp-prompt-injection-ai-security-failures/)); 2026 saw real autonomous-agent damage (Replit deleting a production database; the LiteLLM supply-chain backdoor; Claude Code hijacked for espionage — see Appendix B). **88% of organizations report AI-agent security incidents; only 22% treat agents as identity-bearing entities** ([Okta](https://www.okta.com/blog/ai/okta-ispm-ai-security/)).
- **Regulatory tailwind (multi-year, not a single cliff):** EU AI Act transparency duties apply Aug 2026; high-risk obligations (credit scoring, insurance pricing) phase in to **Dec 2027** (provisional Digital Omnibus); the up-to-7%-of-revenue penalty regime still raises the cost of an ungoverned agent. *We anchor "why now" on the incidents above, not on one date.*
- **Market signal:** two AI-security startups recently acquired ($300M, $180M); analysts call **runtime/control "the decisive battleground"** ([Dell'Oro](https://www.prnewswire.com/news-releases/ai-systems-security-market-to-rise-from-zero-to-nearly-8-b-by-2030-according-to-delloro-group-roughly-60-vendors-racing-to-secure-enterprise-ai-models-agents-and-workflows-302761017.html)).
- **Sales reality:** enterprise cycle 90–180 days, ACV $100K–$500K; to close in a quarter, start outreach the prior quarter.

## 2. Positioning & Moat

**Positioning:** the only platform that governs AI-agent **actions** across AWS, Azure, GCP, and on-prem simultaneously — real-time enforcement (not just detection), cross-agent blast-radius containment, and a deployment model regulated buyers can accept (in-VPC, air-gapped). Cloud providers structurally can't match this — each protects only agents on its own cloud.

**Why we win / defensibility:**
- **Cloud giants are structurally blocked** — they won't guard agents on a rival's cloud.
- **Standards & lock-in** — as companies write their agent rules in our format and build on top, switching cost compounds every month (the Kubernetes / Stripe path).
- **Cross-cloud threat-data moat** — only a cross-cloud platform sees multi-cloud attack patterns; every agent protected compounds the lead.
- **On-prem / air-gapped permanence** — regulated buyers structurally can't use a single-cloud or pure-SaaS competitor.
- **Patent pending** on the core approach.

**What we're building this round (gaps we're closing):** a larger adversarial attack-pattern corpus and continuous red-teaming; formal-verification depth; enterprise trust/brand and SOC 2 (System and Organization Controls); and deeper detection coverage.

## 3. Value Floor vs. Ceiling — and the in-boundary intelligence model

The three questions a skeptical buyer or investor asks: *what if they never enforce? can you still give insights when data stays in our cloud? do compliance certs change the game?* Answers below.

**Value floor — what we're worth even with enforcement OFF.** "Never enforce" is not binary. Enforcement splits in two: a **deterministic floor** (block prod-delete, refund > limit, require KYC-first — near-zero false positives) that *almost every customer turns on*, and **probabilistic layers** (ML, anomaly, trajectory) that sit in monitor for months. The realistic worst case is "enforce the floor, monitor the rest" — which is fine, because the floor is where the highest-blast-radius prevention lives. Even at *zero* enforcement we still deliver a standalone product:
- **Cross-cloud agent inventory + governance** — the only single pane across AWS/Azure/GCP/on-prem; cloud providers can't (each sees only its own).
- **Tamper-evident audit + compliance reporting** — EU AI Act / SOC 2 is a *buy-regardless-of-enforcement* trigger.
- **Risk quantification** — "your agents *attempted* N unsafe money-moves this month your current controls missed" (the confidence-to-enforce counterfactual).
- **Detection + SIEM feed.**

**Value ceiling.** Enforcement + rollback + cross-agent containment is what makes us category-defining and premium-priced; pure-monitor competes closer to the detect-and-warn point tools (thinner moat). So: **monitor is the floor and the landing motion; enforcement is the ceiling and the premium.** Don't let the floor become the ceiling — the [confidence-to-enforce engine](../PRD.md) is the machine that walks customers up that path.

**In-boundary intelligence model.** Keeping data in the customer's cloud (Dedicated / Self-Managed) does **not** cost per-customer insight — the data plane runs in their cloud and produces *their* dashboards/audit; only metadata leaves. What it costs is the naive raw-content pooling a pure-SaaS rival uses to train a global model. We recover that the proven way: **telemetry up, intelligence down** — de-identified signals/signatures flow to the control plane, and signatures + model updates push back to every boundary ("saw this injection at one bank → all customers protected in minutes," no raw content moving; the CrowdStrike pattern). Plus **opt-in/Serverless tiers** feed the global model and the regulated tier receives the resulting intelligence. The flywheel runs on **metadata + signatures, not content** — leaner than a hoover-everything competitor, but the boundary model is a *selling point* to exactly our buyer, not only a cost.

**Compliance certs — unlock, not accelerant.** SOC 2 Type II + HIPAA clear *procurement* (make us eligible), they don't close deals on their own. The real lever: **certs + redaction + DPA open the Serverless edition to more buyers (incl. some bank workloads)** — the lower-friction, higher-margin path — instead of forcing the heavyweight in-VPC install. Caveat: a cert does **not** override a data-residency mandate (residency-bound workloads still need Dedicated/air-gapped). Bonus: our own certs are a credibility proof point for the compliance value we sell *to* customers.

## 4. Go-to-Market — the ladder

**Land where it's easy today; climb to the regulated summit.** Our deployment editions *are* the ladder: Serverless (today) → Dedicated/in-VPC (P1) → Self-Managed/air-gapped (P2), gated by SOC 2 and verified agent identity.

- **Stage 0 — land now (Serverless): software / DevOps / infrastructure & automation agents.** The easiest entry *and* the best fit for what ships today: their actions — delete prod, deploy code, run infrastructure — map directly onto our deterministic policy engine; the buyer is platform engineering (our champion); cycles are weeks; SaaS is acceptable. (Plus **opportunistic e-commerce refund-fraud** for fast cash.) *Goal: 3–5 design partners → paying, reference logos, start SOC 2 Type II.*
- **Stage 1 — the headline beachhead (Serverless → Dedicated): fintech / payments.** Six-figure ACV, money-moving actions, the cleanest ROI and the regulatory audit story we lead the pitch with. Prioritize multi-cloud early adopters.
- **Stage 2 — regulated, higher ACV (Dedicated; SOC 2 Type II + verified identity + compliance reports):** insurance, regional banks / WealthTech, legal & corporate compliance.
- **Stage 3 — the summit & structural moats (Self-Managed / air-gapped):** top-tier banks, healthcare systems, government / defense.

**Why this order:** banking has the biggest ACV but is *product-gated* — it needs in-VPC deployment + SOC 2 Type II + verified identity, all on the roadmap. So we land where today's product already wins (infra/automation), earn the credentials, then climb. The **financial-action story stays the headline narrative** (cleanest ROI + regulatory pull); infra/automation is how we *land first*. Full per-industry analysis, named targets, and scorecard: **Appendix A & C.**

**Buyer map:**
- **Economic buyer:** CISO / Head of AI Governance (approves; rarely champions).
- **Champion:** Platform / DevOps Engineering Lead (Kubernetes-native is familiar; drives bottom-up adoption).
- **The unlock:** the emerging **"Head of AI Platform / VP AI Engineering"** who owns both deployment and security — lead bottom-up via platform engineering, close top-down with the CISO.
- **Beachhead buyer:** platform/SRE lead (Stage 0); Fraud/Risk lead at financial-action companies (Stage 1).

## 5. Competitive Landscape

- **Cloud giants (AWS AgentCore, Azure, Google):** structurally won't govern agents on a rival's cloud; AgentCore is AWS-only by architecture. The cross-cloud position is ours.
- **AI gateways (Portkey $18M Series A, LiteLLM):** govern LLM *calls*, not agent *actions*. Portkey's stated goal is agent governance (~12–18 months out) but **SaaS-only, not Kubernetes-native / on-prem** — that's our differentiator.
- **AI-security point tools (Lakera→Check Point, CalypsoAI→F5, CrowdStrike, Palo Alto):** detect & warn, sell to the CISO, no enforcement-at-the-action depth.
- **Identity (Okta Auth0 for AI Agents, CyberArk, Microsoft Entra Agent ID):** secure *who the agent is* — **complementary** to *what the action may do*. Partners, not competitors (and validation of our verified-agent-identity requirement).
- **Agent-platform vendors (Decagon, Sierra, UiPath, Harvey):** potential customers *and* potential self-builders; selling to the **enterprises that deploy them** is the cleaner motion. Incumbents bundle governance only for their own platform — the same structural gap as the cloud giants.

(Full competitive detail: Appendix D.)

## 6. 5-Year Roadmap

Aligns to the PRD's P0/P1/P2 phasing and the GTM ladder. Detailed year-by-year targets and actions: [pitch/customer/5-year-roadmap.md](customer/5-year-roadmap.md).

| Year | Theme | ARR | Customers | Avg ACV | Key milestone |
|---|---|---|---|---|---|
| 2026 (Y1) | Revenue validation (Stage 0 → 1) | $0.5–1M | 3–5 | ~$150K | First paying customers (infra/automation + fintech); SOC 2 initiated; patent prosecution |
| 2027 (Y2) | Enterprise launch | $3–5M | 15–20 | $200–250K | Multi-cloud GA, in-VPC (Dedicated), SOC 2 Type II, Series A |
| 2028 (Y3) | Category leadership | $12–18M | 50–75 | $200–300K | CRDs / CNCF, automated red-teaming, vertical editions, Series B |
| 2029 (Y4) | Market expansion | $35–50M | 150–200 | $200–300K | Marketplaces, channel, FedRAMP, global compliance |
| 2030 (Y5) | Category standard | $75–100M | 300–400 | $200–300K | Agent-policy standard; exit optionality |

**Product↔phase mapping:** Y1 ≈ PRD **P0** (enforce single-cloud, prove cross-cloud, multi-tenant); Y2 ≈ PRD **P1** (enterprise hardening — Dedicated, local cached enforcement, redaction, distilled model, sidecar, verified identity); Y3+ ≈ PRD **P2** (Self-Managed / air-gapped, compliance reports, blast-radius containment, CRDs).

## 7. Business KPIs & The Ask

*(Product/efficacy metrics live in [PRD.md](../PRD.md) §3.2. These are the business/growth KPIs.)*

| KPI | What it tracks |
|---|---|
| ARR | Recurring revenue (trajectory above) |
| Customers / design partners | Logos signed; marquee FS name |
| Average ACV | Deal size by segment ($100K–$500K band) |
| Net revenue retention (NRR) | Expansion within accounts |
| Pipeline / win rate | GTM efficiency |
| SOC 2 status | Type II milestone (in progress) |
| Runway | Months remaining vs raise plan |

**The Ask:** raising **$5M for ~30 months runway** → ship the third cloud, harden for enterprise (Dedicated + self-managed, on-device detection, resiliency, verified identity), convert 3 design partners into 3–5 paying enterprises incl. one marquee financial-services name, reach **~$500K–$1M ARR**, SOC 2 Type II underway. ($5M ≈ $165K/month for a ~8-person team; full breakdown in Appendix C.) This is the seed; the milestones unlock a credible Series A.

## 8. Open Questions

1. **Open-source core?** — OSS agent-policy spec + basic engine (HashiCorp / Snyk playbook) vs closed.
2. **Pricing — price points & tiers (the rework).** The *basis* is decided: **per governed agent** (tiered), never per-action; infra bundled for Serverless, customer-borne for Dedicated/Self-Managed (see ARCHITECTURE §2.10). Open: the exact prices, volume tiers, and Dedicated managed-service premium — see `pricing-model.md`.
3. **Security co-founder / advisor** — named security leadership for enterprise/bank procurement credibility.

*(Resolved: beachhead = financial-action headline with infra/automation as the Stage-0 land, B2C-fraud opportunistic; product name = AegionAI Guard.)*

---

# PART II — APPENDIX: Market & Industry Analysis (June 2026)

*Evidence behind Part I. Our value proposition is real-time enforcement of consequential agent **actions**, so an industry scores well when agents are adopted, take **irreversible/expensive** actions, face regulatory/operational pressure, the buyer is reachable, and it fits what we ship today (deterministic policy) vs. roadmap (in-VPC, identity, compliance reports).*

## Appendix A — Industry deep dives (with named targets)

### A.1 Software / DevOps / Infrastructure & Automation  ★ easiest + best product fit (Stage 0 lead)
- **Adoption:** highest of any segment. Coding agents: **Cursor ~$1.2B ARR**, **Cognition/Devin $1B raise @ $26B valuation**, Replit Agent; enterprise adopters incl. **Goldman Sachs, Mercedes-Benz** ([MarkTechPost](https://www.marktechpost.com/2026/06/10/ai-coding-agents-development-platforms-2026/), [TechTimes](https://www.techtimes.com/articles/317354/20260529/ai-coding-agents-cognitions-26b-raise-bets-agent-first-architecture-beats-ide-tools.htm)). RPA/automation: **UiPath, Automation Anywhere, ServiceNow, Salesforce Agentforce, Microsoft, Moveworks** ([Kore.ai](https://www.kore.ai/blog/best-ai-workflow-automation-tools)).
- **Consequential actions:** the most irreversible/highest-blast-radius — `terraform destroy`, `kubectl delete`, drop database, push to prod, modify IAM, run shell. (Every incident in Appendix B is this category.)
- **Regulatory:** low–medium (SOC 2, SOX IT general controls). Pressure is **operational risk**, not a compliance deadline.
- **Ease of entry:** **easiest** — buyer is platform engineering / DevOps / SRE (our champion); decides in weeks; SaaS acceptable.
- **Fit:** **excellent** — maps directly onto the deterministic policy engine we ship today + rollback + quarantine; minimal roadmap dependency.
- **Targets:** enterprises/scale-ups running Devin/Cursor/Claude Code/Replit in CI/CD; UiPath/Automation Anywhere/ServiceNow deployers. Agent-builders (Cognition, Anysphere, Replit, UiPath) are potential **partners**; the cleaner first customers are the enterprises operating these agents internally.

### A.2 Fintech / Payments (non-bank)  ★ headline narrative (Stage 1)
- **Adoption:** very high — **Stripe Agent SDK** (virtual cards + spending guardrails; expects **700+ agentic startups**), **Brex Financial Ops Agents**, **Ramp** finance agents — the "bank the bots" race ([Fintech Blueprint](https://lex.substack.com/p/ai-ramp-and-stripe-race-to-bank-the), [AI CERTs](https://www.aicerts.ai/news/financial-ops-agents-brexs-engine-for-agentic-commerce/)).
- **Consequential actions:** money movement — refunds, transfers, payouts, card issuance. Instant cash loss + legal exposure (cleanest ROI).
- **Regulatory:** high (KYC/AML, PCI-DSS, SOX) — they need our audit trail.
- **Ease of entry:** medium — faster than banks; SOC 2 wanted, not always blocking for design partners.
- **Targets:** **Brex, Ramp, Mercury**, neobanks, payment service providers, lending platforms, agentic-commerce startups on Stripe's Agent SDK.

### A.3 Customer Support / E-commerce  (Stage 0 opportunistic)
- **Adoption:** high, already executing money actions — **Decagon ($4.5B valuation)** and **Sierra ($15.8B valuation, $950M Series C)** run autonomous refunds, subscription changes, account updates ([Quiq](https://quiq.com/blog/decagon-vs-intercom/)).
- **Consequential actions:** medium — refunds/credits, account changes (refund-fraud exposure is the concrete ROI).
- **Regulatory:** low. **Ease:** easy (fast, SaaS) — but lower ACV and dilutes the enterprise-security identity.
- **Targets:** e-commerce/marketplaces deploying Decagon/Sierra; food-delivery & marketplace platforms with refund-fraud pain.

### A.4 Insurance  (Stage 2 fast-follow)
- **Adoption:** maturing on actions — **Lemonade's "AI Jim"** processes ~40% of claims instantly, 96% of first-notice-of-loss without humans, 55% fully automated ([Trixly](https://www.trixlyai.com/blog/our-blog-1/agentic-ai-insurance-lemonade-case-study-28)); McKinsey calls agentic AI a **$1.2–2T opportunity for insurers by 2030** ([Hexaware](https://hexaware.com/blogs/agentic-ai-in-insurance-transforming-the-industry-with-enterprise-ai/)). Broad adoption still early (~7% scaled).
- **Consequential actions:** high — claims payouts, underwriting/pricing, eligibility.
- **Regulatory:** high — EU AI Act lists insurance pricing as high-risk; state regulators.
- **Targets:** **Lemonade, Root**, digital-first insurtechs; claims-automation arms of traditional carriers.

### A.5 Banking / Capital Markets  ★ biggest ACV, hardest entry (Stage 2/3 summit)
- **Adoption:** high in production (~47%); HSBC/Citi/UBS/DBS/ING report 20–40% cost cuts ([Kore.ai](https://www.kore.ai/blog/ai-agents-in-finance-banking-12-proven-use-cases-2026)).
- **Consequential actions:** extreme — transfers, lending, treasury, trading.
- **Regulatory:** heaviest — model-risk governance (US SR 11-7), SOX, KYC/AML, EU AI Act credit scoring, vendor-risk reviews, pen-test evidence.
- **Ease of entry:** hardest — 120–180+ day cycles and they require **in-boundary deployment + SOC 2 Type II + verified identity**, all roadmap → **product-gated**, not just sales-gated.
- **Targets (later):** regional banks and WealthTech first, then top-tier (Goldman already runs Cursor — a platform-eng-side wedge).

### A.6 Healthcare / Clinical  (Stage 3 later)
- **Adoption:** highest *usage* (~68%) but lowest *production* (~18%). **Abridge** has **150+ health-system contracts**, moving into billing codes, lab orders, payer–provider mediation ([MedCity News](https://medcitynews.com/2026/06/abridge-clinical-ai/)); **Penn Medicine** deploying clinical agents; **Hippocratic AI**, Suki, Notable ([Keragon](https://www.keragon.com/blog/ai-agent-companies)).
- **Consequential actions:** rising (orders, billing, labs) but strong human-in-the-loop caps autonomy.
- **Regulatory:** very high (HIPAA; emergency triage high-risk). **Ease:** high friction. The **on-prem/air-gapped moat** is the real play.

### A.7 Legal / Professional Services  (Stage 2/3 adjacent)
- **Adoption:** fast & autonomous — **Harvey (~$11B valuation)** runs 25,000 agents, 400,000 daily queries, autonomous end-to-end drafting; **Legora ($5.5B)**, Relativity aiR, DISCO Cecilia ([PlatinumIDS](https://blog.platinumids.com/blog/legal-ai-billion-dollar-arms-race-2026)).
- **Consequential actions:** med–high — drafting/filing legal documents (malpractice, privilege risk).
- **Fit:** good — sequence/approval gates, audit, privileged-data exfil prevention.
- **Targets:** Harvey/Legora ecosystems; corporate legal & compliance.

### A.8 Government / Defense  (Stage 3 long-term moat)
- **Adoption:** growing — **Palantir $1B government contract (2026)**, Maven, **FedStart** path to FedRAMP High / DoD Impact Level 5; federal agent networks autonomously coordinate mission actions ([Military.com](https://www.military.com/feature/2026/03/22/pentagon-expands-palantirs-role-ai-contract.html)).
- **Consequential actions:** extreme (mission systems). **Regulatory:** maximum (FedRAMP, IL5, ITAR, CMMC, air-gap). **Ease:** very hard — fully gated on our Self-Managed edition.
- **Targets (long-term):** Palantir FedStart ecosystem; defense primes; federal agencies.

## Appendix B — Incident evidence (the "why now")

Prompt-injection up **340% YoY**, fastest-growing attack category ([OWASP](https://www.helpnetsecurity.com/2026/06/11/owasp-prompt-injection-ai-security-failures/)). 2026 incidents, mostly infra/coding/automation agents:
- **Replit (2025):** coding agent deleted a production database despite "change nothing," fabricated records, lied that rollback was impossible.
- **LiteLLM supply chain (Mar 2026):** autonomous bot pushed backdoored LiteLLM to PyPI — ~47,000 downloads in ~3 hours ([beam.ai](https://beam.ai/agentic-insights/ai-agent-security-breaches-2026-lessons)).
- **Microsoft Semantic Kernel RCE (2026):** one prompt → host-level remote code execution ([Microsoft](https://www.microsoft.com/en-us/security/blog/2026/05/07/prompts-become-shells-rce-vulnerabilities-ai-agent-frameworks/)).
- **Cursor (CVE-2026-22708) & ModelScope MS-Agent (CVE-2026-2256):** allowlist/denylist bypasses turned approved dev commands into payload carriers.
- **Claude Code espionage (GTG-1002, Sep 2025):** state-sponsored group hijacked coding agents to attack ~30 defense/energy/tech targets, AI handling 80–90% of operations.

## Appendix C — Cross-industry matrix & funding

| Industry | Adoption | Consequential actions | Regulatory | Ease of entry | ACV | Fit (today) | Stage |
|---|---|---|---|---|---|---|---|
| **Software / DevOps / Automation** | Very high | **Extreme** | Low–med | **Easiest** | Moderate | **Excellent** | **0 — lead** |
| **Fintech / Payments** | Very high | High ($) | High | Medium | Six-figure | Excellent | **1 — expand** |
| **Customer Support / E-commerce** | High | Medium | Low | Easy | Lower | Good | 0 — opportunistic |
| **Insurance** | Maturing | High | High | Med–high | $200–400K | Strong | **2 — fast-follow** |
| **Banking / Capital Markets** | High | Extreme | **Very high** | **Hardest** | $300K–1.5M | Excellent (gated) | **2/3 — summit** |
| **Healthcare / Clinical** | Usage high, prod low | Rising | Very high | High friction | $200–400K | Moderate | 3 — later |
| **Legal / Prof. services** | Fast | Med–high | Medium | Medium | Mod–high | Good | 2/3 — adjacent |
| **Government / Defense** | Growing | Extreme | **Max** | Very hard | Very high | Strong (gated) | 3 — long-term |

**Funding detail — $5M over ~30 months** (~$165K/month average burn):
- **Team (~$2.0–2.5M):** ~8-person core — founder, security/red-team lead, ~4–5 engineers (backend / ML / frontend for the cross-cloud, in-VPC, and sidecar build), product, and an enterprise GTM hire.
- **Infrastructure (~$0.8–1.2M):** 3-cloud + **GPU** for self-hosted models and the in-VPC / air-gapped editions.
- **Compliance (~$0.2M):** SOC 2 Type II + HIPAA + pen tests.
- **Go-to-market (~$0.5M):** enterprise sales, conferences, design-partner support.
- Plus **patent prosecution, tooling/ops, and buffer.**

*The earlier $3M plan was thin once GPU infrastructure for self-hosted models, dual certifications, and enterprise GTM are funded; $5M buys ~30 months with proper cushion to convert design partners and reach SOC 2 + HIPAA. This is the seed round — the milestones unlock a credible Series A.*

## Appendix D — Buyer & competitive notes

- **Buyer mismatch is the gap:** security buyers (CISO) and platform buyers (engineering) rarely co-purchase. The unlock is the emerging **Head of AI Platform / VP AI Engineering**. Lead bottom-up via platform engineering; close top-down with the CISO.
- **Identity vendors** (Okta Auth0 for AI Agents, GA Apr 30 2026; CyberArk; Microsoft Entra Agent ID) secure *who the agent is* — complementary partners, and validation of our verified-agent-identity requirement.
- **Agent-platform vendors** (Decagon, Sierra, UiPath, Harvey) are customers *and* potential self-builders (UiPath already markets governance) — sell to the enterprises that deploy them.
- **Portkey** ($18M Series A) will build agent governance in ~12–18 months — SaaS-only, not Kubernetes-native / on-prem; our enforcement depth + cross-cloud + in-boundary deployment is the wedge.
- **Incumbents** (UiPath, ServiceNow, Microsoft, cloud providers) bundle governance only for their own platform — none govern a rival's agents cross-platform. That structural gap is our opening.

## Sources

Market: [Forrester](https://www.forrester.com/blogs/ai-governance-software-spend-will-see-30-cagr-from-2024-to-2030/) · [Gartner](https://www.gartner.com/en/newsroom/press-releases/2026-02-17-gartner-global-ai-regulations-fuel-billion-dollar-market-for-ai-governance-platforms) · [MarketsandMarkets](https://www.marketsandmarkets.com/Market-Reports/ai-agents-market-15761548.html) · [Dell'Oro](https://www.prnewswire.com/news-releases/ai-systems-security-market-to-rise-from-zero-to-nearly-8-b-by-2030-according-to-delloro-group-roughly-60-vendors-racing-to-secure-enterprise-ai-models-agents-and-workflows-302761017.html) · [Grand View](https://www.grandviewresearch.com/industry-analysis/enterprise-agentic-ai-market-report) · [warmly.ai](https://www.warmly.ai/p/blog/ai-agents-statistics)
Incidents/identity: [OWASP via Help Net Security](https://www.helpnetsecurity.com/2026/06/11/owasp-prompt-injection-ai-security-failures/) · [beam.ai breaches](https://beam.ai/agentic-insights/ai-agent-security-breaches-2026-lessons) · [Microsoft Security (RCE)](https://www.microsoft.com/en-us/security/blog/2026/05/07/prompts-become-shells-rce-vulnerabilities-ai-agent-frameworks/) · [Okta](https://www.okta.com/blog/ai/okta-ispm-ai-security/)
Industry: [coding agents — MarkTechPost](https://www.marktechpost.com/2026/06/10/ai-coding-agents-development-platforms-2026/) · [Cognition $26B — TechTimes](https://www.techtimes.com/articles/317354/20260529/ai-coding-agents-cognitions-26b-raise-bets-agent-first-architecture-beats-ide-tools.htm) · [RPA — Kore.ai](https://www.kore.ai/blog/best-ai-workflow-automation-tools) · [Stripe/Ramp/Brex — Fintech Blueprint](https://lex.substack.com/p/ai-ramp-and-stripe-race-to-bank-the) · [Decagon/Sierra — Quiq](https://quiq.com/blog/decagon-vs-intercom/) · [Lemonade — Trixly](https://www.trixlyai.com/blog/our-blog-1/agentic-ai-insurance-lemonade-case-study-28) · [insurance $1.2–2T — Hexaware](https://hexaware.com/blogs/agentic-ai-in-insurance-transforming-the-industry-with-enterprise-ai/) · [banking — Kore.ai](https://www.kore.ai/blog/ai-agents-in-finance-banking-12-proven-use-cases-2026) · [Abridge — MedCity News](https://medcitynews.com/2026/06/abridge-clinical-ai/) · [Harvey/Legora — PlatinumIDS](https://blog.platinumids.com/blog/legal-ai-billion-dollar-arms-race-2026) · [Palantir — Military.com](https://www.military.com/feature/2026/03/22/pentagon-expands-palantirs-role-ai-contract.html) · [EU AI Act — Gibson Dunn](https://www.gibsondunn.com/eu-ai-act-omnibus-agreement-postponed-high-risk-deadlines-and-other-key-changes/)

---
*Single source of truth for strategy. Keep ARR/phase rows in sync with the PRD's release phasing.*
