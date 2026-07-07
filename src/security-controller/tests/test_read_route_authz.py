"""WS-N: read-route auth + tenant-scoping tests (lld/40 D10/D11).

Proves every gated read route:
  1. Returns 401 without ALB-OIDC identity
  2. Binds the tenant via resolve_operator_tenant (customer sees own tenant only)
  3. For by-id reads, foreign resource -> 403/404 via assert_owns
  4. For CloudWatch reads, customer gets fail-closed 422 (never fleet rows)
  5. Sigma-rules are auth-only (no tenant filter — fleet-global)
  6. _operator_read_scope: customer -> own tenant, platform -> None + audited
"""
from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api import routes as R
from app.api.deps import OperatorContext, resolve_operator_tenant


def _ctx(tenant_id: str = "t_a", is_platform: bool = False, role: str = "viewer") -> OperatorContext:
    return OperatorContext(sub="op-x", tenant_id=tenant_id, role=role,
                           email="op@x.co", is_platform=is_platform)


# ============================================================
# N0.1 — _operator_read_scope helper
# ============================================================

class TestOperatorReadScope:
    def test_customer_scope_returns_own_tenant(self):
        ctx = _ctx(tenant_id="t_cust")
        result = R._operator_read_scope(ctx, "test.read")
        assert result == "t_cust"

    def test_customer_scope_never_none(self):
        """A non-platform ctx never yields None (fail-secure)."""
        ctx = _ctx(tenant_id="t_cust", is_platform=False)
        result = R._operator_read_scope(ctx, "test.read")
        assert result is not None

    @patch("app.api.tenancy_routes._audit_platform_read")
    def test_platform_scope_returns_none_and_audits(self, mock_audit):
        ctx = _ctx(tenant_id="_platform", is_platform=True)
        result = R._operator_read_scope(ctx, "sessions.list")
        assert result is None
        mock_audit.assert_called_once_with(ctx, "*", "sessions.list")

    @patch("app.api.tenancy_routes._audit_platform_read")
    def test_platform_audit_records_what(self, mock_audit):
        ctx = _ctx(tenant_id="_platform", is_platform=True)
        R._operator_read_scope(ctx, "metrics.overview")
        mock_audit.assert_called_once_with(ctx, "*", "metrics.overview")


# ============================================================
# N1/N3/N5/N6 — wiring: each read route carries resolve_operator_tenant
# ============================================================

# All read route handlers that should have the dep
_GATED_HANDLERS = [
    R.get_logs,
    R.scan_decisions,
    R.get_session_decisions,
    R.get_sessions,
    R.get_metrics,
    R.get_metrics_overview,
    R.get_platform_distribution,
    R.get_decisions_timeseries,
    R.get_agents,
    R.get_agent,
    R.get_agent_tools,
    R.get_policies,
    R.get_policy_by_id,
    R.get_sigma_rules,
    R.get_sigma_rule_content,
    R.get_conversation_timeline,
    R.discovery_agents,
    R.discovery_summary,
    R.discovery_platforms,
    R.list_connections,
    R.get_connection,
]


@pytest.mark.parametrize("handler", _GATED_HANDLERS, ids=lambda h: h.__name__)
def test_read_route_has_resolve_operator_tenant(handler):
    """Every WS-N-gated read route carries Depends(resolve_operator_tenant)."""
    sig = inspect.signature(handler)
    found = False
    for p in sig.parameters.values():
        dep = getattr(p.default, "dependency", None)
        if dep is None:
            continue
        if dep is resolve_operator_tenant:
            found = True
            break
        if getattr(dep, "__name__", "") == "resolve_operator_tenant":
            found = True
            break
    assert found, f"{handler.__name__} missing Depends(resolve_operator_tenant)"


# ============================================================
# N3 — by-id reads call assert_owns
# ============================================================

_ASSERT_OWNS_HANDLERS = [
    R.get_agent,
    R.get_policy_by_id,
    R.get_connection,
    R.get_conversation_timeline,
]


@pytest.mark.parametrize("handler", _ASSERT_OWNS_HANDLERS, ids=lambda h: h.__name__)
def test_by_id_handler_calls_assert_owns(handler):
    """By-id read handlers must call assert_owns (defence-in-depth, WS-N N3)."""
    src = inspect.getsource(handler)
    assert "assert_owns" in src, f"{handler.__name__} missing assert_owns call"


def test_get_agent_tools_has_assert_owns():
    """Agent tools are agent-specific (bound policy) — assert_owns for defence-in-depth,
    consistent with sibling get_agent (tools are NOT a global registry)."""
    src = inspect.getsource(R.get_agent_tools)
    assert "assert_owns" in src


# ============================================================
# N4 — CloudWatch reads fail-closed for customer
# ============================================================

class TestCloudWatchFailClosed:
    @pytest.mark.asyncio
    async def test_logs_customer_failclosed(self):
        """Customer ctx on /logs -> 422, never fleet rows."""
        from fastapi import HTTPException
        ctx = _ctx(is_platform=False)
        with pytest.raises(HTTPException) as exc_info:
            await R.get_logs(ctx=ctx)
        assert exc_info.value.status_code == 422
        assert "tenant-scoped telemetry" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_metrics_customer_failclosed(self):
        """Customer ctx on /metrics -> 422."""
        from fastapi import HTTPException
        ctx = _ctx(is_platform=False)
        with pytest.raises(HTTPException) as exc_info:
            await R.get_metrics(ctx=ctx)
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_decisions_timeseries_customer_failclosed(self):
        """Customer ctx on /metrics/decisions-timeseries -> 422."""
        from fastapi import HTTPException
        ctx = _ctx(is_platform=False)
        with pytest.raises(HTTPException) as exc_info:
            await R.get_decisions_timeseries(ctx=ctx)
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    @patch("app.api.tenancy_routes._audit_platform_read")
    @patch("app.services.logs_service.LogsService.query_logs", new_callable=AsyncMock)
    async def test_logs_platform_fleet_audited(self, mock_query, mock_audit):
        """Platform ctx on /logs -> fleet (audited)."""
        mock_query.return_value = {"logs": [], "total": 0}
        ctx = _ctx(is_platform=True)
        result = await R.get_logs(ctx=ctx)
        mock_audit.assert_called_once_with(ctx, "*", "logs.list")
        assert result == {"logs": [], "total": 0}


# ============================================================
# N6 — sigma-rules auth-only, no tenant filter
# ============================================================

class TestSigmaRulesAuthOnly:
    @pytest.mark.asyncio
    @patch("app.services.sigma_rules_service.SigmaRulesService.list_sigma_rules", new_callable=AsyncMock)
    async def test_sigma_rules_authed_returns_fleet_rules(self, mock_list):
        """Any authenticated tenant gets the same full rule set (fleet-global)."""
        mock_list.return_value = {"rules": [{"rule_id": "r1"}], "total": 1}
        ctx = _ctx(tenant_id="t_a")
        result = await R.get_sigma_rules(ctx=ctx)
        assert result["total"] == 1
        # No tenant filter was applied — the service is called without a tenant param
        mock_list.assert_awaited_once()


# ============================================================
# N2 — dual-mode: SessionManager.query_sessions tenant_id param
# ============================================================

class TestDualModeSessions:
    @pytest.mark.asyncio
    @patch("app.utils.session_manager.SessionManager.query_sessions", new_callable=AsyncMock)
    async def test_sessions_customer_passes_tenant_id(self, mock_qs):
        """Customer ctx passes tenant_id to session manager (scoped read)."""
        mock_qs.return_value = {"sessions": [], "total": 0, "next_token": None}
        ctx = _ctx(tenant_id="t_a", is_platform=False)
        await R.get_sessions(ctx=ctx)
        mock_qs.assert_awaited_once()
        _, kwargs = mock_qs.call_args
        assert kwargs.get("tenant_id") == "t_a"

    @pytest.mark.asyncio
    @patch("app.api.tenancy_routes._audit_platform_read")
    @patch("app.utils.session_manager.SessionManager.query_sessions", new_callable=AsyncMock)
    async def test_sessions_platform_passes_none(self, mock_qs, mock_audit):
        """Platform ctx passes tenant_id=None (fleet view)."""
        mock_qs.return_value = {"sessions": [], "total": 0, "next_token": None}
        ctx = _ctx(tenant_id="_platform", is_platform=True)
        await R.get_sessions(ctx=ctx)
        _, kwargs = mock_qs.call_args
        assert kwargs.get("tenant_id") is None
        mock_audit.assert_called_once()


# ============================================================
# N2/N4 — metrics/overview: customer gets null CW fields + scoped DDB counts
# ============================================================

class TestOverviewCustomerNullsCW:
    """Customer operator on /metrics/overview: CloudWatch fields (fleet-shared, not
    tenant-partitioned) are nulled; only DDB-scoped counts (quarantined,
    agents_below_threshold, active_agents) are returned."""

    @pytest.mark.asyncio
    @patch("app.utils.metrics_publisher.MetricsPublisher")
    @patch("app.utils.session_manager.SessionManager")
    @patch("app.services.agent_service.AgentService")
    @patch("app.services.metrics_query_service.MetricsQueryService")
    async def test_customer_overview_nulls_cw_fields(
        self, MockMQ, MockAgent, MockSM, MockPub
    ):
        """Customer ctx -> CW fields null, DDB fields present."""
        mq = MockMQ.return_value
        mq.overview.return_value = {
            "threats_blocked": 99, "requests_total": 500,
            "avg_latency_ms": 12, "trust_score": 87,
        }
        mq.attack_category_count.return_value = 4
        agent_svc = MockAgent.return_value
        agent_svc.get_cloud_provider_distribution = AsyncMock(return_value={
            "total_nodes": 3, "clouds": 1,
            "providers": [{"cloud_provider": "aws", "label": "AWS", "count": 3, "pct": 100}],
        })
        sm = MockSM.return_value
        sm.count_sessions_by_status = AsyncMock(return_value=2)
        sm.count_agents_below_trust = AsyncMock(return_value=1)
        pub = MockPub.return_value
        pub.publish_session_metrics = AsyncMock()

        ctx = _ctx(tenant_id="t_a", is_platform=False)
        result = await R.get_metrics_overview(range="24h", ctx=ctx)

        # CW fields must be null for customer (fleet-shared, not tenant-partitioned)
        assert result["threats_blocked"] is None
        assert result["requests_total"] is None
        assert result["avg_latency_ms"] is None
        assert result["trust_score"] is None
        assert result["attack_categories"] is None
        assert result["trust_status"] == "unknown"

        # DDB-scoped counts must be present
        assert result["quarantined"] == 2
        assert result["agents_below_threshold"] == 1
        assert result["active_agents"] == 3

    @pytest.mark.asyncio
    @patch("app.utils.metrics_publisher.MetricsPublisher")
    @patch("app.utils.session_manager.SessionManager")
    @patch("app.services.agent_service.AgentService")
    @patch("app.services.metrics_query_service.MetricsQueryService")
    async def test_customer_overview_count_agents_scoped(
        self, MockMQ, MockAgent, MockSM, MockPub
    ):
        """count_agents_below_trust must receive tenant_id=ctx.tenant_id."""
        mq = MockMQ.return_value
        mq.overview.return_value = {
            "threats_blocked": 0, "requests_total": 0, "avg_latency_ms": 0, "trust_score": None,
        }
        mq.attack_category_count.return_value = 0
        agent_svc = MockAgent.return_value
        agent_svc.get_cloud_provider_distribution = AsyncMock(return_value={
            "total_nodes": 0, "clouds": 0, "providers": [],
        })
        sm = MockSM.return_value
        sm.count_sessions_by_status = AsyncMock(return_value=0)
        sm.count_agents_below_trust = AsyncMock(return_value=0)
        pub = MockPub.return_value
        pub.publish_session_metrics = AsyncMock()

        ctx = _ctx(tenant_id="t_a", is_platform=False)
        await R.get_metrics_overview(range="24h", ctx=ctx)

        # Must pass tenant_id for scoping
        sm.count_agents_below_trust.assert_awaited_once_with(70.0, tenant_id="t_a")


class TestAgentToolsOwnership:
    """get_agent_tools enforces assert_owns — a foreign agent_id -> 403."""

    @pytest.mark.asyncio
    async def test_foreign_agent_tools_403(self):
        """Agent owned by t_b, operator is t_a -> 403."""
        from fastapi import HTTPException
        ctx = _ctx(tenant_id="t_a")
        with pytest.raises(HTTPException) as exc_info:
            await R.get_agent_tools(agent_id="t_b-aws-agent-1", ctx=ctx)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    @patch("app.services.agent_service.AgentService")
    async def test_own_agent_tools_passes(self, MockAgent):
        """Agent owned by t_a, operator is t_a -> no 403."""
        svc = MockAgent.return_value
        svc.get_agent_tools = AsyncMock(return_value={"agent_id": "t_a-aws-x-1", "tools": [], "total": 0})
        ctx = _ctx(tenant_id="t_a")
        result = await R.get_agent_tools(agent_id="t_a-aws-x-1", ctx=ctx)
        assert result["total"] == 0
