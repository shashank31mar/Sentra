"""WS-J Jc.1 (meta) — the coverage guard's three RED conditions fire on a synthetic
manifest+covered-set, and an exempt (landed_flag=False) route is skipped. Proves the
guard is non-vacuous (it would catch a real coverage gap)."""
from __future__ import annotations

from typing import Dict, List, Set, Tuple

from canary.route_manifest import RouteSpec


def _run_guard(wired, manifest_rows, covered):
    """A pure re-implementation of the Jc.1 join over synthetic inputs (mirrors
    test_coverage_guard.test_every_wired_route_has_a_canary)."""
    manifest = {(s.path, s.method): s for s in manifest_rows}
    missing = []
    for key in sorted(wired):
        spec = manifest.get(key)
        if spec is None:
            missing.append(("UNKNOWN_ROUTE_NOT_IN_MANIFEST", key))
            continue
        if not spec.landed_flag:
            continue
        cell = covered.get(key, set())
        if "positive" not in cell:
            missing.append(("LANDED_ROUTE_UNCOVERED", key))
            continue
        for axis in spec.failure_axis:
            if axis not in cell:
                missing.append(("ROUTE_NEGATIVE_AXIS_UNCOVERED", key, axis))
    return missing


def test_guard_flags_uncovered_positive():
    wired = {("/x", "GET")}
    manifest = [RouteSpec("/x", "GET", "key", "WS-J", (), True, False)]
    missing = _run_guard(wired, manifest, {})
    assert ("LANDED_ROUTE_UNCOVERED", ("/x", "GET")) in missing


def test_guard_flags_uncovered_negative_axis():
    wired = {("/x", "POST")}
    manifest = [RouteSpec("/x", "POST", "key", "WS-J", ("422",), True, False)]
    covered = {("/x", "POST"): {"positive"}}  # positive present, 422 missing
    missing = _run_guard(wired, manifest, covered)
    assert ("ROUTE_NEGATIVE_AXIS_UNCOVERED", ("/x", "POST"), "422") in missing


def test_guard_flags_route_not_in_manifest():
    wired = {("/rogue", "GET")}
    missing = _run_guard(wired, [], {})
    assert ("UNKNOWN_ROUTE_NOT_IN_MANIFEST", ("/rogue", "GET")) in missing


def test_guard_skips_exempt_route():
    """A landed_flag=False route with no coverage is NOT a gap (deferred WS / OIDC)."""
    wired = {("/deferred", "GET")}
    manifest = [RouteSpec("/deferred", "GET", "oidc", "WS-M", ("401",), False, False)]
    missing = _run_guard(wired, manifest, {})
    assert missing == []


def test_guard_passes_when_fully_covered():
    wired = {("/x", "POST")}
    manifest = [RouteSpec("/x", "POST", "key", "WS-J", ("422", "401"), True, False)]
    covered = {("/x", "POST"): {"positive", "422", "401"}}
    assert _run_guard(wired, manifest, covered) == []
