"""Unit tests for run diff tool (LLD 41 §7.3, G5)."""

import pytest
from benchmarks.core.diff import (
    IncompleteBaselineError,
    SchemaVersionMismatchError,
    compare_runs,
)


def test_four_buckets():
    curr_m = {"exit": "complete", "schema_version": "1", "benchmark": {"git_sha": "abc"}}
    base_m = {"exit": "complete", "schema_version": "1", "benchmark": {"git_sha": "abc"}}

    curr_rows = [
        {"case_id": "c1", "decision": "DENY"},  # was ALLOW, now DENY -> fixed
        {"case_id": "c2", "decision": "ALLOW"}, # was DENY, now ALLOW -> regressed
        {"case_id": "c3", "decision": "DENY"},  # was DENY, now DENY -> unchanged
        {"case_id": "c4", "decision": "ALLOW"}, # new
    ]
    base_rows = [
        {"case_id": "c1", "decision": "ALLOW"},
        {"case_id": "c2", "decision": "DENY"},
        {"case_id": "c3", "decision": "DENY"},
        {"case_id": "c5", "decision": "ALLOW"}, # removed
    ]

    res = compare_runs(curr_m, curr_rows, base_m, base_rows)
    assert res.fixed == ["c1"]
    assert res.regressed == ["c2"]
    assert res.unchanged == ["c3"]
    assert sorted(res.new_or_removed) == ["c4", "c5"]


def test_adapter_moved_warning():
    curr_m = {"exit": "complete", "schema_version": "1", "benchmark": {"git_sha": "abc"}}
    base_m = {"exit": "complete", "schema_version": "1", "benchmark": {"git_sha": "abc"}}

    curr_rows = [{"case_id": "c1", "decision": "DENY"}, {"case_id": "c2", "decision": "ALLOW"}]
    base_rows = [{"case_id": "c1", "decision": "DENY"}]

    res = compare_runs(curr_m, curr_rows, base_m, base_rows)
    assert res.adapter_moved_warning is True


def test_refuses_incomplete_baseline():
    curr_m = {"exit": "complete", "schema_version": "1"}
    base_m = {"exit": "aborted", "schema_version": "1"}

    with pytest.raises(IncompleteBaselineError):
        compare_runs(curr_m, [], base_m, [])


def test_refuses_schema_version_mismatch():
    curr_m = {"exit": "complete", "schema_version": "2"}
    base_m = {"exit": "complete", "schema_version": "1"}

    with pytest.raises(SchemaVersionMismatchError):
        compare_runs(curr_m, [], base_m, [])


def test_within_noise_on_aggregate_only():
    curr_m = {
        "exit": "complete",
        "schema_version": "1",
        "benchmark": {"git_sha": "abc"},
        "results": {"mode_b": {"asr_reduction_pp": 30.5}},
    }
    base_m = {
        "exit": "complete",
        "schema_version": "1",
        "benchmark": {"git_sha": "abc"},
        "results": {"mode_b": {"asr_reduction_pp": 30.0}},
    }
    # delta is +0.5, which is < noise_floor 1.5
    curr_rows = [{"case_id": "c1", "decision": "DENY"}]
    base_rows = [{"case_id": "c1", "decision": "ALLOW"}]

    res = compare_runs(curr_m, curr_rows, base_m, base_rows, noise_floor_pp=1.5)
    assert res.aggregate_verdict == "within-noise"
    assert res.fixed == ["c1"]  # Per-case buckets are still fully populated!
