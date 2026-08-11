# AegionAI — Governance for what AI agents *do*

### *A neutral control plane that governs AI-agent **actions** — across every cloud, inside the customer's own boundary.*

---

## The shift

AI agents have crossed from **answering** to **acting** — moving money, changing records, calling systems. As the largest US bank put it in its own engineering blog: *"Agents do not just produce outputs; they take action,"* which *"expands the attack surface."* Its conclusion: move *"towards continuous, runtime governance of agent behavior,"* where controls *"operate at the point of execution,"* produce *"tamper-evident … runtime records,"* and let agents *"be constrained or stopped when behavior deviates."* ([JPMorganChase, "Securing the next generation of AI agents," Mar 2026](https://www.jpmorganchase.com/about/technology/blog/securing-agentic-ai))

A systemically-important bank describing a control that doesn't yet exist as a product. **We built it.** The question moved from *"is this prompt safe?"* to *"is this **action** allowed — given its parameters, sequence, identity, and the session's accumulated trust?"* — which prompt-and-content filters, sitting off the action path, can't answer.

## Why now (honestly: early, and inevitable)

- **Real pain, early market.** 96% of CISOs now own AI governance and 78% have stood up dedicated AI-agent security teams ([Splunk CISO Report 2026, n=650](https://www.splunk.com/en_us/campaigns/ciso-report.html)); 65% report an AI-agent incident in the past year ([CSA 2026, n=418, sponsored](https://cloudsecurityalliance.org/press-releases/2026/04/21/new-cloud-security-alliance-survey-reveals-82-of-enterprises-have-unknown-ai-agents-in-their-environments)). Yet Gartner forecasts **>40% of agentic-AI projects cancelled by end-2027** — largely for *inadequate risk controls* — as agentic AI reaches **33% of enterprise software by 2028** ([Gartner, Jun 2025](https://www.gartner.com/en/newsroom/press-releases/2025-06-25-gartner-predicts-over-40-percent-of-agentic-ai-projects-will-be-canceled-by-end-of-2027)). **The missing control is what unblocks the deployment.**
- **Stakes are here; so is the upside.** An Arup employee wired ~US$25M after a deepfake exec call ([CNN, 2024](https://www.cnn.com/2024/05/16/tech/arup-deepfake-scam-hong-kong-intl-hnk/index.html)); early rollouts have stumbled (Klarna course-corrected its AI-first support in May 2025). Gen-AI could add **$200–340B/yr of value to banking** ([McKinsey — modeled potential](https://www.mckinsey.com/industries/financial-services/our-insights/capturing-the-full-value-of-generative-ai-in-banking)) — but only for agents an institution can *let act*. Two AI-security startups were acquired Sept 2025: F5/CalypsoAI ($180M), Check Point/Lakera (reportedly ~$300M).

## What we've built (running today)

A **working system, live across two clouds** from one control plane. In the demo: a payment agent's **$5,000 refund is blocked** for exceeding the manager's cap (a compliant $150 passes); a **prompt-injection attempt is stopped** before the database; a **mass-PII export is denied**; a repeat-violation agent is **quarantined** — every decision written to a tamper-evident audit trail. Two layers: a **deterministic floor** (exact parameters, sequence, caller identity — the part a worded prompt can't talk past) beneath a **probabilistic detector**. SDK wrapper + cloud connector (Bedrock/Azure) live; network sidecar roadmap.

## Why it's hard to copy

Inline action-blocking is no longer novel — a Y-Combinator cohort is building it (e.g. **Salus**, W26), and cross-vendor coverage exists (Zenity, CrowdStrike). So we don't claim the *mechanism* as the moat. The defensible ground is the **combination three ways at once**, which no one else holds together:

1. **Neutral across AWS/Azure/GCP/on-prem** — a position the clouds structurally won't take (AWS won't govern Azure's agents). AWS Bedrock AgentCore added Cedar default-deny **at its own Gateway** (2026) — but only for agents routed through it, on its own cloud.
2. **In-VPC → air-gapped deployment ladder** — for regulated buyers whose data can't leave; the independents lean SaaS/posture.
3. **The tamper-evident agent-decision record** — the policy→signal→verdict→action→outcome chain. Only the inline decision point *owns* that data — and it's exactly the *"tamper-evident runtime record"* the bank above asked for.

*(Patent pending on the core approach — a speed bump, not the moat.)*

## Where we play

Land on **infra/automation agents** (deploy/config/data) where the buyer moves in weeks and agents already span clouds; climb to **money-movement agents** (refunds, transfers, treasury) — irreversible actions where the audit trail is the reason to pay. We govern the customer's *own* agents, on any cloud — the seam platform and endpoint tools miss. (No regulation *mandates* this — the EU AI Act governs AI systems by risk class, not agent actions — we make existing obligations cheaper to satisfy.)

## Traction — honest

**Working MVP + live two-cloud demo; a provisional patent filed. No paying customers yet.** We are in active discovery with regulated-enterprise CISOs and CTOs to validate the buyer pull before we scale — the operator demand above (JPMorgan, the surveys) is validation of *need*, not proof of a market we've captured.

## Team & Ask

**Shashank Gupta — Founder/CEO** (ex-Amazon: cross-org observability at ~100-eng scale for a $4B service; built the core ML platform behind OpenSearch semantic search + led a cross-org SIEM effort). **Sylvester Fernandez — Co-Founder**, four decades US enterprise/GTM. **Shikhar Jain — Security Advisor** (Eng Lead, LinkedIn; ran security posture for $6B of AWS services). **Next hire:** an India-based CTO with deep security experience.

**Raising $5M** — ~50% engineering (India-based ~8-person core incl. security CTO), ~10% ops, ~10% infrastructure (self-hosted CPU models keep this low), ~10% go-to-market, ~20% contingency reserve — for **40+ months of runway** to ship the third cloud, harden the in-VPC/air-gapped editions, and convert design partners to paid.

---

*AI without governance is just liability at scale.*

<sub>© 2026 AegionAI. Confidential — shared for evaluation. **info@aegionai.ai**</sub>
