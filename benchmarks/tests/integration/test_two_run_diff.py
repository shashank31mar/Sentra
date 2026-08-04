"""Integration test for two-run diff generation (LLD 41 G5)."""

from benchmarks.core.diff import compare_runs
from benchmarks.core.manifest import Manifest


def test_two_run_diff(tmp_path):
    run1_dir = tmp_path / "run1"
    run2_dir = tmp_path / "run2"

    m1 = Manifest.collect(adapter_name="agentdojo", allow_dirty=True)
    m1.data["results"]["mode_b"] = {"asr_reduction_pp": 20.0}
    m1.write(run1_dir, exit_status="complete")

    m2 = Manifest.collect(adapter_name="agentdojo", allow_dirty=True)
    m2.data["results"]["mode_b"] = {"asr_reduction_pp": 25.0}
    m2.write(run2_dir, exit_status="complete")

    r1_rows = [
        {"case_id": "c1", "decision": "ALLOW"},
        {"case_id": "c2", "decision": "DENY"},
    ]
    r2_rows = [
        {"case_id": "c1", "decision": "DENY"},  # fixed
        {"case_id": "c2", "decision": "DENY"},  # unchanged
    ]

    res = compare_runs(m2.data, r2_rows, m1.data, r1_rows)
    assert res.fixed == ["c1"]
    assert res.unchanged == ["c2"]
    assert res.aggregate_verdict == "improved"
