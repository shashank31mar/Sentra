"""
API Routes for Security Controller

Implements all REST endpoints:
- GET /v1/health - Health check with dependency verification
- POST /v1/validate - Tool call validation with 5-step pipeline
- GET /v1/logs - Query audit logs (Task 10)
- GET /v1/sessions - Query sessions (Task 11)
- GET /v1/metrics - Query summary metrics (Task 11)

All business logic is delegated to service classes in app/services/.
Routes are kept clean and focused on HTTP handling only.
"""
import contextlib
import logging
from typing import Dict, NoReturn, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.deps import OperatorContext, require_platform, require_role, resolve_operator_tenant
from app.api.ownership import ResourceKind, assert_owns
from app.api.models import (
    ValidationRequest,
    PolicyCreateRequest,
    PolicyUpdateRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1")

# WS-J / LLD 38 §319 (J4.2 hook) — the debug-gated capture response header name and
# the reserved canary tenant prefix. Kept module-level so the value is unambiguous
# and testable. The prefix matches the audit_logger's SEC-11 isolation prefix.
_CANARY_CAPTURE_HEADER = "x-canary-capture"
_CANARY_TENANT_PREFIX = "canary-"
# Header values must be bounded (a header is not a payload channel); cap the echoed
# redacted content so an oversized (but redacted) body can't bloat the response.
_CANARY_CAPTURE_MAX_LEN = 2000


def _maybe_attach_canary_capture(
    response: Response,
    request: "ValidationRequest",
    *,
    tenant_id: Optional[str],
) -> None:
    """Attach the debug-gated `x-canary-capture` header — J4.2 `live` hook (LLD 38
    §319). NO-OP unless BOTH gates pass:
      1. `settings.canary_capture_enabled` is True (default False → zero prod change);
      2. `tenant_id` is a reserved `canary-*` tenant (the VERIFIED tenant from the
         agent JWT — never the client-claimed body).

    When it fires, the header carries ONLY the ALREADY-REDACTED `user_input` /
    `tool_params` from the incoming request — the post-Tier-1-redaction form the SDK/
    connector sent, which is the SAME value the audit writer receives (log_signals is
    called with `request.model_dump()`). It is IMPOSSIBLE for this to echo raw content:
    it never reads any raw source, only the fields the edge already masked, and it only
    runs for a canary tenant with the flag explicitly on. Fail-secure: on ANY error
    building the value it attaches nothing (no header) rather than risk a partial/raw
    echo, and it NEVER raises into the validate path."""
    try:
        from app.config import settings
        if not getattr(settings, "canary_capture_enabled", False):
            return
        if not tenant_id or not tenant_id.startswith(_CANARY_TENANT_PREFIX):
            return
        import json
        # Echo ONLY the already-redacted content-bearing fields the audit writer sees.
        # These are the post-edge-redaction values on the request (redacted=True on a
        # real canary call); no raw source is ever read here.
        payload = {
            "user_input": request.user_input,
            "tool_params": request.tool_params,
            "redacted": request.redacted,
        }
        value = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
        if len(value) > _CANARY_CAPTURE_MAX_LEN:
            value = value[:_CANARY_CAPTURE_MAX_LEN]
        response.headers[_CANARY_CAPTURE_HEADER] = value
    except Exception:  # noqa: BLE001 — the capture is a debug echo; never break validate
        logger.debug("x-canary-capture attach skipped", exc_info=True)


# ============================================================
# WS-N N0.1 — operator read-scope helper (lld/40 §6.2 D10)
# ============================================================

def _operator_read_scope(ctx: OperatorContext, what: str) -> Optional[str]:
    """Resolve the read tenant for an operator read (WS-N N0.1 / lld/40 §6.2).

    * customer operator  -> ctx.tenant_id (STRICT own-tenant; already bound by
      resolve_operator_tenant @ deps.py:435, returned here for explicit service calls)
    * platform operator  -> None (fleet view) + audited via _audit_platform_read(ctx,'*',what)

    A customer NEVER gets None (never a fleet view). Fail-secure: if is_platform is
    somehow absent/False, the tenant_id path is taken (deny-over-allow).
    """
    if ctx.is_platform:
        from app.api.tenancy_routes import _audit_platform_read
        _audit_platform_read(ctx, "*", what)
        return None
    return ctx.tenant_id


@router.get("/health")
async def health_check() -> Dict:
    """
    Health check endpoint with dependency verification.
    
    Checks connectivity to:
    - DynamoDB (sentra-session-context, sentra-policies-metadata, …)
    - S3 (sentra-mvp-artifacts)
    - CloudWatch Logs
    
    Returns:
        200 OK if all dependencies are healthy
        503 Service Unavailable if any dependency is unhealthy
    """
    from app.services import HealthService
    
    health_service = HealthService()
    response, is_healthy = await health_service.check_health()
    
    if not is_healthy:
        raise HTTPException(status_code=503, detail=response)
    
    return response


@router.post("/validate")
async def validate_tool_call(
    request: ValidationRequest, http_request: Request, response: Response
) -> Dict:
    """
    Validate tool call before execution.

    Runs 5-step validation pipeline:
    1. Trust Score Check (fail-fast if suspended/quarantined)
    2. Policy Engine (agent authorization)
    3. Sigma Rule Engine (threat detection)
    4. Context Validator (tool sequence validation)
    5. Abuse Detector (rate limiting)

    Returns:
        ValidationResponse (ALLOW) or ValidationDenyResponse (DENY)

    WS-J / LLD 38 §319 (J4.2 hook): `response` is an injected FastAPI Response the
    handler uses ONLY to (optionally) attach the debug-gated `x-canary-capture`
    header (see `_maybe_attach_canary_capture`). The returned dict body is unchanged;
    FastAPI merges this Response's headers into the final response, so no caller or
    return shape is affected.
    """
    # Capture the caller IP for the audit trail / forensics view. Behind API Gateway + VPC Link the
    # real client is the first hop of X-Forwarded-For; fall back to the socket peer. Stored on the
    # request context so it propagates to every signal row (audit_logger._shared_attrs_from_request).
    xff = http_request.headers.get("x-forwarded-for")
    source_ip = (xff.split(",")[0].strip() if xff else None) or (
        http_request.client.host if http_request.client else None
    )
    if source_ip:
        request.context = {**(request.context or {}), "ip_address": source_ip}

    # WS-B (LLD 30 §3.2) — multi-phase routing guard. Runs FIRST, before tenant
    # derivation / quota / the pipeline, so a known-but-unbuilt phase is denied
    # cheaply and never touches the pipeline, combiner, or Cedar.
    from app.api.models import KNOWN_PHASES  # {request, content, output, memory}

    phase = request.phase  # normally already narrowed to KNOWN_PHASES by the Literal (B1.1).

    # GUARD 1 (FIRST statement — belt-and-suspenders, AHEAD of the `!= request`
    # compare): a value outside KNOWN_PHASES that bypassed the Literal (a hand-built
    # ValidationRequest / model_construct / future internal call) re-raises the SAME
    # 422 — a malformed request, NEVER a deny. Placing this FIRST keeps a typo from
    # ever falling into the DENY path and polluting the Decisions metric (§3.1, §9).
    if phase not in KNOWN_PHASES:
        raise HTTPException(status_code=422, detail=f"unknown phase: {phase}")

    # GUARD 2 (only reached with phase IN KNOWN_PHASES):
    #
    # WS-L M2.1 (FIX-I / SEC-13) — `content` and `memory` now have LIVE handlers
    # (D2 / D3), so they FALL THROUGH to the identity gate + pipeline exactly like
    # `request`. `output` (and any future known-but-unbuilt phase) STAYS on the
    # fail-secure stub (D5 not built — §8). CRITICAL: content/memory route into the
    # pipeline BELOW the identity gate (never in place of GUARD 2) — routing a
    # content/memory call into the D-nodes BEFORE identity resolves would run them
    # for an unauthenticated caller (elevation-of-privilege). The identity gate below
    # calls `validation_service.validate_tool_call(request)` on every accept branch;
    # content/memory ride those same branches, so the D-nodes never run before
    # identity is resolved.
    if phase not in ("request", "content", "memory"):   # i.e. "output" today
        # Known phase, no live handler yet → fail-secure DENY (§3.1 right column,
        # tenet 2). WS-L replaces this line for D5 when the output handler ships.
        return await _phase_not_implemented_deny(
            request, reason=f"phase_handler_not_implemented:{phase}"
        )

    # phase in (request, content, memory): fall through to the EXISTING path —
    # tenant derivation, quota, _run_validation_pipeline. For content/memory the
    # per-phase build_dag picks the D2/D3 node set; the request path is byte-for-byte
    # unchanged (WS-B adds NOTHING to it).

    # Reuse the process-wide ValidationService built at startup (app/main.py
    # lifespan, LLD 24 / WS24 M2). Per-request construction rebuilt ~10 boto3
    # clients and defeated the Sigma rule cache. Fall back to a local instance only
    # if lifespan didn't run (e.g. some test harnesses).
    validation_service = getattr(http_request.app.state, "validation_service", None)
    if validation_service is None:
        from app.services import ValidationService
        validation_service = ValidationService()

    # LLD-26 §3 / WS-A A3: derive the tenant from the *verified* agent JWT, never
    # from the request body. When identity is OFF fleet-wide (the default) this
    # resolves to `disabled` and the call runs byte-identically to pre-LLD-26 —
    # so the background AWS/Azure event traffic sees no change.
    from app.api.deps import resolve_tenant_from_jwt
    from app.config import settings
    from app.utils import tenancy

    ctx = await resolve_tenant_from_jwt(http_request)

    # WS-J / LLD 38 §319 (J4.2 hook) — debug-gated `x-canary-capture` echo. Attaches
    # ONLY when `settings.canary_capture_enabled` is True AND the verified tenant is a
    # reserved `canary-*` tenant. It echoes the ALREADY-REDACTED user_input/tool_params
    # that will be handed to the audit writer (the post-Tier-1-redaction form the SDK/
    # connector sent) so the `live` canary can prove no raw PII entered the audit write
    # without reaching `_bg_tasks`. Off by default → zero prod behavior change. Placed
    # here (after identity resolves the tenant, before the routing returns) so it rides
    # whichever verdict the canary's enforce path returns; a no-op for every real
    # tenant. `ctx.tenant_id` is the verified tenant (never the client-claimed body).
    _maybe_attach_canary_capture(response, request, tenant_id=ctx.tenant_id)

    # WS-M M5.1 / lld/39 §5 (ADR-037): the in-service data-plane auth boundary. When the
    # `require_dataplane_credential` latch is engaged, a MISSING or INVALID agent JWT is
    # denied on the data plane INDEPENDENT of `identity_mode` — closing the tokenless
    # fall-through (previously a tokenless call was only denied at effective `enforce`,
    # and fell through to the legacy path at `shadow`/`off`, incl. a fresh env defaulting
    # to identity `off`). `identity_mode` remains only the enforcement-STRICTNESS latch
    # (shadow→enforce governs whether an unverified-but-well-formed posture is tolerated
    # during soak); credential PRESENCE is not mode-gated. A forged (bad-signature) token
    # is `unverified` here too, so it is denied by this same check regardless of mode.
    # Default-off, so the live env (identity `off`, no agent sends a JWT yet) is unchanged
    # until an operator flips the latch per the WS-K go-live runbook.
    if settings.require_dataplane_credential and not ctx.credential_present:
        return await _identity_deny(request, ctx.reason or "IDENTITY_UNVERIFIED")

    if ctx.state == "disabled":
        return await validation_service.validate_tool_call(request)

    # Carry what identity resolved to into the audit trail (shadow + enforce).
    request.context = {**(request.context or {}), "identity_state": ctx.state}
    if ctx.claimed_tenant_id:
        request.context["claimed_tenant_id"] = ctx.claimed_tenant_id

    if ctx.should_deny:
        # ENFORCE + not cleanly verified. Active spoofing — IDENTITY_TAMPERED (key
        # reuse) / IDENTITY_MISMATCH — is ALWAYS a hard fail-secure DENY (§8). Only
        # a genuinely uncredentialed agent (state=unverified) is eligible for the
        # WS-B B1 residual legacy-fallback window: a time-boxed, alarmed grace ramp
        # so flipping a tenant to enforce before 100% credential coverage doesn't
        # brick a not-yet-onboarded agent. Default-off (window=0 → immediate DENY).
        if ctx.state == "unverified":
            from app.services.fallback_service import consider_fallback
            decision = await consider_fallback(request.agent_id, ctx.claimed_tenant_id)
            if decision.allow:
                request.context["identity_state"] = "legacy_fallback"
                request.context["fallback_deadline_ms"] = decision.deadline_ms
                logger.warning(
                    "identity legacy-fallback: agent=%s state=%s deadline_ms=%s "
                    "(uncredentialed agent riding legacy path on borrowed time)",
                    request.agent_id, decision.state, decision.deadline_ms,
                )
                return await validation_service.validate_tool_call(request)
        # No window (disabled/expired) or non-unverified → fail-secure DENY, audited
        # under the reserved `_unverified` tenant (never the claimed tenant or `default`).
        return await _identity_deny(request, ctx.reason or "IDENTITY_UNVERIFIED")

    if ctx.should_route:
        # ENFORCE + verified → bind the whole request to the verified tenant.
        if request.agent_id != ctx.agent_id:
            return await _identity_deny(request, "IDENTITY_MISMATCH")
        token = tenancy.set_current_tenant(ctx.tenant_id)
        try:
            # Commercial RPS quota (WS-E E2b) — inert unless founder-enabled.
            # Fail-OPEN: a quota counter must never DoS legitimate validate traffic.
            from app.services.quota_service import check_validate_rps
            if not check_validate_rps(ctx.tenant_id):
                # Fire-and-forget metric (self-guarding; never raises) so the
                # commercial quota alarm can page on a tenant hitting its ceiling.
                from app.utils.metrics_publisher import MetricsPublisher
                await MetricsPublisher().publish_quota_exceeded_metric(ctx.tenant_id)
                return {
                    "decision": "DENY", "reason": "QUOTA_EXCEEDED",
                    "trust_score": 0.0, "session_id": request.session_id,
                    "latency_ms": 0.0, "violation_type": "QUOTA_EXCEEDED",
                }
            return await validation_service.validate_tool_call(request)
        finally:
            tenancy.reset_current_tenant(token)

    # SHADOW (incl. verified-but-shadow): observe + log, do NOT route. The legacy
    # path stays in force so an uncredentialed agent is never bricked.
    if ctx.is_verified:
        logger.info(
            "identity shadow: resolved tid=%s agent=%s (observed, not routed)",
            ctx.tenant_id, ctx.agent_id,
        )
    return await validation_service.validate_tool_call(request)


async def _identity_deny(request: "ValidationRequest", reason: str) -> Dict:
    """Fail-secure identity DENY (LLD-26 §8). Audits under the reserved
    `_unverified` tenant with the `claimed_tenant_id` dual-tag (A4) so a tenant's
    SOC still sees spoof attempts against its agents, then returns the standard
    DENY shape the SDK contract expects."""
    from app.utils import tenancy
    from app.utils.audit_logger import AuditLogger

    token = tenancy.set_current_tenant(tenancy.UNVERIFIED_TENANT)
    try:
        await AuditLogger().log_decision(
            decision="DENY",
            request=request.model_dump(),
            session={"session_id": request.session_id, "agent_id": request.agent_id,
                     "trust_score": 0.0},
            validation_result={"reason": reason, "violation_type": reason},
            latency_ms=0.0,
        )
        # Count the gate-DENY in the same CloudWatch streams a normal verdict uses,
        # so an enforce cutover that starts denying an unsigned/uncredentialed agent
        # shows up as DENYs (not as a phantom traffic drop). The `current_tenant()`
        # contextvar is `_unverified` here, so the tenant-keyed `Decisions` series is
        # tagged `_unverified` — never the claimed tenant or `default`. Fire-and-forget,
        # guarded separately so a metrics failure never changes the DENY we return.
        try:
            from app.utils.metrics_publisher import MetricsPublisher
            await MetricsPublisher().publish_validation_metrics(
                decision="DENY", latency_ms=0.0, agent_id=request.agent_id, trust_score=0.0,
            )
        except Exception:  # noqa: BLE001 — metrics are best-effort; the DENY still returns
            logger.warning("identity-DENY metric publish failed", exc_info=True)
    except Exception:  # noqa: BLE001 — audit is best-effort; the DENY still returns
        logger.warning("identity-DENY audit failed", exc_info=True)
    finally:
        tenancy.reset_current_tenant(token)

    return {
        "decision": "DENY",
        "reason": reason,
        "trust_score": 0.0,
        "session_id": request.session_id,
        "latency_ms": 0.0,
        "violation_type": reason,
    }


async def _phase_not_implemented_deny(request: "ValidationRequest", reason: str) -> Dict:
    """Fail-secure DENY for a known-but-not-yet-handled phase (LLD 30 §3.1, right
    column). ONLY for phases in KNOWN_PHASES with no live handler — an unknown/typo
    phase 422s at the edge (validate_tool_call GUARD 1) and never reaches here.

    Modeled on ``_identity_deny``: same DENY response shape (the keys the SDK's
    ``_parse_decision`` reads) plus the same best-effort audit + metric emission,
    so a known-but-unbuilt-phase DENY is observable in the same CloudWatch/audit
    streams as any other verdict — a REAL deny, not a phantom traffic drop (§9).
    WS-L replaces the call site with the real D2/D3/D5 handler when it ships."""
    from app.utils.audit_logger import AuditLogger

    # Audit and metrics are TWO INDEPENDENT best-effort seams, guarded by SIBLING
    # try/excepts — NOT nested. A nested metrics block (inside the audit try) would
    # be skipped entirely when audit raises, so an audit failure would silently
    # UN-METER the phase-DENY — contradicting §9 (the known-but-unbuilt DENY must
    # appear in the Decisions stream as a DENY, mirroring _identity_deny) and the
    # "guarded separately" promise below. Keep them siblings so a failure in one
    # never suppresses the other, and neither ever changes the DENY we return.
    try:
        await AuditLogger().log_decision(
            decision="DENY",
            request=request.model_dump(),
            session={"session_id": request.session_id, "agent_id": request.agent_id,
                     "trust_score": 0.0},
            validation_result={"reason": reason, "violation_type": "PHASE_UNHANDLED"},
            latency_ms=0.0,
        )
    except Exception:  # noqa: BLE001 — audit is best-effort; the DENY still returns
        logger.warning("phase-DENY audit failed", exc_info=True)

    # Count the phase-DENY in the same CloudWatch streams a normal verdict uses
    # so it shows up in Decisions as a DENY (contrast the unknown-phase 422, which
    # must NOT be metered — §9). Fire-and-forget, guarded separately (SIBLING of the
    # audit try above) so a metrics failure never changes the DENY, and — critically
    # — an AUDIT failure never skips this metric publish.
    try:
        from app.utils.metrics_publisher import MetricsPublisher
        await MetricsPublisher().publish_validation_metrics(
            decision="DENY", latency_ms=0.0, agent_id=request.agent_id, trust_score=0.0,
        )
    except Exception:  # noqa: BLE001 — metrics are best-effort; the DENY still returns
        logger.warning("phase-DENY metric publish failed", exc_info=True)

    return {
        "decision": "DENY",
        "reason": reason,
        "trust_score": 0.0,
        "session_id": request.session_id,
        "latency_ms": 0.0,
        "violation_type": "PHASE_UNHANDLED",
    }


# ============================================================
# Task 10: GET /v1/logs - Query Audit Logs
# ============================================================

@router.get("/logs")
async def get_logs(
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 100,
    session_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    decision: Optional[str] = None,
    threat_type: Optional[str] = None,
    ctx: OperatorContext = Depends(resolve_operator_tenant),
) -> Dict:
    """
    Query audit logs from CloudWatch Logs.
    
    Query Parameters:
        since: Start time (ISO 8601 timestamp, default: 1 hour ago)
        until: End time (ISO 8601 timestamp, default: now)
        limit: Max results (default: 100, max: 1000)
        session_id: Filter by session ID
        agent_id: Filter by agent ID
        decision: Filter by decision (ALLOW/DENY)
        threat_type: Filter by threat type
    
    Returns:
        LogsResponse with logs array, total, has_more, next_token
    """
    # WS-N N4.1 (FG-6): CloudWatch reads are NOT tenant-partitioned today. Customer
    # operator -> FAIL CLOSED (never fleet rows); platform -> fleet (audited).
    if not ctx.is_platform:
        raise HTTPException(
            status_code=422,
            detail="tenant-scoped telemetry not yet available (CloudWatch logs are fleet-shared)",
        )
    from app.api.tenancy_routes import _audit_platform_read
    _audit_platform_read(ctx, "*", "logs.list")

    from app.services.logs_service import LogsService

    logs_service = LogsService()
    return await logs_service.query_logs(
        since=since,
        until=until,
        limit=limit,
        session_id=session_id,
        agent_id=agent_id,
        decision=decision,
        threat_type=threat_type
    )


# ============================================================
# Workstream 17 / LLD 17 — Validation Signal Store endpoints
# ============================================================


def _decisions_service():
    """Lazy singleton — boto3 client init has nontrivial cold-start cost."""
    from app.services.decisions_service import DecisionsService
    global _decisions_service_instance
    try:
        return _decisions_service_instance
    except NameError:
        _decisions_service_instance = DecisionsService()
        return _decisions_service_instance


@router.get("/sessions/{session_id}/decisions")
async def get_session_decisions(
    session_id: str,
    request_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    limit: int = 100,
    ctx: OperatorContext = Depends(resolve_operator_tenant),
) -> Dict:
    """LLD 17 §8.2 — signals grouped by request_id, combiner applied per group.

    Dashboard hot path. p95 target ≤100ms (single DDB partition Query).
    Auth (WS-N N1/N1-dc): resolve_operator_tenant binds the tenant; DDB composite
    PK auto-scopes via current_tenant().
    """
    return _decisions_service().get_session_decisions(
        session_id=session_id, request_id=request_id, agent_id=agent_id, limit=limit
    )


@contextlib.asynccontextmanager
async def _dataplane_tenant_bind(http_request: Request):
    """Bind a data-plane READ (``/trail`` + ``/signals``) to the VERIFIED agent
    tenant for the duration of the store read (WS-M M5.2 / lld/39 §5).

    Verifies the agent JWT via ``resolve_tenant_from_jwt`` and:
      * ``should_deny`` (ENFORCE + not cleanly verified) → **401**. A tenant that
        is flipped to enforce must not have its trail read cross-tenant.
      * verified → ``set_current_tenant(ctx.tenant_id)`` for the read, reset in a
        ``finally`` (same-task token; mirrors the ``/validate`` bind at the enforce
        branch above).
      * disabled / shadow (identity not enforcing yet) → no bind change. Identity
        is OFF fleet-wide by default; keeping the ambient tenant here is
        byte-identical to pre-M5.2 for those tenants (the enforce flip is what
        activates the isolation, gated by WS-K's two-latch). We do NOT hard-deny a
        tokenless read at shadow/off (that would break the console before identity
        rolls out); the isolation is effective exactly when the tenant enforces.

    NOTE: this is deliberately NOT ``require_role`` — a data-plane read carries no
    operator role (Invariant 6). It is the JWT-tenant-bind, not RBAC.
    """
    from app.api.deps import resolve_tenant_from_jwt
    from app.config import settings
    from app.utils import tenancy

    ctx = await resolve_tenant_from_jwt(http_request)
    # WS-M M5.1 / lld/39 §5: when the data-plane credential latch is engaged, a
    # MISSING/INVALID agent JWT is denied here too — independent of `identity_mode` —
    # so EVERY data-plane route (not just `/validate`) requires a verified caller.
    # Default-off, so the console keeps working at fleet `off` until the operator
    # flips the latch (WS-K go-live runbook), same as `/validate`.
    if settings.require_dataplane_credential and not ctx.credential_present:
        raise HTTPException(status_code=401, detail="verified agent identity required")
    if ctx.should_deny:
        # ENFORCE + missing/invalid/forged JWT → fail-secure 401 (never read on the
        # ambient `default` partition, which would be a cross-tenant read).
        raise HTTPException(status_code=401, detail="verified agent identity required")
    if ctx.should_route:
        token = tenancy.set_current_tenant(ctx.tenant_id)
        try:
            yield
        finally:
            tenancy.reset_current_tenant(token)
    else:
        # disabled / shadow: identity not enforcing for this tenant yet — behave as
        # before (no bind change). The read stays on the ambient tenant.
        yield


@router.get("/sessions/{session_id}/signals")
async def get_session_signals(
    session_id: str,
    request_id: Optional[str] = None,
    source: Optional[str] = None,
    agent_id: Optional[str] = None,
    limit: int = 100,
    ctx: OperatorContext = Depends(resolve_operator_tenant),
) -> Dict:
    """LLD 17 §8.3 — raw signal list, no combiner applied. For debugging /
    advanced UI drill-down.

    Auth (WS-N D10 / ADR-038 — lane reversal): the SOLE consumer is the operator
    SOC console, so this is an OPERATOR control-plane read, NOT an agent data-plane
    read. Gated by ``resolve_operator_tenant`` (verified ALB-OIDC), which binds
    ``current_tenant(ctx.tenant_id)`` (deps.py:435) so the DDB Query hits the
    operator's own composite partition — customer=own-tenant, platform=fleet
    (audited). Reclassified from the former agent-JWT lane (``_dataplane_tenant_bind``)
    per ADR-038 (Accepted, founder 2026-07-07); verified no agent/SDK caller reads
    this GET (connectors only WRITE via ``POST /sessions/{id}/signals``, route below).
    """
    return _decisions_service().get_session_signals(
        session_id=session_id, request_id=request_id, source=source,
        agent_id=agent_id, limit=limit,
    )


@router.get("/sessions/{session_id}/trail")
async def get_session_trail(
    session_id: str,
    request_id: str,
    ctx: OperatorContext = Depends(resolve_operator_tenant),
) -> Dict:
    """WS-D / LLD 33 §9A — the full decision trail for one request (FR-6.8 / NFR-10).

    Returns the four buckets (ran / ran-ABSTAIN / ran-ERROR / not-run) in coverage
    order with derived display names + counts + recomputed `winning_source` /
    `block_point`. The READ endpoint WS-G (console) calls to render the
    Decision-detail view (G3.3).

    Contract:
      * `request_id` is REQUIRED — the primary form is session-scoped because the
        DDB PK is session-scoped (`tenant_session_id`); a request_id alone is not a
        partition key (§9A.1 FOOTGUN). No new query, no new index.
      * Auth (WS-N D10 / ADR-038 — lane reversal): the SOLE consumer is the operator
        console, so this is an OPERATOR control-plane read. Gated by
        ``resolve_operator_tenant`` (verified ALB-OIDC), which binds
        ``current_tenant(ctx.tenant_id)`` (deps.py:435) so the DDB Query hits the
        operator's own composite partition — customer=own-tenant, platform=fleet.
        Reclassified from the former agent-JWT lane (``_dataplane_tenant_bind``) per
        ADR-038 (Accepted, founder 2026-07-07); verified no agent/SDK caller reads it.
      * `next_token: null` — a single trail (~7 rows) fits one un-paged Query.
    """
    return _decisions_service().get_session_trail(
        session_id=session_id, request_id=request_id,
    )


@router.get("/decisions")
async def scan_decisions(
    since: Optional[str] = None,
    until: Optional[str] = None,
    agent_id: Optional[str] = None,
    decision: Optional[str] = None,
    threat_type: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = 50,
    cursor: Optional[str] = None,
    ctx: OperatorContext = Depends(resolve_operator_tenant),
) -> Dict:
    """LLD 17 §8.4 — paginated time-range scan via GSI 2.

    For cross-session views. The cursor is an opaque base64 token —
    consumers must round-trip it unchanged.
    Auth (WS-N N1): resolve_operator_tenant binds the tenant; DDB composite
    PK auto-scopes via current_tenant().
    """
    import asyncio

    try:
        # scan_decisions is synchronous boto3 (paged DDB Query). Offload to a
        # worker thread so it doesn't block the sole event loop and serialize
        # the dashboard's concurrent reads (RCA 2026-07-02).
        return await asyncio.to_thread(
            _decisions_service().scan_decisions,
            since=since, until=until, agent_id=agent_id,
            decision=decision, threat_type=threat_type, session_id=session_id,
            limit=limit, cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/sessions/{session_id}/signals", status_code=201)
async def post_session_signal(session_id: str, signal: Dict) -> Dict:
    """LLD 17 §8.1 — external producer signal write (Bedrock/Azure connectors).

    Auth (WS-M M2.8 / lld/39 §4.M2.8): INTERIM FAIL-CLOSED. This is an external
    producer write feeding the deny-overrides combiner + FP/FN training; the full
    producer credential + ``threat_type`` enum + bounded-``priority`` validation is
    design-only/deferred (D4). Until it lands, external writes are REJECTED (403) —
    the prior lenient-accept path (unknown source stored with priority=0) is removed.
    No first-party signal is lost: agents post via ``/validate``, not this route.
    The flag ``external_signal_write_enabled`` (default False) flips the route back on
    once the producer credential ships. Fail-secure: an unset/typo'd env stays closed.
    """
    from app.config import settings
    if not settings.external_signal_write_enabled:
        # Fail-closed: no verified external-producer credential yet.
        raise HTTPException(
            status_code=403,
            detail="external signal writes are disabled (producer credential not yet available)",
        )
    try:
        return _decisions_service().post_signal(
            session_id=session_id, signal_data=signal
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


# ============================================================
# Task 11: GET /v1/sessions - Query Sessions
# ============================================================

@router.get("/sessions")
async def get_sessions(
    status: Optional[str] = None,
    agent_id: Optional[str] = None,
    limit: int = 50,
    cursor: Optional[str] = None,
    ctx: OperatorContext = Depends(resolve_operator_tenant),
) -> Dict:
    """
    Query active sessions from DynamoDB — cursor-paginated.

    Query Parameters:
        status: Filter by quarantine status (active/quarantined/suspended)
        agent_id: Filter by agent ID
        limit: Max results per page (default: 50, max: 200)
        cursor: Opaque pagination token from a prior response's next_token

    Returns:
        SessionsResponse with sessions array, total count, and next_token

    Auth (WS-N N2): dual-mode — customer sees own tenant, platform sees fleet (audited).
    """
    from app.utils.session_manager import SessionManager

    scope = _operator_read_scope(ctx, "sessions.list")
    session_manager = SessionManager()
    return await session_manager.query_sessions(
        status=status,
        agent_id=agent_id,
        limit=limit,
        cursor=cursor,
        tenant_id=scope,
    )


# ============================================================
# Task 11: GET /v1/metrics - Query Summary Metrics
# ============================================================

@router.get("/metrics")
async def get_metrics(
    since: Optional[str] = None,
    until: Optional[str] = None,
    ctx: OperatorContext = Depends(resolve_operator_tenant),
) -> Dict:
    """
    Query summary metrics from CloudWatch Logs.

    Query Parameters:
        since: Start time (ISO 8601 timestamp, default: 1 hour ago)
        until: End time (ISO 8601 timestamp, default: now)

    Returns:
        MetricsResponse with aggregated metrics

    Auth (WS-N N4): CloudWatch reads fail-closed for customer (fleet-shared, no tenant field).
    """
    # WS-N N4.1 (FG-6): CloudWatch metrics are NOT tenant-partitioned today.
    if not ctx.is_platform:
        raise HTTPException(
            status_code=422,
            detail="tenant-scoped telemetry not yet available (CloudWatch metrics are fleet-shared)",
        )
    from app.api.tenancy_routes import _audit_platform_read
    _audit_platform_read(ctx, "*", "metrics.summary")

    from app.services.metrics_service import MetricsService

    metrics_service = MetricsService()
    return await metrics_service.query_metrics(
        since=since,
        until=until
    )


# ============================================================
# Workstream 21: SOC Console dashboard metrics (T20-T22)
# Served from CloudWatch Metrics (GetMetricData) + DDB joins. See LLD 21 §10.6.
# ============================================================

_VALID_METRIC_RANGES = {"1h", "24h", "7d", "30d"}
# Bucket tokens the time-series aggregator actually supports (mirror
# metrics_query_service._BUCKET_SECONDS). An unlisted value used to silently
# fall back to 1h — a caller asking for `5m` got 1h-bucketed data labelled `5m`.
# Validate at the edge so an unsupported bucket fails loudly (400), not silently.
_VALID_METRIC_BUCKETS = {"1h", "1d"}


def _trust_status(score: Optional[float]) -> str:
    """Map a 0-100 trust score to a status band (LLD 21 §11.2)."""
    if score is None:
        return "unknown"
    if score >= 80:
        return "healthy"
    if score >= 50:
        return "degraded"
    return "critical"


@router.get("/metrics/overview")
async def get_metrics_overview(
    range: str = "24h",
    ctx: OperatorContext = Depends(resolve_operator_tenant),
) -> Dict:
    """WS-21 T20: single call backing the dashboard KPI cards.

    CloudWatch (GetMetricData) for counts/latency/deny/trust + DDB for
    agent/provider/session counts. P0: delta% and false_positive_pct are null.
    """
    if range not in _VALID_METRIC_RANGES:
        raise HTTPException(
            status_code=400,
            detail=f"range must be one of {sorted(_VALID_METRIC_RANGES)}",
        )
    import asyncio

    from app.services.metrics_query_service import MetricsQueryService
    from app.services.agent_service import AgentService
    from app.utils.session_manager import SessionManager

    mq = MetricsQueryService()
    session_manager = SessionManager()

    # WS-N N2: dual-mode scope — customer gets own-tenant counts, platform gets fleet.
    scope = _operator_read_scope(ctx, "metrics.overview")

    # RCA 2026-07-02: these five reads are independent and each does blocking
    # AWS I/O (CloudWatch GetMetricData/ListMetrics + fleet DDB scans). On the
    # single event loop they were serialized (4 concurrent dashboard reads each
    # ~1.5s, finishing together). Offload the synchronous CloudWatch calls to
    # worker threads and run all five CONCURRENTLY so this handler's wall time is
    # the MAX of the reads, not their SUM. (The count_* / distribution methods
    # already offload their own blocking scans via asyncio.to_thread.)
    # WS-N FIX-B GAP-1: distribution must be fleet-wide for platform operators
    # (same dual-mode as session counts). Previously always used query_or_scan
    # (current_tenant), giving platform operators only their bound tenant's agents.
    # WS-N D11: pass the tenant scope into overview() — customer (scope=tenant_id) reads
    # the per-tenant Decisions{tenant_id,verdict}+ValidateLatency{tenant_id} streams;
    # platform (scope=None) reads the fleet-wide streams. Replaces the old null-fallback.
    cw, attack_categories, distribution, quarantined, suspended, below_threshold = await asyncio.gather(
        asyncio.to_thread(mq.overview, range, scope),
        asyncio.to_thread(mq.attack_category_count),
        AgentService().get_cloud_provider_distribution(fleet=ctx.is_platform),
        session_manager.count_sessions_by_status("quarantined", tenant_id=scope),
        session_manager.count_sessions_by_status("suspended", tenant_id=scope),
        session_manager.count_agents_below_trust(70.0, tenant_id=scope),
    )

    # WS-21 T01: keep the CloudWatch session gauges (QuarantinedSessions /
    # SuspendedSessions) fresh. The controller has no scheduler, so we emit the
    # fleet gauge on dashboard reads (cadence = dashboard load). The PutMetricData
    # WRITE now runs on a worker thread inside publish_session_metrics (RCA
    # 2026-07-02), so awaiting it no longer blocks the event loop for other
    # in-flight requests — it only adds its own ~one-RTT to THIS response. A true
    # off-response-path emitter (background scheduler) is a follow-up; we do NOT
    # use a bare create_task here (an unreferenced task can be GC'd before it
    # runs → silently dropped metric).
    #
    # WS-N FIX-B: ONLY platform operators publish the fleet gauge. A customer
    # operator's scoped counts must NEVER overwrite the fleet-wide CloudWatch
    # metric (QuarantinedSessions/SuspendedSessions are FLEET gauges). Customer
    # path skips the publish entirely — fleet accuracy preserved.
    if ctx.is_platform:
        from app.utils.metrics_publisher import MetricsPublisher
        await MetricsPublisher().publish_session_metrics(quarantined, suspended)

    # WS-N D11 (primary rescope): the count/latency KPIs are now PER-TENANT for a
    # customer operator — `overview(range, scope)` read the tenant-dimensioned
    # `Decisions{tenant_id,verdict}` + `ValidateLatency{tenant_id}` streams (scope=tenant_id),
    # or the fleet-wide streams (scope=None) for a platform operator. So threats_blocked /
    # requests_total / avg_latency_ms are honest tenant-scoped numbers, no longer nulled.
    # Two fields stay null in the customer view — an HONEST gap, not a fabrication:
    #   * trust_score  — TrustScoreAverage has no per-tenant CW stream (fleet-only), so cw["trust_score"]
    #                    is fleet-wide; we null it for a customer rather than leak the fleet average.
    #   * attack_categories — attack_category_count() is fleet-wide (ListMetrics over RuleId, no tenant
    #                    dim), so it too is nulled for a customer until a per-tenant attack stream exists.
    if ctx.is_platform:
        return {
            "range": range,
            "threats_blocked": cw["threats_blocked"],
            "threats_blocked_delta_pct": None,
            "attack_categories": attack_categories,
            "active_agents": distribution["total_nodes"],
            "clouds": distribution["clouds"],
            "trust_score": cw["trust_score"],
            "trust_status": _trust_status(cw["trust_score"]),
            "agents_below_threshold": below_threshold,
            "requests_total": cw["requests_total"],
            "avg_latency_ms": cw["avg_latency_ms"],
            "quarantined": quarantined,
            "false_positive_pct": None,
        }
    # Customer operator: tenant-scoped CW counts/latency (D11) + tenant-scoped DDB counts.
    # trust_score + attack_categories stay null (no per-tenant CW stream — see note above).
    return {
        "range": range,
        "threats_blocked": cw["threats_blocked"],
        "threats_blocked_delta_pct": None,
        "attack_categories": None,
        "active_agents": distribution["total_nodes"],
        "clouds": distribution["clouds"],
        "trust_score": None,
        "trust_status": "unknown",
        "agents_below_threshold": below_threshold,
        "requests_total": cw["requests_total"],
        "avg_latency_ms": cw["avg_latency_ms"],
        "quarantined": quarantined,
        "false_positive_pct": None,
    }


@router.get("/metrics/platform-distribution")
async def get_platform_distribution(
    ctx: OperatorContext = Depends(resolve_operator_tenant),
) -> Dict:
    """WS-21 T21: agent counts grouped by hosting cloud_provider.

    Auth (WS-N N1/N2.3 + FIX-B GAP-3): dual-mode — customer sees own-tenant
    distribution (query_or_scan); platform operator sees fleet-wide distribution
    (fleet_scan + audited via _operator_read_scope).
    """
    from app.services.agent_service import AgentService

    # WS-N FIX-B GAP-3: platform operator needs fleet view, not just bound tenant.
    if ctx.is_platform:
        from app.api.tenancy_routes import _audit_platform_read
        _audit_platform_read(ctx, "*", "metrics.platform_distribution")

    distribution = await AgentService().get_cloud_provider_distribution(fleet=ctx.is_platform)
    return {
        "total_nodes": distribution["total_nodes"],
        "providers": distribution["providers"],
    }


@router.get("/metrics/decisions-timeseries")
async def get_decisions_timeseries(
    range: str = "24h",
    bucket: str = "1h",
    ctx: OperatorContext = Depends(resolve_operator_tenant),
) -> Dict:
    """WS-21 T22: allowed-vs-blocked dense time-series (Chart.js area chart).

    Auth (WS-N D11): dual-mode, mirroring /metrics/overview — a customer operator gets
    a PER-TENANT series from the tenant-dimensioned Decisions{tenant_id,verdict} stream;
    a platform operator gets the FLEET series (audited). This replaces the earlier
    fail-closed 422 (which predated D11 proving the per-tenant stream exists).
    """
    # WS-N D11: scope the series to the operator's tenant (customer) or fleet (platform,
    # audited via _operator_read_scope). scope=None → fleet ValidationsTotal; scope=tid →
    # per-tenant Decisions stream.
    scope = _operator_read_scope(ctx, "metrics.decisions_timeseries")

    if range not in _VALID_METRIC_RANGES:
        raise HTTPException(
            status_code=400,
            detail=f"range must be one of {sorted(_VALID_METRIC_RANGES)}",
        )
    if bucket not in _VALID_METRIC_BUCKETS:
        raise HTTPException(
            status_code=400,
            detail=f"bucket must be one of {sorted(_VALID_METRIC_BUCKETS)}",
        )

    import asyncio

    from app.services.metrics_query_service import MetricsQueryService

    try:
        return await asyncio.to_thread(
            MetricsQueryService().decisions_timeseries, range, bucket, scope
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ============================================================
# Workstream 21 Phase 3: Discovery (read-model), attach, verdict (T30-T34)
# ============================================================

@router.get("/discovery/agents")
async def discovery_agents(
    cloud_provider: Optional[str] = None,
    framework: Optional[str] = None,
    risk: Optional[str] = None,
    status: Optional[str] = None,
    connection_id: Optional[str] = None,
    limit: int = 50,
    cursor: Optional[str] = None,
    ctx: OperatorContext = Depends(resolve_operator_tenant),
) -> Dict:
    """WS-21 T32: detected-agents table (static, policy-derived read-model).

    `connection_id` (connections-api-spec §5) scopes the review table to a just-
    connected account. Backward-compatible — omitted ⇒ current behavior. In the
    P0 policy-derived read-model there is no per-connection agent mapping yet, so
    it is accepted and forwarded for forward-compat (no-op filter today).
    """
    from app.services.discovery_service import DiscoveryService
    try:
        return await DiscoveryService().list_discovered(
            cloud_provider=cloud_provider, framework=framework, risk=risk,
            status=status, connection_id=connection_id, limit=limit, cursor=cursor,
        )
    except ValueError as exc:  # malformed cursor
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/discovery/summary")
async def discovery_summary(
    ctx: OperatorContext = Depends(resolve_operator_tenant),
) -> Dict:
    """WS-21 T32: discovery KPI cards.

    Auth (WS-N N5): bind-only — discovery source is tenant-scoped via connections.
    """
    from app.services.discovery_service import DiscoveryService
    return await DiscoveryService().summary()


@router.get("/discovery/platforms")
async def discovery_platforms(
    ctx: OperatorContext = Depends(resolve_operator_tenant),
) -> Dict:
    """WS-21 T32: per-cloud-provider detected counts (status idle in P0).

    Auth (WS-N N5): bind-only — discovery source is tenant-scoped via connections.
    """
    from app.services.discovery_service import DiscoveryService
    return await DiscoveryService().platforms()


@router.post("/discovery/import", status_code=201)
async def discovery_import(
    request: Dict,
    ctx: OperatorContext = Depends(require_role("editor")),
) -> Dict:
    """WS-21 T32: promote discovered agents to managed (D2 contract).

    Auth (WS-M M2.6 / lld/39 §2.3 row 17): ``require_role("editor")`` + every
    imported/promoted ``agent_id`` is PREFIX-STAMPED to ``ctx.tenant_id``
    (``{tenant}-{raw_id}``, delimiter-safe) BEFORE the write — so an import can never
    land a record under another tenant (the agent-id prefix IS the tenant ownership
    key that ``assert_owns(AGENT, id)`` later checks). An already-correctly-prefixed
    id is left unchanged (idempotent).

    Edge validation (WS-M FIX-B / backend.md): ``agent_ids`` MUST be a list of
    non-empty strings. A non-list body, or any non-string/empty element, is a
    caller fault → an honest **400** with a customer-safe message — NOT a bare 500
    (a non-string element would otherwise raise ``AttributeError`` on ``.startswith``
    and leak an internal failure). Input is narrowed here before the prefix-stamp.
    """
    from app.services.discovery_service import DiscoveryService
    raw_ids = request.get("agent_ids") or []
    enforcement_mode = request.get("enforcement_mode", "monitor")
    if not isinstance(raw_ids, list):
        raise HTTPException(status_code=400, detail="agent_ids must be a list of strings")
    for aid in raw_ids:
        if not isinstance(aid, str) or not aid:
            raise HTTPException(
                status_code=400, detail="agent_ids must contain only non-empty strings"
            )
    prefix = f"{ctx.tenant_id}-"
    agent_ids = [aid if aid.startswith(prefix) else f"{prefix}{aid}" for aid in raw_ids]
    from app.services.quota_service import QuotaExceeded
    try:
        return await DiscoveryService().import_agents(agent_ids, enforcement_mode)
    except QuotaExceeded as exc:
        # Per-tenant agent cap hit (LLD-26 WS-E E2a).
        raise HTTPException(status_code=429, detail=f"QUOTA_EXCEEDED: {exc}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ============================================================
# Cloud Connections (Connect-Account wizard — connections-api-spec.md)
# ============================================================

def _raise_connection_http(exc: Exception) -> NoReturn:
    """Map a connections-domain exception to the HONEST HTTP status and RAISE it
    (WS-M M2.9 / lld/39 §3.7).

    The factory raises rather than returns so a caller cannot accidentally
    ``_raise_connection_http(exc)`` without ``raise`` and silently swallow the
    failure into a fake ``200`` (the anti-pattern this hardens against). The
    ``detail`` messages here are domain classifications (``PROVIDER_NOT_AVAILABLE``
    etc.), not raw provider/STS internals — those never cross the boundary.
    """
    from app.services.connections_service import (
        ConnectionNotFound, InvalidRoleArn, NotConnected, ProviderNotAvailable,
    )
    if isinstance(exc, ConnectionNotFound):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ProviderNotAvailable):
        raise HTTPException(status_code=409, detail=f"PROVIDER_NOT_AVAILABLE: {exc}")
    if isinstance(exc, NotConnected):
        raise HTTPException(status_code=409, detail=f"NOT_CONNECTED: {exc}")
    if isinstance(exc, InvalidRoleArn):
        raise HTTPException(status_code=400, detail=f"VALIDATION_ERROR: {exc}")
    raise HTTPException(status_code=500, detail="connection operation failed")


# Whitelisted, customer-safe probe outcomes (WS-M M2.9). The raw provider message
# from `_probe` can carry the caller principal ARN / role ARN / account id / STS
# detail — never leak that to the client. We log the raw detail server-side and
# return a bounded, classification-only message keyed on the outcome.
def _sanitize_probe_message(connection_id: str, raw_message: str) -> str:
    """Return a customer-safe summary of a rejected-credential probe, logging the
    raw provider detail server-side (with a correlation id = connection_id)."""
    logger.info("connection probe rejected: conn=%s detail=%s", connection_id, raw_message)
    text = (raw_message or "").lower()
    if "accessdenied" in text or "not authorized" in text or "insufficient" in text or "probe failed" in text:
        return "Credential assumed but lacks the required read permissions (bedrock:ListAgents / equivalent)."
    if "assumerole" in text or "role" in text:
        return "Could not assume the provided role — check the role ARN, trust policy, and external id."
    if "no aws role" in text or "no azure" in text or "not set" in text:
        return raw_message  # the "missing credentials" guidance is already safe
    return "Credential probe failed — verify the connection's credentials and try again."


@router.get("/connections")
async def list_connections(
    ctx: OperatorContext = Depends(resolve_operator_tenant),
) -> Dict:
    """List the tenant's cloud connections (spec §4.1). Read; tenant-scoped by the
    ambient tenant. Auth (WS-N N1): bind-only — DDB composite PK auto-scopes."""
    from app.services.connections_service import ConnectionsService
    return ConnectionsService().list_connections()


@router.post("/connections", status_code=201)
async def create_connection(
    request: Dict,
    ctx: OperatorContext = Depends(require_role("admin")),
) -> Dict:
    """Create a connection + mint external_id (spec §4.2). 409 for gcp/azure (v1).

    Auth (WS-M M2.1): ``require_role("admin")`` — creating a cloud-credential
    connection is an admin action. Born tenant-scoped (PK = tenant_id), so a create
    has no cross-tenant target to own.
    """
    from app.services.connections_service import ConnectionsService, ConnectionError
    try:
        return ConnectionsService().create_connection(request.get("cloud_provider"))
    except ConnectionError as exc:
        _raise_connection_http(exc)


@router.get("/connections/{connection_id}")
async def get_connection(
    connection_id: str,
    ctx: OperatorContext = Depends(resolve_operator_tenant),
) -> Dict:
    """Get one connection (spec §4.3). Auth (WS-N N3): bind + assert_owns —
    foreign id -> 404, not a cross-tenant 200."""
    assert_owns(ctx, ResourceKind.CONNECTION, connection_id)
    from app.services.connections_service import ConnectionsService, ConnectionError
    try:
        return ConnectionsService().get_connection(connection_id)
    except ConnectionError as exc:
        _raise_connection_http(exc)


@router.put("/connections/{connection_id}")
async def update_connection(
    connection_id: str,
    request: Dict,
    ctx: OperatorContext = Depends(require_role("admin")),
) -> Dict:
    """Attach/replace the connection's credential reference after the operator
    sets it up (spec §4.4).

    AWS body: `{ "role_arn": "arn:aws:iam::...:role/..." }`.
    Azure body: `{ "azure": { "subscription_id", "tenant_id", "client_id",
    "secret_ref" } }` — the SP ids + a vault reference to the client-secret.

    Auth (WS-M M2.1): ``require_role("admin")`` + ``assert_owns(CONNECTION, id)``.
    FOOTGUN this closes — this route writes an IAM ``role_arn`` / Azure SP
    ``secret_ref``; an ungated caller (or a mere ``viewer``) could set credentials
    that ``test``/``scan`` then drive into a live ``sts:AssumeRole`` (a
    role/privilege gap). Cross-*tenant* is already blocked (born tenant-scoped PK);
    the assert_owns is defence-in-depth + 404-existence-masking.
    """
    from app.services.connections_service import ConnectionsService, ConnectionError
    assert_owns(ctx, ResourceKind.CONNECTION, connection_id)
    svc = ConnectionsService()
    azure = request.get("azure")
    try:
        if azure:
            return svc.set_azure_credentials(
                connection_id,
                subscription_id=azure.get("subscription_id"),
                tenant_id=azure.get("tenant_id"),
                client_id=azure.get("client_id"),
                secret_ref=azure.get("secret_ref"),
            )
        return svc.set_role_arn(connection_id, request.get("role_arn"))
    except ConnectionError as exc:
        _raise_connection_http(exc)


@router.post("/connections/{connection_id}/test")
async def test_connection(
    connection_id: str,
    request: Dict = None,
    ctx: OperatorContext = Depends(require_role("editor")),
) -> Dict:
    """Live read-only probe (spec §4.5) — AWS sts:AssumeRole / Azure SP token. A
    rejected credential returns 200 {ok:false, message}; only an unknown
    connection is an HTTP error.

    The probe does blocking, network-bound SDK calls (AssumeRole / Secrets
    Manager / Azure list), so it runs in a threadpool to keep the event loop free.

    Auth (WS-M M2.1): ``require_role("editor")`` + ``assert_owns(CONNECTION, id)`` —
    this drives a live cross-account ``sts:AssumeRole``, so a ``viewer`` must not
    reach it.

    Error contract (WS-M M2.9): the ``200 {ok:false, message}`` envelope is the
    documented partial-success carve-out for a *rejected credential* (a normal probe
    outcome, not a whole-request failure). But the ``message`` is SANITIZED — the raw
    provider/STS detail (principal ARN, account id) is logged server-side and NEVER
    returned to the client. An *unknown connection* is still an honest HTTP error.
    """
    from fastapi.concurrency import run_in_threadpool
    from app.services.connections_service import ConnectionsService, ConnectionError
    assert_owns(ctx, ResourceKind.CONNECTION, connection_id)
    try:
        role_arn = (request or {}).get("role_arn")
        result = await run_in_threadpool(
            ConnectionsService().test_connection, connection_id, role_arn
        )
    except ConnectionError as exc:
        _raise_connection_http(exc)
    if not result.get("ok"):
        result["message"] = _sanitize_probe_message(connection_id, result.get("message", ""))
    return result


@router.post("/connections/{connection_id}/scan", status_code=202)
async def scan_connection(
    connection_id: str,
    ctx: OperatorContext = Depends(require_role("editor")),
) -> Dict:
    """Trigger discovery for this connection (spec §4.6). 409 if not connected.

    Re-runs the blocking provider probe + persists the inventory, so it's
    offloaded to a threadpool (same rationale as /test).

    Auth (WS-M M2.1): ``require_role("editor")`` + ``assert_owns(CONNECTION, id)``."""
    from fastapi.concurrency import run_in_threadpool
    from app.services.connections_service import ConnectionsService, ConnectionError
    assert_owns(ctx, ResourceKind.CONNECTION, connection_id)
    try:
        return await run_in_threadpool(ConnectionsService().scan_connection, connection_id)
    except ConnectionError as exc:
        _raise_connection_http(exc)


@router.delete("/connections/{connection_id}", status_code=204)
async def delete_connection(
    connection_id: str,
    ctx: OperatorContext = Depends(require_role("admin")),
) -> None:
    """Disconnect — drop the reference; imported agents are retained (spec §4.7).

    Auth (WS-M M2.1): ``require_role("admin")`` + ``assert_owns(CONNECTION, id)``."""
    from app.services.connections_service import ConnectionsService, ConnectionError
    assert_owns(ctx, ResourceKind.CONNECTION, connection_id)
    try:
        ConnectionsService().delete_connection(connection_id)
    except ConnectionError as exc:
        _raise_connection_http(exc)


@router.delete("/feedback/subjects/{subject_locator}")
async def delete_feedback_subject(
    subject_locator: str,
    ctx: OperatorContext = Depends(require_role("admin")),
) -> Dict:
    """DSAR / GDPR subject deletion (WS-E2 / LLD 29 §6.4).

    Deletes every redacted feedback record for a subject in the CALLER's tenant via
    the `subject_locator` GSI. Tenant-scoped: the delete is bound STRICTLY to the
    identity-verified tenant, so tenant A can never delete tenant B's records.

    AuthZ (mirrors every mutating route in tenancy_routes.py — `revoke_credential`
    et al.): the destructive delete is gated by `require_role("admin")`, which layers
    on `resolve_operator_tenant` — the tenant comes from the ES256-verified ALB OIDC
    identity (`ctx.tenant_id`, a membership-asserted value), NEVER from a caller-
    supplied header. The prior `X-Tenant-Id` selector was a cross-tenant IDOR (any
    API-key holder could delete another tenant's records by setting the header) and a
    missing RBAC gate (any authenticated caller could invoke a GDPR-consequential
    delete). A platform operator targeting another tenant uses the audited
    `X-Aegion-Tenant` switch that `resolve_operator_tenant` validates against
    membership — never a raw tenant id. An unauthenticated / unauthorized caller is a
    401/403 from the dependency, never a silent fleet-wide delete.

    The honest GDPR claim (§6.4): "deletable by expiry (TTL) + by subject where a
    subject key exists". A record with no `subject_locator` (no stable subject key
    at write time) is TTL-only-deletable and is not reachable here — this endpoint
    deletes only the subject-locatable records for the given locator.

    Wiring note: this route must ALSO be added to `cdk/.../api_stack.py` per the
    per-resource API-GW convention (an undefined gateway route 403s). That is
    config wiring, deferred to the combined deploy step; the controller route +
    logic is asserted here."""
    from app.redaction.feedback_store import get_feedback_store

    # Tenant is server-side, from the verified identity — never a header selector.
    caller_tenant = ctx.tenant_id

    try:
        deleted = get_feedback_store().delete_subject(subject_locator, tenant_id=caller_tenant)
    except Exception as exc:  # noqa: BLE001 — surface a clean error, never a raw internal
        logger.exception("feedback DSAR delete failed for locator")
        raise HTTPException(status_code=500, detail="feedback deletion failed") from exc

    logger.info(
        "feedback DSAR delete: tenant=%s locator=<redacted> deleted=%d operator=%s",
        caller_tenant, deleted, ctx.email or ctx.sub or "unknown",
    )
    return {"deleted": deleted, "tenant_id": caller_tenant}


@router.post("/agents/{agent_id}/policies")
async def attach_agent_policy(
    agent_id: str,
    request: Dict,
    ctx: OperatorContext = Depends(require_role("editor")),
) -> Dict:
    """Set the agent's policy binding (agent-policy-management §4.2).

    Rebind-as-replace: attaching when already bound is an atomic swap (no 409).

    Auth (WS-M M1.1/M1.2): ``require_role("editor")`` + BOTH ownership asserts, in
    order — the agent first (403 on a foreign tenant-prefixed id) then the policy
    (404 on a cross-tenant opaque id). Operator attribution = verified ``ctx.sub``.
    """
    policy_id = request.get("policy_id")
    if not policy_id:
        raise HTTPException(status_code=400, detail="policy_id is required")
    assert_owns(ctx, ResourceKind.AGENT, agent_id)
    assert_owns(ctx, ResourceKind.POLICY, policy_id)
    from app.services.agent_service import AgentService
    try:
        return await AgentService().attach_policy(agent_id, policy_id, ctx.sub)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/agents/{agent_id}/policies/{policy_id}")
async def detach_agent_policy(
    agent_id: str,
    policy_id: str,
    ctx: OperatorContext = Depends(require_role("editor")),
) -> Dict:
    """Clear the agent's policy binding (agent-policy-management §4.2).

    Auth (WS-M M1.1/M1.2): ``require_role("editor")`` + ``assert_owns(AGENT, id)``.
    Operator attribution = verified ``ctx.sub``.
    """
    assert_owns(ctx, ResourceKind.AGENT, agent_id)
    from app.services.agent_service import AgentService
    try:
        return await AgentService().detach_policy(agent_id, policy_id, ctx.sub)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/decisions/{decision_id}/verdict")
async def post_decision_verdict(
    decision_id: str,
    request: Dict,
    ctx: OperatorContext = Depends(require_role("editor")),
) -> Dict:
    """WS-21 T34: capture an operator FP/FN verdict (silent in P0). decision_id
    = '<session_id>:<request_id>'.

    Auth (WS-M M2.7 / lld/39 §2.3 row 18): authenticate + derive the operator from
    the VERIFIED ``ctx.sub`` (NOT a spoofable body ``operator_id``) +
    ``assert_owns(SESSION, session_id)`` on the session component of the decision id.
    """
    valid = {"false_positive", "confirmed_threat", "false_negative", "confirmed_safe"}
    verdict = request.get("verdict")
    reason = request.get("reason")
    if verdict not in valid:
        raise HTTPException(status_code=400, detail=f"verdict must be one of {sorted(valid)}")
    if not reason:
        raise HTTPException(status_code=400, detail="reason is required")
    # decision_id = '<session_id>:<request_id>'; own the session, not the whole id.
    session_id = decision_id.split(":", 1)[0]
    assert_owns(ctx, ResourceKind.SESSION, session_id)
    # Operator attribution is the verified identity, never the client body.
    operator_id = ctx.sub
    try:
        return _decisions_service().record_verdict(decision_id, verdict, reason, operator_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


# ============================================================
# Task 5: GET /v1/agents - Agent Management APIs
# ============================================================

@router.get("/agents")
async def get_agents(
    enrich: bool = True,
    managed_only: bool = False,
    ctx: OperatorContext = Depends(resolve_operator_tenant),
) -> Dict:
    """
    List all registered agents.

    Auth (WS-N N1/N2.3): BIND-ONLY for ALL callers (customer AND platform).
    list_agents -> query_or_scan(current_tenant()) auto-scopes via the ambient
    tenant set by resolve_operator_tenant. A platform operator with break-glass
    X-Aegion-Tenant targeting tenant t_b sees t_b's agents (correct: the ambient
    tenant IS t_b). Fleet-wide agent listing is NOT exposed here — platform SOC
    uses /metrics/overview active_agents for fleet counts.

    Args:
        enrich: If True (default), include runtime statistics. Set to False for fast response.
        managed_only: If True, return ONLY Managed agents — those with observed
            /v1/validate traffic (data flowing). The Agent Inventory uses this so
            imported-but-silent agents stay in the Import tab (feature §8.1).
            Each returned agent carries `lifecycle_status="managed"` + `last_active`.

    Returns:
        AgentsResponse with agents array and total count
        
    Response Fields (per agent):
        - agent_id: Agent identifier
        - name: Agent display name
        - platform: Platform (sentra/bedrock)
        - security_type: Security type (secured/unsecured)
        - visibility: Visibility (external/internal)
        - type: Agent type (query/action/orchestrator)
        - status: Agent status from DynamoDB
        
    Additional fields when enrich=true:
        - uptime_seconds: Service uptime in seconds
        - last_seen: Last activity timestamp (ISO 8601)
        - trust_score_avg: Average trust score across sessions
        - requests_total: Total requests (last 24h)
        - requests_allowed: Allowed requests count
        - requests_denied: Denied requests count
        - active_sessions: Number of active sessions
    """
    from app.services.agent_service import AgentService
    
    agent_service = AgentService()
    return await agent_service.list_agents(enrich=enrich, managed_only=managed_only)


@router.get("/agents/{agent_id}")
async def get_agent(
    agent_id: str,
    ctx: OperatorContext = Depends(resolve_operator_tenant),
) -> Dict:
    """
    Get detailed information about a specific agent.

    Auth (WS-N N3): bind + assert_owns — foreign agent_id -> 403.
    """
    assert_owns(ctx, ResourceKind.AGENT, agent_id)
    from app.services.agent_service import AgentService

    agent_service = AgentService()
    agent = await agent_service.get_agent(agent_id)

    if not agent:
        raise HTTPException(
            status_code=404,
            detail=f"Agent {agent_id} not found"
        )

    return agent


@router.get("/agents/{agent_id}/tools")
async def get_agent_tools(
    agent_id: str,
    ctx: OperatorContext = Depends(resolve_operator_tenant),
) -> Dict:
    """
    Get list of allowed tools for an agent.

    Auth (WS-N N3): bind + assert_owns — foreign agent_id -> 403 (defence-in-depth,
    consistent with sibling get_agent; tools are agent-specific, not a global registry).

    Path Parameters:
        agent_id: Agent identifier

    Returns:
        ToolsResponse with tools array and total count

    Response Fields (per tool):
        - tool_id: Tool identifier
        - name: Tool name
        - type: Tool type (READ/WRITE/ADMIN)
        - description: Tool description
        - parameters: Tool parameters schema
        - rate_limit: Rate limit (requests per minute)

    HTTP Status Codes:
        200 OK - Success (empty array if agent has no tools)
        403 Forbidden - Agent not owned by tenant
        404 Not Found - Agent doesn't exist
    """
    assert_owns(ctx, ResourceKind.AGENT, agent_id)
    from app.services.agent_service import AgentService

    agent_service = AgentService()
    result = await agent_service.get_agent_tools(agent_id)
    
    # Check if agent exists (service returns empty tools array for non-existent agents)
    # We need to verify agent exists first
    if result.get('error') and 'not found' in result.get('error', '').lower():
        raise HTTPException(
            status_code=404,
            detail=f"Agent {agent_id} not found"
        )
    
    return result


# ============================================================
# Task 6: GET /v1/policies and GET /v1/sigma-rules
# ============================================================

@router.get("/policies")
async def get_policies(
    agent_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    cursor: Optional[str] = None,
    ctx: OperatorContext = Depends(resolve_operator_tenant),
) -> Dict:
    """
    Query agent policies with optional filters.
    
    Query Parameters:
        agent_id: Filter by agent ID (optional)
        status: Filter by status (active/inactive/deprecated) (optional)
        limit: Max results (default: 50, max: 200)
    
    Returns:
        PoliciesResponse with policies array, total, and has_more flag
        
    Response Fields (per policy):
        - policy_id: Policy identifier
        - agent_id: Agent this policy applies to
        - name: Policy name
        - description: Policy description
        - status: Policy status (active/inactive/deprecated)
        - rule: Policy rule expression
        - action: Action to take (DENY/ALLOW/WARN)
        - severity: Severity level (critical/high/medium/low)
        - match_count_24h: Number of matches in last 24 hours
        - created_at: Creation timestamp
        - updated_at: Last update timestamp
    
    HTTP Status Codes:
        200 OK - Success (empty array if no matches)
        400 Bad Request - Invalid status or limit
    """
    from app.services.policy_service import PolicyService
    
    # Validate limit
    if limit < 1 or limit > 200:
        raise HTTPException(
            status_code=400,
            detail="Limit must be between 1 and 200"
        )
    
    # Validate status if provided
    valid_statuses = ['active', 'inactive', 'deprecated']
    if status and status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
        )
    
    policy_service = PolicyService()
    try:
        return await policy_service.query_policies(
            agent_id=agent_id,
            status=status,
            limit=limit,
            cursor=cursor
        )
    except ValueError as exc:  # malformed cursor
        raise HTTPException(status_code=400, detail=str(exc))


# ============================================================
# Workstream 11: Policy CRUD Operations
# LLD 11 Reference: Agent Policy CRUD Operations
# ============================================================

@router.get("/policies/{policy_id}")
async def get_policy_by_id(
    policy_id: str,
    include_content: bool = True,
    ctx: OperatorContext = Depends(resolve_operator_tenant),
) -> Dict:
    """
    Get single policy with full content from S3.

    Path Parameters:
        policy_id: Policy identifier

    Query Parameters:
        include_content: Include S3 YAML content (default: true)

    Returns:
        Policy metadata and optional content from S3

    HTTP Status Codes:
        200 OK - Policy found
        404 Not Found - Policy not found

    Reference: LLD 11 Section 3.4 / WS-N N3: bind + assert_owns.
    """
    assert_owns(ctx, ResourceKind.POLICY, policy_id)
    from app.services.policy_service import PolicyService
    from app.exceptions import NotFoundException

    try:
        policy_service = PolicyService()

        # Get metadata
        metadata = await policy_service.get_policy(policy_id)
        if not metadata:
            raise NotFoundException(f"Policy {policy_id} not found")

        # Optionally get content from S3
        content = None
        if include_content:
            content = await policy_service.get_policy_content(policy_id)

        return {
            "success": True,
            "policy": {
                "metadata": metadata,
                "content": content
            }
        }
    except NotFoundException as e:
        raise HTTPException(status_code=e.status_code, detail=e.to_dict())


@router.post("/policies", status_code=201)
async def create_policy(
    request: PolicyCreateRequest,
    ctx: OperatorContext = Depends(require_role("editor")),
) -> Dict:
    """
    Create a new agent policy with hybrid storage.

    Auth (WS-M M1.1, closes BUG-1): ``require_role("editor")`` — verified ALB-OIDC
    operator, tenant resolved server-side. The mutation is scoped to
    ``ctx.tenant_id`` (a create has no cross-tenant target). Operator attribution
    is keyed on the verified ``ctx.sub`` — the old ``X-Operator-Email`` header is
    no longer an authority.

    Request Body:
        PolicyCreateRequest with schema_version, agent_id, name, version,
        allowed_tools, policies array

    Returns:
        Created policy metadata with policy_id, version, s3_key

    HTTP Status Codes:
        201 Created - Policy created successfully
        400 Bad Request - Validation failed
        409 Conflict - Policy already exists

    Reference: LLD 11 Section 3.1 / lld/39 §3.2
    """
    from app.services.policy_service import PolicyService
    from app.exceptions import ValidationException, ConflictException

    try:
        policy_service = PolicyService()
        return await policy_service.create_policy(
            # exclude_none: don't write optional fields the caller omitted
            # (platform, cloud_region, allowed_agents, cross_cloud_dependencies,
            # max_calls_per_minute) to S3 as explicit nulls. A null
            # max_calls_per_minute crashed the abuse detector (int > None). WS15.
            policy_data=request.dict(exclude_none=True),
            operator_email=ctx.sub,
        )
    except ValidationException as e:
        raise HTTPException(status_code=e.status_code, detail=e.to_dict())
    except ConflictException as e:
        raise HTTPException(status_code=e.status_code, detail=e.to_dict())


@router.put("/policies/{policy_id}")
async def update_policy(
    policy_id: str,
    request: PolicyUpdateRequest,
    ctx: OperatorContext = Depends(require_role("editor")),
) -> Dict:
    """
    Update existing policy (creates new S3 version).

    Auth (WS-M M1.1/M1.2): ``require_role("editor")`` + ``assert_owns(POLICY, id)``
    — a tenant-B editor cannot update tenant-A's policy (403/404, no mutation).
    Operator attribution = verified ``ctx.sub``.

    Path Parameters:
        policy_id: Policy identifier

    Request Body:
        PolicyUpdateRequest (same as create)

    Returns:
        Updated policy metadata with new version

    HTTP Status Codes:
        200 OK - Policy updated successfully
        400 Bad Request - Validation failed
        403 Forbidden - Cannot update disabled policy
        404 Not Found - Policy not found / cross-tenant target

    Reference: LLD 11 Section 3.2 / lld/39 §3.2-3.3
    """
    from app.services.policy_service import PolicyService
    from app.exceptions import (
        ValidationException,
        NotFoundException,
        ForbiddenException
    )

    assert_owns(ctx, ResourceKind.POLICY, policy_id)
    try:
        policy_service = PolicyService()
        return await policy_service.update_policy(
            policy_id=policy_id,
            # exclude_none: don't write optional fields the caller omitted
            # (platform, cloud_region, allowed_agents, cross_cloud_dependencies,
            # max_calls_per_minute) to S3 as explicit nulls. A null
            # max_calls_per_minute crashed the abuse detector (int > None). WS15.
            policy_data=request.dict(exclude_none=True),
            operator_email=ctx.sub,
        )
    except ValidationException as e:
        raise HTTPException(status_code=e.status_code, detail=e.to_dict())
    except NotFoundException as e:
        raise HTTPException(status_code=e.status_code, detail=e.to_dict())
    except ForbiddenException as e:
        raise HTTPException(status_code=e.status_code, detail=e.to_dict())


@router.delete("/policies/{policy_id}")
async def delete_policy(
    policy_id: str,
    ctx: OperatorContext = Depends(require_role("admin")),
) -> Dict:
    """
    Soft delete policy (set status=disabled).

    Auth (WS-M M1.1/M1.2): ``require_role("admin")`` (delete is admin-only) +
    ``assert_owns(POLICY, id)``. Operator attribution = verified ``ctx.sub``.

    Path Parameters:
        policy_id: Policy identifier

    Returns:
        Success response with disabled status

    HTTP Status Codes:
        200 OK - Policy disabled successfully (idempotent)
        403 Forbidden - Cannot delete system policies / below-role
        404 Not Found - Policy not found / cross-tenant target

    Note: This is a soft delete. The policy is marked as disabled but not removed
    from DynamoDB or S3, preserving the audit trail.

    Reference: LLD 11 Section 3.3 / lld/39 §3.2-3.3
    """
    from app.services.policy_service import PolicyService
    from app.exceptions import NotFoundException, ForbiddenException

    assert_owns(ctx, ResourceKind.POLICY, policy_id)
    try:
        policy_service = PolicyService()
        return await policy_service.delete_policy(
            policy_id=policy_id,
            operator_email=ctx.sub,
        )
    except NotFoundException as e:
        raise HTTPException(status_code=e.status_code, detail=e.to_dict())
    except ForbiddenException as e:
        raise HTTPException(status_code=e.status_code, detail=e.to_dict())


@router.patch("/policies/{policy_id}/status")
async def set_policy_status(
    policy_id: str,
    request: Dict,
    ctx: OperatorContext = Depends(require_role("editor")),
) -> Dict:
    """
    Enable or disable a policy (lifecycle status flip).

    agent-policy-management §4.3 / T20. Mirrors PATCH /sigma-rules/{rule_id}.

    Auth (WS-M M1.1/M1.2): ``require_role("editor")`` + ``assert_owns(POLICY, id)``.
    Operator attribution = verified ``ctx.sub``.

    Path Parameters:
        policy_id: Policy identifier

    Request Body:
        {"status": "active" | "disabled"}   (active = enable, disabled = disable)

    Returns:
        {success, policy_id, status, updated_at}

    HTTP Status Codes:
        200 OK - Status updated
        400 Bad Request - Invalid status
        404 Not Found - Policy not found / cross-tenant target

    Note (§2.8): Enable/Disable are ALLOWED on system (`created_by='system'`)
    policies — there is intentionally NO 403 here. Only DELETE is protected.
    """
    from app.services.policy_service import PolicyService
    from app.exceptions import ValidationException, NotFoundException

    assert_owns(ctx, ResourceKind.POLICY, policy_id)
    try:
        policy_service = PolicyService()
        return await policy_service.set_policy_status(
            policy_id=policy_id,
            status=request.get('status'),
            operator_email=ctx.sub,
        )
    except ValidationException as e:
        raise HTTPException(status_code=e.status_code, detail=e.to_dict())
    except NotFoundException as e:
        raise HTTPException(status_code=e.status_code, detail=e.to_dict())


@router.get("/sigma-rules")
async def get_sigma_rules(
    status: Optional[str] = None,
    level: Optional[str] = None,
    limit: int = 50,
    cursor: Optional[str] = None,
    range: str = "24h",
    ctx: OperatorContext = Depends(resolve_operator_tenant),
) -> Dict:
    """
    List Sigma rules with match counts.
    
    Query Parameters:
        status: Filter by status (stable/experimental/deprecated) (optional)
        level: Filter by severity level (critical/high/medium/low) (optional)
        limit: Max results (default: 50, max: 200)
        range: Match-count time window (1h/24h/7d/30d, default 24h)
    
    Returns:
        SigmaRulesResponse with rules array, total, and has_more flag
        
    Response Fields (per rule):
        - rule_id: Sigma rule identifier
        - title: Rule title
        - description: Rule description
        - status: Rule status (stable/experimental/deprecated)
        - level: Severity level (critical/high/medium/low)
        - tags: Rule tags (e.g., attack.llm01, owasp.llm.top10.2025)
        - patterns_count: Number of detection patterns
        - match_count_24h: Matches in last 24 hours
        - match_count_7d: Matches in last 7 days
        - last_matched: Last match timestamp
        - s3_key: S3 key for full rule content
        - created_at: Creation timestamp
        - updated_at: Last update timestamp
    
    Note: Returns metadata only. Full rule content (YAML) is in S3.
    
    HTTP Status Codes:
        200 OK - Success (empty array if no rules)
        400 Bad Request - Invalid status or level
    """
    from app.services.sigma_rules_service import SigmaRulesService
    
    # Validate limit
    if limit < 1 or limit > 200:
        raise HTTPException(
            status_code=400,
            detail="Limit must be between 1 and 200"
        )
    
    # Validate status if provided
    valid_statuses = ['stable', 'experimental', 'deprecated']
    if status and status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
        )
    
    # Validate level if provided
    valid_levels = ['critical', 'high', 'medium', 'low']
    if level and level not in valid_levels:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid level. Must be one of: {', '.join(valid_levels)}"
        )

    # Validate match-count range
    if range not in _VALID_METRIC_RANGES:
        raise HTTPException(
            status_code=400,
            detail=f"range must be one of {sorted(_VALID_METRIC_RANGES)}",
        )
    
    sigma_rules_service = SigmaRulesService()
    try:
        return await sigma_rules_service.list_sigma_rules(
            status=status,
            level=level,
            limit=limit,
            cursor=cursor,
            match_range=range
        )
    except ValueError as exc:  # malformed cursor
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/sigma-rules/{rule_id}")
async def update_sigma_rule(
    rule_id: str,
    request: Dict,
    ctx: OperatorContext = Depends(require_platform),
) -> Dict:
    """
    Update Sigma rule (enable/disable).

    Args:
        rule_id: Rule identifier
        request: {"status": "enabled" | "disabled"}  (native "stable"/"deprecated" also accepted)

    Returns:
        Success response or error

    Auth (WS-M M3.1 / lld/39 §3.5): ``require_platform`` — NOT ``require_role``. The
    sigma store (``sentra-sigma-rules-metadata`` + S3 ``sigma_rules/llm/``) is
    fleet-global, NOT tenant-partitioned (lld/35 §13): flipping a rule to
    ``deprecated`` stops ``load_rules_metadata_from_dynamodb`` from loading it for
    EVERY tenant. A tenant-scoped role here would let any tenant-admin disable a
    detection rule fleet-wide — the disable-switch ADR-034 forbids (via the CRUD
    door). The gate covers both this PATCH handler AND the ``_bump_enforcement_version``
    epoch write it triggers (one call chain behind one door). Copying the
    tenant-scoped ``delete_feedback_subject`` pattern here would be the wrong-scope
    trap — that route is correctly tenant-scoped; this one must be platform.
    """
    from app.services.sigma_rules_service import SigmaRulesService, _enabled_to_ddb_status

    requested = request.get('status')
    ddb_status = _enabled_to_ddb_status(requested)
    if ddb_status is None:
        raise HTTPException(
            status_code=400,
            detail="Invalid status. Must be one of: enabled, disabled",
        )

    service = SigmaRulesService()
    success = await service.update_rule_status(rule_id, ddb_status)

    if not success:
        raise HTTPException(status_code=404, detail="Rule not found")

    # Echo the console's vocabulary back, not the stored value.
    api_status = "enabled" if ddb_status == "stable" else "disabled"
    return {"success": True, "rule_id": rule_id, "status": api_status}


@router.get("/sigma-rules/{rule_id}/content")
async def get_sigma_rule_content(
    rule_id: str,
    ctx: OperatorContext = Depends(resolve_operator_tenant),
) -> Dict:
    """
    Get a Sigma rule's full content, including its detection selections/patterns.

    Downloads the rule YAML from S3 (via the metadata's s3_key) and returns a
    UI-friendly breakdown of the detection block so the console can show exactly
    what each rule matches on.

    Path Parameters:
        rule_id: Sigma rule identifier (e.g., sigma-llm-001)

    Returns:
        - rule_id, title, description, level, status, tags
        - condition: the Sigma detection condition (e.g., "1 of them")
        - selections: [{name, field, patterns: [...]}] — one entry per detection
          selection. ``field`` is the matched field+modifier (e.g.
          "prompt|contains"); ``patterns`` are the literal substrings matched.
        - patterns_total: total number of patterns across all selections
    """
    from app.services.sigma_rules_service import SigmaRulesService

    service = SigmaRulesService()
    rule_data = await service.get_sigma_rule_content(rule_id)
    if not rule_data:
        raise HTTPException(status_code=404, detail="Rule not found")

    detection = rule_data.get("detection") or {}
    selections = []
    patterns_total = 0
    condition = None
    for sel_name, sel_data in detection.items():
        if sel_name == "condition":
            condition = sel_data
            continue
        if isinstance(sel_data, dict):
            for field, values in sel_data.items():
                pattern_list = values if isinstance(values, list) else [values]
                patterns_total += len(pattern_list)
                selections.append({
                    "name": sel_name,
                    "field": field,
                    "patterns": [str(p) for p in pattern_list],
                })

    metadata = rule_data.get("metadata") or {}
    return {
        "rule_id": rule_id,
        "title": rule_data.get("title") or metadata.get("title") or rule_id,
        "description": rule_data.get("description", metadata.get("description", "")),
        "level": rule_data.get("level", metadata.get("level", "medium")),
        "status": metadata.get("status", rule_data.get("status", "")),
        "tags": rule_data.get("tags", metadata.get("tags", [])),
        "condition": condition,
        "selections": selections,
        "patterns_total": patterns_total,
    }


# ============================================================
# Workstream 12: Conversation Timeline API
# ============================================================

@router.get("/logs/conversation/{conversation_id}")
async def get_conversation_timeline(
    conversation_id: str,
    ctx: OperatorContext = Depends(resolve_operator_tenant),
) -> Dict:
    """
    Get complete timeline of a conversation (cross-agent).

    Returns hierarchical tree of requests showing parent-child relationships.

    Path Parameters:
        conversation_id: Conversation identifier (e.g., conv-abc123)

    Returns:
        ConversationTimelineResponse with:
        - conversation_id: The conversation identifier
        - total_requests: Total number of requests in conversation
        - timeline: Hierarchical tree of requests with children
        - statistics: Summary stats (allowed/denied counts, agents involved)

    Example Response:
        {
            "conversation_id": "conv-abc123",
            "total_requests": 3,
            "timeline": [
                {
                    "request_id": "req-cqa-001",
                    "agent_id": "customer-query-agent",
                    "tool_name": "call_payment_agent",
                    "decision": "ALLOW",
                    "children": [
                        {
                            "request_id": "req-pay-001",
                            "agent_id": "payment-agent",
                            "tool_name": "process_refund",
                            "decision": "ALLOW",
                            "children": []
                        }
                    ]
                }
            ],
            "statistics": {
                "total_allowed": 3,
                "total_denied": 0,
                "agents_involved": ["customer-query-agent", "payment-agent"],
                "max_call_depth": 1
            }
        }

    HTTP Status Codes:
        200 OK - Success (empty timeline if conversation not found)

    Auth (WS-N N3): bind + assert_owns(CONVERSATION) — foreign conversation -> 404.
    """
    assert_owns(ctx, ResourceKind.CONVERSATION, conversation_id)
    from app.services.conversation_service import ConversationService

    conversation_service = ConversationService()
    return await conversation_service.get_timeline(conversation_id)


# ============================================================
# Task 12 & 13: POST /v1/rollback - Manual Rollback
# ============================================================

@router.post("/rollback")
async def rollback_action(
    request: Dict,
    ctx: OperatorContext = Depends(require_role("admin")),
) -> Dict:
    """
    Manually rollback a reversible action.

    Request Body:
        action_id: Unique action identifier
        action_type: Type of action (e.g., "process_refund")
        reason: Reason for rollback

    Returns:
        Success response with rollback details or error response

    HTTP Status Codes:
        200 OK - Rollback successful
        404 Not Found - Action doesn't exist / not owned by tenant
        400 Bad Request - Action not reversible or already rolled back
        500 Internal Server Error - Rollback failed
        503 Service Unavailable - Action resolution temporarily unavailable (retry)

    Auth (WS-M M2.3 / lld/39 §2.3 row 15): ``require_role("admin")`` +
    ``assert_owns(ACTION, action_id)`` (tenant resolved via the injection-safe
    Logs-Insights path) + a SECOND in-coordinator tenant re-verify (``tenant_id`` is
    passed through). Operator attribution = verified ``ctx.sub``, never a body field.
    A crafted ``action_id`` is rejected by the grammar regex. Idempotency: a durable
    conditional-PutItem ledger (M2.4) prevents a double-reverse.
    """
    from app.utils.rollback_coordinator import RollbackCoordinator

    # Validate request
    action_id = request.get("action_id")
    action_type = request.get("action_type")
    reason = request.get("reason")

    if not all([action_id, action_type, reason]):
        raise HTTPException(
            status_code=400,
            detail="Missing required fields: action_id, action_type, reason"
        )

    # Anti-IDOR: assert the caller's tenant owns this action before doing anything.
    assert_owns(ctx, ResourceKind.ACTION, action_id)

    # Execute rollback — operator is the verified identity; tenant is re-verified
    # inside the coordinator (defence-in-depth on the money-movement path).
    rollback_coordinator = RollbackCoordinator()
    result = await rollback_coordinator.rollback_action(
        action_id=action_id,
        action_type=action_type,
        reason=reason,
        operator_id=ctx.sub,
        tenant_id=ctx.tenant_id,
    )

    # Handle result
    if not result.get("success"):
        # M2.5: a retryable resolution-substrate failure is a distinct 503, not a 404.
        if result.get("status") == "RESOLUTION_UNAVAILABLE":
            raise HTTPException(status_code=503, detail=result.get("message", "resolution unavailable"))
        message = result.get("message", "Rollback failed")

        if "not found" in message.lower():
            raise HTTPException(status_code=404, detail=message)
        elif "already rolled back" in message.lower():
            raise HTTPException(status_code=400, detail=message)
        elif "not reversible" in message.lower():
            raise HTTPException(status_code=400, detail=message)
        else:
            raise HTTPException(status_code=500, detail=message)

    return result


@router.post("/rollback/conversation/{conversation_id}")
async def rollback_conversation(
    conversation_id: str,
    request: Dict,
    ctx: OperatorContext = Depends(require_role("admin")),
) -> Dict:
    """
    Roll back ALL WRITE operations in a conversation.
    
    Fetches all audit logs for the conversation, filters for reversible
    WRITE operations, and executes rollback in LIFO order (last action first).
    
    Path Parameters:
        conversation_id: Conversation identifier (e.g., conv-abc123)
    
    Request Body:
        reason: Reason for rollback
        operator_id: Operator performing rollback (optional, default: "system")
    
    Returns:
        Rollback summary with:
        - success: Whether all rollbacks succeeded
        - conversation_id: The conversation identifier
        - rolled_back_count: Number of actions rolled back
        - failed_count: Number of failed rollbacks
        - rolled_back_actions: List of rolled back action details
        - failed_actions: List of failed action details with errors
    
    Example Response:
        {
            "success": true,
            "conversation_id": "conv-abc123",
            "rolled_back_count": 2,
            "failed_count": 0,
            "rolled_back_actions": [
                {"action_id": "act-001", "tool_name": "process_refund"},
                {"action_id": "act-002", "tool_name": "create_order"}
            ],
            "failed_actions": [],
            "reason": "Refund denied - rolling back transaction"
        }
    
    HTTP Status Codes:
        200 OK - Rollback completed (check success field for partial failures)
        400 Bad Request - Missing required fields
        500 Internal Server Error - Rollback failed completely
    """
    from app.utils.rollback_coordinator import RollbackCoordinator

    # Validate request
    reason = request.get("reason")
    if not reason:
        raise HTTPException(
            status_code=400,
            detail="Missing required field: reason"
        )

    # Anti-IDOR (WS-M M2.3 / lld/39 §2.3 row 16): the conversation is a
    # session-scoped resource — own it before reversing any action in it. Operator
    # attribution = verified ctx.sub, never a body default of "system".
    assert_owns(ctx, ResourceKind.CONVERSATION, conversation_id)

    # Execute conversation rollback. Thread ctx.tenant_id (WS-M M2.3 conversation-path
    # fix): the coordinator tenant-scopes the enumeration, per-action re-verifies, and
    # claims the idempotency ledger — two independent tenant checks on this money path
    # (the assert_owns above + the coordinator's re-verify), mirroring rollback_action.
    rollback_coordinator = RollbackCoordinator()
    result = await rollback_coordinator.rollback_conversation(
        conversation_id=conversation_id,
        reason=reason,
        operator_id=ctx.sub,
        tenant_id=ctx.tenant_id,
    )

    # Honest error contract (engineering rule: never wrap a whole-request failure in
    # 200). A TOTAL failure — the coordinator's outer-except path — is a batch that
    # never ran: it carries success=False, a top-level "message", and zero processed
    # actions. That must surface as a real 5XX so callers/monitors/retries see it,
    # mirroring the single-action route. A PARTIAL result (some actions reversed, some
    # failed) is a legitimate batch response (per-item statuses in failed_actions[]) —
    # it keeps 200 with success reflecting whether any action failed. The customer-safe
    # message is already sanitized coordinator-side; a correlation id ties it to logs.
    if result.get("success") is False and "message" in result and not (
        result.get("rolled_back_actions") or result.get("failed_actions")
        or result.get("skipped_actions")
    ):
        raise HTTPException(
            status_code=500,
            detail=result.get("message", "Conversation rollback failed"),
        )

    return result


# ============================================================
# Task 13: POST /v1/quarantine/{session_id} - Manual Quarantine
# ============================================================

@router.post("/quarantine/{session_id}")
async def quarantine_session(
    session_id: str,
    request: Dict,
    ctx: OperatorContext = Depends(require_role("admin")),
) -> Dict:
    """
    Manually quarantine a session (operator override).

    Path Parameters:
        session_id: Session identifier

    Request Body:
        reason: Reason for quarantine

    Returns:
        Success response with updated session or error response

    HTTP Status Codes:
        200 OK - Session quarantined
        404 Not Found - Session doesn't exist
        400 Bad Request - Session already quarantined/suspended
        500 Internal Server Error - Update failed

    Auth (WS-M M2.2 / lld/39 §2.3 row 14): ``require_role("admin")`` +
    ``assert_owns(SESSION, session_id)``; operator attribution derives from the
    VERIFIED ``ctx.sub`` (NOT a spoofable body ``operator_id``).
    """
    from app.utils.session_manager import SessionManager

    # Validate request
    reason = request.get("reason")
    if not reason:
        raise HTTPException(
            status_code=400,
            detail="Missing required field: reason"
        )
    # Operator is the verified identity, never the client body.
    operator_id = ctx.sub
    assert_owns(ctx, ResourceKind.SESSION, session_id)

    # Execute quarantine
    session_manager = SessionManager()
    
    try:
        # Get session first to check if it exists
        session = await session_manager.get_session(session_id)
        
        if not session:
            raise HTTPException(
                status_code=404,
                detail=f"Session {session_id} not found"
            )
        
        # Idempotent: re-quarantining an already-quarantined/suspended session is a no-op success,
        # not a 400 — operators and retries should be safe to repeat (idempotency / ops review).
        current_status = session.get('quarantine_status', 'active')
        if current_status in ['quarantined', 'suspended']:
            return {
                "success": True,
                "message": f"Session {session_id} already {current_status}",
                "session_id": session_id,
                "previous_status": current_status,
                "new_status": current_status,
                "trust_score": session.get('trust_score'),
                "idempotent": True,
            }

        # Quarantine session
        updated_session = await session_manager.manual_quarantine(
            session_id=session_id,
            reason=reason,
            operator_id=operator_id
        )

        return {
            "success": True,
            "message": f"Session {session_id} quarantined successfully",
            "session_id": session_id,
            "previous_status": current_status,
            "new_status": updated_session.get('quarantine_status'),
            "trust_score": updated_session.get('trust_score')
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to quarantine session {session_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to quarantine session: {str(e)}"
        )


@router.delete("/quarantine/{session_id}")
async def release_session(
    session_id: str,
    ctx: OperatorContext = Depends(require_role("admin")),
) -> Dict:
    """Release a session from quarantine ('un-quarantine'; operator override). Idempotent.

    Sets quarantine_status back to 'active' and restores trust above the quarantine threshold so the
    session isn't immediately re-quarantined. Releasing an already-active session is a no-op success.

    Auth (WS-M M2.2 / lld/39 §2.3 row 13): ``require_role("admin")`` +
    ``assert_owns(SESSION, session_id)``. FOOTGUN this closes — the prior handler took
    an ``operator_id`` query default (``"operator"``) with NO auth, so a *contained
    agent could lift its own quarantine*. De-containment is now authenticated + admin;
    the operator is the verified ``ctx.sub``, never a query param.
    """
    from app.utils.session_manager import SessionManager

    operator_id = ctx.sub
    assert_owns(ctx, ResourceKind.SESSION, session_id)
    session_manager = SessionManager()
    try:
        session = await session_manager.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        current_status = session.get('quarantine_status', 'active')
        if current_status == 'active':
            return {
                "success": True, "message": f"Session {session_id} already active",
                "session_id": session_id, "new_status": "active", "idempotent": True,
            }
        updated = await session_manager.manual_release(session_id, operator_id)
        return {
            "success": True, "message": f"Session {session_id} released from quarantine",
            "session_id": session_id, "previous_status": current_status,
            "new_status": updated.get('quarantine_status'), "trust_score": updated.get('trust_score'),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to release session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to release session: {str(e)}")
