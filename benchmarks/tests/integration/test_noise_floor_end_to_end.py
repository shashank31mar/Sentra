"""Integration test for noise floor gating diff.py (LLD 41 §7.1.1, WS-E milestone E5)."""

import pytest
from benchmarks.core.diff import compare_manifests
from benchmarks.core.manifest import Manifest
from benchmarks.core.noise_floor import calculate_noise_floor


def test_noise_floor_end_to_end():
    nf = calculate_noise_floor([30.0, 32.0, 33.5], method="paired")
    assert nf["noise_floor_pp"] == 3.5

    m1_dict = {
        "schema_version": "1",
        "exit": "complete",
        "benchmark": {"adapter": "agentdojo"},
        "results": {
            "mode_b": {
                "arms": {
                    "P1": {
                        "asr_reduction_pp": 30.0,
                    }
                },
                "noise_floor": nf,
            }
        },
    }
    m2_dict = {
        "schema_version": "1",
        "exit": "complete",
        "benchmark": {"adapter": "agentdojo"},
        "results": {
            "mode_b": {
                "arms": {
                    "P1": {
                        "asr_reduction_pp": 32.0,
                    }
                },
                "noise_floor": nf,
            }
        },
    }

    diff = compare_manifests(m2_dict, [], m1_dict, [], noise_floor_pp=3.5)
    # Difference is 2.0 pp, which is below noise floor of 3.5 pp
    assert diff.aggregate_verdict == "within-noise"
