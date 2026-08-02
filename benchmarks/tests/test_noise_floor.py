"""Unit tests for noise floor calculation (LLD 41 §7.1.1, WS-E milestone E5)."""

import pytest
from benchmarks.core.noise_floor import calculate_noise_floor


def test_single_replicate_pair_raises():
    with pytest.raises(ValueError) as exc_info:
        calculate_noise_floor([30.0], method="paired")
    assert "requires >= 2 replicate pairs" in str(exc_info.value)


def test_max_abs_pairwise_difference():
    res = calculate_noise_floor([30.0, 32.0, 33.5], method="paired")
    assert res["n_replicates"] == 3
    assert res["noise_floor_pp"] == 3.5
    assert res["method"] == "paired"


def test_single_arm_method_applies_sqrt2():
    res = calculate_noise_floor([10.0, 12.0], method="single_arm_x_sqrt2")
    # spread = 2.0; 2.0 * sqrt(2) = 2.8284 -> 2.83
    assert res["noise_floor_pp"] == 2.83
    assert res["independence_assumption"] is not None


def test_paired_method_takes_reduction_spread_directly():
    res = calculate_noise_floor([15.0, 18.0], method="paired")
    assert res["noise_floor_pp"] == 3.0
    assert res["independence_assumption"] is None


def test_manifest_records_n_replicates_and_method():
    res = calculate_noise_floor([5.0, 6.0, 5.5], method="paired")
    assert "n_replicates" in res
    assert "method" in res
    assert "noise_floor_pp" in res
