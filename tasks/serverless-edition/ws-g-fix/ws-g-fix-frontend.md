# ws-g-fix-frontend — console review-findings fix lane (frontend) — ROUND 2 (residuals)

> **Doc role:** code-loop frontend build lane, **round 2**. Round 1 closed 20 of 22 review findings + 4 integration-sentinel green≠correct gaps; the suite is GREEN on `integration/ws-g-fix` (53 files / 170 tests). This round closes the **4 residual findings** the sentinel raised at the round-cap. **Full round-1 detail:** [../ws-g-fix-review-findings.md](../ws-g-fix-review-findings.md). **DO NOT re-do round-1 work** — only the FXR items below are open (each verified against the current `integration/ws-g-fix` tip 2026-07-09).
> **Stack:** React 19 + TS + Tailwind v4 + Vite + TanStack Query. **Tests:** Vitest (`web/console`, `npm test`). **Build ON `integration/ws-g-fix`** (not fresh off main) so round-1 work is preserved.

## Invariants (do NOT regress)
- Client RBAC render-gate is UX-only; server is the boundary. Missing role HIDES a control. Tenant server-derived. Near-real-time POLL. Absent dep → PARTIAL, never a dead control or fabricated body.
- Keep `tsc -b` + `npm test` green (baseline 53 files / 170 tests). Every fix gets a **non-vacuous** test (fails if reverted). Do not touch the verified-correct spine.

## Milestone FXR — the 4 residuals

### FXR-1 — 403 double-toast: page handler must not toast when the global 403 bridge handled it (MEDIUM)
- **Evidence:** `app/queryClient.ts:33` wires `handleAuthDegrade(error, queryClient, emitErrorToast)` which **returns true + toasts a sanitized message on a 403**. But page-level mutation `onError` handlers ALSO surface their own message on a 403 → **two toasts/banners**. Worse, `PolicyEditorPage.tsx:151` maps *any* 403 to the misleading banner *"This policy is disabled. Enable it first."* — which also fires for a membership/role 403.
- **Fix:** page-level mutation error handlers must **skip their own toast/banner when the error is a 403 that the global bridge handles** — either check `e.status === 403` and defer to the global sanitized toast, or have `handleAuthDegrade` expose "was handled" and skip on true. In `PolicyEditorPage.tsx:151`, only show the "policy is disabled" banner for the **specific** disabled-policy reason (key off the error body reason/code), NOT a bare `status === 403` (which conflates disabled-policy, role-403, and membership-403). Check `SessionForensicsPage.tsx:54` release `onError` and any other mutation `onError` for the same double-toast.
- **Footgun:** do NOT drop the global bridge (it's the fail-secure sanitized-message path FX-2.4 wired) — suppress the *page* duplicate, keep the global one.
- **Unit:** `queryClient.doubleToast.test.tsx` (or extend the degrade test) — a mutation 403 through the wired cache produces **exactly one** sanitized toast, not two; `PolicyEditorPage` shows the "disabled" banner ONLY for the disabled-policy reason, and NOT for a role/membership 403.

### FXR-2 — read-403 role-vs-membership: add the role-403-on-a-read test (MOSTLY DONE — lock it) (MEDIUM)
- **Evidence:** `lib/http.ts:257-264` ALREADY keys the tenant-eject on `isLostTenantBinding403(body)` (the server's reason, `http.ts:101`), NOT on "GET+403" — so a role-gated read (e.g. admin-gated `GET /tenants/{id}/members`) does NOT wrongly eject the operator. The mechanism is correct; the gap is **test coverage** of the role-403-on-a-read branch.
- **Fix:** no source change expected (verify the predicate is right). Add the missing test case: a **role-403 on a READ** (body reason = "requires role", NOT a lost-membership code) does **NOT** call `bounceToOrgOnLostTenant()` / does NOT clear `aegion.activeTenant`; a **membership-lost 403 on a read** DOES. If `isLostTenantBinding403` mis-classifies, fix its body-reason matching.
- **Unit:** extend `lib/__tests__/http.membership403.test.ts` — `role-403 on a read → binding preserved, no org bounce`; `membership-lost 403 on a read → binding cleared + org bounce`.

### FXR-3 — FX-3.1 facet FILTERING is untested (green≠correct gap) (MEDIUM)
- **Evidence:** `ThreatsPage.tsx:102-104` filters rows by the selected `winning_source` (`if (facetAvailable && source !== ALL_SOURCES) out = out.filter(d => d.winning_source === source)`), but `ThreatsPage.facet.test.tsx` only asserts (a) options are DERIVED from the values (`:61`) and (b) PARTIAL degrade when absent (`:78`) — it **never selects a source and asserts rows filter**. Reverting/inverting the predicate stays green.
- **Fix:** no source change expected — add the behavioral test.
- **Unit:** extend `ThreatsPage.facet.test.tsx` — seed rows with mixed `winning_source` (sigma×2, policy×1), `userEvent.selectOptions(facet, 'sentra.sigma')`, assert **only the sigma rows render** (policy row absent) and the loaded-count label updates. A revert of the filter predicate must turn this test red.

### FXR-4 — sourceLabel multi-word formatter unverified (LOW, cosmetic)
- **Evidence:** `ThreatsPage.tsx:28` `sourceLabel` strips `sentra.`, underscores→spaces, title-cases via a `\b\w` regex; the facet test only checks single-word 'Sigma'/'Policy'. Multi-token (`sentra.ml_classifier` → 'Ml Classifier') is unverified.
- **Fix:** none expected — add the formatter assertion.
- **Unit:** extend `ThreatsPage.facet.test.tsx` — a row with `winning_source:'sentra.ml_classifier'` yields option text 'Ml Classifier' (multi-word title-case verified).

## Acceptance
- [ ] FXR-1 — exactly one toast on a mutation 403; PolicyEditor "disabled" banner only for the disabled-policy reason (not role/membership 403). Test green.
- [ ] FXR-2 — role-403-on-a-read preserves the binding; membership-lost-403 clears it. Test green.
- [ ] FXR-3 — selecting a `winning_source` filters rows (reverting the predicate turns it red). Test green.
- [ ] FXR-4 — multi-word sourceLabel verified. Test green.
- [ ] `tsc -b` clean; `npm test` green; no vacuous tests; round-1 work (170 tests) + the verified spine preserved. Then promote `integration/ws-g-fix` → main.
