# AegionAI Guard — Strategy, GTM & Market Analysis

> **CONFIDENTIAL — Do not distribute.** Shared in confidence for investor evaluation. Please do not forward, copy, or share outside your firm without the founder's consent. © 2026 AegionAI. All rights reserved.

> **The single strategy doc.** Part I is the strategy (the investor read, ~3 pages). Part II is the market & industry analysis that backs it (evidence, named targets, sources). Decisions live in Part I; Part II only supplies the facts.

---

# PART I — STRATEGY

## 1. Market & Why Now

- **TAM (Total Addressable Market):** estimates diverge by definition — narrow **AI-governance-platform** spend ~$492M (2026) → >$1B (2030) ([Gartner](https://www.gartner.com/en/newsroom/press-releases/2026-02-17-gartner-global-ai-regulations-fuel-billion-dollar-market-for-ai-governance-platforms)); broader **agentic-AI governance & policy management** $7.3B (2025) → $38.9B (2030), ~40% CAGR ([Mordor](https://www.mordorintelligence.com/industry-reports/agentic-artificial-intelligence-governance-and-policy-management-market); single-source — disclose). Whichever definition, the market compounds 35–40%/yr as agents hit production. Our **near-term beachhead (money-moving agents) is a bottoms-up ~$500M slice** — we don't underwrite the headline TAM. (Full sourcing + the divergence note in Appendix.)
- **Adoption gap:** **~96%** of enterprises use AI agents ([OutSystems 2026, n=1,900](https://www.outsystems.com/news/enterprise-ai-agent-report-2026/)), but only **~21%** have a *mature* governance model for them ([Deloitte 2026, n=3,235](https://www.deloitte.com/us/en/insights/topics/emerging-technologies/ai-agents-scaling-faster.html)) — adoption is racing ahead of control.
- **The pain is here:** prompt-injection *reports* on HackerOne's platform rose **540% YoY** (2024→2025; report volume, not industry incident rate — [HackerOne 9th Annual Report](https://www.hackerone.com/press-release/hackerone-report-finds-210-spike-ai-vulnerability-reports-amid-rise-ai-autonomy)); 2026 saw real autonomous-agent damage (Replit deleting a production database; the LiteLLM supply-chain backdoor; Claude Code hijacked for espionage — see Appendix B). **65% of organizations report an AI-agent security incident in the past 12 months** ([Cloud Security Alliance 2026, n=418](https://cloudsecurityalliance.org/artifacts/autonomous-but-not-controlled-ai-agent-incidents-now-common-in-enterprises)); a separate survey puts it at **54% experienced-or-suspected (~35% confirmed)** ([Gravitee, N=750](https://www.gravitee.io/state-of-ai-agent-security)); only **22% treat agents as identity-bearing entities** ([Okta](https://www.okta.com/blog/ai/okta-ispm-ai-security/)).
- **Regulatory tailwind (multi-year, not a single cliff):** EU AI Act GPAI/transparency duties are **in force since Aug 2025**; the **Digital Omnibus** moves high-risk Annex III obligations (credit scoring, insurance pricing) to **Dec 2, 2027** — provisionally agreed May 7, 2026 and **endorsed by the European Parliament June 16, 2026** (423–57–174; Council adoption expected late June). It's now near-final rather than speculative, but the timeline is *later*, so we **anchor "why now" on the incidents above, not on one regulatory date** — the up-to-7%-of-revenue penalty regime still raises the cost of an ungoverned agent.
- **Market signal:** two AI-security startups acquired in 2025 (**$300M** Check Point/Lakera, **$180M** F5/CalypsoAI); analysts have *named the category* — **Gartner "Guardian Agents" (Feb 2026 Market Guide), Forrester "AEGIS" (2025)** — and ~60 vendors are racing in ([Dell'Oro](https://www.prnewswire.com/news-releases/ai-systems-security-market-to-rise-from-zero-to-nearly-8-b-by-2030-according-to-delloro-group-roughly-60-vendors-racing-to-secure-enterprise-ai-models-agents-and-workflows-302761017.html)).
- **Sales reality:** enterprise cycle 90–180 days, ACV $100K–$500K; to close in a quarter, start outreach the prior quarter.

## 2. Positioning & Moat

**Positioning:** the **neutral control plane** that governs AI-agent **actions** across AWS, Azure, GCP, and on-prem from one place — *what* the action does (params, identity, session state), not just whether a prompt looks bad. Point tools now block inline too, and **neutral cross-vendor *visibility and detection* is no longer open ground**: Zenity (multi-platform, Gartner's "company to beat") and CrowdStrike Falcon AIDR (cross-platform detect-and-respond) already span vendors. That validates the category; it also means **"we're the only neutral one" is no longer the moat.** What remains genuinely unowned — and what we win on — is a tight triad: **(1) stateful action-level enforcement** (parameters + sequence + identity + trust decay/quarantine, not stateless prompt/content scoring); **(2) bounded rollback + cross-agent cascade containment** (no one ships this); **(3) in-VPC / air-gapped action-gating for code-built agents** (the others lean SaaS/posture). No single cloud can be neutral across its rivals — that's still the Wiz ($32B) / Datadog opening — but neutrality is the *table stakes* now, and the triad is the *edge*.

**Why we win / defensibility — two moats, by segment** *(the intercept itself is old tech — WAFs/meshes have done it for a decade; the moat is the position and the data, not the mechanism).* They are deliberately **two**, because each is strongest exactly where the other is weakest — together they cover the whole ladder:

**Moat 1 — the data flywheel (compounds with scale; strongest in Serverless/mid-market).** Every customer we govern makes the next one safer — *only* for a neutral player who sees across vendors.
- **Cross-vendor threat-data flywheel** — seeing attack patterns *across* AWS/Azure/GCP/on-prem; intelligence pushes back to every customer ("saw this injection at one bank → all protected in minutes"; the CrowdStrike pattern — and note CrowdStrike runs exactly this loop, so our flywheel is a *parity* play on intel and a *win* on the triad above, not a unique moat by itself). The flywheel compounds our triad; it isn't a substitute for it.
- **Two tracks, two fuels:** a **content track** (injection/jailbreak/DLP classifiers) fed by **Serverless *redacted* content** (PII/secrets masked, attack-relevant text retained — *an assumption we measure via recall-delta, not assert*, LLD 25 §1.4); and a **behavioral track** (egress reputation, volume/rate anomaly, trust scoring, FP/FN outcome labels) fed by **de-identified metadata from the entire fleet, every edition**. Metadata improves the behavioral track; it does **not** improve the content track — the two are distinct.
- **Honest scope:** content fuel comes from Serverless; **regulated/in-VPC editions leak no content by design** (only metadata + **opt-in, customer-approved derived signatures** — Sigma rules / patterns / centroids, never raw or redacted bodies). So the regulated tier **contributes signatures and metadata and *receives* the improved global model**, but does not feed the content track. The flywheel's content volume = Serverless + opt-in federation. *(Open question we're measuring: does enough of the detection lift come from metadata/signatures — not just content — for the regulated tier to meaningfully feed the flywheel? It determines how strongly Moat 1 reaches our highest-value segment.)*

**Moat 2 — structural defensibility (needs no data; strongest in regulated/in-VPC).** This is why a regulated customer — whose data never feeds Moat 1 — still can't leave and a competitor still can't displace us.
- **Neutrality** — cloud giants govern only their own cloud's agents and won't guard a rival's; a *neutral* cross-vendor plane is not theirs to hold by design (the Wiz/Datadog opening).
- **Switching cost** — agent policies written in our format, us as the cross-vendor audit system-of-record, and — for in-VPC — production egress re-routed through our chokepoint and our audit feed wired into their SIEM. The onboarding friction (LLD 25 §7.4) becomes lock-in once past it; it compounds monthly (the Kubernetes / Stripe path).
- **Compliance certification** — once we're the *audited* enforcement layer in their SOC 2 / HIPAA / EU-AI-Act posture, displacement requires re-certification with a new vendor; regulated buyers exit as slowly as they enter.
- **On-prem / air-gapped permanence** — regulated buyers structurally can't use a single-cloud or pure-SaaS competitor.
- **The three-leg combination is the moat — not any single leg.** Named players each hold *one or two* legs of the §2 triad, never all three: Zenity (multi-platform, but SaaS/posture, no deterministic sequence/rollback), CrowdStrike Falcon AIDR (cross-platform, but prompt-layer detect-and-respond, Falcon-sensor-bound), F5/CalypsoAI (tool-call block + air-gapped, but not stateful/cross-vendor), Operant/HiddenLayer/Noma (US runtime defense, not the trifecta). The defensible claim is **the combination** — *stateful action-level enforcement **+** neutral cross-vendor **+** in-VPC/air-gapped* — held together, not "we're the only one who does X."
- **Deployment-derived US-residency posture (a procurement de-risker, not a flag-wave).** US-HQ on its own is **not** a moat (the category is Israeli-*founded* and bought freely; FedRAMP doesn't require US-HQ). But our **in-VPC / air-gapped architecture means data never leaves the customer boundary and can be US-person-operated** — which is exactly the **data-residency + US-person-access posture DoD IL4/IL5 and ITAR buyers require**, and which a SaaS-centric competitor (Zenity, CrowdStrike-Falcon-SaaS) can't match without re-architecting. Use this as a regulated/federal *procurement* de-risker mentioned second — the deployment model delivers it, not the HQ pin.

- **Patent pending** — priority/defensibility at the margin, *not* a moat in either column.

> **The one-line GTM read:** *Serverless is where the data moat compounds; regulated is where the structural moat (switching cost + compliance + neutrality) holds.* The same customer is rarely both your biggest moat-feeder and your biggest check — and that's by design, not a gap. Land regulated for revenue + credibility; feed the content model from Serverless; both receive the result.

**What we're building this round (gaps we're closing):** a larger adversarial attack-pattern corpus and continuous red-teaming; formal-verification depth; enterprise trust/brand and SOC 2 (System and Organization Controls); and deeper detection coverage.

## 3. Value Floor vs. Ceiling — and the in-boundary intelligence model

The three questions a skeptical buyer or investor asks: *what if they never enforce? can you still give insights when data stays in our cloud? do compliance certs change the game?* Answers below.

**Value floor — what we're worth even with enforcement OFF.** "Never enforce" is not binary. Enforcement splits in two: a **deterministic floor** (block prod-delete, refund > limit, require KYC-first — near-zero false positives) that *almost every customer turns on*, and **probabilistic layers** (ML, anomaly, trajectory) that sit in monitor for months. The realistic worst case is "enforce the floor, monitor the rest" — which is fine, because the floor is where the highest-blast-radius prevention lives. Even at *zero* enforcement we still deliver a standalone product:
- **Cross-cloud agent inventory + governance** — the only single pane across AWS/Azure/GCP/on-prem; cloud providers can't (each sees only its own).
- **Tamper-evident audit + compliance reporting** — EU AI Act / SOC 2 is a *buy-regardless-of-enforcement* trigger.
- **Risk quantification** — "your agents *attempted* N unsafe money-moves this month your current controls missed" (the confidence-to-enforce counterfactual).
- **Detection + SIEM feed.**

**Value ceiling.** Action-level governance + bounded rollback + cross-agent containment — *stateful, across every vendor* — is what makes us category-defining and premium-priced; pure-monitor competes closer to the point tools (thinner moat). Note: inline blocking is no longer the differentiator (the point tools block too now) — *governing the action with session state, and neutrality across vendors,* is. So: **monitor is the floor and the landing motion; action governance is the ceiling and the premium.** Don't let the floor become the ceiling — the confidence-to-enforce engine is the machine that walks customers up that path.

**In-boundary intelligence model (how the two moats split the data).** Keeping data in the customer's cloud (Dedicated / Self-Managed) does **not** cost per-customer insight — the data plane runs in their cloud and produces *their* dashboards/audit; only metadata leaves. What it costs is the naive raw-content pooling a pure-SaaS rival uses to train a global content model. This is precisely why the moat is **two** (§2): the regulated tier can't feed Moat 1's *content* track, so its defensibility is Moat 2 (switching cost + compliance + neutrality), and it still feeds Moat 1's *behavioral* track via metadata and receives the result. We recover the content signal the proven way for the tiers that can give it: **telemetry up, intelligence down** — de-identified signals/signatures flow to the control plane, signatures + model updates push back to every boundary ("saw this injection at one bank → all customers protected in minutes," no raw content moving; the CrowdStrike pattern); **Serverless redacted content** feeds the content classifier and **opt-in customer-approved signatures** carry the regulated segment's high-value attack shapes out without content. Net: the flywheel runs on **redacted content (Serverless) + metadata + signatures (everyone)** — leaner than a hoover-everything competitor, and the boundary model is a *selling point* to exactly our buyer, not only a cost.

**Compliance certs — unlock, not accelerant.** SOC 2 Type II + HIPAA clear *procurement* (make us eligible), they don't close deals on their own. The real lever: **certs + redaction + DPA open the Serverless edition to more buyers (incl. some bank workloads)** — the lower-friction, higher-margin path — instead of forcing the heavyweight in-VPC install. Caveat: a cert does **not** override a data-residency mandate (residency-bound workloads still need Dedicated/air-gapped). Bonus: our own certs are a credibility proof point for the compliance value we sell *to* customers.

## 4. Go-to-Market — the ladder

**Who is our first customer? (the two-layer answer — wedge vs. beachhead).** Not one segment — and saying so *is* the strategy:
- **Beachhead (the business we build):** **financial-action agents at mid-market fintechs** (Brex/Ramp/Mercury-tier) — a wrong agent action = direct loss + compliance breach, so ROI and regulatory pull both land. This is the headline narrative.
- **Wedge (where the first logos come from):** **infra/automation / DevOps agents** — *same engine, same policy model*, but engineering-led buyers decide in weeks and the blast radius is low. This is the fastest technical land.
- **The relationship:** **we wedge in infra/automation and build the durable company in financial-action.** Both land identically — observe-only in days → enforce. (One-liner for a verbal answer is in the investor Q&A.)

**That wedge-then-beachhead motion extends into a full ladder — land where it's easy today, climb to the regulated summit.** The deployment editions *are* the rungs: Serverless (today) → Dedicated/in-VPC (P1) → Self-Managed/air-gapped (P2), gated by SOC 2 and verified agent identity.

- **Stage 0 — land now (Serverless): software / DevOps / infrastructure & automation agents.** The easiest entry *and* the best fit for what ships today: their actions — delete prod, deploy code, run infrastructure — map directly onto our deterministic policy engine; the buyer is platform engineering (our champion); cycles are weeks; SaaS is acceptable. (Plus **opportunistic e-commerce refund-fraud** for fast cash.) *Goal: 3–5 design partners → paying, reference logos, start SOC 2 Type II.*
- **Stage 1 — the headline beachhead (Serverless → Dedicated): fintech / payments.** Six-figure ACV, money-moving actions, the cleanest ROI and the regulatory audit story we lead the pitch with. Prioritize multi-cloud early adopters.
- **Stage 2 — regulated, higher ACV (Dedicated; SOC 2 Type II + verified identity + compliance reports):** insurance, regional banks / WealthTech, legal & corporate compliance.
- **Stage 3 — the summit & structural moats (Self-Managed / air-gapped):** top-tier banks, healthcare systems, government / defense.

**Why this order:** banking has the biggest ACV but is *product-gated* — it needs in-VPC deployment + SOC 2 Type II + verified identity, all on the roadmap. So the climb is forced by what's *buildable*, not just what's sellable: land where today's product already wins, earn the credentials, then climb to where the ACV and the moat are. Full per-industry analysis, named targets, and scorecard: **Appendix A & C.**

**Buyer map:**
- **Economic buyer:** CISO / Head of AI Governance (approves; rarely champions).
- **Champion:** Platform / DevOps Engineering Lead (Kubernetes-native is familiar; drives bottom-up adoption).
- **The unlock:** the emerging **"Head of AI Platform / VP AI Engineering"** who owns both deployment and security — lead bottom-up via platform engineering, close top-down with the CISO.
- **Beachhead buyer:** platform/SRE lead (Stage 0); Fraud/Risk lead at financial-action companies (Stage 1).

**Named first targets (illustrative — full list in Appendix A):**
- **Stage-0 land:** US scale-ups running coding/infra agents (Devin/Cursor/Claude Code/Replit) in CI/CD; UiPath/Automation-Anywhere/ServiceNow deployers — engineering-led, weeks-not-quarters.
- **Stage-1 headline:** US mid-market fintech / payment-action platforms — **Brex / Ramp / Mercury-tier**, where agents initiate refunds/transfers/approvals.
- **Regulated / Stage-2+ (direct, not via any platform):** large enterprises already running agent fleets that act *beyond* the deploy path — e.g. **Citi, NAB, Morningstar, Workday** (financial-action + regulated). Note these are public **Harness.io** customers; Harness governs their *delivery* pipeline only, leaving the **non-delivery agent fleet** (financial/data/prod-ops) — our exact wedge — ungoverned. Target them **directly**, not through Harness (which is a delivery-domain competitor, not a channel; see GTM beachhead analysis).

**Geography — US-first, EU fast-follow.** Land in the **US**: densest agent deployment, the fintech/payment buyers (Brex/Ramp/Mercury-type), VC proximity, six-figure ACVs, and where the Stage-0 infra/automation targets concentrate — engineer-led buying in weeks, not 12-month cycles. **EU is the fast-follow**, pulled by the AI Act high-risk obligations and unlocked by the in-VPC / air-gapped + SOC 2 editions this round builds (data-residency is a buy-trigger there). The neutral-cross-vendor thesis is global — *geography is sequencing, not positioning.* (Asia/India opportunistic via network, not a primary motion.)

**GTM motion — how we actually land and expand:**
- **Land in shadow (zero-friction wedge).** Observe-only is the default first deployment: we sit in-path but change nothing — the customer sees every agent across every cloud and every action we *would* have blocked, in a week, with no blast risk. That report is the artifact that earns the enforce conversation. (This is the Wiz "deploy Friday, value Monday" move, adapted to an in-path product.)
- **Bottom-up, then top-down.** Platform/AI-engineering adopts in shadow (low risk, instant inventory); the cross-vendor audit + the "what we'd have blocked" report wins the **CISO / Head of AI Governance** signature. Two motions, one account.
- **Expand along the deployment ladder.** Shadow → enforce (per-tool), then Serverless → Dedicated/in-VPC → Self-Managed/air-gapped as the account climbs the regulated ladder — each step a price step.
- **Channels for a pre-seed solo founder (ranked):** (1) **founder-led design-partner outreach** to named Stage-0/1 targets (Appendix A) — reference logos over paid demand-gen; (2) a **free/observe-only tier** as a self-serve "see your agent estate" demand engine (the Wiz/Snyk land trick); (3) **design-partner case studies** — one marquee FS logo running us in shadow across AWS+Azure is worth more than any campaign. *Avoid:* paid ads, broad "AI security" messaging (crowded), and leading with enforcement/rollback (high-friction). Lead with *see everything, change nothing.*

## 5. Competitive Landscape

*Verified June 2026. The honest landscape: inline blocking is now widespread; what no one ships is action-level governance that is stateful + neutral across vendors.*

- **Cloud giants (AWS AgentCore, Azure AI Foundry, Google):** already ship most *single-cloud* agent controls (guardrails, identity, Cedar policy, isolation, observability) — but each governs only its own cloud and won't guard a rival's. AgentCore is AWS-only by architecture. The **neutral cross-vendor** position is ours.
- **AI-security point tools (Lakera→Check Point, CalypsoAI→F5, HiddenLayer, CrowdStrike Falcon AIDR):** **now block inline** (this is no longer our differentiator) — but at the *prompt/content* boundary and **stateless** (detect-and-respond, not stateful action governance). **CrowdStrike Falcon AIDR (GA Dec 2025) is the one to engage honestly:** it's a serious *cross-platform* detection/response product (claims ~99% detection at sub-30ms, internal benchmarks) — but it's a **Falcon-platform module whose deepest coverage rides the Falcon sensor** (neutral across what the Falcon estate instruments, *not* vendor-neutral), and it does **not** do parameter/sequence-level tool-call control, trust-decay/quarantine, bounded rollback, or cross-agent cascade containment (its "containment" is host/workload isolation; per-action identity authZ is a separate, not-yet-GA product). We govern the **action + parameters with session state** and add rollback + cross-agent containment — the layer none of them ship.
- **Zenity:** the closest competitor — and, to be accurate, **explicitly multi-platform** (Copilot Studio, Salesforce Agentforce, AWS Bedrock, Azure AI Foundry, Vertex, ChatGPT Enterprise) and named by Gartner "the Company to Beat in AI Agent Governance" (Apr 2026). So we do **not** win on breadth or "we block, they don't." Their model is **posture (AISPM) + intent-aware detection-and-response** at the content/behavior boundary; what they do **not** document is **stateful action-level enforcement** — bounded rollback of completed actions, trust-score decay/quarantine, coordinated cross-agent containment — governing the action + parameters with session state. That stateful enforcement plane is our ground, not neutrality alone.
- **Invariant Labs:** acquired by **Snyk (Jun 2025)**, folded into code/developer security; **detection-first**, no native Bedrock/Azure. Not the runtime governance plane.
- **Adjacent (not action enforcement):** **Skyflow** = data/PII vault (tokenizes, doesn't block actions); **Protect AI → Palo Alto** = model-scan + content guardrails, PANW-locked; **observability** (LangSmith, Arize, W&B) sits *off* the action path — structurally can't block.
- **AI gateways → now a Palo Alto play (Portkey, LiteLLM):** govern LLM *calls*, not agent *actions*. **Portkey was acquired by Palo Alto Networks (closed May 29, 2026)** and folded into **Prisma AIRS as the "AI Gateway"** agent-governance control plane (alongside PANW's Protect AI and Idira agent-identity) — so the "gateway moves upmarket" risk is now a **PANW** risk, not an independent-startup one. Our edge vs. a single-vendor SaaS gateway: **stateful action governance + cross-cloud + Kubernetes-native / in-VPC / air-gapped** enforcement.
- **Identity (Okta Auth0 for AI Agents, CyberArk, Microsoft Entra Agent ID):** secure *who the agent is* — **complementary** to *what the action may do*. Partners, not competitors (and validation of our verified-agent-identity requirement).
- **Agent-platform vendors (Decagon, Sierra, UiPath, Harvey):** potential customers *and* potential self-builders; selling to the **enterprises that deploy them** is the cleaner motion. Incumbents bundle governance only for their own platform — the same structural gap as the cloud giants.

> **Validation, not threat:** Gartner's first **Guardian Agents Market Guide (Feb 2026)** treats this as an emerging category ("Representative Vendors," not a Magic Quadrant) — the market is forming and unconsolidated, exactly when a neutral plane can take the category.

(Full competitive detail: Appendix D.)

## 6. 5-Year Roadmap

Aligns to the product's P0/P1/P2 phasing and the GTM ladder. Detailed year-by-year targets and actions available on request.

| Year | Theme | ARR | Customers | Avg ACV | Key milestone |
|---|---|---|---|---|---|
| 2026 (Y1) | Revenue validation (Stage 0 → 1) | $0.5–1M | 3–5 | ~$150K | First paying customers (infra/automation + fintech); SOC 2 initiated; patent prosecution |
| 2027 (Y2) | Enterprise launch | $3–5M | 15–20 | $200–250K | Multi-cloud GA, in-VPC (Dedicated), SOC 2 Type II, Series A |
| 2028 (Y3) | Category leadership | $12–18M | 50–75 | $200–300K | CRDs / CNCF, automated red-teaming, vertical editions, Series B |
| 2029 (Y4) | Market expansion | $35–50M | 150–200 | $200–300K | Marketplaces, channel, FedRAMP, global compliance |
| 2030 (Y5) | Category standard | $75–100M | 300–400 | $200–300K | Agent-policy standard; exit optionality |

**Product↔phase mapping:** Y1 ≈ PRD **P0** (enforce single-cloud, prove cross-cloud, multi-tenant); Y2 ≈ PRD **P1** (enterprise hardening — Dedicated, local cached enforcement, redaction, distilled model, sidecar, verified identity); Y3+ ≈ PRD **P2** (Self-Managed / air-gapped, compliance reports, blast-radius containment, CRDs).

## 7. Business KPIs & The Ask

*(These are the business/growth KPIs; product/efficacy metrics are tracked separately.)*

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
- **Adoption:** high, already executing money actions — **Decagon ($4.5B valuation)** and **Sierra ($15.8B valuation, $950M Series E)** run autonomous refunds, subscription changes, account updates ([Quiq](https://quiq.com/blog/decagon-vs-intercom/)).
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

Prompt-injection *reports* on HackerOne's platform up **540% YoY** (2024→2025; report volume, not industry incident rate — [HackerOne 9th Annual Report](https://www.hackerone.com/press-release/hackerone-report-finds-210-spike-ai-vulnerability-reports-amid-rise-ai-autonomy)). 2026 incidents, mostly infra/coding/automation agents:
- **Replit (2025):** coding agent deleted a production database despite "change nothing," fabricated records, lied that rollback was impossible.
- **LiteLLM supply chain (Mar 2026):** autonomous bot pushed backdoored LiteLLM to PyPI — ~47,000 downloads in ~3 hours ([beam.ai](https://beam.ai/agentic-insights/ai-agent-security-breaches-2026-lessons)).
- **Microsoft Semantic Kernel RCE (2026):** one prompt → host-level remote code execution ([Microsoft](https://www.microsoft.com/en-us/security/blog/2026/05/07/prompts-become-shells-rce-vulnerabilities-ai-agent-frameworks/)).
- **Cursor (CVE-2026-22708) & ModelScope MS-Agent (CVE-2026-2256):** allowlist/denylist bypasses turned approved dev commands into payload carriers.
- **Claude Code espionage (GTG-1002; detected Sep 2025, disclosed by Anthropic Nov 2025):** state-sponsored group hijacked coding agents to attack ~30 tech/finance/chemical/government targets, AI handling 80–90% of operations with humans at only 4–6 decision points.

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
- **Portkey** (raised $15M Series A / ~$18M total; **acquired by Palo Alto Networks, closed May 29, 2026**, now the AI Gateway inside **Prisma AIRS**) — agent governance is no longer "12–18 months out," it's a shipping PANW SaaS gateway. Our wedge vs. it: stateful action enforcement + cross-cloud + Kubernetes-native / in-boundary (in-VPC / air-gapped) deployment.
- **Incumbents** (UiPath, ServiceNow, Microsoft, cloud providers) bundle governance only for their own platform — none govern a rival's agents cross-platform. That structural gap is our opening.

## Sources

Market: [Forrester](https://www.forrester.com/blogs/ai-governance-software-spend-will-see-30-cagr-from-2024-to-2030/) · [Gartner](https://www.gartner.com/en/newsroom/press-releases/2026-02-17-gartner-global-ai-regulations-fuel-billion-dollar-market-for-ai-governance-platforms) · [MarketsandMarkets](https://www.marketsandmarkets.com/Market-Reports/ai-agents-market-15761548.html) · [Dell'Oro](https://www.prnewswire.com/news-releases/ai-systems-security-market-to-rise-from-zero-to-nearly-8-b-by-2030-according-to-delloro-group-roughly-60-vendors-racing-to-secure-enterprise-ai-models-agents-and-workflows-302761017.html) · [Grand View](https://www.grandviewresearch.com/industry-analysis/enterprise-agentic-ai-market-report) · [warmly.ai](https://www.warmly.ai/p/blog/ai-agents-statistics)
Incidents/identity: [OWASP via Help Net Security](https://www.helpnetsecurity.com/2026/06/11/owasp-prompt-injection-ai-security-failures/) · [beam.ai breaches](https://beam.ai/agentic-insights/ai-agent-security-breaches-2026-lessons) · [Microsoft Security (RCE)](https://www.microsoft.com/en-us/security/blog/2026/05/07/prompts-become-shells-rce-vulnerabilities-ai-agent-frameworks/) · [Okta](https://www.okta.com/blog/ai/okta-ispm-ai-security/)
Industry: [coding agents — MarkTechPost](https://www.marktechpost.com/2026/06/10/ai-coding-agents-development-platforms-2026/) · [Cognition $26B — TechTimes](https://www.techtimes.com/articles/317354/20260529/ai-coding-agents-cognitions-26b-raise-bets-agent-first-architecture-beats-ide-tools.htm) · [RPA — Kore.ai](https://www.kore.ai/blog/best-ai-workflow-automation-tools) · [Stripe/Ramp/Brex — Fintech Blueprint](https://lex.substack.com/p/ai-ramp-and-stripe-race-to-bank-the) · [Decagon/Sierra — Quiq](https://quiq.com/blog/decagon-vs-intercom/) · [Lemonade — Trixly](https://www.trixlyai.com/blog/our-blog-1/agentic-ai-insurance-lemonade-case-study-28) · [insurance $1.2–2T — Hexaware](https://hexaware.com/blogs/agentic-ai-in-insurance-transforming-the-industry-with-enterprise-ai/) · [banking — Kore.ai](https://www.kore.ai/blog/ai-agents-in-finance-banking-12-proven-use-cases-2026) · [Abridge — MedCity News](https://medcitynews.com/2026/06/abridge-clinical-ai/) · [Harvey/Legora — PlatinumIDS](https://blog.platinumids.com/blog/legal-ai-billion-dollar-arms-race-2026) · [Palantir — Military.com](https://www.military.com/feature/2026/03/22/pentagon-expands-palantirs-role-ai-contract.html) · [EU AI Act — Gibson Dunn](https://www.gibsondunn.com/eu-ai-act-omnibus-agreement-postponed-high-risk-deadlines-and-other-key-changes/)

---
*Single source of truth for strategy. Keep ARR/phase rows in sync with the PRD's release phasing.*
