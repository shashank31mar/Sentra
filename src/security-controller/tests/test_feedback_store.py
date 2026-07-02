"""WS-E2 — opt-in redacted feedback store (E8.4 / LLD 29 §15.3, §6).

Hermetic (moto DynamoDB) tests for the write / eval-gate / opt-in / TTL / DSAR /
tenant-isolation contract. The CDK table construct is stage 3; here we provision
the §6.2-schema table via moto and exercise the write/DSAR logic against it.
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch

import boto3
import pytest
from moto import mock_aws

from app.config import settings
from app.redaction.feedback_store import (
    FeedbackRedactionGateFail,
    FeedbackRecord,
    FeedbackStore,
    SUBJECT_LOCATOR_GSI,
    derive_subject_locator,
)


TABLE = "sentra-redacted-feedback"


@pytest.fixture
def feedback_env(monkeypatch):
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(k, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", settings.aws_region)
    monkeypatch.setattr(settings, "dynamodb_feedback_store_table", TABLE)
    # A non-empty salt so subject-locator derivation is exercised.
    monkeypatch.setattr(settings, "feedback_subject_locator_salt", "unit-test-salt")
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


def _record(tenant="t_a", *, payload=None, reason="policy denied", winning="sentra.policy"):
    return FeedbackRecord(
        tenant_id=tenant,
        phase="content",
        redacted_payload=payload if payload is not None else {"content_text": "note ⟦AEGR:x:NAME⟧"},
        decision="DENY",
        reason=reason,
        winning_source=winning,
        detector_outcomes={"sigma": "DENY"},
        ttl_days=90,
    )


# --------------------------------------------------------------------- opt-in (§6.5)

def test_non_opted_in_tenant_writes_no_record(feedback_env):
    """Default OFF: a non-opted-in tenant produces NO record. Must FAIL if the
    opt-in gate is bypassed or defaults ON (§6.5 FOOTGUN)."""
    store = FeedbackStore()
    rid = store.write_if_opted_in(_record(), opted_in=False, redacted=True)
    assert rid is None
    assert store.query_by_tenant("t_a") == []


def test_opted_in_tenant_writes_redacted_record(feedback_env):
    """An opted-in tenant with a clean redacted payload gets a record with the
    §6.2 attributes (opt_in True, redaction_eval_pass True, bounded ttl)."""
    store = FeedbackStore()
    rid = store.write_if_opted_in(_record(), opted_in=True, redacted=True)
    assert rid is not None
    items = store.query_by_tenant("t_a")
    assert len(items) == 1
    it = items[0]
    assert it["opt_in"] is True
    assert it["redaction_eval_pass"] is True
    assert int(it["ttl"]) > int(time.time())  # bounded, future TTL set


# ------------------------------------------------------------------ redacted-only (I-1)

def test_unredacted_payload_rejected(feedback_env):
    """A raw (un-redacted) payload cannot be written — redacted-only invariant."""
    store = FeedbackStore()
    with pytest.raises(FeedbackRedactionGateFail):
        store.write_if_opted_in(_record(), opted_in=True, redacted=False)
    assert store.query_by_tenant("t_a") == []


# ------------------------------------------------------------------- eval-gate (§6.3)

def test_residual_identifier_blocks_write(feedback_env):
    """A record marked redacted but carrying a residual identifier (a Tier-2 miss)
    is caught by the STRONGER INDEPENDENT eval-gate and NOT written +
    FeedbackRedactionGateFail. Must FAIL if the gate re-runs the primary (circular,
    F3) or trusts the flag."""
    store = FeedbackStore()
    with pytest.raises(FeedbackRedactionGateFail):
        store.write_if_opted_in(
            _record(payload={"content_text": "ssn 123-45-6789"}),
            opted_in=True, redacted=True,
        )
    assert store.query_by_tenant("t_a") == []


def test_residual_in_reason_blocks_write(feedback_env):
    """§6.2 FOOTGUN: a residual in the `reason` (not the payload) also blocks the
    write — the eval-gate scans the WHOLE record, not just the payload."""
    store = FeedbackStore()
    with pytest.raises(FeedbackRedactionGateFail):
        store.write_if_opted_in(
            _record(reason="blocked: contained 123-45-6789"),
            opted_in=True, redacted=True,
        )
    assert store.query_by_tenant("t_a") == []


# ------------------------------------------------------------------ DSAR delete (§6.4)

def test_dsar_delete_removes_subject(feedback_env):
    """DELETE-by-subject removes every record for that subject via the GSI."""
    store = FeedbackStore()
    store.write_if_opted_in(_record(), opted_in=True, redacted=True, subject_key="acct-42")
    store.write_if_opted_in(_record(), opted_in=True, redacted=True, subject_key="acct-42")
    # A different subject in the same tenant must survive.
    store.write_if_opted_in(_record(), opted_in=True, redacted=True, subject_key="acct-99")

    locator = derive_subject_locator("acct-42", tenant_id="t_a",
                                     salt=store._tenant_salt("t_a"))
    deleted = store.delete_subject(locator, tenant_id="t_a")
    assert deleted == 2
    remaining = store.query_by_tenant("t_a")
    assert len(remaining) == 1  # acct-99 survives


def test_dsar_cross_tenant_deletes_nothing(feedback_env):
    """Tenant-scoped: tenant B's DSAR for a locator that exists under tenant A
    deletes NOTHING from A (the delete is bound to the caller's tenant). The route
    returns the 403 for a caller with no tenant; here we prove the store never
    crosses the boundary."""
    store = FeedbackStore()
    store.write_if_opted_in(_record("t_a"), opted_in=True, redacted=True, subject_key="acct-42")
    locator = derive_subject_locator("acct-42", tenant_id="t_a",
                                     salt=store._tenant_salt("t_a"))
    # Tenant B asks to delete the SAME locator → nothing under B's partition.
    deleted = store.delete_subject(locator, tenant_id="t_b")
    assert deleted == 0
    # Tenant A's record is untouched.
    assert len(store.query_by_tenant("t_a")) == 1


def test_dsar_delete_paginates_over_page_boundary(feedback_env):
    """DELETE-by-subject must remove EVERY record for the subject even when the GSI
    query spans multiple pages (DynamoDB truncates a query page at 1 MB and returns
    LastEvaluatedKey). REGRESSION: the pre-fix code issued ONE query and deleted only
    the first page, leaving residual PHI while reporting an under-count as complete —
    a silent GDPR-erasure breach (§6.4 "delete every record").

    We force multi-page behaviour deterministically by wrapping the table so every
    `query` carries a small `Limit` (moto then returns LastEvaluatedKey per page).
    The production `delete_subject` supplies no Limit; only its LastEvaluatedKey loop
    can consume all pages — so this FAILS against the single-query implementation.
    """
    store = FeedbackStore()
    n = 5
    for _ in range(n):
        store.write_if_opted_in(_record(), opted_in=True, redacted=True, subject_key="acct-42")
    locator = derive_subject_locator("acct-42", tenant_id="t_a",
                                     salt=store._tenant_salt("t_a"))

    real_table = store._table()

    class _PagedTable:
        """Delegates to the real table but forces one-item query pages, so the GSI
        query genuinely paginates (LastEvaluatedKey on every page but the last)."""

        def query(self, **kw):
            kw.setdefault("Limit", 1)
            return real_table.query(**kw)

        def batch_writer(self):
            return real_table.batch_writer()

        def delete_item(self, **kw):
            return real_table.delete_item(**kw)

    store._table = lambda: _PagedTable()  # type: ignore[method-assign]
    deleted = store.delete_subject(locator, tenant_id="t_a")
    assert deleted == n  # every page consumed, not just the first
    # Restore the real table for the isolation read; all n records gone.
    store._table = lambda: real_table  # type: ignore[method-assign]
    assert store.query_by_tenant("t_a") == []


def test_no_subject_key_is_ttl_only(feedback_env):
    """A record with no stable subject key gets NO subject_locator (TTL-only-
    deletable, §6.4) — we do not claim subject-targeted deletion for it."""
    store = FeedbackStore()
    store.write_if_opted_in(_record(), opted_in=True, redacted=True, subject_key=None)
    it = store.query_by_tenant("t_a")[0]
    assert "subject_locator" not in it


# -------------------------------------------------------------- tenant isolation (NFR-6)

def test_tenant_isolation_query(feedback_env):
    """A tenant-A query can never return tenant-B records (PK-scoped, §6.2)."""
    store = FeedbackStore()
    store.write_if_opted_in(_record("t_a"), opted_in=True, redacted=True)
    store.write_if_opted_in(_record("t_b"), opted_in=True, redacted=True)
    a_rows = store.query_by_tenant("t_a")
    assert all(r["tenant_id"] == "t_a" for r in a_rows)
    assert len(a_rows) == 1


# ---------------------------------------------------------------- locator derivation

def test_subject_locator_is_salted_and_per_tenant(feedback_env):
    """The locator is a salted keyed hash — the SAME subject key yields DIFFERENT
    locators under different tenants (not cross-tenant-linkable, §6.4)."""
    store = FeedbackStore()
    la = derive_subject_locator("acct-42", tenant_id="t_a", salt=store._tenant_salt("t_a"))
    lb = derive_subject_locator("acct-42", tenant_id="t_b", salt=store._tenant_salt("t_b"))
    assert la and lb and la != lb
    # Not the raw key.
    assert "acct-42" not in la


def test_no_salt_yields_ttl_only_locator():
    """No configured salt → no locator emitted (we never emit an unsalted/linkable
    one); the record is TTL-only-deletable."""
    assert derive_subject_locator("acct-42", tenant_id="t_a", salt="") is None
    assert derive_subject_locator(None, tenant_id="t_a", salt="s") is None


# --------------------------------------------------------- alarm task lifetime (R2-L1)

@pytest.mark.asyncio
async def test_gate_fail_alarm_task_completes_not_gc_dropped():
    """`_alarm_gate_fail` must schedule the FeedbackRedactionGateFail publish AND keep a
    strong ref so the loop cannot GC the task before it runs (mirrors
    audit_logger._ALARM_TASKS). REGRESSION: the pre-fix code did a bare
    `create_task(coro)` and discarded the return value — a weakly-referenced task the
    event loop could collect mid-flight, silently dropping the alarm. This test asserts
    the coroutine actually completes (the publisher is awaited) after draining
    `_ALARM_TASKS`. Must FAIL if the task ref is dropped OR the publish never scheduled."""
    import app.redaction.feedback_store as fs

    fs._ALARM_TASKS.clear()
    emit = AsyncMock()
    fake_publisher = type("P", (), {"publish_feedback_redaction_gate_fail_metric": emit})
    with patch("app.utils.metrics_publisher.MetricsPublisher", return_value=fake_publisher()):
        store = FeedbackStore.__new__(FeedbackStore)  # no AWS client needed for the alarm
        store._alarm_gate_fail(["SSN"])
        # The task was retained (strong ref), not immediately discarded.
        assert len(fs._ALARM_TASKS) == 1
        # Drain: the alarm coroutine runs to completion.
        await asyncio.gather(*list(fs._ALARM_TASKS), return_exceptions=True)

    emit.assert_awaited_once()
    assert emit.await_args.kwargs["detected_classes"] == ["SSN"]
    # The done-callback cleaned the set back to empty (it does not grow unbounded).
    assert fs._ALARM_TASKS == set()


def test_gate_fail_alarm_no_running_loop_closes_coro_no_error():
    """In a sync context (no running loop) the alarm closes the coroutine and never
    raises — the write path is never broken by an alarm hiccup (§6.3)."""
    import app.redaction.feedback_store as fs

    fs._ALARM_TASKS.clear()
    emit = AsyncMock()
    fake_publisher = type("P", (), {"publish_feedback_redaction_gate_fail_metric": emit})
    with patch("app.utils.metrics_publisher.MetricsPublisher", return_value=fake_publisher()):
        store = FeedbackStore.__new__(FeedbackStore)
        # No running loop here → must not raise, must not leak a task.
        store._alarm_gate_fail(["SSN"])
    assert fs._ALARM_TASKS == set()
