"""
DiscoveryService — Detected-agents inventory (feature §8.1).

The Detected-Agents list is the **union** of two sources, deduped by the
source's native id:
  1. **Imported** — agents that have a registry row (managed by us), any cloud.
  2. **Visible-but-not-imported** — agents the live scan persisted into the
     discovery cache (`bedrock:ListAgents` today) that have no registry row.

Lifecycle status per agent (derived, never hand-set):
  - `not_imported` — scanned, no registry row.
  - `imported`     — registry row exists, but no `/v1/validate` traffic seen.
  - `managed`      — registry row AND validate traffic observed (data flowing).
`imported → managed` flips only on observed validate signals (sticky +
`last_active`). Source of truth = the validation-signal store's agent index.

Dedupe key is `native_resource_id` (Bedrock agentId / ARN, etc.); existing rows
that predate that field fall back to a normalized-name match.
"""
import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from app.config import settings
from app.utils import tenancy
from app.utils.cloud import resolve_cloud_provider

logger = logging.getLogger(__name__)

_PROVIDERS_TOTAL = 3  # aws / gcp / azure

# Lifecycle statuses (feature §8.1).
NOT_IMPORTED = "not_imported"
IMPORTED = "imported"
MANAGED = "managed"

# Hosting cloud → governing runtime/platform, used when a scanned record doesn't
# carry an explicit `platform` (the AWS Bedrock probe omits it; the Azure scanner
# sets it). Keeps imported registry rows' `platform` correct per cloud.
_CLOUD_TO_PLATFORM = {"aws": "bedrock", "azure": "azure_foundry", "gcp": "vertex_ai"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slug(value: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return s or "agent"


def canonical_agent_id(tenant: str, cloud: str, native_resource_id: str) -> str:
    """Canonical, collision-free agent id (feature §10.1):
    ``{tenant}-{cloud}-{slug(tail)}-{hash(native)}``.

    Derived from the **stable native resource id**, NOT the mutable display name
    — Azure deployment names (``gpt-4o-mini``, ``identity``) are unique only
    within one account, so two subscriptions could otherwise collapse to the
    same registry key and cross-govern each other. A short hash of the full
    native id guarantees uniqueness while a readable tail keeps it legible; both
    are deterministic, so re-import resolves to the same id (idempotent).
    """
    tail = _slug(native_resource_id.rsplit("/", 1)[-1])[:40]
    digest = hashlib.sha1(native_resource_id.encode("utf-8")).hexdigest()[:8]
    return f"{tenant}-{cloud}-{tail}-{digest}"


def _norm(name: Optional[str]) -> str:
    """Normalized name for fallback dedupe (case/space/underscore-insensitive)."""
    return (name or "").strip().lower().replace("_", "-")


def _risk_from_severity(breakdown: Optional[Dict[str, Any]]) -> str:
    """Provisional risk heuristic from a policy's severity breakdown."""
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
    """Union read-model (registry ∪ scanned) + import."""

    def __init__(self):
        self.dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)

    # Tables resolved per-call so TENANCY_V2_ENABLED is honored live (T7).
    @property
    def policies_metadata_table(self):
        return self.dynamodb.Table(tenancy.table_name("policies_metadata"))

    @property
    def agent_registry_table(self):
        return self.dynamodb.Table(tenancy.table_name("agent_registry"))

    @property
    def signals_table(self):
        return self.dynamodb.Table(tenancy.table_name("validation_signals"))

    @property
    def discovery_cache_table(self):
        # Born tenant-scoped (no v1/v2 flag): net-new table, PK tenant_id.
        return self.dynamodb.Table(settings.dynamodb_discovery_cache_table)

    # ----------------------------------------------------------------- helpers

    def _scan_all(self, table) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        kwargs: Dict[str, Any] = {}
        while True:
            resp = tenancy.query_or_scan(table, **kwargs)
            items.extend(resp.get("Items", []))
            lek = resp.get("LastEvaluatedKey")
            if not lek:
                break
            kwargs["ExclusiveStartKey"] = lek
        return items

    def _registry_by_agent(self) -> Dict[str, Dict[str, Any]]:
        # Hide internal control-plane infra (matches agent_service / WS-21 D4).
        out: Dict[str, Dict[str, Any]] = {}
        for it in self._scan_all(self.agent_registry_table):
            if it.get("visibility") == "internal":
                continue
            aid = it.get("agent_id")
            if aid:
                out[aid] = it
        return out

    def _policies_by_agent(self) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for pol in self._scan_all(self.policies_metadata_table):
            agent_id = pol.get("agent_id")
            if agent_id and agent_id not in out:
                out[agent_id] = pol
        return out

    def _scanned_agents(self, connection_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Agents the live scan persisted into the discovery cache (tenant-scoped).
        Empty (not an error) if the cache table doesn't exist yet."""
        items: List[Dict[str, Any]] = []
        kwargs: Dict[str, Any] = {
            "KeyConditionExpression": Key("tenant_id").eq(tenancy.current_tenant())
        }
        try:
            while True:
                resp = self.discovery_cache_table.query(**kwargs)
                items.extend(resp.get("Items", []))
                lek = resp.get("LastEvaluatedKey")
                if not lek:
                    break
                kwargs["ExclusiveStartKey"] = lek
        except ClientError:
            logger.warning("discovery-cache unavailable; union falls back to registry only")
            return []
        if connection_id:
            items = [it for it in items if it.get("connection_id") == connection_id]
        return items

    def _last_active(self, agent_ids: List[str]) -> Dict[str, str]:
        """{agent_id: latest validate-signal timestamp_iso} for agents with traffic
        (feature §8.1). Presence ⇒ Managed (sticky)."""
        from app.utils import agent_activity
        return agent_activity.last_active(self.signals_table, agent_ids)

    def _native_id(self, reg: Dict[str, Any], agent_id: str) -> str:
        return reg.get("native_resource_id") or agent_id

    def _build_rows(self, connection_id: Optional[str] = None) -> List[Dict[str, Any]]:
        registry = self._registry_by_agent()
        policies = self._policies_by_agent()
        activity = self._last_active(list(registry.keys()))
        scanned = self._scanned_agents(connection_id)

        rows: List[Dict[str, Any]] = []
        seen_native: set = set()
        seen_name: set = set()

        # 1) Imported (registry) agents — status managed iff validate traffic seen.
        for agent_id, reg in registry.items():
            native = self._native_id(reg, agent_id)
            name = reg.get("name") or agent_id
            pol = policies.get(agent_id)
            last_active = activity.get(agent_id)
            rows.append({
                "id": native,
                "agent_id": agent_id,
                "native_resource_id": native,
                "name": name,
                "cloud_provider": resolve_cloud_provider(reg),
                "framework": reg.get("framework") or "unknown",
                "first_seen": reg.get("created_at") or (pol.get("created_at") if pol else None),
                "risk": _risk_from_severity(pol.get("severity_breakdown")) if pol else "low",
                "status": MANAGED if last_active else IMPORTED,
                "last_active": last_active,
            })
            seen_native.add(native)
            seen_name.add(_norm(name))
            seen_name.add(_norm(agent_id))

        # 2) Scanned-only agents (visible in cloud, not imported) — dedupe by
        #    native id, falling back to normalized name for pre-backfill rows.
        for sc in scanned:
            native = sc.get("native_resource_id")
            name = sc.get("name") or native
            if not native:
                continue
            if native in seen_native or _norm(name) in seen_name:
                continue  # already represented by an imported row
            rows.append({
                "id": native,
                "agent_id": None,
                "native_resource_id": native,
                "name": name,
                "cloud_provider": sc.get("cloud_provider") or "aws",
                "framework": sc.get("framework") or "unknown",
                "first_seen": sc.get("first_seen") or sc.get("last_scanned"),
                "risk": "low",  # provisional until tool introspection (T62)
                "status": NOT_IMPORTED,
                "last_active": None,
            })
            seen_native.add(native)
            seen_name.add(_norm(name))

        return rows

    # ------------------------------------------------------------------ reads

    async def list_discovered(
        self,
        cloud_provider: Optional[str] = None,
        framework: Optional[str] = None,
        risk: Optional[str] = None,
        status: Optional[str] = None,
        connection_id: Optional[str] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        rows = self._build_rows(connection_id)
        if cloud_provider:
            rows = [r for r in rows if r["cloud_provider"] == cloud_provider]
        if framework:
            rows = [r for r in rows if r["framework"] == framework]
        if risk:
            rows = [r for r in rows if r["risk"] == risk]
        if status:
            rows = [r for r in rows if r["status"] == status]

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
            "unmanaged": sum(1 for r in rows if r["status"] == NOT_IMPORTED),
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
        """Promote agents to managed (registry rows). `agent_ids` are the union
        rows' `id` (= native_resource_id). Each is resolved from the scanned
        cache or (legacy) a policy artifact; importing stores `native_resource_id`
        so future scans dedupe exactly.

        Raises ValueError (→400) on empty input, LookupError (→422) when none of
        the ids resolve. Per-row status handles partial success.
        """
        if not agent_ids:
            raise ValueError("agent_ids is required and must be non-empty")

        registry = self._registry_by_agent()
        policies = self._policies_by_agent()
        scanned_by_native = {s.get("native_resource_id"): s for s in self._scanned_agents()}
        # Registry index by native id — the ONLY safe dedupe key for scanned
        # agents (a display-name match would falsely collapse two distinct
        # deployments that share a generic name like "gpt-4o-mini").
        reg_native = {self._native_id(r, aid): aid for aid, r in registry.items()}

        resolvable = [
            i for i in agent_ids
            if i in scanned_by_native or i in policies or i in reg_native
        ]
        if not resolvable:
            raise LookupError("none of the requested ids resolve to a scanned or policy-declared agent")

        results: List[Dict[str, Any]] = []
        imported = 0
        now = _now_iso()
        for ident in agent_ids:
            sc = scanned_by_native.get(ident)
            pol = policies.get(ident)

            # Already imported? Dedupe strictly on the stable native id (and, for
            # the legacy policy path, on the policy's own agent_id).
            existing = reg_native.get(ident)
            if not existing and ident in registry:
                existing = ident
            if existing:
                results.append({"discovery_id": ident, "agent_id": existing,
                                "status": "skipped", "reason": "already managed"})
                continue

            if sc:
                # Imported from a live cloud scan (any cloud). The canonical id
                # is derived from the STABLE native resource id, not the mutable
                # deployment/display name (feature §10.1) — see canonical_agent_id.
                native = ident
                cloud = sc.get("cloud_provider") or "aws"
                platform = sc.get("platform") or _CLOUD_TO_PLATFORM.get(cloud, "sentra")
                display_name = sc.get("name") or native
                agent_id = canonical_agent_id(tenancy.current_tenant(), cloud, native)
            elif pol:
                # Legacy policy-derived import (agent_id is already the policy's id).
                agent_id = ident
                native = ident
                cloud = resolve_cloud_provider({"platform": "sentra"})
                platform = "sentra"
                display_name = pol.get("name") or agent_id
            else:
                results.append({"discovery_id": ident, "agent_id": None,
                                "status": "failed", "reason": "not found in scan or policy"})
                continue

            registry_item = {
                "agent_id": agent_id,
                "native_resource_id": native,
                "name": display_name,
                "status": "active",
                "platform": platform,
                "cloud_provider": cloud,
                "security_type": "secured",
                "visibility": "external",
                "type": "action",
                "enforcement_mode": enforcement_mode,
                "source_policy_id": pol.get("policy_id") if pol else None,
                "created_at": now,
                "updated_at": now,
            }
            # Carry placement/capability fields the scanner supplied (Azure sets
            # region/model/framework; tools are operator-supplied later — feature
            # §7/§15). Only stamp when present so AWS rows keep their lean shape.
            if sc:
                for src, dst in (("region", "cloud_region"), ("model", "foundation_model"),
                                 ("framework", "framework")):
                    if sc.get(src):
                        registry_item[dst] = sc[src]
                if sc.get("tools"):
                    registry_item["allowed_tools"] = sc["tools"]
            tenancy.stamp_base_item(registry_item)
            self.agent_registry_table.put_item(Item=registry_item)
            imported += 1
            results.append({"discovery_id": ident, "agent_id": agent_id, "status": "managed"})
        return {"imported": imported, "agents": results}
