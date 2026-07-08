# WS-G-FRONTEND — multi-tenant console (M-G1..M-G4, React)

> **Build-lane doc (orchestration).** A `code-loop` lane split of the canonical
> [ws-g-console.md](../ws-g-console.md) — the **frontend/React** half. Runs **AFTER**
> [ws-g-backend.md](ws-g-backend.md) (which emits `role-model.json` + the `resolve_org` contract this lane's
> parity + org-entry tasks hard-depend on). **All task detail, `file:line`, and Vitest test names are
> canonical in [ws-g-console.md](../ws-g-console.md)** (M-G1..M-G4, lines 171–769) — this doc references task
> IDs, it does not restate them. **Design-of-record: [docs/console-design-spec.md](../../../docs/console-design-spec.md)**
> (navy retheme + per-screen specs, distilled from the canvas). **Stack: [docs/frontend-stack.md](../../../docs/frontend-stack.md).**

**Owner:** WS-G build (frontend lane) · **Domain:** frontend (React 19 + TS + Tailwind v4 + Vite, in
`web/console/`) · **Status:** ⬜ not started · **Base:** re-verify `file:line` at tip before editing.

**Founder decision (2026-07-08):** implement the canvas design faithfully → **navy retheme** of the CSS-first
token layer (design-spec §0/§1). This reskins the already-shipped screens too — intended, the canvas is uniform.

---

## Test commands (this lane)

Vitest does NOT exist yet — **G2.0 scaffolds it FIRST** (it is the first task; every other test is un-runnable
without it). After G2.0:
- **Unit + component:** `cd web/console && npm run test`  (`vitest run`)
- **Build gate (per milestone):** `cd web/console && npm run build && npm run lint && npm run test`
  (`build` = `tsc -b && vite build` — this is the typecheck gate too).

The integration gate for this lane = the full `npm run build && npm run lint && npm run test` green in
`web/console`. There is no separate integration-test runner for the frontend; component tests are the integration
surface (with the existing `src/mocks/mockRouter.ts` fetch-adapter + per-test fakes; **no MSW**).

---

## Milestone F0 — Test harness + design tokens (FIRST, blocking)

- **G2.0 — scaffold Vitest + Testing Library.** Canonical [ws-g-console.md](../ws-g-console.md):262. Add
  `vitest`/`jsdom`/`@testing-library/{react,user-event,jest-dom}`/`@vitest/coverage-v8` to `package.json`; new
  `vitest.config.ts` (reuse the Vite plugin/resolve config); new `src/test/setup.ts` (jest-dom + a
  `renderWithProviders` mounting a **fresh per-test `QueryClient`, `retry:false`**); add `"test":"vitest run"`.
  UT `src/test/setup.test.tsx`.
- **F0.1 — navy token remap.** Per design-spec §1: edit `web/console/src/styles/index.css` `@theme` to the navy
  palette (`--color-bg #060E1C`, `--color-surface #0C1730`, `--color-surface-2 #0A1428`, `--color-line`
  `rgba(255,255,255,0.07)`, add `--color-blue/-blue-fill/-blue-lt/-info/-sev-high/-purple`, retarget
  `--color-pink → #FF3D71`). Keep Space Grotesk / IBM Plex fonts. Add a `trustColor(n)` helper (≥80 green /
  50–79 amber / <50 pink). This is a token-layer change; the existing screens re-skin through it — add a
  smoke test that a couple of shipped components still render with the new tokens.

## Milestone F1 — Cosmetic-tenant containment (M-G1)

- **G1.1** rename `tenantOf`→`tenantLabelForDisplay` (`lib/auth.ts` decl + `AccountMenu.tsx` import/call);
  body byte-identical, NO compat alias, do NOT delete (chip still renders). UT `lib/__tests__/auth.test.ts`,
  `components/ui/__tests__/AccountMenu.test.tsx`.
- **G1.2** ESLint AST guard (`no-restricted-syntax`) blocking the label into `queryKeys.*`/`http.{get,post,put,
  patch,del}`/`can|rbacCan|roleSatisfies`/`setActiveTenant`. Net-new `rules` block in `eslint.config.js` — **it
  MUST be the SAME config object M-G2/§5.5 extends** (last-wins would drop the rules). UT
  `lib/__tests__/lint-tenant-guard.test.ts` (RuleTester) + build-gate e2e. (G1.3 backend regression is in the
  backend lane.)

## Milestone F2 — RBAC render-gating + org-first login (M-G2)

Canonical [ws-g-console.md](../ws-g-console.md):252–395. Build **G2.1–G2.12** (skip G2.0 — done in F0):
- G2.1 extend `Capability` union + `MIN_ROLE` (5 caps: `decisions.verdict`/`quarantine.manage`/`policies.delete`
  /`connections.write`/`connections.operate` + `tenant.manage`); **split `sigma.retire` into a separate
  `PlatformCapability` (NOT in `Capability`)**; add `usePlatformCan()`.
- G2.2–G2.7 gate every mutating control across the 6 features (Policy delete=admin, Quarantine release=admin,
  Threats quarantine+verdict, Agents attach/detach/import=agents.write, Connections write=admin/operate=editor,
  Residual read-floor). **Gated control = NOT rendered.**
- G2.8 fail-secure UI degrade (hide / PARTIAL banner on 404-501 / 403→toast+`invalidate(['me'])` NOT reauth /
  demoted→focus-refetch).
- **G2.9 D3 parity+completeness** — `lib/rbac.parity.test.ts` consumes `lib/__fixtures__/role-model.json`
  (**emitted by the backend lane B2.1**). Asserts RANK order, `MIN_ROLE == fixture`, every
  `require_role`/`require_platform` route mapped-or-allowlisted. **Missing fixture → FAIL LOUD, never skip.**
  Negative test uses `role-model.bad.json`. (This is the hard cross-lane dependency — backend lane must land B2.1 first.)
- G2.10 DELETE `TenantSwitcher.tsx` + its `TopBar` mount (do NOT delete `tenant.ts`).
- G2.11 migrate active-tenant to per-tab **`sessionStorage['aegion.activeTenant']`** (`lib/tenant.ts` +
  `http.ts:158` + `reauthenticate` clears it); absent+multi-membership → fail-safe org page, NEVER silent primary bind.
- G2.12 **org-first entry client** (consumes backend D14): the `org.html` client script (fetch
  `/public/resolve-org` → stash tenant → Cognito; miss → stay) + a router redirect-to-org guard for
  multi-membership with no bound tenant. Design per design-spec §4 (dark D-tokens + B2 copy; **no SSO-Okta button**).

## Milestone F3 — Exhaustive FR-13.2 dashboard set (M-G3)

Canonical [ws-g-console.md](../ws-g-console.md):399–609. Build **M-G3.0–M-G3.15**. Per design-spec §5:
- M-G3.0 routes/nav/lazy scaffold — add `activity:'/activity'`,
  `decisionDetail:'/decisions/:sessionId/:requestId'` (**composite PK — not `:requestId` alone**),
  `sessionDetail:'/sessions/:sessionId'`, `usage:'/usage'`; nav groups per design-spec §2 (add FORENSICS, ACCOUNT).
- M-G3.1 Overview verify tenant-scoped + near-real-time label. **M-G3.2 BUILD Activity feed.** M-G3.3 Threats
  winning_source facet (PARTIAL until backend field). **M-G3.4 BUILD Decision-detail client** binds WS-D
  `/trail` (both route params; PARTIAL+`DecisionTrace` fallback). **M-G3.5 BUILD Session forensics** (derive
  header from decisions; no `GET /v1/sessions/{id}`). M-G3.6 Agents gate+field-map (no-traffic→Idle). M-G3.7
  Topology ROADMAP (zero fetch). M-G3.8 Policy library/detail gate + Cedar/JSON PARTIAL (no fabrication). M-G3.9
  Connect/Import gate + grant copy-only + GCP coming-soon + `enforcement_mode` on import. M-G3.10 Quarantine gate
  + why-trace degrade. M-G3.11 Audit verify + editor-gated verdict + **no export**. **M-G3.12 BUILD Usage**
  (flag-OFF/PARTIAL until WS-H; no dark billing tab, no fabricated totals). M-G3.13 remove dead `operator_id`
  client stubs (backend confirms it's not required — backend lane B3). M-G3.14 roadmap-honesty + dual-mode guards.
  M-G3.15 milestone build gate.

## Milestone F4 — Platform global-admin console (M-G4)

Canonical [ws-g-console.md](../ws-g-console.md):611–769. Per design-spec §6. Build **G4.1–G4.8**:
- G4.1 router-root `is_platform` split + `PlatformLayout` + `RequirePlatform` (fail-secure: false AND absent →
  `<Navigate overview>`; gate on `is_platform`, NOT a Capability).
- G4.2 platform API client + types + hooks (`lib/api/platform.ts`, `lib/query/usePlatform.ts`; **MUST NOT attach
  `X-Aegion-Tenant`**; `retry:false` on detail; metric fields optional).
- G4.3 **Fleet Overview / Tenant Grid** — ranked-table design (design-spec §6); 6 cols ship first
  (`# · Tenant · Plan · Identity mode · Status · Created` + `Consent` col), read-only, rows=links, virtualized
  (**add `@tanstack/react-virtual`**); metric cols light up post-backend-rollup.
- G4.4 client-side tenant ranking + quota-headroom (missing metric sorts LAST).
- G4.5 fleet KPIs + timeseries (reuse `metricsApi`/`decisionsApi`; server auto-fleet; backend WS-N audit gate
  must be green).
- G4.6 audited per-tenant drill-down (`/platform/tenants/:tenantId`; `retry:false`; **403 CONSENT_REQUIRED
  first-class empty state**, distinct from 404; aggregate strip stays visible; read-only).
- G4.7 Fleet Topology + System Health ROADMAP (zero fetch).
- G4.8 platform nav (`is_platform`-gated) + the **four structural invariants** (no import, no per-tenant mutation,
  no tenant selector, every cross-tenant read server-audited) enforced structurally + tested.

---

## Acceptance (this lane)
Mirror the canonical [ws-g-console.md](../ws-g-console.md) §Acceptance rows for M-G1/M-G2/M-G3/M-G4 + these
lane specifics:
- [ ] G2.0 Vitest scaffolded, `npm run test` exits 0; F0.1 navy tokens applied, shipped screens still render.
- [ ] Every mutating control across the 6 features NOT-rendered for `viewer`; `sigma.retire` gates on `is_platform`.
- [ ] **G2.9 parity+completeness green against `role-model.json`; fails loud on missing/bad fixture.**
- [ ] `TenantSwitcher` gone from the DOM; per-tab `sessionStorage` binding; org-first entry (hit→stash→Cognito,
      miss→stay); router redirects multi-membership w/ no bound tenant.
- [ ] Activity/Decision-detail(composite)/Session-forensics/Usage routes + pages built; Overview near-real-time
      label; PARTIAL/ROADMAP views issue **no** live read to an unbuilt route; no fabricated data anywhere.
- [ ] Platform tree gated at router root on `is_platform` (fail-secure); ranked-table 6-col+Consent, read-only,
      virtualized, rows-link; drill-down consent-403 empty-state vs 404; four invariants structurally enforced +
      tested; platform client attaches no `X-Aegion-Tenant`.
- [ ] `npm run build && npm run lint && npm run test` all green.

## Do-NOT (this lane)
- Do NOT build the `Continue with SSO · Okta` button (customer-IdP SSO is ADR-035 roadmap; we use our Cognito pool).
- Do NOT ship "monitor" as an identity mode — canonical is `enforce / shadow / off`.
- Do NOT let the render-gate be the security boundary; NOT-rendered, not disabled.
- Do NOT fabricate compiled-Cedar / topology / usage numbers; degrade to PARTIAL/ROADMAP with zero fetch to
  unbuilt routes.
- Do NOT attach `X-Aegion-Tenant` on platform calls; do NOT reach tenant content via the break-glass header.
- Do NOT put the M-G1 ESLint rules in a separate config object from the one M-G2 extends (last-wins drops them).
- Do NOT start before the backend lane's `role-model.json` + `resolve_org` land (G2.9/G2.12 hard-depend on them).
