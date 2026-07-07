"""WS-J J2.4 — the all-route positive + negative case generator (P0-1 headline).

For EACH API-key-reachable landed route (public + key; the 16 oidc rows and the
key_gated feedback-delete are exempt in Increment 1 via ``landed_flag=False``), emit
a positive happy-path probe AND one negative probe per ``failure_axis`` entry. Each
probe registers its covered cell so the Jc.1 coverage guard can require it.

Negative coverage is a HARD gate (J2.4 footgun): a route with only a positive check
is a RED ``ROUTE_NEGATIVE_AXIS_UNCOVERED`` gap in the coverage guard.
"""
from __future__ import annotations

import pytest

from canary import scenarios
from canary.route_manifest import ROUTE_MANIFEST

# API-key-reachable landed routes only (public + key). oidc/key_gated/demo_proxy are
# landed_flag=False in Increment 1 → exempt (task §3 scope line).
_KEY_ROUTES = [
    s for s in ROUTE_MANIFEST
    if s.auth_class in ("public", "key") and s.landed_flag
]

_POSITIVE_IDS = [f"{s.method} {s.path}" for s in _KEY_ROUTES]
_NEGATIVE = [
    (s, axis) for s in _KEY_ROUTES for axis in s.failure_axis
]
_NEGATIVE_IDS = [f"{s.method} {s.path} [{axis}]" for s, axis in _NEGATIVE]


@pytest.mark.parametrize("spec", _KEY_ROUTES, ids=_POSITIVE_IDS)
def test_route_positive(canary_client, spec):
    scenarios.scenario_j2_4_positive(
        canary_client, spec.path, spec.method,
        authz_gap=spec.authz_gap_flag, dataplane_bind=spec.dataplane_bind,
    )


@pytest.mark.parametrize("spec,axis", _NEGATIVE, ids=_NEGATIVE_IDS)
def test_route_negative(canary_client, spec, axis):
    scenarios.scenario_j2_4_negative(canary_client, spec.path, spec.method, axis)
