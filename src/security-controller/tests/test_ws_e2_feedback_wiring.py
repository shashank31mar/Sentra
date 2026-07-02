"""WS-E2 — the feedback WIRING seam: `validate_tool_call` → `_handle_deny`/
`_handle_allow` → `_fire_and_forget(write_redacted_feedback(...))` (R2-M1 / LLD 29 §6.5).

REGRESSION (integration-sentinel MEDIUM — a real test gap): `write_redacted_feedback`
itself is covered directly (test_write_redacted_feedback.py) and the store below it is
covered (test_feedback_store.py), but NOTHING drove `service.validate_tool_call` on a
CONTENT phase to prove the two call-site lines in `_handle_deny` (validation_service.py
:689) and `_handle_allow` (:755) actually FIRE end-to-end. Every existing
`validate_tool_call` test uses the default `request` phase, where the wrapper
early-returns at the phase gate — so a coder could DELETE both `_fire_and_forget(
write_redacted_feedback(...))` lines and the whole suite would stay green.

These tests close that gap. The positive cases drive the ALLOW and DENY paths on a
content phase for an OPTED-IN tenant and assert the wrapper is invoked (spy) AND a
redacted record lands in the moto feedback table (end-to-end). The negative cases
(request phase; non-opted-in tenant) assert NO write fires. Deleting either call-site
line makes `test_content_phase_allow_fires_feedback_write` /
`test_content_phase_deny_fires_feedback_write` FAIL (the spy is never called, and the
table stays empty) — the mutation this test exists to catch.
"""
from __future__ import annotations

import asyncio

import boto3
import pytest
from moto import mock_aws
from unittest.mock import AsyncMock, Mock, patch

from app.api.models import ValidationRequest, ValidationResult
from app.config import settings
from app.redaction.feedback_store import SUBJECT_LOCATOR_GSI
from app.utils import tenancy


TABLE = "sentra-redacted-feedback"
_TENANT = "t_wiring"


async def _drain_bg():
    """WS24 M4.2: the feedback write (like audit + metrics) is emitted off the response
    path via `_fire_and_forget`. Await pending background tasks so the wiring assertion
    is deterministic (mirrors test_validation_service._drain_bg)."""
    import app.services.validation_service as _vs
    pending = list(_vs._bg_tasks)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


@pytest.fixture
def feedback_env(monkeypatch):
    """A moto feedback table + a resolved tenant contextvar, so the wrapper's
    `tenancy.current_tenant()` returns a real tenant (mirrors
    test_write_redacted_feedback.feedback_env)."""
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(k, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", settings.aws_region)
    monkeypatch.setattr(settings, "dynamodb_feedback_store_table", TABLE)
    monkeypatch.setattr(settings, "feedback_subject_locator_salt", "unit-test-salt")
    import app.redaction.feedback_store as fs
    monkeypatch.setattr(fs, "_feedback_store", None)
    token = tenancy.set_current_tenant(_TENANT)
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name=settings.aws_region)
        ddb.create_table(
            TableName=TABLE,
            KeySchema=[
                {"AttributeName": "tenant_id", "KeyType": "HASH"},
                {"AttributeName": "record_id", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "tenant_id", "AttributeType": "S"},
                {"AttributeName": "record_id", "AttributeType": "S"},
                {"AttributeName": "subject_locator", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": SUBJECT_LOCATOR_GSI,
                    "KeySchema": [{"AttributeName": "subject_locator", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield ddb
    tenancy.reset_current_tenant(token)


_SESSION = {
    "session_id": "sess-wire",
    "user_id": "unknown",
    "agent_id": "a-wire",
    "trust_score": 80.0,
    "created_at": "2026-07-02T00:00:00Z",
    "last_activity": "2026-07-02T00:00:00Z",
    "action_count": 1,
}


def _service(*, deny: bool = False):
    """A ValidationService whose whole pipeline is mocked (ALLOW, or a trust-checker
    short-circuit DENY) plus the audit/metrics deps `_handle_*` touch off-path. The
    feedback wiring is the ONLY thing under test — everything else is stubbed so the
    call-site line is what decides whether a record is written."""
    from app.services.validation_service import ValidationService

    with patch.object(ValidationService, "__init__", lambda self: None):
        service = ValidationService()

    service.session_manager = Mock()
    service.session_manager.get_or_create_session = AsyncMock(return_value=dict(_SESSION))
    service.session_manager.update_trust_score_allow = AsyncMock(return_value=dict(_SESSION))
    service.session_manager.update_trust_score_deny = AsyncMock(
        return_value={**_SESSION, "trust_score": 40.0})

    verdict = ValidationResult(
        decision="DENY" if deny else "ALLOW",
        reason="Trust score too low" if deny else "OK",
        should_deny=deny,
        violation_type="LOW_TRUST" if deny else None,
    )
    service.trust_checker = Mock()
    service.trust_checker.check = AsyncMock(return_value=verdict)

    service.policy_engine = Mock()
    service.policy_engine.validate = AsyncMock(return_value=ValidationResult(
        decision="ALLOW", reason="OK", should_deny=False))
    service.policy_engine.get_agent_policy = AsyncMock(return_value={"rate_limit": 100})

    service.cross_agent_validator = Mock()
    service.cross_agent_validator.validate = AsyncMock(return_value=ValidationResult(
        decision="ALLOW", reason="OK", should_deny=False))

    service.sigma_engine = Mock()
    service.sigma_engine.match_rules = AsyncMock(return_value=ValidationResult(
        decision="ALLOW", reason="OK", should_deny=False))

    service.ml_classifier = Mock()
    service.ml_classifier.validate = AsyncMock(
        return_value=ValidationResult.abstain("ml_classifier disabled"))

    service.context_validator = Mock()
    service.context_validator.validate_sequence = AsyncMock(return_value=ValidationResult(
        decision="ALLOW", reason="OK", should_deny=False))

    service.abuse_detector = Mock()
    service.abuse_detector.check_rate_limit = AsyncMock(return_value=ValidationResult(
        decision="ALLOW", reason="OK", should_deny=False))

    service.audit_logger = Mock()
    service.audit_logger.log_signals = AsyncMock()
    service.audit_logger.log_decision = AsyncMock()

    service.metrics_publisher = Mock()
    service.metrics_publisher.publish_validation_metrics = AsyncMock()

    return service


def _content_req(**over):
    base = dict(
        request_id="r-wire", session_id="sess-wire", agent_id="a-wire",
        tool_name="ingest_doc", tool_params={}, user_input="",
        timestamp="2026-07-02T00:00:00Z", operation_type="READ",
        phase="content", content_text="doc body ⟦AEGR:x:NAME⟧", redacted=True,
    )
    base.update(over)
    return ValidationRequest(**base)


def _opt_in(value):
    return patch(
        "app.redaction.feedback_store.tenant_feedback_opt_in", return_value=value)


def _items(ddb):
    return ddb.Table(TABLE).scan().get("Items", [])


# ============================================================ positive — the seam FIRES

@pytest.mark.asyncio
async def test_content_phase_allow_fires_feedback_write(feedback_env):
    """The ALLOW path on a content phase for an opted-in tenant fires
    `write_redacted_feedback` AND persists a redacted record. Must FAIL if the
    `_fire_and_forget(write_redacted_feedback(...))` line at _handle_allow is deleted
    (spy never called; table stays empty)."""
    service = _service(deny=False)
    import app.services.validation_service as _vs
    spy = AsyncMock(wraps=_vs.write_redacted_feedback)
    with _opt_in(True), patch.object(_vs, "write_redacted_feedback", spy):
        result = await service.validate_tool_call(_content_req())
        await _drain_bg()

    assert result["decision"] == "ALLOW"
    spy.assert_awaited_once()
    assert spy.await_args.kwargs["decision"] == "ALLOW"
    rows = _items(feedback_env)
    assert len(rows) == 1
    assert rows[0]["tenant_id"] == _TENANT
    assert rows[0]["phase"] == "content"
    assert rows[0]["decision"] == "ALLOW"
    assert rows[0]["opt_in"] is True
    assert rows[0]["redaction_eval_pass"] is True


@pytest.mark.asyncio
async def test_content_phase_deny_fires_feedback_write(feedback_env):
    """The DENY path on a content phase for an opted-in tenant fires
    `write_redacted_feedback` AND persists a redacted record. Must FAIL if the
    `_fire_and_forget(write_redacted_feedback(...))` line at _handle_deny is deleted."""
    service = _service(deny=True)
    import app.services.validation_service as _vs
    spy = AsyncMock(wraps=_vs.write_redacted_feedback)
    with _opt_in(True), patch.object(_vs, "write_redacted_feedback", spy):
        result = await service.validate_tool_call(_content_req())
        await _drain_bg()

    assert result["decision"] == "DENY"
    spy.assert_awaited_once()
    assert spy.await_args.kwargs["decision"] == "DENY"
    rows = _items(feedback_env)
    assert len(rows) == 1
    assert rows[0]["decision"] == "DENY"
    assert rows[0]["phase"] == "content"


# ============================================================ negative — the seam is INERT

@pytest.mark.asyncio
async def test_request_phase_writes_no_feedback_record(feedback_env):
    """The default `request` phase carries no persistable content — the wrapper
    early-returns at the phase gate, so even an opted-in tenant gets NO record. This is
    exactly why the existing request-phase validate tests could not catch a deleted
    call site: the wrapper is a no-op here. (The call site still fires; the wrapper is
    inert.)"""
    service = _service(deny=False)
    with _opt_in(True):
        result = await service.validate_tool_call(
            ValidationRequest(
                request_id="r-req", session_id="sess-wire", agent_id="a-wire",
                tool_name="get_info", tool_params={}, user_input="hi",
                timestamp="2026-07-02T00:00:00Z", operation_type="READ",
                # phase omitted → defaults to "request"
            )
        )
        await _drain_bg()

    assert result["decision"] == "ALLOW"
    assert _items(feedback_env) == []


@pytest.mark.asyncio
async def test_non_opted_in_tenant_writes_no_feedback_record(feedback_env):
    """A content-phase verdict for a NON-opted-in tenant writes NO record (§6.5 default
    OFF). The wrapper resolves opt-in=False and returns before touching the store."""
    service = _service(deny=False)
    with _opt_in(False):
        result = await service.validate_tool_call(_content_req())
        await _drain_bg()

    assert result["decision"] == "ALLOW"
    assert _items(feedback_env) == []
