---
name: brief
description: Load project context at session start WITHOUT bloating the main thread. Dispatches a subagent to read the canonical docs (HLD/LLD/PRD/best-practices) and return a compact digest. Use instead of manually asking Claude to read a pile of docs.
allowed-tools: Read, Grep, Glob, WebSearch, WebFetch, Agent, Task
---

# /brief — Cheap context bootstrap

Goal: get the context you need for a session **without** dragging full docs into the main conversation, where every later turn re-bills them as cache-read.

## How it works
Do NOT read the large docs into this thread. Instead dispatch the `doc-reader` subagent (pinned to Sonnet — cheap, and pure reading needs no Opus) and have IT read them. Only its digest returns here. If `doc-reader` isn't available in this Claude Code version, dispatch any read-only subagent and pass `model: sonnet`.

The user may name a topic (e.g. `/brief network sidecar`) — if so, scope strictly to it.

Default doc set when NO topic is given (keep it small):
- `CLAUDE.md` (project rules + LLD authoring standards)
- The HLD / `design-hld.md`, `adr.md`, `flow.md` if present
- `PRD` / vision / strategy docs if the task is product-facing

**Do NOT read `lld/` by default** — there are 25+ LLDs, several 60–100KB; reading them all defeats the purpose and blows the subagent's context. Pull a specific LLD only when the user names it or the HLD points to it for the task.

## Subagent instructions to pass
"Read <doc set>. Return a digest of ≤400 lines:
1. One-paragraph purpose per doc.
2. Key decisions, invariants, named components, APIs, data models.
3. Cross-references and any contradictions between docs.
4. Open questions / TODOs / `Status: Draft` markers.
Quote `file:line` for anything I'd need to jump to. Do NOT paste full sections."

## After the digest returns
Summarize in ≤10 lines what's loaded and ask what we're doing. Pull the rest only on demand. The reading subagent always runs on Sonnet; the user never has to pick a model.
