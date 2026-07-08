# WS-G-BACKEND — console backend prerequisites (M-G0 + fixtures + WS-G-owned backend regressions)

> **Build-lane doc (orchestration).** This is a **code-loop lane split** of the canonical
> [ws-g-console.md](../ws-g-console.md), NOT a new spec. It scopes ONLY the **backend/Python/CDK/pytest**
> tasks of WS-G so the `senior-sde-backend` coder builds this lane cleanly (the frontend lane is
> [ws-g-frontend.md](ws-g-frontend.md), built AFTER this one). **All task detail, `file:line`, and test
> names are canonical in [ws-g-console.md](../ws-g-console.md)** — this doc references task IDs, it does
> not restate them. Parent LLD: [lld/40-multi-tenant-console.md](../../../lld/40-multi-tenant-console.md) v1.6.

**Owner:** WS-G build (backend lane) · **Domain:** backend (Python controller + AWS CDK + pytest) ·
**Status:** ⬜ not started · **Base:** re-verify `file:line` at tip (`git rev-parse HEAD`) — the canonical doc's
line numbers are from an older commit and MUST be re-confirmed before editing (`ws-g-console.md:59`).

**Founder decision (2026-07-08):** build EVERYTHING incl. M-G0 + CDK this run (the doc marks M-G0 "owned
elsewhere"; the founder assigned it to this lane to unblock the pilot). **CDK/nginx is CODED + unit-tested
here; the actual `cdk deploy` stays a separate, explicitly-gated step** (production-safety: `Sentra-DEV-*`
stacks ARE prod, acct 531109575379 — never auto-deploy).

**Why this lane runs FIRST:** the frontend lane's **G2.9** parity test consumes `role-model.json` (**FAILS
LOUD if absent**) and **G2.12** org-first entry consumes the D14 `resolve_org` contract + `org.html`. Both are
produced here. Frontend cannot go green until this lane lands.

---

## Test commands (this lane)

Backend tests are **moto-safe** — a leaked real `AWS_PROFILE` causes ~37 spurious failures
(memory: controller-tests-moto-safe-env). Run under a scrubbed env with fake creds:

- **Controller unit/integration** (from repo root):
  ```
  cd src/security-controller && env -u AWS_PROFILE AWS_ACCESS_KEY_ID=testing \
    AWS_SECRET_ACCESS_KEY=testing AWS_DEFAULT_REGION=us-east-1 \
    venv/bin/python -m pytest tests/ test_*.py -q
  ```
- **CDK stack + repo-root integration** (from repo root):
  ```
  env -u AWS_PROFILE AWS_ACCESS_KEY_ID=testing AWS_SECRET_ACCESS_KEY=testing \
    AWS_DEFAULT_REGION=us-east-1 python -m pytest tests/unit/ tests/integration/ -q
  ```
The coder MUST run the tests it touches (controller vs CDK) before handing the diff; the integration gate
runs both suites.

---

## Milestone B0 — Pilot-blocking backend prerequisites (M-G0 core)

Canonical detail: [ws-g-console.md](../ws-g-console.md) §M-G0 (lines 57–167). Build all of:

- **G0.1 (D13) — shadow-write verified-tenant bind on `/v1/validate`.** PILOT-BLOCKING. Handler
  `routes.py` `validate_tool_call` (~:111), shadow branch (~:301–308); mirror the enforce-branch bind
  pattern (~:282/:299). Guard **strictly** on `ctx.is_verified` (no backfill); reset in `finally`.
  Tests (canonical): `test_routes.py::test_shadow_branch_binds_verified_tenant`,
  `::test_shadow_branch_unverified_stays_ambient`;
  `tests/integration/test_shadow_write_tenant_bind.py::test_shadow_decision_visible_to_tenant_overview`.
- **G0.2 (D14) — public `resolve_org(org) → {tenant_id}` endpoint.** PILOT-BLOCKING. NEW handler in
  `src/security-controller/app/api/tenancy_routes.py` on a **non-`/v1`** path (e.g. `/public/resolve-org`
  — `/v1/*` is 401-gated by the priority-5 ALB rule, so it must NOT live under `/v1`). Registry lookup vs
  `sentra-tenants`; **returns ONLY `{tenant_id}`** (zero counts/members/plan); miss → friendly **404**;
  internal error → **fail-closed 5XX, never a fake-200** (engineering error-contract rule); rate-limited.
  Org-NAME enumeration is ACCEPTED (founder 2026-07-08, LLD v1.6 `40:10`) — do not re-add a
  non-enumerating/miss==hit rule. Tests: `test_tenancy_routes.py::test_resolve_org_returns_only_tenant_id`,
  `::test_resolve_org_miss_friendly_not_found`, `::test_resolve_org_internal_error_fails_closed_5xx`;
  `tests/integration/test_resolve_org_public.py::test_resolve_org_reachable_without_cognito`,
  `::test_resolve_org_burst_throttled`.
- **G0.3 (D14) — static `org.html` + ALB public rule (priority < 5) + nginx location + private-ALB forward.**
  PILOT-BLOCKING. Precedent: the priority-3 `ConsoleSplashRule` at `cdk/stacks/compute_stack.py:895`
  (splash is priority 3; the `/v1` API rule `ConsoleApiListenerRule` is priority 5 — the org page + its
  `/public/resolve-org` XHR must be carved out **below 5**). Add: new `org.html` (self-contained like
  `splash.html`, NOT an SPA route — hashed `/assets/*` must fall through to auth), a public ALB listener
  rule priority < 5, an nginx `location` for `/public/resolve-org` that injects the api-key server-side,
  and the private-ALB forward rule. **Shape (b) "widen carve-out to `/assets/*`" is REJECTED** (canonical
  `ws-g-console.md:88`). Tests: `tests/unit/test_compute_stack.py::test_resolve_org_public_rule_priority_below_5`,
  `::test_private_alb_resolve_org_forward_rule_present`;
  `tests/integration/test_org_page_entry.py::test_org_html_served_unauth`,
  `::test_resolve_org_through_nginx_injects_apikey`.
- **G0.4 — per-tenant metrics rollup on `GET /v1/platform/tenants`.** Feeds the platform console (frontend
  G4). Handler `tenancy_routes.py:437` `platform_list_tenants`. Add a **single BATCHED** rollup keyed by
  tenant (fields `blocks_24h`, `deny_rate`, `trust`, `agents`, `quarantined`, `decisions_24h`).
  **Footgun (memory: overview-latency-root-cause):** one batched query, **NOT** N per-tenant scans — the
  latter caused the ~25s overview incident. Tests:
  `test_tenancy_routes.py::test_platform_list_tenants_includes_rollup_fields`,
  `::test_platform_rollup_single_batched_call`;
  `tests/integration/test_platform_grid.py::test_fleet_rollup_matches_per_tenant_sum`.
- **G0.5 — platform registry paging/sort/filter** on the same `platform_list_tenants` handler
  (`limit`/`cursor`/`sort`/`filter`). Tests: `test_tenancy_routes.py::test_platform_list_tenants_paginates`,
  `::test_platform_list_tenants_sort_filter`; `test_platform_grid.py::test_grid_pagination_stable_across_pages`.

---

## Milestone B1 — Backend field-adds the console binds (M-G0 PARTIAL polish + M-G3 prereqs)

Build the field-adds so the frontend renders real data instead of PARTIAL banners. Canonical:
[ws-g-console.md](../ws-g-console.md) §G0.10, §G0.11, §M-G3.3.

- **G0.10 — compiled Cedar/JSON read on `get_policy_by_id`** (`routes.py` ~:1583, returns YAML-from-S3 only
  today). Surface the compiled Cedar/JSON body so the Policy-detail Cedar/JSON tabs are real, not PARTIAL.
  Do **not** fabricate a compiled body when absent — return null/absent and let the client degrade.
- **G0.11 — quarantine origin + why-trace on the session read.** Fields are stored
  (`session_manager.py` ~:394 `quarantine_reason`/`quarantine_operator`) but `_format_session_for_api`
  (~:636) surfaces neither. Surface `quarantine_origin` + signals. Test:
  `test_session_manager.py::test_format_session_surfaces_quarantine_origin_and_signals`.
- **M-G3.3 field-add — `winning_source` on `GET /v1/decisions` rows.** `DecisionItem` (`api.ts:150`) lacks
  it (it lives on `DecisionCombined`). Add `winning_source` to the decision-row projection at `routes.py`
  (~:600) so the Threats per-detector facet is API-driven, not client-fabricated. Add/extend a controller
  test asserting the field is present on the rows projection.

---

## Milestone B2 — D3 role-model fixture generator (FRONTEND-BLOCKING)

Canonical: [ws-g-console.md](../ws-g-console.md) §G2.9 (the frontend consumer). **This lane OWNS the
generator** the frontend parity test reads.

- **B2.1 — emit `web/console/src/lib/__fixtures__/role-model.json`** from a backend route-walk over the
  FastAPI app: for every route carrying `require_role`/`require_platform`, emit `{ path, method, min_role
  or platform:true }`, plus the canonical `RANK` order (`viewer<editor<admin<owner`, from
  `deps.py` `_ROLE_ORDER` ~:39) and the `MIN_ROLE` map. This is the **single source of truth** the client
  RBAC map is checked against. The generator is a script/test-fixture (not a runtime route). Also emit a
  deliberately-broken `role-model.bad.json` for the frontend's negative parity test.
  - **Contract the frontend depends on (do not drift):** the JSON schema (keys `routes[]`, `rank[]`,
    `minRole{}`) MUST match what `web/console/src/lib/rbac.parity.test.ts` expects (frontend G2.9). If the
    generator can't run, the frontend test **fails loud, never skips** — so this fixture must exist + be
    valid before the frontend lane starts.
  - Test (backend): a pytest that runs the generator and asserts every `require_role`/`require_platform`
    route appears in the emitted JSON (completeness) + the emitted RANK matches `_ROLE_ORDER`.

---

## Milestone B3 — WS-G-owned backend regressions (FR-13.1 + operator-id)

Canonical: [ws-g-console.md](../ws-g-console.md) §G1.3, §M-G3.13. **No production behavior change** — these
prove existing behavior + confirm the client can drop dead stubs.

- **G1.3 — resolution uses membership, not email domain.** `test_multitenancy_identity.py` (exists) +
  `test_multitenancy_isolation.py` (exists). Exercise `resolve_operator_tenant` (`deps.py:374` →
  `_resolve_operator_tenant_inner:404`): seed `alice@acme.io` with a sole `t_globex` membership → assert
  `tenant_id == "t_globex"` (NOT `"acme.io"`). Moto-safe. Tests:
  `test_multitenancy_identity.py::test_resolution_uses_membership_not_email_domain`,
  `test_multitenancy_isolation.py::test_domain_matching_tenant_never_auto_bound`.
- **M-G3.13 backend half — confirm the server does NOT require a client `operator_id`.** Server derives
  operator from `ctx.sub`. Add `test_verdict_quarantine_operator.py` proving `POST .../verdict` +
  `POST /quarantine/{id}` succeed **without** a client-supplied `operator_id` (so the frontend can drop the
  stub in its M-G3.13). If the server currently 422-requires the field, that's a real gap — fix the server
  to derive from `ctx.sub`, don't just delete the test expectation.

---

## Acceptance (this lane) — canonical checklist rows this lane owns

From [ws-g-console.md](../ws-g-console.md) §Acceptance (M-G0 + the backend-owned rows):
- [ ] G0.1 shadow-write bind tests green (verified binds, unverified stays ambient, tenant-overview sees it).
- [ ] G0.2 `resolve_org` returns id-only, friendly-404 on miss, fails-closed 5XX on error, reachable
      without Cognito, burst-throttled.
- [ ] G0.3 `org.html` served unauth + ALB rule priority < 5 + private-ALB forward present + nginx injects
      api-key on `/public/resolve-org`.
- [ ] G0.4 rollup fields present + computed in a SINGLE batched call (not N scans) + matches per-tenant sum.
- [ ] G0.5 platform registry paginates + sorts + filters, stable across pages.
- [ ] G0.10 compiled Cedar/JSON surfaced (or honestly absent); G0.11 quarantine origin+signals surfaced;
      `winning_source` on `/v1/decisions` rows.
- [ ] **B2.1 `role-model.json` (+ `role-model.bad.json`) emitted, valid, complete** vs every
      `require_role`/`require_platform` route (the frontend parity test's hard prerequisite).
- [ ] G1.3 resolution-uses-membership regression + domain-never-auto-bound isolation test green.
- [ ] M-G3.13 backend: verdict/quarantine succeed without client `operator_id`.
- [ ] Full backend suite green under moto-safe env; **no `cdk deploy`** performed (deploy is a later gated
      step).

## Do-NOT (this lane)
- Do NOT run `cdk deploy` / mutate any AWS resource — code + `cdk synth`/unit-test only (prod-safety).
- Do NOT put `resolve_org` under `/v1` (the priority-5 rule 401s it); it MUST be a non-`/v1` public path.
- Do NOT fan out N per-tenant scans for the rollup (overview-latency incident) — one batched query.
- Do NOT return a fake-200 wrapping an error from `resolve_org` — honest 404 (miss) / 5XX (fault).
- Do NOT fabricate a compiled-Cedar body when absent — return absent, let the client PARTIAL-degrade.
- Do NOT change the `role-model.json` schema without updating the frontend consumer contract note here.
