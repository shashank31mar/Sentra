# WS-N — Read-route auth + tenant-scoping (close the 21 ungated read gaps)

> **Doc role:** Phase-2 **build-task doc** (granular, zero-ambiguity). Follow-on to **WS-M** ([ws-m-authz.md](ws-m-authz.md)); derives from **[lld/39](../../lld/39-authz-rbac-edge-authorizer.md)** + the **2026-07-07 route audit**. WS-M gated the *mutating* routes; WS-N gates the *read* routes WS-M's Invariant-6 deliberately left as "data-plane reads carry no role" — the audit proved 21 of them carry **neither auth nor tenant scope** and read the ambient `default` partition.

**Parent LLD:** [lld/39-authz-rbac-edge-authorizer.md](../../lld/39-authz-rbac-edge-authorizer.md) (§2 three planes, §5 in-service boundary). **Parent HLD:** [hld/serverless-edition.md](../../hld/serverless-edition.md) §6.2(f)/§6.3.
**Status:** TASKS-DONE (build-ready) · **Owner:** TBD · **Last updated:** 2026-07-07
**Implements:** FR-10.1 (multi-tenant isolation — extended to reads) · FR-13.1 (multi-tenant console, no cross-tenant leak) · FR-13.3 (console auth). **Decision:** consumes **ADR-037** (in-service boundary) + the WS-M `resolve_operator_tenant`/`OperatorContext`/`assert_owns` primitives; **no new ADR** — this is the *operator-read* mirror of WS-M's *operator-mutate* gating (Invariant 6 governed RBAC roles on data-plane *agent* reads; it never sanctioned unauthenticated operator reads — the audit found that was an unintended coverage gap, not a designed exemption).

> **⚙️ FOUNDER MANDATE (2026-07-07):** *"Every API has to have auth and be tenant based. One customer should never be able to see/do anything for another customer, period."* Model: **customer operator → authenticated + STRICTLY scoped to their own tenant; platform operator (`is_platform`) → cross-tenant fleet view (audited).**

---

## 1. Dependencies

- **Depends on (all BUILT + live — reuse, do not rebuild):**
  - `resolve_operator_tenant` ([deps.py:374](../../src/security-controller/app/api/deps.py#L374)) — verifies ALB-OIDC, resolves membership, and **already calls `set_current_tenant(chosen.tenant_id)` at [deps.py:435](../../src/security-controller/app/api/deps.py#L435)** before returning `ctx`. This is the load-bearing fact: **adding `Depends(resolve_operator_tenant)` auto-binds the request tenant** for every downstream store call that routes through `tenancy.query_or_scan()`/`item_key()` on a tenant-composite store.
  - `OperatorContext{sub, email, role, tenant_id, is_platform}` ([deps.py:269](../../src/security-controller/app/api/deps.py)).
  - `assert_owns(ctx, ResourceKind, resource_id)` ([ownership.py](../../src/security-controller/app/api/ownership.py)) — for by-id reads (AGENT/POLICY/CONNECTION/SESSION/CONVERSATION).
  - `tenancy.fleet_scan(table, **kw)` ([tenancy.py:343](../../src/security-controller/app/utils/tenancy.py#L343)) — the genuine cross-tenant scan; the **platform-view path**.
  - `_audit_platform_read(ctx, target_tenant, what)` ([tenancy_routes.py:381](../../src/security-controller/app/api/tenancy_routes.py#L381)) — the audited cross-tenant read gate (`"*"` = aggregate/allowed+audited; `<id>` = per-tenant, consent-gated). **Every platform cross-tenant read MUST call this.**
- **Blocks:** **WS-G** (the console render-gate + multi-tenant demo assume these reads are tenant-isolated; WS-G's D10/D11 prerequisite IS this workstream).
- **Shared (coordinate edits — WS-M/WS-D/WS-G touch too):** `routes.py`, `deps.py` (WS-M owns; WS-N only ADDS `Depends` params to read handlers — do not touch WS-M's mutating gates), the 3 service methods in M-N2.

---

## 2. Model — read before coding

### 2.1 The two operator classes (the whole design)

```mermaid
flowchart TD
  OP(["operator (ALB-OIDC verified)"]) --> RT["resolve_operator_tenant deps.py:374<br/>→ OperatorContext{tenant_id, is_platform}<br/>set_current_tenant(ctx.tenant_id) @ :435"]
  RT --> Q{"is_platform?"}
  Q -->|"NO — customer operator"| CUST["STRICT single-tenant read<br/>store auto-scopes on current_tenant()<br/>(tenant-composite PK/GSI)"]
  Q -->|"YES — platform/Sentra staff"| PLAT["cross-tenant FLEET view<br/>fleet_scan() + _audit_platform_read(ctx,'*',what)"]
  CUST --> DATA[("only THIS tenant's rows")]
  PLAT --> FLEET[("all tenants — audited")]
```

### 2.2 Invariants (load-bearing)

1. **Every read route authenticates.** No route reaches a store without `Depends(resolve_operator_tenant)` (or the data-plane `_dataplane_tenant_bind` for the two agent-facing session reads). The ONLY exemptions are `/health` (liveness) and the already-correct routes.
2. **Customer operator = STRICT own-tenant.** A non-platform `ctx` reads only `ctx.tenant_id`'s rows. **A customer must never see another customer's data — no header, no query param, no path can override this** (`X-Aegion-Tenant` for a non-platform operator is re-validated against membership and 403s a non-member — [deps.py:340](../../src/security-controller/app/api/deps.py) — it can NEVER select a foreign tenant).
3. **Platform operator = fleet view, ALWAYS audited.** Cross-tenant reads go through `fleet_scan()` + `_audit_platform_read(ctx, "*", "<what>")`. A platform read that isn't audited is the bug.
4. **Bind-only where the store is tenant-composite; service-change only where it hard-uses `fleet_scan`.** Do NOT add redundant tenant filters to a store that already composites on `current_tenant()` — it's noise and risks double-scoping. Do NOT leave a `fleet_scan`-backed route bound to nothing — that's the current leak.
5. **Fleet dashboards are DUAL-MODE, not hard-bound.** The 3 M-N2 routes (`/sessions`, `/metrics/overview`, `/metrics/platform-distribution`) are fleet-wide *by design for a platform operator*. Naively binding them to `ctx.tenant_id` for everyone would **break the platform/founder dashboard**. They take `tenant_id: Optional[str]=None` → customer passes `ctx.tenant_id` (scoped); platform passes `None` (fleet_scan + audit).

### 2.3 FOOTGUNS (do NOT do X — it breaks Y)

- **FG-1 — do NOT hard-bind the 3 fleet routes to `ctx.tenant_id` unconditionally.** `SessionManager.query_sessions` ([session_manager.py:555](../../src/security-controller/app/utils/session_manager.py#L555)), `count_sessions_by_status` ([:692](../../src/security-controller/app/utils/session_manager.py#L692)), `AgentService.get_cloud_provider_distribution` ([agent_service.py:243](../../src/security-controller/app/services/agent_service.py#L243)) **currently call `fleet_scan()`**. Binding them single-tenant for everyone silently breaks the platform fleet dashboard. Make them dual-mode (M-N2).
- **FG-2 — do NOT add a tenant filter inside a service that already uses `query_or_scan()`/`item_key()`.** Those auto-scope on `current_tenant()`, which `resolve_operator_tenant` already set. Adding a second filter is redundant and can double-compose the key → zero rows. These are **bind-only** (M-N1).
- **FG-3 — Sigma rules are fleet-global, NOT tenant-partitioned** (confirmed: `sentra-sigma-rules-metadata` has no `{tenant}#` PK — [lld/35 §13](../../lld/35-prompt-signatures.md)). `GET /v1/sigma-rules` + `/content` get `Depends(resolve_operator_tenant)` for **authentication only** — do NOT add a tenant filter (every tenant legitimately sees the same fleet rules). This is the one auth-yes/tenant-scope-no exception (Invariant 1 satisfied; Invariant 2 N/A — no tenant-owned data).
- **FG-4 — the console will NOT break.** It runs behind ALB `authenticate-cognito`; the ALB injects `x-amzn-oidc-data` on every request, which `resolve_operator_tenant` reads. But **tests + local dev MUST provide the ALB header** (`_alb_claims_override`, [deps.py](../../src/security-controller/app/api/deps.py)) or they 401. A curl without the header now correctly 401s.
- **FG-5 — by-id reads need `assert_owns`, not just a bind.** A bind scopes a *list* query; a by-id `get_item` on a tenant-composite PK also auto-scopes, BUT for defense-in-depth + an honest 404 (not a cross-tenant 200), the by-id reads (M-N3) call `assert_owns(ctx, kind, id)` — mirrors WS-M's mutating by-id pattern.
- **FG-6 — CloudWatch-Logs-backed routes** (`/logs`, `/logs/conversation/{id}`, `/metrics`, `/metrics/decisions-timeseries`) do NOT read DynamoDB — no composite PK auto-scope. For a **customer** operator these MUST scope the Logs-Insights query string by `ctx.tenant_id` (or the tenant-stamped field), not rely on a bind. Verify the query is tenant-filtered; if the log group is fleet-shared, add the `filter tenant_id = "<ctx.tenant_id>"` clause (mirror `rollback_coordinator._query_conversation_tenant_sync`). Do NOT ship a customer Logs read that returns fleet rows.

### 2.4 Route classification (from the 2026-07-07 audit — the work-list)

| Class | Fix | Routes |
|---|---|---|
| **M-N1 bind-only** (DDB composite auto-scopes) | + `Depends(resolve_operator_tenant)` | `/decisions`(2), `/sessions/{id}/decisions`(3), `/agents`(7a), `/policies`(8a), `/connections`(9a) |
| **M-N2 dual-mode** (hard-uses `fleet_scan` today) | + `Depends` + service `tenant_id: Optional` param | `/sessions`(4), `/metrics/overview`(5b), `/metrics/platform-distribution`(5d) |
| **M-N3 by-id** (bind + ownership) | + `Depends` + `assert_owns` | `/agents/{id}`(7b), `/agents/{id}/tools`(7c — global tool registry, bind-only, no assert_owns), `/policies/{id}`(8b), `/connections/{id}`(9b), `/logs/conversation/{id}`(1b) |
| **M-N4 CloudWatch reads** (scope the query string) | + `Depends` + tenant-filter the Logs query for customer | `/logs`(1a), `/metrics`(5a — deprecated, still gate), `/metrics/decisions-timeseries`(5c) |
| **M-N5 discovery** (policy-derived read-model) | + `Depends` (confirm tenant-scoping of the source) | `/discovery/agents`(6a), `/discovery/summary`(6b), `/discovery/platforms`(6c) |
| **M-N6 fleet-global (auth-only)** | + `Depends` ONLY, no tenant filter (FG-3) | `/sigma-rules`(10), `/sigma-rules/{id}/content` |

---

## 3. Milestones → tasks

### Milestone N0 — the reusable platform-dual-mode helper (LAND FIRST)

**N0.1 — `_operator_read_scope(ctx, what)` helper** in `routes.py` (new, near `_dataplane_tenant_bind`). Returns the tenant to scope to, and audits a platform fleet read:
```python
def _operator_read_scope(ctx: OperatorContext, what: str) -> Optional[str]:
    """Resolve the read tenant for an operator read.
      * customer operator  -> ctx.tenant_id (STRICT own-tenant; already bound by
        resolve_operator_tenant @ deps.py:435, returned here for explicit service calls)
      * platform operator  -> None (fleet view) + audited via _audit_platform_read(ctx,'*',what)
    A customer NEVER gets None (never a fleet view)."""
    if ctx.is_platform:
        _audit_platform_read(ctx, "*", what)   # aggregate cross-tenant, audited
        return None                             # None => fleet_scan in the dual-mode services
    return ctx.tenant_id
```
- **Unit** (`tests/test_read_route_scope.py`): `test_customer_scope_returns_own_tenant`, `test_customer_scope_never_none` (assert a non-platform ctx never yields None even with `is_platform` spoofed absent), `test_platform_scope_returns_none_and_audits` (spy `_audit_platform_read` called with `"*"`), `test_platform_audit_records_what`.
- **Integ:** N/A (pure helper — exercised by every M-N2 integ test; stated opt-out).

### Milestone N1 — bind-only routes (5) — `Depends(resolve_operator_tenant)`

**N1.1 — add the dep to each M-N1 route** (`routes.py`): `scan_decisions`(:574), `get_session_decisions`(:450), `get_agents`(:1236), `get_policies`(:1347), `list_connections`(:952). Add `ctx: OperatorContext = Depends(resolve_operator_tenant)` to each signature. No service change (FG-2 — store auto-scopes on the now-bound `current_tenant()`). For a **platform** operator these stay single-tenant on the operator's own tenant unless they use the dual-mode routes; that's acceptable (these 5 are not the fleet dashboards).
- **Unit** (`tests/test_read_route_authz.py`, one block per route): `test_<route>_missing_oidc_401` (no ALB header → 401), `test_<route>_binds_ctx_tenant` (spy `current_tenant()` inside the service call == `ctx.tenant_id`), `test_<route>_customer_sees_only_own_tenant` (seed tenant-A + tenant-B rows; ctx=A; assert only A rows returned — the anti-cross-tenant proof).
- **Integ** (`tests/integration/test_read_route_isolation.py`): `test_decisions_cross_tenant_isolation` — real store (moto), tenant-A operator scanning `/decisions` sees zero tenant-B decisions. (This seam — operator-read × tenant-composite store — is the shared contract WS-N owns; ≥1 integ test required.)

### Milestone N2 — dual-mode fleet routes (3) — bind + service `tenant_id` param

**N2.1 — `SessionManager.query_sessions`** ([session_manager.py:555](../../src/security-controller/app/utils/session_manager.py#L555)): add `tenant_id: Optional[str] = None`. When `tenant_id` is not None → `tenancy.query_or_scan()` scoped to it; when None → keep `fleet_scan()` (platform). Route `get_sessions`(:640): add `Depends`, call with `tenant_id=_operator_read_scope(ctx, "sessions.list")`.
**N2.2 — `SessionManager.count_sessions_by_status`** ([:692](../../src/security-controller/app/utils/session_manager.py#L692)): same `tenant_id: Optional` param + same fleet_scan/query_or_scan branch. Called by `/metrics/overview`.
**N2.3 — `AgentService.get_cloud_provider_distribution`** ([agent_service.py:243](../../src/security-controller/app/services/agent_service.py#L243)): add `tenant_id: Optional`. None → full scan (platform); set → single-tenant. Route `get_platform_distribution`(:783) + `get_metrics_overview`(:717): add `Depends`, pass `_operator_read_scope(ctx, ...)`.
- **Unit** (`tests/test_dualmode_reads.py`): per method — `test_<m>_customer_scoped_to_tenant` (tenant_id set → query_or_scan, NOT fleet_scan — spy which path), `test_<m>_platform_fleet_scan_when_none` (tenant_id None → fleet_scan), `test_metrics_overview_customer_excludes_other_tenant` (seed A+B; ctx=A customer → counts reflect only A), `test_metrics_overview_platform_sees_fleet` (ctx=platform → counts reflect A+B + `_audit_platform_read` called).
- **Integ** (`tests/integration/test_read_route_isolation.py`): `test_sessions_customer_isolation_platform_fleet` — moto: customer-A `/sessions` → only A; platform `/sessions` → A+B (audited). Shared-contract seam (fleet_scan dual-mode) — required.

### Milestone N3 — by-id reads (5) — bind + `assert_owns`

**N3.1** (`routes.py`): `get_agent`(:1275) + `assert_owns(ctx, AGENT, agent_id)`; `get_policy_by_id`(:1416) + `assert_owns(POLICY, id)`; `get_connection`(:979) + `assert_owns(CONNECTION, id)`; `get_conversation_timeline`(:1858) + `assert_owns(CONVERSATION, conversation_id)`. `get_agent_tools`(:1304) → bind-only (tool registry is global — no assert_owns; FG-3-adjacent, note it). All get `Depends(resolve_operator_tenant)`.
- **Unit** (`tests/test_read_route_authz.py`): per route `test_<route>_missing_oidc_401`, `test_<route>_foreign_id_404` (ctx=A, id owned by B → 404 via assert_owns, NOT a 200 leak), `test_<route>_own_id_ok`.
- **Integ:** `test_by_id_read_cross_tenant_404` — moto, A requests B's policy/agent/connection id → 404.

### Milestone N4 — CloudWatch-Logs reads (3) — bind + tenant-filter the query (FG-6)

**N4.1** (`routes.py`): `get_logs`(:395), `get_metrics`(:674 deprecated but gate it), `get_decisions_timeseries`(:795) get `Depends(resolve_operator_tenant)`. For a **customer** operator, the Logs-Insights / CloudWatch query MUST filter by `ctx.tenant_id` (verify the log records carry a tenant field; if the metric namespace is per-tenant, scope by dimension). For a **platform** operator → `_operator_read_scope` returns None → fleet (unfiltered) + audited. **Verify** each service's query is tenant-filterable; if a log group is genuinely fleet-shared with no tenant field, that's a flagged gap (record it — do NOT ship a customer read returning fleet rows).
- **Unit** (`tests/test_cloudwatch_read_scope.py`): `test_logs_customer_query_filters_tenant` (assert the built query string contains the tenant filter for a customer ctx), `test_logs_platform_no_filter_audited`, `test_metrics_timeseries_customer_scoped`.
- **Integ:** N/A hermetic (CloudWatch not moto-backed) — **stated opt-out**; covered by the unit query-string assertions + a note in the go-live runbook to verify live.

### Milestone N5 — discovery reads (3) — bind + confirm source scoping

**N5.1** (`routes.py`): `discovery_agents`(:821), `discovery_summary`(:848), `discovery_platforms`(:855) get `Depends(resolve_operator_tenant)`. **Verify** the discovery read-model source: if it's derived from tenant-scoped connections/scans, scope to `ctx.tenant_id`; if it's a static/global cache with no tenant data, bind-only for auth (note which). Discovery reflects a tenant's own imported agents → should be tenant-scoped.
- **Unit** (`tests/test_read_route_authz.py`): `test_discovery_agents_missing_oidc_401`, `test_discovery_agents_customer_scoped` (if source is tenant-scoped), `test_discovery_summary_tenant_scoped`.
- **Integ:** folded into `test_read_route_isolation.py` if the source is tenant-scoped; else stated opt-out (static global).

### Milestone N6 — fleet-global auth-only (2) — `Depends` ONLY (FG-3)

**N6.1** (`routes.py`): `get_sigma_rules`(:1661), `get_sigma_rule_content`(:1795) get `Depends(resolve_operator_tenant)` for **authentication only** — NO tenant filter (rules are fleet-global; every tenant sees the same set).
- **Unit** (`tests/test_read_route_authz.py`): `test_sigma_rules_missing_oidc_401`, `test_sigma_rules_authed_returns_fleet_rules` (any authenticated tenant → same full rule set; assert NOT tenant-filtered).
- **Integ:** N/A (no tenant-owned data / no cross-tenant seam — stated opt-out per FG-3).

### Milestone N7 — the systemic read-coverage gate (extend WS-M's M0.2)

**N7.1** — extend `tests/test_authz_coverage_gate.py` (WS-M's enumerator) to assert **every GET route** on `routes.py`+`tenancy_routes.py` carries an auth dependency (`resolve_operator_tenant` OR `_dataplane_tenant_bind` OR `require_platform`) OR is on a reasoned allowlist (`/health`; the 2 agent-facing `_dataplane_tenant_bind` reads). A new ungated GET fails the build — the systemic guard so this gap can't silently reopen.
- **Unit:** `test_all_read_routes_have_auth_dep`, `test_read_gate_accepts_dataplane_bind`, `test_read_allowlist_requires_reason`.
- **Integ:** N/A (static analysis — stated opt-out, mirrors WS-M M0.2).

---

## 4. Error model

| Condition | Response |
|---|---|
| No/invalid ALB-OIDC on a read route | **401** `verify_alb_oidc` raises (customer-safe) |
| Customer operator, foreign `X-Aegion-Tenant` (non-member) | **403** (`resolve_operator_tenant` membership re-validate) |
| Customer operator, by-id read of foreign resource | **404** via `assert_owns` (never a cross-tenant 200) |
| Platform operator cross-tenant read | 200 fleet data + `_audit_platform_read(ctx,"*",what)` row written |
| Platform per-tenant read without consent (if ever added) | **403** `platform_read_consent not granted` (existing pattern) |

---

## 5. Acceptance criteria (one checklist)

- [ ] **N0:** `_operator_read_scope` helper lands; customer→own-tenant, platform→None+audit; a customer never yields None.
- [ ] **N1:** the 5 bind-only reads carry `Depends(resolve_operator_tenant)`; a customer sees only their tenant's rows (cross-tenant scan returns zero foreign rows).
- [ ] **N2:** the 3 fleet routes are dual-mode (`tenant_id: Optional` on `query_sessions`/`count_sessions_by_status`/`get_cloud_provider_distribution`); customer=scoped, platform=fleet_scan+audited; the platform/founder dashboard still shows the fleet.
- [ ] **N3:** the 5 by-id reads carry `Depends` + `assert_owns` (foreign id → 404, not a 200 leak).
- [ ] **N4:** CloudWatch reads gated + tenant-filter the query for a customer (or a flagged gap recorded if a log group has no tenant field).
- [ ] **N5:** discovery reads gated + scoped to the tenant's own source (or noted global).
- [ ] **N6:** sigma-rule reads gated for auth, NOT tenant-filtered (fleet-global, FG-3).
- [ ] **N7:** the systemic gate fails the build on any new ungated GET route.
- [ ] **No customer can read another customer's data on ANY of the 21 routes** — proven by the cross-tenant isolation integ tests (the founder mandate, objectively verified).
- [ ] **The console is not broken** — verified: every route the console calls returns 200 for an authenticated operator (ALB header present).
- [ ] **unit tests pass** (covering all cases named in §3).
- [ ] **integration tests pass** (covering the operator-read × tenant-composite-store seam + the dual-mode fleet seam — `tests/integration/test_read_route_isolation.py`).

---

## 6. Cross-references

- **This ws's LLD:** [lld/39](../../lld/39-authz-rbac-edge-authorizer.md) §2 (three planes), §5 (in-service boundary). *(WS-N extends §2 Plane-1 coverage from mutating to read routes — a candidate lld/39 §2.4 amendment or a short lld/41 if the founder wants it design-doc'd; this task doc is buildable as-is.)*
- **Sibling refs (sweep verifies consistency):** **WS-M** ([ws-m-authz.md](ws-m-authz.md) — owns `resolve_operator_tenant`/`assert_owns`/the coverage gate WS-N extends; shared files `routes.py`/`deps.py`) · **WS-G** ([ws-g-console.md](ws-g-console.md) — the console consumer; WS-N is its D10/D11 prerequisite) · **WS-D** ([ws-d-decision-trail.md](ws-d-decision-trail.md) — owns `/trail`+`/signals`, already `_dataplane_tenant_bind`-scoped; WS-N does not re-home them) · **WS-H** ([ws-h-metering.md](ws-h-metering.md) — metrics/usage source; coordinate the `/metrics/overview` dual-mode change).
- **Shared contract WS-N owns:** *operator-read tenant scope* — every read route resolves its tenant via `resolve_operator_tenant` (customer) or `fleet_scan`+`_audit_platform_read` (platform). Consumers: WS-G (console), WS-H (usage reads).
