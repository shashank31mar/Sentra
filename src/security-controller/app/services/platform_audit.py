"""Append-only audit ledger for platform-admin cross-tenant access (LLD-26 §5.5 / WS-E E3).

Every ``_platform`` cross-tenant read — both the ALLOWs and, crucially, the
consent-DENIED attempts — writes an immutable record here. This is the *enforced*
half of the §10 Q2 audit-&-consent model: consent gates whether the read happens,
and this ledger is the tamper-evident proof of who looked at what, when, and
whether consent was present.

Design notes
------------
* **Immutable by construction.** Rows are write-once (no update/delete path; the
  table is RETAIN + PITR in CDK). PK ``tenant_id`` = the *target* tenant so a
  tenant's full access history is a single-partition query; SK
  ``{timestamp_ms}#{uuid}`` keeps rows ordered and collision-free.
* **Write the DENY before raising.** A consent-denied read must leave a record —
  the denial is exactly what a SOC2 auditor wants to see — so the audit write
  happens *before* the ``403`` is raised.
* **Audit write failure is fail-secure on the read path.** If the ledger write
  itself fails we log loudly but do NOT silently allow an unaudited cross-tenant
  read; the caller treats a write failure on the ALLOW path as a hard error.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Optional

from app.config import settings
from app.utils.clients import get_clients

logger = logging.getLogger(__name__)


def _now_ms() -> int:
    return int(time.time() * 1000)


class PlatformAuditStore:
    """DDB-backed append-only ledger of platform cross-tenant accesses."""

    def __init__(self) -> None:
        self._dynamodb = get_clients().dynamodb_resource()

    def _table(self):
        return self._dynamodb.Table(settings.dynamodb_platform_audit_table)

    def record(
        self,
        *,
        operator_sub: str,
        target_tenant: str,
        what: str,
        read_type: str,
        decision: str,
        consent_state: str,
    ) -> None:
        """Persist one immutable access record. Raises on a write failure so the
        caller can fail-secure on the ALLOW path (never serve an unaudited read)."""
        now = _now_ms()
        self._table().put_item(
            Item={
                "tenant_id": target_tenant,
                "record_id": f"{now:013d}#{uuid.uuid4()}",
                "operator_sub": operator_sub,
                "action": "READ",
                "target_tenant": target_tenant,
                "read_type": read_type,        # aggregate | per-tenant
                "what": what,                  # e.g. tenant.detail, tenants.list
                "decision": decision,          # ALLOW | DENY
                "consent_state": consent_state,  # true | false | n/a-aggregate
                "timestamp_ms": now,
            }
        )


_store: Optional[PlatformAuditStore] = None


def get_platform_audit_store() -> PlatformAuditStore:
    global _store
    if _store is None:
        _store = PlatformAuditStore()
    return _store
