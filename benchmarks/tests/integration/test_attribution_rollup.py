"""Integration test for cases.jsonl -> results.mode_b attribution rollup (LLD 41 §4.6, WS-E milestone E6)."""

import pytest
from benchmarks.core.mode_b_results import build_mode_b_results
from benchmarks.core.report import generate_markdown_report


def test_attribution_rollup():
    cases_rows = [
        {"episode_id": "ep1", "decision": "DENY", "deciding_source": "sentra.trust", "quarantined": True},
        {"episode_id": "ep1", "decision": "DENY", "deciding_source": "sentra.trust", "quarantined": True},
        {"episode_id": "ep2", "decision": "DENY", "deciding_source": "sentra.policy", "quarantined": False},
        {"episode_id": "ep3", "decision": "DENY", "deciding_source": "sentra.sigma", "quarantined": False},
    ]

    res = build_mode_b_results(cases_rows, synthetic_content_skipped=5)
    assert res["episodes_quarantined"] == 1
    assert res["synthetic_content_skipped"] == 5
    assert res["by_deciding_source_first_deny"] == {
        "sentra.trust": 1,
        "sentra.policy": 1,
        "sentra.sigma": 1,
    }
