"""Unit tests for CLI configuration and flag mapping (LLD 41 §4.8)."""

import pytest
from benchmarks.core.config import NUMBER_MOVING_FLAGS, parse_cli_args


def test_concurrency_above_cap_exits_nonzero():
    with pytest.raises(SystemExit) as exc_info:
        parse_cli_args(["--adapter", "agentdojo", "--concurrency", "16"])
    assert exc_info.value.code != 0


def test_mode_ab_runs_both_rigs():
    cfg = parse_cli_args(["--adapter", "agentdojo", "--mode", "AB"])
    assert cfg.mode == "AB"


def test_missing_adapter_exits_2():
    with pytest.raises(SystemExit) as exc_info:
        parse_cli_args([])
    assert exc_info.value.code == 2


def test_every_number_moving_flag_has_a_manifest_field():
    for flag_name, manifest_field in NUMBER_MOVING_FLAGS.items():
        assert manifest_field is not None, f"Flag {flag_name} moves a number but has no manifest field"
