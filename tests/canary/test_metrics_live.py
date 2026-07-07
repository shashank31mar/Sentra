"""WS-J — the metrics routes that CANNOT run hermetically (moto does not emulate
CloudWatch GetMetricData). Marked ``requires_live`` so the hourly ECS monitor covers
them against real prod while the PR-gate skips them (an honest, documented gap; the
manifest marks these two rows ``landed_flag=False`` so the coverage guard exempts them
from the hermetic gate).

WS-N N8 (lockstep with the read-route auth gate): ``/v1/metrics/overview`` and
``/v1/metrics/decisions-timeseries`` are now ``resolve_operator_tenant``-gated (oidc
class in the manifest). A tokenless probe (X-Api-Key only, no OIDC) is now EXPECTED to
401 — so the old positive-200 probe would false-RED against the deployed gate. We keep
ONLY the 401 probe (the correct expectation for an oidc route); the happy-path 200 is
unreachable without an operator OIDC session and is not asserted here (mirrors the
manifest's oidc rows, which carry no positive probe)."""
from __future__ import annotations

import pytest

from canary import scenarios


@pytest.mark.requires_live
@pytest.mark.parametrize("path", ["/v1/metrics/overview", "/v1/metrics/decisions-timeseries"])
def test_metrics_401_live(canary_client, path):
    """Live-only 401 probe: WS-N gated these to OIDC, so a tokenless call MUST 401
    (was a positive-200 probe pre-WS-N; the 200 path needs an operator OIDC session)."""
    scenarios.scenario_j2_4_negative(canary_client, path, "GET", "401")
