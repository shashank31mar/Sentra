"""WS-J J8.2/J8.3 — the console-route sweep list (the §6.2 coverage-guard join key).

The authoritative console route registry is ``web/console/src/app/routes.ts``
(``export const ROUTES``). This list mirrors it and is the set the live Playwright
sweep (``test_console_sweep``) visits. ``test_j8_coverage.test_console_sweep_list_
matches_routes_registry`` asserts this list EQUALS the parsed ``routes.ts`` registry —
so a console route added in the frontend without a canary sweep is a hermetic RED
(``CONSOLE_ROUTE_UNCOVERED``), and a stale entry here is ``UNKNOWN_CONSOLE_ROUTE``.

Kept as an explicit Python list (not parsed at runtime) so the sweep has a stable,
reviewable target; the guard test is what keeps it honest against the .ts source.

``:param`` templates (``/agents/:agentId``) are swept with a synthetic id filled in by
the sweep — an id-addressed console page renders its empty/not-found state (never a
5xx) against the empty canary tenant, which is the assertion (render + no-5xx +
backing /v1 2xx-or-documented-4xx), same shape as the id-addressed API reads.

PLATFORM routes (``/platform/*``) are swept too: the canary operator is a non-platform
``viewer``, so the sweep asserts the FAIL-SECURE render (an empty/denied state, NOT a
5xx and NOT a crash) — the console must degrade safely for a non-platform operator.
"""
from __future__ import annotations

# Mirrors web/console/src/app/routes.ts `ROUTES` (verified by the guard test).
CONSOLE_SWEEP_ROUTES = [
    "/",                                 # overview
    "/threats",
    "/deployments",
    "/agents",
    "/agents/:agentId",                  # agentDetail
    "/topology",
    "/connect",
    "/import",
    "/deploy",
    "/policies",
    "/policies/new",                     # policyNew
    "/policies/:policyId/edit",          # policyEdit
    "/policies/:policyId",               # policyDetail
    "/quarantine",
    "/identity/residual-agents",         # residualAgents
    "/audit",
    "/activity",
    "/decisions/:sessionId/:requestId",  # decisionDetail
    "/sessions/:sessionId",              # sessionDetail
    "/usage",
    # --- platform tree (is_platform-gated; non-platform canary user → fail-secure) ---
    "/platform",                         # platformOverview
    "/platform/tenants",                 # platformTenants
    "/platform/tenants/:tenantId",       # platformTenantDetail
    "/platform/topology",                # platformTopology
    "/platform/health",                  # platformHealth
]
