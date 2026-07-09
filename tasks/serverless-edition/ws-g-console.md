# WS-G — Multi-tenant console (cosmetic-tenant containment + RBAC render-gating + org-first login + exhaustive FR-13.2 dashboard set + platform global-admin console)

> **Doc role:** **Phase-2 build-task doc** (granular, zero-ambiguity tasks generated from the approved LLD). It supersedes the earlier scope-only version of this file. The §0 scope-honesty banner + §2 "read before coding" model are the context an implementer must hold; the milestones (M-G0…M-G4) are the buildable tasks. Canonical order: HLD → **LLD ([lld/40](../../lld/40-multi-tenant-console.md))** → these tasks.

**Parent LLD:** [lld/40-multi-tenant-console.md](../../lld/40-multi-tenant-console.md) (v1.6, 2026-07-08 — CODE-VERIFIED canvas-UX gap review + login-model reconciliation). **Parent HLD:** [hld/serverless-edition.md](../../hld/serverless-edition.md) §6.2(f) ("Console sign-in & who-sees-what"), §8 hand-off row 8 (`FR-13.3 console`).
**Status:** CODE-DONE + DEPLOYED to prod (2026-07-09) · **Owner:** TBD · **Last updated:** 2026-07-09

> **✅ CODE-DONE + DEPLOYED (2026-07-09).** M-G0..M-G4 built (backend lane `a448bcc` + frontend lane `cc42343`), hardened by a 22-finding deep-review fix pass (`0f9af8b`/`90b81c9`, all code-verified) + 4 post-review residuals (`4d3695c`: #4 server-side threat_type facet + copy/a11y). Console image built from `main@4d3695c` → ECR → `sentra-console` ECS force-new-deploy → **LIVE-VERIFIED in prod** (`/` 200, `/org.html` 200, `GET /public/resolve-org?org=acme` 200; org-first login working; controller resolve_org/D13/platform-rollup all live). Frontend suite **195 pass** (tsc + vitest + lint green). **Still open (NOT blocking, tracked below):** (1) the OPTIONAL `ws-g-fix-backend` field-adds (`winning_source` on `/decisions` rows, `platform_read_consent` on the platform list) — two views ship honest PARTIAL until then; (2) multi-tenant isolation is hermetically tested + deployed but NOT yet exercised with a real second live tenant (pre-two-tenant-demo gate). The PARTIAL/ROADMAP acceptance boxes below are ticked because the degrade behavior IS built + tested (per this doc's rule "the PARTIAL-degrade variant must pass now"), not because the deferred full-fidelity variant shipped.
**Implements:** FR-13.1 (cosmetic-tenant containment — no cross-tenant leak) · FR-13.2 (exhaustive dashboard set) · FR-13.3 (login/tenancy model + RBAC role model).
**Decisions:** **ADR-019 / AD-8** (console multi-tenant SSO + RBAC, refined) · **ADR-039 — Accepted (founder) 2026-07-07** (org-first login: an unauthenticated org page → public `resolve_org(org)→tenant_id` → Cognito → tenant fixed per-tab for the session; deletes the in-session tenant-switcher) · **ADR-035** (federation seam, **design-only / deferred-last** — Cognito is kept; SAML/OIDC/SCIM provider swap is NOT built here; the canvas B2 SSO-federation screens are the post-ADR-035 roadmap target, NOT the pilot's as-built).

---

## §0 — Scope-honesty banner (READ FIRST: most of WS-G's surface is ALREADY BUILT)

> **The console is NOT a greenfield build.** WS-N (read-route auth + tenant-scoping) is COMPLETE and the RBAC/tenant primitives shipped with WS-M. Most feature directories, hooks, and API clients already exist in `web/console/`. The tasks below deliberately mark existing work **VERIFY/GATE/EXTEND** and reserve **BUILD** for the two genuinely-missing views (Activity, Usage) + the platform console + the org-first entry client. Do not rebuild what ships.

**ALREADY BUILT — do not rebuild (grep-verified @ `main`@`761bb88`):**
- **WS-N COMPLETE (N0–N10, `main`, suite 1195/11 green):** all **21 read routes** carry `Depends(resolve_operator_tenant)`; customer operator = STRICT own-tenant, platform operator = fleet view audited via `_audit_platform_read`. **D10** (`/trail`+`/signals` re-homed to the operator lane, ADR-038) + **D11** (per-tenant `/metrics/overview` + `/decisions-timeseries` — real per-tenant tiles, no longer null) are LANDED. WS-G's D10/D11 obligation is **verification-only** (M-G3 tenant-scoping tests), NOT a backend build.
- **WS-M authz LIVE in prod** (milestone-103): `require_role` on the mutating routes + `assert_owns` anti-IDOR; `X-Operator-Email` fully removed (operator = `ctx.sub`); BUG-1 IDOR closed. The server `require_role` (`deps.py:496`) is the real boundary — WS-G's render-gate only MIRRORS it.
- **Membership-403 built** (`deps.py:440`): a customer operator sending a foreign `X-Aegion-Tenant` is re-validated against membership and 403'd — the client can never select a foreign tenant.
- **Most feature dirs exist + routed** (`web/console/src/features/`): `overview`, `agents` (inventory + detail + flow), `threats`, `policies` (library + detail + editor), `connect`, `import`, `quarantine`, `identity` (residual-agents), `audit`, `topology`. `rbac.ts`/`useCan()` exist; `MeContext.is_platform` exists (`types/api.ts:66`). `TenantSwitcher.tsx` exists (to be DELETED per ADR-039).

**The REAL remaining build:**
1. **M-G1 — cosmetic-tenant containment (FR-13.1):** the `tenantOf` email-domain label reaches exactly one JSX site; rename + ESLint AST-guard it so it can never flow into a query/gate/http path; backend regression proving resolution derives from *membership*, not domain.
2. **M-G2 — RBAC render-gating (FR-13.3):** `useCan()` is wired into only 1 of 8 mutating features today; extend the `Capability` map to 1:1-mirror the server `require_role` routes, gate every mutating control, add the D3 client↔server parity test; delete `TenantSwitcher`, migrate the active-tenant binding to per-tab `sessionStorage`, wire the org-first fail-safe. **NOTE: no Vitest infra exists in `web/console` today** — scaffolding it (M-G2 G2.0) is a real WS-G task.
3. **M-G3 — exhaustive FR-13.2 dashboard set (§6/§7):** promote embedded components to routed tenant-scoped pages, BUILD the 2 missing views (Activity, Usage), bind Decision-detail to WS-D `/trail`; PARTIAL/ROADMAP-degrade the views whose backend field-adds aren't landed.
4. **M-G4 — platform global-admin console (§6.11):** a separate `is_platform` route-tree (read-only cross-tenant fleet aggregate) gated at the router root.

**Backend field-adds WS-G binds but does NOT own** are enumerated as **M-G0 prerequisites** (owner WS-N/WS-M-backend / WS-H / roadmap) — not WS-G build tasks.

---

## §1 — Dependencies + demo-readiness gate

- **WS-N (COMPLETE — reuse, do not rebuild):** the 21 read binds + D10 (`/trail`+`/signals` operator lane) + D11 (per-tenant `/metrics/overview` + `/decisions-timeseries`). WS-G's D10/D11 obligation is verification-only (M-G3 tests). **[ws-n-read-route-authz.md](ws-n-read-route-authz.md).**
- **WS-D `/trail` (LIVE in prod, `routes.py:566`):** `GET /v1/sessions/{id}/trail?request_id=` is operator-bound + live (no longer 401/flag-gated). WS-G wires the client (M-G3.4); the `SessionTrail` type SHAPE is WS-D-owned. **[ws-d-decision-trail.md](ws-d-decision-trail.md).**
- **WS-H usage (PREREQ):** `GET /v1/usage` → `UsageRollup` is a WS-H deliverable. Until it is live in the same build train, the Usage view (M-G3.12) is feature-flagged OFF (no dark billing tab) or renders the fail-secure PARTIAL banner. **[ws-h-metering.md](ws-h-metering.md).**
- **M-G0 backend prerequisites (owned by other workstreams — NOT WS-G frontend):**
  - **PILOT-BLOCKING (two-tenant demo DoD, §1 `40:70-91`):** **D13** shadow-write verified-tenant bind (G0.1), **D14** `resolve_org` + org page + ALB/nginx carve-out (G0.2/G0.3); **§6.11(1)** platform per-tenant rollup (G0.4 — for the platform console).
  - **ROADMAP:** topology flow-edge read (G0.6), residual-agents retire mutation (G0.7), system-health per-region route. These degrade to a roadmap badge + sample-data marker in the UI — no live read to a nonexistent route.
  - **PARTIAL field-polish (degrade gracefully):** agent activity-status enum (G0.8), sigma category chip (G0.9, client-only), compiled Cedar/JSON policy read (G0.10), quarantine origin + why-trace (G0.11).

> **Demo-readiness gate:** the two-tenant pilot demo cannot ship until the PILOT-BLOCKING M-G0 items (G0.1–G0.4) land. WS-G's own binding/rendering work (M-G3/M-G4) can build against the documented contract shapes and PARTIAL-degrade until each lands.

---

## §2 — Model / read-before-coding (the client invariants the implementer MUST hold)

1. **Tenant is server-derived, never client-asserted.** The only authoritative tenant binding is `set_current_tenant(chosen.tenant_id)` inside `resolve_operator_tenant` (`deps.py:449`), after a membership lookup. The client may send `X-Aegion-Tenant` as a **preference**; the server re-validates it against membership and 403s a non-member (`deps.py:440`). The email domain (`tenantOf`/`tenantLabelForDisplay`) is **NEVER an authority** — a cosmetic label only (M-G1).
2. **The RBAC render-gate is UX-only, NEVER the boundary.** `rbac.ts`/`useCan()` exist so a `viewer` doesn't *see* a control they can't use. The boundary is **always** the server `require_role` (`deps.py:496`). A gate that *hides* a control the server would reject is correct; a gate that *shows* one is a UX bug, never a security hole. A tampered client gains nothing.
3. **Org-first login (ADR-039).** Tenant is fixed **before** Cognito, per browser tab: an unauth org page → `resolve_org(org)→{tenant_id}` → stash to `sessionStorage["aegion.activeTenant"]` → Cognito → the server re-validates `X-Aegion-Tenant ∈ memberships`. There is NO in-session tenant-switcher (deleted in M-G2). Change-tenant = logout → org page → re-login.
4. **Near-real-time poll, NOT stream.** Every "live" feed is a modest-interval TanStack-Query poll (≤15s), labeled **"near-real-time (≤15s pull)"** — there is NO WebSocket/SSE anywhere in the console. The audit-store writes are fire-and-forget and can lag; a promised-realtime feed against a lagging store looks broken.
5. **Fail-secure.** Missing role ⇒ `can()` returns false ⇒ control hidden (never shown). A dependency API absent (`ApiException.status ∈ {404,501}`) ⇒ PARTIAL banner, never fabricated data and never a blank page. `/v1/me` outage ⇒ mock `is_platform:false` ⇒ the platform tree is denied, not exposed. A 403 on a mutation invalidates `['me']` (force role re-read); it does NOT log the user out.
6. **`/v1/me` is the single source of role + platform-flag for the UI.** `useMe()` returns `MeContext{sub, email, tenant_id, role, is_platform, memberships[]}`. All render-gating derives from `data.role`; the platform tree gates on `data.is_platform`; the org-first redirect gates on `data.memberships.length > 1`.

---

## Milestone M-G0 — Backend prerequisites (NOT WS-G frontend; external deps the console binds to)

Every task below is a **prerequisite owned by another workstream** (WS-N/WS-M-backend or CDK), not a WS-G frontend build item. WS-G's own binding/rendering work lives in M-G3/M-G4 and consumes the contracts these tasks land. Each entry names the real owner, the exact handler/endpoint, what the console consumes, and whether it is **PILOT-BLOCKING** (two-tenant demo DoD, §1 `40:70-91`) or **ROADMAP**. Line numbers are from lld/40's digest and the code inventory at `main`@`761bb88`; the owning coder must re-verify at tip before coding (`40:845`).

Pilot-blocking set: **G0.1 (D13)**, **G0.2 / G0.3 / G0.4 (D14)**. Everything else is roadmap or a field-polish PARTIAL that degrades gracefully in the UI.

---

### G0.1 — D13: shadow-write verified-tenant bind on `/v1/validate` shadow branch — **PILOT-BLOCKING**
- **Owner:** WS-N/WS-M-backend (owns the `/validate` write path). §6.2.1 (`40:368-396`).
- **Prerequisite, not WS-G:** without it every shadow-mode decision writes to partition `default#<date>` instead of `<tenant_id>#<date>`, so a newly-onboarded tenant's console (Overview, Activity, Threats, all `GET /v1/decisions`-bound views in M-G3) renders **blank** even though traffic is flowing. WS-G cannot fix a write-path tenant bind from the client.
- **UI consumes:** nothing new — it unblocks the existing per-tenant tiles/feed already bound in `OverviewPage.tsx:26` (`useOverview`) and the new `ActivityPage` (G3.1).
- **Touches:** `src/security-controller/app/api/routes.py:111` (`validate_tool_call`), shadow branch `routes.py:301-308`; mirror the enforce branch pattern at `routes.py:282` (`set_current_tenant`) / `routes.py:299` (reset).
- **Change:** in the shadow branch, call `set_current_tenant(ctx.tenant_id)` / reset in `finally`, **guarded by `ctx.is_verified` only**. Unverified/spoofed `tid` must stay ambient (`default`) — fail-secure, do NOT bind an unverified claimed tenant.
- **Footguns:** (1) do NOT bind on unverified context — a spoofed `tid` would poison a real tenant's partition; guard strictly on `ctx.is_verified`. (2) **No backfill** — decisions written to `default#` before this lands are not migrated; onboarding MUST credential the agent BEFORE first shadow traffic (`40:390`), else early rows are lost to `default`. (3) Reset in `finally` — a leaked contextvar cross-contaminates the next request on the same worker.
- **Unit:** `test_routes.py::test_shadow_branch_binds_verified_tenant` (verified ctx → `set_current_tenant` called with `ctx.tenant_id`); `::test_shadow_branch_unverified_stays_ambient` (unverified → no bind, writes `default`).
- **Integ:** `tests/integration/test_shadow_write_tenant_bind.py::test_shadow_decision_visible_to_tenant_overview` (verified agent for `t_globex` emits shadow decision → `GET /v1/metrics/overview` as a `t_globex` operator counts it; a `t_acme` operator does not; assert actual GSI partition == `t_globex#<date>`).

### G0.2 — D14: `resolve_org(org) → {tenant_id}` public endpoint — **PILOT-BLOCKING**
- **Owner:** UNASSIGNED backend class — WS-M/WS-N-backend (routes/tenancy). Founder-owned open item: assign + date (§ADRs). Grep-verified **absent** from `app/`@`761bb88`. ADR-039 (Accepted 2026-07-07).
- **Prerequisite, not WS-G:** the org-first login flow (§C, M-G2 §5.5) cannot start without it. The static org page (G0.3) `fetch`es this endpoint to turn a typed org name into a `tenant_id` before redirecting to Cognito. NET-NEW server route.
- **UI consumes:** `{ "tenant_id": "<derived-slug>" }` only — stashed into `sessionStorage["aegion.activeTenant"]` (§C.4), then emitted as `X-Aegion-Tenant`.
- **Touches:** new handler in `src/security-controller/app/api/tenancy_routes.py` (registry lookup against `sentra-tenants`); mounted on a **non-`/v1`** public path (e.g. `/public/resolve-org`). Registry/slug derivation per LLD-26 §6.2.
- **Change:** public (no auth), **fail-closed on internal error** (5XX, never a fake-200 — engineering error-contract rule), **rate-limited** (per-IP burst throttle), returns **ONLY** `tenant_id` (derived slug, never the echoed typed name). Miss → friendly `404`-shaped `{"error":"org not found — check spelling"}` (founder 2026-07-08 ACCEPTED org-NAME enumeration; the earlier "miss==hit non-enumerating" rule is DROPPED, `40:971`).
- **Footguns:** (1) MUST NOT be `/v1/*`-namespaced — priority-5 `ConsoleApiListenerRule` (`compute_stack.py:967`) 401s ALL unauth `/v1/*` before priority-10 ever sees it (`40:955-958`). (2) Return **zero** tenant data beyond the id — no counts, members, plan, or status (§C.2). (3) A miss must NOT advance the operator to Cognito with nothing stashed — keep them on the org page (§C.2 step 2).
- **Unit:** `test_tenancy_routes.py::test_resolve_org_returns_only_tenant_id` (hit → `{tenant_id}` and no other keys); `::test_resolve_org_miss_friendly_not_found`; `::test_resolve_org_internal_error_fails_closed_5xx`.
- **Integ:** `tests/integration/test_resolve_org_public.py::test_resolve_org_reachable_without_cognito` (unauth call succeeds, no `authenticate-cognito` redirect); `::test_resolve_org_burst_throttled` (rate limit trips on burst).

### G0.3 — D14: standalone static org page + ALB priority-<5 carve-out + nginx location + private-ALB forward — **PILOT-BLOCKING**
- **Owner:** WS-M/WS-N-backend + **CDK** (compute stack + console-nginx). §C.1 (`40:955-975`). Coordinate w/ LLD-08/LLD-16.
- **Prerequisite, not WS-G:** the entry page must be a **self-contained static HTML** (shape (a), like `splash.html`) — NOT a React-SPA route. An SPA org-route can't fetch its own hashed `/assets/*` bundle because those chunks fall through to priority-10 auth (`40:960-962`). Shape (b) "widen carve-out to `/assets/*`" is **REJECTED** pending explicit founder decision — do NOT implement it.
- **UI consumes:** page `fetch`es G0.2, stashes `tenant_id` to `sessionStorage`, then `window.location = <Cognito hosted UI>`.
- **Touches:** (a) new static `org.html` served like `splash.html`; (b) `cdk/stacks/compute_stack.py` — new **public** listener rule at **priority < 5** (host + exact path, plain `forward`, NO `authenticate-cognito`), precedent = priority-3 `ConsoleSplashRule` (`compute_stack.py:887`); (c) console-nginx `location` block for `/public/resolve-org` (inject `x-api-key`, forward to controller); (d) **private-ALB forward rule** — private ALB default is 404, rules live at `compute_stack.py:1031-1105`.
- **Footguns:** (1) priority MUST be `< 5` or the `/v1/*` deny rule (`compute_stack.py:967`) wins first. (2) Private ALB default-404 means the forward rule (d) is mandatory or the internal hop 404s (`40:967`). (3) nginx must inject the api-key — the browser never sets `x-api-key` (per `http.ts` contract). (4) Keep the page dependency-free (no bundle fetch) — that's the whole reason for shape (a).
- **Unit:** `tests/unit/test_compute_stack.py::test_resolve_org_public_rule_priority_below_5` (synth asserts rule priority < 5, no cognito action, exact-path condition); `::test_private_alb_resolve_org_forward_rule_present`.
- **Integ:** `tests/integration/test_org_page_entry.py::test_org_html_served_unauth` (GET `/org.html` → 200 unauth, no redirect); `::test_resolve_org_through_nginx_injects_apikey` (nginx path reaches controller with api-key).

### G0.4 — Platform per-tenant metrics rollup on `GET /v1/platform/tenants` — feeds M-G4 (**PILOT-relevant for platform console**)
- **Owner:** WS-N/WS-M-backend (owns `tenancy_routes.py`). §6.11 (1) (`40:539-540`).
- **Prerequisite, not WS-G:** `platform_list_tenants` (`tenancy_routes.py:437`, `require_platform`) today returns only `{tenant_id, display_name, plan, status, identity_mode, created_at}` — no fleet metrics. Until this lands, M-G4 Fleet Overview / Tenant Grid ships the **Ranked-Table (6-col) shape as roadmap-degraded**, NOT the full metrics grid (§7.2, `40:785-787`).
- **UI consumes:** per-row `blocks_24h`, `deny_rate`, `trust`, `agents`, `quarantined`, `decisions_24h` → new `PlatformTenantRow` type (`web/console/src/types/api.ts`); bound by the new `platformApi` client (does NOT exist today — grep found zero `platform/tenants` refs).
- **Touches:** `src/security-controller/app/api/tenancy_routes.py:437` (`platform_list_tenants`); add a **batch** per-tenant rollup (one call keyed by tenant — NOT N per-tenant scans).
- **Footguns:** (1) do NOT fan out one `fleet_scan`/query per tenant — that's the O(N) blast that caused the overview-latency incident; use a single batched rollup keyed by tenant. (2) Every cross-tenant read here is a platform read — must route through `_audit_platform_read` (see M-G4 invariants). (3) Fleet path uses `tenant_id=None` → `fleet_scan`; do not bind an operator tenant.
- **Unit:** `test_tenancy_routes.py::test_platform_list_tenants_includes_rollup_fields` (row carries the 6 metric fields); `::test_platform_rollup_single_batched_call` (assert not N-per-tenant).
- **Integ:** `tests/integration/test_platform_grid.py::test_fleet_rollup_matches_per_tenant_sum` (rollup `blocks_24h` for `t_acme` == sum of `t_acme` decisions).

### G0.5 — Platform registry paging / sort / filter on `GET /v1/platform/tenants`
- **Owner:** WS-N/WS-M-backend. §6.11 (2) (`40:541`).
- **Prerequisite, not WS-G:** same handler (`tenancy_routes.py:437`) returns `list_all()` **unpaginated**; a 1000-tenant grid can't be served or client-filtered safely. Until this lands, the Tenant Grid stays capped/roadmap-labeled.
- **UI consumes:** `?limit`, `?cursor`, `?sort`, `?filter` query params → paginated `Page<PlatformTenantRow>` for the M-G4 grid.
- **Touches:** `src/security-controller/app/api/tenancy_routes.py:437` — add `limit`/`cursor`/`sort`/`filter` params + cursor response envelope.
- **Footguns:** (1) `require_platform` gate must remain — never widen to tenant operators. (2) Cursor must be opaque/server-issued (no client-controlled offset into a cross-tenant scan). (3) Pairs with G0.4 — page the rollup, don't roll up an unpaged list.
- **Unit:** `test_tenancy_routes.py::test_platform_list_tenants_paginates` (limit honored, cursor round-trips); `::test_platform_list_tenants_sort_filter`.
- **Integ:** `tests/integration/test_platform_grid.py::test_grid_pagination_stable_across_pages` (no dup/skip across cursor pages).

### G0.6 — Topology flow-edge aggregation read `GET /v1/topology` — **ROADMAP**
- **Owner:** ROADMAP (WS-N/WS-M-backend if built). §6.1/§7.2 (`40:588`, `40:615`).
- **Prerequisite, not WS-G:** **zero** `topology`/`flow-edge`/`sankey` routes exist in `app/api/`. The existing `TopologyPage.tsx` (`FlowSankey`, `buildFleetFlow` from `lib/flowGraph.ts`) has no live source. Until this route exists, both the customer Topology view (§7.2) and M-G4(b) fleet topology render a **roadmap badge + explicitly-marked sample data** — NO live read to a nonexistent route (`40:785-787`).
- **UI consumes (when built):** cloud→agent→tool aggregated `{volume, allowed, blocked}` edges for the Sankey.
- **Touches:** new handler under `src/security-controller/app/api/` (customer per-tenant + platform fleet mode); no existing line to cite (net-new).
- **Footguns:** (1) do NOT wire `TopologyPage`/`FlowSankey` to a live fetch against a route that 404s — keep it roadmap-badged sample data until the route ships (§7.2 test). (2) When built, customer mode must bind operator tenant; platform mode `tenant_id=None` + `_audit_platform_read`.
- **Unit:** `test_topology_routes.py::test_topology_edges_aggregate_by_cloud_agent_tool` (only if/when built).
- **Integ:** `web/console/src/features/topology/__tests__/TopologyPage.roadmap.test.tsx::renders_roadmap_badge_no_live_fetch` (asserts no network call to `/v1/topology`, sample-data marker present) — this WS-G guard test lands now regardless.

### G0.7 — Residual-agents retire mutation route + capability — **ROADMAP (founder-deferred 2026-07-08)**
- **Owner:** roadmap (later increment) — **founder-deferred 2026-07-08**. §7.1e (`40:591`).
- **Prerequisite, not WS-G — deferred to a later increment:** `GET /v1/identity/residual-agents` (`tenancy_routes.py:117`) is **GET-only**; `ResidualAgentsPage.tsx:12` is correctly read-only today. A retire button needs a new mutation route + a new `Capability`. **The founder deferred retire to roadmap** — the page stays read-only for the pilot (no dead/fabricated retire button); the retire mutation + cap land in a later increment, not now.
- **UI consumes (when built):** a `POST`/`DELETE` retire endpoint + new client cap (e.g. `identity.residual.retire`) added to `rbac.ts` `MIN_ROLE`.
- **Touches:** new mutation handler alongside `tenancy_routes.py:117`; on landing, `web/console/src/lib/rbac.ts:29` `MIN_ROLE` gains the retire cap (exhaustive `Record` — omitting it fails `tsc -b`).
- **Footguns:** (1) do NOT add a retire control to `ResidualAgentsPage` before the route + cap exist — renders a button that 404/403s. (2) New cap MUST be added to the exhaustive `MIN_ROLE` map AND the D2/D3 parity fixture (M-G2) or the parity gate fails.
- **Unit:** `test_tenancy_routes.py::test_residual_agent_retire_requires_role` (only if built).
- **Integ:** `web/console/src/features/identity/__tests__/ResidualAgentsPage.readonly.test.tsx::no_retire_control_until_route_exists` (WS-G guard, lands now).

### G0.8 — PARTIAL field (a): agent activity-status enum (`GET /v1/agents`)
- **Owner:** WS-N/WS-M-backend **OR** WS-G client-map. §7.1a (`40:606`).
- **Prerequisite (conditional):** `GET /v1/agents` `status` = ECS lifecycle enum `running/starting/stopped/not_found/unknown` (`agent_service.py:687`, enrich `:634-697`) — NOT the canvas `Active/Idle/Offline`. **Recommended: client-side map (no backend needed)**; only if a server `activity_status` field is preferred does this become a WS-N/WS-M task. `denied_pct` is already client-computed (`:642-644`, fine — no change).
- **UI consumes:** mapped status for `AgentInventoryPage.tsx:25` rows (`running`→Active, `stopped`/`not_found`→Offline, no-traffic→Idle — Idle NOT Active).
- **Touches (client path):** `web/console/src/features/agents/AgentInventoryPage.tsx` + a small mapper in `lib/api/agents.ts`. (backend path, if chosen): `src/security-controller/app/services/agent_service.py:687`.
- **Footguns:** (1) no-traffic must map to **Idle, not Active** (§15 `40:779`). (2) Prefer the client map — do not block the M-G3 inventory promotion on a backend field.
- **Unit:** `web/console/src/features/agents/__tests__/activityStatus.map.test.ts::maps_ecs_state_to_canvas_status` (running→Active, stopped/not_found→Offline, no-traffic→Idle).
- **Integ:** `web/console/src/features/agents/__tests__/AgentInventoryPage.test.tsx::renders_mapped_activity_status`.

### G0.9 — PARTIAL field (b): sigma category chip — **NO backend prerequisite (WS-G client-derives)**
- **Owner:** WS-G client only. §7.1b (`40:607`). Listed here for completeness — it is **not** a backend dep.
- **Detail:** `GET /v1/sigma-rules` (`routes.py:1829`) returns `tags`/`level`/`patterns_count`/`match_count_24h`/`status` — no `category`. Derive the chip from `tags` client-side (best-effort map, fallback to raw tag). No backend change requested or needed.
- **Touches (WS-G, in M-G3):** `web/console/src/features/policies/PolicyLibraryPage.tsx` sigma table + a `tags→category` mapper.
- **Footguns:** unmapped `tags` → fallback label, **no code change** required to add a new category (§15 `40:781`).
- **Unit:** `web/console/src/features/policies/__tests__/sigmaCategory.map.test.ts::unmapped_tag_falls_back_no_code_change`.
- **Integ:** covered by M-G3 `PolicyLibraryPage` test — no backend integ.

### G0.10 — PARTIAL field (c): policy compiled Cedar/JSON source read (`GET /v1/policies/{id}`)
- **Owner:** WS-N/WS-M-backend (or roadmap tabs). §7.1c (`40:608`).
- **Prerequisite, not WS-G:** `get_policy_by_id` (`routes.py:1583`, `?include_content=true`) returns metadata + authored **YAML from S3 only** — no compiled Cedar/JSON. The console's Cedar/JSON toggle (`PolicyDetailPage.tsx`, `policyFormat.ts`) has no compiled source to show. Until a compiled-source read lands, the YAML tab is LIVE and the Cedar/JSON tab degrades to **PARTIAL** — the client MUST NOT fabricate a compiled body.
- **UI consumes (when built):** new compiled field OR `?format=cedar|json` variant of `GET /v1/policies/{id}`.
- **Touches:** `src/security-controller/app/api/routes.py:1583` (`get_policy_by_id`) — add compiled-source read (new response field or `format` param).
- **Footguns:** (1) client must NEVER synthesize/compile Cedar in the browser — show PARTIAL when the compiled source is absent (§15 `40:782`). (2) YAML tab stays live regardless.
- **Unit:** `test_routes.py::test_get_policy_returns_compiled_cedar_when_requested` (only if built).
- **Integ:** `web/console/src/features/policies/__tests__/PolicyDetailPage.test.tsx::cedar_tab_partial_without_compiled_source` (WS-G guard, lands now).

### G0.11 — PARTIAL field (d): quarantine origin + why-trace on the session read
- **Owner:** WS-N/WS-M-backend (owns `session_manager.py`/`routes.py`). §7.1d (`40:609`).
- **Prerequisite, not WS-G:** the store HAS `quarantine_reason` + `quarantine_operator` (`session_manager.py:394`), but `_format_session_for_api` (`session_manager.py:636`) surfaces **neither** the origin (auto vs operator) nor an ordered trigger-signal list. `QuarantinePage.tsx` can't render a why-trace without them. Until surfaced, the UI degrades to showing `quarantine_status` only.
- **UI consumes:** `quarantine_origin` (auto|operator) + ordered trigger-signal list on `SessionInfo` (`GET /v1/sessions?status=quarantined`, `routes.py:669`).
- **Touches:** `src/security-controller/app/services/session_manager.py:636` (`_format_session_for_api`) — surface origin + ordered signals from the fields already stored at `:394`.
- **Footguns:** (1) origin must distinguish auto-quarantine from operator-quarantine (don't collapse to a single flag). (2) Client degrades to `quarantine_status` when absent — no fabricated trace (§15 `40:783`).
- **Unit:** `test_session_manager.py::test_format_session_surfaces_quarantine_origin_and_signals`.
- **Integ:** `web/console/src/features/quarantine/__tests__/QuarantinePage.test.tsx::why_trace_renders_when_origin_and_signals_present_else_degrades`.

---

**Not re-tasked here (tracked in their owning workstreams, WS-G binds no new contract):** D10/D11 read-bind (COMPLETE, WS-N N0–N10 @`761bb88`), D11 identity-DENY undercount (§6.10, WS-N/WS-H follow-up), D12 read-access attribution (§8 SEC-5, WS-N N9.1), feed DoS/RCU ceiling (§13, WS-N/WS-M before demo). WS-G's D10/D11 obligation is verification-only (M-G3 tests), not a backend build.

---

## Milestone M-G1 — Cosmetic-tenant containment (FR-13.1)

**LLD:** lld/40 §4 (`40:198-226`). **Owner:** WS-G (frontend), except G1.3 which touches the backend PDP.
**Goal:** the email-domain tenant label (`tenantOf`, `web/console/src/lib/auth.ts:61`) is display-only and today reaches exactly one JSX site (`AccountMenu.tsx`). Make its re-introduction into any auth/query/gate path **impossible to merge** (rename + AST lint guard), grep-prove containment, and add a backend regression proving tenant resolution derives from *membership*, never the email domain. **Do NOT delete `tenantOf`** — `AccountMenu` renders its output as a cosmetic chip (`AccountMenu.tsx:133-140`); deleting it breaks that chip.

**Cross-references:** Implements FR-13.1. Shared contract: `tenantLabelForDisplay` (renamed export), `resolve_operator_tenant` (`deps.py:374`, authority = `get_member_store().by_operator(sub)`). Sibling: M-G2 §5.5 (adds the `no-restricted-syntax` rules block this milestone creates; M-G2 extends the same `rules` object).

---

### G1.1 — Rename `tenantOf` → `tenantLabelForDisplay` (export + sole caller)

**Touches:**
- `web/console/src/lib/auth.ts:61` — `export function tenantOf(...)` → `export function tenantLabelForDisplay(...)`. Keep the body byte-identical (`email.split('@')[1]`), keep the `DISPLAY-ONLY, NON-AUTHORITATIVE` docblock (`auth.ts:54-60`).
- `web/console/src/components/ui/AccountMenu.tsx:12` — update the named import `{ ... tenantOf }` → `{ ... tenantLabelForDisplay }` (import line currently pulls `displayName, initials, primaryRole, signOut, tenantOf` from `../../lib/auth`).
- `web/console/src/components/ui/AccountMenu.tsx:44` — call site `const tenant = tenantOf(user)` → `tenantLabelForDisplay(user)`. The consuming JSX (`AccountMenu.tsx:133-140`, the tenant chip) is unchanged — it reads the local `tenant` var.

**Concrete change:** pure rename; no signature/return-type change (`(user?: CurrentUser | null) => string | null`). The new name makes any future misuse self-evidently a display value at the call site.

**Footguns:**
- Do NOT `export { tenantOf as tenantLabelForDisplay }` (a compat alias) — that leaves the old symbol callable and defeats the lint guard in G1.2. Rename the declaration itself; no re-export of the old name.
- `AccountMenu.tsx` uses the **cosmetic** `useCurrentUser` (`/whoami` edge claims), NOT `useMe` (`/v1/me`). Do not "fix" this by swapping to `useMe` here — the authoritative tenant is bound server-side (G1.3) and surfaced elsewhere; this call stays display-only.
- Grep the whole tree first: only `auth.ts:61` (def) and `AccountMenu.tsx:12,44` reference `tenantOf`. If any other hit appears, it is a latent scoping-misuse — STOP and flag, do not blind-rename.

**Unit:** `web/console/src/lib/__tests__/auth.test.ts` → `tenantLabelForDisplay returns email domain for display` (input `{email:'alice@acme.io'}` → `'acme.io'`; `null`/no-`@` → `null`) and `tenantOf is no longer exported` (`expect((authModule as any).tenantOf).toBeUndefined()`).
**Integ (component):** `web/console/src/components/ui/__tests__/AccountMenu.test.tsx` → `renders cosmetic tenant chip from tenantLabelForDisplay` (mock `useCurrentUser` → `{email:'bob@globex.com'}`; assert chip shows `globex.com`, render via Testing Library `screen.getByText`).

---

### G1.2 — ESLint AST guard: `tenantLabelForDisplay`/`tenantOf` cannot flow into query/http/rbac paths

**Touches:**
- `web/console/eslint.config.js` — add a **net-new `rules` block** scoped to the existing `files: ['**/*.{ts,tsx}']` config object (the flat-config array currently has NO `rules` key; add one). Use `no-restricted-syntax` with `CallExpression` selectors.

**Concrete change:** add rules that fail the build (`npm run lint`, and thus the CI gate) when `tenantLabelForDisplay(` or `tenantOf(` appears as an **argument** to a scoping sink. Selectors (esquery), each with a message pointing to FR-13.1:
- Passed into query keys: `CallExpression[callee.object.name='queryKeys'] > CallExpression.arguments > CallExpression[callee.name=/^(tenantLabelForDisplay|tenantOf)$/]` and the nested-member variant `MemberExpression[object.name='queryKeys']`.
- Passed into the fetch layer: `CallExpression[callee.object.name='http'][callee.property.name=/^(get|post|put|patch|del)$/] > CallExpression[callee.name=/^(tenantLabelForDisplay|tenantOf)$/]`.
- Passed into RBAC: `CallExpression[callee.name=/^(can|rbacCan|roleSatisfies)$/] > CallExpression[callee.name=/^(tenantLabelForDisplay|tenantOf)$/]`, plus `CallExpression[callee.property.name='can']` (for `useCan().can`) with the same arg selector.
- Belt-and-suspenders: a `no-restricted-syntax` selector flagging the label passed to anything setting the tenant header — `CallExpression[callee.name='setActiveTenant'] > CallExpression[callee.name=/^(tenantLabelForDisplay|tenantOf)$/]` (guards the `lib/tenant.ts` seam).

**Footguns:**
- `no-restricted-syntax` with an argument selector catches the **direct-call** form (`http.get(k, tenantOf(u))`). It does NOT catch launder-through-a-variable (`const t = tenantOf(u); http.get(k, t)`). Document this limit in a comment; the real authority guard is server-side (G1.3) — the lint is defense-in-depth against the obvious re-introduction, not a proof. Do not over-claim it as complete interprocedural coverage.
- Flat-config merge order: M-G2 §5.5 also adds capability-related lint. Put this `rules` object on the SAME config entry (the `**/*.{ts,tsx}` one) so both milestones append to one `rules` map — do NOT add a second competing config object for the same glob (last-wins would silently drop rules).
- `del` is the real method name in `lib/http.ts` (`http.{get,post,put,patch,del}`, `http.ts:192`) — not `delete`. Match `del`.
- Selector must not false-positive on the legitimate display call in `AccountMenu.tsx:44` (`const tenant = tenantLabelForDisplay(user)` — assignment, not an argument to a sink). Verify the AST selectors target `CallExpression.arguments` only.

**Unit (lint-rule behavior):** `web/console/src/lib/__tests__/lint-tenant-guard.test.ts` using `RuleTester`/`Linter` from `eslint` — `flags tenantLabelForDisplay passed to http.get` (asserts ≥1 error), `flags tenantOf passed to queryKeys.decisions.list`, `flags label passed to can()`, and negative `allows tenantLabelForDisplay assigned to a local var` (0 errors — the AccountMenu shape). Load the actual `eslint.config.js` rules block into the `Linter`.
**Integ (build gate):** `web/console/src/lib/__tests__/lint-guard-e2e.test.ts` (or a CI step) → `npm run lint fails on a fixture that scopes on the label` — write a temp fixture file `queryKeys.decisions.list(tenantLabelForDisplay(user))`, run `eslint` programmatically over it, assert non-zero result; a fixture WITHOUT the misuse lints clean.

---

### G1.3 — Backend FR-13.1 regression: resolution uses membership, never email domain

**Touches:**
- `src/security-controller/tests/test_multitenancy_identity.py` — add a new test (this file already holds the OIDC-claim resolution tests and the `mt_env` fixture pattern). NO production code change — this asserts existing `deps.py:374` behavior can never regress to domain-derivation.

**Concrete change:** exercise `resolve_operator_tenant` (`deps.py:374` → `_resolve_operator_tenant_inner` `deps.py:404`) with:
- `verify_alb_oidc` monkeypatched to return claims `{"sub":"alice-sub","email":"alice@acme.io"}` (mirror the existing `monkeypatch.setattr(deps, "verify_alb_oidc", lambda req: {...})` style; the inner reads `claims["sub"]` `deps.py:406` and `claims.get("email")` `deps.py:407`).
- Member store seeded so `by_operator("alice-sub")` (`tenant_service.py:295`) returns a **sole** membership in `t_globex` — via `get_member_store().add(operator_sub="alice-sub", tenant_id="t_globex", role="viewer", is_primary=True)` (`add`, `tenant_service.py:328`), under the `mt_env` moto fixture.
- No `X-Aegion-Tenant` header (drives the `else` primary-pick branch, `deps.py:443-447`).
- **Assert** the returned `OperatorContext.tenant_id == "t_globex"` AND `tenancy.get_current_tenant() == "t_globex"` (set at `deps.py:449`) — explicitly **NOT** `"acme.io"` / `"acme"` (the email domain). Add an inline assert-message naming FR-13.1 so a future domain-based regression is unmistakable.

**Footguns:**
- The email domain (`acme.io`) and the membership tenant (`t_globex`) MUST be deliberately DIFFERENT — that mismatch is the whole point (if they matched, a domain-derivation bug would pass silently). Do not seed `tenant_id="acme.io"`.
- Run under the moto-safe harness: reuse `mt_env` (clears `deps._mode_cache`, resets `ts._member_store`) and the `run(...)` async helper from `tests/mt_helpers`; leaking a real `AWS_PROFILE` breaks the member-store fixture (per repo test-hygiene note — `env -u AWS_PROFILE`, fake creds).
- Do NOT test via `resolve_tenant_from_jwt` (that's the JWT-in-body identity path, `deps.py` shadow-lane) — FR-13.1 authority is `resolve_operator_tenant`'s membership lookup. Use `app.dependency_overrides`-free direct `run(resolve_operator_tenant(FakeRequest({})))` with `verify_alb_oidc` patched (the `test_agent_management_apis.py:22` override pattern is for route tests; here call the dep directly).

**Unit:** `src/security-controller/tests/test_multitenancy_identity.py::test_resolution_uses_membership_not_email_domain` — the core case above (`alice@acme.io` + sole `t_globex` → `t_globex`).
**Integ (isolation):** `src/security-controller/tests/test_multitenancy_isolation.py::test_domain_matching_tenant_never_auto_bound` — seed operator `carol@acme.io` whose **only** membership is `t_globex`, AND ensure a *different* tenant `t_acme` exists in the registry with no membership for carol; assert `resolve_operator_tenant` binds `t_globex` and that a subsequent bound read (e.g. `GET /v1/agents` via `TestClient`) returns only `t_globex` rows — never `t_acme`, proving the email domain grants zero access.

---

**Acceptance (M-G1):**
- [x] `tenantOf` no longer an exported symbol; `tenantLabelForDisplay` is; sole callers = `auth.ts` def + `AccountMenu.tsx:12,44` (grep-proven display-only, G1.1).
- [x] `eslint.config.js` has a `rules` block failing `npm run lint` when the label is passed into `queryKeys.*` / `http.{get,post,put,patch,del}` / `can`|`rbacCan`|`roleSatisfies` / `setActiveTenant` (G1.2 unit + build-gate integ green).
- [x] Backend regression proves `alice@acme.io` + sole `t_globex` membership resolves to `t_globex`, not the domain (G1.3 unit + isolation integ green under `mt_env`).
- [x] `npm run build` (tsc-b + vite) and `npm run lint` pass; `pytest tests/test_multitenancy_identity.py tests/test_multitenancy_isolation.py` green.

**PREREQUISITES:** none (all touch-points exist at `761bb88`; `resolve_operator_tenant`/`by_operator` already ship — G1.3 is a regression lock, not a build).

---

## Milestone M-G2 — RBAC render-gating + org-first login binding (FR-13.3)

Scope: `rbac.ts` + `useCan()` already exist but are wired into exactly **one** of eight mutating features (`PolicyLibraryPage`). This milestone (A) extends the `Capability` map to 1:1-mirror the server `require_role` routes and wires `useCan()` into every mutating control across `features/{agents,policies,connect,import,quarantine,identity}`, adds the D3 client↔server parity Vitest; and (B) deletes `TenantSwitcher`, migrates the active-tenant binding to per-tab `sessionStorage`, and wires the org-first fail-safe. All render-gating is defense-in-depth — the server `require_role` (`deps.py:496`) remains the real boundary; a gate that hides a control the server would reject is correct, a gate that *shows* one is a UX bug, never a security hole.

**PREREQUISITES this milestone consumes (NOT WS-G build tasks — owners named):**
- **D14 — org page + `resolve_org` + ALB/nginx carve-out** (§C.1–C.2, `40:955-977`). NET-NEW public endpoint on a non-`/v1` path, new public ALB rule < priority-5, nginx `location`, private-ALB forward rule. Grep-verified absent from `app/` @ `761bb88`. **Owner: WS-M/WS-N-backend + CDK (UNASSIGNED — must be assigned).** M-G2's org-entry client task (G2.12) is blocked on the `resolve_org` contract shape landing.
- **D3 backend fixture generator** — the pytest that regenerates `web/console/src/lib/__fixtures__/role-model.json` from `deps.py` `require_role`/`require_platform` route walk and fails on uncommitted diff. **Owner: WS-N/WS-M (backend files, `40:270`).** G2.11 (the Vitest parity assertion) consumes the emitted fixture; it cannot author the generator.

---

### G2.0 — Scaffold Vitest + Testing Library (test harness does not exist yet)

- **Touches:** `web/console/package.json` (`scripts` block — currently only `dev`/`build`/`lint`/`preview`, no `test`; `devDependencies` — no vitest/testing-library present), new `web/console/vitest.config.ts`, new `web/console/src/test/setup.ts`.
- **Change:** Add devDeps `vitest`, `jsdom`, `@testing-library/react`, `@testing-library/user-event`, `@testing-library/jest-dom`, `@vitest/coverage-v8`. Add `"test": "vitest run"` + `"test:watch": "vitest"` scripts. `vitest.config.ts`: `environment: 'jsdom'`, `setupFiles: ['src/test/setup.ts']`, reuse the existing `@vitejs/plugin-react` from `vite.config`. `setup.ts` imports `@testing-library/jest-dom/vitest` and registers `afterEach(cleanup)`. Provide a `renderWithProviders` helper wrapping `QueryClientProvider` (new `QueryClient` per test, `retry:false`) + `MemoryRouter` so page-level tests can mount.
- **Footguns:** Every "Unit" test named below is un-runnable until this lands — do this FIRST. Do NOT add vitest globals to `eslint.config.js` `globals.browser` blindly; scope test globals to `**/*.test.{ts,tsx}` or `tsc -b` + lint will flag `describe`/`it` in app files. `QueryClient` must be per-test (a shared client leaks `['me']` cache across the RBAC tests and makes role-swap assertions flaky).
- **Unit:** `src/test/setup.test.tsx` — `renderWithProviders(<div/>)` mounts and `jest-dom` matcher `toBeInTheDocument` resolves (smoke: harness wired).
- **Integ:** n/a (infra task); gate = `npm run test` exits 0 and `npm run build` still green.

---

### G2.1 — Extend `Capability` union + `MIN_ROLE` (5 new caps) + split `sigma.retire` into `PlatformCapability` (D2, §5.1 `40:234-255`)

- **Touches:** `web/console/src/lib/rbac.ts:19-27` (`Capability` union), `:29-40` (`MIN_ROLE`), `:16` (`RANK`), `:42` (`roleSatisfies`), `:48` (`can`); `web/console/src/lib/query/useMe.ts:22` (`useCan`).
- **Change:** Add to the `Capability` union the 5 new caps with `MIN_ROLE` matching the Appendix-A server map exactly (`40:824-843`): `decisions.verdict`→`editor` (server `POST /decisions/{id}/verdict` `require_role("editor")` @routes.py:1347), `quarantine.manage`→`admin` (`POST`@2269 + `DELETE`@2363 `/quarantine/{id}`), `policies.delete`→`admin` (`DELETE /policies/{id}`@1739), `connections.write`→`admin` (`POST`@1107/`PUT`@1140/`DELETE`@1236 `/connections`), `connections.operate`→`editor` (`POST /connections/{id}/test`@1178, `/scan`@1216). Also add `tenant.manage`→`admin` for `PATCH /tenants/{id}` (`update_tenant`, `tenancy_routes.py:227`) to close the D3-completeness gap (`40:253`) — OR route it to the completeness allowlist; pick the cap (it's an admin control). Add a **separate** `export type PlatformCapability = 'sigma.retire'` + `const PLATFORM_MIN` gated on `is_platform` (server `PATCH /sigma-rules/{id}` `require_platform`@1916), and a `usePlatformCan()` in `useMe.ts` reading `useMe().data?.is_platform`.
- **Footguns:** `MIN_ROLE` is an **exhaustive** `Record<Capability,TenantRole>` (`rbac.ts:29`) — adding a union member without its `MIN_ROLE` entry fails `tsc -b`; add both together. **`sigma.retire` MUST NOT enter the `Capability` union** (`40:872`) — it gates on `is_platform`, not a `TenantRole`, so it has no valid `MIN_ROLE[cap]` and would break the exhaustive map. Keep `RANK` unchanged (`{viewer:0,editor:1,admin:2,owner:3}`) — it already mirrors `deps.py:39 _ROLE_ORDER`; do not renumber.
- **Unit:** `src/lib/rbac.test.ts` — `can('viewer','policies.delete')===false`, `can('editor','policies.delete')===false`, `can('admin','policies.delete')===true`; `can('editor','decisions.verdict')===true`, `can('viewer','decisions.verdict')===false`; `can('editor','connections.write')===false`; `can('editor','connections.operate')===true`; TS-level: a `satisfies Record<Capability,TenantRole>` assertion on `MIN_ROLE` compiles (guards the exhaustive-key gap).
- **Integ:** covered by G2.11 parity test (asserts every new `MIN_ROLE[cap]` == server fixture role).

---

### G2.2 — Complete RBAC gating on `PolicyLibraryPage` (promote: partially gated today)

- **Touches:** `web/console/src/features/policies/PolicyLibraryPage.tsx:47` (`const can = useCan()`), `:111` (create — already gated `can('policies.write')`), `:184` (Enable/Disable toggle — `onToggle`), `:194` (Delete button — `setDeleteFor`).
- **Change:** This page ALREADY calls `useCan` (`:16,47`) and gates the "New policy" button (`:111`). Extend: wrap the **Delete** control (`:194`) in `can('policies.delete')` (was implicitly under `policies.write`; server is stricter — `DELETE`@1739 is admin, `PUT`@1682 is editor). Keep Enable/Disable (`PATCH /policies/{id}/status`@1781, editor) under `can('policies.write')`. Gated control is **not-rendered**, not disabled (`40:289`).
- **Footguns:** Do NOT collapse delete under `policies.write` — an editor can edit but not delete; conflating them shows a delete button the server 403s. The row is clickable to detail regardless (read is not gated).
- **Unit:** `PolicyLibraryPage.test.tsx` — mock `useMe` role `editor` → New-policy + Edit + Disable present, Delete absent; role `admin` → Delete present; role `viewer` → none of {New, Edit, Disable, Delete} present.
- **Integ:** part of G2.11 completeness walk (both policy routes mapped).

---

### G2.3 — Gate quarantine release control (`quarantine.manage`)

- **Touches:** `web/console/src/features/quarantine/QuarantinePage.tsx` — `ReleaseButton` component (`:20-40`, `useReleaseQuarantine` @`:21`, the `<button>` @`:34`).
- **Change:** Import `useCan` from `lib/query/useMe`; in `ReleaseButton` (or its parent, so the hook isn't called conditionally) compute `can('quarantine.manage')` and render the release `<button>` only when true. Server floor: `DELETE /quarantine/{id}` @routes.py:2363 is `require_role` admin-class per Appendix-A row 3.
- **Footguns:** `useCan` returns a function — call `useCan()` once at component top, never inside the `onClick`/map callback (violates rules-of-hooks; `eslint-plugin-react-hooks` @flat/recommended will flag). Read-only quarantine list stays visible to viewers; only the release action hides.
- **Unit:** `QuarantinePage.test.tsx` — `admin` → Release button rendered; `viewer`/`editor` → Release absent, session rows still listed.
- **Integ:** G2.11 (route `/quarantine/{id}` DELETE mapped to `quarantine.manage`).

---

### G2.4 — Gate Threats-page quarantine + verdict controls (`quarantine.manage`, `decisions.verdict`)

- **Touches:** `web/console/src/features/threats/ThreatsPage.tsx:43` (`useQuarantine`), quarantine `<Button>` @`~183` (`quarantine.mutate` block, verified `:190` region); `web/console/src/components/decisions/DecisionReviewPanel.tsx:16` (`useVerdict`), verdict `<Button>`s @`:46,49,55`.
- **Change:** In `ThreatsPage`, gate the inline "Quarantine" `<Button>` (`~183`) behind `can('quarantine.manage')`. In `DecisionReviewPanel`, gate the FP/FN verdict buttons behind `can('decisions.verdict')` (server `POST /decisions/{id}/verdict` editor@1347). `DecisionReviewPanel` is a shared component (also used by `AuditTrailPage`, `ThreatsPage`) — add the gate inside the panel so every mount inherits it.
- **Footguns:** `DecisionReviewPanel` currently hardcodes `operator_id:'dana.reyes'` (`:22`) — that dead stub removal is **M-G3 D8** (`40:500`), NOT this task; do not touch the request body here beyond the render gate, or you collide with the M-G3 diff. The panel is used in 2+ places — gate once in the component, don't gate at each call-site.
- **Unit:** `DecisionReviewPanel.test.tsx` — `editor` → verdict buttons rendered; `viewer` → absent. `ThreatsPage.test.tsx` — `admin` → Quarantine button present; `viewer` → absent, rows still expand to `DecisionTrace`.
- **Integ:** G2.11 (verdict + both quarantine routes mapped).

---

### G2.5 — Gate agent inventory + import controls (`agents.write`)

- **Touches:** `web/console/src/features/agents/AgentInventoryPage.tsx` — attach control @`~97`, detach control @`~122/133`, `useDetachPolicy`@`:34`; `web/console/src/features/agents/AttachPolicyModal.tsx:70` (Attach confirm `<Button>`, `useAttachPolicy`@`:28`); `web/console/src/features/import/ImportAgentsPage.tsx` (the import `<Button>` driving `useImportAgents`).
- **Change:** Gate attach/detach on `AgentInventoryPage` and the confirm in `AttachPolicyModal` behind `can('agents.write')` (server `POST /agents/{id}/policies`@1302, `DELETE`@1328, editor). Gate the Import action on `ImportAgentsPage` behind `can('agents.write')` (server `POST /discovery/import`@1007, editor). The discovery review **table** stays visible (read); only the import mutation hides.
- **Footguns:** Row click → `agentDetailPath` (`AgentInventoryPage.tsx:81`) is navigation, not a mutation — leave ungated. `AttachPolicyModal` also renders a "create policy" nav button (`:81`) — that's navigation to the editor (itself gated by G2.2's `policies.write`), don't double-gate it under `agents.write`.
- **Unit:** `AgentInventoryPage.test.tsx` — `editor` → attach/detach present; `viewer` → absent, agent rows still navigable. `ImportAgentsPage.test.tsx` — `viewer` → Import button absent, discovery table rendered.
- **Integ:** G2.11 (three agent/discovery routes mapped to `agents.write`).

---

### G2.6 — Gate cloud-connection controls (`connections.write`, `connections.operate`)

- **Touches:** `web/console/src/features/connect/ConnectAccountPage.tsx:88` (`useCreateConnection`), `create.mutate` @`:122`; `scan.mutate` @`:142` (`useScanConnection`@`:89`); the "Connect & scan" `<Button>` @`:282`; the test-connection call-site (`connectionsApi.test` via its hook).
- **Change:** Gate the create step (`:122`, choose-tile → `create.mutate`) and any PUT/DELETE connection edit behind `can('connections.write')` (admin; `POST`@1107/`PUT`@1140/`DELETE`@1236). Gate the **test** and **scan** actions behind `can('connections.operate')` (editor; `POST /connections/{id}/test`@1178, `/scan`@1216). The wizard read/preview stays visible.
- **Footguns:** The wizard is multi-step — an editor (operate but not write) can test/scan an *existing* connection but not create a new one. If create is hidden, don't leave the "Connect & scan" combined button (`:282`) live, or an editor triggers a create they can't complete (server 403 on `POST /connections`); split the gate so the combined button requires `connections.write`. Do NOT gate the "coming soon"/GCP tile logic (that's M-G3 G3.5).
- **Unit:** `ConnectAccountPage.test.tsx` — `admin` → create + test/scan present; `editor` → test/scan present, create/"Connect & scan" absent; `viewer` → all mutating controls absent.
- **Integ:** G2.11 (five connection routes mapped: 3 write-admin, 2 operate-editor).

---

### G2.7 — Verify residual-agents read floor (`identity.residual.read`, viewer) — no new gate

- **Touches:** `web/console/src/features/identity/ResidualAgentsPage.tsx:12` (`useResidualAgents`); `rbac.ts:39` (`identity.residual.read`→`viewer`, already present).
- **Change:** This page is read-only (WS-B fallback window) and the cap already maps to the `viewer` floor. No control-gate to add — **verify** the page renders for a `viewer` and that the nav item is not hidden by a stricter cap. If the nav config gates the route, confirm it uses `identity.residual.read` (viewer), matching server `GET /identity/residual-agents` (`tenancy_routes.py:117`, any-role).
- **Footguns:** Do NOT add a mutating "retire" control here — the retire route does not exist server-side (§7.1e, GET-only) and is a WS-N/WS-M-backend-OR-roadmap prerequisite, not WS-G.
- **Unit:** `ResidualAgentsPage.test.tsx` — `viewer` → page renders the residual list, no mutation control present.
- **Integ:** G2.11 completeness allowlist keeps `GET /identity/residual-agents` mapped (viewer floor).

---

### G2.8 — Fail-secure UI degrade on auth changes (D6, §5.4 `40:291-298`)

- **Touches:** `web/console/src/lib/http.ts` — `request()`@`:126`, `ApiException`@`:18`, `reauthenticate()`@`:42`; `web/console/src/lib/query/useMe.ts` (add `refetchOnWindowFocus`); a shared toast/error surface.
- **Change:** Four degrade rules: (1) **no-role/insufficient** → control not-rendered (G2.2–G2.7 already do this). (2) **dependency-absent** (feature-probe `ApiException.status ∈ {404,501}`) → PARTIAL banner, not a crash (banner component is shared with M-G3; here just the 403 path). (3) **403 on a mutation** → toast the sanitized message + `queryClient.invalidateQueries(['me'])` (force role re-read; key = `queryKeys.auth.context()`). (4) **demoted operator** → `useMe` gains `refetchOnWindowFocus:true`; ≤5-min staleness accepted (`staleTime` stays `5*60_000`, `useMe.ts:16`). On refetch showing a lower role, gated controls disappear on next render.
- **Footguns:** Do NOT surface the raw server exception string in the toast — pass `normalizeErrorBody` (`http.ts:87`) output only (engineering error-contract rule: customer-safe message + correlation id, never a stack/host/query). A 403 must NOT trigger `reauthenticate()` (`http.ts:42`, which is for 401/opaqueredirect) — a 403 means *authenticated-but-forbidden*; logging the user out on a forbidden mutation is a footgun. Invalidate `['me']`, don't hard-navigate.
- **Unit:** `http.degrade.test.ts` — a mocked 403 response → toast fired with sanitized body + `['me']` invalidated, `reauthenticate` NOT called; a 401 → `reauthenticate` path taken.
- **Integ:** `useMe.refetch.test.tsx` — window `focus` event triggers `meApi.get` refetch; a role change from `admin`→`viewer` hides a previously-shown control on re-render.

---

### G2.9 — D3 client↔server role-parity + completeness Vitest (consumes backend fixture)

- **Touches:** new `web/console/src/lib/rbac.parity.test.ts`; consumes `web/console/src/lib/__fixtures__/role-model.json` (**emitted by the WS-N/WS-M backend generator — PREREQUISITE, not built here**); reads `rbac.ts` `RANK`/`MIN_ROLE`/`PLATFORM_MIN`.
- **Change:** Vitest asserts: (a) `RANK` order === fixture `role_order` (mirror of `deps.py:39 _ROLE_ORDER` = `("viewer","editor","admin","owner")`); (b) for every server route in the fixture, `MIN_ROLE[mappedCap] === fixture.route.min_role` (or `PlatformCapability` for `require_platform` rows); (c) **completeness** — every fixture route carrying `require_role`/`require_platform` (walk of BOTH `routes.py` AND `tenancy_routes.py`) has a mapped client `Capability`/`PlatformCapability`, else it must be in an explicit `NO_CONSOLE_ROUTES` allowlist (e.g. `POST /rollback`@2095, `/rollback/conversation/{id}`@2171 — roadmap, admin, no control). Fail the test if any `require_role` route is neither mapped nor allowlisted.
- **Footguns:** WS-G owns ONLY the Vitest assertion side (`40:270` — parity generator is WS-N/WS-M backend). If `role-model.json` is absent at test time (backend prereq not landed), the test must **fail loud** ("fixture missing — backend D3 generator not run"), NOT skip/pass — a silent skip re-opens the parity drift this gate exists to catch. The `NO_CONSOLE_ROUTES` allowlist may NEVER hold a *tenant-partitioned read* (that's the D10 read-side gate, WS-N-owned) — this allowlist is only for deliberately console-less **mutations**.
- **Unit:** `rbac.parity.test.ts` (the test IS the deliverable) — passes against the committed fixture; add a negative fixture (`role-model.bad.json` with a mismatched `min_role`) proving the assertion fails.
- **Integ:** cross-checked by the backend generator's own pytest (fails on uncommitted `role-model.json` diff) — named in the prerequisite, run in the backend suite.

---

### G2.10 — DELETE `TenantSwitcher` + its TopBar mount (§5.5 `40:300-314`)

- **Touches:** delete `web/console/src/components/ui/TenantSwitcher.tsx` (whole file, 83 lines); `web/console/src/components/ui/TopBar.tsx:12` (import) + `:117` (`<TenantSwitcher />` render).
- **Change:** Remove both TopBar lines and delete the file. The in-session tenant-switch UI is gone; tenant is bound org-first (G2.11/G2.12). The switch-race apparatus collapses to cheap defense-in-depth (the server 403 at `deps.py:440` remains the boundary).
- **Footguns:** `TenantSwitcher.tsx:4` imports `useMe` but the header wiring (`tenant.ts` / `X-Aegion-Tenant` in `http.ts:158`) is **independent** of the switcher UI — deleting the switcher must NOT delete `tenant.ts` (G2.11 rewrites it). Grep for any other importer before deleting (`grep -rn TenantSwitcher src`) — currently only `TopBar.tsx:12`. Do NOT touch `AccountMenu.tsx`'s cosmetic tenant chip (that's M-G1 `tenantOf` containment).
- **Unit:** `TopBar.test.tsx` — TopBar renders with no `TenantSwitcher` in the DOM (query by its test-id/role returns null), and `tsc -b` has no dangling import.
- **Integ:** `orgflow.test.tsx` (G2.12) asserts no tenant-selector control exists anywhere in the mounted shell.

---

### G2.11 — Migrate active-tenant binding to per-tab `sessionStorage` + fail-safe (§C.4 `40:1001-1007`)

- **Touches:** `web/console/src/lib/tenant.ts` — `STORAGE_KEY`@`:14` (currently `'aegion:active-tenant'` in **`localStorage`**), `readInitial()`@`:19`, `setActiveTenant()`@`:32`, `tenantHeader()`@`:50`; `web/console/src/lib/http.ts:158` (calls `tenantHeader()` — unchanged); `reauthenticate()`@`http.ts:42` (add clear-on-logout).
- **Change:** Rename key to `'aegion.activeTenant'` and switch backing store `localStorage`→`sessionStorage` (per-tab, cleared on tab close — the ADR-039 contract). `tenantHeader()` continues to emit `X-Aegion-Tenant` when set. **Absent/lost value → fail SAFE**: for a resolved single-tenant operator the server picks the sole membership (fine), but for a multi-membership operator an absent value must route back to the org page (G2.12), NEVER a silent primary-fallback bind. Add `clearActiveTenant()` and call it from `reauthenticate()` (`http.ts:42`) so logout clears the tenant.
- **Footguns:** Do NOT keep `localStorage` — it persists across tabs and defeats per-tab org selection for MSSP/partner operators (a stale other-tenant value would ride along). Do NOT synthesize a primary fallback for multi-membership (`40:1005`) — the server already 403s a non-member `X-Aegion-Tenant` (`deps.py:440`), but a silent wrong-tenant bind for an operator with 2 memberships is the exact cross-tenant footgun ADR-039 closes. A **corrupted** stored value → send it, let the server 403, then fail safe to org page (do not trust/parse it client-side as authority — it's a preference, `tenant.ts:9`).
- **Unit:** `tenant.test.ts` — `setActiveTenant('t_globex')` writes `sessionStorage['aegion.activeTenant']` (not localStorage); `clearActiveTenant()` empties it and `tenantHeader()==={}`; a fresh tab (`sessionStorage` empty) → `getActiveTenant()===null`.
- **Integ:** `orgflow.test.tsx` — reload with sessionStorage set → `X-Aegion-Tenant` re-attached; absent + multi-membership `MeContext` → redirect to org page (no header sent); logout → sessionStorage cleared.

---

### G2.12 — Org-first entry client: stash resolved tenant → Cognito, fail-safe (§C.1–C.4, ADR-039) — consumes D14

- **Touches:** the standalone static org page's client script (served by D14 at a non-`/v1` public path, e.g. `/org` or `splash`-style — **hosting + `resolve_org` endpoint + ALB rule = D14 prerequisite**); `web/console/src/lib/tenant.ts` (`setActiveTenant`, from G2.11); app boot/router guard in `web/console/src/app/router.tsx` (redirect-to-org when a multi-membership operator has no bound tenant).
- **Change:** Client behavior of the org-first flow: (1) unauth operator on the static org page types org name → `fetch` the D14 `resolve_org(org)` endpoint → on hit, `setActiveTenant(tenant_id)` (stash to `sessionStorage`), then `window.location = <Cognito hosted-UI URL>`; (2) on **miss**, show the friendly "org not found — check spelling" message and **stay on the org page** (never advance to Cognito with nothing stashed); (3) after Cognito returns, the server re-validates `X-Aegion-Tenant` ∈ memberships (`deps.py:404-440`, already built) — client does nothing but send the header; (4) router guard: a signed-in multi-membership operator (`MeContext.memberships.length > 1`) with no bound tenant → redirect to the org page.
- **Footguns:** The org page is **standalone static HTML, NOT a React-SPA route** (`40:960`) — an SPA route can't fetch its own hashed `/assets/*` bundle under the priority-10 auth rule; do not add it to `routes.ts`/`lazyPages.ts`. `resolve_org` returns **only** `tenant_id` (derived slug) — never echo the typed name or any tenant data/counts/members (`40:970`); the client must not display anything beyond the resolved-id-driven redirect. `resolve_org` is on a **non-`/v1`** path (priority-5 `ConsoleApiListenerRule` @compute_stack.py:967 denies unauth `/v1/*`) — the client must call the D14 path (e.g. `/public/resolve-org`), not `/v1/...`. Change-tenant = logout→org page→re-login (no in-session switch — the switcher is deleted in G2.10). Miss must be treated as a real "not found" (founder 2026-07-08 ACCEPTED org-NAME enumeration; the earlier miss==hit rule is DROPPED) — do not fabricate a fake success.
- **Blocked-on:** D14 `resolve_org` contract shape (path, response `{tenant_id}`, rate-limit/error semantics). Build the client stub against the documented contract; integration-verify once D14 lands.
- **Unit:** `orgEntry.test.ts` — mocked `resolve_org` hit → `setActiveTenant` called with returned `tenant_id` + redirect URL constructed to Cognito; mocked miss → no `setActiveTenant`, no redirect, friendly message shown.
- **Integ:** `orgflow.test.tsx` — full sim: org submit (hit) → sessionStorage bound → (mock) return → `MeContext` with matching membership → shell renders bound tenant, `X-Aegion-Tenant`===resolved id, no `TenantSwitcher` in DOM; non-member header → server 403 → fail-safe redirect to org page; single-membership operator with null preference → server picks sole membership (no redirect-loop regression).

---

**Milestone acceptance (M-G2):** `npm run build` (tsc-b + vite) + `npm run lint` green; `npm run test` green (all Vitest above); the D3 parity test passes against the backend-emitted `role-model.json` and fails on a seeded mismatch; a `viewer` sees zero mutating controls across all six features while the server still enforces `require_role`; no `TenantSwitcher` in the DOM; org-first flow binds tenant via `sessionStorage['aegion.activeTenant']` and fails safe to the org page when absent for a multi-membership operator.

**Cross-references:** Implements FR-13.3 · Decisions ADR-039 (org-first), ADR-038 (D10 lane) · Shared contracts: `Capability`/`MIN_ROLE` (rbac.ts) ↔ `require_role`/`_ROLE_ORDER` (deps.py), `X-Aegion-Tenant` header, `resolve_org` (D14) · Upstream: lld/40 §5 + Appendix C · Sibling: M-G1 (`tenantOf` containment, ESLint rule + `AccountMenu` chip — do not collide), M-G3 (D8 `operator_id` stub removal, winning_source facet).

---

## Milestone M-G3 — Exhaustive FR-13.2 customer dashboard set (§6, §7)

Promote every embedded FR-13.2 component to a routed, tenant-scoped page; wire each to its §7 endpoint via TanStack Query; add the 2 genuinely-missing views (Activity, Usage); label all polled feeds "near-real-time (≤15s pull)" — **no WebSocket/SSE anywhere**. Fail-secure PARTIAL banner when a dep API is absent (`ApiException.status ∈ {404,501}`). Tenant scoping is server-side (`resolve_operator_tenant` + `X-Aegion-Tenant`); the client MUST NOT reintroduce `tenantLabelForDisplay` into any query/gate — that is M-G1's ESLint gate. RBAC gating on mutating controls is wired here per the M-G2 capability map. Backend field-adds the UI binds but does NOT own are listed as **PREREQUISITES (owner WS-N/WS-M-backend)**, not build tasks.

**Naming note:** frontend tests are Vitest + Testing Library under `web/console/src/**/__tests__/*.test.tsx`; backend regressions are pytest under `src/security-controller/tests/`.

---

### M-G3.0 — Route + nav + lazy-chunk scaffolding for the new/promoted views (D4)

- **Touches:** `web/console/src/app/routes.ts:2-19` (add constants), `web/console/src/app/routes.ts:21-27` (add path builders), `web/console/src/app/lazyPages.ts:10-48` (add lazy decls), `web/console/src/app/router.tsx:10-24` (imports), `router.tsx:37-57` (route rows), `web/console/src/app/navConfig.ts` (nav groups — Monitor / Forensics(NEW) / Account(NEW)).
- **Change:** Add route constants `activity:'/activity'`, `decisionDetail:'/decisions/:sessionId/:requestId'`, `sessionDetail:'/sessions/:sessionId'`, `usage:'/usage'`. Add path builders `decisionDetailPath(sessionId, requestId) => '/decisions/${enc(sessionId)}/${enc(requestId)}'`, `sessionDetailPath(sessionId)`, `usagePath()`. Add lazy `ActivityPage`, `DecisionDetailPage`, `SessionForensicsPage`, `UsagePage`; register in `router.tsx` under `AppLayout`. Delete/repurpose the two dead `PlaceholderPage` rows (`router.tsx:43,49` — `/deployments`, `/deploy`) only if founder confirms; otherwise leave them (out of M-G3 scope).
- **Footguns:**
  - Decision-detail route MUST be `:sessionId/:requestId` (composite PK). `:requestId` alone CANNOT build the trail query — `routes.py:554` keys on `{session_id}#{request_id}`. Do NOT collapse to `/decisions/:requestId`.
  - The `/sessions/:sessionId` param route MUST be registered — but there is NO existing `/sessions` list route; Session-forensics is reached from Threats/Activity row links and Quarantine, not a nav item, unless founder adds a Forensics nav group.
  - Static routes before param routes (precedent `router.tsx:51` comment): none of the 4 new paths collide, but keep `/usage` and `/activity` as literals.
- **Unit:** `web/console/src/app/__tests__/routes.test.ts::builds decisionDetailPath with encoded session+request ids` (assert `decisionDetailPath('s 1','r/2')` === `/decisions/s%201/r%2F2`).
- **Integ:** `web/console/src/app/__tests__/router.test.tsx::renders ActivityPage/DecisionDetailPage/SessionForensicsPage/UsagePage at their paths` (MemoryRouter render, assert each lazy page mounts, no 404 fallback).

---

### M-G3.1 — Overview landing (PROMOTE/VERIFY — exists)

- **Touches:** `web/console/src/features/overview/OverviewPage.tsx:26` (exists), hooks `useOverview`, `usePlatformDistribution`, `useDecisionsTimeseries`, `useDecisions`; components `KpiGrid.tsx`, `LiveActivity.tsx`, `PlatformDistribution.tsx`.
- **Change:** This view EXISTS and is routed at `/` and `/overview` (`router.tsx:37,41`). NO rebuild. Task = **verify tenant-scoping**: it binds `GET /v1/metrics/overview` + `GET /v1/decisions`, both operator-bound server-side (D10/D11 LANDED @ `761bb88`). Confirm `LiveActivity` uses `useDecisions` with the 15s poll and carries the "near-real-time (≤15s pull)" label (add if missing). No client tenant filtering — the server SEARCH-scopes by `set_current_tenant`.
- **Footguns:** Do NOT add a client-side `tenant_id` filter param to `/metrics/overview` — the server derives tenant from `X-Aegion-Tenant`; passing a client tenant is ignored and misleads reviewers. Overview tiles are per-tenant already (D11 `_search_tenant`).
- **Unit:** `overview/__tests__/OverviewPage.test.tsx::renders KPI tiles + near-real-time label on LiveActivity`.
- **Integ:** `overview/__tests__/OverviewPage.tenant.test.tsx::tenant-A MeContext → overview query issued with no client tenant filter (server-scoped), renders tiles from mocked overview(tenant_id=A) sum` (mock `meApi.get` role/tenant A; assert fetch to `/v1/metrics/overview` carries `X-Aegion-Tenant: t_acme`, not a query param).

---

### M-G3.2 — Activity / live-decision feed (BUILD — missing, G3.1)

- **Touches:** NEW `web/console/src/features/activity/ActivityPage.tsx`; reuse `web/console/src/lib/query/useDecisions.ts:11` (`refetchInterval:15_000` @ `:20`); route from M-G3.0; row-link via `decisionDetailPath(session_id, request_id)`.
- **Change:** Build a routed `ActivityPage` binding `GET /v1/decisions` (cursor) through `useDecisions({})`. Render a paginated table (reuse the Threats/Audit row layout); "Load more" wired to `fetchNextPage`/`getNextPageParam` (`useDecisions.ts:19`). Each row is a `Link` to `decisionDetailPath(d.session_id, d.request_id)`. Header label literal: **"near-real-time (≤15s pull)"**. Gate: read-only view, no RBAC gate needed (any authenticated operator).
- **Footguns:**
  - Do NOT introduce a socket/EventSource — the label is a pull cadence, not streaming. `useDecisions` already polls at 15s.
  - Row link MUST pass BOTH `session_id` AND `request_id` (composite PK); a link with only `request_id` breaks the detail query (see M-G3.3 footgun).
  - `DecisionItem` (`api.ts:150`) has `session_id`+`request_id` — use those, not the concatenated `decision_id` (`{session_id}:{request_id}`) which is `:`-joined and would need splitting.
- **Unit:** `activity/__tests__/ActivityPage.test.tsx::rows link to decisionDetailPath(session_id,request_id)` and `::renders near-real-time (≤15s pull) label`.
- **Integ:** `activity/__tests__/ActivityPage.pagination.test.tsx::cursor pagination loads a 2nd page via next_token and appends rows` (mock two `/v1/decisions` responses with `next_token`).

---

### M-G3.3 — Threats per-detector facet on winning_source (EXTEND — exists, G3.2)

- **Touches:** `web/console/src/features/threats/ThreatsPage.tsx:25` (exists), `ThreatsPage.tsx:189-190` (quarantine call — has dead `operator_id`), hooks `useDecisions`/`useSessions`/`useQuarantine`.
- **Change:** Add a **winning-source facet** filter to the existing Threats Explorer. Drive the facet list **from the API response values, not a frontend constant** — collect distinct `winning_source` across loaded rows; fallback label `source.replace(/^sentra\./,'')`. Wire the quarantine mutating control behind `useCan('quarantine.manage')` (M-G2 map; admin) — hide, don't disable.
- **Footguns:**
  - **`DecisionItem` (`api.ts:150-164`) has NO `winning_source` field** — `winning_source` lives on `DecisionCombined` (`api.ts:247`, from `/sessions/{id}/decisions`), not on the `/v1/decisions` row. Faceting on `winning_source` at the Threats list therefore requires the **PREREQUISITE below** (server field-add on `/v1/decisions`) OR fall back to the existing `threat_type` facet + render the winning-source facet as PARTIAL until the field lands. Do NOT fabricate `winning_source` client-side.
  - Do NOT hardcode a `sentra.*` facet enum — a novel `sentra.<new>` source must appear as a facet automatically with the fallback label.
  - Remove the dead `operator_id:'dana.reyes'` at `ThreatsPage.tsx:190` (see M-G3.13) — server derives from `ctx.sub`.
- **PREREQUISITE (WS-N/WS-M-backend):** add `winning_source` (and optionally `matched_rule`) to each `DecisionItem` returned by `GET /v1/decisions` (`routes.py:600`), sourced from the combined verdict. **Until landed, the facet degrades to PARTIAL.**
- **Unit:** `threats/__tests__/ThreatsPage.facet.test.tsx::facet list derives from API winning_source values with sentra.<x> fallback label` (inject `winning_source:'sentra.brandnew'` → facet chip "brandnew", no code change).
- **Integ:** `threats/__tests__/ThreatsPage.gate.test.tsx::viewer sees no Quarantine control; admin sees it` (mock `useCan`).

---

### M-G3.4 — Decision detail — bind WS-D `/trail` (BUILD client + PROMOTE component, G3.3)

- **Touches:** NEW `web/console/src/features/forensics/DecisionDetailPage.tsx`; NEW client method `sessionsApi.trail` in `web/console/src/lib/api/sessions.ts` (no trail client exists today — confirmed: `sessions.ts` only has `list`/`listPage`/`release`/`decisions`); NEW hook `useSessionTrail` in `web/console/src/lib/query/useSessions.ts`; NEW type `SessionTrail` in `web/console/src/types/api.ts` (WS-D-owned shape); reuse `components/decisions/DecisionReviewPanel.tsx` (FP/FN); optionally reuse `DecisionTrace.tsx`.
- **Change:**
  - Add `sessionsApi.trail(sessionId, requestId) => http.get('/sessions/${enc(sessionId)}/trail', { request_id: requestId })` binding `GET /v1/sessions/{id}/trail?request_id=` (`routes.py:566`, operator-bound, LIVE — no longer 401/flag-gated per digest).
  - Add `SessionTrail` type mirroring the WS-D four-bucket trail (LLD-33). Coordinate exact shape with WS-D owner; treat the fetched body as data — validate the buckets exist before rendering.
  - Build `DecisionDetailPage` reading `useParams` `sessionId`+`requestId`, render the trail; embed `DecisionReviewPanel` for the row's `DecisionItem`, gated `useCan('decisions.verdict')` (M-G2; editor).
- **Footguns:**
  - Route param is `:sessionId/:requestId` — build the query from BOTH. A `request_id`-only route can't key `routes.py:554`'s composite PK.
  - Keep `DecisionReviewPanel` render behind `decisions.verdict` (editor) — do not render FP/FN controls to viewers.
  - PARTIAL-degrade: if `/trail` returns 404/501 (older session, pre-WS-D), show the PARTIAL banner and fall back to `DecisionTrace` (`/sessions/{id}/decisions`), never a blank page.
- **PREREQUISITE (WS-D):** `SessionTrail` type shape is WS-D-owned; the `/trail` endpoint is LIVE at `routes.py:566` — WS-G only wires the client.
- **Unit:** `forensics/__tests__/DecisionDetailPage.test.tsx::binds /sessions/:id/trail?request_id= from both route params`.
- **Integ:** `forensics/__tests__/DecisionDetailPage.partial.test.tsx::/trail 404 → PARTIAL banner + DecisionTrace fallback, no blank`; `::verdict panel hidden for viewer, shown for editor`.

---

### M-G3.5 — Session forensics page (BUILD — missing, G3.4)

- **Touches:** NEW `web/console/src/features/forensics/SessionForensicsPage.tsx` at `/sessions/:sessionId`; reuse `web/console/src/lib/api/sessions.ts` — `sessionsApi.list` (`SessionInfo`, `sessions.ts:19`) + `sessionsApi.decisions()` (`SessionDecisionsResponse`, `sessions.ts:38`); reuse `DecisionTrace.tsx`.
- **Change:** Build a routed page keyed on `sessionId`: header from the session's `SessionInfo` (trust_score, quarantine_status, counts — `api.ts` `SessionInfo`), body = per-request list from `sessionsApi.decisions(sessionId)` rendered via `DecisionTrace`. Each request row links to `decisionDetailPath(sessionId, request_id)`.
- **Footguns:**
  - `sessionsApi.list` returns the whole (paged) session set; to fetch one session's header you may need to filter client-side by `session_id` OR there is no single-session GET — do NOT invent `GET /v1/sessions/{id}`; it does not exist. Derive the header from the `decisions` response's first request + `SessionInfo` if reachable, else render header PARTIAL.
  - Server tenant-scopes `/sessions*`; no client tenant filter.
- **Unit:** `forensics/__tests__/SessionForensicsPage.test.tsx::renders per-request trace from sessionsApi.decisions`.
- **Integ:** `forensics/__tests__/SessionForensicsPage.tenant.test.tsx::non-member session → 403 handled, PARTIAL/redirect not blank`.

---

### M-G3.6 — Agent Inventory + Agent Detail (PROMOTE/GATE/FIELD-MAP — exists)

- **Touches:** `web/console/src/features/agents/AgentInventoryPage.tsx:25` (exists), `AgentDetailPage.tsx:30` (exists — Overview + Flow tabs @ `AgentDetailPage.tsx:26`, `AgentFlowTab.tsx`), `AttachPolicyModal.tsx`, `useDetachPolicy`, `useAgentDetail`/`useAgentTools` (`lib/query/useAgents`).
- **Change:** Both views EXIST and are routed (`router.tsx:44,45`). NO rebuild. Tasks:
  1. Gate the attach/detach-policy controls behind `useCan('agents.write')` (M-G2; editor) — currently ungated (per inventory: only `PolicyLibraryPage` uses `useCan`). Hide, don't disable.
  2. **Field-map agent activity-status client-side** (§7.1a PARTIAL): `GET /v1/agents` `status` = ECS state `running/starting/stopped/not_found/unknown` (`agent_service.py:687`) ≠ canvas Active/Idle/Offline. Add a client map: `running`→Active, `stopped`/`not_found`→Offline, running-but-no-recent-traffic→Idle (not Active). `denied_pct` is client-computed already (`agent_service.py:642-644`) — keep.
  3. Add a Tools tab and a Policy tab surfacing `useAgentTools` + attached policies if not already present (`AgentDetailPage.tsx:26` currently shows Overview+Flow — verify; add Tools/Policy tabs if missing).
- **Footguns:** Do NOT block on a server `activity_status` field — the client map is the accepted resolution (§7.1a "or client map"). Do NOT show ECS `unknown` as "Active".
- **PREREQUISITE (optional, WS-N/WS-M):** server `activity_status` field on `GET /v1/agents` — if landed, prefer it over the client map.
- **Unit:** `agents/__tests__/activityStatus.test.ts::maps running→Active, stopped/not_found→Offline, running+no-traffic→Idle`.
- **Integ:** `agents/__tests__/AgentInventoryPage.gate.test.tsx::viewer sees no attach/detach; editor sees them`.

---

### M-G3.7 — Topology (VERIFY-OR-ROADMAP — exists as page, backend absent)

- **Touches:** `web/console/src/features/topology/TopologyPage.tsx` (exists — `FlowSankey`, `buildFleetFlow`/`computeHeatPath` from `lib/flowGraph.ts`), route `router.tsx:46`.
- **Change:** The page EXISTS but there is **ZERO `/v1/topology` route** in `app/api/` (digest §7.2, verified). Task = make the view **honest ROADMAP**: render a "roadmap" badge + explicit "sample data" marker; it must NOT issue a live read to a nonexistent `/v1/topology`. Today it builds the Sankey from `useDecisions` client-aggregation (`buildFleetFlow`) — if that is the source, label it "derived from decision feed (near-real-time ≤15s)"; if it expects a topology endpoint, mark ROADMAP and gate the live read off.
- **Footguns:** Do NOT wire `GET /v1/topology` — it returns 404 (no route). A live fetch to it fails the "no read to nonexistent route" §7.2 test. Sample/derived data MUST be visibly marked.
- **PREREQUISITE (ROADMAP, WS-N/WS-M-backend if built):** `GET /v1/topology` (cloud→agent→tool aggregated volume+allowed+blocked).
- **Unit:** `topology/__tests__/TopologyPage.test.tsx::renders roadmap/sample badge and issues no fetch to /v1/topology`.
- **Integ:** covered by the §7.2 roadmap suite in M-G3.14.

---

### M-G3.8 — Policy Library + Policy Detail (VERIFY/GATE — exists; Cedar/JSON per §7.1c)

- **Touches:** `web/console/src/features/policies/PolicyLibraryPage.tsx:42` (exists — already uses `useCan` @ `:16,47`), `PolicyDetailPage.tsx` (exists — YAML/CEDAR/JSON toggle already present @ `:36-38`, `:74`, `policyFormat.ts`), `PolicyEditorPage.tsx`.
- **Change:** Both views EXIST and Policy Detail ALREADY has the CEDAR/YAML/JSON toggle (`PolicyDetailPage.tsx:36-38`). NO rebuild. Tasks:
  1. Verify/extend RBAC gating on Library: delete → `useCan('policies.delete')` (admin, M-G2 new cap); create/edit/status → `useCan('policies.write')` (editor). `PolicyLibraryPage` already calls `useCan` — extend to the new `policies.delete` cap.
  2. §7.1c PARTIAL: `get_policy_by_id` (`routes.py:1582`, `include_content=true`) returns metadata + authored YAML from S3 only — **no compiled Cedar/JSON body**. So the CEDAR/JSON tabs must render from `renderCedar`/`renderContent` (`policyFormat.ts`) which derive from `policy.content` client-side; if a tab needs a compiled body the server doesn't return, render PARTIAL — **never a client-fabricated Cedar body**.
- **Footguns:** Do NOT fabricate compiled Cedar/JSON when the server returns only YAML — show PARTIAL for those tabs (§15 `40:781`). `policyFormat.renderCedar` deriving a *display* form of the authored policy is fine; a fabricated *compiled enforcement* body is not.
- **PREREQUISITE (WS-N/WS-M-backend, or roadmap):** compiled-source read on `get_policy_by_id` (new field OR `?format=cedar|json`) to make CEDAR/JSON tabs live rather than derived.
- **Unit:** `policies/__tests__/PolicyDetailPage.format.test.tsx::YAML tab live; CEDAR/JSON derive from content, PARTIAL when compiled body absent, no fabricated body`.
- **Integ:** `policies/__tests__/PolicyLibraryPage.gate.test.tsx::viewer no create/delete; editor create not delete; admin delete visible`.

---

### M-G3.9 — Connect Cloud + Import Agents (VERIFY/GATE — exists; grant copy-only)

- **Touches:** `web/console/src/features/connect/ConnectAccountPage.tsx` (exists — `GrantAccessCard.tsx`, `GrantAzureAccessCard.tsx`, `CopyField.tsx`, `cloudCatalog.ts`), `web/console/src/features/import/ImportAgentsPage.tsx` (exists — monitor/enforce mode, `ImportResultDrawer.tsx`), hooks `useConnections`, `useDiscoveredAgents`/`useImportAgents`.
- **Change:** Both EXIST and are routed (`router.tsx:47,48`). NO rebuild. Tasks:
  1. Gate mutating controls: Connect create/edit/delete → `useCan('connections.write')` (admin, new); test/scan probes → `useCan('connections.operate')` (editor, new). Import (`POST /discovery/import`) → `useCan('agents.write')` (editor).
  2. Verify **grant is copy-only** (D9 footgun): the console shows the CFN trust template + AssumeRole probe copy text; it NEVER applies a grant. GCP is "coming soon" (`available:false` in `cloudCatalog.ts`).
  3. Import enforcement_mode selector must pass `enforcement_mode` = `monitor|enforce` to `POST /discovery/import` (`routes.py:1007`) — verify the param is forwarded (already a §7.3 covered import param).
- **Footguns:** Console MUST NOT call any AWS/Azure grant-apply API — copy-only. Do NOT re-enable the descoped `POST /discovery/scan` (`discovery.ts:41` — descoped). GCP card stays `available:false` (coming-soon), no live connect.
- **Unit:** `connect/__tests__/GrantAccessCard.test.tsx::renders copy fields only, no apply/mutation call fired`; `connect/__tests__/cloudCatalog.test.ts::GCP available:false coming-soon`.
- **Integ:** `import/__tests__/ImportAgentsPage.test.tsx::enforcement_mode monitor|enforce forwarded to POST /discovery/import`; `connect/__tests__/ConnectAccountPage.gate.test.tsx::viewer no connect/test; editor test; admin create`.

---

### M-G3.10 — Quarantine (VERIFY/GATE — exists; why-trace per §7.1d)

- **Touches:** `web/console/src/features/quarantine/QuarantinePage.tsx` (exists — infinite scroll `useInfiniteSessions`, release override `useReleaseQuarantine`, `DecisionTrace`).
- **Change:** EXISTS and routed (`router.tsx:55`). NO rebuild. Tasks:
  1. Gate the release-override control behind `useCan('quarantine.manage')` (admin, M-G2 new). Hide, don't disable.
  2. §7.1d why-trace: the store HAS `quarantine_reason`+`quarantine_operator` (`session_manager.py:394`) but `_format_session_for_api` (`session_manager.py:636`) surfaces neither origin (auto vs operator) nor the ordered trigger-signal list. So the "why quarantined" panel must **degrade to `quarantine_status` alone** until the server surfaces origin+signals; render the full why-trace only once those fields exist.
- **Footguns:** `SessionInfo` (`api.ts`) has `quarantine_status` but no `quarantine_reason`/origin/trigger-signals field — do NOT read fields that aren't in the type; degrade gracefully.
- **PREREQUISITE (WS-N/WS-M-backend):** add origin (auto vs operator) + ordered trigger-signal list to the session read (`_format_session_for_api` `session_manager.py:636`).
- **Unit:** `quarantine/__tests__/QuarantinePage.gate.test.tsx::viewer/editor no release; admin release visible`.
- **Integ:** `quarantine/__tests__/QuarantinePage.whytrace.test.tsx::renders quarantine_status only when origin+signals absent; full why-trace when present`.

---

### M-G3.11 — Audit trail (VERIFY — exists)

- **Touches:** `web/console/src/features/audit/AuditTrailPage.tsx:22` (exists — filter + session/text search, `DecisionTrace` + `DecisionReviewPanel`, `useDecisions`).
- **Change:** EXISTS and routed (`router.tsx:57`). NO rebuild. Tasks: verify it binds `GET /v1/decisions` (LIVE forensic slice) + can drill into `/sessions/{id}/trail` via the M-G3.4 client; gate the embedded `DecisionReviewPanel` behind `useCan('decisions.verdict')` (editor). Export is DEFERRED with FR-6.5 — do NOT build an export button.
- **Footguns:** Do NOT add CSV/PDF export — deferred with FR-6.5. Keep the verdict panel editor-gated.
- **Unit:** `audit/__tests__/AuditTrailPage.test.tsx::binds /v1/decisions; verdict panel editor-gated`.
- **Integ:** covered by M-G3.13 (operator_id-stub) + M-G3.4 (trail).

---

### M-G3.12 — Usage & billing (BUILD — missing, WS-H dep, PARTIAL stub, G3.6)

- **Touches:** NEW `web/console/src/features/usage/UsagePage.tsx` at `/usage`; NEW client `usageApi.get()` in NEW `web/console/src/lib/api/usage.ts` binding `GET /v1/usage`; NEW type `UsageRollup` in `web/console/src/types/api.ts` (WS-H-owned, provisional); route from M-G3.0.
- **Change:** Build a routed `UsagePage` binding `GET /v1/usage` → `UsageRollup`. **Sequencing gate:** if WS-H is NOT in the build train, feature-flag the route/nav OFF (no dark billing tab). When the endpoint returns 404/501 (stub not deployed), render the fail-secure PARTIAL banner ("Usage data not yet available"), never fabricated numbers.
- **Footguns:** Do NOT ship a visible billing nav item unless WS-H `/v1/usage` is live in the same train (digest §6.8 "no dark billing tab"). `UsageRollup` is provisional — treat the response as data, validate before rendering.
- **PREREQUISITE (WS-H):** `GET /v1/usage` returning `UsageRollup` (metered rollup). Until live, feature-flag OFF or PARTIAL.
- **Unit:** `usage/__tests__/UsagePage.test.tsx::renders PARTIAL banner on 404/501, no fabricated totals`.
- **Integ:** `usage/__tests__/UsagePage.flag.test.tsx::route/nav hidden when WS-H flag off`.

---

### M-G3.13 — Remove dead `operator_id` client stubs (D8, §6.9)

- **Touches:** `web/console/src/components/decisions/DecisionReviewPanel.tsx:22` (dead `operator_id:'dana.reyes'`), `web/console/src/features/threats/ThreatsPage.tsx:190` (dead `operator_id:'dana.reyes'`), `web/console/src/lib/api/sessions.ts:31,33` (`release(sessionId, operatorId='operator')` → `buildQuery({operator_id})`); also the types `VerdictRequest.operator_id` (`api.ts:180`) and `QuarantineRequest.operator_id` (`api.ts:191`).
- **Change:** Server overrides operator identity with `ctx.sub` — the client-sent `operator_id` is dead weight and misleadingly hardcodes `'dana.reyes'`/`'operator'`. Remove `operator_id` from the verdict body (`DecisionReviewPanel.tsx:22`), the quarantine body (`ThreatsPage.tsx:190`), and the `release` query (`sessions.ts:31-33`). Drop `operator_id` from `VerdictRequest`/`QuarantineRequest` types (`api.ts:180,191`) so `tsc -b` enforces no caller re-adds it. Verify each mutation still succeeds (server derives from `ctx.sub`).
- **Footguns:**
  - Removing the type field is the enforcement — do it, or a future caller silently re-adds the stub. But confirm the backend does NOT *require* `operator_id` in the request schema (it overrides with `ctx.sub`; digest confirms "server overrides w/ ctx.sub"). If the FastAPI model marks it required, coordinate a WS-M schema change first — do NOT ship a body the server 422-rejects.
  - `sessions.ts:31` default-arg `operatorId='operator'` must be deleted from the signature, not just the call site.
- **Unit:** `components/decisions/__tests__/DecisionReviewPanel.test.tsx::verdict body omits operator_id`.
- **Integ:** `web/console/src/lib/api/__tests__/mutations.test.ts::verdict/quarantine/release send no operator_id and still resolve success` (mock 200); backend regression `src/security-controller/tests/test_verdict_quarantine_operator.py::operator_id from ctx.sub not request body` (pytest — verify server ignores/omits client operator_id, attributes to `ctx.sub`).

---

### M-G3.14 — §7.2 ROADMAP honesty + §7.3 dual-mode regression guards

- **Touches:** `web/console/src/features/topology/TopologyPage.tsx` (M-G3.7); any Platform·Fleet-topology / System-Health surfaces (M-G4, cross-ref); `useDecisionsTimeseries` + `usePlatformDistribution` (Overview, `metrics.ts`).
- **Change:**
  1. ROADMAP guard: Topology, Fleet-topology, System-Health render a roadmap badge + "sample data" marker and issue **no live read** to nonexistent routes (`/v1/topology`, per-region health — only scalar `avg_latency_ms` @ `routes.py:863` exists).
  2. §7.3 regression: `GET /v1/metrics/decisions-timeseries` (`routes.py:910`, dual-mode) + `/metrics/platform-distribution` (`routes.py:886`) stay LIVE and correctly per-tenant — guard against re-mislabeling as roadmap/mock.
- **Footguns:** These §7.3 endpoints are ALREADY covered/live — do NOT re-task them as gaps or mark them mock.
- **Unit:** `topology/__tests__/roadmap.test.tsx::roadmap views render badge + no fetch to unbuilt routes`.
- **Integ:** `overview/__tests__/timeseries.dualmode.test.tsx::decisions-timeseries + platform-distribution render live per-tenant, not roadmap`.

---

### M-G3.15 — Milestone build gate (all M-G3 views)

- **Touches:** whole `web/console/` + `src/security-controller/tests/`.
- **Change:** Green gate for M-G3: `cd web/console && npm run build` (`tsc -b && vite build`) + `npm run lint` (eslint, incl. the M-G1 `no-restricted-syntax` rule) both pass; all Vitest suites above green; backend regressions (`test_verdict_quarantine_operator.py`, plus D10/D11 binds already in WS-N suite) green under `env -u AWS_PROFILE ... venv/bin/python -m pytest` (moto-safe env per project memory).
- **Footguns:** Do NOT let a PARTIAL/ROADMAP view issue a live read to an unbuilt route — the §7.2 tests fail on it. Backend field-add prereqs (winning_source on `/decisions`, quarantine origin+signals, compiled-policy read, agent `activity_status`, `/v1/usage`, `/v1/topology`) are **owner WS-N/WS-M-backend / WS-H / roadmap** and gate the *live* variant of their tests — the PARTIAL-degrade variant must pass now.

---

**Prerequisites rollup (NOT WS-G build tasks — owner in bold):**
- **WS-N/WS-M-backend:** `winning_source` on `GET /v1/decisions` rows (M-G3.3); quarantine origin+trigger-signals on session read `session_manager.py:636` (M-G3.10); compiled Cedar/JSON read on `get_policy_by_id` `routes.py:1582` (M-G3.8); optional agent `activity_status` field (M-G3.6); accept/ignore-not-require `operator_id` in verdict/quarantine/release request schemas (M-G3.13).
- **WS-H:** `GET /v1/usage` → `UsageRollup` (M-G3.12).
- **WS-D:** `SessionTrail` type shape for `/sessions/{id}/trail` (M-G3.4) — endpoint already LIVE `routes.py:566`.
- **ROADMAP (backend if built):** `GET /v1/topology` (M-G3.7); per-region System-Health route (M-G3.14).

---

## Milestone M-G4 — Platform global-admin console (§6.11, LLD-26 §5.5)

A separate `is_platform` route-tree (`PlatformLayout`) gated at the router root, rendering a read-only cross-tenant aggregate. **Four hard invariants** (`40:554-558`): no import, no per-tenant mutation, no tenant selector, every cross-tenant read audited via server-side `_audit_platform_read`, fleet path uses `tenant_id=None`. WS-G builds the client; fleet-mode reads + platform routes are WS-N (LANDED). Per-tenant metrics rollup + registry paging are **M-G0 backend prerequisites** (WS-N/WS-M-backend) — this milestone degrades gracefully until they land.

> **PREREQUISITES (NOT WS-G frontend — owner WS-N/WS-M-backend, tracked in M-G0):**
> - **PRE-G4-a — per-tenant metrics rollup on `/platform/tenants`** (§6.11(1), `40:539-540`): `platform_list_tenants` (`tenancy_routes.py:437`) returns only `{tenant_id,display_name,plan,status,identity_mode,created_at}` — no `blocks_24h`/`deny_rate`/`trust`/`agents`/`quarantined`/`decisions_24h`. WS-G binds these fields as OPTIONAL and renders the **Ranked-Table (6-col)** shape until they exist. Owner: WS-N/WS-M-backend.
> - **PRE-G4-b — registry paging/sort/filter** (§6.11(2), `40:541`): same handler returns `list_all()` unpaginated. WS-G binds `limit`/`cursor`/`sort`/`filter` as OPTIONAL query params; enables server-paging + row virtualization only when the response carries a `cursor`. Owner: WS-N/WS-M-backend.
> - **PRE-G4-c — consent-enforcement flip + LLD-26 §6.3 break-glass** (§6.11, `40:537`): founder-owned. `platform_read_consent_enforced` defaults **False** (`config.py:237`); drill-down is currently served + audited `consent_state="false-unenforced"`. The enforced-ON 403 path and time-boxed break-glass are NOT runnable now (mechanism absent — only the standing `platform_read_consent` boolean at `tenant_service.py:81`).

---

### G4.1 — Router-root `is_platform` split + `PlatformLayout` + `RequirePlatform` guard

**Touches:**
- `web/console/src/app/router.tsx:31-63` (add a SECOND top-level route object as a sibling to the existing `AppLayout` block).
- NEW `web/console/src/app/PlatformLayout.tsx` (platform chrome — mirrors `AppLayout.tsx:8` shell but mounts a platform-only nav rail, NO `TopBar` tenant controls).
- NEW `web/console/src/app/RequirePlatform.tsx` (route-element guard).
- `web/console/src/app/routes.ts:2-19` (add `platformOverview:'/platform'`, `platformTenants:'/platform/tenants'`, `platformTenantDetail:'/platform/tenants/:tenantId'`, `platformTopology:'/platform/topology'`, `platformHealth:'/platform/health'` + `platformTenantDetailPath = (tenantId:string) => '/platform/tenants/${encodeURIComponent(tenantId)}'`).
- `web/console/src/app/lazyPages.ts:10-48` (add lazy exports for the new platform pages).

**Concrete change:** Add a sibling route object `{ path:'/platform', element: <RequirePlatform><PlatformLayout/></RequirePlatform>, errorElement:<RouteErrorBoundary/>, children:[…] }`. `RequirePlatform` reads `useMe()` (`lib/query/useMe.ts:10`): while `isLoading` → `<LoadingState/>`; if `data?.is_platform !== true` (covers false AND absent) → `<Navigate to={ROUTES.overview} replace/>`. Fail-secure: any non-true value redirects. Because `is_platform` also drives the nav entry (G4.8), a customer never sees the link, and the guard blocks a hand-typed `/platform` URL.

**Footguns:**
- Do NOT nest platform routes under the existing `AppLayout` children — that would render the customer `NavRail`/`TopBar` (which includes tenant chrome) around a platform view, violating the "no tenant selector" invariant. It MUST be a distinct top-level route with its own layout.
- Do NOT gate on a `Capability` (RBAC role) — `is_platform` is an orthogonal boolean, NOT `owner`/`admin`. A tenant `owner` is NOT a platform operator.
- Guard must fail-secure on the `/v1/me` fallback: `me.ts:12` returns a mock with `is_platform:false`, so a `/v1/me` outage correctly denies the platform tree rather than exposing it.

**Unit** (`web/console/src/app/__tests__/RequirePlatform.test.tsx`): `redirects_non_platform_operator_to_overview`; `renders_platform_tree_when_is_platform_true`; `shows_loading_while_me_pending`; `treats_absent_is_platform_as_denied` (mock `MeContext` without the field).
**Integ** (`web/console/src/app/__tests__/platformRouter.integration.test.tsx`): with `MeContext{is_platform:false}` a MemoryRouter navigation to `/platform/tenants` lands on `/overview` (customer never mounts a platform route); with `{is_platform:true}` it mounts `FleetOverviewPage`.

---

### G4.2 — Platform API client + types + query hooks

**Touches:**
- NEW `web/console/src/lib/api/platform.ts` (`platformApi`).
- `web/console/src/types/api.ts` (add `PlatformTenantRow`, `PlatformTenantsResponse`, `PlatformTenantDetail`, `PlatformMemberRow` — NEW types).
- NEW `web/console/src/lib/query/usePlatform.ts` (TanStack hooks).
- `web/console/src/lib/queryKeys.ts` (add a `platform` key namespace: `platform.tenants(params)`, `platform.tenantDetail(id)`).

**Concrete change:** `platformApi.listTenants = (params?:{limit?:number;cursor?:string;sort?:string;filter?:string}) => http.get<PlatformTenantsResponse>('/platform/tenants', params)` and `platformApi.tenantDetail = (id:string) => http.get<PlatformTenantDetail>('/platform/tenants/${encodeURIComponent(id)}')`. Types mirror the confirmed server shapes:
- `PlatformTenantRow = { tenant_id:string; display_name:string; plan:string; status:string; identity_mode:string; created_at:string; blocks_24h?:number; deny_rate?:number; trust?:number; agents?:number; quarantined?:number; decisions_24h?:number }` — the six metric fields OPTIONAL (PRE-G4-a).
- `PlatformTenantsResponse = { count:number; tenants:PlatformTenantRow[]; cursor?:string }` (`cursor` optional, PRE-G4-b).
- `PlatformTenantDetail = { tenant_id; display_name; status; plan; identity_mode; quota:Record<string,unknown>; platform_read_consent:boolean; members:PlatformMemberRow[] }`; `PlatformMemberRow = { operator_sub:string; role:string }`. Verified against `tenancy_routes.py:437` and `:454` return dicts.
- `useFleetTenants(params)` → `useQuery`; `useTenantDetail(id)` → `useQuery` with `retry:false` (so a 403/404 surfaces immediately, see G4.6).

**Footguns:**
- `platformApi` calls MUST NOT attach `X-Aegion-Tenant`. `http.request` (`http.ts:126`) auto-adds `tenantHeader()` (`http.ts:158`) which reads the active-tenant binding — but a platform operator has NO active tenant (org-first, M-G2) so the header is absent and the server's `_operator_read_scope` (`routes.py:100`) takes the fleet path. Do NOT introduce a code path that sets an active tenant in the platform tree.
- Do NOT reach a tenant's data by setting `X-Aegion-Tenant` to a target tenant (break-glass) — that hits the forensic-content consent gate `_gate_forensic_break_glass` (`routes.py:104`), a different, stricter path. Metadata drill-down MUST use the `/platform/tenants/{id}` path param.
- Treat every field as untrusted: `deny_rate`/`trust` are optional and may be absent, null, or out of `[0,1]` — clamp/guard in the render layer, never assume presence.

**Unit** (`web/console/src/lib/api/__tests__/platform.test.ts`): `listTenants_hits_platform_tenants_no_tenant_header` (assert fetch mock received NO `X-Aegion-Tenant`); `tenantDetail_encodes_id_in_path`; `parses_optional_metric_fields_when_absent` (row without metrics parses; fields `undefined`).
**Integ** — covered by G4.3/G4.6 page tests binding these hooks.

---

### G4.3 — Fleet Overview / Tenant Grid page (ranked, paginated, sortable, filterable, virtualized)

**Touches:**
- NEW `web/console/src/features/platform/FleetOverviewPage.tsx`.
- NEW `web/console/src/features/platform/TenantGrid.tsx` (extends the existing `web/console/src/components/ui/Table.tsx` primitive — do NOT hand-roll a `<table>`).
- ADD dependency `@tanstack/react-virtual` to `web/console/package.json` (confirmed absent) for row windowing.

**Concrete change:** `FleetOverviewPage` binds `useFleetTenants` (G4.2). Renders `TenantGrid` with 6 columns in the degraded shape: **Tenant (display_name) · Plan · Status · Identity mode · Created · Consent**. When the OPTIONAL metric fields are present (post PRE-G4-a), extend to the full metric columns (`blocks_24h`, `deny_rate`, `trust`, `agents`, `quarantined`, `decisions_24h`). Sort/filter: if the response carries a `cursor` (PRE-G4-b landed) → server-driven via `sort`/`filter`/`cursor` params + `useVirtualizer` for row windowing over the paged set; otherwise → client-side sort/filter over the unpaginated `tenants[]` (safe at the current small fleet size) with a "showing all N — server paging pending" note. Each row links to `platformTenantDetailPath(tenant_id)` (G4.6).

**Footguns:**
- Do NOT block the whole page on the metric columns — the LLD mandates the Ranked-Table 6-col shape ships FIRST (`40:539`, §7.2 `40:787`). Rendering nothing until PRE-G4-a lands is wrong.
- Do NOT render any mutation control (no invite, no plan-change, no delete) — read-only invariant (`40:554`). `TenantGrid` rows are links only.
- Row-virtualization requires a fixed scroll container height; a mis-set container collapses `useVirtualizer` to zero rows. Guard with a test asserting rows render.
- Do NOT compute a fleet aggregate by summing the per-tenant rows client-side when a fleet metric endpoint exists — fleet KPIs come from the server fleet path (G4.5), not row summation (rows may be paginated/partial).

**Unit** (`web/console/src/features/platform/__tests__/TenantGrid.test.tsx`): `renders_6col_ranked_shape_when_metrics_absent`; `renders_metric_columns_when_present`; `client_sorts_when_no_cursor`; `row_links_to_platform_detail_path`; `virtualizes_rows_when_cursor_present` (assert windowed row count < total).
**Integ** (`web/console/src/features/platform/__tests__/FleetOverviewPage.integration.test.tsx`): mounts under `MeContext{is_platform:true}`, MSW-mocks `GET /v1/platform/tenants` returning `{count:3,tenants:[…]}` (no cursor) → renders 3 ranked rows, no mutation control in DOM, no `TenantSwitcher`.

---

### G4.4 — Tenant ranking + quota-headroom derivation (client-side, over rollup fields)

**Touches:** `web/console/src/features/platform/FleetOverviewPage.tsx`; NEW `web/console/src/features/platform/fleetRank.ts` (pure helpers).

**Concrete change:** `fleetRank.ts` exposes `rankByBlocks(rows)` and `rankByDenyRate(rows)` (descending), and `quotaHeadroom(row)` computed from `decisions_24h` vs the tenant's `quota` (from drill-down detail) — rendered as a headroom bar/percent. `FleetOverviewPage` surfaces a "Top tenants by blocks" and "Top tenants by DENY rate" ranked strip above the grid, driven by these helpers. All ranking is DERIVED client-side from the rollup fields — no new endpoint.

**Footguns:**
- Ranking is meaningless until PRE-G4-a lands (metric fields absent → all zero/undefined). Gate the ranked strips behind "metrics present" and show a "ranking available once fleet rollup ships" note otherwise — do NOT rank on `undefined` (renders a garbage all-tie list).
- `deny_rate` may be absent/NaN/out-of-range — `quotaHeadroom` and rank comparators must treat missing as "unknown" (sort last), never coerce `undefined` to `0` silently (would falsely rank a no-data tenant as safest).
- Quota shape (`quota:Record<string,unknown>`) is loose — narrow the specific key you read (e.g. `quota.monthly_validations`) and guard; do not assume a numeric.

**Unit** (`web/console/src/features/platform/__tests__/fleetRank.test.ts`): `rankByBlocks_desc`; `rankByDenyRate_desc`; `missing_metric_sorts_last_not_zero`; `quotaHeadroom_guards_missing_quota_returns_unknown`; `quotaHeadroom_percent_from_decisions_vs_quota`.
**Integ:** exercised via the `FleetOverviewPage` integration test (ranked strip renders top tenant when metrics present; shows pending note when absent).

---

### G4.5 — Fleet KPIs + fleet decisions-timeseries (reuse `metricsApi`/`decisionsApi`, server auto-fleet)

**Touches:** `web/console/src/features/platform/FleetOverviewPage.tsx` (reuse existing hooks — do NOT build new metric clients).

**Concrete change:** For a platform operator, `metricsApi.overview` (`lib/api/metrics.ts:9` → `GET /v1/metrics/overview`), `metricsApi.decisionsTimeseries` (`GET /v1/metrics/decisions-timeseries`, already dual-mode `routes.py:911`), and `decisionsApi.list` (`GET /v1/decisions`) ALL return fleet-scoped (`tenant_id=None`) data automatically — `_operator_read_scope` (`routes.py:100`) detects `is_platform` and returns None + audits via `_audit_platform_read(ctx,'*',what)`. So `FleetOverviewPage` reuses `useOverview`/`useDecisionsTimeseries` (from `features/overview/`) and the existing `KpiGrid`/`AllowedVsBlockedChart` components verbatim for the fleet aggregate. This is a **wire/reuse** task, not a rebuild — the fleet dual-mode is LANDED (§7.3, `40:789`).

**Footguns:**
- Do NOT pass any tenant scoping to these calls from the platform tree — scope is server-derived from `is_platform`. Adding a client tenant param would break the fleet path.
- Do NOT re-implement `MetricsOverview`/`DecisionsTimeseries` rendering — reuse `features/overview/KpiGrid.tsx` + `AllowedVsBlockedChart`. Only the enclosing page/layout is new.
- The server audits these fleet reads as aggregate (`consent_state="n/a-aggregate"`); the client does nothing to audit — do NOT attempt a client-side audit call.

**Unit:** none new (reuses covered `useOverview`/`KpiGrid`).
**Integ** (`web/console/src/features/platform/__tests__/fleetMetrics.integration.test.tsx`): platform operator mounts `FleetOverviewPage`, MSW-mock `GET /v1/metrics/overview` + `/metrics/decisions-timeseries` (fleet shape) → KPI grid + timeseries render; assert NO `X-Aegion-Tenant` header sent on either call. **Backend regression gate (WS-N-owned, must be green):** `src/security-controller/tests/test_ws_n_read_scope.py::test_platform_overview_returns_fleet_and_audits_aggregate` — platform `GET /metrics/overview` returns fleet aggregate AND writes `_audit_platform_read(ctx,'*','metrics.summary')`.

---

### G4.6 — Audited per-tenant drill-down page (consent-gated, 403 handling)

**Touches:** NEW `web/console/src/features/platform/TenantDetailPage.tsx`; binds `useTenantDetail(id)` (G4.2) at route `platformTenantDetail` (`/platform/tenants/:tenantId`).

**Concrete change:** Reads `:tenantId` from the route param, calls `platformApi.tenantDetail` → `GET /v1/platform/tenants/{id}` (`tenancy_routes.py:454`, `require_platform`). Renders the registry row + `quota` + `platform_read_consent` state + member roster (`members[]` → operator_sub·role, read-only). The server dual-audits via `_audit_platform_read(ctx, tenant_id, "tenant.detail")` (`tenancy_routes.py:456`) BEFORE serving. **As-built (enforcement OFF, `config.py:237` default False):** the read succeeds and is audited `consent_state="false-unenforced"` even for a non-consenting tenant. **Gated behavior (PRE-G4-c, founder flip):** when `platform_read_consent_enforced` is ON and the tenant hasn't consented, the server returns **403** `"platform_read_consent not granted by tenant"` (`tenancy_routes.py:426`) — the page must render a **"consent required"** empty-state (not a generic error toast, not a retry loop) using `ApiException.status===403`.

**Footguns:**
- `useTenantDetail` MUST set `retry:false` — a 403 consent denial must NOT be retried (retry storm + repeated DENY audit rows).
- Do NOT render the drill-down by binding `X-Aegion-Tenant` to the target and reusing customer pages — that routes through the stricter forensic break-glass gate (`_gate_forensic_break_glass`, `routes.py:104`) and is a different contract. Use the metadata `/platform/tenants/{id}` route only.
- Distinguish 403 (consent required — friendly consent-state panel) from 404 (`"tenant not found"`, `tenancy_routes.py:451`) — different empty states.
- Read-only: no member add/remove, no consent-toggle control here (mutating consent is LLD-26 tenant-settings, not the platform ops console).

**Unit** (`web/console/src/features/platform/__tests__/TenantDetailPage.test.tsx`): `renders_registry_and_members_readonly`; `no_mutation_controls_present`; `renders_consent_required_state_on_403`; `renders_not_found_on_404`; `does_not_retry_on_403`.
**Integ** (`web/console/src/features/platform/__tests__/TenantDetailPage.integration.test.tsx`): platform operator navigates a `TenantGrid` row → detail page; MSW-mock `GET /v1/platform/tenants/t_globex` (consented) renders roster; a `403` mock renders consent-required panel. **Backend gate (WS-N-owned):** `src/security-controller/tests/test_platform_audit.py::test_tenant_detail_audits_before_serve` (as-built: non-consent served + audited `false-unenforced`) and the founder-flip case `::test_tenant_detail_403_when_enforced_and_no_consent` (skipped until PRE-G4-c).

---

### G4.7 — ROADMAP surfaces: Fleet Topology + System Health + rich Ops-Terminal metric grid

**Touches:** NEW `web/console/src/features/platform/FleetTopologyPage.tsx`, `web/console/src/features/platform/SystemHealthPage.tsx` (both at `platformTopology`/`platformHealth` routes); reuse `web/console/src/components/ui/PlaceholderPage.tsx` pattern with a roadmap badge.

**Concrete change:** Both pages render a **ROADMAP badge** + explicitly-labeled **sample/mock data** — NO live read to a nonexistent route (§7.2, `40:785-787`). Fleet Topology: no `GET /v1/topology` route exists (grounding confirms zero topology routes); render the Sankey shell with a "sample data — fleet topology roadmap" banner, do NOT call any topology endpoint. System Health (per-region latency): no route exists — only a scalar `avg_latency_ms` at `routes.py:863`; render a roadmap mock, do NOT fabricate per-region series from the scalar. The richest Ops-Terminal metric grid is likewise ROADMAP (backend absent per M-G0).

**Footguns:**
- Do NOT issue a live fetch to `/v1/topology` or a per-region health route — they return 404 and would surface as a spurious error. The roadmap page makes ZERO network calls.
- Every mock datum MUST carry a visible "sample data" marker (§7.2) — no unmarked fabricated numbers on a platform ops screen.

**Unit** (`web/console/src/features/platform/__tests__/roadmapPages.test.tsx`): `FleetTopology_renders_roadmap_badge_and_makes_no_fetch` (assert fetch spy uncalled); `SystemHealth_renders_roadmap_badge_and_marks_sample_data`; `sample_data_marker_present`.
**Integ:** none (no network surface — the "makes no fetch" unit assertion is the contract).

---

### G4.8 — Platform nav entry (is_platform-gated) + four-invariant structural enforcement

**Touches:**
- `web/console/src/app/navConfig.ts` (add a `PLATFORM_NAV` group — Fleet Overview, Tenant Grid, Fleet Topology(roadmap), System Health(roadmap) — consumed only by the platform nav rail, NOT the customer `NAV_GROUPS`).
- NEW `web/console/src/components/ui/PlatformNavRail.tsx` (or a `variant` prop on `NavRail.tsx:47`) mounted inside `PlatformLayout` (G4.1).
- `web/console/src/components/ui/TopBar.tsx` — ensure the platform layout mounts NO `TenantSwitcher` (already slated for deletion in M-G2; assert its absence here).

**Concrete change:** The platform nav is rendered ONLY inside `PlatformLayout`, which is only reachable when `RequirePlatform` passes (`is_platform===true`). The customer `NavRail` (`NavRail.tsx`) gains NO platform link — a customer never sees a route into `/platform`. Add a structural test enforcing all four invariants in one place.

**Footguns:**
- Do NOT add a platform link to the customer `NAV_GROUPS` guarded only by a runtime `is_platform &&` render check — belt-and-suspenders is fine, but the authoritative gate is the router-level `RequirePlatform` (G4.1). A nav-only check without the route guard leaves `/platform` hand-typeable by a customer.
- The platform tree MUST NOT mount `TenantSwitcher` (`components/ui/TenantSwitcher.tsx`, being deleted in M-G2) nor any active-tenant setter — "no tenant selector" invariant (`40:556`).

**Unit** (`web/console/src/app/__tests__/platformInvariants.test.tsx`): `platform_tree_has_no_import_route` (no `/import` mount reachable from `PlatformLayout`); `platform_tree_has_no_mutation_control` (scan rendered platform pages for buttons wired to `http.{post,put,patch,del}` — none); `platform_tree_has_no_tenant_switcher` (no `TenantSwitcher` in DOM, no `setActiveTenant` call); `customer_nav_omits_platform_link`.
**Integ** (`web/console/src/app/__tests__/platformInvariants.integration.test.tsx`): full platform-tree mount under `{is_platform:true}` asserts (a) Tenant Grid read binds `GET /v1/platform/tenants` and the server records `_audit_platform_read(ctx,'*','tenants.list')` — **backend gate (WS-N-owned):** `src/security-controller/tests/test_platform_audit.py::test_list_tenants_audits_aggregate`; (b) no import/mutation/tenant-selector control anywhere in the tree.

---

**Milestone build gates (`40:802-806`):** `npm run build` (tsc-b + vite) + `npm run lint` green with the extended types; all G4.* Vitest suites green; the WS-N-owned backend gates named above green in `pytest tests/`; WS-J canary (`tests/canary/`) unaffected (platform routes are `require_platform`, already OIDC-gated). **Sequencing:** G4.1→G4.2 land first (guard + client); G4.3/G4.5/G4.6 bind next; G4.4 ranking + full metric columns light up only when PRE-G4-a/b land; G4.6 enforced-403 path only when PRE-G4-c (founder flip) lands — until then the as-built `false-unenforced` path is the tested contract.

---

## §Error model

| Condition | Surfaced as | Notes |
|---|---|---|
| No/invalid ALB-OIDC on any `/v1` read | server **401** (`verify_alb_oidc`) → console `reauthenticate()` top-level nav | do not `fetch`-follow the cross-origin 302 (CSP-blocked); `http.ts:42` |
| Customer operator, foreign `X-Aegion-Tenant` (non-member) | server **403** (`deps.py:440`) → toast "not a member of requested tenant" + fail-safe redirect to org page | org-first flow should never send a non-member header; the 403 is belt-and-braces (G2.11/G2.12) |
| Operator lacks role for a mutation | server **403** (`require_role`) → sanitized toast + `invalidateQueries(['me'])` (force role re-read); render-gate should have hidden the control | 403 must NOT `reauthenticate()` — authenticated-but-forbidden (G2.8) |
| `resolve_org` miss (org not found) | **404**-shaped `{"error":"org not found — check spelling"}` → stay on org page, nothing stashed | founder 2026-07-08 accepted org-NAME enumeration; miss==hit rule DROPPED (G0.2/G2.12) |
| `resolve_org` internal error | server **5XX** fail-closed (never a fake-200) → org page shows retryable error | engineering error-contract rule (G0.2) |
| Non-`is_platform` operator hits `/platform/*` | `RequirePlatform` `<Navigate to=/overview replace/>` (client) | authoritative gate is router-level; server `require_platform` still 403s the API (G4.1) |
| Platform per-tenant drill-down, consent enforced + no consent | server **403** `"platform_read_consent not granted"` → "consent required" empty-state, `retry:false` | distinct from 404 tenant-not-found; PRE-G4-c founder flip (G4.6) |
| Platform cross-tenant read (aggregate/detail) | 200 fleet data + server `_audit_platform_read(ctx,"*"/tenant_id,what)` row | client does no audit; every platform read is server-attributed (G4.5/G4.6) |
| Dep API absent (`/trail`, `/usage`, winning_source, compiled-Cedar, `/topology`) | `ApiException.status ∈ {404,501}` → **PARTIAL banner** / ROADMAP badge + sample-data marker | never a blank page, never fabricated data (M-G3.4/3.8/3.12, M-G3.14/G4.7) |
| `/v1/me` unavailable | `useMe()` non-throwing fallback (`retry:false`, mock `is_platform:false`) → shell renders, gates default closed, platform tree denied | **fail-secure: missing role hides controls; missing platform-flag denies** (§2 #5) |

---

## §Acceptance criteria

Each box ties a major task to its FR + the §15 test (Vitest for the console, pytest for the backend regressions). Backend field-add prereqs gate only the *live* variant; the PARTIAL-degrade variant must pass now.

**M-G0 (prerequisites — owned elsewhere; WS-G lands the guard tests now):**
- [x] G0.1 D13 shadow-write verified-tenant bind (PILOT-BLOCKING) — `test_shadow_branch_binds_verified_tenant` + `test_shadow_decision_visible_to_tenant_overview` (WS-N/WS-M-backend).
- [x] G0.2 `resolve_org` returns only `tenant_id`, fails-closed 5XX, friendly-404 miss (PILOT-BLOCKING) — `test_resolve_org_returns_only_tenant_id` + `test_resolve_org_reachable_without_cognito` (WS-M/WS-N-backend + CDK).
- [x] G0.3 static org page + ALB priority-<5 carve-out + nginx + private-ALB forward (PILOT-BLOCKING) — `test_resolve_org_public_rule_priority_below_5` + `test_org_html_served_unauth`.
- [x] G0.4 platform per-tenant rollup on `/platform/tenants` — `test_platform_list_tenants_includes_rollup_fields` (feeds M-G4).
- [x] WS-G guard tests that land regardless: `TopologyPage.roadmap` (G0.6), `ResidualAgentsPage.readonly` (G0.7), `PolicyDetailPage cedar_tab_partial` (G0.10) all green.

**M-G1 (FR-13.1 — cosmetic-tenant containment):**
- [x] G1.1 `tenantOf`→`tenantLabelForDisplay` renamed; sole callers `auth.ts` def + `AccountMenu.tsx:12,44` (display-only, grep-proven) — `auth.test.ts` (`tenantOf is no longer exported`).
- [x] G1.2 ESLint AST guard fails `npm run lint` on the label into `queryKeys.*`/`http.{get,post,put,patch,del}`/`can|rbacCan|roleSatisfies`/`setActiveTenant` — `lint-tenant-guard.test.ts` + `lint-guard-e2e.test.ts`.
- [x] G1.3 resolution uses membership not domain (`alice@acme.io` + sole `t_globex` → `t_globex`) — `test_resolution_uses_membership_not_email_domain` + `test_domain_matching_tenant_never_auto_bound`.

**M-G2 (FR-13.3 — RBAC render-gating + org-first login):**
- [x] G2.0 Vitest + Testing Library scaffolded; `npm run test` exits 0 — `setup.test.tsx`.
- [x] G2.1 `Capability` union + `MIN_ROLE` extended (5 caps) + `PlatformCapability='sigma.retire'` separate; `sigma.retire` NOT in `Capability` — `rbac.test.ts`.
- [x] G2.2–G2.7 every mutating control across `features/{agents,policies,connect,import,quarantine,identity}` gated (hide not disable); a `viewer` sees zero mutating controls — per-page `.gate.test.tsx`.
- [x] G2.8 fail-secure degrade: 403→toast+`invalidate(['me'])` (no reauth); demoted operator re-fetch hides controls — `http.degrade.test.ts` + `useMe.refetch.test.tsx`.
- [x] G2.9 D3 client↔server parity + completeness passes against backend `role-model.json` and fails loud when the fixture is missing / on a seeded mismatch — `rbac.parity.test.ts`.
- [x] G2.10 `TenantSwitcher` deleted (file + TopBar mount); no `TenantSwitcher` in DOM — `TopBar.test.tsx`.
- [x] G2.11 active-tenant binding on per-tab `sessionStorage['aegion.activeTenant']`; absent + multi-membership → fail-safe redirect to org page (no silent primary bind); logout clears — `tenant.test.ts` + `orgflow.test.tsx`.
- [x] G2.12 org-first entry: `resolve_org` hit → stash → Cognito; miss → stay on org page; router guard redirects multi-membership operator with no bound tenant — `orgEntry.test.ts` + `orgflow.test.tsx` (blocked-on D14).

**M-G3 (FR-13.2 — exhaustive customer dashboard set):**
- [x] M-G3.0 routes/nav/lazy for Activity, DecisionDetail (`:sessionId/:requestId`), SessionForensics, Usage — `routes.test.ts` + `router.test.tsx`.
- [x] M-G3.1 Overview verified tenant-scoped (no client tenant filter), near-real-time label — `OverviewPage.tenant.test.tsx`.
- [x] M-G3.2 Activity feed BUILT (cursor-paginated, rows link to `decisionDetailPath(session_id,request_id)`, ≤15s pull label) — `ActivityPage.test.tsx` + `.pagination.test.tsx`.
- [x] M-G3.3 Threats winning_source facet API-driven with fallback (PARTIAL until server field lands); quarantine control admin-gated — `ThreatsPage.facet.test.tsx` + `.gate.test.tsx`.
- [x] M-G3.4 Decision-detail binds WS-D `/trail` from both route params; PARTIAL+`DecisionTrace` fallback on 404/501; verdict panel editor-gated — `DecisionDetailPage.test.tsx` + `.partial.test.tsx`.
- [x] M-G3.5 Session-forensics BUILT (header + per-request trace); non-member 403 handled not blank — `SessionForensicsPage.test.tsx` + `.tenant.test.tsx`.
- [x] M-G3.6 Agent inventory/detail: attach/detach `agents.write`-gated; ECS→canvas activity-status client-mapped (no-traffic→Idle) — `activityStatus.test.ts` + `AgentInventoryPage.gate.test.tsx`.
- [x] M-G3.7 Topology ROADMAP-honest (badge + sample marker, no fetch to `/v1/topology`) — `TopologyPage.test.tsx`.
- [x] M-G3.8 Policy library delete=`policies.delete` (admin) / create-edit=`policies.write` (editor); Cedar/JSON PARTIAL when compiled body absent, no fabricated body — `PolicyDetailPage.format.test.tsx` + `PolicyLibraryPage.gate.test.tsx`.
- [x] M-G3.9 Connect/Import gated (write=admin, operate=editor, import=editor); grant copy-only; GCP coming-soon — `GrantAccessCard.test.tsx` + `ConnectAccountPage.gate.test.tsx` + `ImportAgentsPage.test.tsx`.
- [x] M-G3.10 Quarantine release admin-gated; why-trace degrades to `quarantine_status` until origin+signals surface — `QuarantinePage.gate.test.tsx` + `.whytrace.test.tsx`.
- [x] M-G3.11 Audit trail verified; verdict panel editor-gated; NO export (FR-6.5 deferred) — `AuditTrailPage.test.tsx`.
- [x] M-G3.12 Usage view BUILT; feature-flag OFF or PARTIAL banner without WS-H `/v1/usage` (no dark billing tab, no fabricated totals) — `UsagePage.test.tsx` + `.flag.test.tsx`.
- [x] M-G3.13 dead `operator_id` client stubs removed + dropped from `VerdictRequest`/`QuarantineRequest` types; server attributes `ctx.sub` — `DecisionReviewPanel.test.tsx` + `mutations.test.ts` + `test_verdict_quarantine_operator.py`.
- [x] M-G3.14 §7.3 dual-mode (`decisions-timeseries` + `platform-distribution`) stays LIVE per-tenant, not re-mislabeled — `timeseries.dualmode.test.tsx`.
- [x] M-G3.15 build gate: `npm run build` + `npm run lint` (incl. M-G1 rule) green; all Vitest green; backend regressions green under moto-safe env.

**M-G4 (§6.11 — platform global-admin console):**
- [x] G4.1 router-root `is_platform` split; `RequirePlatform` fail-secure (false AND absent redirect); distinct `PlatformLayout` (no tenant chrome) — `RequirePlatform.test.tsx` + `platformRouter.integration.test.tsx`.
- [x] G4.2 `platformApi` + types + hooks; NO `X-Aegion-Tenant` header on platform calls; optional metric fields parse when absent — `platform.test.ts`.
- [x] G4.3 Fleet Overview / Tenant Grid: 6-col ranked shape ships first, metric columns light up post PRE-G4-a; read-only (no mutation control); rows link to detail — `TenantGrid.test.tsx` + `FleetOverviewPage.integration.test.tsx`.
- [x] G4.4 ranking + quota-headroom derived client-side; missing metric sorts last (not zero) — `fleetRank.test.ts`.
- [x] G4.5 fleet KPIs + timeseries reuse `metricsApi`/`decisionsApi` (server auto-fleet, no client scope) + WS-N audit gate green — `fleetMetrics.integration.test.tsx` + `test_ws_n_read_scope.py`.
- [x] G4.6 audited per-tenant drill-down: `retry:false`, consent-required 403 empty-state vs 404, no mutation control — `TenantDetailPage.test.tsx` + `test_platform_audit.py`.
- [x] G4.7 Fleet-topology + System-health ROADMAP (badge + sample marker, ZERO network calls) — `roadmapPages.test.tsx`.
- [x] G4.8 platform nav is_platform-gated + four invariants (no import, no mutation, no tenant-selector, audited fleet reads) enforced structurally — `platformInvariants.test.tsx` + `.integration.test.tsx` + `test_platform_audit.py::test_list_tenants_audits_aggregate`.

**Cross-cutting:**
- [x] `npm run build` (tsc-b + vite) + `npm run lint` + `npm run test` green; backend `pytest tests/` green under `env -u AWS_PROFILE ... venv/bin/python` (moto-safe) for the WS-G-owned regressions.
- [x] No PARTIAL/ROADMAP view issues a live read to an unbuilt route (§7.2 tests enforce).
- [x] The RBAC render-gate never becomes the boundary — every gated mutation has a matching WS-M server `require_role` (asserted by the G2.9 parity walk).

---

## §Cross-references

- **Design-of-record (LLD):** [lld/40-multi-tenant-console.md](../../lld/40-multi-tenant-console.md) — §4 (`40:198-226`, cosmetic-tenant / M-G1) · §5 + Appendix A role map (`40:234-255`, `40:824-843`, M-G2 caps) · §5.4 (`40:291-298`, D6 fail-secure degrade) · §5.5 + Appendix C (`40:300-314`, `40:955-1007`, org-first + `resolve_org` + carve-out) · §6/§7 (customer dashboard set + endpoint bindings, M-G3) · §6.9 (`40:500`, D8 `operator_id` stub) · §6.11 + LLD-26 §5.5 (`40:537-558`, platform console + four invariants, M-G4) · §7.1a–e (`40:606-609`, PARTIAL fields) · §7.2 (`40:785-787`, ROADMAP honesty) · §7.3 (`40:789`, dual-mode) · §8 SEC-5 (`40`, D12 read attribution — WS-N-owned) · §15 (test matrix) · §16 (status ledger).
- **Decisions:** **ADR-039** (org-first login, Accepted founder 2026-07-07 — deletes in-session switcher, per-tab `sessionStorage`) · **ADR-019 / AD-8** (console multi-tenant SSO + RBAC, refined) · **ADR-035** (federation seam, design-only/deferred — Cognito kept; SSO-federation = post-ADR-035 roadmap, NOT the pilot) · **ADR-038** (consume — D10 operator-lane reclassification of `/trail`+`/signals`) · **ADR-037** (consume — in-service auth boundary; edge authorizer deferred).
- **Sibling refs (Phase-3 consistency sweep):** **WS-N** ([ws-n-read-route-authz.md](ws-n-read-route-authz.md) — COMPLETE; owns the 21 read binds + D10/D11 + `_operator_read_scope`/`_audit_platform_read`/`resolve_operator_tenant`; WS-G's D10/D11 obligation is verification-only; WS-N/WS-M-backend owns the M-G0 backend prereqs G0.1–G0.11 + the D3 fixture generator) · **WS-M** ([ws-m-authz.md](ws-m-authz.md) — LIVE server `require_role`/`assert_owns`/`OperatorContext` the render-gate mirrors; shares `deps.py`/`routes.py`/`tenancy_routes.py`; owns the ADR-039 `resolve_org` backend + org-page carve-out class) · **WS-D** ([ws-d-decision-trail.md](ws-d-decision-trail.md) — owns the `SessionTrail` shape for `/trail`; endpoint LIVE `routes.py:566`) · **WS-H** ([ws-h-metering.md](ws-h-metering.md) — owns `GET /v1/usage` → `UsageRollup`; Usage view flag-OFF/PARTIAL until live) · **WS-J** ([ws-j-canary-tests.md](ws-j-canary-tests.md) — platform routes are `require_platform`, already OIDC-gated, canary unaffected).
- **Shared contracts (join keys):** `Capability`/`MIN_ROLE`/`PlatformCapability`/`RANK` (`rbac.ts`) ↔ `require_role`/`require_platform`/`_ROLE_ORDER` (`deps.py`) · `X-Aegion-Tenant` header (`tenant.ts`/`http.ts:158`) · `MeContext{sub,email,tenant_id,role,is_platform,memberships[]}` (`types/api.ts`, `GET /v1/me`) · `resolve_org(org)→{tenant_id}` (D14, non-`/v1` public) · `sessionStorage['aegion.activeTenant']` (per-tab tenant preference) · `resolve_operator_tenant`/`_operator_read_scope`/`_audit_platform_read` (server read scope) · `SessionTrail` (WS-D) · `UsageRollup` (WS-H) · `PlatformTenantRow`/`PlatformTenantDetail` (M-G0 rollup).
- **Upstream LLDs to extend, not rebuild:** LLD-26 §5–6 (membership/RBAC primitives + `sentra-tenant-members`) · LLD-08 §6.5 (`verify_alb_oidc` / `GET /v1/me`) · LLD-16 (console-nginx / ALB) · lld/39 (WS-M authz boundary the render-gate mirrors).
- **Code anchors (re-verify at tip @ `761bb88`):** `web/console/src/lib/{auth.ts:61, rbac.ts:16-48, tenant.ts:14-50, http.ts:42/126/158, api/{me.ts,sessions.ts,metrics.ts,platform.ts(new)}, query/{useMe.ts,useDecisions.ts,useSessions.ts,usePlatform.ts(new)}, queryKeys.ts}` · `web/console/src/app/{routes.ts, lazyPages.ts, router.tsx, navConfig.ts, AppLayout.tsx, PlatformLayout.tsx(new), RequirePlatform.tsx(new)}` · `web/console/src/components/{ui/{AccountMenu.tsx,TopBar.tsx,TenantSwitcher.tsx(delete),NavRail.tsx,Table.tsx}, decisions/{DecisionTrace,DecisionReviewPanel}.tsx}` · `web/console/src/features/{overview,activity(new),threats,forensics(new),agents,topology,policies,connect,import,quarantine,identity,audit,usage(new),platform(new)}` · `web/console/eslint.config.js` · `src/security-controller/app/api/{routes.py:{100,104,111,554,566,600,863,910,1347,1739,1783/1829,1583}, tenancy_routes.py:{117,227,437,454,456}, deps.py:{374,404,440,449,496}}` · `app/services/{agent_service.py:687, session_manager.py:{394,636}}` · `cdk/stacks/compute_stack.py:{887,967,1031-1105}` · `app/config.py:237`.
- **Memory:** [[policy-crud-routes-no-authz]] (BUG-1, WS-M closed) · [[authz-identity-model-reframe-2026-07-06]] (org-first / two-cred-lane / T1-T2-T3 roles) · [[overview-latency-root-cause]] (the O(N) fleet-scan blast G0.4 must avoid) · [[controller-tests-moto-safe-env]] (backend test env) · [[dev-stack-is-prod]].
