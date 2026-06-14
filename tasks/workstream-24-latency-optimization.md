# Workstream 24: `/v1/validate` Latency Optimization

**Status**: v0.2 — M1 instrumentation + M2 singleton landed in code (deploy + re-baseline pending); M3+ pending
**Owner**: Founder + 1 backend engineer
**Start Date**: TBD (post-review)
**LLD Reference**: [lld/24-latency-optimization.md](../lld/24-latency-optimization.md) (v1.0)

---

## Overview

`/v1/validate` runs at **~2.5s average** in dev (pre-singleton baseline). Root cause is **not** the order of the cheap validators — it is (1) the ML classifier running live with Haiku + Sonnet escalation up to a 2.5s budget on every request, stacked on top of (2) a per-request `ValidationService()` construction that rebuilt ~10 boto3 clients and **defeated the Sigma rule cache** (12 S3 reads/request) — **now fixed by the singleton (M2)**, (3) uncached policy S3 reads (**×3** — STEP 2 Cedar / STEP 4 context / STEP 5 abuse), and (4) audit/metrics blocking the response.

**Goal:** deterministic path **≤ 500ms p99**; ML-hot path **≤ 900ms p99**; ML-with-escalation bounded ≤ 2.5s. No change to ML verdict behavior — ML is **reordered to last only**; deeper ML latency work is a tracked follow-up.

### Success Criteria
- [ ] Deterministic-path p99 ≤ 500ms (measured via M1 timing).
- [ ] ML-hot p99 ≤ 900ms.
- [ ] **Zero change** in ALLOW/DENY outcomes vs. a recorded baseline set (verdict regression guard).
- [ ] Sigma rule cache survives across requests (0 S3 reads on warm path) — *already true post-singleton; verify in M1*.
- [ ] No per-request boto3 client/resource construction.

### Guardrails (from best-practices.md + LLDs)
- Do **not** add `asyncio.gather` to the validator pipeline (best-practices §14.3 / deferred to WS20.0). `to_thread` per-call offloading is allowed.
- CloudWatch dual-write is **mandatory** (§12.5) — make it async, do not remove it.
- Keep the DDB signal-store write prompt (SOC console reads within minutes, LLD 17 §2).
- ML stays **enabled** (founder decision 2026-05-30). Reorder only.

---

## Milestones & Tasks

### M1 — Instrument first (measurement) — *do before any fix*
> **Singleton (M2 / 2.1+2.2) already landed**, so this baseline is taken against **post-singleton** code — the historical ~2.5s predates it. Re-confirm R1/R3/R8 status here.
- [x] 1.1 Add `time.perf_counter()` spans per pipeline step in `_run_validation_pipeline`; emit one structured `validation.timing` log. **Done in `validation_service.py`** (contextvar `_step_timings` + `_timed()` wrapping session/policy/sigma/ml/context/abuse/handle); deploy to capture the breakdown.
- [ ] 1.2 Capture a per-step before-breakdown **serial AND N-concurrent** (state RPS/concurrency with the numbers — F6 only shows under concurrency).
- [ ] 1.3 Pull CloudWatch ML metrics: Haiku latency, **Sonnet escalation rate**, ML p99. Confirm ML vs sigma split.
- [ ] 1.4 Record a baseline **final-verdict** set (inputs → ALLOW/DENY), **ML-on traffic included**, for the regression guard — assert on final verdict, not signal-set.
- **Exit:** documented before-number (serial + concurrent) + escalation rate; verdict baseline captured.

### M2 — Singleton service + client registry (F1) — *partially DONE*
- [x] 2.1 Construct `ValidationService` once in `app/main.py` `lifespan`; store on `app.state`. **DONE.**
- [x] 2.2 Route `/v1/validate` resolves the singleton from `app.state` (`ValidationService()` is test-fallback only). **DONE.**
- [ ] 2.3 Introduce a boto **client registry** (tenant-keyed factory; returns shared default today). Validators take clients from it instead of `boto3.client/resource` in `__init__`.
- [ ] 2.4 Warm **system** sigma rules + tool-requirements in `lifespan` (policy stays lazy-on-first-request; do not pre-load every tenant's policy).
- [ ] 2.5 Concurrency check: confirm the shared singleton + clients are safe under load (boto3 clients are thread-safe; validators hold no per-request mutable state).
- **Exit:** 0 per-request constructions ✅; sigma cache persists ✅; re-measure in M1.

### M3 — Sigma + Policy caches (F2/F3)
- [ ] 3.1 Sigma cache → process/module-scoped, **tenant-aware** (system + customer rule sets).
- [ ] 3.2 **Write-through** on rule CRUD (sync DDB + cache update) + **cross-instance invalidation** — `meta#version` row in `sentra-sigma-rules-metadata` (bumped on CRUD, keep `status='stable'` consistent) or Redis pub/sub.
- [ ] 3.3 Add `SIGMA_RULES_CACHE_TTL_SECONDS` (new env var; not currently set) → 6h safety net. Remove orphan `SIGMA_REFRESH_INTERVAL`.
- [ ] 3.4 Parallel cold-load of rule S3 objects (`gather` over `to_thread` — fan-out within one step, allowed; LLD §1.2.1).
- [ ] 3.5 **Policy: cache on `resolve_policy_bundle(agent_id)`** (choke point for all 3 loads) — request-scoped memo + short TTL via the **existing WS5 cache framework** (`policy_cache_ttl_seconds`); wire dead `POLICY_CACHE_TTL_SECONDS`; remove orphan `POLICY_CACHE_TTL`.
- [ ] 3.6 Verify all **3** policy call sites (STEP 2 Cedar, STEP 4 context, STEP 5 abuse) hit the cache.
- [ ] 3.7 **(was M5)** Move `config/tool_requirements.yaml` → per-tenant write-through store, reusing 3.1/3.2 machinery. *Feature, not a latency win — done here only because it shares the cache plumbing.*
- **Exit:** deterministic-path p99 ≤ 500ms (at documented concurrency).

### M4 — ML reorder + telemetry async + to_thread (F4/F5/F6)
- [ ] 4.1 Move ML classifier to the **end** of the pipeline (after context + abuse). Preserve deny-overrides/signal semantics.
- [ ] 4.2 Audit + metrics → fire-and-forget (`asyncio.create_task`) **with a retained task-set + done-callback logging exceptions** (bare create_task can be GC'd / swallow errors). Keep CloudWatch dual-write; keep DDB write prompt. Fix the false "fire-and-forget" comment in `_handle_deny`; normalize deny/allow audit↔metrics order.
- [ ] 4.3 Wrap remaining sync boto3 hot-path calls in `asyncio.to_thread` (per-call offload, not pipeline gather; LLD §1.2.1).
- [ ] 4.4 Verdict guard passes — assert on **final ALLOW/DENY only**, not signal-set (ML-last legitimately drops ML signals on cheap-denied requests).
- **Exit:** ML-hot p99 ≤ 900ms; fewer ML invocations (cheap checks short-circuit first).

### M5 — Tenant sequence rules (F8, data-model) — *pulled forward into M3.7*
Per founder call (2026-06-14), this is done **right after M3 core** because it reuses M3's write-through tenant-cache machinery (tracked as **M3.7**). It is a **feature** (customer-defined sequence rules), **not** a latency win — the singleton already removed the per-request YAML read.
- [ ] 5.1 CRUD + system/customer split for sequence rules.
- [ ] 5.2 Migrate the static `tool_requirements.yaml` content as the seed "system" rule set.

### M6 — ML latency deep-dive (deferred ML work) — *revisit after re-measure*
- [ ] 6.1 Evaluate risk-gated ML (run ML only on money-movement / low-trust / borderline).
- [ ] 6.2 Evaluate narrowing the [0.5, 0.9] Sonnet-escalation band (measure escalation rate from M1.3).
- [ ] 6.3 Evaluate Haiku-inline + Sonnet-async for low-risk.
- **Note:** no change until M1–M4 land and we re-measure. Long-term execution model = parallel DAG ([LLD 20 §3.4 / WS20.0](../lld/20-defense-in-depth-layers.md)).

### M7 — Durable telemetry shipper (long-term)
- [ ] 7.1 App writes structured audit/metrics to stdout/append-file.
- [ ] 7.2 Shipper sidecar (Fluent Bit / OTel Collector / CloudWatch agent) → CloudWatch + metrics.
- [ ] 7.3 Verify compliance durability (no audit loss on crash) vs. current in-memory fire-and-forget.

---

## Dependencies & Risks
- **Concurrency:** the singleton is the one structural change — validators must be stateless per request (verify in M2.5).
- **Multi-instance cache coherence:** M3.2 invalidation is essential — a stale security rule across tasks is a correctness risk, not just a perf one.
- **Verdict drift:** ML reorder and caching must not change outcomes — M1.4 baseline + M4.4 guard.
- **Interaction with WS20.0 DAG:** ML-last (M4.1) is the frontier-first interim; do not pre-build the DAG here.
