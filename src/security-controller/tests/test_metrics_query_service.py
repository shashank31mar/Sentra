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
    # one GetMetricData call. No "total" query — ValidationsTotal always carries a Decision dim,
    # so total = allowed + denied (an unfiltered SEARCH would match nothing). See overview().
    assert cw.get_metric_data.call_count == 1
    queries = cw.get_metric_data.call_args.kwargs["MetricDataQueries"]
    assert {q["Id"] for q in queries} == {"allowed", "denied", "latency", "trust"}


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


# --------------------------------------------------------------------------- #
# WS-N D11 — per-tenant overview (the primary rescope, not the null-fallback)
# --------------------------------------------------------------------------- #
def test_overview_tenant_scoped_queries_decisions_stream():
    """overview(tenant_id="t_a") builds SEARCH expressions over the tenant-dimensioned
    Decisions{tenant_id,verdict}+ValidateLatency{tenant_id} streams (NOT the fleet-wide
    ValidationsTotal), filtered on tenant_id="t_a". trust is NOT queried (no per-tenant
    trust stream) → trust_score null."""
    svc, cw = _svc({
        "MetricDataResults": [
            {"Id": "allowed", "Values": [8.0]},
            {"Id": "denied", "Values": [2.0]},
            {"Id": "latency", "Values": [11.0]},
        ]
    })
    out = svc.overview("24h", tenant_id="t_a")
    assert out["requests_total"] == 10
    assert out["allowed"] == 8
    assert out["denied"] == 2
    assert out["threats_blocked"] == 2
    assert out["avg_latency_ms"] == 11
    assert out["trust_score"] is None  # no per-tenant trust CW stream

    queries = cw.get_metric_data.call_args.kwargs["MetricDataQueries"]
    ids = {q["Id"] for q in queries}
    assert ids == {"allowed", "denied", "latency"}  # NO 'trust' query in the tenant path
    exprs = " ".join(q["Expression"] for q in queries)
    # tenant-dimensioned streams + the tenant filter — NOT the fleet ValidationsTotal
    assert 'MetricName="Decisions"' in exprs
    assert 'MetricName="ValidateLatency"' in exprs
    assert 'tenant_id="t_a"' in exprs
    assert 'verdict="ALLOW"' in exprs and 'verdict="DENY"' in exprs
    assert "ValidationsTotal" not in exprs  # fleet stream must NOT be used for a tenant read


def test_overview_fleet_path_unchanged_when_tenant_none():
    """overview() with no tenant_id (platform/fleet) still queries the fleet-wide
    ValidationsTotal + TrustScoreAverage streams (the pre-D11 behavior)."""
    svc, cw = _svc({"MetricDataResults": [
        {"Id": "allowed", "Values": [80.0]}, {"Id": "denied", "Values": [20.0]},
        {"Id": "latency", "Values": [12.0]}, {"Id": "trust", "Values": [87.0]},
    ]})
    out = svc.overview("24h")  # tenant_id defaults to None
    assert out["trust_score"] == 87
    exprs = " ".join(q["Expression"] for q in cw.get_metric_data.call_args.kwargs["MetricDataQueries"])
    assert 'MetricName="ValidationsTotal"' in exprs
    assert 'MetricName="TrustScoreAverage"' in exprs
    assert "tenant_id=" not in exprs  # fleet path is not tenant-filtered


def test_search_tenant_rejects_unsafe_tenant_id():
    """WS-N D11 defence-in-depth: a tenant_id with a SEARCH metachar is REJECTED (raise),
    never interpolated — fail-secure against a future non-slug id / injection path."""
    import pytest as _pytest
    svc, _ = _svc({"MetricDataResults": []})
    for bad in ('t_a" OR verdict="DENY', "t_a')", 't"', "with space", ""):
        with _pytest.raises(ValueError):
            svc._search_tenant("Decisions", "Sum", 3600, bad, "ALLOW")
    # a normal server-minted id is accepted
    expr = svc._search_tenant("Decisions", "Sum", 3600, "t_0abc123def456", "ALLOW")
    assert 'tenant_id="t_0abc123def456"' in expr


def test_decisions_timeseries_tenant_scoped_uses_decisions_stream():
    """WS-N D11: decisions_timeseries(tenant_id=...) queries the tenant-dimensioned
    Decisions{tenant_id,verdict} stream (customer per-tenant series), NOT fleet
    ValidationsTotal."""
    svc, cw = _svc({"MetricDataResults": [
        {"Id": "allowed", "Timestamps": [], "Values": []},
        {"Id": "blocked", "Timestamps": [], "Values": []},
    ]})
    svc.decisions_timeseries("24h", "1h", tenant_id="t_a")
    exprs = " ".join(q["Expression"] for q in cw.get_metric_data.call_args.kwargs["MetricDataQueries"])
    assert 'MetricName="Decisions"' in exprs
    assert 'tenant_id="t_a"' in exprs
    assert 'verdict="ALLOW"' in exprs and 'verdict="DENY"' in exprs
    assert "ValidationsTotal" not in exprs  # not the fleet stream


def test_decisions_timeseries_fleet_path_unchanged():
    """decisions_timeseries() with no tenant (platform) still uses fleet ValidationsTotal."""
    svc, cw = _svc({"MetricDataResults": [
        {"Id": "allowed", "Timestamps": [], "Values": []},
        {"Id": "blocked", "Timestamps": [], "Values": []},
    ]})
    svc.decisions_timeseries("24h", "1h")  # tenant_id defaults None
    exprs = " ".join(q["Expression"] for q in cw.get_metric_data.call_args.kwargs["MetricDataQueries"])
    assert 'MetricName="ValidationsTotal"' in exprs
    assert "tenant_id=" not in exprs


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


def test_sigma_match_counts_aggregates_per_rule():
    """sigma_match_counts() returns {rule_id: summed count} over the window."""
    cw = Mock()
    # ListMetrics enumerates the RuleId dimensions that have data.
    cw.list_metrics.return_value = {
        "Metrics": [
            {"Dimensions": [{"Name": "RuleId", "Value": "sigma-llm-001"}]},
            {"Dimensions": [{"Name": "RuleId", "Value": "sigma-llm-002"}]},
        ]
    }
    # GetMetricData returns one summed value per rule query id (r0, r1).
    cw.get_metric_data.return_value = {
        "MetricDataResults": [
            {"Id": "r0", "Values": [7.0]},
            {"Id": "r1", "Values": [3.0]},
        ]
    }
    svc = MetricsQueryService(cloudwatch_client=cw)
    counts = svc.sigma_match_counts("24h")

    assert counts == {"sigma-llm-001": 7, "sigma-llm-002": 3}
    # Window defaults sensibly and a single GetMetricData call is made.
    assert cw.get_metric_data.call_count == 1


def test_sigma_match_counts_no_series_returns_empty():
    """No emitted metrics yet -> empty map (caller defaults rules to 0)."""
    cw = Mock()
    cw.list_metrics.return_value = {"Metrics": []}
    svc = MetricsQueryService(cloudwatch_client=cw)

    assert svc.sigma_match_counts("7d") == {}
    # No rule series -> no GetMetricData call needed.
    cw.get_metric_data.assert_not_called()
