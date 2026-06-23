"""Per-tenant quota enforcement (LLD-26 §9.3 / WS-E E2).

Two ceilings live on the `sentra-tenants` row's `quota` map, keyed off `plan`:

* **`max_agents`** — checked at **agent import** (cheap, low-frequency): count the
  tenant's agents and reject an import that would exceed the cap. Wired now.

* **`max_validate_rps`** — the *hot path*, so it is **off by default**
  (`quota_enforcement_enabled=False`) and must never add a per-validate hot
  partition. When enabled it uses a **write-sharded atomic counter** (increment a
  random shard, sum on read) and **fails OPEN on any counter error** — a quota
  counter must never become a denial-of-service on legitimate validate traffic.
  Quota is a *commercial* guardrail, not a security boundary (security fail-secure
  is WS-A/B). This is founder-gated (LLD-26 §9.3) — built, inert until flipped.
"""
from __future__ import annotations

import logging
import random
import time
from typing import Optional

from botocore.exceptions import ClientError

from app.config import settings
from app.utils import tenancy
from app.utils.clients import get_clients
from app.services.tenant_service import get_tenant_store

logger = logging.getLogger(__name__)

# Shards spread the per-tenant counter so it isn't a single hot key.
_RPS_SHARDS = 10


class QuotaExceeded(Exception):
    """A tenant exceeded a commercial quota (→ HTTP 429 / QUOTA_EXCEEDED)."""

    def __init__(self, kind: str, limit: int, current: int) -> None:
        super().__init__(f"quota '{kind}' exceeded: {current} >= {limit}")
        self.kind = kind
        self.limit = limit
        self.current = current


def _tenant_quota(tenant_id: str) -> Optional[dict]:
    """The tenant's quota map, or None when there is no registry row (e.g. the
    `default` tenant pre-identity) — in which case no quota applies (no regression)."""
    try:
        tenant = get_tenant_store().get(tenant_id)
    except Exception:  # noqa: BLE001
        logger.warning("quota: tenant lookup failed for %s", tenant_id, exc_info=True)
        return None
    return tenant.quota if tenant else None


def check_agent_quota(current_count: int, adding: int = 1, tenant_id: Optional[str] = None) -> None:
    """Reject an import that would push the tenant over `max_agents` (E2a).
    No-op when the tenant has no registry row or no `max_agents` set."""
    tid = tenant_id or tenancy.current_tenant()
    quota = _tenant_quota(tid)
    if not quota:
        return
    cap = int(quota.get("max_agents", 0))
    if cap <= 0:
        return
    if current_count + adding > cap:
        raise QuotaExceeded("max_agents", cap, current_count + adding)


# --------------------------------------------------------------------------- #
# Hot-path RPS counter (E2b) — OFF by default
# --------------------------------------------------------------------------- #
class QuotaCounter:
    """Write-sharded, fail-open per-tenant validate-RPS counter."""

    def __init__(self) -> None:
        self._dynamodb = get_clients().dynamodb_resource()

    def _table(self):
        return self._dynamodb.Table(settings.dynamodb_quota_counters_table)

    def allow(self, tenant_id: str, max_rps: int) -> bool:
        """Increment the current 1s window's counter (random shard) and return
        whether the tenant is under `max_rps`. **Fails OPEN** on any counter
        error or throttle — quota must never deny legitimate traffic."""
        if max_rps <= 0:
            return True
        window = int(time.time())  # 1-second granularity
        shard = random.randint(0, _RPS_SHARDS - 1)
        counter_key = f"_rps#{window}#{shard}"
        ttl = window + 5  # auto-reap stale window shards
        try:
            self._table().update_item(
                Key={"tenant_id": tenant_id, "counter_key": counter_key},
                UpdateExpression="ADD #c :one SET #t = :ttl",
                ExpressionAttributeNames={"#c": "count", "#t": "ttl"},
                ExpressionAttributeValues={":one": 1, ":ttl": ttl},
            )
            total = self._sum_window(tenant_id, window)
            return total <= max_rps
        except ClientError:
            logger.warning("quota: RPS counter throttled/failed — failing OPEN", exc_info=True)
            return True
        except Exception:  # noqa: BLE001
            logger.warning("quota: RPS counter error — failing OPEN", exc_info=True)
            return True

    def _sum_window(self, tenant_id: str, window: int) -> int:
        resp = self._table().query(
            KeyConditionExpression="tenant_id = :t AND begins_with(counter_key, :p)",
            ExpressionAttributeValues={":t": tenant_id, ":p": f"_rps#{window}#"},
        )
        return sum(int(i.get("count", 0)) for i in resp.get("Items", []))


_counter: Optional[QuotaCounter] = None


def get_quota_counter() -> QuotaCounter:
    global _counter
    if _counter is None:
        _counter = QuotaCounter()
    return _counter


def check_validate_rps(tenant_id: str) -> bool:
    """Hot-path entry. Returns True (allow) unless enforcement is enabled AND the
    tenant is over its `max_validate_rps`. Always True when the feature flag is
    off (the default) → zero hot-path cost until founder-enabled."""
    if not settings.quota_enforcement_enabled:
        return True
    quota = _tenant_quota(tenant_id)
    if not quota:
        return True
    max_rps = int(quota.get("max_validate_rps", 0))
    return get_quota_counter().allow(tenant_id, max_rps)
