"""Unit tests for report ordering and formatting (LLD 41 §7.3)."""

from benchmarks.core.report import INTERSTITIAL_SENTENCE, generate_report


def test_fixed_section_order():
    manifest_data = {
        "benchmark": {"dirty": False, "suites": ["all"]},
        "results": {
            "mode_b": {"asr_with": 10.0, "asr_without": 40.0, "asr_reduction_pp": 30.0},
            "mode_a": {
                "d1": {"readiness": "scored", "recall": 0.85, "precision": 0.9, "f1": 0.87, "fp_budget_gate": "PASS"}
            },
        },
        "errors": [],
    }
    report = generate_report(manifest_data, rows=[])

    s1_idx = report.find("## 1. Disclosures")
    s2_idx = report.find("## 2. Mode B")
    sentence_idx = report.find(INTERSTITIAL_SENTENCE)
    s3_idx = report.find("## 3. Mode A")
    s4_idx = report.find("## 4. Errors & Exclusions")

    assert s1_idx != -1
    assert s2_idx > s1_idx
    assert sentence_idx > s2_idx
    assert s3_idx > sentence_idx
    assert s4_idx > s3_idx


def test_interstitial_sentence_present_and_between():
    manifest_data = {
        "benchmark": {},
        "results": {
            "mode_b": {"asr_with": 5.0},
            "mode_a": {"d1": {"readiness": "scored", "recall": 0.9}},
        },
    }
    report = generate_report(manifest_data, rows=[])
    assert INTERSTITIAL_SENTENCE in report


def test_inert_detector_prints_no_metrics():
    manifest_data = {
        "benchmark": {},
        "results": {
            "mode_a": {
                "d3": {"readiness": "inert"}
            }
        },
    }
    report = generate_report(manifest_data, rows=[])
    assert "Detector: d3" in report
    assert "`inert`" in report
    assert "Recall" not in report


def test_partial_detector_names_the_dead_leg():
    manifest_data = {
        "benchmark": {},
        "results": {
            "mode_a": {
                "d2": {"readiness": "partial", "dead_leg": "ml_leg"}
            }
        },
    }
    report = generate_report(manifest_data, rows=[])
    assert "Detector: d2" in report
    assert "`partial`" in report
    assert "ml_leg" in report


def test_recall_adjacent_to_every_gate_verdict():
    manifest_data = {
        "benchmark": {},
        "results": {
            "mode_a": {
                "d1": {"readiness": "scored", "recall": 0.88, "precision": 0.9, "f1": 0.89, "fp_budget_gate": "PASS"}
            }
        },
    }
    report = generate_report(manifest_data, rows=[])
    assert "- **fp_budget_gate verdict**: PASS (recall: 0.880)" in report


def test_subset_corpus_prints_not_comparable_banner():
    manifest_data = {
        "benchmark": {"suites": ["banking"]},
        "results": {},
    }
    report = generate_report(manifest_data, rows=[])
    assert "single-suite inner loop — not comparable to a full-suite headline" in report
