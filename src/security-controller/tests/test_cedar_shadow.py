"""Tests for Cedar shadow mode (CT07).

Shadow mode runs CedarPolicyEngine alongside the legacy engine and records
disagreements, but the live verdict must be byte-identical to Cedar-off. These
tests drive `ValidationService._cedar_shadow_compare` directly with a stubbed
Cedar engine + a recording metrics publisher.
"""
import pytest

from app.api.models import ValidationRequest, ValidationResult
from app.services.validation_service import ValidationService


def _request(tool_name="get_balance", tool_params=None):
    return ValidationRequest(
        request_id="req-1", session_id="sess-1", agent_id="agent-1",
        tool_name=tool_name, tool_params=tool_params or {},
        user_input="x", timestamp="2026-06-12T00:00:00Z", operation_type="WRITE")


class _FakeCedar:
    def __init__(self, result):
        self._result = result

    async def validate(self, request):
        return self._result


class _RecordingMetrics:
    def __init__(self):
        self.calls = []

    async def publish_cedar_shadow_metric(self, agreed, disagreement_kind="none"):
        self.calls.append((agreed, disagreement_kind))


@pytest.fixture
def service():
    svc = ValidationService.__new__(ValidationService)  # skip heavy __init__
    svc.metrics_publisher = _RecordingMetrics()
    return svc


@pytest.mark.asyncio
async def test_agreement_records_no_discrepancy(service):
    live = ValidationResult(decision="ALLOW", reason="ok", should_deny=False)
    service.cedar_engine = _FakeCedar(ValidationResult(decision="ALLOW", reason="ok", should_deny=False))
    await service._cedar_shadow_compare(_request(), live)
    assert service.metrics_publisher.calls == [(True, "none")]


@pytest.mark.asyncio
async def test_verdict_disagreement_recorded_but_live_untouched(service):
    # Cedar DENY on an engine ALLOW — recorded, not blocked.
    live = ValidationResult(decision="ALLOW", reason="ok", should_deny=False)
    before = live.model_dump()
    service.cedar_engine = _FakeCedar(
        ValidationResult(decision="DENY", reason="nope", violation_type="UNAUTHORIZED_TOOL",
                         penalty=-15, should_deny=True))
    await service._cedar_shadow_compare(_request(), live)
    assert service.metrics_publisher.calls == [(False, "verdict")]
    # Live result is byte-identical — shadow never mutates it.
    assert live.model_dump() == before


@pytest.mark.asyncio
async def test_violation_type_disagreement_recorded(service):
    live = ValidationResult(decision="DENY", reason="x", violation_type="UNAUTHORIZED_TOOL",
                            penalty=-15, should_deny=True)
    service.cedar_engine = _FakeCedar(
        ValidationResult(decision="DENY", reason="x", violation_type="UNAUTHORIZED_AGENT_INVOCATION",
                         penalty=-15, should_deny=True))
    await service._cedar_shadow_compare(_request("invoke_agent"), live)
    assert service.metrics_publisher.calls == [(False, "violation_type")]


@pytest.mark.asyncio
async def test_abstain_not_counted_as_disagreement(service):
    live = ValidationResult(decision="ALLOW", reason="ok", should_deny=False)
    service.cedar_engine = _FakeCedar(ValidationResult.abstain("not migrated"))
    await service._cedar_shadow_compare(_request(), live)
    assert service.metrics_publisher.calls == [(True, "cedar_abstain")]


@pytest.mark.asyncio
async def test_cedar_error_classified(service):
    live = ValidationResult(decision="ALLOW", reason="ok", should_deny=False)
    service.cedar_engine = _FakeCedar(
        ValidationResult(decision="DENY", reason="err", violation_type="POLICY_ERROR",
                         penalty=-15, should_deny=True))
    await service._cedar_shadow_compare(_request(), live)
    assert service.metrics_publisher.calls == [(False, "cedar_error")]


@pytest.mark.asyncio
async def test_shadow_never_raises(service):
    class _Boom:
        async def validate(self, request):
            raise RuntimeError("boom")

    live = ValidationResult(decision="ALLOW", reason="ok", should_deny=False)
    service.cedar_engine = _Boom()
    # Must not raise; no metric recorded for the crash path beyond the swallow.
    await service._cedar_shadow_compare(_request(), live)
    assert live.decision == "ALLOW"
