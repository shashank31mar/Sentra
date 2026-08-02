"""Integration test proving CI gate blocks a degraded detector (LLD 41 G3)."""

from benchmarks.core.gate import check_benchmark_gate


def test_ci_gate_blocks_regression(tmp_path):
    thresh_file = tmp_path / "thresholds.yaml"
    thresh_file.write_text("fp_budget: 0.01\nrecall_floor: 0.70\n")

    # Degraded detector (recall 0.40 < recall_floor 0.70)
    degraded_metrics = {"readiness": "scored", "fp_rate": 0.005, "recall": 0.40}
    assert check_benchmark_gate(degraded_metrics, str(thresh_file)) is False

    # Healthy detector
    healthy_metrics = {"readiness": "scored", "fp_rate": 0.005, "recall": 0.85}
    assert check_benchmark_gate(healthy_metrics, str(thresh_file)) is True
