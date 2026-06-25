# AegionAI — Pricing Model

*A starting position to pressure-test with design partners — not final list price. Answers two questions: how a customer is charged, and how this becomes a good business.*

---

## Principles (why the model looks the way it does)

1. **Value-based, not cost-plus.** We're priced against the *risk and compliance cost we remove* — a single prevented unauthorized transaction, or one avoided regulatory penalty, dwarfs the annual fee. The pitch is always *"less than the cost of one incident."*
2. **Never penalize coverage.** We sit in the hot path of *every* action — so we must *never* meter per-action as the primary charge. Charging per check makes customers guard *fewer* agents to save money, which is the opposite of safe. Pricing must reward putting **everything** behind us.
3. **Land small, expand naturally.** Start with a few high-risk agents; grow as agent count and clouds grow. Agent counts are exploding (projected ~1.3B AI agents by 2028) — the meter should ride that curve.
4. **A free wedge for adoption.** A free tier (and open-source visibility layer) puts us in clusters before any procurement conversation, the way the standard-setters did it.

## The meter: **per governed agent**, with capability gates

- **Primary unit = a governed agent** (an agent under active policy). It's predictable, it's how buyers already count their exposure ("we have ~40 agents in production"), and it expands as they deploy more.
- **Capability gates** layer on top — the high-value differentiators unlock at higher tiers: **cross-cloud governance, blast-radius containment, on-prem, compliance reporting.**
- **Not** per-API-call (punishes coverage), **not** per-seat (it's not a human tool).

## Tiers

| Tier | Who | Agents | What's included | Indicative price |
|---|---|---|---|---|
| **Free / Open** | Developers, evaluators | up to ~5 | Single cloud · prompt-injection + PII blocking · basic tool/parameter policy · community support | **$0** |
| **Growth** | Mid-market fintech / single-cloud teams | up to ~50 | + sequence enforcement · trust/quarantine · audit logs · email support | **~$15–30K/yr** |
| **Scale** | Multi-cloud companies | up to ~500 | + **cross-cloud governance** · blast-radius containment · compliance-ready audit · priority support | **~$40–80K/yr** |
| **Enterprise** | Regulated / Fortune-class | unlimited | + **on-prem / air-gapped** · compliance report packs (EU AI Act, SOC2, HIPAA) · dedicated engineer · SLA | **custom, ~$150–500K/yr** |

*Effective per-agent price falls as you move up — volume + value, not a tax on growth. Annual contracts; an overage allowance rather than hard cutoffs so safety is never interrupted by a billing limit.*

## What unlocks where (the upsell path)

`Single-cloud protection` (Growth) → **`cross-cloud governance`** (Scale, our wedge becomes a moat) → **`on-prem + compliance`** (Enterprise, where no SaaS competitor can follow). The customer *graduates up the same platform* — we don't get ripped and replaced.

## How a customer justifies it

- **Fintech beachhead:** one blocked unauthorized transfer, or one enforced approval step the agent would've skipped, typically exceeds the annual fee — plus they get the audit trail a regulator now requires (otherwise a separate compliance project).
- **Framing:** position against the **+$670K average added cost of an AI-related breach** and EU AI Act exposure (up to 7% of revenue) — the fee is a rounding error against either.

## Why this is a good business *(for investors)*

- **Land-and-expand built in:** revenue grows as customers add agents *and* clouds — natural **net revenue retention > 100%** as agent fleets multiply.
- **High gross margin:** software control plane; the ML check is the only variable cost and runs only on borderline traffic.
- **Two expansion vectors per account:** more agents (volume) and tier upgrades (cross-cloud → on-prem/compliance).
- **Free/open wedge** lowers CAC by seeding adoption before sales engages.

## Open questions to validate with the first 3 design partners

1. Is **per-agent** the unit they actually budget by — or do they think in *workflows* / *applications*? (We may offer a per-workflow option.)
2. Where's the price ceiling before they'd build in-house or wait for a cloud vendor to bundle?
3. Does cross-cloud justify a **step-change** in price (it's the unique value) or just a tier bump?
4. Do they want **usage transparency** (a dashboard of checks) even though we don't bill per check?
5. Compliance reporting — bundled, or a separate **add-on SKU** (it may carry its own budget line)?

---
*Bottom line: charge per governed agent, gate the differentiators, never meter the hot path. Land at one high-risk agent, expand to the fleet and across clouds.*
