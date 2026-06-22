---
name: write-doc
description: Draft or extend an HLD/LLD/vision/pitch doc following the project's authoring standards (concrete mechanisms, mermaid flow diagrams, the LLD template, cross-doc consistency). Plans first, writes to a file on approval, edits incrementally after. Use when asked to write or expand a design/product doc.
---

# /write-doc — Author docs the project's way

Topic / target: what the user names; if unclear, ask before drafting.

## Workflow (matches the user's spark → plan → doc → review loop)
1. **Plan first, don't write yet.** Propose an outline + the key decisions the doc must lock down. Get a thumbs-up before drafting. Use plan mode if the scope is large.
2. **Then write to the file** (not into chat). For a new LLD, follow the template in `CLAUDE.md` (Overview → Architecture → APIs → Data Models → Config → Error Handling → Monitoring → Cross-References), version/status header included.
3. **Revise with Edit, never full rewrites** — saves output tokens and avoids re-reading the whole doc each turn.

## Standards (non-negotiable, from project memory + CLAUDE.md)
- **Be specific**: concrete mechanisms, real field/endpoint names, actual data shapes — no vague "the system handles X".
- **Mermaid flow diagrams** for any non-trivial flow; verify the syntax renders.
- **Pseudo-code, not production code** — conceptual level; real impl lives in `/src`, `/cdk`.
- **Concise**: aim 500–1000 lines, hard cap 2000; split if larger.
- **Cross-doc consistency**: when you add an endpoint/component, note which sibling docs (HLD, ADR, flow, demo, PRD) also need updating — list them at the end.
- Align every doc to the Vision + PRD; flag anything that drifts.

## Don't
Reproduce the finished doc back into chat — point to `file:line`. Keep chat replies terse.
