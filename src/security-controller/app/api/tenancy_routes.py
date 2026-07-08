"""Multi-tenancy control-plane API (LLD-26 §3 / §6 — WS-A A2, WS-D D2/D3/D4/D5).

Endpoints for: agent credentials (register/list/rotate/revoke), tenant lifecycle
(create/get/update/delete), membership + invites, and ``GET /v1/me`` (the
role + membership bootstrap the console uses to render role-conditional UI).

Every route is behind ALB OIDC (verified in-app via ``verify_alb_oidc``) and,
where it mutates, an RBAC ``require_role`` gate. Tenant scoping is server-side:
the operator's tenant is resolved from their membership, never trusted from the
client. Ownership of an agent is asserted with a **delimited** prefix check
(``agent_id.startswith(tenant + "-")``) so a short tenant id can't match a longer
one (LLD-26 §3.3 / WS-A A2).
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.deps import (
    OperatorContext,
    require_platform,
    require_role,
    resolve_operator_tenant,
    role_satisfies,
    verify_alb_oidc,
)
# `_assert_owns_agent` is now the single ownership authority in app.api.ownership
# (WS-M M0.1). Re-exported here under the same name so the existing gate call
# sites repoint with no behaviour change (delimited-prefix, 403 on mismatch).
from app.api.ownership import _assert_owns_agent_compat as _assert_owns_agent
from app.config import settings
from app.services.credentials_service import (
    CredentialValidationError,
    get_credential_cache,
    get_credential_store,
)
from app.services.tenant_service import (
    TenantError,
    get_member_store,
    get_tenant_store,
)
from app.utils import tenancy

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1")

# =========================================================================== #
# WS-G G0.2 / D14 (ADR-039) — PUBLIC org resolver (org-first login)
#
# `resolve_org(org) -> {tenant_id}` turns a typed org NAME into the opaque
# tenant slug the org-first login flow stashes to sessionStorage before Cognito.
# It is mounted on a NON-`/v1` public path so it is NOT caught by the priority-5
# `ConsoleApiListenerRule` (which 401s ALL unauth `/v1/*` — compute_stack.py:967).
# It carries NO auth by design (it runs BEFORE sign-in) and returns ONLY the
# tenant_id — never counts / members / plan / status (zero tenant data leak).
# Org-NAME enumeration is ACCEPTED (founder 2026-07-08, LLD v1.6 40:10): a miss is
# an honest 404, NOT a fake-200 miss==hit. An internal fault fails CLOSED (5XX,
# never a fake-200). Per-IP burst throttled so an unauth endpoint can't be swept.
# =========================================================================== #
public_router = APIRouter(tags=["public"])

# In-process per-IP token bucket. Deliberately lightweight (no DDB round-trip on
# an unauth path): a fixed-window counter keyed by client IP. Multi-worker means
# the effective ceiling is `_RESOLVE_ORG_BURST * n_workers`, which is fine — this
# is a coarse brute-force/sweep brake, not a billing quota. Fail-safe: on any
# limiter bookkeeping error we DENY (429) rather than wave the request through.
_RESOLVE_ORG_BURST = 20          # requests
_RESOLVE_ORG_WINDOW_S = 10.0     # per this many seconds, per IP
_resolve_org_hits: Dict[str, "tuple[float, int]"] = {}
_resolve_org_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    """First hop of X-Forwarded-For (real client behind the ALB/API-GW), else the
    socket peer. Mirrors the `/validate` source-IP derivation (routes.py:184)."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _resolve_org_rate_ok(ip: str) -> bool:
    """Fixed-window per-IP throttle. Returns False once the burst ceiling is hit
    inside the current window. Fail-secure: bookkeeping trouble → throttle."""
    now = time.monotonic()
    try:
        with _resolve_org_lock:
            window_start, count = _resolve_org_hits.get(ip, (now, 0))
            if now - window_start >= _RESOLVE_ORG_WINDOW_S:
                window_start, count = now, 0
            count += 1
            _resolve_org_hits[ip] = (window_start, count)
            return count <= _RESOLVE_ORG_BURST
    except Exception:  # noqa: BLE001 — a limiter fault must never fail OPEN
        logger.warning("resolve_org rate-limiter bookkeeping failed for ip=%s", ip, exc_info=True)
        return False


@public_router.get("/public/resolve-org")
async def resolve_org(org: str, request: Request) -> Dict:
    """Public org-name → ``{tenant_id}`` resolver for the org-first login flow (D14).

    Contract (do NOT drift — the frontend org page + G2.12 consume this):
      * hit   → 200 ``{"tenant_id": "<slug>"}`` and NOTHING else.
      * miss  → 404 ``{"error": "org not found — check spelling"}`` (enumeration OK).
      * fault → 5XX (fail-closed; never a fake-200 wrapping an error).
      * burst → 429 (per-IP throttle).
    """
    ip = _client_ip(request)
    if not _resolve_org_rate_ok(ip):
        # Honest 429 — the client backs off; no tenant data touched.
        raise HTTPException(status_code=429, detail="too many requests — slow down")

    name = (org or "").strip()
    if not name:
        # An empty query is a miss, not a fault (nothing to look up).
        raise HTTPException(status_code=404, detail="org not found — check spelling")

    try:
        tenant_id = get_tenant_store().resolve_org_to_tenant_id(name)
    except Exception:  # noqa: BLE001 — registry read/fault → fail CLOSED (never fake-200)
        # Log the internal detail server-side; return ONLY a sanitized 5XX (the
        # honest fault status the client decides on — engineering error-contract).
        logger.error("resolve_org registry lookup failed for org=%r", name, exc_info=True)
        raise HTTPException(status_code=503, detail="org lookup temporarily unavailable")

    if not tenant_id:
        # Miss → honest 404. Do NOT advance the operator to Cognito with nothing
        # stashed; the org page keeps them put (footgun 3).
        raise HTTPException(status_code=404, detail="org not found — check spelling")

    # ONLY the id — never counts/members/plan/status (footgun 2 / §C.2).
    return {"tenant_id": tenant_id}


# =========================================================================== #
# GET /v1/me — role + memberships bootstrap (D3b)
# =========================================================================== #
@router.get("/me")
async def get_me(ctx: OperatorContext = Depends(resolve_operator_tenant)) -> Dict:
    return {
        "sub": ctx.sub,
        "email": ctx.email,
        "tenant_id": ctx.tenant_id,
        "role": ctx.role,
        "is_platform": ctx.is_platform,
        "memberships": [
            {"tenant_id": m.tenant_id, "role": m.role, "is_primary": m.is_primary}
            for m in (ctx.memberships or [])
        ],
    }


# =========================================================================== #
# Agent credentials (WS-A A2)
# =========================================================================== #
class CredentialRegisterRequest(BaseModel):
    public_key: str = Field(..., description="PEM or JWK ES256 (P-256) public key")
    alg: str = Field(default="ES256")
    not_after: Optional[int] = Field(default=None, description="Validity end (epoch ms)")


@router.post("/agents/{agent_id}/credentials", status_code=201)
async def register_credential(
    agent_id: str,
    body: CredentialRegisterRequest,
    ctx: OperatorContext = Depends(require_role("admin")),
) -> Dict:
    _assert_owns_agent(ctx, agent_id)
    try:
        kid = get_credential_store().register(
            tenant_id=ctx.tenant_id,
            agent_id=agent_id,
            public_key=body.public_key,
            alg=body.alg,
            not_after=body.not_after,
            created_by=ctx.sub,
        )
    except CredentialValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"kid": kid, "agent_id": agent_id, "status": "active"}


@router.get("/agents/{agent_id}/credentials")
async def list_credentials(
    agent_id: str,
    ctx: OperatorContext = Depends(resolve_operator_tenant),
) -> Dict:
    _assert_owns_agent(ctx, agent_id)
    creds = get_credential_store().list_for_agent(ctx.tenant_id, agent_id)
    return {
        "agent_id": agent_id,
        "credentials": [
            {"kid": c.kid, "status": c.status, "alg": c.alg,
             "not_before": c.not_before, "not_after": c.not_after}
            for c in creds  # never any private material
        ],
    }


@router.get("/identity/residual-agents")
async def list_residual_agents(
    ctx: OperatorContext = Depends(resolve_operator_tenant),
) -> Dict:
    """Agents in this tenant currently riding the WS-B B1 legacy-fallback window
    (uncredentialed, enforce-flipped, on borrowed time). The console surfaces this
    so operators onboard or retire them before the window closes (LLD-26 §7.1.2 /
    WS-C C2). Read-only; any role may view."""
    from app.services.fallback_service import get_fallback_store

    residual = get_fallback_store().list_residual(ctx.tenant_id)
    return {"tenant_id": ctx.tenant_id, "residual_agents": residual, "count": len(residual)}


@router.post("/agents/{agent_id}/credentials/{kid}/rotate")
async def rotate_credential(
    agent_id: str,
    kid: str,
    ctx: OperatorContext = Depends(require_role("editor")),
) -> Dict:
    _assert_owns_agent(ctx, agent_id)
    ok = get_credential_store().set_status(ctx.tenant_id, agent_id, kid, "rotating")
    if not ok:
        raise HTTPException(status_code=404, detail="credential not found")
    return {"kid": kid, "status": "rotating"}


@router.delete("/agents/{agent_id}/credentials/{kid}")
async def revoke_credential(
    agent_id: str,
    kid: str,
    ctx: OperatorContext = Depends(require_role("admin")),
) -> Dict:
    _assert_owns_agent(ctx, agent_id)
    store = get_credential_store()
    ok = store.set_status(ctx.tenant_id, agent_id, kid, "revoked")
    if not ok:
        raise HTTPException(status_code=404, detail="credential not found")
    # Bump the shared revoked-since epoch so every task's cache learns of this
    # revoke within one refresh interval (A3.1), not just on cache TTL expiry.
    try:
        store.bump_revocation_epoch()
        get_credential_cache().invalidate_local(kid)
    except Exception:  # noqa: BLE001 — best-effort; TTL still bounds it
        logger.warning("revoked-since bump failed for kid=%s", kid, exc_info=True)
    return {"kid": kid, "status": "revoked"}


# =========================================================================== #
# Tenant lifecycle (WS-D D2/D4)
# =========================================================================== #
class TenantCreateRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=200)
    plan: str = Field(default="trial")


@router.post("/tenants", status_code=201)
async def create_tenant(body: TenantCreateRequest, request: Request) -> Dict:
    """Provision a tenant and make the creating operator its ``owner``. Auth is
    just an authenticated operator (a first-tenant creator has no membership yet,
    so this can't depend on ``resolve_operator_tenant``).

    Self-serve creation ALWAYS mints an opaque ``t_<slug>`` id. A
    customer-domain label (e.g. ``acme-com``) is **not** self-serve: it implies a
    verified corporate-identity claim, and honoring an unverified ``verified_domain``
    from the request body was a tenant-takeover/squatting vector (#2 / §6.2). A
    verified-domain slug can only be set via Sentra-staff provisioning once the
    DNS-TXT / email challenge exists; it is intentionally absent here."""
    claims = verify_alb_oidc(request)
    sub = claims["sub"]

    try:
        # tenant_id=None → minted opaque slug (never customer-chosen free text).
        tenant = get_tenant_store().create(
            display_name=body.display_name, plan=body.plan, created_by=sub,
        )
    except TenantError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    members = get_member_store()
    is_first = not members.by_operator(sub)
    members.add(sub, tenant.tenant_id, role="owner", is_primary=is_first, invited_by="self")
    return {"tenant_id": tenant.tenant_id, "display_name": tenant.display_name,
            "plan": tenant.plan, "status": tenant.status, "role": "owner"}


@router.get("/tenants/{tenant_id}")
async def get_tenant(
    tenant_id: str,
    ctx: OperatorContext = Depends(resolve_operator_tenant),
) -> Dict:
    if tenant_id != ctx.tenant_id and not ctx.is_platform:
        raise HTTPException(status_code=403, detail="not a member of tenant")
    tenant = get_tenant_store().get(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    return {
        "tenant_id": tenant.tenant_id, "display_name": tenant.display_name,
        "status": tenant.status, "plan": tenant.plan,
        "identity_mode": tenant.identity_mode, "quota": tenant.quota,
    }


class TenantUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    identity_mode: Optional[str] = None  # off|shadow|enforce — the rollout control
    status: Optional[str] = None  # active|suspended (deletion has its own route)
    platform_read_consent: Optional[bool] = None  # WS-E E3 cross-tenant consent


@router.patch("/tenants/{tenant_id}")
async def update_tenant(
    tenant_id: str,
    body: TenantUpdateRequest,
    ctx: OperatorContext = Depends(require_role("admin")),
) -> Dict:
    if tenant_id != ctx.tenant_id and not ctx.is_platform:
        raise HTTPException(status_code=403, detail="not a member of tenant")
    store = get_tenant_store()
    try:
        if body.display_name is not None:
            # The one free-text mutable field; admin+ may rename (no owner gate).
            store.set_display_name(tenant_id, body.display_name)
        if body.identity_mode is not None:
            # Flipping a tenant to `enforce` is a gated rollout action (WS-B B1) —
            # owner-only, never an admin self-serve.
            if body.identity_mode == "enforce" and ctx.role != "owner" and not ctx.is_platform:
                raise HTTPException(status_code=403, detail="enforce flip requires owner")
            store.set_identity_mode(tenant_id, body.identity_mode)
        if body.status is not None:
            if body.status not in ("active", "suspended"):
                raise HTTPException(status_code=400, detail="status must be active|suspended")
            store.set_status(tenant_id, body.status)
        if body.platform_read_consent is not None:
            # Consenting to Sentra-staff cross-tenant reads is a trust decision —
            # owner-only (or platform), never an admin self-serve (WS-E E3).
            if ctx.role != "owner" and not ctx.is_platform:
                raise HTTPException(status_code=403,
                                    detail="platform_read_consent requires owner")
            store.set_platform_read_consent(tenant_id, body.platform_read_consent)
    except TenantError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    tenant = store.get(tenant_id)
    return {"tenant_id": tenant_id, "display_name": tenant.display_name,
            "identity_mode": tenant.identity_mode,
            "status": tenant.status, "platform_read_consent": tenant.platform_read_consent}


@router.delete("/tenants/{tenant_id}")
async def delete_tenant(
    tenant_id: str,
    ctx: OperatorContext = Depends(require_role("owner")),
) -> Dict:
    """Begin staged, resumable deletion (D5): mark `deleting` and revoke
    credentials. The destructive live-store purge runs out-of-band behind an
    explicit sign-off (it is irreversible) — see app.services.tenant_purge."""
    if tenant_id != ctx.tenant_id and not ctx.is_platform:
        raise HTTPException(status_code=403, detail="not a member of tenant")
    store = get_tenant_store()
    try:
        store.set_status(tenant_id, "deleting")
    except TenantError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    revoked = get_credential_store().revoke_all_for_tenant(tenant_id)
    return {"tenant_id": tenant_id, "status": "deleting", "credentials_revoked": revoked,
            "note": "live-store purge runs out-of-band after sign-off (irreversible)"}


# =========================================================================== #
# Membership & invites (WS-D D2/D3)
# =========================================================================== #
@router.get("/tenants/{tenant_id}/members")
async def list_members(
    tenant_id: str,
    ctx: OperatorContext = Depends(require_role("admin")),
) -> Dict:
    if tenant_id != ctx.tenant_id and not ctx.is_platform:
        raise HTTPException(status_code=403, detail="not a member of tenant")
    members = get_member_store().by_tenant(tenant_id)
    return {"tenant_id": tenant_id,
            "members": [{"operator_sub": m.operator_sub, "role": m.role,
                         "is_primary": m.is_primary} for m in members]}


class InviteCreateRequest(BaseModel):
    email: str
    role: str = Field(default="viewer")


@router.post("/tenants/{tenant_id}/invites", status_code=201)
async def create_invite(
    tenant_id: str,
    body: InviteCreateRequest,
    ctx: OperatorContext = Depends(require_role("admin")),
) -> Dict:
    if tenant_id != ctx.tenant_id and not ctx.is_platform:
        raise HTTPException(status_code=403, detail="not a member of tenant")
    # No privilege escalation: an inviter cannot grant a role above their own
    # (an admin minting an `owner` invite was a self-escalation path, #1).
    if not role_satisfies(ctx.role, body.role):
        raise HTTPException(status_code=403, detail="cannot invite a role above your own")
    try:
        token = get_member_store().create_invite(
            tenant_id=tenant_id, email=body.email, role=body.role, invited_by=ctx.sub,
        )
    except TenantError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"invite_token": token, "tenant_id": tenant_id, "role": body.role}


class InviteRedeemRequest(BaseModel):
    invite_token: str


@router.post("/invites/redeem", status_code=201)
async def redeem_invite(body: InviteRedeemRequest, request: Request) -> Dict:
    """Redeem an invite into a real membership. Auth is an authenticated operator
    (who may have no membership yet)."""
    claims = verify_alb_oidc(request)
    sub = claims["sub"]
    try:
        membership = get_member_store().redeem_invite(
            body.invite_token, sub, redeemer_email=claims.get("email", ""),
        )
    except TenantError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"tenant_id": membership.tenant_id, "role": membership.role}


@router.delete("/tenants/{tenant_id}/members/{operator_sub}")
async def remove_member(
    tenant_id: str,
    operator_sub: str,
    ctx: OperatorContext = Depends(require_role("admin")),
) -> Dict:
    if tenant_id != ctx.tenant_id and not ctx.is_platform:
        raise HTTPException(status_code=403, detail="not a member of tenant")
    if operator_sub == ctx.sub:
        raise HTTPException(status_code=400, detail="cannot remove yourself")
    members = get_member_store()
    roster = members.by_tenant(tenant_id)
    target = next((m for m in roster if m.operator_sub == operator_sub), None)
    if target is None:
        raise HTTPException(status_code=404, detail="member not found")
    # An admin can't act on a higher-privileged member (e.g. remove an owner), #8.
    if not role_satisfies(ctx.role, target.role) and not ctx.is_platform:
        raise HTTPException(status_code=403, detail="cannot remove a higher-privileged member")
    # Never strand a tenant with no owner.
    if target.role == "owner" and sum(1 for m in roster if m.role == "owner") <= 1:
        raise HTTPException(status_code=400, detail="cannot remove the last owner")
    members.remove(operator_sub, tenant_id)
    return {"removed": operator_sub, "tenant_id": tenant_id}


# =========================================================================== #
# Platform-admin (internal ops) console — WS-E E3 (LLD-26 §5.5 / §10 Q2)
# Gated by the reserved `_platform` capability, NOT a tenant role. Reads the
# tenant/member REGISTRIES (allowed for `_platform`); every cross-tenant access
# is enforced-audited: a per-tenant read DENIES (403) unless the target tenant has
# granted `platform_read_consent`, and EVERY access (allow or deny) writes an
# immutable record to `sentra-platform-audit-records`. This is the enforced half
# of the §10 Q2 audit-&-consent model.
#
# An AGGREGATE read (target `*`) is `_platform`-only by construction and carries no
# single tenant's data, so it is allowed without per-tenant consent but is still
# audited. Cross-tenant CloudWatch *metric aggregation* remains out of scope here
# (registry reads only).
# =========================================================================== #
def _audit_platform_read(ctx: OperatorContext, target_tenant: str, what: str) -> None:
    """Enforce + audit a platform cross-tenant read (LLD-26 §5.5 / §10 Q2 / WS-E E3).

    Aggregate reads (``target_tenant == "*"``) are allowed (no single tenant's data)
    but audited. A per-tenant read requires the target tenant's
    ``platform_read_consent``; without it we write a DENY record and raise ``403``.
    The audit record is written *before* serving (or denying), so an unaudited
    cross-tenant read can never occur — an audit-write failure is itself fail-secure.
    """
    from app.services.platform_audit import get_platform_audit_store

    def _write(decision: str, consent_state: str, read_type: str) -> None:
        get_platform_audit_store().record(
            operator_sub=ctx.sub, target_tenant=target_tenant, what=what,
            read_type=read_type, decision=decision, consent_state=consent_state,
        )

    if target_tenant == "*":
        # Aggregate cross-tenant view: _platform-only, no per-tenant consent needed.
        _write(decision="ALLOW", consent_state="n/a-aggregate", read_type="aggregate")
        logger.info("PLATFORM_ACCESS operator=%s read=%s target=* (aggregate, audited)",
                    ctx.sub, what)
        return

    # Per-tenant read: deny-by-default unless the tenant opted in.
    target = get_tenant_store().get(target_tenant)
    consented = bool(target.platform_read_consent) if target else False
    enforced = bool(settings.platform_read_consent_enforced)
    if not consented:
        # Enforcement OFF (the §10 Q2 rollout hasn't flipped yet): still write an
        # honest audit row, but ALLOW the read so the platform console keeps working.
        if not enforced:
            _write(decision="ALLOW", consent_state="false-unenforced", read_type="per-tenant")
            logger.info("PLATFORM_ACCESS operator=%s read=%s target=%s "
                        "(no consent; enforcement OFF — allowed + audited)",
                        ctx.sub, what, target_tenant)
            return
        try:
            _write(decision="DENY", consent_state="false", read_type="per-tenant")
        except Exception:  # noqa: BLE001 — never let an audit failure mask the DENY
            logger.error("platform audit write failed on DENY path for target=%s",
                         target_tenant, exc_info=True)
        logger.warning("PLATFORM_ACCESS DENIED operator=%s read=%s target=%s (no consent)",
                       ctx.sub, what, target_tenant)
        raise HTTPException(status_code=403, detail="platform_read_consent not granted by tenant")
    # Consented: audit the ALLOW before the data is served. A write failure here
    # fails secure — we do not serve an unaudited cross-tenant read.
    _write(decision="ALLOW", consent_state="true", read_type="per-tenant")
    logger.info("PLATFORM_ACCESS operator=%s read=%s target=%s (consented, audited)",
                ctx.sub, what, target_tenant)


# Sort keys the Tenant Grid may request (server-validated allowlist — never an
# arbitrary attribute path, so a client can't drive an unbounded scan/sort). Each
# maps to a (row-dict-key, default) the sort reads.
_PLATFORM_SORT_KEYS = {
    "display_name": ("display_name", ""),
    "created_at": ("created_at", 0),
    "blocks_24h": ("blocks_24h", 0),
    "deny_rate": ("deny_rate", 0.0),
    "decisions_24h": ("decisions_24h", 0),
    "trust": ("trust", 0),
    "agents": ("agents", 0),
    "quarantined": ("quarantined", 0),
    "plan": ("plan", ""),
    "status": ("status", ""),
}


@router.get("/platform/tenants")
async def platform_list_tenants(
    limit: int = 50,
    cursor: Optional[str] = None,
    sort: Optional[str] = None,
    filter: Optional[str] = None,  # noqa: A002 — API query param name, matches the console
    ctx: OperatorContext = Depends(require_platform),
) -> Dict:
    """Cross-tenant registry view for Sentra ops. Aggregate cross-tenant read —
    `_platform` only.

    WS-G G0.4 (§6.11(1)): each row now also carries a per-tenant metrics rollup —
    ``blocks_24h``, ``deny_rate``, ``trust``, ``agents``, ``quarantined``,
    ``decisions_24h`` — computed via TWO SINGLE batched fleet scans (sessions +
    decisions), grouped in memory by tenant. NOT N per-tenant scans (that O(N)
    fan-out caused the overview-latency incident; memory: overview-latency-root-cause).

    WS-G G0.5 (§6.11(2)): server-side paging (``limit``/``cursor``) + ``sort`` +
    ``filter`` so a large fleet is served in stable pages, not one unpaged list. The
    cursor is an opaque server-issued offset token (no client-controlled offset into
    the cross-tenant scan). ``require_platform`` gate is unchanged — never widened."""
    _audit_platform_read(ctx, target_tenant="*", what="tenants.list")

    tenants = get_tenant_store().list_all()

    # Batched rollups: exactly ONE call each, regardless of tenant count.
    from app.utils.session_manager import SessionManager
    from app.services.decisions_service import DecisionsService
    session_rollup = await SessionManager().fleet_rollup_by_tenant()
    decisions_rollup = await asyncio.to_thread(
        DecisionsService().fleet_decisions_rollup_by_tenant
    )

    rows: List[Dict] = []
    for t in tenants:
        sr = session_rollup.get(t.tenant_id, {})
        dr = decisions_rollup.get(t.tenant_id, {})
        rows.append({
            "tenant_id": t.tenant_id, "display_name": t.display_name, "plan": t.plan,
            "status": t.status, "identity_mode": t.identity_mode, "created_at": t.created_at,
            # G0.4 rollup fields (0/None-safe — an inactive tenant reads honestly).
            "blocks_24h": dr.get("blocks_24h", 0),
            "deny_rate": dr.get("deny_rate", 0.0),
            "decisions_24h": dr.get("decisions_24h", 0),
            "trust": sr.get("trust"),
            "agents": sr.get("agents", 0),
            "quarantined": sr.get("quarantined", 0),
        })

    # G0.5 filter: case-insensitive substring on display_name OR tenant_id.
    if filter:
        needle = filter.strip().lower()
        rows = [r for r in rows
                if needle in (r["display_name"] or "").lower()
                or needle in r["tenant_id"].lower()]

    # G0.5 sort (allowlisted key only; descending for metrics, ascending for names).
    if sort:
        key = sort.lstrip("-")
        if key in _PLATFORM_SORT_KEYS:
            attr, default = _PLATFORM_SORT_KEYS[key]
            reverse = sort.startswith("-") or key in (
                "blocks_24h", "deny_rate", "decisions_24h", "quarantined", "created_at",
            )
            rows.sort(key=lambda r, a=attr, d=default: (r.get(a) if r.get(a) is not None else d),
                      reverse=reverse)

    total = len(rows)
    # G0.5 opaque cursor = the numeric offset, base64'd (server-issued; a tampered
    # cursor decodes to 0 → first page, never an out-of-range scan).
    import base64
    start = 0
    if cursor:
        try:
            start = max(0, int(base64.b64decode(cursor.encode()).decode()))
        except Exception:  # noqa: BLE001 — malformed cursor → first page (fail-safe)
            start = 0
    page_size = max(1, min(int(limit), 200))
    page = rows[start:start + page_size]
    next_cursor = None
    if start + page_size < total:
        next_cursor = base64.b64encode(str(start + page_size).encode()).decode()

    return {
        "count": total,
        "tenants": page,
        "cursor": next_cursor,
    }


@router.get("/platform/tenants/{tenant_id}")
async def platform_tenant_detail(
    tenant_id: str, ctx: OperatorContext = Depends(require_platform)
) -> Dict:
    """Per-tenant ops detail: registry row + member roster + credential health
    (active/revoked key counts). Dual-audited under `_platform` + target."""
    _audit_platform_read(ctx, target_tenant=tenant_id, what="tenant.detail")
    tenant = get_tenant_store().get(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    members = get_member_store().by_tenant(tenant_id)
    return {
        "tenant_id": tenant.tenant_id, "display_name": tenant.display_name,
        "status": tenant.status, "plan": tenant.plan, "identity_mode": tenant.identity_mode,
        "quota": tenant.quota, "platform_read_consent": tenant.platform_read_consent,
        "members": [{"operator_sub": m.operator_sub, "role": m.role} for m in members],
    }
