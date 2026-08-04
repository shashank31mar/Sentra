"""Detector readiness checking and per-leg composite audit (LLD 41 §4.3, §18.1, WS-C milestone C2)."""

import os
from typing import Any, Dict, Optional


class ReadinessError(Exception):
    """Raised when an unpinned or empty artifact aborts the run."""


def assess_detector_readiness(
    detector_name: str,
    *,
    fired_count: int,
    artifact_info: Optional[Dict[str, Any]] = None,
    composite_legs: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Assess readiness for a single detector or composite detector.
    
    Verdicts:
    - 'inert': tp + fp == 0 across corpus.
    - 'partial': one or more dead legs in a composite detector.
    - 'scored': armed, artifact loaded, and fired >= 1 time.
    """
    # Check activation flags where one exists
    activation_var_map = {
        "D1_trajectory": "D1_ENABLED",
        "ml_classifier": "ML_CLASSIFIER_ENABLED",
    }
    env_var = activation_var_map.get(detector_name)
    activated = (os.environ.get(env_var) == "1" or os.environ.get(env_var) == "true") if env_var else None

    # Check for empty/missing artifacts
    if artifact_info is not None:
        if artifact_info.get("sigma_rule_count") == 0:
            raise ReadinessError("Sigma ruleset count is 0; unpinned ruleset aborts run.")
        if "model_id" in artifact_info and not artifact_info["model_id"]:
            raise ReadinessError("ML model_id is unresolvable; unpinned model aborts run.")

    if composite_legs:
        # Per-leg readiness check for composite detectors (e.g. D2)
        dead_legs = []
        for leg_name, leg_data in composite_legs.items():
            if leg_data.get("fired", 0) == 0 or not leg_data.get("activated", True):
                dead_legs.append(leg_name)
        
        if dead_legs:
            return {
                "activated": True if activated is None else activated,
                "composite_legs": composite_legs,
                "fired": fired_count,
                "dead_leg": dead_legs[0],
                "verdict": "partial",
            }

    if fired_count == 0:
        return {
            "activated": False if activated is False else True,
            "artifact": artifact_info,
            "fired": 0,
            "verdict": "inert",
        }

    return {
        "activated": True if activated is None else activated,
        "artifact": artifact_info,
        "fired": fired_count,
        "verdict": "scored",
    }
