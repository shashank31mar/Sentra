"""Unit tests for MLClassifierValidator — LLD 19 §12.1 (T-ML-01..10).

Bedrock is fully mocked. These tests exercise the validator's control flow:
tier selection, budget enforcement, ABSTAIN paths, and signal stamping. The
integration tests (test_ml_classifier_bedrock.py, gated on RUN_INTEGRATION=1)
cover the real-Bedrock behaviors.

Design: every test wires its own MagicMock bedrock_client through the
MLClassifierValidator constructor, so tests are hermetic and parallel-safe.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from app.api.models import ValidationRequest, ValidationResult
from app.combiners import Source
from app.config import settings
from app.validators.ml_classifier import MLClassifierValidator
from app.validators.ml_classifier_schema import TOOL_NAME


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


@pytest.fixture(autouse=True)
def enable_ml_classifier(monkeypatch):
    """All tests in this module run with the flag ON unless they assert otherwise.
    The disabled-flag test (T-ML-01) explicitly flips it back off."""
    monkeypatch.setattr(settings, "ml_classifier_enabled", True)
    # Keep test runtime fast — the validator's defaults (2s per tier, 2.5s total)
    # are production-realistic but slow for unit tests.
    monkeypatch.setattr(settings, "ml_classifier_timeout_seconds", 1.0)
    monkeypatch.setattr(settings, "ml_classifier_total_budget_seconds", 2.0)
    monkeypatch.setattr(settings, "ml_classifier_inference_profile_arn", "")
    monkeypatch.setattr(
        settings, "ml_classifier_hot_model_id", "anthropic.claude-haiku-4-5-20251001-v1:0"
    )
    monkeypatch.setattr(
        settings, "ml_classifier_escalation_model_id", "us.anthropic.claude-sonnet-4-6"
    )


@pytest.fixture
def request_obj():
    return ValidationRequest(
        request_id="req-test-1",
        session_id="sess-test-1",
        agent_id="customer-query-agent",
        tool_name="query_customers",
        tool_params={"state": "CA"},
        user_input="Show me customers in California",
        timestamp="2026-05-28T10:00:00Z",
        operation_type="READ",
    )


def _converse_response(decision: str, threat_type: str, confidence: float, reason: str) -> dict:
    """Build a Converse API response that calls emit_security_verdict."""
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "toolUse": {
                            "toolUseId": "mock-tool-use-1",
                            "name": TOOL_NAME,
                            "input": {
                                "decision": decision,
                                "threat_type": threat_type,
                                "confidence": confidence,
                                "reason": reason,
                            },
                        }
                    }
                ],
            }
        },
        "stopReason": "tool_use",
    }


def _make_validator(bedrock_mock: MagicMock) -> MLClassifierValidator:
    return MLClassifierValidator(bedrock_client=bedrock_mock)


# ----------------------------------------------------------------------
# T-ML-01 — feature flag off
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t_ml_01_flag_off_returns_abstain(monkeypatch, request_obj):
    monkeypatch.setattr(settings, "ml_classifier_enabled", False)
    bedrock = MagicMock()
    validator = _make_validator(bedrock)

    result = await validator.validate(request_obj)

    assert result.is_abstain
    assert "disabled" in result.reason
    bedrock.converse.assert_not_called()  # no Bedrock cost when flag is off


# ----------------------------------------------------------------------
# T-ML-02 — confident hot path
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t_ml_02_hot_path_high_confidence_returns_haiku_verdict(request_obj):
    bedrock = MagicMock()
    bedrock.converse.return_value = _converse_response(
        decision="ALLOW", threat_type="NONE", confidence=0.95,
        reason="Scoped state-filtered query.",
    )
    validator = _make_validator(bedrock)

    result = await validator.validate(request_obj)

    assert result.decision == "ALLOW"
    assert result.confidence == pytest.approx(0.95)
    assert result.metadata["model_used"] == "hot"
    assert result.source == Source.SENTRA_ML_CLASSIFIER  # @stamps applied
    assert bedrock.converse.call_count == 1  # no escalation


# ----------------------------------------------------------------------
# T-ML-03 — escalation on borderline confidence
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t_ml_03_borderline_confidence_escalates(request_obj):
    bedrock = MagicMock()
    bedrock.converse.side_effect = [
        _converse_response("ALLOW", "NONE", 0.65, "Plausible but borderline."),  # hot
        _converse_response("DENY", "DATA_THEFT", 0.94, "Bulk enumeration."),     # escalation
    ]
    validator = _make_validator(bedrock)

    result = await validator.validate(request_obj)

    assert result.decision == "DENY"
    assert result.threat_type == "DATA_THEFT"
    assert result.metadata["model_used"] == "escalated"
    assert bedrock.converse.call_count == 2

    # Hot call used Haiku, escalation used Sonnet
    hot_call_args = bedrock.converse.call_args_list[0].kwargs
    esc_call_args = bedrock.converse.call_args_list[1].kwargs
    assert "haiku" in hot_call_args["modelId"]
    assert "sonnet" in esc_call_args["modelId"]


# ----------------------------------------------------------------------
# T-ML-04 — both tiers low confidence -> ABSTAIN
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t_ml_04_both_tiers_low_confidence_abstains(request_obj):
    bedrock = MagicMock()
    bedrock.converse.side_effect = [
        _converse_response("ALLOW", "NONE", 0.35, "Cannot tell."),  # hot — below abstain threshold
        _converse_response("ALLOW", "NONE", 0.40, "Still unclear."),  # escalation — still low
    ]
    validator = _make_validator(bedrock)

    result = await validator.validate(request_obj)

    assert result.is_abstain
    assert "low confidence" in result.reason


# ----------------------------------------------------------------------
# T-ML-05 — hot path timeout -> escalation
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t_ml_05_hot_timeout_pivots_to_escalation(request_obj, monkeypatch):
    # Tight timeout so we can simulate a slow Bedrock call without a long test.
    monkeypatch.setattr(settings, "ml_classifier_timeout_seconds", 0.2)
    monkeypatch.setattr(settings, "ml_classifier_total_budget_seconds", 2.0)

    bedrock = MagicMock()

    def slow_then_fast(**kwargs):
        # First call (hot) sleeps past the timeout; second (escalation) returns fast.
        if bedrock.converse.call_count == 1:
            import time as _t
            _t.sleep(1.0)  # exceeds 0.2s per-tier cap
            return _converse_response("ALLOW", "NONE", 0.9, "Should not be reached.")
        return _converse_response("DENY", "PROMPT_INJECTION", 0.96, "Override attempt.")

    bedrock.converse.side_effect = slow_then_fast
    validator = _make_validator(bedrock)

    result = await validator.validate(request_obj)

    assert result.decision == "DENY"
    assert result.metadata["model_used"] == "escalation_only"
    assert bedrock.converse.call_count == 2


# ----------------------------------------------------------------------
# T-ML-06 — hot 5xx -> escalation
# ----------------------------------------------------------------------


def _client_error(http_status: int, code: str = "InternalServerException") -> ClientError:
    return ClientError(
        error_response={
            "Error": {"Code": code, "Message": "mock"},
            "ResponseMetadata": {"HTTPStatusCode": http_status},
        },
        operation_name="Converse",
    )


@pytest.mark.asyncio
async def test_t_ml_06_hot_5xx_pivots_to_escalation(request_obj):
    bedrock = MagicMock()
    bedrock.converse.side_effect = [
        _client_error(503),  # hot
        _converse_response("ALLOW", "NONE", 0.92, "Benign on retry."),  # escalation
    ]
    validator = _make_validator(bedrock)

    result = await validator.validate(request_obj)

    assert result.decision == "ALLOW"
    assert result.metadata["model_used"] == "escalation_only"


# ----------------------------------------------------------------------
# T-ML-07 — hot 4xx -> CRITICAL log + ABSTAIN (escalation also unavailable)
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t_ml_07_hot_4xx_logs_critical_and_abstains(request_obj, caplog):
    bedrock = MagicMock()
    # Both tiers 4xx (e.g. quota exhausted on both) -> final result is ABSTAIN.
    bedrock.converse.side_effect = [
        _client_error(429, code="ThrottlingException"),
        _client_error(429, code="ThrottlingException"),
    ]
    validator = _make_validator(bedrock)

    with caplog.at_level(logging.CRITICAL, logger="app.validators.ml_classifier"):
        result = await validator.validate(request_obj)

    assert result.is_abstain
    critical_records = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert critical_records, "expected at least one CRITICAL log for 4xx"


# ----------------------------------------------------------------------
# T-ML-08 — parse failure (no tool call) -> ABSTAIN
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t_ml_08_no_tool_use_block_abstains(request_obj):
    bedrock = MagicMock()
    # Model replied in free text despite forced toolChoice — shouldn't happen
    # with Bedrock + tool-use, but defend against it. Both tiers do the same
    # broken thing → final result is ABSTAIN.
    broken_response = {
        "output": {"message": {"role": "assistant", "content": [{"text": "i refuse"}]}},
        "stopReason": "end_turn",
    }
    bedrock.converse.return_value = broken_response
    validator = _make_validator(bedrock)

    result = await validator.validate(request_obj)

    assert result.is_abstain


# ----------------------------------------------------------------------
# T-ML-09 — emitted Signal has correct source/decision/threat_type/confidence
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t_ml_09_signal_round_trip(request_obj):
    bedrock = MagicMock()
    bedrock.converse.return_value = _converse_response(
        decision="DENY", threat_type="PII_EXPOSURE", confidence=0.95,
        reason="Bulk SSN selection without scope.",
    )
    validator = _make_validator(bedrock)

    result = await validator.validate(request_obj)
    signal = result.to_signal()

    assert signal is not None
    assert signal.source == Source.SENTRA_ML_CLASSIFIER
    assert signal.decision == "DENY"
    assert signal.threat_type == "PII_EXPOSURE"
    assert signal.confidence == pytest.approx(0.95)
    assert signal.metadata["model_used"] == "hot"
    assert "model_id" in signal.metadata


@pytest.mark.asyncio
async def test_t_ml_09b_abstain_yields_no_signal(monkeypatch, request_obj):
    monkeypatch.setattr(settings, "ml_classifier_enabled", False)
    validator = _make_validator(MagicMock())

    result = await validator.validate(request_obj)

    assert result.is_abstain
    assert result.to_signal() is None  # LLD 17 §4 absence semantics


# ----------------------------------------------------------------------
# T-ML-10 — total-budget enforcement (LLD 19 v0.2 §3.2.1)
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t_ml_10_total_budget_caps_combined_tier_time(request_obj, monkeypatch):
    """Hot path consumes most of the budget; escalation must run under the
    remaining slice, not the full per-tier timeout."""
    monkeypatch.setattr(settings, "ml_classifier_timeout_seconds", 1.0)
    monkeypatch.setattr(settings, "ml_classifier_total_budget_seconds", 1.2)

    bedrock = MagicMock()

    def consume_then_return(**kwargs):
        # Hot path: borderline confidence -> escalation needed.
        if bedrock.converse.call_count == 1:
            import time as _t
            _t.sleep(0.9)  # consume most of the 1.2s budget
            return _converse_response("ALLOW", "NONE", 0.6, "borderline")
        # Escalation should be invoked with a shrunken timeout, but for this
        # test we let it return immediately and inspect that it was called.
        return _converse_response("DENY", "DATA_THEFT", 0.95, "esc")

    bedrock.converse.side_effect = consume_then_return
    validator = _make_validator(bedrock)

    result = await validator.validate(request_obj)

    # Escalation should have been called — but the per-call timeout passed in
    # should be the remaining budget (~0.3s), NOT the full 1.0s per-tier cap.
    # We can't inspect the timeout directly (it's inside asyncio.wait_for), so
    # we verify the result reflects escalation completing.
    assert bedrock.converse.call_count == 2
    assert result.decision == "DENY"
    assert result.metadata["model_used"] == "escalated"


# ----------------------------------------------------------------------
# Few-shot structural invariant — every toolUse must have a matching
# toolResult with the SAME toolUseId in the next user turn. Bedrock
# Converse rejects mismatched ids with ValidationException. Unit-mocked
# tests can't catch this (the mock never sends the conversation over the
# wire); this test enforces the invariant at module-load time so a
# regression here is caught before any real Bedrock call.
# ----------------------------------------------------------------------


def test_few_shot_tool_use_ids_pair_with_tool_results():
    from app.validators.ml_classifier_prompts import FEW_SHOTS

    seen_tool_use_ids: list[str] = []
    for msg in FEW_SHOTS:
        role = msg["role"]
        for block in msg["content"]:
            tu = block.get("toolUse") if isinstance(block, dict) else None
            tr = block.get("toolResult") if isinstance(block, dict) else None
            if tu:
                assert role == "assistant", "toolUse must be in an assistant turn"
                seen_tool_use_ids.append(tu["toolUseId"])
            if tr:
                assert role == "user", "toolResult must be in a user turn"
                # Must reference the immediately-prior toolUse id.
                assert seen_tool_use_ids, "toolResult with no prior toolUse"
                assert tr["toolUseId"] == seen_tool_use_ids[-1], (
                    f"toolResult.toolUseId={tr['toolUseId']!r} does not match "
                    f"prior toolUse.toolUseId={seen_tool_use_ids[-1]!r} — "
                    "Bedrock Converse will reject with ValidationException"
                )

    # All ids must be unique across the whole conversation (Bedrock requirement).
    assert len(seen_tool_use_ids) == len(set(seen_tool_use_ids)), (
        f"duplicate toolUseIds in FEW_SHOTS: {seen_tool_use_ids}"
    )


@pytest.mark.asyncio
async def test_t_ml_10b_budget_exhausted_returns_hot_low_conf(request_obj, monkeypatch):
    """When hot finishes with low-but-above-abstain confidence AND the total
    budget is already exhausted, the validator returns the Haiku verdict
    flagged as hot_only_budget_exhausted rather than burning further on a
    doomed escalation."""
    monkeypatch.setattr(settings, "ml_classifier_timeout_seconds", 1.0)
    monkeypatch.setattr(settings, "ml_classifier_total_budget_seconds", 0.5)

    bedrock = MagicMock()

    def slow_hot(**kwargs):
        import time as _t
        _t.sleep(0.45)  # consume nearly all the 0.5s budget
        return _converse_response("ALLOW", "NONE", 0.7, "borderline but ran out of time")

    bedrock.converse.side_effect = slow_hot
    validator = _make_validator(bedrock)

    result = await validator.validate(request_obj)

    assert result.decision == "ALLOW"
    assert result.metadata["model_used"] == "hot_only_budget_exhausted"
    assert bedrock.converse.call_count == 1  # no escalation attempted
