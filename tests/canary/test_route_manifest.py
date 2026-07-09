"""WS-J J1.4 — the RouteSpec manifest shape (Appendix A)."""
from __future__ import annotations

import dataclasses

import pytest

from canary.route_manifest import (
    ALLOWED_AXES,
    ROUTE_MANIFEST,
    RouteSpec,
)


def test_manifest_row_count():
    """(a) 66 rows: 61 in-code /v1 + 4 demo-proxy + 1 public non-/v1 (/public/resolve-org,
    the WS-G org-first login route — added J8 §5C when the coverage guard flagged it as a
    wired-but-unmanifested route)."""
    assert len(ROUTE_MANIFEST) == 66


def test_manifest_auth_class_split():
    """(b) exactly 2 public, 39 oidc, 4 demo_proxy, rest key/key_gated.

    WS-N N8 reclassified the 21 read routes key->oidc (16 original + 21 = 37); WS-N D10
    (ADR-038) then reclassified the 2 remaining agent-lane GET reads (/trail + /signals)
    key->oidc → 39. All in lockstep with the in-app resolve_operator_tenant gate. J8 §5C
    added /public/resolve-org (public, non-/v1) → 2 public rows, total 66."""
    from collections import Counter

    c = Counter(s.auth_class for s in ROUTE_MANIFEST)
    assert c["public"] == 2
    assert c["oidc"] == 39
    assert c["demo_proxy"] == 4
    assert c["key"] + c["key_gated"] == 66 - 2 - 39 - 4


def test_authz_gap_rows_are_mutations():
    """(c) every authz_gap_flag row is a mutation (POST/PUT/DELETE/PATCH)."""
    mut = {"POST", "PUT", "DELETE", "PATCH"}
    for s in ROUTE_MANIFEST:
        if s.authz_gap_flag:
            assert s.method in mut, f"{s.method} {s.path} gap flag on a non-mutation"


def test_oidc_rows_deferred_in_increment_1():
    """(d) every oidc row has landed_flag=False (the Increment-1 console/auth defer)."""
    for s in ROUTE_MANIFEST:
        if s.auth_class == "oidc":
            assert s.landed_flag is False


def test_failure_axes_are_allowed():
    """(e) every failure_axis value is in the allowed axis set."""
    for s in ROUTE_MANIFEST:
        for axis in s.failure_axis:
            assert axis in ALLOWED_AXES, f"{s.path} {s.method}: bad axis {axis}"


def test_routespec_is_frozen():
    """(f) RouteSpec is frozen (mutation raises)."""
    spec = ROUTE_MANIFEST[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.path = "/mutated"  # type: ignore[misc]


def test_no_duplicate_rows():
    """Every (path, method) appears exactly once."""
    from collections import Counter

    dups = [k for k, v in Counter((s.path, s.method) for s in ROUTE_MANIFEST).items() if v > 1]
    assert not dups, f"duplicate manifest rows: {dups}"


def test_validate_row_landed_with_deny_axis():
    """/v1/validate is a landed key route carrying the DENY axis (DENY-is-200)."""
    v = next(s for s in ROUTE_MANIFEST if s.path == "/v1/validate" and s.method == "POST")
    assert v.landed_flag is True and v.auth_class == "key"
    assert "DENY" in v.failure_axis
