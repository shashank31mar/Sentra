# AegionAI Guard — Strategy, GTM & Roadmap

**Version:** 0.1 (scaffold)
**Last Updated:** 2026-06-15
**Status:** Draft for Review
**Owner:** Shashank Gupta (Founder/CEO)
**Companion docs:** [PRD.md](PRD.md) (the "what") · [vision.md](vision.md) (vision & pillars) · [ARCHITECTURE.md](ARCHITECTURE.md) (the "how") · [pitch/](pitch/) (external materials)

> This doc holds the **market, go-to-market, roadmap, and business targets**. The PRD stays product-only and references this doc for anything business/growth. Detailed source research lives in [pitch/customer/5-year-roadmap.md](pitch/customer/5-year-roadmap.md); this is the consolidated, durable version.

---

## 1. Market & Why Now

- **TAM:** AI-governance software ~$5B (2026) → ~$16B (2030). The cloud-agnostic, fleet-level slice (our space) ~$5.8B by 2030 at ~45% CAGR. Near-term beachhead (agents that handle money) ~$500M.
- **Adoption gap:** ~82% of enterprises use AI agents; only ~26–44% govern them.
- **Regulatory forcing function:** EU AI Act enforcement **Aug 2, 2026** — financial AI agents are high-risk; penalties up to **7% of global revenue**.
- **Market signal:** two AI-security startups recently acquired ($300M, $180M).
- **Sales reality:** enterprise cycle 90–180 days, ACV $100K–$500K; to close in a quarter, start outreach the prior quarter.

*Sources: Forrester, Gartner, MarketsandMarkets, IBM, CNCF, OWASP — see [pitch/one-pager.md](pitch/one-pager.md) and the 5-year roadmap doc.*

---

## 2. Positioning & Moat

**Positioning:** the only platform that governs AI-agent **actions** across AWS, Azure, GCP, and on-prem simultaneously — real-time enforcement (not just detection), cross-agent blast-radius containment, and a deployment model regulated buyers can accept (in-VPC, air-gapped). Cloud providers structurally can't match this — each protects only agents on its own cloud.

**Why we win / defensibility:**
- **Cloud giants are structurally blocked** — they won't guard agents on a rival's cloud.
- **Standards play** — first to define agent-policy CRDs becomes the default (Kubernetes/HashiCorp precedent).
- **Cross-cloud threat-data moat** — only a cross-cloud platform sees multi-cloud attack patterns; every agent protected compounds the lead.
- **On-prem/air-gapped permanence** — regulated buyers structurally can't use a single-cloud or pure-SaaS competitor.
- **Patent pending** on the core approach.

**Honest weaknesses (don't overclaim):** competitors have larger attack-pattern corpora and formal-verification depth today; no enterprise trust/brand yet; rollback is not our lead. *(See [pitch/competitive-analysis-honest.md] and the 5-year roadmap for detail.)*

---

## 3. Go-to-Market

**Beachhead — agents that handle money.** Fintech/payments companies putting agents in charge of refunds, transfers, lending: a wrong action is an instant loss *and* a legal problem, so they pay to prevent it; stopping one bad transaction pays for us, and we hand them the regulator-required audit trail. Fast-moving buyers who can decide in weeks. *(Beachhead emphasis — financial-action agents vs a B2C-fraud wedge — is an open GTM decision; see §6.)*

**Expansion — multi-cloud enterprises.** Large companies running agents on more than one cloud — the gap no cloud provider will close. This is the position only we can hold.

**Buyer map:**
- **Economic buyer:** CISO / Head of AI Governance (approves; rarely champions).
- **Champion:** Platform / DevOps Engineering Lead (K8s-native = familiar; the trojan horse).
- **User/integrator:** AI/ML engineers.
- **Beachhead buyer:** Fraud/Risk lead at financial-action companies.

---

## 4. 5-Year Roadmap (summary)

Aligns to the PRD's P0/P1/P2 phasing. Detailed targets, customer lists, and GTM actions per year are in [pitch/customer/5-year-roadmap.md](pitch/customer/5-year-roadmap.md).

| Year | Theme | ARR | Customers | Avg ACV | Key milestone |
|---|---|---|---|---|---|
| 2026 (Y1) | Revenue validation (beachhead) | $150–300K | 3–5 | ~$60K | First paying customers; SOC 2 initiated; patent prosecution |
| 2027 (Y2) | Enterprise launch | $3–5M | 15–20 | $200–250K | Multi-cloud GA, in-VPC (Dedicated), SOC 2 Type II, Series A |
| 2028 (Y3) | Category leadership | $12–18M | 50–75 | $200–300K | CRDs/CNCF, automated red-teaming, vertical editions, Series B |
| 2029 (Y4) | Market expansion | $35–50M | 150–200 | $200–300K | Marketplaces, channel, FedRAMP, global compliance |
| 2030 (Y5) | Category standard | $75–100M | 300–400 | $200–300K | Agent-policy CRD as the standard; exit optionality |

**Product↔phase mapping:** Y1 ≈ PRD **P0** (enforce single-cloud, prove cross-cloud); Y2 ≈ PRD **P1** (enterprise hardening — Dedicated, local cached enforcement, redaction, distilled model, sidecar); Y3+ ≈ PRD **P2** (Self-Managed/air-gapped, compliance reports, blast-radius containment, CRDs).

---

## 5. Business KPIs (targets)

*(Product/efficacy metrics live in [PRD.md](PRD.md) §3.2. These are the business/growth KPIs.)*

| KPI | What it tracks |
|---|---|
| ARR | Recurring revenue (trajectory above) |
| Customers / design partners | Logos signed; marquee FS name |
| Average ACV | Deal size by segment |
| Net revenue retention (NRR) | Expansion within accounts |
| Pipeline / win rate | GTM efficiency |
| SOC 2 status | Type II milestone (in progress) |
| Runway | Months remaining vs raise plan |

**The Ask (current):** raising $2M for ~24 months runway → ship third cloud, harden for enterprise (Dedicated + self-managed, on-device detection, resiliency), convert 3 design partners into 3–5 paying enterprises incl. one marquee FS name, ~$500K–$1M ARR, SOC 2 underway.

---

## 6. Key Strategic Decisions / Open Questions

1. **Beachhead emphasis** — financial-action agents (current one-pager) vs a faster B2C-fraud wedge (5-year roadmap doc). Reconcile.
2. **Open-source core?** — OSS agent-policy CRD + basic engine (HashiCorp/Snyk playbook) vs closed.
3. **Pricing/metering basis** — per-agent, per-action/validation, or per-cluster (see ARCHITECTURE.md §Metering & Billing once written).
4. **Security co-founder / advisor** — named security leadership for enterprise/bank procurement credibility.
5. **Company name** — finalized as AegionAI (product: AegionAI Guard); confirm domains/trademarks.

---
*Living document. Keep ARR/phase rows in sync with the PRD's release phasing and the detailed 5-year roadmap.*
