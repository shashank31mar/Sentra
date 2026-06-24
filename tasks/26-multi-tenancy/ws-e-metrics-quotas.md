# WS-E: Tenant-Aware Metrics, Quotas & Platform-Admin Console

**Parent LLD**: [lld/26-multi-tenancy.md](../../lld/26-multi-tenancy.md) §9 (+ §5.5)
**Status**: 🟡 Partial (2026-06-24) — DONE: E1 `tenant_id` metric dimension (`metrics_publisher.py`), E2 `quota_service` + `quota_enforcement_enabled` flag, E3 `_platform` gate + `/v1/platform/tenants` endpoints. PENDING: E1 cardinality-cost validation, E2 enforce soak, E3 §10 Q2 audit/consent compliance gate before cross-tenant reads ship.
**Owner**: TBD

## Dependencies

- **Depends on**: **WS-A** (the `tenant_id` dimension only becomes meaningful once identity is resolved per request) and **WS-D** (`sentra-tenants` registry for quota config + the `_platform` capability for the ops console).
- **Blocks**: nothing on the critical path. Can run in parallel with WS-C once A/D land.
- **Note**: WS-E is designed in the LLD but **not shown in the §7 rollout diagram** — it is deliberately deferred/parallel. Billing/metering rollup is explicitly out of scope (tracked in `pitch/STRATEGY.md`).

---

## Tasks

### E1 — Tenant-dimensioned metrics (LLD §9.1)

Once WS-A lands, all CloudWatch custom metrics gain a `tenant_id` dimension:

- `Decisions{tenant_id, verdict}`
- `ValidateLatency{tenant_id}`
- `IdentityUnverified{tenant_id|_unverified}`
- `IdentityMismatch{tenant_id}`

**Per-tenant dashboards become a filter, not a new pipeline.** Watch cardinality — `tenant_id` as a dimension multiplies metric streams; confirm CloudWatch custom-metric cost is acceptable at target tenant count, and consider EMF for high-cardinality emission.

### E2 — Quota enforcement (LLD §9.3)

Quota lives on the `sentra-tenants` row: `quota = {max_agents, max_validate_rps}`, keyed off `plan` (`trial|dedicated|enterprise`).

- **`max_agents`** — checked at **agent import** (cheap, low-frequency): count tenant's agents vs `max_agents`; reject import over cap.
- **`max_validate_rps`** — this is the hot path, so enforcement must not add a per-request hot partition:
  - **This is a NEW per-validate DDB write — not a reuse of the existing limiter.** The current per-session rate limiter is a read-modify-write on the session record (`session.get("abuse_counters")` in [abuse_detector.py](../../src/security-controller/app/validators/abuse_detector.py)), keyed per session, not per tenant. A per-tenant `max_validate_rps` adds a *tenant*-scoped counter the hot path does not have today. Budget for the extra write (latency + DDB cost) when deciding to build this.
  - Use a **write-sharded atomic DDB counter** (N shards per tenant; increment a random shard, sum on read) so the rate counter itself doesn't become a tenant-wide hot key.
  - **Fail-open on counter throttle**: if the counter read/write is throttled, allow the request — a quota counter must never become a denial-of-service on legitimate validate traffic. (Quota is a commercial guardrail, not a security boundary; security fail-secure is WS-A/B.)
  - Emit a `QuotaExceeded{tenant_id}` metric + alarm rather than hard-blocking silently.

> Implementation status: **designed, not yet sequenced.** Confirm with founder before building — it may wait until there are paying tenants with contractual limits.

### E3 — Platform-admin (internal ops) console (LLD §5.5)

Sentra staff need a cross-tenant operational view no customer operator can see. Gated by the reserved **`_platform`** capability (WS-D), **not** a tenant role.

- **Scope**: tenants onboarded (count, plan, status, `created_at`); per-tenant threats blocked / validate volume / DENY rate; quota headroom (E2); credential health (active/revoked keys, agents pending first `/v1/validate`); onboarding funnel state.
- **Data path**: reads the tenant-dimensioned CloudWatch metrics (E1) + the `sentra-tenants` / `sentra-tenant-members` registries. **Aggregate, cross-tenant** queries are allowed **only** for `_platform` principals; every cross-tenant read is **audited under both `_platform` and the target tenant** (LLD §6.3, §10 Q2).
- **Build**: a `_platform`-only, role-gated section of `web/console` (preferred — one codebase) rather than a separate app. Reuses the WS-C role-conditional rendering and the WS-D `GET /v1/me` capability check.
- **Compliance gate**: confirm the audit/consent model for Sentra staff accessing a customer tenant (SOC2 / customer contract) — LLD §10 Q2 is open; resolve before shipping cross-tenant reads.

## Acceptance criteria

- [ ] All four custom metrics carry a `tenant_id` dimension; per-tenant dashboard is a filter; cardinality cost validated.
- [ ] `max_agents` enforced at import; `max_validate_rps` via write-sharded counter, **fail-open on throttle**, with `QuotaExceeded` metric + alarm. (Gated on founder go-ahead.)
- [ ] Platform console is `_platform`-gated; cross-tenant reads dual-audited; non-`_platform` operators cannot reach it.
- [ ] §10 Q2 (platform-admin access audit/consent) resolved before cross-tenant reads ship.

## Cross-references

- LLD §9 (metrics/quotas), §5.5 (platform console), §6.3 (`_platform`), §10 Q2 (open: audit/consent model).
- Pairs with WS-C (shares role-gated console infra). Reads WS-D registries + WS-A identity.
