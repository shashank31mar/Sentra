# ws-g-fix-backend — console review-findings fix lane (backend, OPTIONAL)

> **⏸️ DEFERRED — pending a design partner (founder 2026-07-09).** Not "forgotten" or "TODO": a deliberate anti-over-build decision. The two views this lane would upgrade (Threats detector-facet, platform Consent column) ship **honest PARTIAL** today — nothing looks broken. Build this lane only when a design partner concretely needs the detector-facet filter or the fleet consent-at-a-glance column; not before. The console is sufficiently built for the current stage.

> **Doc role:** code-loop backend build lane — **optional**. Two field-adds that upgrade two frontend PARTIAL states to full fidelity. The frontend lane ships without these (honest PARTIAL), so this lane is **not blocking**. **Full detail in [../ws-g-fix-review-findings.md](../ws-g-fix-review-findings.md)** (FX-3.1, FX-3.5).
> **Stack:** Python + pytest (`src/security-controller`). **Tests moto-safe:** `env -u AWS_PROFILE` + fake creds + `venv/bin/python`. **No CDK, no `cdk deploy`, no AWS mutation.**
> **Parent:** [lld/40](../../../lld/40-multi-tenant-console.md) §6.4 (winning_source facet), §6.11 (consent). Owner class = WS-N/WS-M-backend (shared `routes.py`/`tenancy_routes.py`).

## Invariants (do NOT regress)
- These are **additive read-field projections** — do NOT change tenant-scoping, auth, or the existing response contract shape beyond adding the named field. Keep the controller suite green (moto-safe).
- Both fields already exist server-side elsewhere; this only projects them onto the list responses the console reads.

## Milestone FXB-1 — the 2 field-adds
- **FXB-1.1 (FX-3.1 backend half)** — Add `winning_source` to each row of `GET /v1/decisions` (`scan_decisions`, `decisions_service.py`). It exists on `SessionDecision.combined` (`types` — the combiner's deciding source) but NOT on the list-scan row shape the Threats view reads. Project it so the FE facet (FX-3.1) can drive its options from real API values.
  - **Unit:** `test_decisions_service.py::test_scan_decisions_row_carries_winning_source` — a seeded decision's scan row includes `winning_source` matching the combiner verdict; tenant-scoping unchanged.
- **FXB-1.2 (FX-3.5 backend half)** — Project `tenant.platform_read_consent` onto each row of `platform_list_tenants` (`tenancy_routes.py:665-675`). It's returned on the DETAIL route (`:732`) but omitted from the list, so the console Consent column shows a false universal "required". Add the field to the list row dict (still `require_platform`, still `_audit_platform_read`).
  - **Unit:** `test_tenancy_routes.py::test_platform_list_projects_consent` — list rows carry `platform_read_consent` matching the tenant record; platform-gate + audit unchanged.

## Acceptance
- [ ] FXB-1.1 `winning_source` on `/decisions` scan rows (tenant-scoping + auth unchanged) — test green.
- [ ] FXB-1.2 `platform_read_consent` on `platform_list_tenants` rows (platform-gate + audit unchanged) — test green.
- [ ] Controller suite green (moto-safe); no contract shape change beyond the 2 additive fields; no CDK/deploy.
- [ ] After this lands, re-verify FX-3.1 + FX-3.5 upgrade from PARTIAL → full in the frontend.
