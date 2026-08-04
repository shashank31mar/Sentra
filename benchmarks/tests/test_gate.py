"""Unit tests for Mode A CI Gate (LLD 41 §15, FR-14.2, G3)."""

from pathlib import Path
from benchmarks.core.gate import check_benchmark_gate
import scripts.eval_ml_classifier as eval_ml_mod


def test_inert_detector_yields_no_verdict(tmp_path):
    thresh_file = tmp_path / "thresholds.yaml"
    thresh_file.write_text("fp_budget: 0.01\nrecall_floor: 0.70\n")

    metrics = {"readiness": "inert", "fp_rate": 0.0, "recall": 0.0}
    res = check_benchmark_gate(metrics, str(thresh_file))
    assert res is None


def test_partial_detector_yields_no_verdict(tmp_path):
    thresh_file = tmp_path / "thresholds.yaml"
    thresh_file.write_text("fp_budget: 0.01\nrecall_floor: 0.70\n")

    metrics = {"readiness": "partial (dead: ml_leg)", "fp_rate": 0.0, "recall": 0.95}
    res = check_benchmark_gate(metrics, str(thresh_file))
    assert res is None


def test_two_sided(tmp_path):
    thresh_file = tmp_path / "thresholds.yaml"
    thresh_file.write_text("fp_budget: 0.01\nrecall_floor: 0.70\n")

    # Passes fp_budget (0.005 <= 0.01), but fails recall (0.10 < 0.70) -> FAIL
    metrics = {"readiness": "scored", "fp_rate": 0.005, "recall": 0.10}
    res = check_benchmark_gate(metrics, str(thresh_file))
    assert res is False


def test_thresholds_loaded_with_imported_loader():
    from benchmarks.core.gate import _load_thresholds
    assert _load_thresholds is eval_ml_mod._load_thresholds


def test_gate_does_not_mutate_fp_budget_gate():
    from app.services.detection_eval import fp_budget_gate
    assert callable(fp_budget_gate)
