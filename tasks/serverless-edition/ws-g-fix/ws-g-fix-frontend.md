# ws-g-fix-frontend — console review-findings fix lane (frontend)

> **Doc role:** code-loop frontend build lane. Closes 20 of the 22 review findings in `web/console/src`. **Full detail (evidence file:line + exact fix + test) lives in [../ws-g-fix-review-findings.md](../ws-g-fix-review-findings.md)** — this lane doc is the buildable checklist keyed by FX-id; the coder reads the findings doc for each task's specifics.
> **Stack:** React 19 + TypeScript + Tailwind v4 + Vite + React Router + TanStack Query. **Tests:** Vitest + Testing Library (`web/console`, `npm test`). **Design-of-record:** [../../../docs/console-design-spec.md](../../../docs/console-design-spec.md) + the canvas mockups.
> **Parent:** [lld/40](../../../lld/40-multi-tenant-console.md) · [ws-g-console.md](../ws-g-console.md) (M-G1..M-G4).

## Invariants (do NOT regress)
- Client RBAC render-gate is **UX-only**; server `require_role`/`require_platform` is the boundary. Missing role **HIDES** a control (fail-secure).
- Tenant is **server-derived** (never a client filter); near-real-time **POLL**, never streaming.
- An absent dep API **DEGRADES to PARTIAL/roadmap**, never a dead control or a **fabricated body**.
- Keep `tsc -b` + `npm test` green (baseline 37 files / 118 tests). Every behavior change gets a **non-vacuous** test (fails if the behavior regresses). Do not touch the verified-correct spine (org-first machinery, RBAC map, D3 parity, platform gate).

## Milestone FX-1 — HIGH (5)
- **FX-1.1** — Gate the Sigma enable/disable toggle on `usePlatformCan('sigma.retire')` (dead machinery today; `PolicyLibraryPage.tsx:286-317`). Hide for non-platform ops. UT `PolicyLibraryPage.sigmaGate.test.tsx`.
- **FX-1.2** — Bind Decision-detail to WS-D `GET /sessions/{id}/trail` (not legacy `/decisions`); add `sessionsApi.trail` + `SessionTrail` type; PARTIAL fallback on 404. UT `DecisionDetailPage.trail.test.tsx`.
- **FX-1.3** — Session-forensics summary header from `SessionInfo` (trust/deny counts/quarantine/timeline); Release gated on `quarantine.manage`. UT `SessionForensicsPage.test.tsx`.
- **FX-1.4** — Client-map agent ECS status → Active/Idle/Offline (`activityStatus.ts`); fix the lying `AgentStatus` type. UT `agents/__tests__/activityStatus.test.ts` (real ECS fixtures).
- **FX-1.5** — Platform Fleet Overview: bind `useOverview`/`useDecisionsTimeseries` (fleet mode) + `KpiGrid`/`AllowedVsBlockedChart`. Integ `features/platform/__tests__/fleetMetrics.integration.test.tsx`.

## Milestone FX-2 — MEDIUM: security-adjacent + correctness
- **FX-2.1** — Read/bootstrap 403 fail-safe: on a bound-tenant 403 (esp. `/v1/me`), `clearActiveTenant()` + bounce to `ORG_PAGE_PATH`; do NOT clear on a mutation role-403. UT `http.membership403.test.ts`.
- **FX-2.2** — Gate `PolicyEditorPage` Save/Create on `useCan('policies.write')` + guard the route. UT `PolicyEditorPage.gate.test.tsx`.
- **FX-2.3** — platformApi MUST NOT attach `X-Aegion-Tenant` (code-enforced `{omitTenant:true}`, not environmental); rewrite the circular test. UT `platform.tenantHeader.test.ts`.
- **FX-2.4** — Wire the sanitized-403 toast through the central `MutationCache` (no-op today at `queryClient.ts:29`). UT `queryClient.degrade.test.ts` (assert against the WIRED cache).
- **FX-2.5** — Confine a platform op to the platform tree (landing redirect `is_platform` → `/platform`). UT `app/__tests__/platformConfinement.test.tsx`.
- **FX-2.6** — Add the G2.8 window-focus demotion test (mechanism at `useMe.ts:26` exists, test missing). UT `useMe.refetch.test.tsx`.

## Milestone FX-3 — MEDIUM: canvas-fidelity + honest-degrade
- **FX-3.1** — Threats per-detector `winning_source` facet, **driven from API values** (not a FE constant). If the backend `winning_source`-on-`/decisions` field-add (ws-g-fix-backend) is absent → ship the facet **PARTIAL/disabled**, no crash, no hardcoded list. UT `ThreatsPage.facet.test.tsx`.
- **FX-3.2** — Relabel 'Live'/'Streaming'/'Real-time telemetry' → 'near-real-time (≤15s pull)' (`LiveActivity.tsx:52,55`, `OverviewPage.tsx:49,80`). UT `OverviewPage.label.test.tsx`.
- **FX-3.3** — Policy Detail: Cedar/JSON tabs render compiled body ONLY when present; else PARTIAL — **never fabricate** a `permit/forbid` body (`policyFormat.ts:110-163`). UT `PolicyDetailPage.format.test.tsx`.
- **FX-3.4** — Platform fleet grid: send `limit/cursor/sort/filter` (backend paging landed but unreachable); at minimum advance the cursor. UT `FleetOverviewPage.paging.test.tsx`.
- **FX-3.5** — Consent column: render "unknown"/neutral when `platform_read_consent` absent from the list row — NOT a universal amber "required". (ws-g-fix-backend can add the field to upgrade it.) UT `TenantGrid.consent.test.tsx`.
- **FX-3.6** — Render `quotaHeadroom()` (computed + unit-tested but shown nowhere) in the platform view. UT `TenantDetailPage.quota.test.tsx`.

## Acceptance
- [ ] All FX-1 (5 HIGH) closed with the named tests green.
- [ ] All FX-2 (6 security/correctness MED) closed; FX-2.3/FX-2.4 tests are non-circular (assert against the wired path).
- [ ] All FX-3 (6 canvas/degrade MED) closed; FX-3.1 + FX-3.5 correctly PARTIAL-degrade when the backend field is absent (no crash, no fabrication).
- [ ] `tsc -b` clean; `npm test` green; no vacuous tests; green baseline + verified spine preserved.
