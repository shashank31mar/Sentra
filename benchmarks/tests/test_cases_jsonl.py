"""Unit tests for cases.jsonl writer and resume ledger (LLD 41 §12, §14.2, FR-14.5)."""

from pathlib import Path
import pytest
from benchmarks.core.cases_jsonl import (
    CASES_JSONL_FIELDS,
    CaseLedgerRow,
    CasesJsonlWriter,
    load_cases_jsonl,
)


def test_error_decision_is_not_coerced(tmp_path):
    writer = CasesJsonlWriter(tmp_path / "cases.jsonl")
    row = CaseLedgerRow(
        case_id="c1",
        episode_id="ep1",
        session_id="bench-123-abc",
        arm="with",
        phase="request",
        label=True,
        expected_outcome="deny",
        decision="ERROR",
        deciding_source=None,
        trust_score_after=None,
        quarantined=False,
        first_deny_in_episode=False,
        reason="Execution fault",
        latency_ms=12.5,
    )
    writer.append_row(row)

    rows = load_cases_jsonl(tmp_path / "cases.jsonl")
    assert len(rows) == 1
    assert rows[0]["decision"] == "ERROR"


def test_resume_skips_existing_pair(tmp_path):
    writer = CasesJsonlWriter(tmp_path / "cases.jsonl")
    row1 = CaseLedgerRow(
        case_id="c1", episode_id="ep1", session_id="s1", arm="with", phase="request",
        label=True, expected_outcome="deny", decision="DENY", deciding_source="sentra.policy",
        trust_score_after=0.1, quarantined=False, first_deny_in_episode=True, reason="policy_deny",
        latency_ms=10.0,
    )
    writer.append_row(row1)

    completed = writer.read_completed_pairs()
    assert ("c1", "with") in completed

    # Simulated resume
    if ("c1", "with") not in completed:
        writer.append_row(row1)

    row2 = CaseLedgerRow(
        case_id="c1", episode_id="ep1", session_id="s1", arm="without", phase="request",
        label=True, expected_outcome="deny", decision="ALLOW", deciding_source=None,
        trust_score_after=1.0, quarantined=False, first_deny_in_episode=False, reason="allow",
        latency_ms=8.0,
    )
    if ("c1", "without") not in completed:
        writer.append_row(row2)

    rows = load_cases_jsonl(tmp_path / "cases.jsonl")
    assert len(rows) == 2


def test_mode_a_rows_have_null_arm(tmp_path):
    writer = CasesJsonlWriter(tmp_path / "cases.jsonl")
    row = CaseLedgerRow(
        case_id="c1", episode_id="ep1", session_id="s1", arm=None, phase="request",
        label=True, expected_outcome="deny", decision="DENY", deciding_source="sentra.trust",
        trust_score_after=None, quarantined=False, first_deny_in_episode=True, reason="deny",
        latency_ms=5.0,
    )
    writer.append_row(row)

    rows = load_cases_jsonl(tmp_path / "cases.jsonl")
    assert rows[0]["arm"] is None


def test_all_16_fields_present(tmp_path):
    writer = CasesJsonlWriter(tmp_path / "cases.jsonl")
    row = CaseLedgerRow(
        case_id="c1", episode_id="ep1", session_id="s1", arm="with", phase="request",
        label=True, expected_outcome="deny", decision="DENY", deciding_source="sentra.policy",
        trust_score_after=0.5, quarantined=False, first_deny_in_episode=True, reason="deny",
        latency_ms=15.0, attack_success=False, utility=True,
    )
    writer.append_row(row)

    rows = load_cases_jsonl(tmp_path / "cases.jsonl")
    assert set(rows[0].keys()) == set(CASES_JSONL_FIELDS)
    assert len(rows[0].keys()) == 16
