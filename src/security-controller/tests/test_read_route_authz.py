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
    @patch("app.services.metrics_query_service.MetricsQueryService")
    async def test_decisions_timeseries_customer_scoped_d11(self, MockMQ):
        """WS-N D11: /metrics/decisions-timeseries is now PER-TENANT for a customer (no
        longer 422) — the service is called with the customer's tenant scope so the
        series comes from the tenant-dimensioned Decisions stream, not fleet-wide."""
        MockMQ.return_value.decisions_timeseries = MagicMock(return_value={
            "range": "24h", "bucket": "1h", "series": [],
        })
        ctx = _ctx(tenant_id="t_a", is_platform=False)
        result = await R.get_decisions_timeseries(range="24h", bucket="1h", ctx=ctx)
        assert result["range"] == "24h"
        # called with the customer's tenant scope (positional: range, bucket, tenant_id)
        args = MockMQ.return_value.decisions_timeseries.call_args.args
        assert args[2] == "t_a", f"expected tenant scope t_a, got {args}"

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

class TestOverviewCustomerD11Scoped:
    """WS-N D11 (primary rescope): a customer operator on /metrics/overview now gets
    PER-TENANT CloudWatch counts/latency — overview() is called with the tenant scope
    and reads the tenant-dimensioned Decisions{tenant_id,verdict}+ValidateLatency{tenant_id}
    streams. Only trust_score + attack_categories stay null (no per-tenant CW stream —
    an honest gap). Replaces the former null-everything fallback."""

    @pytest.mark.asyncio
    @patch("app.utils.metrics_publisher.MetricsPublisher")
    @patch("app.utils.session_manager.SessionManager")
    @patch("app.services.agent_service.AgentService")
    @patch("app.services.metrics_query_service.MetricsQueryService")
    async def test_customer_overview_scoped_cw_fields(
        self, MockMQ, MockAgent, MockSM, MockPub
    ):
        """Customer ctx -> per-tenant CW counts present; trust/attack null; overview
        called with tenant_id=ctx.tenant_id (the D11 scope)."""
        mq = MockMQ.return_value
        # overview() now returns the PER-TENANT numbers (handler passes scope=tenant_id).
        mq.overview.return_value = {
            "threats_blocked": 99, "requests_total": 500,
            "avg_latency_ms": 12, "trust_score": None,  # no per-tenant trust stream
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

        # D11: overview() was scoped to the customer's tenant (not fleet None).
        mq.overview.assert_called_once_with("24h", "t_a")

        # Per-tenant CW counts/latency are now REAL (no longer nulled).
        assert result["threats_blocked"] == 99
        assert result["requests_total"] == 500
        assert result["avg_latency_ms"] == 12
        # trust_score + attack_categories stay null (no per-tenant CW stream — honest gap).
        assert result["trust_score"] is None
        assert result["attack_categories"] is None
        assert result["trust_status"] == "unknown"

        # DDB-scoped counts still present.
        assert result["quarantined"] == 2
        assert result["agents_below_threshold"] == 1
        assert result["active_agents"] == 3

    @pytest.mark.asyncio
    @patch("app.api.tenancy_routes._audit_platform_read")
    @patch("app.utils.metrics_publisher.MetricsPublisher")
    @patch("app.utils.session_manager.SessionManager")
    @patch("app.services.agent_service.AgentService")
    @patch("app.services.metrics_query_service.MetricsQueryService")
    async def test_platform_overview_fleet_scope(
        self, MockMQ, MockAgent, MockSM, MockPub, MockAudit
    ):
        """Platform ctx -> overview() called with tenant_id=None (fleet) + full CW fields."""
        mq = MockMQ.return_value
        mq.overview.return_value = {
            "threats_blocked": 42, "requests_total": 1000, "avg_latency_ms": 15, "trust_score": 88,
        }
        mq.attack_category_count.return_value = 7
        MockAgent.return_value.get_cloud_provider_distribution = AsyncMock(return_value={
            "total_nodes": 9, "clouds": 2, "providers": [],
        })
        sm = MockSM.return_value
        sm.count_sessions_by_status = AsyncMock(return_value=0)
        sm.count_agents_below_trust = AsyncMock(return_value=0)
        MockPub.return_value.publish_session_metrics = AsyncMock()

        ctx = _ctx(tenant_id="_platform", is_platform=True)
        result = await R.get_metrics_overview(range="24h", ctx=ctx)

        mq.overview.assert_called_once_with("24h", None)  # fleet scope
        assert result["threats_blocked"] == 42
        assert result["trust_score"] == 88  # fleet trust IS surfaced for platform

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


# ============================================================
# N3 FIX-B — behavioral cross-tenant rejection tests for policy, connection,
# conversation (the assert_owns DDB/CW-backed ownership checks)
# ============================================================

class TestPolicyOwnershipBehavioral:
    """get_policy_by_id: foreign policy_id -> 404 (existence-masked, WS-N N3)."""

    @pytest.mark.asyncio
    @patch("app.api.ownership.tenancy.v2_enabled", return_value=True)
    @patch("boto3.resource")
    async def test_foreign_policy_404(self, mock_resource, _v2):
        """A policy_id absent from the operator's tenant partition -> 404."""
        from fastapi import HTTPException
        # DDB returns no Item for the tenant-scoped key (foreign resource)
        mock_table = MagicMock()
        mock_table.get_item.return_value = {}
        mock_ddb = MagicMock()
        mock_ddb.Table.return_value = mock_table
        mock_resource.return_value = mock_ddb

        ctx = _ctx(tenant_id="t_a")
        with pytest.raises(HTTPException) as exc_info:
            await R.get_policy_by_id(policy_id="pol-foreign-xyz", ctx=ctx)
        assert exc_info.value.status_code == 404
        assert "policy not found" in exc_info.value.detail

    @pytest.mark.asyncio
    @patch("app.api.ownership.tenancy.v2_enabled", return_value=True)
    @patch("boto3.resource")
    @patch("app.services.policy_service.PolicyService")
    async def test_own_policy_passes(self, MockPolicy, mock_resource, _v2):
        """A policy_id present in the operator's partition -> passes assert_owns."""
        # DDB returns the item with matching tenant
        mock_table = MagicMock()
        mock_table.get_item.return_value = {"Item": {"policy_id": "pol-x", "tenant_id": "t_a"}}
        mock_ddb = MagicMock()
        mock_ddb.Table.return_value = mock_table
        mock_resource.return_value = mock_ddb

        svc = MockPolicy.return_value
        svc.get_policy = AsyncMock(return_value={"policy_id": "pol-x", "name": "test"})
        svc.get_policy_content = AsyncMock(return_value="rules: []")

        ctx = _ctx(tenant_id="t_a")
        result = await R.get_policy_by_id(policy_id="pol-x", ctx=ctx)
        assert result["success"] is True


class TestConnectionOwnershipBehavioral:
    """get_connection: foreign connection_id -> 404 (existence-masked, WS-N N3)."""

    @pytest.mark.asyncio
    @patch("boto3.resource")
    async def test_foreign_connection_404(self, mock_resource):
        """A connection_id absent from the operator's tenant row -> 404."""
        from fastapi import HTTPException
        # DDB returns no Item for the (tenant_id, id) key
        mock_table = MagicMock()
        mock_table.get_item.return_value = {}
        mock_ddb = MagicMock()
        mock_ddb.Table.return_value = mock_table
        mock_resource.return_value = mock_ddb

        ctx = _ctx(tenant_id="t_a")
        with pytest.raises(HTTPException) as exc_info:
            await R.get_connection(connection_id="conn-foreign-abc", ctx=ctx)
        assert exc_info.value.status_code == 404
        assert "connection not found" in exc_info.value.detail

    @pytest.mark.asyncio
    @patch("boto3.resource")
    @patch("app.services.connections_service.ConnectionsService")
    async def test_own_connection_passes(self, MockConn, mock_resource):
        """A connection_id present under the operator's tenant -> passes."""
        # DDB returns the item (tenant_id + id match)
        mock_table = MagicMock()
        mock_table.get_item.return_value = {"Item": {"tenant_id": "t_a", "id": "conn-x"}}
        mock_ddb = MagicMock()
        mock_ddb.Table.return_value = mock_table
        mock_resource.return_value = mock_ddb

        svc = MockConn.return_value
        svc.get_connection.return_value = {"id": "conn-x", "status": "active"}

        ctx = _ctx(tenant_id="t_a")
        result = await R.get_connection(connection_id="conn-x", ctx=ctx)
        assert result["id"] == "conn-x"


class TestConversationOwnershipBehavioral:
    """get_conversation_timeline: foreign conversation_id -> 404 (WS-N N3).

    NOTE: conversation ownership goes through CloudWatch Logs Insights (not DDB),
    so we mock at the ownership dispatch level to simulate the cross-tenant path
    while still exercising the full handler -> assert_owns -> raise chain.
    """

    @pytest.mark.asyncio
    @patch("app.api.ownership.tenancy.v2_enabled", return_value=True)
    @patch("app.utils.rollback_coordinator._tenant_of_conversation", return_value=None)
    async def test_foreign_conversation_404(self, _mock_tenant, _v2):
        """A conversation_id not owned by the operator -> 404."""
        from fastapi import HTTPException

        ctx = _ctx(tenant_id="t_a")
        with pytest.raises(HTTPException) as exc_info:
            await R.get_conversation_timeline(conversation_id="conv-foreign-999", ctx=ctx)
        assert exc_info.value.status_code == 404
        assert "conversation not found" in exc_info.value.detail

    @pytest.mark.asyncio
    @patch("app.api.ownership.tenancy.v2_enabled", return_value=True)
    @patch("app.utils.rollback_coordinator._tenant_of_conversation", return_value="t_a")
    @patch("app.services.conversation_service.ConversationService")
    async def test_own_conversation_passes(self, MockConv, _mock_tenant, _v2):
        """A conversation owned by the operator's tenant -> passes."""
        svc = MockConv.return_value
        svc.get_timeline = AsyncMock(return_value={
            "conversation_id": "conv-own-1", "timeline": [], "agents": [],
        })

        ctx = _ctx(tenant_id="t_a")
        result = await R.get_conversation_timeline(conversation_id="conv-own-1", ctx=ctx)
        assert result["conversation_id"] == "conv-own-1"


# ============================================================
# FIX-B — publish_session_metrics only fires for platform operators
# ============================================================

class TestOverviewMetricsPublishGuard:
    """Customer overview must NOT publish to the fleet-wide CW gauge (FIX-B)."""

    @pytest.mark.asyncio
    @patch("app.utils.metrics_publisher.MetricsPublisher")
    @patch("app.utils.session_manager.SessionManager")
    @patch("app.services.agent_service.AgentService")
    @patch("app.services.metrics_query_service.MetricsQueryService")
    async def test_customer_overview_does_not_publish_cw(
        self, MockMQ, MockAgent, MockSM, MockPub
    ):
        """Customer operator must NEVER call publish_session_metrics (fleet gauge)."""
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

        # The fleet-wide CW gauge must NOT be published by a customer operator
        pub.publish_session_metrics.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("app.api.tenancy_routes._audit_platform_read")
    @patch("app.utils.metrics_publisher.MetricsPublisher")
    @patch("app.utils.session_manager.SessionManager")
    @patch("app.services.agent_service.AgentService")
    @patch("app.services.metrics_query_service.MetricsQueryService")
    async def test_platform_overview_publishes_cw(
        self, MockMQ, MockAgent, MockSM, MockPub, _audit
    ):
        """Platform operator DOES publish fleet-wide CW gauge."""
        mq = MockMQ.return_value
        mq.overview.return_value = {
            "threats_blocked": 5, "requests_total": 100, "avg_latency_ms": 10, "trust_score": 80,
        }
        mq.attack_category_count.return_value = 2
        agent_svc = MockAgent.return_value
        agent_svc.get_cloud_provider_distribution = AsyncMock(return_value={
            "total_nodes": 4, "clouds": 2, "providers": [],
        })
        sm = MockSM.return_value
        sm.count_sessions_by_status = AsyncMock(return_value=3)
        sm.count_agents_below_trust = AsyncMock(return_value=1)
        pub = MockPub.return_value
        pub.publish_session_metrics = AsyncMock()

        ctx = _ctx(tenant_id="_platform", is_platform=True)
        await R.get_metrics_overview(range="24h", ctx=ctx)

        # Platform DOES publish the fleet gauge
        pub.publish_session_metrics.assert_awaited_once_with(3, 3)


# ============================================================
# FIX-B GAP-1 — overview: platform operator gets fleet distribution
# ============================================================

class TestOverviewPlatformFleetDistribution:
    """Platform operator on /metrics/overview must get fleet-wide distribution
    (active_agents/clouds), not just their bound tenant's agents (GAP-1)."""

    @pytest.mark.asyncio
    @patch("app.api.tenancy_routes._audit_platform_read")
    @patch("app.utils.metrics_publisher.MetricsPublisher")
    @patch("app.utils.session_manager.SessionManager")
    @patch("app.services.agent_service.AgentService")
    @patch("app.services.metrics_query_service.MetricsQueryService")
    async def test_platform_overview_distribution_uses_fleet(
        self, MockMQ, MockAgent, MockSM, MockPub, _audit
    ):
        """Platform ctx -> get_cloud_provider_distribution called with fleet=True."""
        mq = MockMQ.return_value
        mq.overview.return_value = {
            "threats_blocked": 5, "requests_total": 100, "avg_latency_ms": 10, "trust_score": 80,
        }
        mq.attack_category_count.return_value = 2
        agent_svc = MockAgent.return_value
        agent_svc.get_cloud_provider_distribution = AsyncMock(return_value={
            "total_nodes": 10, "clouds": 3, "providers": [],
        })
        sm = MockSM.return_value
        sm.count_sessions_by_status = AsyncMock(return_value=3)
        sm.count_agents_below_trust = AsyncMock(return_value=1)
        pub = MockPub.return_value
        pub.publish_session_metrics = AsyncMock()

        ctx = _ctx(tenant_id="_platform", is_platform=True)
        result = await R.get_metrics_overview(range="24h", ctx=ctx)

        # The distribution must be fleet-wide (fleet=True passed)
        agent_svc.get_cloud_provider_distribution.assert_awaited_once_with(fleet=True)
        assert result["active_agents"] == 10
        assert result["clouds"] == 3

    @pytest.mark.asyncio
    @patch("app.utils.metrics_publisher.MetricsPublisher")
    @patch("app.utils.session_manager.SessionManager")
    @patch("app.services.agent_service.AgentService")
    @patch("app.services.metrics_query_service.MetricsQueryService")
    async def test_customer_overview_distribution_not_fleet(
        self, MockMQ, MockAgent, MockSM, MockPub
    ):
        """Customer ctx -> get_cloud_provider_distribution called with fleet=False."""
        mq = MockMQ.return_value
        mq.overview.return_value = {
            "threats_blocked": 0, "requests_total": 0, "avg_latency_ms": 0, "trust_score": None,
        }
        mq.attack_category_count.return_value = 0
        agent_svc = MockAgent.return_value
        agent_svc.get_cloud_provider_distribution = AsyncMock(return_value={
            "total_nodes": 2, "clouds": 1, "providers": [],
        })
        sm = MockSM.return_value
        sm.count_sessions_by_status = AsyncMock(return_value=0)
        sm.count_agents_below_trust = AsyncMock(return_value=0)
        pub = MockPub.return_value
        pub.publish_session_metrics = AsyncMock()

        ctx = _ctx(tenant_id="t_a", is_platform=False)
        result = await R.get_metrics_overview(range="24h", ctx=ctx)

        # Customer must NOT get fleet view
        agent_svc.get_cloud_provider_distribution.assert_awaited_once_with(fleet=False)
        assert result["active_agents"] == 2


# ============================================================
# WS-N D11 — decisions-timeseries is now per-tenant (was FIX-B GAP-2 fail-closed 422)
# ============================================================

class TestDecisionsTimeseriesD11Scoped:
    """WS-N D11 superseded FIX-B GAP-2: /metrics/decisions-timeseries is now a per-tenant
    read (customer gets their own series from the Decisions{tenant_id,verdict} stream),
    so a customer is an AUTHORIZED caller. A bad range therefore returns the normal 400
    validation error for BOTH customer and platform — the 422 fail-closed (and its
    param-leak concern for an *unauthorized* caller) no longer applies, since the caller
    is now authorized to read this route."""

    @pytest.mark.asyncio
    @patch("app.services.metrics_query_service.MetricsQueryService")
    async def test_customer_invalid_range_gets_400(self, MockMQ):
        """Customer with bad range -> 400 (they're an authorized caller now; the old
        422 info-leak concern is moot)."""
        from fastapi import HTTPException
        ctx = _ctx(tenant_id="t_a", is_platform=False)
        with pytest.raises(HTTPException) as exc_info:
            await R.get_decisions_timeseries(range="999d", bucket="1h", ctx=ctx)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    @patch("app.api.tenancy_routes._audit_platform_read")
    async def test_platform_invalid_range_gets_400(self, _audit):
        """Platform with bad range -> 400 (legitimate validation error)."""
        from fastapi import HTTPException
        ctx = _ctx(is_platform=True)
        with pytest.raises(HTTPException) as exc_info:
            await R.get_decisions_timeseries(range="999d", bucket="1h", ctx=ctx)
        assert exc_info.value.status_code == 400


# ============================================================
# FIX-B GAP-3 — platform-distribution: fleet view for platform operators
# ============================================================

class TestPlatformDistributionFleetView:
    """Platform operator on /metrics/platform-distribution must get fleet-wide
    distribution, not just their bound tenant (GAP-3)."""

    @pytest.mark.asyncio
    @patch("app.api.tenancy_routes._audit_platform_read")
    @patch("app.services.agent_service.AgentService")
    async def test_platform_distribution_uses_fleet(self, MockAgent, mock_audit):
        """Platform ctx -> get_cloud_provider_distribution(fleet=True) + audited."""
        agent_svc = MockAgent.return_value
        agent_svc.get_cloud_provider_distribution = AsyncMock(return_value={
            "total_nodes": 8, "clouds": 2,
            "providers": [{"cloud_provider": "aws", "label": "AWS", "count": 5, "pct": 62},
                          {"cloud_provider": "azure", "label": "Azure", "count": 3, "pct": 38}],
        })

        ctx = _ctx(tenant_id="_platform", is_platform=True)
        result = await R.get_platform_distribution(ctx=ctx)

        agent_svc.get_cloud_provider_distribution.assert_awaited_once_with(fleet=True)
        mock_audit.assert_called_once_with(ctx, "*", "metrics.platform_distribution")
        assert result["total_nodes"] == 8

    @pytest.mark.asyncio
    @patch("app.services.agent_service.AgentService")
    async def test_customer_distribution_not_fleet(self, MockAgent):
        """Customer ctx -> get_cloud_provider_distribution(fleet=False), no audit."""
        agent_svc = MockAgent.return_value
        agent_svc.get_cloud_provider_distribution = AsyncMock(return_value={
            "total_nodes": 2, "clouds": 1,
            "providers": [{"cloud_provider": "aws", "label": "AWS", "count": 2, "pct": 100}],
        })

        ctx = _ctx(tenant_id="t_a", is_platform=False)
        result = await R.get_platform_distribution(ctx=ctx)

        agent_svc.get_cloud_provider_distribution.assert_awaited_once_with(fleet=False)
        assert result["total_nodes"] == 2


# ============================================================
# FIX-B GAP-4 — platform operator by-id routes with break-glass header
# ============================================================

class TestPlatformBreakGlassByIdRoutes:
    """Platform operator using X-Aegion-Tenant break-glass header to read
    resources in another tenant's partition must succeed (GAP-4).

    The break-glass mechanism (deps.py:418) synthesizes a viewer Membership for
    the requested tenant, so ctx.tenant_id = the target tenant. assert_owns then
    checks the resource against that bound tenant — should pass for resources
    owned by the target tenant.
    """

    @pytest.mark.asyncio
    @patch("app.services.agent_service.AgentService")
    async def test_platform_breakglass_get_agent_succeeds(self, MockAgent):
        """Platform operator with break-glass tenant t_b can read t_b's agent."""
        svc = MockAgent.return_value
        svc.get_agent = AsyncMock(return_value={"agent_id": "t_b-aws-x-1", "name": "X"})

        # Break-glass: ctx.tenant_id = t_b (the target tenant), is_platform=True
        ctx = _ctx(tenant_id="t_b", is_platform=True)
        result = await R.get_agent(agent_id="t_b-aws-x-1", ctx=ctx)
        assert result["agent_id"] == "t_b-aws-x-1"

    @pytest.mark.asyncio
    @patch("app.api.ownership.tenancy.v2_enabled", return_value=True)
    @patch("boto3.resource")
    @patch("app.services.policy_service.PolicyService")
    async def test_platform_breakglass_get_policy_succeeds(self, MockPolicy, mock_resource, _v2):
        """Platform operator with break-glass tenant t_b can read t_b's policy."""
        mock_table = MagicMock()
        mock_table.get_item.return_value = {"Item": {"policy_id": "pol-b", "tenant_id": "t_b"}}
        mock_ddb = MagicMock()
        mock_ddb.Table.return_value = mock_table
        mock_resource.return_value = mock_ddb

        svc = MockPolicy.return_value
        svc.get_policy = AsyncMock(return_value={"policy_id": "pol-b", "name": "Test B"})
        svc.get_policy_content = AsyncMock(return_value="rules: []")

        ctx = _ctx(tenant_id="t_b", is_platform=True)
        result = await R.get_policy_by_id(policy_id="pol-b", ctx=ctx)
        assert result["success"] is True

    @pytest.mark.asyncio
    @patch("boto3.resource")
    @patch("app.services.connections_service.ConnectionsService")
    async def test_platform_breakglass_get_connection_succeeds(self, MockConn, mock_resource):
        """Platform operator with break-glass tenant t_b can read t_b's connection."""
        mock_table = MagicMock()
        mock_table.get_item.return_value = {"Item": {"tenant_id": "t_b", "id": "conn-b"}}
        mock_ddb = MagicMock()
        mock_ddb.Table.return_value = mock_table
        mock_resource.return_value = mock_ddb

        svc = MockConn.return_value
        svc.get_connection.return_value = {"id": "conn-b", "status": "active"}

        ctx = _ctx(tenant_id="t_b", is_platform=True)
        result = await R.get_connection(connection_id="conn-b", ctx=ctx)
        assert result["id"] == "conn-b"

    @pytest.mark.asyncio
    @patch("app.api.ownership.tenancy.v2_enabled", return_value=True)
    @patch("app.utils.rollback_coordinator._tenant_of_conversation", return_value="t_b")
    @patch("app.services.conversation_service.ConversationService")
    async def test_platform_breakglass_get_conversation_succeeds(self, MockConv, _mock_tenant, _v2):
        """Platform operator with break-glass tenant t_b can read t_b's conversation."""
        svc = MockConv.return_value
        svc.get_timeline = AsyncMock(return_value={
            "conversation_id": "conv-b-1", "timeline": [], "agents": [],
        })

        ctx = _ctx(tenant_id="t_b", is_platform=True)
        result = await R.get_conversation_timeline(conversation_id="conv-b-1", ctx=ctx)
        assert result["conversation_id"] == "conv-b-1"


# ============================================================
# FIX-B GAP-5 — get_agents list: platform operator bind-only behavior
# ============================================================

class TestGetAgentsBindOnly:
    """GET /agents for a platform operator is bind-only (scoped to their bound
    tenant via query_or_scan, NOT fleet). This is by design (task doc N2.3).
    The test verifies the platform operator does NOT get fleet=True (no fleet_scan)
    — it gets the same tenant-scoped view as a customer (GAP-5)."""

    @pytest.mark.asyncio
    @patch("app.services.agent_service.AgentService")
    async def test_platform_get_agents_not_fleet(self, MockAgent):
        """Platform operator on GET /agents gets bind-only (NOT fleet scan)."""
        svc = MockAgent.return_value
        svc.list_agents = AsyncMock(return_value={"agents": [], "total": 0})

        ctx = _ctx(tenant_id="t_b", is_platform=True)
        result = await R.get_agents(enrich=False, managed_only=False, ctx=ctx)

        # list_agents is called WITHOUT fleet=True (bind-only by design)
        svc.list_agents.assert_awaited_once_with(enrich=False, managed_only=False)
        assert result["total"] == 0

    @pytest.mark.asyncio
    @patch("app.services.agent_service.AgentService")
    async def test_customer_get_agents_scoped(self, MockAgent):
        """Customer operator on GET /agents gets scoped view (bind-only)."""
        svc = MockAgent.return_value
        svc.list_agents = AsyncMock(return_value={"agents": [{"agent_id": "t_a-x"}], "total": 1})

        ctx = _ctx(tenant_id="t_a", is_platform=False)
        result = await R.get_agents(enrich=True, managed_only=False, ctx=ctx)

        svc.list_agents.assert_awaited_once_with(enrich=True, managed_only=False)
        assert result["total"] == 1


# ============================================================
# N-SENTINEL — BEHAVIORAL cross-tenant isolation proofs (integration-sentinel
# coverage gaps). These stand up a REAL moto-backed two-tenant store, bind one
# tenant the way resolve_operator_tenant does (set_current_tenant, deps.py:435),
# run the real route handler, and assert the OTHER tenant's rows never appear.
#
# Why these exist: the sibling tests above mock the service layer, so they prove
# wiring (the dep is present, fleet flags are right) but NOT that current_tenant()
# actually scopes the DDB read. A mock returning canned rows proves nothing about
# isolation. These exercise the real query_or_scan / composite-PK path end-to-end.
#
# TWO of them (list_agents, query_policies) are ALSO regression guards for the
# cross-tenant CACHE-KEY leaks fixed in this change: those services cache on the
# PROCESS-GLOBAL get_cache_manager() singleton under a key that omitted the tenant
# (agent_service.py:159, policy_service.py:101). With the cache ON and a shared
# singleton, tenant B's list-read hit tenant A's cached rows. The fix prefixes
# both keys with tenancy.current_tenant() (mirroring policy_engine.py's
# `policy_bundle:{current_tenant()}:`). These two tests FAIL against the pre-fix
# tenant-less key and PASS after — that is what makes them non-vacuous guards.
# ============================================================

import asyncio  # noqa: E402
import boto3  # noqa: E402
from moto import mock_aws  # noqa: E402

from app.config import settings as _settings  # noqa: E402
from app.utils import tenancy  # noqa: E402
from tests.mt_helpers import create_mt_tables  # noqa: E402


def _run(coro):
    """Run a coroutine on a fresh loop. set_current_tenant is set in THIS context
    before the call, and asyncio captures the current context when it wraps the
    coro in a Task — so the bound tenant propagates into the handler (and across
    its asyncio.to_thread hops, per test_multitenancy_isolation B7)."""
    return asyncio.new_event_loop().run_until_complete(coro)


def _as_tenant(tenant_id, coro_factory):
    """Bind current_tenant the way resolve_operator_tenant does, run the handler,
    then reset. The direct-handler harness MUST reproduce the dep's bind or the
    service reads the ambient 'default' partition and the test proves nothing."""
    token = tenancy.set_current_tenant(tenant_id)
    try:
        return _run(coro_factory())
    finally:
        tenancy.reset_current_tenant(token)


def _create_registry_v2(ddb):
    ddb.create_table(
        TableName=_settings.dynamodb_agent_registry_table_v2,
        KeySchema=[{"AttributeName": "tenant_id", "KeyType": "HASH"},
                   {"AttributeName": "agent_id", "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": "tenant_id", "AttributeType": "S"},
                              {"AttributeName": "agent_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )


def _create_policies_v2(ddb):
    ddb.create_table(
        TableName=_settings.dynamodb_policies_metadata_table_v2,
        KeySchema=[{"AttributeName": "tenant_id", "KeyType": "HASH"},
                   {"AttributeName": "policy_id", "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": "tenant_id", "AttributeType": "S"},
                              {"AttributeName": "policy_id", "AttributeType": "S"},
                              {"AttributeName": "tenant_agent_id", "AttributeType": "S"},
                              {"AttributeName": "status", "AttributeType": "S"}],
        GlobalSecondaryIndexes=[
            {"IndexName": "agent-index",
             "KeySchema": [{"AttributeName": "tenant_agent_id", "KeyType": "HASH"}],
             "Projection": {"ProjectionType": "ALL"}},
            {"IndexName": "status-index",
             "KeySchema": [{"AttributeName": "tenant_id", "KeyType": "HASH"},
                           {"AttributeName": "status", "KeyType": "RANGE"}],
             "Projection": {"ProjectionType": "ALL"}}],
        BillingMode="PAY_PER_REQUEST",
    )


def _create_signals_v2(ddb):
    """validation-signals v2: composite PK tenant_session_id (get_session_decisions
    Query) + the agent-timestamp-index GSI keyed on the composite tenant_agent_id
    (discovery's _last_active / agent_activity)."""
    ddb.create_table(
        TableName=_settings.dynamodb_validation_signals_table_v2,
        KeySchema=[{"AttributeName": "tenant_session_id", "KeyType": "HASH"},
                   {"AttributeName": "sk", "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": "tenant_session_id", "AttributeType": "S"},
                              {"AttributeName": "sk", "AttributeType": "S"},
                              {"AttributeName": "tenant_agent_id", "AttributeType": "S"},
                              {"AttributeName": "timestamp_ms", "AttributeType": "N"}],
        GlobalSecondaryIndexes=[{
            "IndexName": "agent-timestamp-index",
            "KeySchema": [{"AttributeName": "tenant_agent_id", "KeyType": "HASH"},
                          {"AttributeName": "timestamp_ms", "KeyType": "RANGE"}],
            "Projection": {"ProjectionType": "ALL"}}],
        BillingMode="PAY_PER_REQUEST",
    )


def _create_discovery_cache(ddb):
    ddb.create_table(
        TableName=_settings.dynamodb_discovery_cache_table,
        KeySchema=[{"AttributeName": "tenant_id", "KeyType": "HASH"},
                   {"AttributeName": "native_resource_id", "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": "tenant_id", "AttributeType": "S"},
                              {"AttributeName": "native_resource_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )


@pytest.fixture
def mt_store(monkeypatch):
    """A real moto-backed v2 store with the four tables these routes read, plus a
    RESET of the process-global service/cache singletons so a prior test's state
    can't mask a leak. cache_enabled=True is DELIBERATE: the cache-key regression
    guards only manifest a leak with the shared singleton enabled."""
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SECURITY_TOKEN", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(k, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", _settings.aws_region)
    monkeypatch.setattr(_settings, "tenancy_v2_enabled", True)
    monkeypatch.setattr(_settings, "cache_enabled", True)
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name=_settings.aws_region)
        create_mt_tables(ddb)
        _create_registry_v2(ddb)
        _create_policies_v2(ddb)
        _create_signals_v2(ddb)
        _create_discovery_cache(ddb)

        # Reset every process-global that latches a client/flag/cache at __init__,
        # so this test's moto tables + fresh cache are what the services see.
        import app.utils.cache_manager as cm
        import app.api.routes as routes_mod
        cm._cache_instance = None
        if hasattr(routes_mod, "_decisions_service_instance"):
            del routes_mod._decisions_service_instance
        yield ddb
        cm._cache_instance = None


# ------------------------------------------------------------ GAP 1: discovery/agents
class TestDiscoveryAgentsTenantIsolation:
    """GET /discovery/agents (routes.py:951): a customer operator sees ONLY their
    own tenant's discovered agents. DiscoveryService routes BOTH sources through
    the tenant partition — registry/policies via query_or_scan(current_tenant())
    and the scan cache via an explicit Key('tenant_id').eq(current_tenant()) Query
    — so this is genuine behavioral isolation, not a mock."""

    def test_customer_sees_only_own_discovered_agents(self, mt_store):
        reg = mt_store.Table(_settings.dynamodb_agent_registry_table_v2)
        reg.put_item(Item={"tenant_id": "t_a", "agent_id": "t_a-aws-x-1", "name": "A-reg",
                           "cloud_provider": "aws", "visibility": "external",
                           "native_resource_id": "arn-a"})
        reg.put_item(Item={"tenant_id": "t_b", "agent_id": "t_b-aws-y-2", "name": "B-reg",
                           "cloud_provider": "aws", "visibility": "external",
                           "native_resource_id": "arn-b"})
        cache = mt_store.Table(_settings.dynamodb_discovery_cache_table)
        cache.put_item(Item={"tenant_id": "t_a", "native_resource_id": "scan-a", "name": "A-scan",
                             "cloud_provider": "aws"})
        cache.put_item(Item={"tenant_id": "t_b", "native_resource_id": "scan-b", "name": "B-scan",
                             "cloud_provider": "aws"})

        ctx = _ctx(tenant_id="t_a", is_platform=False)
        out = _as_tenant("t_a", lambda: R.discovery_agents(ctx=ctx))

        names = {r["name"] for r in out["agents"]}
        assert names == {"A-reg", "A-scan"}, names
        # Tenant B's registry AND scanned rows are invisible.
        assert not any(n.startswith("B") for n in names)


# ------------------------------------------------------------ GAP 3: discovery summary/platforms
class TestDiscoverySummaryPlatformsTenantIsolation:
    """GET /discovery/summary + /discovery/platforms (routes.py:979, 991): bind-only.
    A customer sees ONLY their own tenant's discovery aggregate; a _platform
    operator sees ONLY their bound (reserved) partition — which is empty. Both are
    scoped via _build_rows -> query_or_scan(current_tenant())."""

    def test_customer_summary_and_platforms_own_tenant_only(self, mt_store):
        reg = mt_store.Table(_settings.dynamodb_agent_registry_table_v2)
        reg.put_item(Item={"tenant_id": "t_a", "agent_id": "t_a-aws-x-1", "name": "A",
                           "cloud_provider": "aws", "visibility": "external",
                           "native_resource_id": "arn-a"})
        reg.put_item(Item={"tenant_id": "t_b", "agent_id": "t_b-azure-y-2", "name": "B",
                           "cloud_provider": "azure", "visibility": "external",
                           "native_resource_id": "arn-b"})

        ctx = _ctx(tenant_id="t_a", is_platform=False)
        summary = _as_tenant("t_a", lambda: R.discovery_summary(ctx=ctx))
        platforms = _as_tenant("t_a", lambda: R.discovery_platforms(ctx=ctx))

        # Only tenant A's single aws agent — tenant B's azure agent never counted.
        assert summary["detected"] == 1
        provider_map = {p["cloud_provider"]: p["agents"] for p in platforms["providers"]}
        assert provider_map == {"aws": 1}, provider_map
        assert "azure" not in provider_map  # B's cloud does not leak in

    def test_platform_operator_sees_only_bound_partition(self, mt_store):
        """A _platform operator is bound to the reserved _platform partition (no
        fleet_scan here — bind-only, task doc FG). It holds no discovered agents,
        so summary is empty — it does NOT see customers' agents by default."""
        reg = mt_store.Table(_settings.dynamodb_agent_registry_table_v2)
        reg.put_item(Item={"tenant_id": "t_a", "agent_id": "t_a-aws-x-1", "name": "A",
                           "cloud_provider": "aws", "visibility": "external",
                           "native_resource_id": "arn-a"})

        ctx = _ctx(tenant_id=tenancy.PLATFORM_TENANT, is_platform=True)
        summary = _as_tenant(tenancy.PLATFORM_TENANT,
                             lambda: R.discovery_summary(ctx=ctx))

        assert summary["detected"] == 0  # bound partition is empty; no customer leak


# ------------------------------------------------------------ GAP 4: session decisions
class TestSessionDecisionsTenantIsolation:
    """GET /sessions/{id}/decisions (routes.py:482): tenant isolation is STRUCTURAL
    — the signal PK is the composite tenant_session_id ({tenant}#{session_id}), so
    a Query for another tenant's session_id lands in a partition that does not
    exist under the caller's tenant and returns ZERO rows. A foreign session_id
    cannot be read cross-tenant even when the session_id string is known."""

    def test_foreign_session_id_returns_no_decisions(self, mt_store):
        sig = mt_store.Table(_settings.dynamodb_validation_signals_table_v2)
        # Tenant A owns session "sess-shared" (a DENY decision on one request).
        sig.put_item(Item={
            "tenant_session_id": tenancy.compose("t_a", "sess-shared"),
            "sk": "req1#100#sentra.policy", "session_id": "sess-shared",
            "request_id": "req1", "source": "sentra.policy", "decision": "DENY",
            "agent_id": "t_a-aws-x-1", "timestamp_ms": 100, "priority": 100,
            "tenant_id": "t_a", "tenant_agent_id": tenancy.compose("t_a", "t_a-aws-x-1"),
            "timestamp_iso": "2026-06-11T00:00:00.000Z"})

        # Tenant A reads its own session -> the decision is visible.
        ctx_a = _ctx(tenant_id="t_a", is_platform=False)
        own = _as_tenant("t_a", lambda: R.get_session_decisions(session_id="sess-shared", ctx=ctx_a))
        assert own["total"] >= 1
        assert own["decisions"][0]["combined"]["decision"] == "DENY"

        # Tenant B requests the SAME session_id string -> foreign partition -> empty.
        ctx_b = _ctx(tenant_id="t_b", is_platform=False)
        foreign = _as_tenant("t_b", lambda: R.get_session_decisions(session_id="sess-shared", ctx=ctx_b))
        assert foreign["total"] == 0
        assert foreign["decisions"] == []


# ------------------------------------------------------------ GAP 2: list_agents cache leak
class TestListAgentsCacheLeakRegression:
    """GET /agents (routes.py:1382 -> AgentService.list_agents). REGRESSION GUARD
    for the cross-tenant cache-key leak: list_agents caches on the process-global
    singleton, and the pre-fix key omitted the tenant, so tenant B's list-read hit
    tenant A's cached rows. Verified to FAIL against the tenant-less key and PASS
    after the current_tenant()-prefixed key. The A-read populates the cache; the
    B-read must NOT see A's row."""

    def test_second_tenant_never_sees_first_tenants_cached_agents(self, mt_store):
        reg = mt_store.Table(_settings.dynamodb_agent_registry_table_v2)
        reg.put_item(Item={"tenant_id": "t_a", "agent_id": "t_a-aws-x-1", "status": "active",
                           "name": "A", "visibility": "external", "platform": "bedrock"})
        reg.put_item(Item={"tenant_id": "t_b", "agent_id": "t_b-aws-y-2", "status": "active",
                           "name": "B", "visibility": "external", "platform": "bedrock"})

        # A reads first -> populates the (now tenant-scoped) cache entry.
        ctx_a = _ctx(tenant_id="t_a", is_platform=False)
        a = _as_tenant("t_a", lambda: R.get_agents(enrich=False, managed_only=False, ctx=ctx_a))
        assert {x["agent_id"] for x in a["agents"]} == {"t_a-aws-x-1"}

        # B reads with the cache warm -> must get ONLY its own row, never A's.
        ctx_b = _ctx(tenant_id="t_b", is_platform=False)
        b = _as_tenant("t_b", lambda: R.get_agents(enrich=False, managed_only=False, ctx=ctx_b))
        b_ids = {x["agent_id"] for x in b["agents"]}
        assert b_ids == {"t_b-aws-y-2"}, b_ids
        assert "t_a-aws-x-1" not in b_ids  # the leak this guard pins


# ------------------------------------------------------------ POLICY cache leak
class TestListPoliciesCacheLeakRegression:
    """GET /policies (routes.py:1501 -> PolicyService.query_policies). REGRESSION
    GUARD for the SAME cache-key leak class on the list-all (agent_id=None) path:
    the DDB read is tenant-scoped via query_or_scan(current_tenant()), but the
    pre-fix cache key omitted the tenant, so tenant B's list-all hit tenant A's
    cached policies. Verified to FAIL against the tenant-less key and PASS after
    the current_tenant()-prefixed key."""

    def test_second_tenant_never_sees_first_tenants_cached_policies(self, mt_store):
        pol = mt_store.Table(_settings.dynamodb_policies_metadata_table_v2)
        pol.put_item(Item={"tenant_id": "t_a", "policy_id": "pol-a", "status": "active", "name": "A-pol"})
        pol.put_item(Item={"tenant_id": "t_b", "policy_id": "pol-b", "status": "active", "name": "B-pol"})

        # A reads the list-all path first -> warms the (now tenant-scoped) cache.
        ctx_a = _ctx(tenant_id="t_a", is_platform=False)
        a = _as_tenant("t_a", lambda: R.get_policies(ctx=ctx_a))
        assert {p["policy_id"] for p in a["policies"]} == {"pol-a"}

        # B reads with the cache warm -> must get ONLY its own policy, never A's.
        ctx_b = _ctx(tenant_id="t_b", is_platform=False)
        b = _as_tenant("t_b", lambda: R.get_policies(ctx=ctx_b))
        b_ids = {p["policy_id"] for p in b["policies"]}
        assert b_ids == {"pol-b"}, b_ids
        assert "pol-a" not in b_ids  # the leak this guard pins


# ============================================================
# GAP-6 — GET /agents: platform operator with break-glass sees target tenant
# ============================================================

class TestGetAgentsBreakGlass:
    """Platform operator with X-Aegion-Tenant break-glass header sees the target
    tenant's agents (bind-only via ambient current_tenant), NOT fleet.

    This closes the undocumented-intent gap: the break-glass mechanism in deps.py
    synthesizes ctx.tenant_id = target tenant, which list_agents auto-scopes via
    query_or_scan(current_tenant()). The test proves the platform operator with
    break-glass targeting t_b sees t_b's agents (and not t_a's)."""

    @pytest.mark.asyncio
    @patch("app.services.agent_service.AgentService")
    async def test_platform_breakglass_sees_target_tenant_agents(self, MockAgent):
        """Platform operator break-glass targeting t_b sees t_b's agents."""
        svc = MockAgent.return_value
        svc.list_agents = AsyncMock(return_value={
            "agents": [{"agent_id": "t_b-aws-agent-1", "name": "B-Agent"}],
            "total": 1,
        })

        # Break-glass: ctx.tenant_id = t_b (target), is_platform=True
        ctx = _ctx(tenant_id="t_b", is_platform=True)
        result = await R.get_agents(enrich=False, managed_only=False, ctx=ctx)

        # list_agents is called (bind-only), ambient current_tenant() = t_b
        svc.list_agents.assert_awaited_once_with(enrich=False, managed_only=False)
        assert result["total"] == 1
        assert result["agents"][0]["agent_id"] == "t_b-aws-agent-1"

    @pytest.mark.asyncio
    @patch("app.services.agent_service.AgentService")
    async def test_platform_breakglass_does_not_get_fleet(self, MockAgent):
        """Platform operator break-glass still bind-only (no fleet=True kwarg)."""
        svc = MockAgent.return_value
        svc.list_agents = AsyncMock(return_value={"agents": [], "total": 0})

        ctx = _ctx(tenant_id="t_b", is_platform=True)
        await R.get_agents(enrich=True, managed_only=True, ctx=ctx)

        # Verify fleet=True is NOT passed (bind-only by design)
        svc.list_agents.assert_awaited_once_with(enrich=True, managed_only=True)


# ============================================================
# GAP-7 — sigma-rules: cross-tenant isolation (two tenants get identical set)
# ============================================================

class TestSigmaRulesCrossTenantIsolation:
    """Two different tenant contexts calling GET /sigma-rules must receive the
    same result set (fleet-global resource, no accidental tenancy filtering).

    Closes the gap: a regression introducing tenant-filtering on sigma-rules
    would silently partition a fleet-global resource."""

    @pytest.mark.asyncio
    @patch("app.services.sigma_rules_service.SigmaRulesService.list_sigma_rules", new_callable=AsyncMock)
    async def test_two_tenants_get_identical_sigma_rules(self, mock_list):
        """Tenant t_a and t_b both get the same full rule set (no tenant filter)."""
        fleet_rules = {"rules": [{"rule_id": "r1"}, {"rule_id": "r2"}], "total": 2}
        mock_list.return_value = fleet_rules

        ctx_a = _ctx(tenant_id="t_a")
        ctx_b = _ctx(tenant_id="t_b")

        result_a = await R.get_sigma_rules(ctx=ctx_a)
        result_b = await R.get_sigma_rules(ctx=ctx_b)

        # Both tenants see the identical rule set
        assert result_a == result_b
        assert result_a["total"] == 2
        assert result_b["total"] == 2

        # The service was called twice, both times WITHOUT a tenant param
        assert mock_list.await_count == 2
        for call in mock_list.call_args_list:
            # No tenant_id kwarg was passed
            assert "tenant_id" not in call.kwargs

    @pytest.mark.asyncio
    @patch("app.services.sigma_rules_service.SigmaRulesService.list_sigma_rules", new_callable=AsyncMock)
    async def test_platform_gets_same_sigma_rules_as_customer(self, mock_list):
        """Platform operator gets the same rule set as a customer tenant."""
        fleet_rules = {"rules": [{"rule_id": "r1"}], "total": 1}
        mock_list.return_value = fleet_rules

        ctx_customer = _ctx(tenant_id="t_a", is_platform=False)
        ctx_platform = _ctx(tenant_id="_platform", is_platform=True)

        result_customer = await R.get_sigma_rules(ctx=ctx_customer)
        result_platform = await R.get_sigma_rules(ctx=ctx_platform)

        assert result_customer == result_platform


# ============================================================
# GAP-8 — discovery routes: platform operator is bind-only (intentional)
# ============================================================

class TestDiscoveryBindOnly:
    """Discovery routes (N5) are bind-only for ALL callers — platform operators
    do NOT get a fleet view because discovery data is tenant-scoped via
    connections. This test documents and verifies the intentional behavior.

    Closes the gap: no test verified whether the bind-only intent for platform
    operators on discovery was intentional vs a gap."""

    @pytest.mark.asyncio
    @patch("app.services.discovery_service.DiscoveryService")
    async def test_discovery_agents_platform_is_bind_only(self, MockDiscovery):
        """Platform operator on /discovery/agents: bind-only (no fleet param)."""
        svc = MockDiscovery.return_value
        svc.list_discovered = AsyncMock(return_value={
            "agents": [{"agent_id": "disc-1"}], "total": 1, "cursor": None,
        })

        ctx = _ctx(tenant_id="t_b", is_platform=True)
        result = await R.discovery_agents(ctx=ctx)

        # Service is called without any fleet/tenant_id override
        svc.list_discovered.assert_awaited_once()
        call_kwargs = svc.list_discovered.call_args.kwargs
        assert "fleet" not in call_kwargs
        assert "tenant_id" not in call_kwargs
        assert result["total"] == 1

    @pytest.mark.asyncio
    @patch("app.services.discovery_service.DiscoveryService")
    async def test_discovery_summary_platform_is_bind_only(self, MockDiscovery):
        """Platform operator on /discovery/summary: bind-only."""
        svc = MockDiscovery.return_value
        svc.summary = AsyncMock(return_value={"total": 5, "by_risk": {}})

        ctx = _ctx(tenant_id="t_b", is_platform=True)
        result = await R.discovery_summary(ctx=ctx)

        svc.summary.assert_awaited_once_with()
        assert result["total"] == 5

    @pytest.mark.asyncio
    @patch("app.services.discovery_service.DiscoveryService")
    async def test_discovery_platforms_platform_is_bind_only(self, MockDiscovery):
        """Platform operator on /discovery/platforms: bind-only."""
        svc = MockDiscovery.return_value
        svc.platforms = AsyncMock(return_value={"platforms": [{"name": "aws", "count": 3}]})

        ctx = _ctx(tenant_id="t_b", is_platform=True)
        result = await R.discovery_platforms(ctx=ctx)

        svc.platforms.assert_awaited_once_with()
        assert result["platforms"][0]["count"] == 3

    @pytest.mark.asyncio
    @patch("app.services.discovery_service.DiscoveryService")
    async def test_discovery_agents_customer_is_bind_only(self, MockDiscovery):
        """Customer operator on /discovery/agents: bind-only (same as platform)."""
        svc = MockDiscovery.return_value
        svc.list_discovered = AsyncMock(return_value={
            "agents": [], "total": 0, "cursor": None,
        })

        ctx = _ctx(tenant_id="t_a", is_platform=False)
        result = await R.discovery_agents(ctx=ctx)

        svc.list_discovered.assert_awaited_once()
        assert result["total"] == 0
