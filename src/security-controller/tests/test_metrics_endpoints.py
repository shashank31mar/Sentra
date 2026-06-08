"""Route-level tests for the WS-21 Phase 2 dashboard metrics endpoints (T20-T22).

Services are lazily imported inside the route functions, so we patch them at
their source modules.
"""
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_metrics_query():
    with patch('app.services.metrics_query_service.MetricsQueryService') as mock:
        svc = Mock()
        svc.overview = Mock(return_value={
            "range": "24h", "requests_total": 1000, "allowed": 900, "denied": 100,
            "threats_blocked": 100, "avg_latency_ms": 12, "trust_score": 87,
        })
        svc.attack_category_count = Mock(return_value=4)
        svc.decisions_timeseries = Mock(return_value={
            "range": "24h", "bucket": "1h",
            "series": [{"t": "2026-06-06T00:00:00Z", "allowed": 10, "blocked": 2}],
        })
        mock.return_value = svc
        yield svc


@pytest.fixture
def mock_agent_dist():
    with patch('app.services.agent_service.AgentService') as mock:
        svc = Mock()
        svc.get_cloud_provider_distribution = AsyncMock(return_value={
            "total_nodes": 5, "clouds": 2,
            "providers": [
                {"cloud_provider": "aws", "label": "AWS", "count": 3, "pct": 60},
                {"cloud_provider": "azure", "label": "Azure", "count": 2, "pct": 40},
            ],
        })
        mock.return_value = svc
        yield svc


@pytest.fixture
def mock_session_counts():
    with patch('app.utils.session_manager.SessionManager') as mock:
        svc = Mock()
        svc.count_sessions_by_status = AsyncMock(return_value=3)
        svc.count_agents_below_trust = AsyncMock(return_value=1)
        mock.return_value = svc
        yield svc


@pytest.fixture
def mock_metrics_publisher():
    """WS-21 T01: overview emits the CloudWatch session gauge as a side effect."""
    with patch('app.utils.metrics_publisher.MetricsPublisher') as mock:
        pub = Mock()
        pub.publish_session_metrics = AsyncMock()
        mock.return_value = pub
        yield pub


class TestMetricsOverview:
    def test_overview_merges_cloudwatch_and_ddb(
        self, client, mock_metrics_query, mock_agent_dist, mock_session_counts,
        mock_metrics_publisher,
    ):
        resp = client.get("/v1/metrics/overview?range=24h")
        assert resp.status_code == 200
        data = resp.json()
        assert data["requests_total"] == 1000
        assert data["threats_blocked"] == 100
        assert data["attack_categories"] == 4
        assert data["active_agents"] == 5      # from DDB distribution
        assert data["clouds"] == 2
        assert data["quarantined"] == 3        # from sessions
        assert data["agents_below_threshold"] == 1
        assert data["trust_score"] == 87
        assert data["trust_status"] == "healthy"   # 87 >= 80
        # P0: not shown
        assert data["false_positive_pct"] is None
        assert data["threats_blocked_delta_pct"] is None
        # WS-21 T01: session gauge emitted (quarantined=3, suspended=3)
        mock_metrics_publisher.publish_session_metrics.assert_awaited_once_with(3, 3)

    def test_overview_empty_fleet_trust_null_status_unknown(
        self, client, mock_metrics_query, mock_agent_dist, mock_session_counts,
        mock_metrics_publisher,
    ):
        """Kiro review: empty fleet → trust_score null, trust_status 'unknown'
        (contract marks these nullable; null ≠ a misleading 0)."""
        mock_metrics_query.overview.return_value = {
            "range": "24h", "requests_total": 0, "allowed": 0, "denied": 0,
            "threats_blocked": 0, "avg_latency_ms": 0, "trust_score": None,
        }
        data = client.get("/v1/metrics/overview").json()
        assert data["trust_score"] is None
        assert data["trust_status"] == "unknown"

    def test_overview_trust_status_bands(
        self, client, mock_metrics_query, mock_agent_dist, mock_session_counts,
        mock_metrics_publisher,
    ):
        mock_metrics_query.overview.return_value = {
            "range": "24h", "requests_total": 1, "allowed": 1, "denied": 0,
            "threats_blocked": 0, "avg_latency_ms": 5, "trust_score": 55,
        }
        data = client.get("/v1/metrics/overview").json()
        assert data["trust_status"] == "degraded"  # 50 <= 55 < 80

    def test_overview_rejects_bad_range(self, client):
        resp = client.get("/v1/metrics/overview?range=99y")
        assert resp.status_code == 400


class TestPlatformDistribution:
    def test_platform_distribution(self, client, mock_agent_dist):
        resp = client.get("/v1/metrics/platform-distribution")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_nodes"] == 5
        assert {p["cloud_provider"] for p in data["providers"]} == {"aws", "azure"}


class TestDecisionsTimeseries:
    def test_timeseries_ok(self, client, mock_metrics_query):
        resp = client.get("/v1/metrics/decisions-timeseries?range=24h&bucket=1h")
        assert resp.status_code == 200
        data = resp.json()
        assert data["bucket"] == "1h"
        assert data["series"][0]["allowed"] == 10

    def test_timeseries_value_error_maps_to_400(self, client, mock_metrics_query):
        mock_metrics_query.decisions_timeseries.side_effect = ValueError("too many points")
        resp = client.get("/v1/metrics/decisions-timeseries?range=30d&bucket=1h")
        assert resp.status_code == 400

    def test_timeseries_rejects_bad_range(self, client):
        resp = client.get("/v1/metrics/decisions-timeseries?range=bogus")
        assert resp.status_code == 400
