# Apple-to-Apple Competitor Rubric — the conflict test for VC outreach

**Purpose.** Before emailing any VC, verify (freshly, from the web) whether that fund backs a
company that competes with AegionAI. The blunt filter "backs *any* AI-agent-security company =
conflict" **over-counts** — the shortlist's own 2026-07-19 re-screen proved most "AI security"
bets are a *different plane* from ours. This rubric encodes the real test so the daily re-check
matches the curation logic and nothing drifts.

## What AegionAI actually is (the yardstick)
Neutral, cross-vendor **runtime action-governance**: a **deterministic floor** that checks the
*action itself* — exact **parameters** (amount > cap), **step sequence/ordering**, **caller
identity + authorization** — and **blocks it inline before it executes**, *plus* a probabilistic
detection layer on top, deployable **in-VPC / air-gapped**, across AWS/Azure/GCP/on-prem.

A portfolio company is a **true twin** only if it does inline **block-before-execute on the
action** with parameter/sequence/authz checks. One layer of our stack ≠ a twin.

## Verdicts (assign one per fund, with cited evidence)

> **POLICY = MODERATE (founder call, 2026-07-28).** Drop only a **true inline action-governance
> twin**. A **platform partial** that a VC *might* pattern-match as us but sits on a different
> plane (endpoint/content/posture/identity) is **CAUTION → KEEP and differentiate**, not a drop —
> this matches the shortlist's own "keep YL / Shield, lead with the 4 differentiators" calls.
> Two carve-outs still block a send: (a) an **unresolvable** portco (can't tell if it's a twin)
> and (b) the **fund's own decision-maker is the investor in an agent-security company** —
> both → `review_drop` (dropped from the auto-send list until the founder confirms/overturns the
> drop), NOT a silent keep and NOT a settled hard competitor-drop.

### 🔴 CONFLICT → DROP the fund (do not email)
The fund backs **a genuine inline action-governance twin** — deterministic policy on argument
values / authz / ordered steps that **blocks the action inline before it executes**. Known
twins: **Runlayer** (the one original direct-twin), **CodeIntegrity**, **Arcade**, **Operant
AI**, **Capsule**, **Dome Systems**, **Geordie**, **Neo** (neo.ai), **Acuvity**, plus any
**stealth/named "policy / enforcement / control plane for AI agents"** listing that confirms
inline block-before-execute on the action.

### 🟠 review_drop → DROPPED but rescue-able (surface to founder to confirm/overturn)
- **Unresolvable twin** — a stealth/opaque portco you *can't confirm* is or isn't a true twin
  (e.g. a "#"-linked stealth "security for computer-use agents"). Fail-secure: don't send blind.
- **Contact-is-the-investor** — the fund's decision-maker (your intended recipient) is personally
  the backer of an AI-agent-security company (e.g. Acrew's Kraynak → Nokod/Kanopy + Protect AI).
  Pitching them competes with their own bet regardless of that bet's twin-status.

### 🟡 CAUTION → KEEP, but name the daylight in the email
The fund backs an **adjacent** bet on a genuinely **different plane** — fundable, but the first
email must pre-empt the comparison ("they secure the data / test for vulns / verify identity —
we govern and block the *action*, inline, across every cloud"). Adjacent categories + examples:
- **Content / prompt classifiers:** Lakera, Prompt Security, Lasso, Aiceberg.
- **Posture / DSPM / data-security:** Matters.AI, Aurva, Protecto.
- **Identity (WHO, not WHAT — explicitly complementary):** Keycard, Scalekit, Aembit, Entra
  Agent ID, Okta, CyberArk. *(Identity is a partner, not a rival — do not down-rank for it.)*
- **Red-team / pentest:** Repello, SplxAI, Astra, FireCompass, Terra Security.
- **Off-path SOC / SIEM / AIDR / fraud:** Manifold, CloudSEK, AIStrike, Miggo (ADR), RunReveal,
  Difenz, Charm Security.

### 🟢 CLEAN → KEEP
No AI-security / agent-security bet at all, or only the complementary-identity kind.

## How to check each fund (deep, apple-to-apple)
1. Pull the fund's **live portfolio page** + recent (last ~12 mo) funding announcements — VCs add
   bets constantly, so **trust fresh web data over any cached list**.
2. For every security/AI-security-looking portco, read what it actually does and classify it
   against the yardstick above — **inline action-block = twin; single-layer = adjacent.**
3. Assign the fund the **most severe** verdict any single portco earns (one twin ⇒ CONFLICT).
4. **Cite evidence** — company name + one line on what it does + the source URL. Date it.
5. **Fail-secure:** if you cannot resolve whether a portco is a true twin, treat the fund as
   CONFLICT and flag `review_drop` — never send on an unresolved conflict.
