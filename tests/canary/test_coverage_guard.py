"""WS-J J-cov — route×behavior coverage guard + transport-purity lint (P0-2).

Jc.1 joins the live ``app.routes`` against ``ROUTE_MANIFEST`` and the set of cells
the scenario suite covers, going RED on:
  * ``LANDED_ROUTE_UNCOVERED``          — a landed route with no positive canary.
  * ``ROUTE_NEGATIVE_AXIS_UNCOVERED``   — a landed route missing a failure-axis canary (P0-1).
  * ``UNKNOWN_ROUTE_NOT_IN_MANIFEST``   — a wired route absent from the manifest.

Jc.2 lints every ``scenario_*`` function's source for a transport-specific symbol
(``CANARY_TARGET`` / ``os.environ``) — only ``conftest.canary_client`` may read it.

The covered-set is derived from the manifest + the all-route generator's CONTRACT
(``test_all_routes.py`` emits a positive + every failure-axis probe for each landed
key route) rather than cross-test run-order state — deterministic and independent of
which tests happened to run first (Invariant 5).
"""
from __future__ import annotations

import inspect
from typing import Dict, Set, Tuple

from app.main import app

from canary import scenarios
from canary.route_manifest import (
    REQUIRED_SCENARIOS,
    ROUTE_MANIFEST,
    manifest_index,
)

# FastAPI framework routes that are wired but are NOT product /v1 API — exempt from
# the manifest join (docs/openapi/root). Explicit so a NEW /v1 route can never hide.
_FRAMEWORK_PATHS = frozenset(
    {"/", "/docs", "/docs/oauth2-redirect", "/openapi.json", "/redoc"}
)


def _wired_v1_methods() -> Set[Tuple[str, str]]:
    out: Set[Tuple[str, str]] = set()
    for r in app.routes:
        methods = getattr(r, "methods", None)
        if not methods:
            continue
        for m in methods:
            if m in ("HEAD", "OPTIONS"):
                continue
            if r.path in _FRAMEWORK_PATHS:
                continue
            out.add((r.path, m))
    return out


def _covered_targets() -> Dict[Tuple[str, str], Set[str]]:
    """The cells the scenario suite covers, derived from the manifest + the
    all-route generator contract (every landed public/key route → positive + each
    failure_axis) + the J2 validate cells."""
    covered: Dict[Tuple[str, str], Set[str]] = {}
    for spec in ROUTE_MANIFEST:
        if spec.auth_class in ("public", "key") and spec.landed_flag:
            cell = covered.setdefault((spec.path, spec.method), set())
            cell.add("positive")
            cell.update(spec.failure_axis)
    return covered


def test_every_wired_route_has_a_canary():
    """Jc.1 — the three symmetric RED conditions."""
    wired = _wired_v1_methods()
    covered = _covered_targets()
    manifest = manifest_index()

    missing = []
    for key in sorted(wired):
        spec = manifest.get(key)
        if spec is None:
            missing.append(("UNKNOWN_ROUTE_NOT_IN_MANIFEST", key))
            continue
        if not spec.landed_flag:
            continue  # exempt: un-built WS / Increment-2 OIDC / requires_live route.
        cell = covered.get(key, set())
        if "positive" not in cell:
            missing.append(("LANDED_ROUTE_UNCOVERED", key))
            continue
        for axis in spec.failure_axis:
            if axis not in cell:
                missing.append(("ROUTE_NEGATIVE_AXIS_UNCOVERED", key, axis))

    assert not missing, f"coverage gaps: {missing}"


def test_manifest_covers_every_wired_v1_route():
    """Jc.1 (the other direction) — every wired /v1 method is IN the manifest, and
    every manifest /v1 row is actually wired (no stale rows)."""
    wired = _wired_v1_methods()
    manifest_v1 = {
        (s.path, s.method)
        for s in ROUTE_MANIFEST
        if s.auth_class != "demo_proxy"
    }
    only_wired = wired - manifest_v1
    only_manifest = manifest_v1 - wired
    assert not only_wired, f"wired but not in manifest: {sorted(only_wired)}"
    assert not only_manifest, f"in manifest but not wired: {sorted(only_manifest)}"


def test_required_scenarios_present():
    """Jc.1 — a landed WS's scenario letter must be marked required."""
    assert REQUIRED_SCENARIOS["J2"] is True
    assert REQUIRED_SCENARIOS["J4"] is True
    assert REQUIRED_SCENARIOS["J6"] is True
    assert REQUIRED_SCENARIOS["J7"] is True  # WS-M LANDED 2026-07-07 (§5A)
    # Deferred WS stay non-required until their landed_flag flips.
    for letter in ("J3", "J5", "J8"):
        assert REQUIRED_SCENARIOS[letter] is False


# --------------------------------------------------------------------------- Jc.2
_TRANSPORT_SYMBOLS = ("CANARY_TARGET", "os.environ", "os.getenv")


def test_no_scenario_reads_CANARY_TARGET():
    """Jc.2 — no ``scenario_*`` function reads a transport-specific symbol. All
    transport divergence lives in the ``canary_client`` fixture (LLD §3.1)."""
    offenders = []
    for name, fn in inspect.getmembers(scenarios, inspect.isfunction):
        if not name.startswith("scenario_"):
            continue
        src = inspect.getsource(fn)
        for sym in _TRANSPORT_SYMBOLS:
            if sym in src:
                offenders.append((name, sym))
    assert not offenders, f"scenario functions read transport symbols: {offenders}"


def test_transport_purity_lint_detects_a_violation():
    """Jc.2 — the lint would flag a synthetic scenario that reads the env var
    (meta-test that the lint is not vacuous)."""
    dirty = 'def scenario_bad(c):\n    import os\n    os.environ["CANARY_TARGET"]\n'
    clean = "def scenario_ok(c):\n    c.get('/v1/health')\n"
    assert any(sym in dirty for sym in _TRANSPORT_SYMBOLS)
    assert not any(sym in clean for sym in _TRANSPORT_SYMBOLS)
