# AegionAI Guard

**The neutral control plane for every AI agent.** AegionAI Guard governs the *actions* AI agents take — across AWS, Azure, GCP, and on-prem from one place — evaluating *what* an action does (parameters, identity, sequence, session/trust state), not just whether a prompt looks bad, and stopping the harmful action the instant it happens.

> *"Sentra" is the internal control-plane codename and the name of this repository; the customer-facing product is **AegionAI Guard** (company: **AegionAI**).*

## What it does

- **Action-level governance** — Cedar policy (tool/parameter/sequence) + Sigma signatures + ML detection + per-agent trust state, combined deny-overrides.
- **Block-before-execute, fail-secure, quarantine** — built today; **bounded, opt-in rollback** where an action is reversible (roadmap).
- **Neutral across vendors** — one plane the clouds structurally can't be; identity vendors (Okta, Entra Agent ID) are partners, not competitors.
- **Customer-set data boundary** — Serverless (today) → Dedicated/in-VPC → Self-Managed/air-gapped.

## Architecture (in one line)

A **PEP/PDP split**: a lightweight **checkpoint (PEP)** in the customer's environment intercepts each action and enforces the verdict; the **policy engine (PDP)** — the "brain" — decides; the **control plane is never on the action path**. See [lld/ARCHITECTURE.md](lld/ARCHITECTURE.md).

## Where things live

| Path | What |
|---|---|
| [src/](src/) | Application code (Python) — `security-controller/` (the PDP), `connectors/`, demo agents, `dashboard/` |
| [benchmarks/](benchmarks/) · [benchmarks.md](benchmarks.md) | In-process security benchmark harness & local E2E runbook (`agentdojo`, `asb`, `local_prompts`) |
| [cdk/](cdk/) | AWS CDK infrastructure (Python) |
| [frontend/](frontend/) | React 19 + TypeScript + Tailwind console |
| [lld/](lld/) | Architecture + low-level design docs ([ARCHITECTURE.md](lld/ARCHITECTURE.md) is the index) |
| [PRD.md](PRD.md) · [vision.md](vision.md) | Requirements · vision |
| [pitch/share/STRATEGY.md](pitch/share/STRATEGY.md) | Market / GTM / moat |
| [CLAUDE.md](CLAUDE.md) | Orientation for working in this repo |
