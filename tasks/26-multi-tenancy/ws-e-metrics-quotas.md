# WS-E: Tenant-Aware Metrics, Quotas & Platform-Admin Console

**Parent LLD**: [lld/26-multi-tenancy.md](../../lld/26-multi-tenancy.md) §9 (+ §5.5)
**Status**: 🟢 Code-complete (2026-06-24) — DONE: E1 `tenant_id` metric dimension (`metrics_publisher.py`); E2 `quota_service` + `quota_enforcement_enabled` flag **+ `QuotaExceeded{tenant_id}` metric on the RPS-denial path + `{prefix}-quota-exceeded` CloudWatch alarm** (`metrics_publisher.publish_quota_exceeded_metric`, `routes.py`, `monitoring_stack.py`); E3 `_platform` gate + `/v1/platform/tenants` endpoints **+ the §10 Q2 audit/consent gate is BUILT but PARKED** — the immutable audit ledger (`sentra-platform-audit-records`) always writes, but the deny-by-default 403 is gated behind `platform_read_consent_enforced` (**default OFF**, founder call 2026-06-24). While off, per-tenant reads are allowed + audited (`consent_state="false-unenforced"`); flip the flag to enforce. **LIVE-GATED, not executed:** E2 enforce soak + founder go-ahead before raising `max_validate_rps`; E1 cardinality-cost validation at target tenant count; per-tenant consent grants are a rollout step (default deny → Sentra-staff per-tenant detail reads 403 until a tenant opts in). **Naming note:** the shipped unverified/fallback metric is `IdentityFallback{State,tenant_id}` (WS-B B1), not the LLD's earlier `IdentityUnverified` — code is canonical; doc updated below.
**Owner**: TBD

## Dependencies

- **Depends on**: **WS-A** (the `tenant_id` dimension only becomes meaningful once identity is resolved per request) and **WS-D** (`sentra-tenants` registry for quota config + the `_platform` capability for the ops console).
- **Blocks**: nothing on the critical path. Can run in parallel with WS-C once A/D land.
- **Note**: WS-E is designed in the LLD but **not shown in the §7 rollout diagram** — it is deliberately deferred/parallel. Billing/metering rollup is explicitly out of scope (tracked in `pitch/share/STRATEGY.md`).

---

## Tasks

### E1 — Tenant-dimensioned metrics (LLD §9.1)

Once WS-A lands, all CloudWatch custom metrics gain a `tenant_id` dimension:

- `Decisions{tenant_id, verdict}`
- `ValidateLatency{tenant_id}`
- `IdentityFallback{State, tenant_id}` — residual-agent fallback window (WS-B B1); `State ∈ {opened, active, expired}`. (This is the as-built name; the LLD's earlier `IdentityUnverified` is superseded — `_unverified` is still the audit-bucket *tenant*, not a metric.)
- `QuotaExceeded{tenant_id}` — emitted once on a per-validate RPS quota denial (E2b); single `tenant_id` dimension; routed to the P1 `{prefix}-quota-exceeded` alarm on `alerts_topic` (commercial, not security-critical).

**Per-tenant dashboards become a filter, not a new pipeline.** Watch cardinality — `tenant_id` as a dimension multiplies metric streams; confirm CloudWatch custom-metric cost is acceptable at target tenant count, and consider EMF for high-cardinality emission.

### E2 — Quota enforcement (LLD §9.3)

Quota lives on the `sentra-tenants` row: `quota = {max_agents, max_validate_rps}`, keyed off `plan` (`trial|dedicated|enterprise`).

- **`max_agents`** — checked at **agent import** (cheap, low-frequency): count tenant's agents vs `max_agents`; reject import over cap.
- **`max_validate_rps`** — this is the hot path, so enforcement must not add a per-request hot partition:
  - **This is a NEW per-validate DDB write — not a reuse of the existing limiter.** The current per-session rate limiter is a read-modify-write on the session record (`session.get("abuse_counters")` in [abuse_detector.py](../../src/security-controller/app/validators/abuse_detector.py)), keyed per session, not per tenant. A per-tenant `max_validate_rps` adds a *tenant*-scoped counter the hot path does not have today. Budget for the extra write (latency + DDB cost) when deciding to build this.
  - Use a **write-sharded atomic DDB counter** (N shards per tenant; increment a random shard, sum on read) so the rate counter itself doesn't become a tenant-wide hot key.
  - **Fail-open on counter throttle**: if the counter read/write is throttled, allow the request — a quota counter must never become a denial-of-service on legitimate validate traffic. (Quota is a commercial guardrail, not a security boundary; security fail-secure is WS-A/B.)
  - **DONE** — emits a `QuotaExceeded{tenant_id}` metric on each RPS denial ([metrics_publisher.publish_quota_exceeded_metric](../../src/security-controller/app/utils/metrics_publisher.py), fired from [routes.py](../../src/security-controller/app/api/routes.py) before the `QUOTA_EXCEEDED` DENY) with a `{prefix}-quota-exceeded` CloudWatch alarm ([monitoring_stack.py](../../cdk/stacks/monitoring_stack.py)) — never a silent block.

> Implementation status: **built; the RPS counter + metric + alarm are wired but the counter stays off behind `quota_enforcement_enabled` on prod/staging (on for dev, inert until a tenant has a `max_validate_rps` and is in enforce).** Confirm with founder before raising a real ceiling — it may wait until there are paying tenants with contractual limits.

### E3 — Platform-admin (internal ops) console (LLD §5.5)

Sentra staff need a cross-tenant operational view no customer operator can see. Gated by the reserved **`_platform`** capability (WS-D), **not** a tenant role.

- **Scope**: tenants onboarded (count, plan, status, `created_at`); per-tenant threats blocked / validate volume / DENY rate; quota headroom (E2); credential health (active/revoked keys, agents pending first `/v1/validate`); onboarding funnel state.
- **Data path**: reads the tenant-dimensioned CloudWatch metrics (E1) + the `sentra-tenants` / `sentra-tenant-members` registries. **Aggregate, cross-tenant** queries are allowed **only** for `_platform` principals; every cross-tenant read is **audited** (LLD §6.3, §10 Q2).
- **Build**: a `_platform`-only, role-gated section of `web/console` (preferred — one codebase) rather than a separate app. Reuses the WS-C role-conditional rendering and the WS-D `GET /v1/me` capability check.
- **Compliance gate — BUILT, enforcement PARKED (founder call 2026-06-24):** the §10 Q2 audit/consent model is built but the deny-by-default 403 is gated behind `platform_read_consent_enforced` (**default OFF**). While off, per-tenant reads are *allowed* and audited (`consent_state="false-unenforced"`) so the platform console keeps working; flip `PLATFORM_READ_CONSENT_ENFORCED=true` to turn on enforcement. When enforced, the model is deny-by-default:
  - Each tenant carries `platform_read_consent` (bool, default `false`) on its `sentra-tenants` row; settable only by an `owner` or `_platform` operator via `PATCH /v1/tenants/{id}` ([tenant_service.set_platform_read_consent](../../src/security-controller/app/services/tenant_service.py), [tenancy_routes.update_tenant](../../src/security-controller/app/api/tenancy_routes.py)).
  - A **per-tenant** platform read (`GET /v1/platform/tenants/{id}`) **DENIES (403)** unless that tenant consented; enforcement runs in `_audit_platform_read` *before* any data fetch (no roster leak on denial).
  - An **aggregate** read (`GET /v1/platform/tenants`, target `*`) is `_platform`-only and needs no per-tenant consent, but is still audited.
  - Every access — ALLOW and DENY — writes an **immutable** record to `sentra-platform-audit-records` (PK target `tenant_id` / SK `{ms}#{uuid}`, RETAIN + PITR): `operator_sub, read_type, decision, consent_state, timestamp_ms` ([platform_audit.py](../../src/security-controller/app/services/platform_audit.py)).
  - **Rollout caveat**: default-deny means existing Sentra-staff per-tenant detail reads return 403 until each tenant opts in; the aggregate list is unaffected.

## Acceptance criteria

- [x] Custom metrics carry a `tenant_id` dimension (`Decisions`, `ValidateLatency`, `IdentityFallback`, `QuotaExceeded`); per-tenant dashboard is a filter. *(cardinality cost at target tenant count still to be validated — LIVE-GATED.)*
- [x] `max_agents` enforced at import; `max_validate_rps` via write-sharded counter, **fail-open on throttle**, with `QuotaExceeded` metric + `{prefix}-quota-exceeded` alarm. *(Counter stays off until founder raises a real ceiling.)*
- [x] Platform console is `_platform`-gated; cross-tenant reads audited (immutable `sentra-platform-audit-records`); non-`_platform` operators cannot reach it.
- [x] §10 Q2 (platform-admin access audit/consent) resolved + enforced — per-tenant reads deny-by-default without `platform_read_consent`; consent grants are the remaining rollout step.

## Cross-references

- LLD §9 (metrics/quotas), §5.5 (platform console), §6.3 (`_platform`), §10 Q2 (**resolved**: consent + immutable audit, see E3 above).
- Pairs with WS-C (shares role-gated console infra). Reads WS-D registries + WS-A identity.
- New table `sentra-platform-audit-records` (E3) — add to LLD §3 data-model inventory alongside `sentra-identity-fallback`.
