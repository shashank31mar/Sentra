"""Residual uncredentialed-agent legacy-fallback window (LLD-26 §7.1.2 / WS-B B1).

The enforce flip is per-TENANT, but credential coverage is per-AGENT — so the
instant a tenant flips to ``enforce`` it can still contain an agent that hasn't
registered a credential yet. Fail-secure would brick that agent immediately. To
make the flip safe to perform *before* coverage is 100%, each not-yet-credentialed
agent gets a **time-boxed, alarmed grace window**: it keeps running on the legacy
self-asserted path ("no worse than today") until a per-agent deadline, then the
window **expires to a hard DENY** — it never silently rides on ``default``.

Design notes
------------
* **Not a security boundary.** The window is strictly *more permissive* than the
  DENY it defers, and only ever applies to ``state == "unverified"`` (no credential
  / no token). Active spoofing — ``IDENTITY_TAMPERED`` (key reuse) and
  ``IDENTITY_MISMATCH`` — is never eligible; the route hard-DENYs those regardless.
* **Deadline is persisted** (``sentra-identity-fallback``) so "expires to DENY"
  survives instance churn — an in-process-only deadline would reset on every cold
  start and never expire. The deadline is fixed at *open* time; changing the window
  config later does not move existing deadlines (deterministic, auditable).
* **Hot-path cheap.** The deadline is immutable once set, so it is cached
  in-process; a flood of unverified requests for the same agent costs one DDB write
  (open) then pure in-memory checks. Rows auto-reap via a TTL past the deadline.
* **Default OFF.** ``identity_fallback_window_seconds == 0`` (the default) disables
  the window entirely → enforce denies an uncredentialed agent immediately (strict).
  Operators set it >0 only while performing a per-tenant enforce flip.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from botocore.exceptions import ClientError

from app.config import settings
from app.utils import tenancy
from app.utils.clients import get_clients

logger = logging.getLogger(__name__)

# Keep a row a while past its deadline so the residual list still shows recently
# expired agents (and so a clock-skewed re-open can't thrash). Auto-reaped by TTL.
_TTL_GRACE_SECONDS = 7 * 24 * 3600


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class FallbackDecision:
    allow: bool
    state: str  # opened | active | expired | disabled
    deadline_ms: Optional[int] = None


@dataclass
class _FallbackRow:
    agent_id: str
    tenant_id: str
    first_seen_ms: int
    deadline_ms: int
    last_seen_ms: int


class FallbackWindowStore:
    """DDB-backed per-agent fallback ledger + in-process deadline cache."""

    def __init__(self) -> None:
        self._cache: Dict[str, _FallbackRow] = {}
        self._lock = asyncio.Lock()

    def _table(self):
        return get_clients().dynamodb_resource().Table(settings.dynamodb_identity_fallback_table)

    # ---- hot path --------------------------------------------------------- #
    async def consider(self, agent_id: str, tenant_hint: Optional[str]) -> FallbackDecision:
        """Decide whether an uncredentialed ``agent_id`` may ride the legacy path.

        Opens the window on first sight (persisting a deadline), returns ``active``
        while inside it, and ``expired`` (deny) once the deadline passes. Never
        raises — a store error fails **secure** (deny), since the window is an
        optional convenience and must not become a way to bypass enforce.
        """
        window = int(settings.identity_fallback_window_seconds or 0)
        if window <= 0:
            return FallbackDecision(allow=False, state="disabled")

        now = _now_ms()
        cached = self._cache.get(agent_id)
        if cached is not None:
            return self._decide(cached, now)

        async with self._lock:
            cached = self._cache.get(agent_id)
            if cached is not None:
                return self._decide(cached, now)
            try:
                row = await asyncio.to_thread(self._open_or_get, agent_id, tenant_hint, window, now)
            except Exception:  # noqa: BLE001 — fail secure (deny), don't open a hole
                logger.warning("fallback store error for agent=%s — denying", agent_id, exc_info=True)
                return FallbackDecision(allow=False, state="expired")
            self._cache[agent_id] = row
            opened = row.first_seen_ms == now
            decision = self._decide(row, now)
            if opened:
                return FallbackDecision(allow=decision.allow, state="opened", deadline_ms=row.deadline_ms)
            return decision

    @staticmethod
    def _decide(row: _FallbackRow, now: int) -> FallbackDecision:
        if now <= row.deadline_ms:
            return FallbackDecision(allow=True, state="active", deadline_ms=row.deadline_ms)
        return FallbackDecision(allow=False, state="expired", deadline_ms=row.deadline_ms)

    def _open_or_get(self, agent_id: str, tenant_hint: Optional[str], window: int, now: int) -> _FallbackRow:
        """Create the row on first sight (idempotent via a conditional put), else
        read the existing one. Runs in a worker thread (boto3 is sync)."""
        table = self._table()
        deadline = now + window * 1000
        ttl = int(deadline / 1000) + _TTL_GRACE_SECONDS
        item = {
            "agent_id": agent_id,
            "tenant_id": tenant_hint or "_unknown",
            "first_seen_ms": now,
            "deadline_ms": deadline,
            "last_seen_ms": now,
            "ttl": ttl,
        }
        try:
            table.put_item(Item=item, ConditionExpression="attribute_not_exists(agent_id)")
            return _FallbackRow(agent_id, item["tenant_id"], now, deadline, now)
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            existing = table.get_item(Key={"agent_id": agent_id}).get("Item") or item
            # Best-effort last_seen bump (observability only; never gates the decision).
            try:
                table.update_item(
                    Key={"agent_id": agent_id},
                    UpdateExpression="SET last_seen_ms = :n",
                    ExpressionAttributeValues={":n": now},
                )
            except ClientError:
                pass
            return _FallbackRow(
                agent_id,
                existing.get("tenant_id", "_unknown"),
                int(existing.get("first_seen_ms", now)),
                int(existing.get("deadline_ms", deadline)),
                now,
            )

    # ---- residual list (WS-C console) ------------------------------------ #
    def list_residual(self, tenant_id: Optional[str] = None) -> List[Dict]:
        """Agents currently on a fallback window (deadline not yet passed), for the
        console's 'onboard or retire before the window closes' view. Low-frequency
        operator read; a scan is fine."""
        table = self._table()
        now = _now_ms()
        out: List[Dict] = []
        start_key = None
        while True:
            kwargs: Dict = {}
            if tenant_id:
                kwargs = {"FilterExpression": "tenant_id = :t",
                          "ExpressionAttributeValues": {":t": tenant_id}}
            if start_key:
                kwargs["ExclusiveStartKey"] = start_key
            try:
                resp = table.scan(**kwargs)
            except ClientError as exc:
                if exc.response["Error"]["Code"] == "ResourceNotFoundException":
                    return out
                raise
            for it in resp.get("Items", []):
                out.append({
                    "agent_id": it.get("agent_id"),
                    "tenant_id": it.get("tenant_id"),
                    "first_seen_ms": int(it.get("first_seen_ms", 0)),
                    "deadline_ms": int(it.get("deadline_ms", 0)),
                    "expired": now > int(it.get("deadline_ms", 0)),
                })
            start_key = resp.get("LastEvaluatedKey")
            if not start_key:
                break
        return out


_store: Optional[FallbackWindowStore] = None


def get_fallback_store() -> FallbackWindowStore:
    global _store
    if _store is None:
        _store = FallbackWindowStore()
    return _store


async def consider_fallback(agent_id: str, tenant_hint: Optional[str]) -> FallbackDecision:
    """Route entry point. Decides + emits the alarm metric (fire-and-forget)."""
    decision = await get_fallback_store().consider(agent_id, tenant_hint)
    if decision.state in ("opened", "active", "expired") and settings.identity_fallback_window_seconds:
        try:
            from app.utils.metrics_publisher import MetricsPublisher
            await MetricsPublisher().publish_identity_fallback_metric(
                decision.state, tenant_hint or tenancy.UNVERIFIED_TENANT
            )
        except Exception:  # noqa: BLE001
            logger.debug("fallback metric publish failed", exc_info=True)
    return decision
