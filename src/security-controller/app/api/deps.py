"""Request-auth dependencies for both trust roots (LLD-26 §3, §6 / WS-A, WS-D).

Two independent identity paths converge on the same ``set_current_tenant``
contextvar:

* **Control plane** (operators) — :func:`verify_alb_oidc` cryptographically
  verifies ALB's Cognito OIDC token (D3a, the controller's first app-layer
  authN), then :func:`resolve_operator_tenant` maps the verified ``sub`` →
  membership → tenant and :func:`require_role` gates by RBAC role (D3b).
* **Data plane** (agents) — :func:`resolve_tenant_from_jwt` verifies the agent's
  asymmetric ES256 JWT against its registered public key and derives
  ``(tenant_id, agent_id)`` from the *verified* token, never the request body (A3).

Fail-secure is the rule everywhere: any ambiguity resolves to *unverified*
(data plane) or ``401``/``403`` (control plane), never to ``"default"``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Optional

import jwt
from fastapi import HTTPException, Request

from app.config import settings
from app.services.credentials_service import get_credential_cache
from app.services.tenant_service import get_member_store, get_tenant_store
from app.utils import tenancy

logger = logging.getLogger(__name__)

# RBAC ladder (LLD-26 §6.3). Higher index = more capability.
_ROLE_ORDER = ("viewer", "editor", "admin", "owner")

# Agent JWT contract (LLD-23 signs it; we only verify).
_JWT_ISS = "aegion-guard"
_JWT_AUD = "sentra-controller"


# =========================================================================== #
# Data-plane context (agent identity)
# =========================================================================== #
@dataclass
class TenantContext:
    """Outcome of verifying (or failing to verify) an agent's JWT. The route
    decides what to *do* with it based on ``effective_mode``."""

    state: str  # verified | unverified | tampered | mismatch | disabled
    tenant_id: Optional[str] = None
    agent_id: Optional[str] = None
    claimed_tenant_id: Optional[str] = None  # dual-tag for _unverified audit
    effective_mode: str = "off"
    reason: Optional[str] = None  # IDENTITY_UNVERIFIED | IDENTITY_TAMPERED | IDENTITY_MISMATCH

    # ---- constructors ----------------------------------------------------- #
    @classmethod
    def disabled(cls) -> "TenantContext":
        """Identity is off fleet-wide — the route behaves exactly as pre-LLD-26."""
        return cls(state="disabled", effective_mode="off")

    @classmethod
    def unverified(cls, claimed_tenant_id: Optional[str] = None,
                   effective_mode: str = "off") -> "TenantContext":
        return cls(state="unverified", claimed_tenant_id=claimed_tenant_id,
                   effective_mode=effective_mode, reason="IDENTITY_UNVERIFIED")

    @classmethod
    def tampered(cls, claimed_tenant_id: str, effective_mode: str) -> "TenantContext":
        return cls(state="tampered", claimed_tenant_id=claimed_tenant_id,
                   effective_mode=effective_mode, reason="IDENTITY_TAMPERED")

    @classmethod
    def mismatch(cls, claimed_tenant_id: Optional[str], effective_mode: str) -> "TenantContext":
        return cls(state="mismatch", claimed_tenant_id=claimed_tenant_id,
                   effective_mode=effective_mode, reason="IDENTITY_MISMATCH")

    @classmethod
    def verified(cls, tenant_id: str, agent_id: str, effective_mode: str) -> "TenantContext":
        return cls(state="verified", tenant_id=tenant_id, agent_id=agent_id,
                   effective_mode=effective_mode)

    # ---- decisions -------------------------------------------------------- #
    @property
    def is_verified(self) -> bool:
        return self.state == "verified"

    @property
    def should_route(self) -> bool:
        """Bind the request to the verified tenant only in ENFORCE + verified.
        In shadow we observe but never route (legacy path stays in force)."""
        return self.is_verified and self.effective_mode == "enforce"

    @property
    def should_deny(self) -> bool:
        """Fail-secure: in ENFORCE, anything not cleanly verified is denied."""
        return self.effective_mode == "enforce" and not self.is_verified

    @property
    def credential_present(self) -> bool:
        """True iff the caller presented a *usable* agent credential — i.e. a token
        that cleanly verified (``verified``) OR one whose signature verified against a
        real tenant key but failed a downstream tenant/subject binding
        (``tampered``/``mismatch``). It is False for ``unverified`` (missing token, bad
        signature, expired, unknown kid) and ``disabled`` (no token looked at).

        WS-M M5.1: the data-plane credential latch (``require_dataplane_credential``)
        keys on *absence/invalidity* of a credential, INDEPENDENT of ``identity_mode``.
        A ``tampered``/``mismatch`` token DID present a valid signature (so it is not
        "missing/invalid" for the latch) — those are already hard-denied by
        ``should_deny`` at enforce and by their own audit path; the latch's job is to
        close the *tokenless / bad-token* fall-through, not to relax the tamper deny."""
        return self.state in ("verified", "tampered", "mismatch")

    def audit_tenant(self) -> str:
        """Where this request's audit row belongs. Unverified/tampered/mismatch
        never leak into a real tenant's (or ``default``'s) trail — they go to
        the reserved ``_unverified`` bucket (A4)."""
        return self.tenant_id if self.is_verified else tenancy.UNVERIFIED_TENANT


async def resolve_tenant_from_jwt(request: Request) -> TenantContext:
    """Verify the agent JWT and resolve ``(tenant_id, agent_id)`` (A3).

    Never raises — every failure path returns a :class:`TenantContext` the route
    interprets per ``effective_mode``. The verify lookup goes through the
    in-process public-key cache (A3.1), so the hot path does **not** hit the
    ``kid-index`` GSI per request.
    """
    ceiling = (settings.tenant_identity_mode or "off").lower()
    if ceiling == "off" and not settings.require_dataplane_credential:
        # Fleet kill-switch: don't even look at the token. Byte-identical to pre-26.
        # BUT if the data-plane credential latch (WS-M M5.1) is engaged we must still
        # attempt verification even at fleet `off`, so the route can distinguish a
        # valid token from a missing/invalid one INDEPENDENT of `identity_mode`. In
        # that case we fall through with the ceiling treated as `off` — the resolved
        # TenantContext carries effective_mode=`off` (so `should_route`/`should_deny`
        # stay off), and the route applies the latch on `credential_present`.
        return TenantContext.disabled()

    # For requests where no tenant can be established (no/invalid token, kid miss)
    # the per-tenant mode is unknowable, so the FLEET CEILING governs: at enforce
    # this denies unauthenticated traffic (§8); at shadow it is observed + allowed.
    token = _extract_bearer(request)
    if not token:
        return TenantContext.unverified(effective_mode=ceiling)

    # Read the (unverified) header only to find the kid; trust nothing yet.
    try:
        kid = jwt.get_unverified_header(token).get("kid")
    except Exception:  # noqa: BLE001
        return TenantContext.unverified(effective_mode=ceiling)
    if not kid:
        return TenantContext.unverified(effective_mode=ceiling)

    cred = await get_credential_cache().get(kid)
    if cred is None or not cred.is_usable:
        return TenantContext.unverified(effective_mode=ceiling)

    # Now we know a candidate tenant → compute the effective mode for it (cached,
    # off the event loop — A3.1: no per-request blocking DDB read on the hot path).
    mode = await _effective_mode_for(cred.tenant_id)

    skew = settings.jwt_clock_skew_seconds
    now_ms = int(time.time() * 1000)
    if not (cred.not_before - skew * 1000 <= now_ms <= cred.not_after + skew * 1000):
        return TenantContext.unverified(claimed_tenant_id=cred.tenant_id, effective_mode=mode)

    try:
        claims = jwt.decode(
            token,
            _coerce_verify_key(cred.public_key),  # PEM string or JWK→key object (#6)
            algorithms=["ES256"],  # never honor the token's own alg → no "none" downgrade
            audience=_JWT_AUD,
            issuer=_JWT_ISS,
            leeway=skew,
        )
    except Exception:  # noqa: BLE001 — bad sig / expired / wrong aud|iss / bad key
        return TenantContext.unverified(claimed_tenant_id=cred.tenant_id, effective_mode=mode)

    tid = claims.get("tid")
    sub = claims.get("sub") or ""
    if tid != cred.tenant_id:
        # Key reuse across tenants — high-severity (§8). The token verified
        # against a key that belongs to a DIFFERENT tenant than it claims.
        logger.warning("IDENTITY_TAMPERED kid=%s claims.tid=%s cred.tenant=%s",
                       kid, tid, cred.tenant_id)
        return TenantContext.tampered(claimed_tenant_id=cred.tenant_id, effective_mode=mode)

    # Delimited prefix — `sub` is `{tenant}-{cloud}-{slug}-{hash}`; a bare
    # startswith(tid) would let `t_01` match `t_01hxyz-…` (§3.3, A3).
    if not sub.startswith(tid + "-"):
        return TenantContext.mismatch(claimed_tenant_id=tid, effective_mode=mode)

    return TenantContext.verified(tenant_id=tid, agent_id=sub, effective_mode=mode)


# Short-TTL cache of tenant → identity_mode so the hot path doesn't do an
# uncached, event-loop-blocking get_item on `sentra-tenants` per validate (A3.1,
# #4). identity_mode changes are rare and rollout-gated, so a few-second lag is
# fine — and it is still bounded by min(this, credential cache TTL).
_MODE_TTL = 30.0
_mode_cache: Dict[str, "tuple[float, str]"] = {}


async def _effective_mode_for(tenant_id: str) -> str:
    """min(env ceiling, tenant.identity_mode), via a short-TTL cache and an
    ``asyncio.to_thread`` DDB read (never blocks the loop). A registry hiccup
    fails closed (the tenant is treated as ``off``)."""
    import time as _time

    now = _time.monotonic()
    cached = _mode_cache.get(tenant_id)
    if cached and now - cached[0] < _MODE_TTL:
        return tenancy.effective_identity_mode(cached[1])
    try:
        tenant = await asyncio.to_thread(get_tenant_store().get, tenant_id)
    except Exception:  # noqa: BLE001
        # Fail CLOSED, not to "off". The tenant is already PROVEN from the
        # credential — only the rollout mode is unknown. Honoring the fleet
        # ceiling keeps a verified agent on its OWN tenant (routes at enforce)
        # rather than dropping it to the legacy/`default` path and mis-filing its
        # signals. Do NOT cache the failure, so the next request retries.
        logger.warning("identity_mode lookup failed for %s — honoring ceiling", tenant_id, exc_info=True)
        return (settings.tenant_identity_mode or "off").lower()
    # tenant=None is a real read result (row genuinely absent) → "off", cacheable.
    tenant_mode = tenant.identity_mode if tenant else "off"
    _mode_cache[tenant_id] = (now, tenant_mode)
    # The fleet ceiling is applied in effective_identity_mode(); a suspended/
    # deleting tenant is handled separately by the route's status check.
    return tenancy.effective_identity_mode(tenant_mode)


def _coerce_verify_key(public_key: str):
    """Return a PyJWT-usable verification key (#6). A stored PEM is passed through;
    a stored JWK JSON string is converted via ``PyJWK`` (PyJWT cannot verify
    against a raw JWK string). Registration already validated EC/P-256."""
    pk = (public_key or "").strip()
    if pk.startswith("{"):
        return jwt.PyJWK.from_json(pk).key
    return pk


def _extract_bearer(request: Request) -> Optional[str]:
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth:
        return None
    parts = auth.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


# =========================================================================== #
# Control-plane context (operator identity)
# =========================================================================== #
@dataclass
class OperatorContext:
    sub: str
    tenant_id: str
    role: str
    email: str = ""
    memberships: List["object"] = None  # list[Membership]
    is_platform: bool = False


# ---- D3a: verify ALB's Cognito OIDC token --------------------------------- #
class _ALBKeyCache:
    """Caches ALB's regional public signing keys by ``kid``. Keys rotate slowly
    and are immutable per kid, so a fetch-once-per-kid cache is safe and keeps
    verification off the network on the hot path."""

    def __init__(self) -> None:
        self._keys: Dict[str, str] = {}
        self._lock = threading.Lock()

    def get(self, kid: str, region: str) -> str:
        key = self._keys.get(kid)
        if key is not None:
            return key
        # Lock so a key rotation doesn't trigger a thundering herd of fetches for
        # the same new kid (control plane is low-QPS; the fetch is rare).
        with self._lock:
            key = self._keys.get(kid)
            if key is None:
                url = f"https://public-keys.auth.elb.{region}.amazonaws.com/{kid}"
                with urllib.request.urlopen(url, timeout=2) as resp:  # noqa: S310 — fixed AWS host
                    key = resp.read().decode("utf-8")
                self._keys[kid] = key
        return key


_alb_keys = _ALBKeyCache()
# Test/dev seam: a hook that returns claims directly, bypassing ALB. Production
# leaves this None so the real signature check is always exercised.
_alb_claims_override = None


def verify_alb_oidc(request: Request) -> Dict:
    """Verify ``x-amzn-oidc-data`` and return the Cognito claims (D3a).

    ALB injects a signed JWT of the authenticated claims; its header names the
    signing ``kid`` and we fetch the matching **regional** public key. We verify
    signature + ``exp`` — never trust the header blind. Any failure → ``401``.
    """
    if _alb_claims_override is not None:  # pragma: no cover - test seam
        return _alb_claims_override(request)

    # The native `x-amzn-oidc-data` is a RESERVED, ALB-authoritative header: every
    # gateway hop after the authenticating public ALB (API Gateway AND the internal
    # ALB) STRIPS inbound `x-amzn-oidc-*` to prevent spoofing. So the console nginx
    # re-emits it under a non-reserved name (`x-sentra-oidc-data`) that survives the
    # gateway; we read that first, falling back to the native header for any path
    # that preserves it (direct calls / tests). Renaming the TRANSPORT is not a
    # spoof vector — the ALB signature is still cryptographically verified below.
    data = request.headers.get("x-sentra-oidc-data") or request.headers.get("x-amzn-oidc-data")
    if not data:
        raise HTTPException(status_code=401, detail="missing ALB identity")
    try:
        header = jwt.get_unverified_header(data)
        kid = header.get("kid")
        if not kid:
            raise ValueError("no kid")
        public_key = _alb_keys.get(kid, settings.aws_region)
        # ALB OIDC tokens are ES256; verify signature + expiry. ALB does not set
        # a stable `aud`, so we don't assert one here.
        claims = jwt.decode(data, public_key, algorithms=["ES256"],
                            options={"verify_aud": False})
        # WS-M M1.0 / lld/39 §3.1 — signer + issuer PIN. Signature-valid is not
        # enough: any in-region ALB / any Cognito pool would otherwise pass, and
        # account 531109575379 runs multiple stacks. Enforced HERE (after the
        # signature check) so it applies to WHICHEVER header we read — the
        # `x-sentra-oidc-data` fallback cannot bypass it. Empty allowlists = no pin.
        _assert_signer_issuer_pinned(header, claims)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.info("ALB OIDC verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="invalid ALB identity") from exc

    if not claims.get("sub"):
        raise HTTPException(status_code=401, detail="ALB identity missing sub")
    return claims


def _csv_allowlist(raw: str) -> frozenset:
    return frozenset(p.strip() for p in (raw or "").split(",") if p.strip())


def _assert_signer_issuer_pinned(header: Dict, claims: Dict) -> None:
    """Reject a signature-valid token whose ALB `signer` (JWT header) is not in the
    expected-signer allowlist, or whose `iss` is not the expected Cognito issuer
    (WS-M M1.0). Empty allowlists disable the corresponding check (dev/test/
    transition). Any mismatch raises 401 (caught + normalized by the caller)."""
    signers = _csv_allowlist(settings.alb_oidc_expected_signers)
    if signers:
        signer = header.get("signer")
        if signer not in signers:
            logger.warning("ALB OIDC signer pin rejected signer=%r", signer)
            raise HTTPException(status_code=401, detail="untrusted ALB signer")
    expected_iss = (settings.alb_oidc_expected_issuer or "").strip()
    if expected_iss:
        if claims.get("iss") != expected_iss:
            logger.warning("ALB OIDC issuer pin rejected iss=%r", claims.get("iss"))
            raise HTTPException(status_code=401, detail="untrusted OIDC issuer")


# ---- D3b: operator → tenant resolution + RBAC ----------------------------- #
async def resolve_operator_tenant(request: Request) -> OperatorContext:
    """Resolve the active tenant for an authenticated operator (D3b).

    Consumes the *verified* claims from :func:`verify_alb_oidc`, looks up the
    operator's memberships, honors an optional ``X-Aegion-Tenant`` switch header
    (asserted against membership), and binds the request tenant via
    ``set_current_tenant``. Returns ``(tenant_id, role)`` + the membership set.

    Same-task ContextVar hygiene (WS-M M5.3 / lld/39 §5): on a *raising* resolve
    (401/403, incl. the below-role/non-platform rejections in ``require_role`` /
    ``require_platform``) the tenant is forced back to the ``default`` sentinel — a
    failed auth must never leave a stale same-context bind that a later
    ``current_tenant()`` read (e.g. a non-gated handler on the same asyncio Task)
    could act on. On a *successful* resolve the resolved tenant stays bound (the
    downstream handler needs it). This is defence-in-depth — asyncio isolates the
    ContextVar per Task so a bind never leaks across requests — the reset guards the
    *same-context* re-read path (Invariant 5, lld/39 §2.2). We do NOT remove the
    module-level ``default=DEFAULT_TENANT`` (tenancy.py) — ~49 sites + the disabled
    ``/validate`` path rely on it as the baseline.
    """
    try:
        return await _resolve_operator_tenant_inner(request)
    except BaseException:
        # A raising resolve must not leave any same-context bind in place. Force the
        # DEFAULT sentinel (fail-secure — no ambient tenant survives a failed
        # operator auth), regardless of what a prior same-context resolve bound.
        tenancy.set_current_tenant(tenancy.DEFAULT_TENANT)
        raise


async def _resolve_operator_tenant_inner(request: Request) -> OperatorContext:
    claims = verify_alb_oidc(request)
    sub = claims["sub"]
    email = claims.get("email", "")

    members = get_member_store().by_operator(sub)
    # `_platform` is AegionAI's reserved cross-tenant OPERATIONAL-fleet grant
    # (metrics/metadata across tenants — NOT customer content).
    is_platform = any(m.tenant_id == tenancy.PLATFORM_TENANT for m in members)
    customer_members = [m for m in members if m.tenant_id != tenancy.PLATFORM_TENANT]

    # WS-N N0.3 — alarm (do NOT block) on the mis-provisioning fingerprint: an
    # account holding BOTH `_platform` AND ≥1 customer membership. The grant is
    # server-derived (unspoofable), so this is a config anomaly to page-and-fix,
    # not an attack — the guard is fire-and-forget and never breaks auth.
    from app.api.platform_guard import check_platform_membership_anomaly

    check_platform_membership_anomaly(
        operator_sub=sub,
        is_platform=is_platform,
        customer_tenant_ids=[m.tenant_id for m in customer_members],
    )

    requested = request.headers.get("x-aegion-tenant") or request.headers.get("X-Aegion-Tenant")
    chosen = None
    if requested:
        chosen = next((m for m in members if m.tenant_id == requested), None)
        if chosen is None and is_platform:
            # Break-glass support: a `_platform` operator may *read* any tenant,
            # but defaults to VIEWER — never write authority by header alone
            # (LLD-26 §6.3). Mutations in a non-member tenant require an explicit,
            # separately-audited elevation, not a synthesized admin role.
            from app.services.tenant_service import Membership

            chosen = Membership(operator_sub=sub, tenant_id=requested, role="viewer")
        if chosen is None:
            raise HTTPException(status_code=403, detail="not a member of requested tenant")
    else:
        chosen = next((m for m in customer_members if m.is_primary), None)
        if chosen is None and customer_members:
            chosen = customer_members[0]
        if chosen is None:
            raise HTTPException(status_code=403, detail="operator has no tenant membership")

    tenancy.set_current_tenant(chosen.tenant_id)

    # WS-N N9 / lld/40 §8 SEC-5 (D12): attribute the operator READ. Emitted HERE so
    # coverage == every resolve_operator_tenant-bound read by construction (a bound
    # read cannot be forgotten). GET-only + fire-and-forget inside the helper — never
    # breaks the read. The break-glass `_platform` cross-tenant read records the
    # SPECIFIC resolved tenant (chosen.tenant_id), making it non-repudiable.
    from app.api.read_access_audit import emit_read_access_event

    emit_read_access_event(
        request, operator_sub=sub, tenant_id=chosen.tenant_id, is_platform=is_platform,
    )

    return OperatorContext(
        sub=sub,
        tenant_id=chosen.tenant_id,
        role=chosen.role,
        email=email,
        memberships=customer_members,
        is_platform=is_platform,
    )


def role_satisfies(have: str, need: str) -> bool:
    try:
        return _ROLE_ORDER.index(have) >= _ROLE_ORDER.index(need)
    except ValueError:
        return False


async def require_platform(request: Request) -> OperatorContext:
    """Gate the platform-admin (internal ops) surface (LLD-26 §5.5 / WS-E E3).

    Authority is the reserved ``_platform`` membership, NOT a tenant role — only
    Sentra staff hold it. Cross-tenant reads behind this gate are audited under
    both ``_platform`` and the target tenant (caller's responsibility per route).

    On a non-platform operator we raise 403 AND reset the tenant bind that
    :func:`resolve_operator_tenant` just set — the request is rejected, so no
    ambient tenant should survive it (WS-M M5.3 fail-secure hygiene).
    """
    ctx = await resolve_operator_tenant(request)
    if not ctx.is_platform:
        tenancy.set_current_tenant(tenancy.DEFAULT_TENANT)
        raise HTTPException(status_code=403, detail="platform access required")
    return ctx


def require_role(min_role: str):
    """Dependency factory: layered after :func:`resolve_operator_tenant`, gates a
    control-plane mutation by RBAC role. Client-side gating is UX only — this is
    the boundary (§5.4).

    On a below-role operator we raise 403 AND reset the tenant bind that
    :func:`resolve_operator_tenant` just set — a rejected request leaves no ambient
    tenant (WS-M M5.3 fail-secure hygiene)."""
    from fastapi import Depends

    async def _dep(ctx: OperatorContext = Depends(resolve_operator_tenant)) -> OperatorContext:
        if not role_satisfies(ctx.role, min_role):
            tenancy.set_current_tenant(tenancy.DEFAULT_TENANT)
            raise HTTPException(status_code=403, detail=f"requires role >= {min_role}")
        return ctx

    return _dep
