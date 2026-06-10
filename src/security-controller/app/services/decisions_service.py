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
            "next_token": None,  # single-partition Query; not paged in MVP (LLD 21 §11.1)
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

            # Per-request forensic context (the prompt, the caller, the IP) lives as shared attrs on
            # the raw signal rows — surface the first non-empty value so the detail view can show
            # "what was the prompt / who called / from where" without a second round-trip.
            def _first(field: str) -> Optional[Any]:
                return next((it.get(field) for it in group if it.get(field)), None)

            decisions.append({
                "request_id": rid,
                "timestamp_iso": timestamp_iso,
                "user_input": _first("user_input"),
                "agent_id": _first("agent_id"),
                "tool_name": _first("tool_name"),
                "source_ip": _first("source_ip"),
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
            "next_token": None,  # single-partition Query; not paged in MVP (LLD 21 §11.1)
        }

    def scan_decisions(
        self,
        since: Optional[str] = None,
        until: Optional[str] = None,
        agent_id: Optional[str] = None,
        decision: Optional[str] = None,
        threat_type: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        """Paginated time-range scan via GSI 2 — LLD 17 §8.4.

        decision_date is the GSI partition key (YYYY-MM-DD). For a multi-day
        range we'd ideally Query each day's partition; for Phase 1 with
        on-demand low traffic we accept a Scan with FilterExpression on the
        GSI. Cursor round-trips as opaque base64 LastEvaluatedKey.
        """
        # Window: a `cursor` (opaque base64 of a timestamp_ms) advances `until` backward through
        # history so the threat feed can page through ALL decisions, not just the first page. Without
        # a cursor, default to the last 30 days (signal-store TTL is 90d) so there's real history to
        # page through. Explicit since/until still win.
        from datetime import datetime, timedelta, timezone
        if until:
            until_dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
        else:
            until_dt = datetime.now(timezone.utc)
        if cursor:
            try:
                cur_ms = int(base64.b64decode(cursor.encode()).decode())
                until_dt = datetime.fromtimestamp(cur_ms / 1000.0, tz=timezone.utc)
            except Exception:
                logger.warning("ignoring malformed decisions cursor: %r", cursor)
        if since:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        else:
            since_dt = until_dt - timedelta(days=30)

        # Optional filters (agent/decision/threat) become a FilterExpression; the time window is the
        # GSI SORT key (timestamp_ms), expressed in the KeyConditionExpression below — NOT a filter.
        since_ms = int(since_dt.timestamp() * 1000)
        until_ms = int(until_dt.timestamp() * 1000)
        expr_values: dict[str, Any] = {":since": {"N": str(since_ms)}, ":until": {"N": str(until_ms)}}
        expr_names: dict[str, str] = {}
        filter_parts: list[str] = []
        if agent_id:
            filter_parts.append("agent_id = :aid")
            expr_values[":aid"] = {"S": agent_id}
        if decision:
            filter_parts.append("#dec = :d")
            expr_values[":d"] = {"S": decision}
            expr_names["#dec"] = "decision"  # reserved DDB word
        if threat_type:
            filter_parts.append("threat_type = :tt")
            expr_values[":tt"] = {"S": threat_type}
        if session_id:
            filter_parts.append("session_id = :sid")
            expr_values[":sid"] = {"S": session_id}

        # decision_date is the GSI PARTITION key (YYYY-MM-DD), so Query each day in the window,
        # newest-first. The previous Scan+Limit was broken: Scan applies Limit BEFORE the
        # FilterExpression, so on a multi-date table it returned ~0 matches even when the window held
        # hundreds of rows — which is why Live Activity showed nothing. (Cross-day cursor pagination
        # is a follow-up; Live Activity reads the most-recent page.)
        decisions_target = min(limit, 200)
        # Fetch enough SIGNALS to yield ~`decisions_target` grouped DECISIONS. Each validation writes
        # several signals (sigma/policy/trust/ml/context) that group into ONE decision by request_id,
        # so capping signals at `limit` returns ~1 decision — which made the Overview's limit=5 Live
        # Activity look single-agent. Over-fetch signals (bounded), group, then cap decisions.
        # Also paginate per day so an agent_id/decision FilterExpression (applied after each page
        # read) still finds enough matches.
        signal_budget = min(decisions_target * 10, 2000)
        page_size = 200
        max_pages_per_day = 25
        items: list[dict] = []
        day = until_dt.date()
        start_day = since_dt.date()
        while day >= start_day and len(items) < signal_budget:
            last_key: dict | None = None
            for _ in range(max_pages_per_day):
                if len(items) >= signal_budget:
                    break
                q: dict[str, Any] = {
                    "TableName": self.table_name,
                    "IndexName": _GSI_DECISION_DATE,
                    "KeyConditionExpression": "decision_date = :dd AND timestamp_ms BETWEEN :since AND :until",
                    "ExpressionAttributeValues": {**expr_values, ":dd": {"S": day.isoformat()}},
                    "ScanIndexForward": False,  # newest first
                    "Limit": page_size,
                }
                if filter_parts:
                    q["FilterExpression"] = " AND ".join(filter_parts)
                if expr_names:
                    q["ExpressionAttributeNames"] = expr_names
                if last_key:
                    q["ExclusiveStartKey"] = last_key
                try:
                    resp = self._ddb().query(**q)
                except ClientError as exc:
                    logger.exception("scan_decisions query failed: %s", exc)
                    return {"decisions": [], "next_token": None, "total": 0, "error": str(exc)}
                items.extend(self._deserialize_item(it) for it in resp.get("Items", []))
                last_key = resp.get("LastEvaluatedKey")
                if not last_key:
                    break
            day -= timedelta(days=1)
        items = items[:signal_budget]

        # Group signals by request_id and combine — same as get_session_decisions
        # but across sessions. The dashboard's all-events view can render
        # per-request rows uniformly with the per-session view.
        groups: dict[tuple[str, str], list[dict]] = {}
        for it in items:
            key = (it.get("session_id") or "<unknown>", it.get("request_id") or "<unknown>")
            groups.setdefault(key, []).append(it)

        from app.utils.cloud import resolve_cloud_provider

        decisions = []
        for (sid, rid), group in groups.items():
            group.sort(key=lambda x: x.get("timestamp_ms", 0))
            signals_obj = [_item_to_signal(it) for it in group]
            try:
                combined = self._combiner.combine(signals_obj)
            except ValueError:
                continue
            # Representative item for the row's flat fields; prefer the denying signal for threat info.
            rep = next((it for it in group if it.get("decision") == "DENY"), group[-1])
            deny_sig = next((s for s in signals_obj if s.decision == "DENY"), None)
            platform = rep.get("platform")
            timestamp = next((it.get("timestamp_iso") for it in group if it.get("timestamp_iso")), None)
            ts_ms = max((int(it.get("timestamp_ms") or 0) for it in group), default=0)
            decisions.append({
                "_ts_ms": ts_ms,  # internal: ordering + pagination cursor; popped before responding
                # Flat fields the SOC console renders (DecisionItem, LLD 21 §11.2):
                # agent / tool / decision / threat / trust / cloud at the row level.
                "decision_id": f"{sid}:{rid}",
                "session_id": sid,
                "request_id": rid,
                "agent_id": rep.get("agent_id"),
                "agent_name": rep.get("agent_id"),
                "cloud_provider": resolve_cloud_provider({"platform": platform}),
                "platform": platform,
                "decision": combined.decision,
                "threat_type": deny_sig.threat_type if deny_sig else None,
                "tool_name": rep.get("tool_name"),
                "reason": combined.reason,
                "trust_score": rep.get("trust_score_before"),
                "timestamp": timestamp,
                # Backward-compatible detail for drill-down consumers (Streamlit dashboard).
                "combined": {
                    "source": Source.DASHBOARD_COMBINED,
                    "decision": combined.decision,
                    "reason": combined.reason,
                    "winning_source": (combined.metadata or {}).get("winning_source"),
                },
                "signals": [s.to_dict() for s in signals_obj],
            })

        # Newest-first by timestamp_ms, then cap to the requested number of DECISIONS.
        reached_budget = len(items) >= signal_budget
        decisions.sort(key=lambda d: d.get("_ts_ms") or 0, reverse=True)
        more = reached_budget or len(decisions) > decisions_target
        decisions = decisions[:decisions_target]

        # next_token: an opaque base64 of the oldest returned decision's timestamp_ms MINUS 1, so the
        # next page resumes strictly older (no overlap). Emitted only when more rows likely exist
        # (we hit the fetch budget, or grouped more decisions than the page size). Decisions are
        # seconds apart, so the ms-exclusive boundary won't skip a distinct decision.
        next_token = None
        if more and decisions:
            oldest_ms = int(decisions[-1].get("_ts_ms") or 0)
            if oldest_ms > 0:
                next_token = base64.b64encode(str(oldest_ms - 1).encode()).decode()
        for d in decisions:
            d.pop("_ts_ms", None)
        return {
            "decisions": decisions,
            "next_token": next_token,
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
    # Operator verdict (WS-21 T34 — FP/FN feedback capture, silent in P0)
    # -----------------------------------------------------------------------

    _VERDICT_METRIC = {
        "false_positive": "FalsePositiveOverturns",
        "false_negative": "FalseNegativeReports",
    }

    def record_verdict(
        self, decision_id: str, verdict: str, reason: str, operator_id: str
    ) -> dict[str, Any]:
        """Attach an operator verdict to a decision's signal rows.

        decision_id = '<session_id>:<request_id>'. Writes operator_verdict /
        verdict_reason / verdict_by / verdict_at onto every signal row of that
        request, and (for FP/FN) emits a CloudWatch count. P0: stored silently —
        false_positive_pct stays null (LLD 21 §12).

        Raises ValueError (→400) on malformed id, LookupError (→404) when the
        decision has no rows, RuntimeError (→409) if already verdicted.

        NOTE (atomicity, Kiro review): the per-row updates below are sequential
        and NOT transactional. If a write fails mid-loop, some rows carry the
        verdict and some don't; a retry would then hit the `any(...)` 409 guard
        and leave the partial state stuck. At P0 volume (a handful of rows per
        request) this is very unlikely. The hardening is to use a single
        `TransactWriteItems` (≤100 rows) so all rows commit or none do — tracked
        for when verdict volume justifies it.
        """
        if ":" not in decision_id:
            raise ValueError("decision_id must be '<session_id>:<request_id>'")
        session_id, request_id = decision_id.split(":", 1)

        rows = self.get_session_signals(
            session_id=session_id, request_id=request_id
        ).get("signals", [])
        if not rows:
            raise LookupError(f"no decision found for {decision_id}")
        if any(r.get("operator_verdict") for r in rows):
            raise RuntimeError(f"decision {decision_id} already has a verdict")

        from datetime import datetime, timezone
        verdict_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        agent_id = next((r.get("agent_id") for r in rows if r.get("agent_id")), None)

        for row in rows:
            sk = row.get("sk")
            if not sk:
                continue
            self._ddb().update_item(
                TableName=self.table_name,
                Key={"session_id": {"S": session_id}, "sk": {"S": sk}},
                UpdateExpression=(
                    "SET operator_verdict = :v, verdict_reason = :r, "
                    "verdict_by = :o, verdict_at = :t"
                ),
                ExpressionAttributeValues={
                    ":v": {"S": verdict},
                    ":r": {"S": reason},
                    ":o": {"S": operator_id},
                    ":t": {"S": verdict_at},
                },
            )

        self._emit_verdict_metric(verdict, agent_id)
        return {"decision_id": decision_id, "verdict": verdict, "verdict_at": verdict_at}

    def _emit_verdict_metric(self, verdict: str, agent_id: Optional[str]) -> None:
        """Emit FalsePositiveOverturns / FalseNegativeReports (fire-and-forget)."""
        metric_name = self._VERDICT_METRIC.get(verdict)
        if not metric_name:
            return
        try:
            dims = [{"Name": "AgentId", "Value": agent_id}] if agent_id else []
            boto3.client("cloudwatch", region_name=self.region).put_metric_data(
                Namespace="Sentra/SecurityController",
                MetricData=[{
                    "MetricName": metric_name, "Value": 1, "Unit": "Count",
                    "Dimensions": dims,
                }],
            )
        except Exception as exc:  # noqa: BLE001 - metrics must not block the verdict
            logger.warning("verdict metric emit failed (non-blocking): %s", exc)

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
