"""WS-E2 — the `write_redacted_feedback` ORCHESTRATION wrapper (E5.3 / LLD 29 §6.5).

REGRESSION (integration-sentinel HIGH): the opt-in feedback orchestration fired
fire-and-forget from `_handle_deny`/`_handle_allow` had NO direct test — only the
lower-level `FeedbackStore.write_if_opted_in` was covered (test_feedback_store.py).
These tests exercise the COMPOSITION end-to-end against a moto table so the seam that
decides whether an opted-in tenant's content-phase record is actually written is
verified, not just the store in isolation:

  * the phase gate (request phase → early return, NO write);
  * the `tenant_feedback_opt_in` resolution (non-opted-in → no record; opted-in → write);
  * the FeedbackGateFail swallow path (a residual → skipped, never raised to caller);
  * the generic exception swallow path (a store hiccup never surfaces to the verdict);
  * the subject_key extraction (§6.4) — `subject_id`/`subject`/`user_id` → a durable
    `subject_locator`; none present → TTL-only (no locator). This is the MEDIUM gap:
    a real caller populates `user_id` (models.py:118), NOT `subject_id`.
"""
from __future__ import annotations

from unittest.mock import Mock, patch

import boto3
import pytest
from moto import mock_aws

from app.api.models import ValidationRequest
from app.config import settings
from app.redaction.feedback_store import FeedbackGateFail, SUBJECT_LOCATOR_GSI
from app.services.validation_service import (
    _subject_key_from_context,
    write_redacted_feedback,
)
from app.utils import tenancy


TABLE = "sentra-redacted-feedback"
_TENANT = "t_feedback"


@pytest.fixture
def feedback_env(monkeypatch):
    """A moto feedback table + a resolved tenant contextvar (so the wrapper's
    `tenancy.current_tenant()` returns a real tenant, not the P0a default)."""
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(k, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", settings.aws_region)
    monkeypatch.setattr(settings, "dynamodb_feedback_store_table", TABLE)
    monkeypatch.setattr(settings, "feedback_subject_locator_salt", "unit-test-salt")
    # Reset the process-wide feedback-store singleton so it binds to the moto resource.
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


def _req(**over):
    base = dict(
        request_id="r1", session_id="s1", agent_id="a1", tool_name="ingest",
        tool_params={}, user_input="", timestamp="2026-07-02T00:00:00Z",
        operation_type="READ", phase="content",
        content_text="note ⟦AEGR:x:NAME⟧", redacted=True,
    )
    base.update(over)
    return ValidationRequest(**base)


def _items(ddb):
    return ddb.Table(TABLE).scan().get("Items", [])


def _opt_in(value):
    """Patch the wrapper's lazily-imported opt-in resolver."""
    return patch(
        "app.redaction.feedback_store.tenant_feedback_opt_in", return_value=value
    )


# ============================================================ phase gate (early return)

@pytest.mark.asyncio
async def test_request_phase_writes_nothing(feedback_env):
    """The request phase carries no persistable content — the wrapper returns BEFORE
    touching the store. Even an opted-in tenant gets no record. Must FAIL if the phase
    gate is removed (a request-phase record would appear)."""
    with _opt_in(True) as opt:
        await write_redacted_feedback(
            _req(phase="request", content_text=None),
            decision="ALLOW", reason="ok", winning_source="sentra.combined",
            detector_outcomes={},
        )
    # Returned before resolving opt-in at all.
    opt.assert_not_called()
    assert _items(feedback_env) == []


# ============================================================ opt-in resolution (§6.5)

@pytest.mark.asyncio
async def test_non_opted_in_tenant_writes_no_record(feedback_env):
    """Default OFF: an un-opted-in tenant's content-phase verdict writes NO record.
    Must FAIL if the opt-in gate is bypassed."""
    with _opt_in(False):
        await write_redacted_feedback(
            _req(), decision="DENY", reason="policy denied",
            winning_source="sentra.policy", detector_outcomes={"violation_type": "X"},
        )
    assert _items(feedback_env) == []


@pytest.mark.asyncio
async def test_opted_in_tenant_content_phase_writes_record(feedback_env):
    """The happy path the seam owns: an OPTED-IN tenant's redacted content-phase
    verdict IS written end-to-end (composition, not just the store in isolation)."""
    with _opt_in(True):
        await write_redacted_feedback(
            _req(), decision="DENY", reason="policy denied",
            winning_source="sentra.policy", detector_outcomes={"violation_type": "X"},
        )
    items = _items(feedback_env)
    assert len(items) == 1
    row = items[0]
    assert row["tenant_id"] == _TENANT
    assert row["phase"] == "content"
    assert row["decision"] == "DENY"
    assert row["opt_in"] is True
    assert row["redaction_eval_pass"] is True


# ============================================================ subject_key extraction (§6.4)

@pytest.mark.asyncio
async def test_user_id_context_yields_subject_locator(feedback_env):
    """MEDIUM gap: a real caller populates `user_id` (the documented context identity
    convention, models.py:118), NOT `subject_id`. The wrapper must derive a durable
    `subject_locator` from `user_id` so the DSAR delete-by-subject route can target it.
    Before the fix (keying only off `subject_id`) this record had no locator →
    TTL-only-deletable. Must FAIL if the extraction drops back to subject_id-only."""
    with _opt_in(True):
        await write_redacted_feedback(
            _req(context={"user_id": "user-42", "ip_address": "1.2.3.4"}),
            decision="ALLOW", reason="ok", winning_source="sentra.combined",
            detector_outcomes={},
        )
    row = _items(feedback_env)[0]
    assert "subject_locator" in row and row["subject_locator"]


@pytest.mark.asyncio
async def test_no_identity_context_is_ttl_only(feedback_env):
    """No subject key in context → no `subject_locator` (TTL-only-deletable, §6.4). The
    record still writes; it just is not subject-targetable. Must FAIL if a locator is
    fabricated from a non-identity field."""
    with _opt_in(True):
        await write_redacted_feedback(
            _req(context={"ip_address": "1.2.3.4", "authorization_level": "user"}),
            decision="ALLOW", reason="ok", winning_source="sentra.combined",
            detector_outcomes={},
        )
    row = _items(feedback_env)[0]
    assert "subject_locator" not in row


def test_subject_key_extraction_priority_and_types():
    """`_subject_key_from_context` prefers subject_id > subject > user_id, ignores
    non-string / empty values, and returns None for a keyless context."""
    assert _subject_key_from_context({"subject_id": "sid", "user_id": "uid"}) == "sid"
    assert _subject_key_from_context({"subject": "subj", "user_id": "uid"}) == "subj"
    assert _subject_key_from_context({"user_id": "uid"}) == "uid"
    assert _subject_key_from_context({"user_id": "   "}) is None       # blank ignored
    assert _subject_key_from_context({"user_id": 12345}) is None        # non-string ignored
    assert _subject_key_from_context({"ip_address": "1.2.3.4"}) is None  # no identity key
    assert _subject_key_from_context(None) is None
    assert _subject_key_from_context({}) is None


# ============================================================ eval-gate swallow (F3)

@pytest.mark.asyncio
async def test_eval_gate_residual_is_swallowed_not_raised(feedback_env):
    """A residual identifier that survives into the would-be-persisted record trips the
    eval-gate → FeedbackGateFail INSIDE the store; the wrapper SWALLOWS it (the skip is
    the security action) and never raises to the fire-and-forget caller. No record is
    written. Must FAIL if the wrapper lets FeedbackGateFail propagate."""
    with _opt_in(True):
        # A raw SSN in the reason is a residual the IndependentGateDetector catches.
        await write_redacted_feedback(
            _req(), decision="DENY", reason="subject SSN 123-45-6789 leaked",
            winning_source="sentra.policy", detector_outcomes={},
        )
    assert _items(feedback_env) == []   # gate blocked → nothing persisted


@pytest.mark.asyncio
async def test_unredacted_request_is_gate_failed_not_written(feedback_env):
    """If the barrier did NOT stamp `redacted=True` (a content field that never went
    through a redaction pass), the store's redacted-only check raises FeedbackGateFail,
    which the wrapper swallows — no raw content is persisted. Must FAIL if an un-flagged
    record is written."""
    with _opt_in(True):
        await write_redacted_feedback(
            _req(redacted=False), decision="ALLOW", reason="ok",
            winning_source="sentra.combined", detector_outcomes={},
        )
    assert _items(feedback_env) == []


# ============================================================ generic error swallow

@pytest.mark.asyncio
async def test_store_error_never_surfaces_to_caller(feedback_env):
    """A feedback-store hiccup (any exception below the wrapper) must NEVER surface to
    the verdict path — the wrapper returns cleanly. Patch the store to raise and assert
    write_redacted_feedback does not propagate."""
    boom = Mock()
    boom.write_if_opted_in = Mock(side_effect=RuntimeError("ddb on fire"))
    with _opt_in(True), patch(
        "app.redaction.feedback_store.get_feedback_store", return_value=boom
    ):
        # No exception should escape.
        await write_redacted_feedback(
            _req(), decision="DENY", reason="policy denied",
            winning_source="sentra.policy", detector_outcomes={},
        )
    # (reaching here without raising is the assertion)


@pytest.mark.asyncio
async def test_opt_in_resolution_error_defaults_off(feedback_env):
    """If the opt-in resolver itself raises, the wrapper's outer try swallows it — no
    record, fail-secure. (The resolver's own conservative-off is tested in
    test_feedback_store; here we prove the wrapper does not crash the verdict path.)"""
    with patch(
        "app.redaction.feedback_store.tenant_feedback_opt_in",
        side_effect=RuntimeError("tenant store down"),
    ):
        await write_redacted_feedback(
            _req(), decision="ALLOW", reason="ok",
            winning_source="sentra.combined", detector_outcomes={},
        )
    assert _items(feedback_env) == []
