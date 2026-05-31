"""Unit tests for signal_store_writer — Workstream 17 / LLD 17 §14.1 tests 10-13.

All AWS calls mocked. No live DDB.

Run from src/security-controller/:
    PYTHONPATH=. pytest tests/test_signal_store_writer.py -v
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.combiners.signal import Signal
from app.utils.signal_store_writer import (
    SignalStoreWriter,
    _assert_canonical_iso,
    _build_item,
    _isoformat_ms_z,
)


# ---------------------------------------------------------------------------
# Timestamp canonicalization (LLD §14.1 test 10)
# ---------------------------------------------------------------------------


class TestTimestampCanonicalization:
    def test_10a_writer_rejects_iso_without_milliseconds(self):
        """Test 10: writer rejects timestamps without milliseconds."""
        with pytest.raises(ValueError, match="YYYY-MM-DDTHH:MM:SS.sssZ"):
            _assert_canonical_iso("2026-05-26T02:48:44Z")

    def test_10b_writer_rejects_microsecond_iso(self):
        """Microseconds also break SK lexical sort — must reject."""
        with pytest.raises(ValueError):
            _assert_canonical_iso("2026-05-26T02:48:44.344123Z")

    def test_10c_writer_rejects_naive_iso_without_z(self):
        """Missing 'Z' (no timezone marker) → reject."""
        with pytest.raises(ValueError):
            _assert_canonical_iso("2026-05-26T02:48:44.344")

    def test_10d_canonical_iso_accepted(self):
        """Happy path: canonical format passes."""
        _assert_canonical_iso("2026-05-26T02:48:44.344Z")  # no raise = pass

    def test_10e_isoformat_ms_z_produces_canonical(self):
        """The writer's own clock-renderer always emits canonical format."""
        dt = datetime(2026, 5, 26, 2, 48, 44, 344123, tzinfo=timezone.utc)
        rendered = _isoformat_ms_z(dt)
        assert rendered == "2026-05-26T02:48:44.344Z"  # microseconds truncated
        _assert_canonical_iso(rendered)


# ---------------------------------------------------------------------------
# decision_date computation (LLD §14.1 test 11)
# ---------------------------------------------------------------------------


def test_11_decision_date_sliced_from_timestamp():
    """Test 11: writer computes decision_date = timestamp_iso[:10]."""
    signal = Signal(source="sentra.sigma", decision="DENY", reason="PII", priority=70)
    item = _build_item(
        session_id="s1",
        request_id="req-1",
        timestamp_ms=1779763724344,
        timestamp_iso="2026-05-26T02:48:44.344Z",
        signal=signal,
        shared_attrs={"agent_id": "agent-x"},
        expires_at=1789000000,
    )
    assert item["decision_date"] == "2026-05-26"


def test_11b_sk_layout_request_id_first():
    """SK must lead with request_id so per-request queries are O(K)."""
    signal = Signal(source="sentra.sigma", decision="DENY", priority=70)
    item = _build_item(
        session_id="s1",
        request_id="req-abc",
        timestamp_ms=42,
        timestamp_iso="2026-05-26T02:48:44.344Z",
        signal=signal,
        shared_attrs={},
        expires_at=1789000000,
    )
    assert item["sk"] == "req-abc#42#sentra.sigma"


def test_11c_shared_attrs_dont_overwrite_signal_fields():
    """A bad shared_attrs dict shouldn't be able to forge per-signal data."""
    signal = Signal(source="sentra.sigma", decision="DENY", priority=70)
    item = _build_item(
        session_id="s1",
        request_id="req-1",
        timestamp_ms=42,
        timestamp_iso="2026-05-26T02:48:44.344Z",
        signal=signal,
        shared_attrs={"decision": "ALLOW", "source": "evil"},  # malicious
        expires_at=1789000000,
    )
    assert item["decision"] == "DENY"
    assert item["source"] == "sentra.sigma"


# ---------------------------------------------------------------------------
# Retry / timeout semantics (LLD §14.1 tests 12-13)
# ---------------------------------------------------------------------------


@pytest.fixture
def writer():
    with patch("app.utils.signal_store_writer.boto3"):
        w = SignalStoreWriter(table_name="test-signals", region="us-east-1")
    return w


def _signal_set(n: int = 3) -> list[Signal]:
    return [
        Signal(source=f"sentra.test{i}", decision="ALLOW", priority=50)
        for i in range(n)
    ]


def test_12_unprocessed_items_retried(writer):
    """Test 12: BatchWriteItem returns UnprocessedItems → retry path executes ≤ max_retries."""
    # First call: 2 of 3 unprocessed. Second call: 0 unprocessed.
    call_responses = [
        {
            "UnprocessedItems": {
                "test-signals": [
                    {"PutRequest": {"Item": {"sk": {"S": "fake1"}, "session_id": {"S": "s"}}}},
                    {"PutRequest": {"Item": {"sk": {"S": "fake2"}, "session_id": {"S": "s"}}}},
                ]
            }
        },
        {"UnprocessedItems": {}},
    ]
    writer._client = MagicMock()
    writer._client.batch_write_item.side_effect = call_responses
    writer.retry_backoff_ms = [1, 1, 1]  # fast for test
    writer.write_timeout_ms = 5000  # generous so backoff doesn't kill us

    success, failure = writer.write_signals(
        session_id="s1",
        request_id="req-1",
        signals=_signal_set(3),
        shared_attrs={"agent_id": "a"},
    )

    assert writer._client.batch_write_item.call_count == 2  # 1 initial + 1 retry
    assert failure == 0
    assert success >= 1  # at least the first-pass success counted


def test_12b_max_retries_exhausted_records_failure(writer):
    """When UnprocessedItems persist past max_retries, items go to failure count."""
    # Every call returns the same unprocessed item — never makes progress.
    writer._client = MagicMock()
    writer._client.batch_write_item.return_value = {
        "UnprocessedItems": {
            "test-signals": [
                {"PutRequest": {"Item": {"sk": {"S": "stuck"}, "session_id": {"S": "s"}}}}
            ]
        }
    }
    writer.retry_backoff_ms = [1, 1, 1]
    writer.write_timeout_ms = 5000
    writer.max_retries = 2

    success, failure = writer.write_signals(
        session_id="s1",
        request_id="req-1",
        signals=[Signal(source="x", decision="ALLOW")],
        shared_attrs={},
    )
    assert failure >= 1  # the stuck item is recorded as failure
    assert writer._client.batch_write_item.call_count == writer.max_retries + 1


def test_13_timeout_does_not_raise(writer):
    """Test 13: BatchWriteItem timeout / slow path — writer returns counts, doesn't raise."""
    writer._client = MagicMock()

    # Make every call slow so the 50ms budget gets blown after one attempt.
    def slow_call(**kwargs):
        time.sleep(0.06)  # 60ms; deadline is 50ms
        return {
            "UnprocessedItems": {
                "test-signals": [
                    {"PutRequest": {"Item": {"sk": {"S": "x"}, "session_id": {"S": "s"}}}}
                ]
            }
        }

    writer._client.batch_write_item.side_effect = slow_call
    writer.write_timeout_ms = 50  # very tight budget for the test
    writer.retry_backoff_ms = [200, 200, 200]  # large enough that budget kills retry
    writer.max_retries = 3

    # Must not raise.
    success, failure = writer.write_signals(
        session_id="s1",
        request_id="req-1",
        signals=[Signal(source="x", decision="ALLOW")],
        shared_attrs={},
    )
    # At least one failure recorded; no exception
    assert failure >= 1


def test_13b_client_error_does_not_raise(writer):
    """Boto client errors → log + count as failure, never re-raise."""
    from botocore.exceptions import ClientError

    writer._client = MagicMock()
    writer._client.batch_write_item.side_effect = ClientError(
        {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "throttled"}},
        "BatchWriteItem",
    )

    success, failure = writer.write_signals(
        session_id="s1",
        request_id="req-1",
        signals=_signal_set(2),
        shared_attrs={},
    )
    assert failure == 2
    assert success == 0


def test_13c_empty_signals_returns_zero(writer):
    """Empty input is a no-op, not an error."""
    success, failure = writer.write_signals(
        session_id="s1", request_id="req-1", signals=[], shared_attrs={}
    )
    assert (success, failure) == (0, 0)
