"""Integration test for paired arms run with stubbed LLM (LLD 41 §4.4b, WS-E milestone E3)."""

import pytest
from benchmarks.adapters.agentdojo.adapter import AgentDojoAdapter
from benchmarks.core.adapter import ArmResult


def test_paired_arms_stub_llm():
    adapter = AgentDojoAdapter()

    # Stub P1 arm results
    with_arm_p1 = ArmResult(arm="with", episode_ids=("e1",), native={"asr": 0.1, "utility": 0.9, "refuse_rate": 0.16})
    without_arm_p1 = ArmResult(arm="without", episode_ids=("e1",), native={"asr": 0.5, "utility": 1.0})

    score_p1 = adapter.score_run(with_arm=with_arm_p1, without_arm=without_arm_p1)
    assert score_p1.asr_reduction_pp == 40.0
    assert round(score_p1.utility_retention * 100.0, 2) == 90.0

    # Stub P3 arm results (request phase only)
    with_arm_p3 = ArmResult(arm="with", episode_ids=("e1",), native={"asr": 0.0, "utility": 1.0})
    without_arm_p3 = ArmResult(arm="without", episode_ids=("e1",), native={"asr": 0.33, "utility": 1.0})

    score_p3 = adapter.score_run(with_arm=with_arm_p3, without_arm=without_arm_p3)
    assert round(score_p3.asr_reduction_pp, 2) in (33.00, 33.0)
