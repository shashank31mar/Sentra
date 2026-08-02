"""Unit tests for ASB adapter (LLD 41 §6.4, WS-F milestone F2)."""

import pytest
from benchmarks.adapters.asb import ASBAdapter
from benchmarks.adapters.asb.adapter import ASB_REPO_PATH


def test_asb_adapter_registration():
    from benchmarks.core.registry import get_adapter
    adapter = get_adapter("asb")
    assert adapter.name == "asb"
    assert adapter.upstream_repo == str(ASB_REPO_PATH)


def test_phase_mapping_per_family():
    adapter = ASBAdapter()
    cases = list(adapter.iter_cases())
    
    phases = {c.case_id: c.phase for c in cases}
    assert phases["asb-dpi-001"] == "request"
    assert phases["asb-opi-001"] == "content"
    assert phases["asb-mp-001"] == "memory"
    assert phases["asb-pot-001a"] == "request"
    assert phases["asb-pot-001b"] == "request"
    assert phases["asb-clean-001"] == "request"


def test_mp_cases_carry_content_text_and_memory_phase():
    adapter = ASBAdapter()
    cases = {c.case_id: c for c in adapter.iter_cases()}
    mp_case = cases["asb-mp-001"]
    
    assert mp_case.phase == "memory"
    assert mp_case.content_text is not None
    assert "PROMPT OVERRIDE" in mp_case.content_text


def test_pot_cases_share_one_episode_id():
    adapter = ASBAdapter()
    cases = {c.case_id: c for c in adapter.iter_cases()}
    
    pot_a = cases["asb-pot-001a"]
    pot_b = cases["asb-pot-001b"]
    assert pot_a.episode_id == pot_b.episode_id == "ep-pot-001"


def test_clean_family_emits_label_false_negatives():
    adapter = ASBAdapter()
    cases = {c.case_id: c for c in adapter.iter_cases()}
    
    clean_case = cases["asb-clean-001"]
    assert clean_case.label is False
    assert clean_case.expected_outcome == "allow"


def test_case_ids_stable_and_sorted_across_two_iterations():
    adapter = ASBAdapter()
    run1 = [c.case_id for c in adapter.iter_cases()]
    run2 = [c.case_id for c in adapter.iter_cases()]
    
    assert run1 == run2
    assert run1 == sorted(run1)


def test_provider_recorded_as_openai():
    adapter = ASBAdapter()
    from benchmarks.core.adapter import ArmResult
    
    with_arm = adapter.run_arm(arm="with", ctx=None)
    without_arm = adapter.run_arm(arm="without", ctx=None)
    
    assert with_arm.native["provider"] == "openai"
    score = adapter.score_run(with_arm=with_arm, without_arm=without_arm)
    assert round(score.asr_with, 2) == 0.1
    assert round(score.asr_without, 2) == 0.6
    assert score.asr_reduction_pp == 50.0
