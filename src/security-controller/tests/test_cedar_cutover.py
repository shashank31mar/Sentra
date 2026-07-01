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
    # WS-I I4.2: save/restore legacy_retired too, so a test that sets it True
    # (the end-state fail-secure test) cannot leak into the others.
    before = (settings.cedar_enabled, settings.cedar_shadow_mode, settings.legacy_retired)
    yield
    settings.cedar_enabled, settings.cedar_shadow_mode, settings.legacy_retired = before


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
    # WS-I I4.2: this test pins the ROLLOUT-era permissive fallback — it is only
    # correct while legacy_retired is false. Assert that precondition explicitly so
    # a flag leak can't silently turn this into the end-state behavior.
    assert settings.legacy_retired is False

    result, _signals = await svc._run_validation_pipeline(_request(), session)

    svc.cedar_engine.validate.assert_awaited_once()
    svc.policy_engine.validate.assert_awaited_once()  # fell back to legacy enforcement
    assert result.should_deny is False


@pytest.mark.asyncio
async def test_cutover_abstain_denies_when_legacy_retired():
    """WS-I I4.1 / LLD 28 §14.2 — the end state. With legacy_retired=True a Cedar
    abstain (missing .cedar co-artifact) is a defect and must fail SECURE to DENY,
    never ride the retired legacy path. Legacy engine is NOT consulted."""
    session = _session()
    svc = _pipeline_service(session)
    svc.cedar_engine = Mock()
    svc.cedar_engine.validate = AsyncMock(return_value=ValidationResult.abstain("not migrated"))
    settings.cedar_enabled = True
    settings.cedar_shadow_mode = False
    settings.legacy_retired = True            # the end state

    result, _signals = await svc._run_validation_pipeline(_request(), session)

    svc.cedar_engine.validate.assert_awaited_once()
    svc.policy_engine.validate.assert_not_called()   # legacy is RETIRED — not consulted
    assert result.should_deny is True                # fail-secure, NOT permissive
    assert result.violation_type == "POLICY_NOT_MIGRATED"


@pytest.mark.asyncio
async def test_policy_not_migrated_deny_is_audit_only_not_metered():
    """WS-I I2.4 / LLD 28 §12 — a POLICY_NOT_MIGRATED fail-secure DENY is surfaced
    to the audit log but EXCLUDED from the metered Decisions/quota series, so a
    missing-co-artifact defect cannot exhaust a victim tenant's budget. We assert
    the verdict-metering publisher is NOT called on this DENY while the audit write
    IS, and the abstain-denied ops metric fires."""
    session = _session()
    svc = _pipeline_service(session)
    svc.cedar_engine = Mock()
    svc.cedar_engine.validate = AsyncMock(return_value=ValidationResult.abstain("not migrated"))
    settings.cedar_enabled = True
    settings.cedar_shadow_mode = False
    settings.legacy_retired = True

    # Wire the telemetry surfaces the full validate path touches.
    svc.session_manager.update_trust_score_deny = AsyncMock(
        return_value={**session, "trust_score": 60.0})
    svc.audit_logger = Mock()
    svc.audit_logger.log_signals = AsyncMock()
    svc.audit_logger.log_decision = AsyncMock()
    svc.metrics_publisher = Mock()
    svc.metrics_publisher.publish_validation_metrics = AsyncMock()
    svc.metrics_publisher.publish_cedar_abstain_metric = AsyncMock()

    result = await svc.validate_tool_call(_request())
    # Let the fire-and-forget telemetry tasks run.
    import asyncio
    await asyncio.sleep(0)

    assert result["decision"] == "DENY"
    assert result["violation_type"] == "POLICY_NOT_MIGRATED"
    # Audit-only: the metered verdict series is NOT incremented for this DENY...
    svc.metrics_publisher.publish_validation_metrics.assert_not_awaited()
    # ...but the abstain-denied ops metric DID fire, and an audit record was written.
    svc.metrics_publisher.publish_cedar_abstain_metric.assert_awaited_once()
    assert (svc.audit_logger.log_signals.await_count
            + svc.audit_logger.log_decision.await_count) >= 1


@pytest.mark.asyncio
async def test_cutover_cedar_error_fails_secure():
    """WS-K K3.2 / LLD 27 — the SYSTEM-error path (distinct from the migration-gap
    path above). When Cedar is the authoritative engine and itself returns a
    fail-secure DENY (evaluator error → POLICY_ERROR), the verdict is a DENY whose
    deciding source is Cedar, NOT a legacy fallback. Guards the cutover invariant
    that an engine error denies rather than silently delegating to legacy."""
    session = _session()
    svc = _pipeline_service(session)
    svc.cedar_engine = Mock()
    # Cedar's own fail-secure DENY shape (engine.py _deny: POLICY_ERROR / -15).
    svc.cedar_engine.validate = AsyncMock(return_value=ValidationResult(
        decision="DENY", reason="Policy evaluation error", violation_type="POLICY_ERROR",
        violated_policy=None, penalty=-15, should_deny=True, source=Source.SENTRA_POLICY))
    settings.cedar_enabled = True
    settings.cedar_shadow_mode = False

    result, _signals = await svc._run_validation_pipeline(_request(), session)

    assert result.should_deny is True
    assert result.violation_type in ("POLICY_ERROR", "SYSTEM_ERROR")
    svc.cedar_engine.validate.assert_awaited_once()
    svc.policy_engine.validate.assert_not_called()   # Cedar decided; legacy not the source
