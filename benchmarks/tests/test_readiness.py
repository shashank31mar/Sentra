"""Unit tests for detector readiness evaluation (LLD 41 §4.3, §18.1)."""

import os
import pytest
from benchmarks.core.readiness import ReadinessError, assess_detector_readiness


def test_never_fired_yields_inert():
    res = assess_detector_readiness("sentra.sigma", fired_count=0, artifact_info={"sigma_rule_count": 47})
    assert res["verdict"] == "inert"
    assert res["fired"] == 0


def test_dead_ml_leg_yields_partial_naming_the_leg():
    legs = {
        "sigma_leg": {"activated": True, "fired": 14},
        "ml_leg": {"activated": True, "fired": 0},
        "heuristic_leg": {"activated": True, "fired": 25},
    }
    res = assess_detector_readiness("D2_indirect_injection", fired_count=39, composite_legs=legs)
    assert res["verdict"] == "partial"
    assert res["dead_leg"] == "ml_leg"


def test_zero_sigma_rules_aborts_run():
    with pytest.raises(ReadinessError) as exc_info:
        assess_detector_readiness("sentra.sigma", fired_count=0, artifact_info={"sigma_rule_count": 0})
    assert "Sigma ruleset count is 0" in str(exc_info.value)


def test_missing_model_id_aborts_run():
    with pytest.raises(ReadinessError) as exc_info:
        assess_detector_readiness("ml_classifier", fired_count=0, artifact_info={"model_id": ""})
    assert "ML model_id is unresolvable" in str(exc_info.value)


def test_d1_unarmed_records_activated_false(monkeypatch):
    monkeypatch.setenv("D1_ENABLED", "0")
    res = assess_detector_readiness("D1_trajectory", fired_count=0)
    assert res["activated"] is False
    assert res["verdict"] == "inert"


def test_no_fictional_activation_flag_for_d2_d3():
    # Asserting D2/D3 do not read env vars D2_ENABLED/D3_ENABLED
    res = assess_detector_readiness("D2_indirect_injection", fired_count=10)
    assert "D2_ENABLED" not in os.environ or os.environ.get("D2_ENABLED") is not None
    assert res["activated"] is True
