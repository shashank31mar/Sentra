"""Opt-in redacted feedback store — WS-E2 / LLD 29 §6.

A SEPARATE, tenant-scoped DynamoDB store of REDACTED-only records, bounded TTL,
OPT-IN per DPA (default OFF), that feeds the offline re-score + retrain loop
(FR-3.14). It is NOT the signal store (LLD 17) and NOT the meter/billing ledger
(WS-H) — conflating them is a consent breach (§6.1). This module owns the
WRITE / EVAL-GATE / DSAR logic; the CDK table construct is stage 3 (this stage
tests against a moto table using the §6.2 schema as the contract).

Invariants enforced here:
  * REDACTED-ONLY (§6.2, I-1): a record whose payload is not marked redacted, or
    that fails the eval-gate re-scan, is NEVER written.
  * OPT-IN default OFF (§6.5): a record is written only when the tenant's
    `sentra-tenants` row carries the DPA-scoped `feedback_opt_in` flag. A
    non-opted-in tenant produces NO record (an accidental default-ON is a
    clause-(b) + consent breach — the flag is conservative-off, mirroring LLD
    27's absent-key trap).
  * EVAL-GATE (§6.3, F3): the write is gated by a STRONGER, INDEPENDENT detector
    (the persist-gate `GateDetector`, NOT the Tier-2 primary — that would be
    circular). A residual hit → skip + `FeedbackRedactionGateFail`.
  * TTL-bounded (§6.2): every record carries a bounded `ttl` (default 90d,
    DPA-scoped placeholder).
  * DSAR (§6.4): `subject_locator = HMAC(per-tenant-salt, subject_key)` at write
    time where a stable subject key exists (else null → TTL-only-deletable). The
    DELETE route deletes every record for a subject via the `subject_locator`
    GSI; tenant A cannot delete tenant B's (tenant-scoped PK).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from botocore.exceptions import ClientError

from app.config import settings
from app.redaction.phi_ner import get_gate_detector
from app.utils import tenancy
from app.utils.clients import get_clients

logger = logging.getLogger(__name__)

# GSI name for subject-targeted DSAR deletion (§6.4). Provisioned by the stage-3
# CDK construct; the moto tests create it under the same name.
SUBJECT_LOCATOR_GSI = "subject-locator-index"


class FeedbackGateFail(Exception):
    """The would-be-persisted record failed the redaction eval-gate (§6.3) — a
    residual identifier survived. The write is skipped, never stored raw."""

    def __init__(self, detected_classes: List[str]) -> None:
        self.detected_classes = detected_classes
        super().__init__(f"feedback eval-gate residual: {detected_classes}")


@dataclass
class FeedbackRecord:
    """One redacted feedback record (§6.2 schema). Payload is REDACTED-only."""

    tenant_id: str
    phase: str
    redacted_payload: Dict[str, Any]
    decision: str
    reason: str
    winning_source: str
    detector_outcomes: Dict[str, Any]
    subject_locator: Optional[str] = None
    ttl_days: int = 90


def _now_ms() -> int:
    return int(time.time() * 1000)


def _record_scan_text(record: FeedbackRecord) -> str:
    """The WHOLE would-be-persisted record as one string for the eval-gate re-scan
    (§5.3.3 / §6.2 FOOTGUN: payload + reason + winning_source + detector_outcomes —
    NOT just the payload, since a `reason` can quote offending free-text)."""
    parts: List[str] = [str(record.redacted_payload), record.reason or "",
                        record.winning_source or "", str(record.detector_outcomes)]
    return "\n".join(p for p in parts if p)


def derive_subject_locator(subject_key: Optional[str], *, tenant_id: str, salt: str) -> Optional[str]:
    """Derive the DSAR `subject_locator` (§6.4).

    Where a stable subject key exists (an authenticated subject_id / a structured
    value present BEFORE masking), return `HMAC(per-tenant-salt, subject_key)` — a
    per-tenant salted hash so it is neither cross-tenant-linkable nor reversible to
    the raw identifier. Where none exists → None (the record is TTL-only-deletable,
    §6.2; do NOT claim subject-targeted deletability for it).
    """
    if not subject_key:
        return None
    if not salt:
        # No per-tenant salt configured → do not emit an unsalted (linkable) locator;
        # concede TTL-only deletion rather than a weaker locator.
        logger.warning("no feedback subject-locator salt for tenant=%s; TTL-only record", tenant_id)
        return None
    return hmac.new(salt.encode(), subject_key.encode(), hashlib.sha256).hexdigest()


class FeedbackStore:
    """Write / eval-gate / DSAR against the redacted feedback table (§6)."""

    def __init__(self) -> None:
        self._dynamodb = get_clients().dynamodb_resource()

    def _table(self):
        return self._dynamodb.Table(settings.dynamodb_feedback_store_table)

    # ---- write path (§6.5) ------------------------------------------------- #
    def write_if_opted_in(
        self,
        record: FeedbackRecord,
        *,
        opted_in: bool,
        redacted: bool,
        subject_key: Optional[str] = None,
    ) -> Optional[str]:
        """Write a redacted record ONLY when all gates pass. Returns the written
        `record_id`, or None when the tenant is not opted in (§6.5 — a non-opted-in
        tenant produces NO record). Raises :class:`FeedbackGateFail` on a residual.

        Gate order (each stricter than the last):
          1. OPT-IN (§6.5, default OFF): not opted in → return None, write nothing.
          2. REDACTED flag (§6.2, I-1): payload not marked redacted → refuse.
          3. EVAL-GATE (§6.3, F3): the stronger INDEPENDENT detector re-scans the
             WHOLE record; a residual → skip + `FeedbackRedactionGateFail`.
        """
        # 1. Opt-in — the ONLY thing that persists is opt-in gated (§6.5). Transient
        # redaction is always-on under the BAA; this store is the consented part.
        if not opted_in:
            return None

        # 2. Redacted-only (I-1): never store an un-redacted payload.
        if not redacted:
            raise FeedbackGateFail(["not-redacted"])

        # 3. Eval-gate — a STRONGER INDEPENDENT re-scan over the whole record (NOT
        # the Tier-2 primary; that would be circular, F3).
        residual = get_gate_detector().find_residual(_record_scan_text(record))
        if residual:
            self._alarm_gate_fail(residual)
            raise FeedbackGateFail(residual)

        record_id = f"{_now_ms()}#{uuid.uuid4().hex}"
        salt = self._tenant_salt(record.tenant_id)
        subject_locator = derive_subject_locator(
            subject_key, tenant_id=record.tenant_id, salt=salt
        )
        ttl_epoch = int(time.time()) + record.ttl_days * 86400
        item: Dict[str, Any] = {
            "tenant_id": record.tenant_id,
            "record_id": record_id,
            "redacted_payload": record.redacted_payload,
            "phase": record.phase,
            "decision": record.decision,
            "reason": record.reason,
            "winning_source": record.winning_source,
            "detector_outcomes": record.detector_outcomes,
            "ttl": ttl_epoch,
            "opt_in": True,
            "redaction_eval_pass": True,
        }
        if subject_locator:
            item["subject_locator"] = subject_locator
        self._table().put_item(Item=item)
        return record_id

    # ---- DSAR / deletion (§6.4) ------------------------------------------- #
    def delete_subject(self, subject_locator: str, *, tenant_id: str) -> int:
        """Delete EVERY record for a subject in THIS tenant via the subject_locator
        GSI (§6.4). Tenant-scoped: the query filters on `tenant_id`, so tenant A
        cannot delete tenant B's records (the route enforces the 403; this method
        never crosses the tenant boundary). Returns the number deleted.

        MUST paginate: a DynamoDB `query` page truncates at 1 MB and returns
        `LastEvaluatedKey` for the rest. A subject that accumulated many feedback
        records (up to the 90-day TTL) can span multiple pages; deleting only page 1
        would leave residual PHI behind while the DSAR route reports success — a
        silent GDPR-erasure breach against the §6.4 "delete every record" claim.

        Collect ALL matching primary keys across every page FIRST, then delete — do
        NOT interleave deletes with the paginated query. Deleting the item the current
        `LastEvaluatedKey` points at and then resuming from that (now-absent) cursor
        makes the engine resume PAST it and skip the remaining page — items would
        survive. Query-all-then-delete keeps the pagination cursor stable, then a
        `BatchWriteItem` writer erases the collected keys."""
        table = self._table()
        keys: List[Dict[str, str]] = []
        start_key: Optional[Dict[str, Any]] = None
        while True:
            kwargs: Dict[str, Any] = {
                "IndexName": SUBJECT_LOCATOR_GSI,
                "KeyConditionExpression": "subject_locator = :sl",
                "FilterExpression": "tenant_id = :t",
                "ExpressionAttributeValues": {":sl": subject_locator, ":t": tenant_id},
            }
            if start_key is not None:
                kwargs["ExclusiveStartKey"] = start_key
            resp = table.query(**kwargs)
            for it in resp.get("Items", []):
                keys.append({"tenant_id": it["tenant_id"], "record_id": it["record_id"]})
            start_key = resp.get("LastEvaluatedKey")
            if not start_key:
                break
        # BatchWriteItem (25/req, auto-batched + retried by the resource writer) so a
        # large subject's erasure is not a delete-per-item round-trip storm.
        if keys:
            with table.batch_writer() as batch:
                for key in keys:
                    batch.delete_item(Key=key)
        return len(keys)

    def query_by_tenant(self, tenant_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Tenant-scoped read (isolation guard for the tests): a query PK-scoped to
        `tenant_id` can never return another tenant's rows (§6.2 / NFR-6)."""
        resp = self._table().query(
            KeyConditionExpression="tenant_id = :t",
            ExpressionAttributeValues={":t": tenant_id},
            Limit=limit,
        )
        return resp.get("Items", [])

    # ---- helpers ---------------------------------------------------------- #
    def _tenant_salt(self, tenant_id: str) -> str:
        """The per-tenant HMAC salt for subject_locator derivation (§6.4). Sourced
        from config (a KMS-backed secret in prod); combined with the tenant_id so a
        locator is never cross-tenant-linkable even under a shared base secret."""
        base = settings.feedback_subject_locator_salt
        if not base:
            return ""
        return hashlib.sha256(f"{base}:{tenant_id}".encode()).hexdigest()

    def _alarm_gate_fail(self, detected_classes: List[str]) -> None:
        """Best-effort `FeedbackRedactionGateFail` alarm (§6.3). Never raises — the
        skip is the security action; the alarm is observability."""
        try:
            import asyncio

            from app.utils.metrics_publisher import MetricsPublisher

            emit = MetricsPublisher().publish_feedback_redaction_gate_fail_metric
            coro = emit(detected_classes=detected_classes)
            try:
                asyncio.get_running_loop().create_task(coro)
            except RuntimeError:
                coro.close()
        except Exception:  # noqa: BLE001 — the alarm must never break the write path
            logger.debug("FeedbackRedactionGateFail alarm skipped", exc_info=True)


def tenant_feedback_opt_in(tenant_id: str) -> bool:
    """Resolve the tenant's DPA-scoped feedback opt-in flag (§6.5, default OFF).

    Reads the `sentra-tenants` row's `feedback_opt_in` attribute. Fail-secure: a
    missing tenant / missing attribute / any read error → False (NO write). An
    accidental default-ON would be a consent breach (§6.5 FOOTGUN)."""
    try:
        from app.services.tenant_service import get_tenant_store
        t = get_tenant_store().get(tenant_id)
        return bool(getattr(t, "feedback_opt_in", False)) if t else False
    except Exception:  # noqa: BLE001 — conservative-off on any resolution error
        logger.debug("feedback opt-in resolution failed for tenant=%s; default OFF", tenant_id)
        return False


_feedback_store: Optional[FeedbackStore] = None


def get_feedback_store() -> FeedbackStore:
    global _feedback_store
    if _feedback_store is None:
        _feedback_store = FeedbackStore()
    return _feedback_store
