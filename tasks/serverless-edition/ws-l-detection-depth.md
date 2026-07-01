# WS-L — Detection Depth (ALL IN ONE: D1–D7 + distilled + heavy-tier + reclassify loop + multimodal)

> **Doc role:** This is the **workstream SCOPE** — boundary, dependencies, real `file:line` anchors, footguns, acceptance criteria. It is the **INPUT to this workstream's consolidated LLD** (`lld/31-detection-depth.md`, to be authored), *not* the granular task breakdown. Canonical order: HLD → LLD → tasks. See [00-index.md](00-index.md).

**Workstream:** WS-L (Serverless edition) — **Detection Depth, consolidated.** The single place that owns everything "depth": the D1–D7 layers, the distilled local model, the heavy-tier escalation model, the offline reclassify/retrain loop, and multimodal.
**Status:** Scope-stage. **SPIKE-GATED** (rides WS-0 / WS-C). LLD not yet authored — see *Authoring order* below.
**Owner:** TBD.

## Why this workstream exists (the gap it closes)
Depth-in-defense was **designed at the engine level** ([lld/20-defense-in-depth-layers.md](../../lld/20-defense-in-depth-layers.md) = D1–D7; [lld/19-ml-threat-classifier.md](../../lld/19-ml-threat-classifier.md) = the tiered Haiku/Sonnet/Opus models), but **no Serverless workstream carried it into the build plan** — WS-C owns the *scheduler mechanism*, WS-D owns the *decision-trail*, and the D1–D7 *layer nodes* + the distilled model (FR-3.12) + multimodal (FR-3.15) + the FR-3.14 reclassify loop had no owner. Separately, WS-B/[lld/30](../../lld/30-multiphase-contract.md) shipped the multi-phase *contract* but left the `content`/`output`/`memory` **detection handlers** ownerless (routed-but-stubbed → fail-secure DENY). WS-L is that owner for both — the depth pieces **and** the three phase handlers (content=D2, memory=D3, output=D5) — **consolidated in one place** (owner directives 2026-07-01).

## Consolidation contract (LLD 19 + LLD 20 → this workstream)
- **`lld/31-detection-depth.md` (to author) is the Serverless build-of-record** for all depth. It **consolidates** LLD 19 (tiered models) + LLD 20 (D1–D7) and elevates FR-3.12 to **P0**.
- **LLD 19 and LLD 20 are marked `superseded-for-Serverless by lld/31` with a forward pointer, retained as origin design** (traceability — do not delete or silently fork them; `propagate-change` discipline).

## Scope (all in one)
| Piece | Req | Priority (owner call) | Origin design to consolidate |
|---|---|---|---|
| **Distilled local model** | FR-3.12 | **P0** (Serverless latency lever; pairs with the WS-A local floor) | LLD 19 tiered strategy (new — no LLD today) |
| **Heavy-tier escalation model** | FR-3.2 | P0 | LLD 19 §3–4 (Haiku hot → Sonnet escalation → Opus offline) |
| **Offline reclassify-with-heavy-mode + retrain loop** | FR-3.14 | P0 | LLD 19 §4.3/§13.3 (Opus batch) + the lld/29 §6.6 feedback-store cross-ref (the gap it named) |
| **D1–D7 layers** | FR-3.5–3.11 | P0 build-wave (honest: P1/P2 in sub-PRD — see footgun) | LLD 20 §4–10 (all seven designed) |
| **Multimodal / image threat** | FR-3.15 | P0 build-wave | named, not yet designed |
| **Content-phase handler (D2 indirect / second-order injection)** | FR-3.5/3.6 | **P0** (owner call 2026-07-01) | LLD 20 D2 (taint-tag) — the real handler behind WS-B's `content` phase (lld/30) |
| **Memory-phase handler (D3 memory-integrity)** | FR-3.8 | **P0** (owner call 2026-07-01) | LLD 20 D3 — the real handler behind WS-B's `memory` phase (lld/30) |
| **Output-phase handler (D5 output-DLP)** | FR-3.7 | **later** (owner call — REDACT/rewrite is the harder piece; see footgun) | LLD 20 D5 — the real handler behind WS-B's `output` phase (lld/30) |

## Per-phase detection handlers (owner decision 2026-07-01 — WS-L owns them)
WS-B ([ws-b-multiphase-contract.md](ws-b-multiphase-contract.md) / [lld/30](../../lld/30-multiphase-contract.md)) ships the multi-phase **contract** — the additive `phase` field, the `KNOWN_PHASES` set, the `_CONTENT_FIELD` phase→content map, and the **"known-but-unimplemented → fail-secure DENY"** stub (`phase_handler_not_implemented:<p>`, lld/30 §3.2) — but explicitly **does not build the `content`/`output`/`memory` detection handlers** (lld/30 §1.3, non-goals). Those handlers had **no owner**; WS-L is the closest fit (they are detection depth) and now **owns all three**:
- **Content-phase handler → D2 (indirect / second-order injection).** Validates the untrusted data the agent *ingests* (retrieved docs, other tools' output, web text) carried in the `content_text` field for `phase=content`. **Priority: P0.**
- **Memory-phase handler → D3 (memory-integrity).** Validates a *write* to the agent's own memory store (`content_text`, `phase=memory`). **Priority: P0.**
- **Output-phase handler → D5 (output-DLP).** Validates data the agent *emits* (`content_text`, `phase=output`). **Priority: later** — its useful verdict is a server-side **REDACT / content-rewrite**, which needs the **PDP→PEP rewrite loop** the SDK decorator does *not* have today (it can only ALLOW/DENY, not hand back a masked payload — lld/29 §2.1(d), lld/30 out-of-scope). A DENY-only output handler is low value; the REDACT path is a separate, later deliverable.

Each handler **replaces WS-B's fail-secure stub** for its phase (the stub is the placeholder; the real handler is the fill). Until a handler lands, the phase stays routed-but-stubbed → DENY (fail-secure) — landing the handler is what turns that DENY into a real check.

## Dependencies
- **Depends on (GATE):** **WS-0** (measure-first spike) — depth rides the escalated/deep tier the spike measures; the AgentCore kill-check can reshape whether the deep-tier thesis holds. No build before the signed packet.
- **Depends on (contract):** **WS-C** — every D1–D7 layer + the model tiers **and the three phase handlers** register as **nodes** into WS-C's scheduler (node-registry, `cost_tier`, `depends_on` dependency-edge vocabulary). The content/memory/output detectors are **tier-1 nodes** with their own `cost_tier` + `depends_on`, exactly like the D1–D7 layers (D2→D4→D5 ordering already lives there). **WS-C's LLD must be authored BEFORE WS-L's** or WS-L guesses a contract it doesn't own. WS-C owns the *mechanism*; WS-L owns the *nodes* (the boundary WS-C's scope doc §"Shared" already states).
- **Depends on (phase contract):** **WS-B** ([lld/30](../../lld/30-multiphase-contract.md)) — WS-L's three phase handlers **consume** WS-B's phase contract: the `phase` field on `ValidationRequest`, the `_CONTENT_FIELD` phase→content-field map, and the `KNOWN_PHASES` set. Each handler is the real implementation that **replaces WS-B's "known-but-unimplemented → DENY" stub** (`phase_handler_not_implemented:<p>`) for its phase. lld/30 is the contract source; WS-L must not re-cut the `phase` field or the content map (additive-only, per lld/30 tie-breaker A).
- **Depends on:** the WS-E feedback store (redacted corpus the reclassify loop reads) + WS-F prompt-signature corpus (the retrain loop also feeds it).
- **Blocks:** the "deep enough to catch real attacks" §3 thesis of the HLD — the depth claim is unmet until these land.

## Read before coding (invariants to carry into the LLD)
1. **Nodes, not a parallel subsystem.** Every layer/model is a node in WS-C's DAG with a declared `cost_tier` + `depends_on`. **FOOTGUN:** do NOT hard-code `asyncio.gather` inside a layer — all parallelism is owned by the scheduler (WS-C scope doc footgun); a self-gathering layer re-introduces summed latency and bypasses the run-mode flag.
2. **Distilled model is the latency lever, not a new detector class.** FR-3.12's job is to classify the common case locally (<100ms) so the heavy hosted model runs only on edge cases — it pairs with the WS-A local floor. **On Serverless the distilled model runs server-side** (the stdlib-only SDK edge can't host a model — lld/29 §4/HLD §6.2(e) latency note); the at-edge distilled variant is the in-VPC/sidecar story, out of this slice.
3. **Dependency edges are real (D2→D4→D5).** Taint-tag (D2) → information-flow (D4) → output-DLP (D5) must run in order (LLD 20 §3.4); the scheduler expresses this, the layers declare it.
4. **The reclassify loop is offline / cold-path, never on `/v1/validate`** (LLD 19 §4.3). It re-scores stored **redacted** records (WS-E feedback store, gated by the §6.3 content-aware eval gate — no retrain on an unmeasured-quality corpus).
5. **Honest phasing inside "P0 build-wave":** the sub-PRD marks FR-3.5–3.11 as P1/P2 and FR-3.15 P1/P2. Treating the *workstream* as P0 means it's consolidated + designed now and first-wave-eligible; the LLD should still **sequence the layers** (distilled model + heavy-tier + reclassify first; D1–D7 as they mature) rather than claim all seven ship simultaneously. Don't anchor the build estimate on "7 layers + 2 models + a retrain pipeline, all at once."

## Authoring order (why the LLD isn't first in the queue despite P0)
"P0" = **build-wave** priority, not **authoring-order** priority. WS-L consumes WS-C's node contract, and both are spike-gated. Recommended LLD queue: non-spike-gated (**WS-H, WS-G, WS-F**) → then **WS-C → WS-L → WS-D** (ideally after the WS-0 packet signs, since the spike can reshape the deep-tier thesis). WS-L is registered P0 now so the gap is closed on paper; its LLD is authored once WS-C's scheduler contract exists.

## Acceptance criteria (workstream-level — refined when the LLD lands)
- [ ] `lld/31-detection-depth.md` authored, consolidating LLD 19 + LLD 20, FR-3.12 elevated to P0, review-lld APPROVE + rendered.
- [ ] LLD 19 + LLD 20 carry a `superseded-for-Serverless by lld/31` forward pointer (retained as origin design).
- [ ] Every layer/model defined as a WS-C DAG node (declared `cost_tier` + `depends_on`); no in-layer `asyncio.gather`.
- [ ] Distilled model (FR-3.12) design: model form, server-side placement, <100ms target, the hand-off to the heavy tier on low confidence.
- [ ] Heavy-tier escalation + the offline reclassify/retrain loop (FR-3.14) designed, reading the WS-E redacted feedback store through the §6.3 eval gate.
- [ ] D1–D7 layer designs consolidated with per-layer phasing; multimodal (FR-3.15) scoped.
- [ ] **Content-phase handler (D2 indirect/second-order injection)** designed + built (**P0**), replacing WS-B's `phase_handler_not_implemented:content` stub; registered as a WS-C DAG node (`cost_tier` + `depends_on`); consumes the lld/30 `phase` field + `_CONTENT_FIELD` map.
- [ ] **Memory-phase handler (D3 memory-integrity)** designed + built (**P0**), replacing WS-B's `phase_handler_not_implemented:memory` stub; registered as a WS-C DAG node; consumes the lld/30 contract.
- [ ] **Output-phase handler (D5 output-DLP)** scoped as a **later** deliverable (its REDACT/content-rewrite verdict needs the PDP→PEP rewrite loop the decorator lacks today — lld/29 §2.1(d) / lld/30 out-of-scope); until it lands, `phase=output` stays routed-but-stubbed → fail-secure DENY.
- [ ] Verdict-equivalence + latency-budget fit stated against WS-C's DAG (no summed latency).
- [ ] Cross-references: LLD 19, LLD 20, WS-B (lld/30 phase contract), WS-C, WS-E, WS-F, WS-0, HLD §6.2(c)/§3.

## Cross-references
- **Consolidates:** [lld/19-ml-threat-classifier.md](../../lld/19-ml-threat-classifier.md), [lld/20-defense-in-depth-layers.md](../../lld/20-defense-in-depth-layers.md).
- **Contract from:** [ws-c-dag-scheduler.md](ws-c-dag-scheduler.md) (node registry / cost-tier / dependency edges); [ws-b-multiphase-contract.md](ws-b-multiphase-contract.md) / [lld/30-multiphase-contract.md](../../lld/30-multiphase-contract.md) (the `phase` field + `_CONTENT_FIELD` map + the `phase_handler_not_implemented:<p>` stub the three phase handlers replace).
- **Consumes:** [ws-e-redaction.md](ws-e-redaction.md) (redacted feedback store), [ws-f-prompt-signatures.md](ws-f-prompt-signatures.md) (corpus loop).
- **Gated by:** [ws-0-measure-first-spike.md](ws-0-measure-first-spike.md).
- **HLD:** [hld/serverless-edition.md](../../hld/serverless-edition.md) §6.2(c) (the DAG that carries depth), §3 (the "deep enough" thesis).
