# LLD 37 — SDK local-floor caching: interpreter + signed-bundle client (WS-A deferred)

> **STATUS: STUB / PLANNED — not yet authored to implementation depth.** This file exists so the
> many `[LLD 37]` join-key links in [LLD 36](36-sdk-release-and-local-floor-seam.md) resolve and so
> the LLD index can carry the row. The **authoritative design source until this is written** is the
> committed plan [tasks/serverless-edition/ws-a-local-floor-caching-plan.md](../tasks/serverless-edition/ws-a-local-floor-caching-plan.md)
> (Gate-3 approved 2026-07-03, decisions D1–D4). **Do not build from this stub** — it is a placeholder,
> not a spec.

**Version**: 0.1 (stub)
**Last Updated**: 2026-07-03
**Status**: PLANNED — deferred build (founder call 2026-07-03: write LLD-36 ship-now first; author + build this LLD as a separate gate, reasonably sequenced behind WS-F/G/H)
**Prerequisites**: [LLD 36](36-sdk-release-and-local-floor-seam.md) (the released SDK + the frozen no-op seam this fills) · [LLD 28](28-cedar-policy-engine.md) (WS-I bundle-emit + the differential corpus oracle) · [LLD 26 §3.6](26-multi-tenancy.md) (the `revoked-since` revocation-epoch pattern reused) · [LLD 24](24-latency-optimization.md) (the latency budget this closes)

## 1. Purpose (what this LLD will specify when authored)

lld/37 **fills the no-op seam** LLD 36 froze — it turns `_local_floor_verdict` from a `return None`
into a real in-process evaluator. It owns the SDK-side **interpreter + signed-bundle client + signing-key
verify/lifecycle + the durable edge meter journal**. [LLD 28](28-cedar-policy-engine.md) (WS-I) owns the
**emitter + corpus oracle**; WS-J owns the **differential gating runner**; WS-H owns the **hosted meter
ledger** this LLD's journal flushes into.

## 2. Scope when authored (the deferred work — from the approved plan)

The full outline + locked decisions are in
[ws-a-local-floor-caching-plan.md](../tasks/serverless-edition/ws-a-local-floor-caching-plan.md). In brief:

- **The closed-subset interpreter** (`local_floor.py`) — pure-Python, stdlib-only evaluation of the
  closed non-Cedar subset (literal tool allow/deny, integer-cents param bounds with `deny_on_missing`,
  agent-allow, single-session sequence, prompt-signature `re` patterns, egress host/path/port match-table).
  Unrecognized construct / no-bundle → **ESCALATE, never local-ALLOW** (the structural allowlist⇒escalate
  guarantee from [LLD 28 §5.3](28-cedar-policy-engine.md)).
- **The signed-bundle client** (`bundle_poll.py`) — background poll (conditional GET + ETag→304,
  keep-last-good), **verify-before-swap** (JWT sig + per-file SHA-256).
- **Staleness / epoch / anti-rollback** (D2) — `MAX_STALENESS_BOUND=300s` / `REFRESH_CADENCE=60s` from a
  **monotonic clock**; stale-past-bound → deny-by-default; revocation-epoch as the cross-restart anchor;
  reject `bundle_version <= highest_seen`.
- **Crypto** (D1) — the `[local-floor]` extra (pure-python `ecdsa` ES256 verify-only, lazy-imported so
  base `dependencies=[]` holds; missing extra ⇒ floor OFF ⇒ fail-secure to hosted).
- **Cold-start disk persistence** (D3) — persist last-good bundle + `highest_seen_version`, verify-on-load.
- **The durable edge meter journal** (D4, founder "meter everything, period") — fsync'd on-disk journal of
  every local verdict, flushed on the poll into WS-H's idempotent `PutItem attribute_not_exists(request_id)`
  ledger; crash-replay + dedup = effectively-once, zero evaluated events lost.

## 3. The seam this fills (from LLD 36 — the frozen contract)

- `LocalFloorVerdict = {LOCAL_ALLOW, LOCAL_DENY, ESCALATE, DENY_BY_DEFAULT}` — frozen public enum ([LLD 36 §4.2.1](36-sdk-release-and-local-floor-seam.md)).
- `local_floor_enabled` flag — off = network-required (hosted); on-without-interpreter = fail-secure to hosted. lld/37 flips the shipped default to per-tenant `true` once the interpreter lands ([LLD 28:394-397](28-cedar-policy-engine.md) semantics).
- `_local_floor_verdict(self, payload) -> Optional[Decision]` — internal hook; lld/37 translates the enum to a `Decision` **inside** the method (LOCAL_ALLOW→ALLOW, LOCAL_DENY→DENY; ESCALATE/DENY_BY_DEFAULT→`None` so the caller routes to `_send`) and **never** returns the bare enum (fail-open guard, `test_seam_returns_decision_or_none`). Bundle/epoch/staleness/meter state live on `self`, not in the signature.
- **Async restructure** — lld/37 moves the interpreter run **off the event loop** (into the `to_thread` worker) and owns the contextvars-propagation + exception-ordering equivalence tests for that change (LLD 36 kept the async path byte-identical precisely so this restructure is lld/37's, with its own proof).

## 4. Cross-references (stub)

- **Implements:** FR-1.7 (the in-process local floor — the caching that fills LLD 36's seam), FR-2.9 (egress match-table, interpreter side), NFR-1 (≤500 ms p99 deterministic), NFR-3 (enforce-during-outage), NFR-4 (fail-secure), NFR-12 (metering integrity — the durable journal).
- **Decisions:** ADR-029 (In-Process Local Enforcement via Signed Policy Bundle — this is the *fill*; LLD 36 was the *plug*), ADR-031 (`DenyOverrides.combine()` untouched), ADR-032 (redactor-before-floor ordering), ADR-033 (durable meter pipeline — WS-H).
- **Shared contracts:** the bundle wire schema + `corpus/cedar_differential.jsonl` ([LLD 28](28-cedar-policy-engine.md)); `LocalFloorVerdict` + `local_floor_enabled` + `_local_floor_verdict` ([LLD 36](36-sdk-release-and-local-floor-seam.md)); `sentra-meter-events` durable ledger (WS-H).
- **Upstream:** [HLD §6.2(a)](../hld/serverless-edition.md) (Option A signed-bundle local floor).
- **Sibling refs:** [LLD 36](36-sdk-release-and-local-floor-seam.md) (the seam), [LLD 28](28-cedar-policy-engine.md) (emitter/corpus), [LLD 24](24-latency-optimization.md), [LLD 26 §3.6](26-multi-tenancy.md) (revocation-epoch), WS-I / WS-J / WS-H.
- **Reconcile-on-author:** [tasks/serverless-edition/ws-h-metering.md:71](../tasks/serverless-edition/ws-h-metering.md) — its "edge beacon carries only volume / NOT no-miss" stance holds only for coarse volume-band telemetry once D4's durable per-decision journal lands; reconcile when this LLD is authored (per the plan's D4 flag).
