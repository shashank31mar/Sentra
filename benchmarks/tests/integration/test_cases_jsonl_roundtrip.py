"""Integration test for cases.jsonl two-reader roundtrip (report & diff)."""

from benchmarks.core.cases_jsonl import (
    CaseLedgerRow,
    CasesJsonlWriter,
    load_cases_jsonl,
)
from benchmarks.core.report import generate_report


def test_cases_jsonl_roundtrip(tmp_path):
    file_path = tmp_path / "cases.jsonl"
    writer = CasesJsonlWriter(file_path)

    # Write Mode A and Mode B rows
    r1 = CaseLedgerRow(
        case_id="c1", episode_id="ep1", session_id="s1", arm="with", phase="request",
        label=True, expected_outcome="deny", decision="DENY", deciding_source="sentra.policy",
        trust_score_after=0.2, quarantined=False, first_deny_in_episode=True, reason="deny",
        latency_ms=10.0, attack_success=False, utility=True,
    )
    r2 = CaseLedgerRow(
        case_id="c2", episode_id="ep2", session_id="s2", arm=None, phase="request",
        label=False, expected_outcome="allow", decision="ALLOW", deciding_source=None,
        trust_score_after=1.0, quarantined=False, first_deny_in_episode=False, reason="allow",
        latency_ms=8.0, attack_success=None, utility=None,
    )
    writer.append_row(r1)
    writer.append_row(r2)

    loaded = load_cases_jsonl(file_path)
    assert len(loaded) == 2

    manifest_data = {
        "benchmark": {"suites": ["all"], "dirty": False},
        "results": {"mode_b": {"asr_reduction_pp": 20.0}},
        "errors": [],
    }

    report = generate_report(manifest_data, loaded)
    assert "Sentra Security Benchmark Report" in report
