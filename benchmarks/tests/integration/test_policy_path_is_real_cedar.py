"""Integration test verifying synthesized policy drives real Cedar evaluation (LLD 41 §4.5, WS-D milestone D2)."""

import pytest
from app.api.models import ValidationRequest
from app.services.validation_service import ValidationService
from benchmarks.core.policy_fixture import patch_policy_engine
from benchmarks.core.session_store import BenchmarkSessionStore


@pytest.mark.asyncio
async def test_policy_path_is_real_cedar(monkeypatch):
    from benchmarks.core.null_objects import NullAuditWriter
    monkeypatch.setattr("app.utils.audit_logger.AuditLogger", lambda: NullAuditWriter())

    syn_policy = {
        "agent_id": "cedar-agent",
        "allowed_tools": ["allowed_tool"],
        "allowed_agents": [],
        "max_calls_per_minute": 10000,
        "platform": "unknown",
        "cloud_region": "us-east-1",
        "metadata": {},
    }

    from app.config import settings
    monkeypatch.setattr(settings, "cedar_enabled", True)

    with patch_policy_engine({"cedar-agent": syn_policy}):
        svc = ValidationService()
        from benchmarks.core.null_objects import NullAuditWriter, NullMetricsPublisher
        svc.audit_logger = NullAuditWriter()
        svc.metrics_publisher = NullMetricsPublisher()
        svc.session_manager = BenchmarkSessionStore()

        # 1. Validation request for allowed tool
        req_allowed = ValidationRequest(
            request_id="req-1",
            session_id="sess-1",
            agent_id="cedar-agent",
            user_id="u1",
            tool_name="allowed_tool",
            tool_params={},
            phase="request",
            operation_type="READ",
            user_input="test",
            timestamp="2026-08-02T12:00:00Z",
        )
        res_allowed = await svc.validate_tool_call(req_allowed)
        assert res_allowed["decision"] == "ALLOW"

        # 2. Validation request for disallowed tool
        req_denied = ValidationRequest(
            request_id="req-2",
            session_id="sess-1",
            agent_id="cedar-agent",
            user_id="u1",
            tool_name="forbidden_tool",
            tool_params={},
            phase="request",
            operation_type="WRITE",
            user_input="test",
            timestamp="2026-08-02T12:00:00Z",
        )
        res_denied = await svc.validate_tool_call(req_denied)
        assert res_denied["decision"] == "DENY"
        assert res_denied["violation_type"] in ("POLICY_VIOLATION", "UNAUTHORIZED_TOOL")
