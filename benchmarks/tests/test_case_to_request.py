"""Unit tests for case_to_request conversion (LLD 41 §5.1, WS-C milestone C1)."""

import pytest
from benchmarks.core.case import BenchmarkCase
from benchmarks.core.context import RunContext
from benchmarks.rigs.replay import case_to_request


@pytest.fixture
def run_ctx(tmp_path):
    return RunContext(
        run_id="2026-07-27T14-02-11Z-a1b2c3",
        run_clock_iso="2026-07-27T14:02:11Z",
        transcript_dir=tmp_path,
        mode="A",
    )


@pytest.mark.parametrize("phase", ["content", "memory"])
def test_content_case_puts_payload_in_content_text_and_empty_user_input(phase, run_ctx):
    case = BenchmarkCase(
        benchmark="agentdojo",
        suite="banking",
        case_id=f"case_{phase}_1",
        episode_id=f"case_{phase}_1",
        phase=phase,
        agent_id="agent1",
        tool_name="tool1",
        tool_params={},
        user_input="user prompt here",
        content_text="payload text here",
        operation_type="READ",
        label=True,
        attack_type="indirect_injection",
        injection_goal="goal",
        expected_outcome="deny",
        raw={},
    )
    req = case_to_request(case, ctx=run_ctx)
    assert req.user_input == ""
    assert req.content_text == "payload text here"


def test_request_case_has_none_content_text(run_ctx):
    case = BenchmarkCase(
        benchmark="agentdojo",
        suite="banking",
        case_id="case_req_1",
        episode_id="case_req_1",
        phase="request",
        agent_id="agent1",
        tool_name="tool1",
        tool_params={"arg": "val"},
        user_input="user prompt here",
        content_text=None,
        operation_type="READ",
        label=False,
        attack_type=None,
        injection_goal=None,
        expected_outcome="allow",
        raw={},
    )
    req = case_to_request(case, ctx=run_ctx)
    assert req.user_input == "user prompt here"
    assert req.content_text is None


def test_request_id_is_derived_from_case_id(run_ctx):
    case = BenchmarkCase(
        benchmark="agentdojo", suite="banking", case_id="c123", episode_id="c123",
        phase="request", agent_id="a1", tool_name="t1", tool_params={},
        user_input="hi", content_text=None, operation_type="READ", label=False,
        attack_type=None, injection_goal=None, expected_outcome="allow", raw={},
    )
    req = case_to_request(case, ctx=run_ctx)
    assert req.request_id == "bench-c123"


def test_timestamp_is_run_clock(run_ctx):
    case = BenchmarkCase(
        benchmark="agentdojo", suite="banking", case_id="c1", episode_id="c1",
        phase="request", agent_id="a1", tool_name="t1", tool_params={},
        user_input="hi", content_text=None, operation_type="READ", label=False,
        attack_type=None, injection_goal=None, expected_outcome="allow", raw={},
    )
    req1 = case_to_request(case, ctx=run_ctx)
    req2 = case_to_request(case, ctx=run_ctx)
    assert req1.timestamp == run_ctx.run_clock_iso
    assert req1.timestamp == req2.timestamp
