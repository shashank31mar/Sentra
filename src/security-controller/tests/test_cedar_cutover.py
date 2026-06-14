"""Cutover engine-selection tests (CT10).

Verifies STEP 2 picks the authoritative policy engine by flag:
  * cedar_enabled & NOT shadow → CedarPolicyEngine is the decision (legacy not called).
  * cedar_enabled & shadow      → legacy decides; Cedar runs alongside (CT07).
  * cedar disabled              → legacy decides; Cedar never constructed/called.
Plus the abstain fallback: a not-migrated agent under cutover falls back to legacy.
"""
from unittest.mock import AsyncMock, Mock

import pytest

from app.api.models import ValidationRequest, ValidationResult
from app.combiners import Source
from app.config import settings
from tests.test_validation_service import _pipeline_service


def _session():
    return {
        "session_id": "sess-123", "user_id": "user-456", "agent_id": "test-agent",
        "trust_score": 75.0, "created_at": "2025-11-19T10:00:00Z",
        "last_activity": "2025-11-19T10:00:00Z", "action_count": 5,
    }


def _request():
    return ValidationRequest(
        request_id="req", session_id="sess-123", agent_id="test-agent", tool_name="process_refund",
        tool_params={"amount": 9000}, user_input="x", timestamp="2026-06-12T00:00:00Z",
        operation_type="WRITE")


def _deny(source):
    return ValidationResult(decision="DENY", reason="cedar deny", violation_type="POLICY_VIOLATION",
                            violated_policy="max_refund_amount", penalty=-10, should_deny=True, source=source)


@pytest.fixture(autouse=True)
def _reset_flags():
    before = (settings.cedar_enabled, settings.cedar_shadow_mode)
    yield
    settings.cedar_enabled, settings.cedar_shadow_mode = before


@pytest.mark.asyncio
async def test_cutover_uses_cedar_legacy_not_called():
    session = _session()
    svc = _pipeline_service(session)
    svc.cedar_engine = Mock()
    svc.cedar_engine.validate = AsyncMock(return_value=_deny(Source.SENTRA_POLICY))
    settings.cedar_enabled = True
    settings.cedar_shadow_mode = False

    result, _signals = await svc._run_validation_pipeline(_request(), session)

    assert result.should_deny is True
    assert result.violated_policy == "max_refund_amount"
    svc.cedar_engine.validate.assert_awaited_once()
    svc.policy_engine.validate.assert_not_called()


@pytest.mark.asyncio
async def test_shadow_uses_legacy_and_compares():
    session = _session()
    svc = _pipeline_service(session)
    svc.cedar_engine = Mock()
    svc.cedar_engine.validate = AsyncMock(return_value=_deny(Source.SENTRA_POLICY))
    svc.metrics_publisher = Mock()
    svc.metrics_publisher.publish_cedar_shadow_metric = AsyncMock()
    settings.cedar_enabled = True
    settings.cedar_shadow_mode = True

    # legacy ALLOWs (default mock); cedar DENYs → shadow records a verdict diff,
    # but the live result is the legacy ALLOW (pipeline proceeds to full ALLOW).
    result, _signals = await svc._run_validation_pipeline(_request(), session)

    svc.policy_engine.validate.assert_awaited_once()
    svc.metrics_publisher.publish_cedar_shadow_metric.assert_awaited()
    assert result.should_deny is False  # legacy verdict is live, not Cedar's DENY


@pytest.mark.asyncio
async def test_disabled_never_calls_cedar():
    session = _session()
    svc = _pipeline_service(session)  # no cedar_engine attribute set
    settings.cedar_enabled = False
    settings.cedar_shadow_mode = False

    result, _signals = await svc._run_validation_pipeline(_request(), session)
    svc.policy_engine.validate.assert_awaited_once()
    assert result.should_deny is False


@pytest.mark.asyncio
async def test_cutover_abstain_falls_back_to_legacy():
    session = _session()
    svc = _pipeline_service(session)
    svc.cedar_engine = Mock()
    svc.cedar_engine.validate = AsyncMock(return_value=ValidationResult.abstain("not migrated"))
    settings.cedar_enabled = True
    settings.cedar_shadow_mode = False

    result, _signals = await svc._run_validation_pipeline(_request(), session)

    svc.cedar_engine.validate.assert_awaited_once()
    svc.policy_engine.validate.assert_awaited_once()  # fell back to legacy enforcement
    assert result.should_deny is False
