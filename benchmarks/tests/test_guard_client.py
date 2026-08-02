"""Unit tests for GuardClient (LLD 41 §4.8, WS-D milestone D4)."""

import pytest
from app.api.models import ValidationRequest
from benchmarks.core.context import RunContext
from benchmarks.core.guard_client import Decision, GuardClient, RunAborted


class MockAccountant:
    def __init__(self):
        self.n_validate_calls = 0


@pytest.mark.asyncio
async def test_deny_does_not_raise(monkeypatch):
    from benchmarks.core.null_objects import NullAuditWriter, NullMetricsPublisher
    from benchmarks.core.policy_fixture import patch_policy_engine
    monkeypatch.setattr("app.utils.audit_logger.AuditLogger", lambda: NullAuditWriter())
    monkeypatch.setattr("app.utils.metrics_publisher.MetricsPublisher", lambda: NullMetricsPublisher())

    gc = GuardClient()
    ctx = RunContext.for_mode_a(run_id="run-1", run_clock_iso="2026-08-02T12:00:00Z")

    req = ValidationRequest(
        request_id="req-deny",
        session_id="sess-gc-1",
        agent_id="gc-agent",
        user_id="u1",
        tool_name="forbidden_tool",
        tool_params={},
        phase="request",
        operation_type="WRITE",
        user_input="test",
        timestamp="2026-08-02T12:00:00Z",
    )

    syn_policy = {"agent_id": "gc-agent", "allowed_tools": ["allowed_tool"], "metadata": {}}
    with patch_policy_engine({"gc-agent": syn_policy}):
        decision = await gc.validate(req, session_id="sess-gc-1", ctx=ctx, transport="in-process")
        assert isinstance(decision, Decision)
        assert decision.allowed is False


@pytest.mark.asyncio
async def test_n_validate_calls_incremented_in_finally(monkeypatch):
    from benchmarks.core.null_objects import NullAuditWriter, NullMetricsPublisher
    from benchmarks.core.policy_fixture import patch_policy_engine
    monkeypatch.setattr("app.utils.audit_logger.AuditLogger", lambda: NullAuditWriter())
    monkeypatch.setattr("app.utils.metrics_publisher.MetricsPublisher", lambda: NullMetricsPublisher())

    accountant = MockAccountant()
    gc = GuardClient(accountant=accountant)
    ctx = RunContext.for_mode_a(run_id="run-1", run_clock_iso="2026-08-02T12:00:00Z")

    req = ValidationRequest(
        request_id="req-1",
        session_id="sess-1",
        agent_id="agent-1",
        user_id="u1",
        tool_name="test_tool",
        tool_params={},
        phase="request",
        operation_type="READ",
        user_input="test",
        timestamp="2026-08-02T12:00:00Z",
    )

    syn_policy = {"agent_id": "agent-1", "allowed_tools": ["test_tool"], "metadata": {}}
    with patch_policy_engine({"agent-1": syn_policy}):
        await gc.validate(req, session_id="sess-1", ctx=ctx, transport="in-process")
    assert accountant.n_validate_calls == 1


@pytest.mark.asyncio
async def test_three_consecutive_transport_failures_abort(monkeypatch):
    gc = GuardClient()
    ctx = RunContext.for_mode_a(run_id="run-1", run_clock_iso="2026-08-02T12:00:00Z")

    async def _failing_validate(req, session_id):
        raise ConnectionError("Transport failure")

    monkeypatch.setattr(gc, "_validate_in_process", _failing_validate)

    req = ValidationRequest(
        request_id="req-1", session_id="s1", agent_id="a1", user_id="u1",
        tool_name="t1", tool_params={}, phase="request", operation_type="READ",
        user_input="", timestamp="2026-08-02T12:00:00Z",
    )

    # First 2 failures raise ConnectionError
    with pytest.raises(ConnectionError):
        await gc.validate(req, session_id="s1", ctx=ctx, transport="in-process")

    with pytest.raises(ConnectionError):
        await gc.validate(req, session_id="s1", ctx=ctx, transport="in-process")

    # 3rd failure raises RunAborted
    with pytest.raises(RunAborted) as exc_info:
        await gc.validate(req, session_id="s1", ctx=ctx, transport="in-process")
    assert "3 consecutive transport failures" in str(exc_info.value)
