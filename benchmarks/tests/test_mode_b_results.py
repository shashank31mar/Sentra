"""Unit tests for Mode B results aggregation (LLD 41 §4.6, WS-E milestone E6)."""

import pytest
from benchmarks.core.mode_b_results import build_mode_b_results


def test_first_deny_denominator_is_episodes():
    # Episode 1 has 3 denies: all sentra.trust
    # Episode 2 has 1 deny: sentra.policy
    rows = [
        {"episode_id": "ep1", "decision": "DENY", "deciding_source": "sentra.trust"},
        {"episode_id": "ep1", "decision": "DENY", "deciding_source": "sentra.trust"},
        {"episode_id": "ep1", "decision": "DENY", "deciding_source": "sentra.trust"},
        {"episode_id": "ep2", "decision": "DENY", "deciding_source": "sentra.policy"},
    ]

    res = build_mode_b_results(rows)
    assert res["by_deciding_source_first_deny"]["sentra.trust"] == 1
    assert res["by_deciding_source_first_deny"]["sentra.policy"] == 1
    assert res["by_deciding_source_all_denies"]["sentra.trust"] == 3


def test_both_tables_emitted_and_labelled():
    rows = [{"episode_id": "ep1", "decision": "DENY", "deciding_source": "sentra.sigma"}]
    res = build_mode_b_results(rows)
    assert "by_deciding_source_first_deny" in res
    assert "by_deciding_source_all_denies" in res


def test_trust_dominance_emits_a_worded_finding():
    rows = [
        {"episode_id": "ep1", "decision": "DENY", "deciding_source": "sentra.trust"},
        {"episode_id": "ep2", "decision": "DENY", "deciding_source": "sentra.trust"},
        {"episode_id": "ep3", "decision": "DENY", "deciding_source": "sentra.policy"},
    ]
    res = build_mode_b_results(rows)
    assert res["trust_dominance_finding"] is not None
    assert "G2 is defeated for this run" in res["trust_dominance_finding"]


def test_episodes_quarantined_rolls_up_from_rows():
    rows = [
        {"episode_id": "ep1", "quarantined": True},
        {"episode_id": "ep1", "quarantined": True},
        {"episode_id": "ep2", "quarantined": False},
    ]
    res = build_mode_b_results(rows)
    assert res["episodes_quarantined"] == 1


def test_synthetic_content_skipped_rolls_up():
    res = build_mode_b_results([], synthetic_content_skipped=42)
    assert res["synthetic_content_skipped"] == 42
