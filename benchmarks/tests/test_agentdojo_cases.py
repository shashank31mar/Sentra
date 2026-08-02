"""Unit tests for AgentDojo adapter (LLD 41 §5.1, WS-C milestone C4)."""

import pytest
from benchmarks.adapters.agentdojo.adapter import AgentDojoAdapter, InsufficientNegativesError
from benchmarks.core.case import BenchmarkCase


def test_case_ids_are_stable_and_sorted():
    adapter = AgentDojoAdapter()
    cases1 = list(adapter.iter_cases(suite="banking"))
    cases2 = list(adapter.iter_cases(suite="banking"))

    ids1 = [c.case_id for c in cases1]
    ids2 = [c.case_id for c in cases2]

    assert ids1 == ids2
    assert ids1 == sorted(ids1)


def test_benign_negatives_emitted_with_label_false():
    adapter = AgentDojoAdapter()
    cases = list(adapter.iter_cases(suite="banking"))
    benign = [c for c in cases if not c.label]
    assert len(benign) >= 300
    assert all(c.expected_outcome == "allow" for c in benign)


def test_refuses_below_30_negatives():
    few_negatives = [
        BenchmarkCase(
            benchmark="agentdojo", suite="banking", case_id=f"c{i}", episode_id=f"c{i}",
            phase="content", agent_id="a", tool_name="t", tool_params={}, user_input="",
            content_text="txt", operation_type="READ", label=False, attack_type=None,
            injection_goal=None, expected_outcome="allow", raw={},
        )
        for i in range(10)
    ]
    adapter = AgentDojoAdapter(fixture_cases=few_negatives)
    with pytest.raises(InsufficientNegativesError) as exc_info:
        list(adapter.iter_cases())
    assert "minimum required floor is 30" in str(exc_info.value)


def test_tool_manifest_provenance():
    adapter = AgentDojoAdapter()
    manifest = adapter.tool_manifest(suite="banking")
    assert manifest.provenance.startswith("agentdojo:banking@")
