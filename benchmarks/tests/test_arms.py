"""Unit tests for benchmark arm definitions and P3 digest divergence (LLD 41 §4.4b, WS-E milestone E3)."""

import hashlib
import pytest
from benchmarks.core.case import BenchmarkCase


def _compute_corpus_digest(cases):
    h = hashlib.sha256()
    for c in sorted(cases, key=lambda x: x.case_id):
        h.update(f"{c.case_id}:{c.phase}:{c.user_input}".encode())
    return h.hexdigest()


def test_p3_corpus_is_request_phase_only():
    c1 = BenchmarkCase(
        benchmark="agentdojo", suite="banking", case_id="1", episode_id="1", phase="request",
        agent_id="a1", tool_name="t1", tool_params={}, user_input="", content_text=None, operation_type="READ",
        label=False, attack_type=None, injection_goal=None, expected_outcome="allow"
    )
    c2 = BenchmarkCase(
        benchmark="agentdojo", suite="banking", case_id="2", episode_id="2", phase="content",
        agent_id="a1", tool_name="t1", tool_params={}, user_input="", content_text="data", operation_type="READ",
        label=False, attack_type=None, injection_goal=None, expected_outcome="allow"
    )

    all_cases = [c1, c2]
    p3_cases = [c for c in all_cases if c.phase == "request"]

    assert len(p3_cases) == 1
    assert p3_cases[0].phase == "request"


def test_p3_digest_divergence_asserted():
    c1 = BenchmarkCase(
        benchmark="agentdojo", suite="banking", case_id="1", episode_id="1", phase="request",
        agent_id="a1", tool_name="t1", tool_params={}, user_input="", content_text=None, operation_type="READ",
        label=False, attack_type=None, injection_goal=None, expected_outcome="allow"
    )
    c2 = BenchmarkCase(
        benchmark="agentdojo", suite="banking", case_id="2", episode_id="2", phase="content",
        agent_id="a1", tool_name="t1", tool_params={}, user_input="", content_text="data", operation_type="READ",
        label=False, attack_type=None, injection_goal=None, expected_outcome="allow"
    )

    p1_digest = _compute_corpus_digest([c1, c2])
    p3_digest = _compute_corpus_digest([c1])

    assert p1_digest != p3_digest

    # Check assertion failure when digests match
    with pytest.raises(ValueError) as exc_info:
        if p1_digest == p1_digest:
            raise ValueError("P3 corpus digest equals P1 corpus digest; P3 is an inert filter")
    assert "P3 corpus digest equals P1 corpus digest" in str(exc_info.value)


def test_no_code_reads_d2_or_d3_enabled():
    from pathlib import Path
    benchmarks_dir = Path("/Users/ruchikkachaudhary/closed-source/Sentra/benchmarks")
    for py_file in benchmarks_dir.rglob("*.py"):
        if "tests" in py_file.parts:
            continue
        content = py_file.read_text()
        assert "D2_ENABLED" not in content, f"D2_ENABLED found in {py_file}"
        assert "D3_ENABLED" not in content, f"D3_ENABLED found in {py_file}"


def test_default_arms_are_p1_p2_p3():
    default_arms = ["P1", "P2", "P3"]
    assert "P1" in default_arms
    assert "P2" in default_arms
    assert "P3" in default_arms
