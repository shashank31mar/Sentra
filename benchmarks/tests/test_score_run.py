"""Unit tests for score_run AgentDojo security -> ASR mapping (LLD 41 §5.2, WS-E milestone E2)."""

import pytest
from benchmarks.adapters.agentdojo.adapter import AgentDojoAdapter
from benchmarks.core.adapter import ArmResult


def test_security_true_means_attack_failed():
    adapter = AgentDojoAdapter()
    # security = 1.0 means attack failed for 100% of cases -> asr == 0.0
    with_arm = ArmResult(arm="with", episode_ids=("e1",), native={"security": 1.0, "utility": 1.0})
    without_arm = ArmResult(arm="without", episode_ids=("e1",), native={"security": 0.5, "utility": 1.0})

    score = adapter.score_run(with_arm=with_arm, without_arm=without_arm)
    assert score.asr_with == 0.0
    assert score.asr_without == 0.5
    assert score.asr_reduction_pp == 50.0


def test_asr_reduction_is_pp_not_relative():
    adapter = AgentDojoAdapter()
    with_arm = ArmResult(arm="with", episode_ids=("e1",), native={"asr": 0.11, "utility": 1.0})
    without_arm = ArmResult(arm="without", episode_ids=("e1",), native={"asr": 0.43, "utility": 1.0})

    score = adapter.score_run(with_arm=with_arm, without_arm=without_arm)
    assert round(score.asr_reduction_pp, 2) == 32.0


def test_utility_retention_reports_both_raw_numbers():
    adapter = AgentDojoAdapter()
    with_arm = ArmResult(arm="with", episode_ids=("e1",), native={"asr": 0.1, "utility": 0.8})
    without_arm = ArmResult(arm="without", episode_ids=("e1",), native={"asr": 0.5, "utility": 1.0})

    score = adapter.score_run(with_arm=with_arm, without_arm=without_arm)
    assert score.utility_with == 0.8
    assert score.utility_without == 1.0
    assert round(score.utility_retention * 100.0, 2) == 80.0


def test_refuse_rate_from_attribution_rows():
    adapter = AgentDojoAdapter()
    with_arm = ArmResult(arm="with", episode_ids=("e1",), native={"asr": 0.1, "utility": 0.8, "refuse_rate": 0.25})
    without_arm = ArmResult(arm="without", episode_ids=("e1",), native={"asr": 0.5, "utility": 1.0})

    score = adapter.score_run(with_arm=with_arm, without_arm=without_arm)
    assert score.refuse_rate == 0.25
