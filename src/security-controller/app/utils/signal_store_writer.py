"""DynamoDB writer for the Validation Signal Store — Workstream 17 / LLD 17 §7.

Responsibilities
----------------
- Convert a list of Signal objects into DDB items with the right SK shape
  (`request_id#timestamp_ms#source`) and writer-populated attributes
  (`expires_at`, `decision_date`, `timestamp_ms`).
- Issue BatchWriteItem in chunks of 25.
- Retry `UnprocessedItems` up to N times with explicit backoff.
- Enforce a hard total-time budget so /v1/validate's tail latency
  doesn't blow up when DDB is slow.
- Never raise into the validation path — log + metric on every failure mode.

What this module is NOT
-----------------------
- Not the audit logger. `audit_logger.log_signals` is the call site that
  invokes this writer; CloudWatch dual-write lives there.
- Not the read path. See `decisions_service.py`.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable, Optional, Sequence

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.combiners.signal import Signal
from app.config import settings

logger = logging.getLogger(__name__)


# ISO 8601 with millisecond precision, ending in 'Z'. Locked by LLD 17 §5.2
# so SK ordering is well-defined across all writers.
_ISO_MS_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def _isoformat_ms_z(ts: datetime) -> str:
    """Render a UTC datetime as `YYYY-MM-DDTHH:MM:SS.sssZ`.

    Python's default isoformat emits microseconds; we truncate to milliseconds
    so every writer in the system produces lexically-comparable strings.
    """
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    else:
        ts = ts.astimezone(timezone.utc)
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def _assert_canonical_iso(ts_iso: str) -> None:
    """Reject any timestamp that isn't `YYYY-MM-DDTHH:MM:SS.sssZ`.

    SK lexical sort breaks if some writers emit microseconds or no
    milliseconds at all. Fail loud at the writer rather than corrupt
    the partition.
    """
    if not _ISO_MS_Z.match(ts_iso):
        raise ValueError(
            f"timestamp_iso must be 'YYYY-MM-DDTHH:MM:SS.sssZ' (LLD 17 §5.2); got {ts_iso!r}"
        )


def _to_ddb_value(value: Any) -> Any:
    """Coerce Python values into DDB-safe types.

    DDB rejects native floats — convert to Decimal. dicts/lists are walked
    so nested confidence values inside `metadata` also get cast.
    """
    if isinstance(value, float):
        # DDB Decimal doesn't accept NaN/Inf; clamp the rare case.
        if value != value or value in (float("inf"), float("-inf")):
            return Decimal("0")
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_ddb_value(v) for k, v in value.items() if v is not None}
    if isinstance(value, (list, tuple)):
        return [_to_ddb_value(v) for v in value]
    return value


def _build_item(
    *,
    session_id: str,
    request_id: str,
    timestamp_ms: int,
    timestamp_iso: str,
    signal: Signal,
    shared_attrs: dict[str, Any],
    expires_at: int,
) -> dict[str, Any]:
    """Construct the DDB item for one Signal.

    SK lays request_id first so per-request reads are O(K) Query with
    `SK begins_with <request_id>`. See LLD 17 §5.2.
    """
    sk = f"{request_id}#{timestamp_ms}#{signal.source}"
    item = {
        "session_id": session_id,
        "sk": sk,
        "request_id": request_id,
        "timestamp_ms": timestamp_ms,
        "timestamp_iso": timestamp_iso,
        "source": signal.source,
        "decision": signal.decision,
        "priority": signal.priority,
        "expires_at": expires_at,
        # decision_date is the GSI 2 partition key — a real stored attribute
        # (DDB GSIs project from attributes, not expressions). Slice the date
        # off the canonical timestamp so it always matches.
        "decision_date": timestamp_iso[:10],
    }
    # Optional signal fields — only include when populated to keep items lean.
    optional = {
        "reason": signal.reason,
        "confidence": signal.confidence,
        "threat_type": signal.threat_type,
        "matched_rule": signal.matched_rule,
        "severity": signal.severity,
        "metadata": signal.metadata or None,
    }
    for k, v in optional.items():
        if v is not None and v != {}:
            item[k] = v
    # Shared invocation-level attributes (agent_id, tool_name, etc.) — these
    # propagate to every signal row so single-table queries don't need joins.
    for k, v in shared_attrs.items():
        if v is None:
            continue
        if k in item:
            continue  # never overwrite per-signal fields
        item[k] = v
    return _to_ddb_value(item)


class SignalStoreWriter:
    """Sync best-effort BatchWriteItem with budgeted retry.

    Public API:
        write_signals(...)  → (success_count, failure_count)

    On any error or timeout: log, increment metric (TODO when metrics module
    lands; for now structured-log only), return counts. Never raise into the
    /v1/validate path.
    """

    def __init__(self, table_name: Optional[str] = None, region: Optional[str] = None):
        self.table_name = table_name or settings.dynamodb_validation_signals_table
        self.region = region or settings.aws_region
        self._client = boto3.client("dynamodb", region_name=self.region)
        # Tuned constants from LLD 17 §10
        self.write_timeout_ms = settings.signal_store_write_timeout_ms
        self.max_retries = settings.signal_store_batch_max_retries
        self.ttl_days = settings.signal_store_ttl_days
        self.retry_backoff_ms = [50, 200, 800]

    def write_signals(
        self,
        *,
        session_id: str,
        request_id: str,
        signals: Sequence[Signal],
        shared_attrs: dict[str, Any],
        now: Optional[datetime] = None,
    ) -> tuple[int, int]:
        """Persist signals to DDB. Returns (success_count, failure_count).

        Args:
            session_id: DDB PK.
            request_id: groups signals from one /v1/validate call.
            signals: the Signal objects to write.
            shared_attrs: per-invocation attributes propagated to every row
                (agent_id, tool_name, tool_params, user_input, platform,
                cloud_region, trust_score_before/after). Anything in here
                that collides with a per-signal field is dropped.
            now: injectable clock for tests. Defaults to UTC now.

        Time budget: total wall time across attempts ≤ write_timeout_ms.
        Beyond the budget, remaining items are abandoned with a warning.
        """
        if not signals:
            return (0, 0)

        if now is None:
            now = datetime.now(timezone.utc)
        timestamp_iso = _isoformat_ms_z(now)
        _assert_canonical_iso(timestamp_iso)
        timestamp_ms = int(now.timestamp() * 1000)
        expires_at = int(
            (now + timedelta(days=self.ttl_days)).timestamp()
        )

        items = [
            _build_item(
                session_id=session_id,
                request_id=request_id,
                timestamp_ms=timestamp_ms,
                timestamp_iso=timestamp_iso,
                signal=sig,
                shared_attrs=shared_attrs,
                expires_at=expires_at,
            )
            for sig in signals
        ]
        return self._batch_write_with_retry(items)

    def _batch_write_with_retry(self, items: list[dict[str, Any]]) -> tuple[int, int]:
        """Issue BatchWriteItem in 25-item chunks; retry UnprocessedItems.

        Returns (success, failure) counts. Failure is "still in
        UnprocessedItems after max_retries" or "client error".
        """
        from boto3.dynamodb.types import TypeSerializer

        serializer = TypeSerializer()
        deadline = time.monotonic() + (self.write_timeout_ms / 1000.0)
        success = 0
        failure = 0

        # Chunk into batches of 25 (DDB hard limit).
        for batch_start in range(0, len(items), 25):
            chunk = items[batch_start : batch_start + 25]
            if time.monotonic() > deadline:
                # Budget exhausted before we even got to this chunk.
                failure += len(chunk)
                logger.warning(
                    "signal_store.write.timeout: budget exhausted; abandoning %d items "
                    "(session_id=%s)",
                    len(chunk),
                    chunk[0].get("session_id") if chunk else "<unknown>",
                )
                continue

            request_items = {
                self.table_name: [
                    {"PutRequest": {"Item": {k: serializer.serialize(v) for k, v in item.items()}}}
                    for item in chunk
                ]
            }

            for attempt in range(self.max_retries + 1):
                remaining_ms = (deadline - time.monotonic()) * 1000
                if remaining_ms <= 0:
                    n_remaining = sum(
                        len(v) for v in request_items.values()
                    )
                    failure += n_remaining
                    logger.warning(
                        "signal_store.write.timeout: budget exceeded after %d attempt(s); "
                        "abandoning %d items",
                        attempt,
                        n_remaining,
                    )
                    break

                try:
                    response = self._client.batch_write_item(
                        RequestItems=request_items
                    )
                except (BotoCoreError, ClientError) as exc:
                    n_lost = sum(len(v) for v in request_items.values())
                    failure += n_lost
                    logger.warning(
                        "signal_store.write.failure: %s — %d items lost (will be in CloudWatch)",
                        exc.__class__.__name__,
                        n_lost,
                    )
                    break

                unprocessed = response.get("UnprocessedItems") or {}
                done_this_attempt = sum(
                    1
                    for tbl_requests in request_items.values()
                    for _ in tbl_requests
                ) - sum(len(v) for v in unprocessed.values())
                success += done_this_attempt

                if not unprocessed:
                    break

                # Some items still need work — retry the unprocessed only.
                request_items = unprocessed
                if attempt < self.max_retries:
                    backoff = self.retry_backoff_ms[
                        min(attempt, len(self.retry_backoff_ms) - 1)
                    ] / 1000.0
                    # Don't sleep past the deadline.
                    if (time.monotonic() + backoff) > deadline:
                        backoff = max(0, deadline - time.monotonic())
                    time.sleep(backoff)
                else:
                    # Exhausted retries — record the loss.
                    n_lost = sum(len(v) for v in request_items.values())
                    failure += n_lost
                    logger.warning(
                        "signal_store.write.failure: %d items still unprocessed after %d retries",
                        n_lost,
                        self.max_retries,
                    )

        return (success, failure)
