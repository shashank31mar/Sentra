"""WS-J J8.1/J8.2/J8.4 (browser) — the Playwright console lane: real hosted-UI login,
the console UI read-sweep, and the AUTHENTICATED leg of the oidc routes.

LIVE + BROWSER only. Two guards keep this out of the hermetic PR gate WITHOUT erroring
collection (the lean container has no Chromium; the PR gate has no browser):

  * ``pytestmark = requires_live`` — the hourly monitor runs it; the PR gate's
    ``-m "not requires_live"`` skips it.
  * a module-level ``playwright`` import guard — if Playwright is absent (any non-browser
    run, incl. the hermetic PR gate and a lean-image collection), the tests are
    ``pytest.skip``-collected, NEVER an ImportError at collection (which would blank the
    alarms — the lean-collection invariant, conftest §_LIVE_SAFE_MODULES).

The AUTHENTICATED legs need the ``canary_operator`` live form (J8.1) — a real
Cognito hosted-UI login (D-4). Until the founder provisions the ``sentra/canary/
console-user`` secret + the Cognito user, the fixture raises a clear precondition
error → the reporting plugin records INFRA (never a silent skip, never a false green).
"""
from __future__ import annotations

import pytest

# --- browser import guard (skip-collect, never error-collect) --------------------
playwright = pytest.importorskip(
    "playwright.sync_api",
    reason="Playwright/Chromium not installed — console (J8) scenarios are browser+live "
    "only; the hermetic PR gate and the lean live-image collect them as skips, never "
    "an ImportError (which would blank the canary alarms).",
)

from canary.console_routes import CONSOLE_SWEEP_ROUTES  # noqa: E402
from canary.route_manifest import ROUTE_MANIFEST  # noqa: E402

pytestmark = pytest.mark.requires_live


# The oidc routes whose AUTHENTICATED (operator-session) leg this module exercises.
# GET reads a viewer can perform; mutations a viewer cannot → documented 403 (mirrors
# J7.3). Platform routes with a non-platform viewer → 403. All go THROUGH the console
# host (cookie + nginx re-emit), never the api-key gateway host.
_OIDC_ROUTES = [s for s in ROUTE_MANIFEST if s.auth_class == "oidc"]


def _fill(path: str) -> str:
    import re

    return re.sub(r"\{[^}]+\}", "canary-probe-id", path)


# --------------------------------------------------------------------------- J8.2
@pytest.mark.parametrize("route", CONSOLE_SWEEP_ROUTES, ids=CONSOLE_SWEEP_ROUTES)
def test_console_route_renders(console_page, route):
    """J8.2 — each console route renders with no 5xx, no uncaught error, and its backing
    /v1 call(s) return 2xx-or-documented-4xx. ``console_page`` (J8.1 fixture) is an authed
    Playwright page whose network trace is captured. A ``/platform/*`` route for the
    non-platform viewer asserts a FAIL-SECURE render (empty/denied state, never a 5xx)."""
    result = console_page.visit(_fill(route))
    assert not result.saw_5xx, (
        f"console {route} produced a 5xx in its network trace: {result.five_xx_urls}"
    )
    assert result.rendered, f"console {route} did not render a landmark element"
    assert not result.uncaught_error, f"console {route} raised an uncaught render error"


# --------------------------------------------------------------------------- J8.4 (authed)
_AUTHED_READS = [s for s in _OIDC_ROUTES if s.method == "GET"]
_AUTHED_IDS = [f"{s.method} {s.path}" for s in _AUTHED_READS]


@pytest.mark.parametrize("spec", _AUTHED_READS, ids=_AUTHED_IDS)
def test_oidc_read_authenticated(console_oidc_client, spec):
    """J8.4 (authenticated leg) — a viewer operator session reaching an oidc GET read
    through the console host gets a DOCUMENTED status. The load-bearing assertion is the
    NEGATIVE one: NEVER a 401 (the session cookie carried → the gate saw a real operator,
    so a 401 means the login fixture / console-host routing is broken) and NEVER a 5xx.

    The positive code is route-shaped and NOT pinned to 200: an id-addressed read filled
    with the synthetic ``canary-probe-id`` legitimately hits the ownership gate —
    ``assert_owns(AGENT)`` on a non-tenant-prefixed id → 403, an opaque foreign
    id (tenant/policy/connection) → existence-masked 404 — and a platform route for the
    non-platform viewer → 403. All of those are CORRECT fail-secure behavior, not a leak.
    So we assert a documented, non-401, sub-500 status: 200 (readable/empty), 403
    (ownership/platform denied), or 404 (existence-masked)."""
    resp = console_oidc_client.get(_fill(spec.path))
    assert resp.status_code != 401, (
        f"authed GET {spec.path} → 401 — the operator session cookie did not carry "
        f"(login fixture / console-host routing broken)"
    )
    if spec.path.startswith("/v1/platform/"):
        # A non-platform viewer must be refused the platform lane (require_platform).
        assert resp.status_code == 403, (
            f"platform route {spec.path} for a non-platform viewer → {resp.status_code}, "
            f"expected 403 (fail-secure)"
        )
    else:
        assert resp.status_code in (200, 403, 404), (
            f"authed viewer GET {spec.path} → {resp.status_code}, expected 200 (readable), "
            f"403 (ownership-denied on the probe id), or 404 (existence-masked); never 401/5xx"
        )
