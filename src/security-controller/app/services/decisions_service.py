"""DDB-backed read service for the Validation Signal Store.

Workstream 17 / LLD 17 §8. Backs four endpoints:

  GET  /v1/sessions/{id}/decisions   — combined verdicts grouped by request_id
  GET  /v1/sessions/{id}/signals     — raw signal stream
  GET  /v1/decisions                 — paginated time-range scan via GSI 2
  POST /v1/sessions/{id}/signals     — external-producer signal write

All reads go through this module. The audit-log path (`/v1/logs` via
CloudWatch Insights) stays in logs_service.py — that's the compliance
archive, this is the fast-read substrate.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any, Optional

import boto3
from boto3.dynamodb.types import TypeDeserializer
from botocore.exceptions import ClientError

from app.combiners import DenyOverrides, Signal, Source
from app.combiners.signal import Signal as SignalClass  # alias for clarity in helpers
from app.combiners.sources import DEFAULT_PRIORITIES
from app.config import settings
from app.utils.signal_store_writer import (
    _ISO_MS_Z,
    _isoformat_ms_z,
    SignalStoreWriter,
)

logger = logging.getLogger(__name__)

_GSI_DECISION_DATE = "decision-date-timestamp-index"


class DecisionsService:
    """Read-side companion to SignalStoreWriter.

    Stateless — constructed once and shared. boto3 client is created lazily
    so unit tests can monkey-patch before first call.
    """

    def __init__(self):
        self.table_name = settings.dynamodb_validation_signals_table
        self.region = settings.aws_region
        self._client: Optional[Any] = None
        self._deser = TypeDeserializer()
        # Reuse the writer for the POST signal path so we have one place
        # that knows how to serialize Signals → DDB items.
        self._writer = SignalStoreWriter()
        self._combiner = DenyOverrides()

    def _ddb(self):
        if self._client is None:
            self._client = boto3.client("dynamodb", region_name=self.region)
        return self._client

    # -----------------------------------------------------------------------
    # Read paths
    # -----------------------------------------------------------------------

    def get_session_signals(
        self,
        session_id: str,
        request_id: Optional[str] = None,
        source: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Return raw signal rows for a session — LLD 17 §8.3.

        Uses Query on the main table (PK=session_id). When request_id is
        provided, narrows to that one request via SK begins_with — the
        dashboard's hot-path pattern.
        """
        kwargs: dict[str, Any] = {
            "TableName": self.table_name,
            "Limit": min(limit, 500),
            "KeyConditionExpression": "session_id = :sid",
            "ExpressionAttributeValues": {":sid": {"S": session_id}},
        }
        if request_id:
            kwargs["KeyConditionExpression"] = "session_id = :sid AND begins_with(sk, :rid)"
            kwargs["ExpressionAttributeValues"][":rid"] = {"S": f"{request_id}#"}

        # Optional source / agent_id filter applied post-query (small N expected).
        items = self._query_all(kwargs)
        if source:
            items = [it for it in items if it.get("source") == source]
        if agent_id:
            items = [it for it in items if it.get("agent_id") == agent_id]

        return {
            "session_id": session_id,
            "signals": items,
            "total": len(items),
        }

    def get_session_decisions(
        self,
        session_id: str,
        request_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Return signals grouped by request_id with combiner applied per group — LLD 17 §8.2.

        This is the dashboard's hot path. p95 target ≤100ms.
        """
        raw = self.get_session_signals(
            session_id=session_id,
            request_id=request_id,
            agent_id=agent_id,
            limit=limit,
        )
        items = raw["signals"]

        # Group by request_id, preserving each item's order within its group.
        groups: dict[str, list[dict]] = {}
        for it in items:
            rid = it.get("request_id") or "<unknown>"
            groups.setdefault(rid, []).append(it)

        decisions = []
        for rid, group in groups.items():
            # Sort within group: timestamp_ms ascending so the audit-style
            # display matches the order signals were emitted.
            group.sort(key=lambda x: x.get("timestamp_ms", 0))
            timestamp_iso = next(
                (it.get("timestamp_iso") for it in group if it.get("timestamp_iso")),
                None,
            )
            signals_obj = [_item_to_signal(it) for it in group]
            try:
                combined = self._combiner.combine(signals_obj)
            except ValueError:
                # No-signals shouldn't happen here (group exists only if at
                # least one row matched), but be defensive.
                continue
            decisions.append({
                "request_id": rid,
                "timestamp_iso": timestamp_iso,
                "combined": {
                    # Workstream 17 / LLD 17 §4 — stamp the read-side aggregate
                    # with `dashboard.combined` so consumers can distinguish a
                    # runner-side fold (Sentra + edge signals) from the
                    # controller's internal `sentra.combined` (Sentra-only).
                    "source": Source.DASHBOARD_COMBINED,
                    "decision": combined.decision,
                    "reason": combined.reason,
                    "winning_source": (combined.metadata or {}).get("winning_source"),
                    "threat_type": combined.threat_type,
                    "matched_rule": combined.matched_rule,
                    "severity": combined.severity,
                },
                # Return signals as dicts so the HTTP response is JSON-clean.
                "signals": [s.to_dict() for s in signals_obj],
            })

        # Sort decisions newest-first by timestamp_iso (fall back to rid).
        decisions.sort(key=lambda d: d.get("timestamp_iso") or "", reverse=True)

        return {
            "session_id": session_id,
            "decisions": decisions,
            "total": len(decisions),
        }

    def scan_decisions(
        self,
        since: Optional[str] = None,
        until: Optional[str] = None,
        agent_id: Optional[str] = None,
        decision: Optional[str] = None,
        threat_type: Optional[str] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        """Paginated time-range scan via GSI 2 — LLD 17 §8.4.

        decision_date is the GSI partition key (YYYY-MM-DD). For a multi-day
        range we'd ideally Query each day's partition; for Phase 1 with
        on-demand low traffic we accept a Scan with FilterExpression on the
        GSI. Cursor round-trips as opaque base64 LastEvaluatedKey.
        """
        # Default window: last 24h.
        from datetime import datetime, timedelta, timezone
        if until:
            until_dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
        else:
            until_dt = datetime.now(timezone.utc)
        if since:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        else:
            since_dt = until_dt - timedelta(hours=24)

        # Build FilterExpression for the optional filters.
        filter_parts: list[str] = []
        expr_values: dict[str, Any] = {
            ":since": {"N": str(int(since_dt.timestamp() * 1000))},
            ":until": {"N": str(int(until_dt.timestamp() * 1000))},
        }
        filter_parts.append("timestamp_ms BETWEEN :since AND :until")

        if agent_id:
            filter_parts.append("agent_id = :aid")
            expr_values[":aid"] = {"S": agent_id}
        if decision:
            filter_parts.append("#dec = :d")
            expr_values[":d"] = {"S": decision}
        if threat_type:
            filter_parts.append("threat_type = :tt")
            expr_values[":tt"] = {"S": threat_type}

        kwargs: dict[str, Any] = {
            "TableName": self.table_name,
            "IndexName": _GSI_DECISION_DATE,
            "Limit": min(limit, 200),
            "FilterExpression": " AND ".join(filter_parts),
            "ExpressionAttributeValues": expr_values,
        }
        if decision:
            # `decision` is a reserved DDB word, hence the placeholder.
            kwargs["ExpressionAttributeNames"] = {"#dec": "decision"}
        if cursor:
            try:
                kwargs["ExclusiveStartKey"] = _decode_cursor(cursor)
            except Exception as exc:
                raise ValueError(f"invalid cursor: {exc}") from exc

        try:
            resp = self._ddb().scan(**kwargs)
        except ClientError as exc:
            logger.exception("scan_decisions failed: %s", exc)
            return {"decisions": [], "next_cursor": None, "has_more": False, "error": str(exc)}

        items = [self._deserialize_item(it) for it in resp.get("Items", [])]

        # Group signals by request_id and combine — same as get_session_decisions
        # but across sessions. The dashboard's all-events view can render
        # per-request rows uniformly with the per-session view.
        groups: dict[tuple[str, str], list[dict]] = {}
        for it in items:
            key = (it.get("session_id") or "<unknown>", it.get("request_id") or "<unknown>")
            groups.setdefault(key, []).append(it)

        decisions = []
        for (sid, rid), group in groups.items():
            group.sort(key=lambda x: x.get("timestamp_ms", 0))
            signals_obj = [_item_to_signal(it) for it in group]
            try:
                combined = self._combiner.combine(signals_obj)
            except ValueError:
                continue
            decisions.append({
                "session_id": sid,
                "request_id": rid,
                "timestamp_iso": next(
                    (it.get("timestamp_iso") for it in group if it.get("timestamp_iso")), None
                ),
                "combined": {
                    # See get_session_decisions — same rationale, same source.
                    "source": Source.DASHBOARD_COMBINED,
                    "decision": combined.decision,
                    "reason": combined.reason,
                    "winning_source": (combined.metadata or {}).get("winning_source"),
                },
                "signals": [s.to_dict() for s in signals_obj],
            })

        next_cursor = (
            _encode_cursor(resp["LastEvaluatedKey"])
            if "LastEvaluatedKey" in resp
            else None
        )
        return {
            "decisions": decisions,
            "next_cursor": next_cursor,
            "has_more": next_cursor is not None,
            "total": len(decisions),
        }

    # -----------------------------------------------------------------------
    # Write path (external producers)
    # -----------------------------------------------------------------------

    def post_signal(
        self,
        session_id: str,
        signal_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Accept an externally-produced signal — LLD 17 §8.1.

        Used by Bedrock/Azure connectors to report their guardrail
        observations. Validates the source against taxonomy (lenient — unknown
        sources are stored but logged) and writes via the same SignalStoreWriter
        used by audit_logger.
        """
        # Build a Signal from the payload. Required fields per §8.1:
        # request_id, source, decision. Everything else optional.
        required = ("request_id", "source", "decision")
        missing = [k for k in required if not signal_data.get(k)]
        if missing:
            raise ValueError(f"missing required fields: {missing}")

        if signal_data["decision"] not in ("ALLOW", "DENY"):
            raise ValueError(f"decision must be ALLOW or DENY, got {signal_data['decision']!r}")

        source = signal_data["source"]
        if source not in DEFAULT_PRIORITIES:
            # Unknown source — accept, log, use priority 0 unless caller set one.
            logger.warning("signal post with unknown source %r — using priority 0", source)

        signal = Signal(
            source=source,
            decision=signal_data["decision"],
            reason=signal_data.get("reason"),
            priority=signal_data.get("priority") or DEFAULT_PRIORITIES.get(source, 0),
            confidence=signal_data.get("confidence"),
            threat_type=signal_data.get("threat_type"),
            matched_rule=signal_data.get("matched_rule"),
            severity=signal_data.get("severity"),
            metadata=signal_data.get("metadata") or {},
        )

        shared = {
            "agent_id": signal_data.get("agent_id"),
            "tool_name": signal_data.get("tool_name"),
            "platform": signal_data.get("platform"),
            "cloud_region": signal_data.get("cloud_region"),
            "user_input": signal_data.get("user_input"),
        }
        # Inject `now` into the writer so we can return the SK the row
        # actually got, not a placeholder. The writer computes timestamp_ms
        # from this same datetime, so the SK we compose here is bit-identical.
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        success, failure = self._writer.write_signals(
            session_id=session_id,
            request_id=signal_data["request_id"],
            signals=[signal],
            shared_attrs=shared,
            now=now,
        )
        if failure or not success:
            raise RuntimeError(
                f"signal write failed: success={success} failure={failure}"
            )
        timestamp_ms = int(now.timestamp() * 1000)
        return {
            "signal_sk": f"{signal_data['request_id']}#{timestamp_ms}#{source}",
            "stored_at": _isoformat_ms_z(now),
        }

    # -----------------------------------------------------------------------
    # Internals
    # -----------------------------------------------------------------------

    def _query_all(self, kwargs: dict[str, Any]) -> list[dict[str, Any]]:
        """Query DDB and deserialize all items. Single-page only — Limit
        already caps the row count; pagination across pages is reserved for
        scan endpoints."""
        try:
            resp = self._ddb().query(**kwargs)
        except ClientError as exc:
            logger.exception("query failed: %s", exc)
            return []
        return [self._deserialize_item(it) for it in resp.get("Items", [])]

    def _deserialize_item(self, item: dict) -> dict[str, Any]:
        """DDB TypedDict → plain Python dict.

        Numbers come back as Decimal — coerce to int/float for JSON cleanliness.
        """
        out = {}
        for k, v in item.items():
            val = self._deser.deserialize(v)
            # Coerce DDB Decimals so the FastAPI JSON encoder doesn't choke.
            from decimal import Decimal
            if isinstance(val, Decimal):
                val = int(val) if val == val.to_integral_value() else float(val)
            out[k] = val
        return out


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def _item_to_signal(item: dict[str, Any]) -> Signal:
    """Reconstruct a Signal from a DDB row dict. Inverse of the writer's
    item-build path."""
    return Signal(
        source=item.get("source") or "",
        decision=item.get("decision") or "ALLOW",
        reason=item.get("reason"),
        priority=int(item.get("priority") or 0),
        confidence=(float(item["confidence"]) if item.get("confidence") is not None else None),
        threat_type=item.get("threat_type"),
        matched_rule=item.get("matched_rule"),
        severity=item.get("severity"),
        metadata=item.get("metadata") or {},
    )


def _encode_cursor(key: dict) -> str:
    """Opaque base64-encoded LastEvaluatedKey. Consumers must treat as opaque
    (LLD 17 §8.4)."""
    return base64.b64encode(json.dumps(key, default=str).encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> dict:
    raw = base64.b64decode(cursor.encode("ascii")).decode("utf-8")
    return json.loads(raw)
