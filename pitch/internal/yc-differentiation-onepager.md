# AegionAI — Why us, and why not just the others

**One line:** A neutral control plane that governs what AI agents are *allowed to do* — across AWS, Azure, GCP, and on-prem, from one place. Live today on two clouds.

**For:** YC interview prep + investor leave-behind. Answers the one question that decides the room: *"agent security is crowded now — why you?"*
**Date:** 2026-08-04 · **Sources:** [STRATEGY.md](../share/STRATEGY.md), [yc-2025-2026-competitive-scan.md](yc-2025-2026-competitive-scan.md)

---

## The problem, in one breath
Enterprises are putting autonomous AI agents into production faster than anyone can govern them. The instant an agent can *act* — move money, delete infrastructure, change a customer record, direct another agent — a wrong or hijacked action is a **direct financial and compliance loss**, not a bad chat reply. The Arup deepfake wire ($25.6M) and OWASP's agentic threat list are the market waking up to this.

## What everyone built — and the gap they left
The industry poured effort into governing what an agent **says** (prompt-injection scanners, observability, evals). Governing what an agent **does** — neutrally, in the place a regulated enterprise can actually deploy — was left open.

## What we do differently — the combination, not any single leg
We judge the **action itself**: its parameters, the sequence it belongs to, the caller's identity/authorization, and the session's accumulated trust — then allow, block, or quarantine *before it executes*. A **deterministic policy floor** (exact parameters, step order, caller identity) runs first — the part a cleverly-worded prompt can't talk past — with a probabilistic detector for depth. And the same engine runs **in our cloud, inside the customer's VPC, or fully air-gapped**, every action producing a **tamper-evident record** that stands up as SOC 2 / HIPAA / EU AI Act evidence.

---

## Why not just… (the competitive teardown)

| If they ask about… | Who | What they've got | What they're missing (our seat) |
|---|---|---|---|
| **"Block the action" startups** | Salus (YC W26), Golf, Alter, Silmaril | Proved "govern the action, not the prompt" — real, well-built | **SaaS-only; model-agnostic ≠ cloud-neutral; no in-VPC/air-gap; dev/reliability buyer.** They validated the wedge; they can't serve the regulated, multi-cloud buyer. |
| **Cross-vendor security platforms** | Zenity, CrowdStrike, Straiker | Strong cross-vendor *visibility & detection* | They **detect and report** — not an inline, neutral, in-VPC **enforcement chokepoint** on the action. |
| **Cloud-native guardrails** | AWS Bedrock AgentCore, Azure Foundry, Google | Strong controls *for their own cloud* | Govern only agents built on **their** rails; won't sit inline to block on a **rival's** cloud. Structurally conflicted to be neutral. |
| **Agent-identity vendors** | Okta, CyberArk, Entra Agent ID, Multifactor, Clawvisor | *Who the agent is* | Complementary, **not competitive** — we answer *what the action may do*. We partner with this layer. |
| **Observability / evals** | LangSmith, Arize, Datadog LLM | Debugging + optimization | Off the action path; can't block. Not compliance evidence. |

**The one-sentence version:** *Point tools race each other on "block the action." The regulated, multi-cloud enterprise — the buyer who pays most and churns least — still has no one who governs neutrally, inside their VPC, with audit a regulator accepts. That seat is ours, and no SaaS-only or single-cloud player can take it.*

---

## The two moats (each strongest where the other is weakest)
1. **Structural** (needs no data; strongest in regulated/in-VPC): neutrality + switching cost (we become the cross-vendor audit system-of-record and the egress chokepoint) + compliance certification + on-prem/air-gapped permanence.
2. **Data flywheel** (compounds with scale; strongest in serverless/mid-market): a de-identified cross-vendor threat signal seen at one customer protects all — the CrowdStrike pattern, which only a *neutral* player can spin.

## Why now
Agents are moving from "draft the answer" to "take the action" in production *this year*; EU AI Act high-risk obligations land Aug 2026; and YC itself has funded ~11 agent-security companies across the last six batches — the category is proven, the neutral + in-VPC seat is still empty.

## Proof it's real (not slideware)
Live enforcement across **two clouds** (AWS Bedrock + Azure) on one engine, behind both an SDK wrapper and a cloud connector; deterministic floor + shadow ML; tamper-evident audit shipping — built to design-partner readiness on pre-seed capital.

## Honest edges (we say these first)
- Inline blocking alone is **no longer** the differentiator — the combination is.
- The in-VPC/air-gapped editions and bounded rollback are **roadmap**; serverless enforcement is what's live.
- Latency today is ~0.6–1.2s on serverless (network round-trip); the sub-100ms **in-VPC local floor** is what closes it.
- Patent pending is a margin speed-bump, **not** a moat — we don't lead with it.

---
**The ask / next step:** `⟨FOUNDER: fund raise amount + what it buys — ~8-person team to in-VPC edition + first regulated design partners; keep consistent with STRATEGY §4.⟩`
