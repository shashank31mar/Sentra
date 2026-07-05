"""WS-J — the metrics routes that CANNOT run hermetically (moto does not emulate
CloudWatch GetMetricData). Marked ``requires_live`` so the hourly ECS monitor covers
them against real prod while the PR-gate skips them (an honest, documented gap; the
manifest marks these two rows ``landed_flag=False`` so the coverage guard exempts them
from the hermetic gate)."""
from __future__ import annotations

import pytest

from canary import scenarios


@pytest.mark.requires_live
@pytest.mark.parametrize("path", ["/v1/metrics/overview", "/v1/metrics/decisions-timeseries"])
def test_metrics_positive_live(canary_client, path):
    """Live-only positive probe for the CloudWatch-backed metrics routes."""
    scenarios.scenario_j2_4_positive(canary_client, path, "GET")


@pytest.mark.requires_live
@pytest.mark.parametrize("path", ["/v1/metrics/overview", "/v1/metrics/decisions-timeseries"])
def test_metrics_401_live(canary_client, path):
    """Live-only 401 probe (the API Gateway key check the app never sees in-process)."""
    scenarios.scenario_j2_4_negative(canary_client, path, "GET", "401")
