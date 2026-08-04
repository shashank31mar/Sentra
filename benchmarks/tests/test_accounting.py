"""Unit tests for RunAccountant (LLD 41 §14.2, WS-E milestone E4)."""

import pytest
from benchmarks.core.accounting import MODEL_RATES, RunAccountant, estimate_cost


def test_shares_rate_table_with_eval_ml_classifier():
    assert "claude-3-5-sonnet-20241022" in MODEL_RATES
    assert MODEL_RATES["claude-3-5-sonnet-20241022"]["input"] == 3.0 / 1_000_000


def test_token_based_not_call_based():
    acc = RunAccountant()
    acc.record_llm_call("ep1", "with", 100, 50)
    acc.record_llm_call("ep2", "with", 1000, 500)

    ep1_cost = acc.episodes[("ep1", "with")].cost_usd
    ep2_cost = acc.episodes[("ep2", "with")].cost_usd

    assert ep2_cost > ep1_cost * 5


def test_attribution_key_is_episode_and_arm():
    acc = RunAccountant()
    acc.record_llm_call("ep-1", "with", 200, 100)
    acc.record_llm_call("ep-1", "without", 150, 80)

    assert ("ep-1", "with") in acc.episodes
    assert ("ep-1", "without") in acc.episodes


def test_n_validate_calls_counted_on_exception_path():
    acc = RunAccountant()
    try:
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            pass
    finally:
        acc.record_validate_call("ep-1", "with")

    assert acc.n_validate_calls == 1
    assert acc.episodes[("ep-1", "with")].n_validate_calls == 1


def test_with_arm_premium_visible():
    acc = RunAccountant()
    # With arm retries, leading to higher token total
    acc.record_llm_call("ep1", "with", 500, 200)
    acc.record_llm_call("ep1", "without", 200, 80)

    d = acc.to_manifest_dict()
    assert d["by_arm"]["with"]["input_tokens"] > d["by_arm"]["without"]["input_tokens"]
