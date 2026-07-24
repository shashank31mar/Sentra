# AegionAI — Seed Cost Model & Runway

### *$5M raise · build-in-India / sell-in-US*

> **All figures are planning estimates and assumptions — speculative, not commitments.** They are built from sourced benchmarks and this account's real AWS run-rate, but actual costs will change with hiring pace, FX, AWS usage, deal activity, and market rates. Treat this as a directional model to be revised as reality lands, not a fixed budget.

*Assumptions: FX ₹90/USD · India employer load 15% · 30% contingency buffer on recurring burn · US enterprise Account Executive (AE) deferred in the base case (founder-led sales first ~12–18 months).*

---

## Headline (Base scenario)

| Metric | Value | How derived |
|---|---:|---|
| Total raise | **$5,000,000** | Seed round |
| Recurring burn / year | **$1,348,796** | buckets subtotal $1,037,535 + 30% buffer $311,261 |
| Recurring burn / month | **$112,400** | annual ÷ 12 |
| One-time costs | **$90,300** | laptops + deposits + SOC2 T1 + seed legal/patent + formation |
| **Base runway (months)** | **43.7** | ($5,000,000 − $90,300 one-time) ÷ $1,348,796/yr × 12 |
| Headcount (India base) | 8 | + US AE when hired = 9 |

## Use of Funds — where the $5M goes

Share of the raise over the 44-month base runway (US AE deferred).

| Bucket | Annual | Over runway | % of $5M |
|---|---:|---:|---:|
| Team — eng + product + leadership (India) | $677,222 | $2,465,131 | **49.3%** |
| GTM — programs only, founder-led sales (AE deferred) | $100,800 | $366,918 | **7.3%** |
| Cloud / AWS + AI coding tools | $80,100 | $291,569 | **5.8%** |
| Physical infra & facilities | $33,333 | $121,334 | **2.4%** |
| Operations & G&A | $71,680 | $260,920 | **5.2%** |
| Compliance & certifications | $74,400 | $270,821 | **5.4%** |
| Contingency buffer (30%) | $311,261 | $1,133,008 | **22.7%** |
| **Total** | | **$4,909,700** | **98.2%** |

*Memo (not summed into Total above): if the US enterprise AE is hired full-year, GTM (programs + AE, loaded) ≈ **27.7%** of $5M and runway drops to **33.9 months** — see the "+ US AE" scenario below.*

> **Note:** **Team ≈ 49.3% of spend**; real **cloud/infra is only ~5.8%** (not a red flag — the distilled model self-hosts on CPU, so no ~$1M GPU line is needed). **GTM here (7.3%) is programs-only** — founder-led sales, AE deferred; see the memo above for the ~27.7% figure once the AE is hired.

## Team & Compensation

Per-role salaries. India comp shown INR→USD at ₹90, then + 15% employer load. The US enterprise seller is priced in USD (cannot be India-priced) and is **deferred** in the base case.

Hiring phase: **Start** = day one · **Scale** ≈ mo 9 · **Sell** ≈ mo 12–18.

| Role | Hire | Loc | Base (INR/yr) | Base (USD/yr) | How derived |
|---|---|---|---:|---:|---|
| Founder / CEO | Start | India | ₹8,500,000 | $94,444 | ₹85L ÷ 90 |
| Security CTO | Start | India | ₹8,500,000 | $94,444 | ₹85L ÷ 90 (= CEO for now) |
| Sr Engineer (SDE3) | Start | India | ₹8,000,000 | $88,889 | ₹80L ÷ 90 |
| ML Engineer | Start | India | ₹6,000,000 | $66,667 | ₹60L ÷ 90 |
| Engineer (SDE2) | Start | India | ₹5,000,000 | $55,556 | ₹50L ÷ 90 |
| Engineer (SDE2) | Start | India | ₹5,000,000 | $55,556 | ₹50L ÷ 90 |
| Engineer (SDE2) | Scale | India | ₹5,000,000 | $55,556 | ₹50L ÷ 90 |
| Product Manager | Scale | India | ₹7,000,000 | $77,778 | ₹70L ÷ 90 |
| *Enterprise AE (DEFERRED)* | Sell | US | — | *$300,000* | $140K base + $135K commission (OTE ~$275K) × 1.15 burden |
| **India base payroll** | | | | **$588,889** | sum of 8 India roles |
| + India employer load (15%) | | | | **88333.33333333333** | $588,889 × 0.15 |
| **BASE PAYROLL (loaded, India)** | | | | **$677,222** | flows to runway; $56,435/mo |
| *US seller (deferred, loaded)* | | | | *$300,000* | added when hired (see scenarios) |

## Operating Costs — by bucket (annual)

Bucket 1 is payroll (above). Buckets 2–7 below; *(one-time)* rows are excluded from the recurring subtotal and sit in one-time costs instead.

**1 · Team & Compensation** — recurring **$677,222/yr** ($56,435/mo). India team; see table above.

**2 · Physical Infrastructure & Facilities** — recurring **$33,333/yr**  ·  one-time $43,300

| Line item | Annual | Type | How derived | Note |
|---|---:|:--:|---|---|
| Office rent — Bangalore | $33,333 | recurring | ₹2.5L/mo × 12 ÷ 90 | Base sheet |
| Laptops — MacBook Pro × 10 | $27,800 | one-time | ₹25L ÷ 90 | 3-yr refresh |
| Mac Studio × 1 (ML/dev) | $4,400 | one-time | ₹4L ÷ 90 | One-time |
| Office deposit + setup | $11,100 | one-time | ₹10L ÷ 90 | Refundable deposit + fit-out |

**3 · AI Coding Tools (Claude Code)** — recurring **$14,400/yr**

| Line item | Annual | Type | How derived | Note |
|---|---:|:--:|---|---|
| Claude Code — Team plan (8 × $150/seat) | $14,400 | recurring | 8 seats × $150/seat/mo × 12 | Anthropic Team plan (premium seat, annual): Claude Code + org SSO / central billing / admin; cheaper than 8 individual Max subscriptions |

**4 · Cloud / AWS Infrastructure** — recurring **$65,700/yr**

| Line item | Annual | Type | How derived | Note |
|---|---:|:--:|---|---|
| Bedrock foundation-model inference | $30,000 | recurring | ~$2.5K/mo × 12 (real run-rate) | Dominant lever; declines as distilled sidecar absorbs ALLOWs |
| Distilled classifier — CPU Fargate (HA) | $1,740 | recurring | ~$145/mo × 12 | 2 HA tasks; 5× cheaper than always-on GPU |
| GPU retraining (amortized) | $1,440 | recurring | ~$120/mo × 12 | Rent g5/p4 for periodic distillation runs only |
| Platform (ECS+DynamoDB+S3+CW+API GW+ALB+NAT) | $14,520 | recurring | ~$1,210/mo × 12 (real run-rate) | Core production platform |
| Legacy tail (OpenSearch/SageMaker/EC2) → $0 | $18,000 | recurring | ~$1.5K/mo × 12, decaying | Winding down; not part of clean target |

**5 · GTM Programs (non-payroll)** — recurring **$100,800/yr**  ·  one-time $1,500

| Line item | Annual | Type | How derived | Note |
|---|---:|:--:|---|---|
| Events & conferences (RSA + meetups) | $42,000 | recurring | RSA booth+passes + meetups, annual | Excl. BLR→US travel (separate line) |
| Founder US travel (sell-in-US) | $26,400 | recurring | 5–6 trips/yr SF/NYC × ~$4.4K/trip | GSA per-diem basis |
| Content / website / demand-gen | $18,000 | recurring | ~$1.5K/mo × 12 | Seed-stage light demand-gen |
| CRM + sales tooling (HubSpot) | $8,400 | recurring | ~$700/mo × 12 | HubSpot Sales + tooling |
| HubSpot Pro onboarding | $1,500 | one-time | one-time fee | One-time |
| Design-partner program (mostly non-cash) | $6,000 | recurring | ~$500/mo × 12 | Credits/support for observe-only partners |

**6 · Operations & G&A (US C-corp + India Pvt Ltd)** — recurring **$71,680/yr**  ·  one-time $27,500

| Line item | Annual | Type | How derived | Note |
|---|---:|:--:|---|---|
| Legal — ongoing (MSAs/DPAs/IP) | $36,000 | recurring | ~$3K/mo × 12 | Bank MSA/DPA load |
| Accounting / bookkeeping (US + India) | $10,200 | recurring | ~$850/mo × 12 | Kruze benchmark |
| Payroll + tax filings (US + India) | $4,200 | recurring | ~$350/mo × 12 | Amortized |
| Insurance — D&O | $4,800 | recurring | ~$400/mo × 12 | <$10M funding band |
| Insurance — Tech E&O + Cyber + GL | $5,200 | recurring | ~$430/mo × 12 | Banks demand $2–5M limits |
| Business SaaS stack | $6,480 | recurring | ~$60/head × 9 heads × 12 | Google WS, Slack, Notion, GitHub, 1Password, Zoom |
| US C-corp + India Pvt Ltd ongoing compliance | $2,400 | recurring | ~$200/mo × 12 | DE franchise/agent + India ROC/MCA/audit |
| Banking / cross-border FX | $2,400 | recurring | ~$200/mo × 12 | Wise/wires |
| Entity formation (US + India) | $500 | one-time | one-time filings | One-time |
| Seed-financing legal + first patent | $27,000 | one-time | round docs ~$20–40K + patent ~$10–15K | One-time Yr-1 |

**7 · Compliance & Certifications** — recurring **$74,400/yr**  ·  one-time $18,000

| Line item | Annual | Type | How derived | Note |
|---|---:|:--:|---|---|
| SOC 2 automation platform (Vanta/Drata) | $12,000 | recurring | ~$1K/mo × 12 | Annual subscription |
| SOC 2 Type II auditor (annual) | $18,000 | recurring | annual audit fee | Recurring |
| Third-party pen test (annual) | $12,000 | recurring | annual pen test | Banks demand current report |
| SOC 2 Type I auditor (interim) | $10,000 | one-time | one-time Yr-1 interim | Unblocks early deals |
| SOC 2 readiness / gap + policy dev | $8,000 | one-time | one-time Yr-1 | Gap assessment + policies |
| GDPR — fractional DPO + tooling (conditional) | $32,400 | recurring | ~$2.7K/mo × 12 | Gate until EU customers exist |

## Runway & Scenarios

Runway = (Raise − one-time) ÷ annual recurring burn × 12. All scenarios include the 30% buffer.

| Scenario | Annual burn | Runway (mo) | How derived |
|---|---:|---:|---|
| **Phased hiring** (recommended) | ramps | **45.0** | start 6 heads $95,399/mo for 9 mo, then full team |
| Base (full India team day 1, founder-led sales) | $1,348,796 | 43.7 | buckets + buffer, US AE deferred |
| + US enterprise AE (full year) | $1,738,796 | 33.9 | base + AE $300,000 × 1.30 |
| Lean (trim AWS legacy + GTM) | $1,265,596 | 46.6 | base − ~$64K, + buffer |
| High (AE + fractional VP + high cloud) | $1,894,796 | 31.1 | base + (AE + $120K VP) × 1.30 |

**Phased hiring plan (recommended):**

| Phase | When | Team | Adds |
|---|---|---|---|
| Start | mo 0 | CEO + **Security CTO** + SDE3 + 2× SDE2 + ML (6 India) | Founder owns product & sales |
| Scale | ~mo 9 | + 3rd SDE2 + **Product Manager** | PM once design-partner delivery outgrows founder |
| Sell | ~mo 12–18 | + US enterprise AE | Once founder-led sales prove a repeatable motion |

*The starting 6-head team burns only ~$95,399/mo — if never scaled it would run 51 months. Phasing the last India hires in at ~mo 9 lands ~45 months total. Adding the US AE full-time from day one is what drops the plan to 34 months, so that hire waits for traction.*

## Sources

Every external unit cost traces to a source (accessed 2026-07-23). AWS figures are grounded in this account's real run-rate (~$6–14K/mo, Apr–Jun 2026). **These remain estimates and will change.**

| Bucket | Figure | Source |
|---|---|---|
| Claude Code | Max 20x $200 / Max 5x $100; blend $150/seat | [claude.com/pricing](https://claude.com/pricing) |
| Claude Code | PAYG ~$13/dev/active-day; $150–250/dev/mo | [Anthropic Claude Code costs](https://code.claude.com/docs/en/costs) |
| AWS — Bedrock | Haiku $1/$5, Sonnet $3/$15 per MTok | [Anthropic/Bedrock pricing](https://platform.claude.com/docs/en/about-claude/pricing) |
| AWS — Fargate | CPU serving ~$145/mo | [AWS Fargate pricing](https://aws.amazon.com/fargate/pricing/) |
| AWS — GPU | g5.xlarge $1.006/hr; retraining ~$120/mo | [Vantage EC2](https://instances.vantage.sh/aws/ec2/g5.xlarge) |
| AWS — real run-rate | ~$6–14K/mo actual (Apr–Jun 2026) | AWS Cost Explorer, acct 531109575379 |
| GTM — US AE | base ~$140K / OTE ~$275K; loaded ~$312K | [RepVue enterprise-AE](https://www.repvue.com/salaries/enterprise-account-executive) |
| GTM — events | RSA passes/booth | [Lensmor RSAC 2026](https://www.lensmor.com/event-guides/rsa-conference-2026-attendee-guide) |
| GTM — travel | GSA per-diem; SF/NYC lodging | [GSA per-diem](https://www.gsa.gov/travel/plan-book/per-diem-rates) |
| GTM — CRM | HubSpot Starter/Pro + onboarding | [HubSpot pricing](https://www.hubspot.com/pricing/sales) |
| Compliance — SOC 2 | Type I ~$10K, Type II ~$18K/yr, readiness ~$8K | [Drata SOC 2 cost](https://drata.com/learn/soc-2/cost) |
| Compliance — platform | Vanta/Drata ~$12K/yr | [RiskPublishing SOC 2](https://riskpublishing.com/soc-2-audit-cost-complete-pricing-breakdown/) |
| Compliance — GDPR DPO | fractional DPO ~$2.2K/mo | [EngageCompliance](https://engagecompliance.co/fractional-dpo-pricing-benchmark-2026) |
| Ops — legal | seed ~$3K/mo; round+patent ~$27K one-time | [Arceus startup legal](https://arceus.legal/blog/how-much-should-legal-cost-startup-by-stage) |
| Ops — accounting | ~$850/mo bookkeeping | [Kruze pricing](https://kruzeconsulting.com/pricing/) |
| Ops — insurance | D&O $3.5–6K/yr; E&O+cyber+GL | [Embroker D&O](https://www.embroker.com/blog/directors-and-officers-insurance-cost/) |
| Ops — India entity | Pvt Ltd ROC/MCA ₹40K–1.5L/yr | [Incorpx](https://incorpx.io/blog/annual-compliance-cost-startups-2026) |
| Ops — US entity | DE franchise/agent + CA $800 | [Delaware Div. of Corp.](https://corp.delaware.gov/paytaxes/) |
| Ops — SaaS | ~$60/head | [Google Workspace](https://workspace.google.com/pricing) |
| Team — India salaries | SDE2 ₹50L, SDE3 ₹80L, ML ₹60L, CEO/CTO ₹85L | Founder base sheet (internal, 2026-02) |

<sub>© 2026 AegionAI. Confidential — internal planning model, all figures estimated/speculative. Editable source: AegionAI-Cost-Model.xlsx (formulas recalc on open).</sub>
