"""WS-N N9 / lld/40 §8 SEC-5 (D12) — read-access attribution (non-repudiation).

The multi-tenant SOC console is a SOC2 / HIPAA / EU-AI-Act **system of record**, so
"which operator viewed which tenant's forensic records" is itself an audit obligation.
Today only MUTATIONS are attributed; WS-N widened the operator-readable surface to 21
tenant-scoped reads, so every one of those reads must leave an attributable event too —
`ctx.sub` + the resolved `tenant_id` + the query scope (route + key params).

Coverage is GUARANTEED-by-construction, not wired per-route: this is emitted from inside
`resolve_operator_tenant` (deps.py), through which EVERY bound read passes — so a
bound-but-unattributed read is impossible (a new gated read inherits attribution for
free; it cannot be forgotten). We emit only for GET (reads) — mutations have their own
audit trail; double-logging them here would be noise.

Especially the break-glass `_platform` operator-lane reads: a `_platform` operator
defaults to viewer and may read any tenant via `X-Aegion-Tenant`, so the event records
the SPECIFIC resolved `tenant_id` (never `"*"`), making a cross-tenant operator-lane
read non-repudiable. This complements `_audit_platform_read` (which covers the platform
aggregate/detail routes); together they attribute every cross-tenant operator read.

Reuses the existing tamper-evident platform-audit ledger (no second store). Fire-and-
forget: an audit-write failure logs loudly but must never break the read (the read is
already tenant-scoped by the bind; attribution is additive). Note this is the softer
best-effort posture appropriate for a READ trail — a MUTATION's audit stays fail-secure
in its own path; a read is not gated on its attribution write.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Query params worth recording as the read "scope" (bounded — never log arbitrary/
# free-text params, which could carry PII). These are the id/filter keys the reads use.
_SCOPE_PARAMS = (
    "request_id", "session_id", "agent_id", "policy_id", "connection_id",
    "conversation_id", "rule_id", "source", "status", "range", "bucket",
    "cloud_provider", "framework", "risk",
)


def emit_read_access_event(request, *, operator_sub: str, tenant_id: str,
                           is_platform: bool) -> None:
    """Record a read-access event for a bound operator READ. Called from
    ``resolve_operator_tenant`` after the tenant is resolved+bound. GET-only; never
    raises (best-effort attribution — the read is not gated on it)."""
    try:
        method = getattr(request, "method", "GET") or "GET"
        if method.upper() != "GET":
            return  # reads only — mutations have their own audit trail
        path = _safe_path(request)
        scope = _safe_scope(request)
        from app.services.platform_audit import get_platform_audit_store

        get_platform_audit_store().record(
            operator_sub=operator_sub,
            target_tenant=tenant_id,          # the SPECIFIC resolved tenant (never "*")
            what=f"read:{path}",              # e.g. read:/v1/sessions/{id}/trail
            read_type="operator_read",
            decision="READ",
            consent_state=("platform_break_glass" if is_platform else "own_tenant"),
        )
        logger.info(
            "READ_ACCESS operator=%s tenant=%s route=%s scope=%s platform=%s",
            operator_sub, tenant_id, path, scope, is_platform,
        )
    except Exception as e:  # noqa: BLE001 — attribution is best-effort, never break the read
        logger.exception("N9 read-access audit failed (non-blocking): %s", e)


def _safe_path(request) -> str:
    try:
        # The route template (with {param} placeholders) is stable + PII-free; fall
        # back to the raw path if the matched route isn't available.
        route = request.scope.get("route") if hasattr(request, "scope") else None
        if route is not None and getattr(route, "path", None):
            return route.path
        return getattr(getattr(request, "url", None), "path", "") or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def _safe_scope(request) -> Optional[dict]:
    """Extract only the bounded id/filter params (never arbitrary free-text)."""
    try:
        qp = getattr(request, "query_params", None)
        if qp is None:
            return None
        return {k: qp[k] for k in _SCOPE_PARAMS if k in qp}
    except Exception:  # noqa: BLE001
        return None
