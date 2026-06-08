"""Unit tests for MetricsQueryService (WS-21 T02) — mocked CloudWatch GetMetricData."""
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from app.services.metrics_query_service import MetricsQueryService


def _svc(get_metric_data_return):
    cw = Mock()
    cw.get_metric_data.return_value = get_metric_data_return
    return MetricsQueryService(cloudwatch_client=cw), cw


def test_overview_aggregates_cloudwatch_values():
    svc, cw = _svc({
        "MetricDataResults": [
            {"Id": "total", "Values": [100.0]},
            {"Id": "allowed", "Values": [80.0]},
            {"Id": "denied", "Values": [20.0]},
            {"Id": "latency", "Values": [12.0]},
            {"Id": "trust", "Values": [87.0]},
        ]
    })
    out = svc.overview("24h")
    assert out["range"] == "24h"
    assert out["requests_total"] == 100
    assert out["allowed"] == 80
    assert out["denied"] == 20
    assert out["threats_blocked"] == 20
    assert out["avg_latency_ms"] == 12
    assert out["trust_score"] == 87
    # one GetMetricData call with the 5 expression queries
    assert cw.get_metric_data.call_count == 1
    queries = cw.get_metric_data.call_args.kwargs["MetricDataQueries"]
    assert {q["Id"] for q in queries} == {"total", "allowed", "denied", "latency", "trust"}


def test_overview_empty_data_returns_zeros_and_null_trust():
    svc, _ = _svc({"MetricDataResults": [
        {"Id": "total", "Values": []},
        {"Id": "allowed", "Values": []},
        {"Id": "denied", "Values": []},
        {"Id": "latency", "Values": []},
        {"Id": "trust", "Values": []},
    ]})
    out = svc.overview("1h")
    assert out["requests_total"] == 0
    assert out["allowed"] == 0
    assert out["threats_blocked"] == 0
    assert out["avg_latency_ms"] == 0
    # trust averages over no samples → None (not a misleading 0)
    assert out["trust_score"] is None


def test_overview_unknown_range_defaults_to_24h_window():
    svc, cw = _svc({"MetricDataResults": []})
    out = svc.overview("bogus")
    # echoes the requested token, but the window/period default to 24h
    assert out["range"] == "bogus"
    kwargs = cw.get_metric_data.call_args.kwargs
    span = (kwargs["EndTime"] - kwargs["StartTime"]).total_seconds()
    assert abs(span - 86400) < 5


def test_decisions_timeseries_dense_merge():
    t1 = datetime(2026, 6, 6, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 6, 6, 1, 0, tzinfo=timezone.utc)
    svc, _ = _svc({
        "MetricDataResults": [
            {"Id": "allowed", "Timestamps": [t1, t2], "Values": [10.0, 20.0]},
            {"Id": "blocked", "Timestamps": [t1], "Values": [3.0]},
        ]
    })
    out = svc.decisions_timeseries("24h", "1h")
    assert out["bucket"] == "1h"
    series = out["series"]
    assert len(series) == 2
    # bucket t1 has both; t2 has allowed only → blocked zero-filled
    assert series[0] == {"t": "2026-06-06T00:00:00Z", "allowed": 10, "blocked": 3}
    assert series[1] == {"t": "2026-06-06T01:00:00Z", "allowed": 20, "blocked": 0}


def test_decisions_timeseries_rejects_too_many_points():
    svc, _ = _svc({"MetricDataResults": []})
    # 30d @ 1h = 720 buckets > 200 cap → ValueError (route maps to HTTP 400)
    with pytest.raises(ValueError):
        svc.decisions_timeseries("30d", "1h")


def test_decisions_timeseries_30d_with_1d_bucket_ok():
    svc, _ = _svc({"MetricDataResults": []})
    out = svc.decisions_timeseries("30d", "1d")  # 30 buckets — fine
    assert out["series"] == []


def test_attack_category_count_distinct_threat_types():
    svc, cw = _svc({})
    cw.list_metrics.return_value = {
        "Metrics": [
            {"Dimensions": [{"Name": "AgentId", "Value": "a"}, {"Name": "ThreatType", "Value": "PROMPT_INJECTION"}]},
            {"Dimensions": [{"Name": "AgentId", "Value": "b"}, {"Name": "ThreatType", "Value": "PROMPT_INJECTION"}]},
            {"Dimensions": [{"Name": "AgentId", "Value": "c"}, {"Name": "ThreatType", "Value": "DATA_EXFIL"}]},
            {"Dimensions": [{"Name": "AgentId", "Value": "d"}]},  # no ThreatType dim
        ]
    }
    assert svc.attack_category_count() == 2
