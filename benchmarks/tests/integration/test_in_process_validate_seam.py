"""Integration test for in-process validate seam under execution isolation (LLD 41 §4.8, WS-D milestone D4)."""

import pytest
from app.api.models import ValidationRequest
from benchmarks.core.context import RunContext
from benchmarks.core.guard_client import GuardClient
from benchmarks.core.null_objects import NullAuditWriter, NullMetricsPublisher
from benchmarks.core.policy_fixture import patch_policy_engine
from benchmarks.core.session_store import BenchmarkSessionStore


@pytest.mark.asyncio
async def test_in_process_validate_seam(monkeypatch):
    monkeypatch.setattr("app.utils.audit_logger.AuditLogger", lambda: NullAuditWriter())
    monkeypatch.setattr("app.utils.metrics_publisher.MetricsPublisher", lambda: NullMetricsPublisher())

    syn_policy = {
        "agent_id": "seam-agent",
        "allowed_tools": ["read_inbox", "search_contacts"],
        "allowed_agents": [],
        "max_calls_per_minute": 10000,
        "platform": "unknown",
        "cloud_region": "us-east-1",
        "metadata": {},
    }

    ctx = RunContext.for_mode_a(run_id="run-seam", run_clock_iso="2026-08-02T12:00:00Z")

    with patch_policy_engine({"seam-agent": syn_policy}):
        gc = GuardClient()
        gc.service.session_manager = BenchmarkSessionStore()

        # 1. Allowed request
        req_allowed = ValidationRequest(
            request_id="r1",
            session_id="s1",
            agent_id="seam-agent",
            user_id="u1",
            tool_name="read_inbox",
            tool_params={},
            phase="request",
            operation_type="READ",
            user_input="check mail",
            timestamp="2026-08-02T12:00:00Z",
        )
        dec1 = await gc.validate(req_allowed, session_id="s1", ctx=ctx, transport="in-process")
        assert dec1.allowed is True

        # 2. Four DENYs entering quarantine
        req_denied = ValidationRequest(
            request_id="r2",
            session_id="s1",
            agent_id="seam-agent",
            user_id="u1",
            tool_name="unauthorized_tool",
            tool_params={},
            phase="request",
            operation_type="WRITE",
            user_input="hack",
            timestamp="2026-08-02T12:00:00Z",
        )

        for _ in range(4):
            dec = await gc.validate(req_denied, session_id="s1", ctx=ctx, transport="in-process")

        assert dec.trust_score_after == 40.0
        assert dec.quarantined is True
