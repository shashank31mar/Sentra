"""Integration test for readiness contract across producer (WS-C) and consumers (WS-A)."""

from benchmarks.core.gate import check_benchmark_gate
from benchmarks.core.readiness import assess_detector_readiness
from benchmarks.core.report import generate_report


def test_readiness_contract(tmp_path):
    thresh_file = tmp_path / "thresholds.yaml"
    thresh_file.write_text("fp_budget: 0.01\nrecall_floor: 0.70\n")

    # 1. Armed & Scored
    r_scored = assess_detector_readiness("d1", fired_count=50, artifact_info={"sigma_rule_count": 10})
    m_scored = {"readiness": r_scored["verdict"], "recall": 0.85, "fp_rate": 0.005}
    assert check_benchmark_gate(m_scored, str(thresh_file)) is True

    # 2. Inert (fired_count == 0)
    r_inert = assess_detector_readiness("d1", fired_count=0, artifact_info={"sigma_rule_count": 10})
    m_inert = {"readiness": r_inert["verdict"], "recall": 0.0, "fp_rate": 0.0}
    assert check_benchmark_gate(m_inert, str(thresh_file)) is None

    # Report verification
    manifest_data = {
        "benchmark": {},
        "results": {"mode_a": {"d1": m_inert}},
    }
    report = generate_report(manifest_data, rows=[])
    assert "`inert`" in report
