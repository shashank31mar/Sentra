"""
DiscoveryService — WS-21 Phase 3 (T31/T32). STATIC, policy-derived discovery.

Discovery is a **read-model** over existing data: agents declared in policy
artifacts (`sentra-policies-metadata`) joined against the managed inventory
(`sentra-agent-registry`). No new tables, no async scanner — dynamic discovery
(runtime request-path observation) is deferred to WS-21 T62.

`cloud_provider`/`framework` aren't in policy metadata, so they're sourced from
the registry when the agent is managed, else defaulted. `risk` is a provisional
heuristic from the policy's severity breakdown (LLD 21 §11.3 — label as
provisional in the UI until T62).
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import boto3

from app.config import settings
from app.utils.cloud import resolve_cloud_provider

logger = logging.getLogger(__name__)

_PROVIDERS_TOTAL = 3  # aws / gcp / azure


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _risk_from_severity(breakdown: Optional[Dict[str, Any]]) -> str:
    """Provisional risk heuristic from a policy's severity breakdown (T31)."""
    b = breakdown or {}
    def _n(k: str) -> int:
        try:
            return int(b.get(k, 0) or 0)
        except (TypeError, ValueError):
            return 0
    if _n("critical") or _n("high"):
        return "high"
    if _n("medium") or _n("med"):
        return "med"
    return "low"


def _is_within_24h(ts: Any) -> bool:
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt) < timedelta(hours=24)
    except (ValueError, TypeError):
        return False


class DiscoveryService:
    """Read-model + import over policy artifacts and the agent registry."""

    def __init__(self):
        self.dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
        self.policies_metadata_table = self.dynamodb.Table(settings.dynamodb_policies_metadata_table)
        self.agent_registry_table = self.dynamodb.Table(settings.dynamodb_agent_registry_table)

    # ----------------------------------------------------------------- helpers

    def _scan_all(self, table) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        kwargs: Dict[str, Any] = {}
        while True:
            resp = table.scan(**kwargs)
            items.extend(resp.get("Items", []))
            lek = resp.get("LastEvaluatedKey")
            if not lek:
                break
            kwargs["ExclusiveStartKey"] = lek
        return items

    def _registry_by_agent(self) -> Dict[str, Dict[str, Any]]:
        return {it.get("agent_id"): it for it in self._scan_all(self.agent_registry_table)}

    def _policies_by_agent(self) -> Dict[str, Dict[str, Any]]:
        """First policy seen per agent_id (one governing policy per agent)."""
        out: Dict[str, Dict[str, Any]] = {}
        for pol in self._scan_all(self.policies_metadata_table):
            agent_id = pol.get("agent_id")
            if agent_id and agent_id not in out:
                out[agent_id] = pol
        return out

    def _build_rows(self) -> List[Dict[str, Any]]:
        registry = self._registry_by_agent()
        rows: List[Dict[str, Any]] = []
        for agent_id, pol in self._policies_by_agent().items():
            reg = registry.get(agent_id)
            rows.append({
                "id": agent_id,
                "name": pol.get("name") or agent_id,
                "cloud_provider": resolve_cloud_provider(reg),
                "framework": "unknown",  # not available statically; T62 (dynamic)
                "first_seen": pol.get("created_at"),
                "risk": _risk_from_severity(pol.get("severity_breakdown")),
                "status": "managed" if reg else "unmanaged",
            })
        return rows

    # ------------------------------------------------------------------ reads

    async def list_discovered(
        self,
        cloud_provider: Optional[str] = None,
        framework: Optional[str] = None,
        risk: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        rows = self._build_rows()
        if cloud_provider:
            rows = [r for r in rows if r["cloud_provider"] == cloud_provider]
        if framework:
            rows = [r for r in rows if r["framework"] == framework]
        if risk:
            rows = [r for r in rows if r["risk"] == risk]
        if status:
            rows = [r for r in rows if r["status"] == status]

        # Honor limit/cursor (Kiro review). The read-model is fully in memory, so
        # the opaque cursor encodes a simple offset (not a DDB key). Canonical
        # next_token per LLD 21 §11.1. decode_cursor raises ValueError → 400.
        from app.utils.pagination import decode_cursor, encode_cursor
        total = len(rows)
        limit = max(1, min(int(limit), 200))
        offset = int(decode_cursor(cursor).get("offset", 0)) if cursor else 0
        page = rows[offset:offset + limit]
        next_token = (
            encode_cursor({"offset": offset + limit}) if offset + limit < total else None
        )
        return {"total": total, "agents": page, "next_token": next_token}

    async def summary(self) -> Dict[str, Any]:
        rows = self._build_rows()
        providers = {r["cloud_provider"] for r in rows if r["cloud_provider"] != "unknown"}
        return {
            "detected": len(rows),
            "unmanaged": sum(1 for r in rows if r["status"] == "unmanaged"),
            "new_24h": sum(1 for r in rows if _is_within_24h(r["first_seen"])),
            "providers_connected": len(providers),
            "providers_total": _PROVIDERS_TOTAL,
            "last_scan": _now_iso(),
        }

    async def platforms(self) -> Dict[str, Any]:
        rows = self._build_rows()
        counts: Dict[str, int] = {}
        for r in rows:
            cp = r["cloud_provider"]
            if cp != "unknown":
                counts[cp] = counts.get(cp, 0) + 1
        providers = [
            {"cloud_provider": cp, "agents": n, "status": "idle", "last_scan": _now_iso()}
            for cp, n in sorted(counts.items())
        ]
        return {"providers": providers}

    # ----------------------------------------------------------------- import

    async def import_agents(
        self, agent_ids: List[str], enforcement_mode: str = "monitor"
    ) -> Dict[str, Any]:
        """Promote discovered agents to managed (D2 contract).

        Raises ValueError (→400) on empty input, LookupError (→422) when no
        requested id maps to a policy. Per-row status handles partial success.
        """
        if not agent_ids:
            raise ValueError("agent_ids is required and must be non-empty")

        policies = self._policies_by_agent()
        registry = self._registry_by_agent()
        if all(aid not in policies for aid in agent_ids):
            raise LookupError("none of the requested agent_ids are declared in a policy")

        results: List[Dict[str, Any]] = []
        imported = 0
        now = _now_iso()
        for agent_id in agent_ids:
            pol = policies.get(agent_id)
            if not pol:
                results.append({"discovery_id": agent_id, "agent_id": None,
                                "status": "failed", "reason": "no governing policy"})
                continue
            if agent_id in registry:
                results.append({"discovery_id": agent_id, "agent_id": agent_id,
                                "status": "skipped", "reason": "already managed"})
                continue
            self.agent_registry_table.put_item(Item={
                "agent_id": agent_id,
                "name": pol.get("name") or agent_id,
                "status": "active",
                "platform": "sentra",
                # derive from platform so the API never emits an unmapped value;
                # real platform/cloud is refined on enrich / dynamic discovery (T62)
                "cloud_provider": resolve_cloud_provider({"platform": "sentra"}),
                "security_type": "secured",
                "visibility": "external",
                "type": "action",
                "enforcement_mode": enforcement_mode,
                "source_policy_id": pol.get("policy_id"),
                "created_at": now,
                "updated_at": now,
            })
            imported += 1
            results.append({"discovery_id": agent_id, "agent_id": agent_id, "status": "managed"})
        return {"imported": imported, "agents": results}
