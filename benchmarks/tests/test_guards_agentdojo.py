"""Unit tests for AgentDojo guards (LLD 41 §4.4, WS-E milestone E1)."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from agentdojo.types import ChatMessage, ChatToolResultMessage, FunctionCall
from benchmarks.adapters.agentdojo.guards import SentraContentGuard, SentraRequestGuard
from benchmarks.core.context import RunContext
from benchmarks.core.guard_client import Decision


class MockGuardClient:
    def __init__(self, allowed_tools=None):
        self.allowed_tools = allowed_tools or set()

    async def validate(self, req, session_id=None, ctx=None, transport="in-process"):
        tool_name = req.tool_name
        is_allowed = tool_name in self.allowed_tools
        return Decision(
            allowed=is_allowed,
            reason="Allowed" if is_allowed else f"Tool '{tool_name}' denied by policy",
            deciding_source="sentra.policy",
            trust_score_after=100.0 if is_allowed else 85.0,
            quarantined=False,
            latency_ms=1.0,
        )


def test_branch_a_non_assistant_turn_passes_through():
    client = MockGuardClient()
    guard = SentraRequestGuard(client=client)

    messages = [{"role": "user", "content": "hello"}]
    q, r, e, out_msgs, ea = guard.query("hello", MagicMock(), MagicMock(), messages, {})
    assert out_msgs == messages


def test_branch_b_all_allowed_passes_through():
    client = MockGuardClient(allowed_tools={"tool_a", "tool_b"})
    guard = SentraRequestGuard(client=client)

    tc1 = FunctionCall(id="tc1", function="tool_a", args={})
    tc2 = FunctionCall(id="tc2", function="tool_b", args={})
    messages = [{"role": "assistant", "content": None, "tool_calls": [tc1, tc2]}]

    q, r, e, out_msgs, ea = guard.query("query", MagicMock(), MagicMock(), messages, {})
    assert out_msgs == messages


def test_branch_c_mixed_delegates_allowed_subset():
    client = MockGuardClient(allowed_tools={"tool_a"})
    guard = SentraRequestGuard(client=client)

    tc1 = FunctionCall(id="tc1", function="tool_a", args={})
    tc2 = FunctionCall(id="tc2", function="tool_denied", args={})
    messages = [{"role": "assistant", "content": None, "tool_calls": [tc1, tc2]}]

    runtime = MagicMock()
    tool_mock = MagicMock()
    tool_mock.name = "tool_a"
    runtime.functions = {"tool_a": tool_mock}
    runtime.run_function = MagicMock(return_value=("output_a", None))

    q, r, e, out_msgs, ea = guard.query("query", runtime, MagicMock(), messages, {})
    assert len(out_msgs) == 3
    assert out_msgs[0] == messages[0]
    # Check tool result messages
    tool_msgs = out_msgs[1:]
    assert len(tool_msgs) == 2
    # tc1 (allowed) and tc2 (denied) in original order
    assert tool_msgs[0]["tool_call_id"] == "tc1"
    assert tool_msgs[1]["tool_call_id"] == "tc2"
    assert tool_msgs[1]["error"] == "Tool 'tool_denied' denied by policy"


def test_branch_c_all_denied_appends_only_errors():
    client = MockGuardClient(allowed_tools=set())
    guard = SentraRequestGuard(client=client)

    tc1 = FunctionCall(id="tc1", function="denied_1", args={})
    tc2 = FunctionCall(id="tc2", function="denied_2", args={})
    messages = [{"role": "assistant", "content": None, "tool_calls": [tc1, tc2]}]

    q, r, e, out_msgs, ea = guard.query("query", MagicMock(), MagicMock(), messages, {})
    assert len(out_msgs) == 3
    assert out_msgs[1]["error"] == "Tool 'denied_1' denied by policy"
    assert out_msgs[2]["error"] == "Tool 'denied_2' denied by policy"


def test_synthetic_messages_are_tagged():
    client = MockGuardClient(allowed_tools=set())
    guard = SentraRequestGuard(client=client)

    tc1 = FunctionCall(id="tc1", function="denied_1", args={})
    messages = [{"role": "assistant", "content": None, "tool_calls": [tc1]}]

    q, r, e, out_msgs, ea = guard.query("query", MagicMock(), MagicMock(), messages, {})
    assert getattr(out_msgs[1], "aegion_synthetic", False) is True or out_msgs[1].get("aegion_synthetic") is True


def test_content_guard_skips_synthetic_and_counts_it():
    client = MockGuardClient()
    client.validate = AsyncMock()

    ctx = MagicMock()
    ctx.synthetic_content_skipped = 0
    guard = SentraContentGuard(client=client, ctx=ctx)

    synth_msg = ChatToolResultMessage(
        role="tool",
        content=[],
        tool_call_id="tc1",
        tool_call=MagicMock(),
        error="denied",
    )
    synth_msg["aegion_synthetic"] = True

    messages = [synth_msg]
    guard.query("query", MagicMock(), MagicMock(), messages, {})

    # GuardClient validate should NOT be called
    client.validate.assert_not_called()
    assert guard.synthetic_content_skipped == 1
    assert ctx.synthetic_content_skipped == 1


def test_content_guard_never_raises():
    client = MockGuardClient()
    
    async def _failing_validate(*args, **kwargs):
        raise RuntimeError("Validation explosion")
    
    client.validate = _failing_validate

    guard = SentraContentGuard(client=client)
    res = guard.detect("suspicious payload")
    assert res == (False, 0.0)
