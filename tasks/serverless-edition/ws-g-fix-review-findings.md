# WS-G Console — Fix pass (review findings from the built UI)

> **Doc role:** Phase-2 **fix-task doc** for `code-loop`. Closes the 22 code-verified findings from the 2026-07-09 deep review of the built `web/console` vs lld/40 + ws-g-console.md + the canvas mockups. Every finding was adversarially re-verified against actual code (0 false positives). **Parent LLD:** [lld/40](../../lld/40-multi-tenant-console.md). **Frontend stack:** React 19 + Vite + TanStack Query + Tailwind + React Router; tests = Vitest + Testing Library (`web/console`). Backend (any prereq) = pytest under `src/security-controller`.

> **Baseline (verified 2026-07-09):** `web/console` `tsc -b` clean; **37 test files / 118 tests pass**. The spine is sound (org-first machinery, RBAC map exact, D3 parity real, platform tree gated). These fixes close contract/degrade/wiring gaps — **none is an auth breach** (the server boundary holds in every case), but several break the spec render-gate contract, a canvas view, or leave built machinery dead.

> **Invariants to hold (do NOT regress):** client RBAC render-gate is UX-only, server `require_role`/`require_platform` is the boundary; tenant is server-derived (never a client filter); near-real-time POLL, never streaming; missing-role HIDES a control (fail-secure); an absent dep API DEGRADES to a PARTIAL/roadmap state, never a dead control or a fabricated body. Keep `tsc -b` + `vitest run` green; every behavior change gets a real (non-vacuous) test that fails if the behavior regresses.

---

## Milestone FX-1 — HIGH (5): spec-contract + dead-machinery + canvas-flagship

### FX-1.1 — Gate the Sigma enable/disable toggle on `usePlatformCan('sigma.retire')` (dead PlatformCapability machinery)
- **Touches:** `web/console/src/features/policies/PolicyLibraryPage.tsx:286-317` (`SigmaRuleRow`); `web/console/src/lib/query/useMe.ts:38` (`usePlatformCan`, currently ZERO call sites).
- **Fix:** wrap the enable/disable toggle render in `usePlatformCan('sigma.retire')` — HIDE it for non-platform operators (mirrors server `require_platform` on `PATCH /sigma-rules/{id}`). A tenant admin must NOT see a fleet-global kill-switch they can't use. Import `usePlatformCan` (do not use `useCan` — `sigma.retire` is a `PlatformCapability`, not in the `Capability` union).
- **Footgun:** do NOT add `sigma.retire` to the `Capability`/`MIN_ROLE` map (breaks the exhaustive `Record` + the D3 parity gate) — it gates on `is_platform`, not a `TenantRole`.
- **Unit:** `PolicyLibraryPage.sigmaGate.test.tsx` — `is_platform:false` → toggle absent; `is_platform:true` → toggle present + fires `toggle.mutate`.

### FX-1.2 — Bind Decision-detail to the WS-D `/sessions/{id}/trail` (not legacy `/decisions`)
- **Touches:** `web/console/src/features/forensics/DecisionDetailPage.tsx:37`, `web/console/src/components/decisions/DecisionTrace.tsx:167`, `web/console/src/lib/api/sessions.ts` (add `trail`), `web/console/src/types/api.ts` (add `SessionTrail`).
- **Fix:** add `sessionsApi.trail(sessionId, requestId)` → `GET /v1/sessions/{id}/trail?request_id=` (LIVE per lld/40 v1.4, `routes.py:566`), returning the four coverage buckets (ran / ran-ABSTAIN / ran-ERROR / not-run) + recomputed `winning_source` + `block_point`. Add the `SessionTrail` type to match the server envelope. Bind Decision-detail to it; keep the legacy client-reconstruction only as the PARTIAL fallback on 404/501 (never blank).
- **Footgun:** do NOT keep the legacy `/decisions` client-side pipeline reconstruction as the primary — the whole point is the server's recomputed trail.
- **Unit:** `DecisionDetailPage.trail.test.tsx` — binds `/sessions/{id}/trail`, renders the 4 buckets + winning_source; on 404 → PARTIAL banner + DecisionTrace fallback (not blank).

### FX-1.3 — Session forensics: render the session-summary header from `SessionInfo`
- **Touches:** `web/console/src/features/forensics/SessionForensicsPage.tsx:14-33`; reuse `sessionsApi.list`/`SessionInfo` (`lib/api/sessions.ts`).
- **Fix:** fetch the session via `sessionsApi` and render the summary header the canvas Decision-Trail mockup centers on: trust score (trajectory), total/allow/deny counts + deny rate, quarantine status badge, `created_at`/`last_activity` timeline, and the ordered tool-call sequence, above the existing `DecisionTrace`. (Release action only if `useCan('quarantine.manage')`.)
- **Unit:** `SessionForensicsPage.test.tsx` — renders trust score + deny counts + quarantine badge from a seeded `SessionInfo`; Release control hidden for a `viewer`.

### FX-1.4 — Map agent ECS status → canvas Active/Idle/Offline (client mapper)
- **Touches:** `web/console/src/features/agents/AgentInventoryPage.tsx:93-95`, `web/console/src/types/enums.ts:21` (`AgentStatus`), new `web/console/src/features/agents/activityStatus.ts`.
- **Fix:** the server emits ECS states (`running`/`starting`/`stopped`/`not_found`/`unknown` — `agent_service.py:636/666/680/691-696`), NOT the canvas enum. Add a mapper: `running`→Active, `stopped`/`not_found`→Offline, `running`-but-no-recent-traffic→**Idle** (never show `unknown` as Active — map to a neutral "Unknown"). Fix the `AgentStatus` type to reflect the real server contract + the mapped activity label; render the mapped value + `STATUS_COLOR`.
- **Footgun:** do NOT keep the type asserting `'active'|'idle'|'quarantined'|'inactive'` as if the server returns those — it lies about the contract.
- **Unit:** `agents/__tests__/activityStatus.test.ts` — `running`→Active, `stopped`/`not_found`→Offline, `running`+no-traffic→Idle, `unknown`→Unknown (NOT Active). Fixtures use REAL ECS values.

### FX-1.5 — Platform Fleet Overview: build the fleet KPI grid + fleet decisions-timeseries (G4.5)
- **Touches:** `web/console/src/features/platform/FleetOverviewPage.tsx:38-88`; reuse `useOverview`/`useDecisionsTimeseries` + `KpiGrid`/`AllowedVsBlockedChart` (already wired into the customer `OverviewPage`).
- **Fix:** bind `useOverview()` + `useDecisionsTimeseries()` in fleet mode (server auto-aggregates for `is_platform` via `_operator_read_scope` → `tenant_id=None`, audited) and render `KpiGrid` + `AllowedVsBlockedChart` above the tenant grid — the fleet aggregate the §6.11 view-set (a) mandates.
- **Unit/Integ:** `features/platform/__tests__/fleetMetrics.integration.test.tsx` (the named-but-absent acceptance test) — fleet KPI tiles + allowed/blocked chart render from the fleet-mode endpoints; no `X-Aegion-Tenant` header sent.

---

## Milestone FX-2 — MEDIUM: security-adjacent + correctness (close before pilot)

### FX-2.1 — Read/bootstrap-path membership-403 fail-safe (clear binding → org page)
- **Touches:** `web/console/src/lib/http.ts:177-188`; `web/console/src/lib/tenant.ts` (`clearActiveTenant`), `orgEntry.ts` (`ORG_PAGE_PATH`).
- **Fix:** on a **403** from a READ (esp. the `/v1/me` bootstrap — a stale/corrupted `sessionStorage['aegion.activeTenant']` fails `deps.py:440` membership check), call `clearActiveTenant()` and bounce to `ORG_PAGE_PATH` (per lld/40 §C.4 "absent/lost value fails SAFE → org page"). Distinguish a *bound-tenant* 403 (clear + re-org) from a *role* 403 on a mutation (toast, per FX-2.4) — key off whether the failing request is a read/bootstrap vs a gated mutation.
- **Footgun:** do NOT treat every 403 as a reauth (that's 401's job at :177) and do NOT clear the binding on a *mutation* role-403 (that's a legit "you lack the role", not a bad tenant).
- **Unit:** `http.membership403.test.ts` — a 403 on `/v1/me` clears `aegion.activeTenant` + redirects to `ORG_PAGE_PATH`; a 403 on a mutation does NOT clear the binding.

### FX-2.2 — Gate `PolicyEditorPage` Save/Create on `policies.write` (deep-linkable)
- **Touches:** `web/console/src/features/policies/PolicyEditorPage.tsx:243` (submit `Button`), `router.tsx:63-64` (unguarded route).
- **Fix:** hide/disable the submit for an operator without `useCan('policies.write')` (editor), and guard the route. The page is reachable by deep-link today with no role check.
- **Unit:** `PolicyEditorPage.gate.test.tsx` — `viewer` sees no Save/Create (or disabled + blocked); `editor` can submit.

### FX-2.3 — Fix the platformApi `X-Aegion-Tenant` invariant (make it code-enforced, not environmental)
- **Touches:** `web/console/src/lib/api/platform.ts:15-21`, `web/console/src/lib/http.ts:161` (`tenantHeader()` spread).
- **Fix:** platformApi calls MUST NOT attach `X-Aegion-Tenant` even if a tenant is ambiently set — add an explicit `{ omitTenant: true }` option to the http layer (or a platform-specific fetch path that never spreads `tenantHeader()`). Today the invariant holds only *because* a platform op happens to have no active tenant — that's luck, not enforcement.
- **Footgun:** the current `platform.test.ts` is circular (it `clearActiveTenant()`s in `beforeEach` then asserts absence) — rewrite it to SET an active tenant and assert platformApi STILL sends none.
- **Unit:** `platform.tenantHeader.test.ts` — with an active tenant set, `platformApi.listTenants()` sends NO `X-Aegion-Tenant`.

### FX-2.4 — MutationCache: surface the sanitized 403 message (no-op toast today)
- **Touches:** `web/console/src/lib/query/queryClient.ts:29` (no-op toast), `degrade.ts:30`.
- **Fix:** wire the real sanitized-message toast through the central `MutationCache`/`QueryCache` `onError` path (currently `handleAuthDegrade(err, qc, () => {})` drops the message; only the `['auth','context']` invalidation fires). Pass the actual toast fn.
- **Unit:** `queryClient.degrade.test.ts` — a real 403 through the cache path fires `toastError` with the sanitized message (assert against the WIRED cache, not an injected `vi.fn()`).

### FX-2.5 — Confine a platform operator to the platform tree (symmetric root-split)
- **Touches:** `web/console/src/app/AppLayout.tsx:9-29` (customer tree, only `RequireBoundTenant` today), `router.tsx` root.
- **Fix:** add a landing redirect so an `is_platform` operator hitting `/` or a customer route is sent to `/platform` (the exclusive root split lld/40 §3.1 frames — "a platform operator never sees a customer route"). Today a platform op mounts the full customer shell.
- **Unit:** `app/__tests__/platformConfinement.test.tsx` — an `is_platform` op at `/overview` redirects to `/platform`; a customer op at `/platform` still 403s/redirects (existing behavior, keep).

### FX-2.6 — G2.8 demoted-operator-on-window-focus test (mechanism exists, test missing)
- **Touches:** `web/console/src/lib/query/useMe.ts:26` (`refetchOnWindowFocus:true`, already set); new `useMe.refetch.test.tsx`.
- **Fix:** add the named acceptance test — window focus triggers `meApi.get` refetch; a role change admin→viewer hides a previously-shown control on re-render (fail-secure demotion, §2 rule 5). No source change; the behavior is untested.
- **Unit:** `useMe.refetch.test.tsx` as named above.

---

## Milestone FX-3 — MEDIUM: canvas-fidelity + honest-degrade (batch)

### FX-3.1 — Threats per-detector `winning_source` facet (G3.2) — needs a backend field too
- **Touches:** `web/console/src/features/threats/ThreatsPage.tsx:20-24`, `types/api.ts:150-165` (`DecisionItem` — no `winning_source`). **Backend prereq:** `GET /v1/decisions` (`scan_decisions`) must return `winning_source` per row (it exists on `SessionDecision.combined` but not the list shape).
- **Fix:** add a facet by deciding source driven from the API's `winning_source` values (NOT a FE constant). If the backend field-add is deferred, ship the facet as PARTIAL/disabled with a note — do NOT hardcode the source list.
- **Owner note:** the `winning_source`-on-`/decisions` field-add is a **backend task** (WS-N/WS-M-backend class, `decisions_service.py`); the facet UI is WS-G. If backend not done this cycle, FX-3.1 UI degrades to PARTIAL.
- **Unit:** `ThreatsPage.facet.test.tsx` — facet options derived from response `winning_source` values; absent field → PARTIAL, no crash.

### FX-3.2 — Relabel 'Live'/'Streaming' → 'near-real-time (≤15s pull)'
- **Touches:** `web/console/src/features/overview/LiveActivity.tsx:52,55`, `OverviewPage.tsx:49,80`.
- **Fix:** replace "Live"/"Streaming"/"Real-time … telemetry" with "near-real-time (≤15s pull)" (the routed `ActivityPage.tsx:46` already does this correctly — match it). Data is a 15s TanStack poll, not push.
- **Unit:** `OverviewPage.label.test.tsx` — no "Streaming"/"Live" literal; asserts the near-real-time label.

### FX-3.3 — Policy Detail: Cedar/JSON tabs degrade to PARTIAL when no compiled body (stop fabricating)
- **Touches:** `web/console/src/features/policies/PolicyDetailPage.tsx:74,140-151`, `web/console/src/features/policies/policyFormat.ts:110-163` (`renderCedar` fabricates a synthetic `permit/forbid`).
- **Fix:** YAML tab stays LIVE (default to YAML). Cedar/JSON tabs render the compiled body ONLY when `cedar_content` is present; when null → a PARTIAL/roadmap state, NEVER a client-fabricated `permit(...)/forbid(...)` body. Do not default `lang='cedar'` when it's synthetic.
- **Unit:** `PolicyDetailPage.format.test.tsx` — compiled present → Cedar renders it; compiled absent → Cedar tab shows PARTIAL, no fabricated body.

### FX-3.4 — Platform fleet grid: send `limit/cursor/sort/filter` (backend paging is landed but unreachable)
- **Touches:** `web/console/src/features/platform/FleetOverviewPage.tsx:39`, `lib/query/usePlatform.ts:5-10`, `lib/api/platform.ts:16`, `TenantGrid.tsx`.
- **Fix:** wire the paging/sort/filter params (backend `tenancy_routes.py:629-715` supports `limit`(50)/`cursor`/`sort`/`filter` + returns a next-page cursor). At minimum advance the cursor so the fleet isn't silently truncated to page 1; ideally expose sort (blocks_24h/trust/created_at) + facet filters (plan/status/identity_mode).
- **Unit:** `FleetOverviewPage.paging.test.tsx` — advancing the pager sends the cursor; sort/filter change re-queries with the param.

### FX-3.5 — Consent column: back it or don't imply a state (platform_list_tenants omits the field)
- **Touches:** `web/console/src/features/platform/TenantGrid.tsx:16-24,75-77,121` (`ConsentPill`). **Backend option:** `tenancy_routes.py:665-675` (`platform_list_tenants` row dict) could project `tenant.platform_read_consent` (it's on the DETAIL route only).
- **Fix:** either (a) project `platform_read_consent` onto each list row (backend, small), OR (b) render the Consent state as "—/unknown" until drill-down, NOT a universal amber "required". A governance console must not falsely show "consent required" for every tenant.
- **Owner note:** (a) is a WS-N/WS-M-backend field-add; (b) is pure WS-G. Prefer (b) now (honest), (a) as follow-up.
- **Unit:** `TenantGrid.consent.test.tsx` — a row without `platform_read_consent` renders "unknown"/neutral, NOT "required".

### FX-3.6 — Render quota-headroom (G4.4) — computed + tested but never shown
- **Touches:** `web/console/src/features/platform/fleetRank.ts:67-78` (`quotaHeadroom`, zero call sites), `FleetOverviewPage.tsx` / `TenantDetailPage.tsx:88-89` (dumps raw `JSON.stringify(t.quota)`).
- **Fix:** surface `quotaHeadroom()` in the platform view (per-tenant `quota.max_agents`/`max_validate_rps` vs usage) — the §6.11 view-set (a) requires it; today the pure fn passes its unit test while no view uses it.
- **Unit:** `TenantDetailPage.quota.test.tsx` — renders the headroom value from `quotaHeadroom`, not raw JSON.

---

## Acceptance
- [x] FX-1.1 sigma toggle gated on `usePlatformCan` (hidden for non-platform) · FX-1.2 `/trail` bound + `SessionTrail` type + PARTIAL fallback · FX-1.3 session header from `SessionInfo` · FX-1.4 ECS→activity mapper + honest type · FX-1.5 fleet KPI grid + timeseries + named integ test.
- [x] FX-2.1 read-403 fail-safe (clear+org bounce) · FX-2.2 PolicyEditor gated · FX-2.3 platformApi omits tenant header (code-enforced + non-circular test) · FX-2.4 sanitized 403 toast wired · FX-2.5 platform-op confined to platform tree · FX-2.6 window-focus demotion test.
- [x] FX-3.1 threats facet (PARTIAL if backend field absent) · FX-3.2 near-real-time relabel · FX-3.3 Cedar/JSON PARTIAL-degrade (no fabrication) · FX-3.4 fleet paging params sent · FX-3.5 consent column honest · FX-3.6 quota-headroom rendered.
- [x] `tsc -b` clean; `vitest run` green; every new test is non-vacuous (fails if the behavior regresses).
- [x] No regression to the green baseline (37 files/118 tests) or the verified-correct spine (org-first machinery, RBAC map, D3 parity, platform gate).

## Cross-references
- **Parent:** [lld/40](../../lld/40-multi-tenant-console.md) (§5.1 sigma gate, §5 D2/D3, §6.3 near-real-time, §6.4 threats facet, §6.5 trail, §6.6 forensics, §6.11 platform, §7 catalog, §C.4 fail-safe, §7.1a agent status, §7.1c policy formats) · [ws-g-console.md](ws-g-console.md) (M-G1..M-G4 + acceptance).
- **Backend field-adds referenced (owner = WS-N/WS-M-backend, not WS-G frontend):** `winning_source` on `/decisions` (FX-3.1), `platform_read_consent` on `platform_list_tenants` (FX-3.5) — ship UI PARTIAL if these slip.
- **Review source:** deep review 2026-07-09, 22 findings, all code-verified (0 false positives).
