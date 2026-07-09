"""WS-J J8 — hermetic guards for the console/OIDC coverage contract.

These run in the PR gate (no browser, no live target) and assert the STRUCTURE J8's
live scenarios rely on, so a drift is caught hermetically rather than only at 3am in
prod:

  * every ``oidc`` route carries a ``401`` axis (the no-identity live probe asserts it);
  * every ``oidc`` route is claimed by exactly one live-probe module (no un-probed
    operator route, no double-probe);
  * ``REQUIRED_SCENARIOS["J8"]`` is on (WS-G landed → J8 is required, not deferred);
  * the console-route sweep list matches the console's ``ROUTES`` registry (no
    console route silently un-swept) — the hermetic half of the §6.2 guard.
"""
from __future__ import annotations

import re
from pathlib import Path

from canary.route_manifest import REQUIRED_SCENARIOS, ROUTE_MANIFEST

_REPO = Path(__file__).resolve().parents[2]
_ROUTES_TS = _REPO / "web" / "console" / "src" / "app" / "routes.ts"


def _oidc_routes():
    return [s for s in ROUTE_MANIFEST if s.auth_class == "oidc"]


def test_j8_required_now():
    """WS-G CODE-DONE (lld/40) unblocked J8 — it is REQUIRED, not deferred."""
    assert REQUIRED_SCENARIOS["J8"] is True


def test_every_oidc_route_has_401_axis():
    """The no-identity live probe (test_oidc_routes_live) calls the 401 negative axis
    on every oidc route — so every oidc row MUST declare "401" (a tokenless operator
    call fail-secures to 401/403)."""
    missing = [f"{s.method} {s.path}" for s in _oidc_routes() if "401" not in s.failure_axis]
    assert not missing, f"oidc routes missing a 401 axis: {missing}"


def test_oidc_routes_probed_by_exactly_one_live_module():
    """Every oidc route (minus the 2 CloudWatch metrics rows owned by
    test_metrics_live) is covered by test_oidc_routes_live's no-identity sweep — no
    operator route is left un-probed live, and none is double-probed."""
    from canary.test_oidc_routes_live import _METRICS_LIVE_OWNED, _OIDC_ROUTES

    swept = {(s.method, s.path) for s in _OIDC_ROUTES}
    expected = {
        (s.method, s.path) for s in _oidc_routes() if s.path not in _METRICS_LIVE_OWNED
    }
    assert swept == expected, (
        f"oidc live-probe drift — un-probed: {expected - swept}; "
        f"unexpected: {swept - expected}"
    )
    # The 2 metrics rows are the ONLY oidc routes NOT in the no-identity sweep.
    metrics_oidc = {s.path for s in _oidc_routes()} & _METRICS_LIVE_OWNED
    assert metrics_oidc == set(_METRICS_LIVE_OWNED), (
        "the metrics rows expected to be oidc + owned by test_metrics_live changed"
    )


# --------------------------------------------------------------------------- §6.2
def _console_routes_from_ts() -> set:
    """Parse the ``path`` string literals from the console ``ROUTES = {...}`` export.
    A build-time source-of-truth join (the console-route guard's hermetic half) — the
    live Playwright sweep (test_console_sweep) visits these; this asserts the SWEEP
    LIST matches the registry so a new console route can't land un-swept."""
    if not _ROUTES_TS.exists():
        return set()
    text = _ROUTES_TS.read_text()
    # Grab the object body of `export const ROUTES = { ... }`.
    m = re.search(r"export const ROUTES\s*=\s*\{(.*?)\n\}", text, re.DOTALL)
    body = m.group(1) if m else ""
    # Each entry: `name: '/path'` — capture the single-quoted path literal.
    return set(re.findall(r":\s*'([^']+)'", body))


def test_console_sweep_list_matches_routes_registry():
    """§6.2 hermetic guard — the sweep's declared route list equals the console's
    ROUTES registry. RED on a registry entry with no sweep (CONSOLE_ROUTE_UNCOVERED)
    or a sweep path not in the registry (UNKNOWN_CONSOLE_ROUTE)."""
    from canary.console_routes import CONSOLE_SWEEP_ROUTES

    registry = _console_routes_from_ts()
    if not registry:  # routes.ts absent (shouldn't happen post-WS-G) — fail loud.
        raise AssertionError(f"console routes.ts not found at {_ROUTES_TS}")
    swept = set(CONSOLE_SWEEP_ROUTES)
    uncovered = registry - swept
    unknown = swept - registry
    assert not uncovered, f"CONSOLE_ROUTE_UNCOVERED (in routes.ts, no sweep): {uncovered}"
    assert not unknown, f"UNKNOWN_CONSOLE_ROUTE (swept, not in routes.ts): {unknown}"
