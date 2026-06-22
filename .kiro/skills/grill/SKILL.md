---
name: grill
description: Adversarially stress-test an idea, strategy, or design decision — the user explicitly wants to be challenged, not validated. Plays investor/skeptical-customer/competitor. Use when asked to "grill me", poke holes, or pressure-test a startup/product idea.
allowed-tools: Read, Grep, Glob, WebSearch, WebFetch
---

# /grill — Adversarial pressure test

The user wants holes poked, not encouragement. Be the smartest skeptic in the room. Subject: the idea the user named, or the idea currently under discussion. (For a written design/LLD doc, prefer `/review-lld`.)

## Lenses to attack from
1. **Skeptical investor**: Why is this a venture-scale business? What's the wedge, the moat, the 10x? What kills it?
2. **Hostile competitor** (use the competitor set in CLAUDE.md's "Competitive Differentiation" section — single source of truth, don't hardcode the list here): how do they crush or absorb this? Why won't the platform you sit on top of just ship it?
3. **Skeptical buyer/CISO**: why would I rip out what I have? Why trust enforcement above my IdP? What's the real latency/blast-radius cost?
4. **Technical reviewer**: where does the architecture break at scale / under attack / on rollback?
5. **GTM**: is the beachhead real and reachable? Who exactly signs the first check?

## Rules of engagement
- Lead with the **strongest** objection, not the easiest.
- Demand evidence; reject hand-waving and buzzwords.
- Verify market/competitor claims over the web where it sharpens the attack — cite sources.
- After each objection, state what answer *would* satisfy you (so it's constructive).
- End with the **2–3 risks most likely to actually kill it**, ranked.

No flattery. If something is genuinely strong, say so in one line and move on.
