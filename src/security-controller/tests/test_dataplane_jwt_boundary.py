"""Data-plane JWT boundary + /trail-/signals tenant bind + operator contextvar reset
(WS-M M5.1 / M5.2 / M5.3, lld/39 §5).

M5.1: a MISSING/INVALID agent JWT is denied on the data plane INDEPENDENT of
``identity_mode`` when the ``require_dataplane_credential`` latch is engaged — closing
the tokenless fall-through (previously a tokenless ``/validate`` call was only denied at
effective ``enforce`` and fell through to the legacy path at ``shadow``/``off``). The
latch decouples data-plane authN from the enforcement-strictness rollout ceiling.
M5.2: the deployed WS-D ``/trail`` + ``/signals`` read handlers resolved the partition
from the ambient ``current_tenant()`` (``"default"``) — a live cross-tenant read for a
non-enforcing tenant. They now bind the VERIFIED agent tenant (NOT ``require_role`` —
Invariant 6). M5.3: a *raising* ``resolve_operator_tenant`` (401/403) must reset the
tenant contextvar to the ``default`` sentinel, not leave a stale same-context bind.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, Mock, patch

from app.api import routes as R
from app.api.deps import TenantContext
from app.main import app
from app.utils import tenancy


class _Req:
    headers = {}


# --------------------------------------------------------------------------- #
# M5.1 — deny missing/invalid agent JWT on /validate INDEPENDENT of identity_mode
# --------------------------------------------------------------------------- #
_AGENT_ID = "t_a-aws-x-deadbeef"


def _validate_payload(**overrides):
    base = dict(
        request_id="req-m5", session_id="sess-m5", agent_id=_AGENT_ID,
        tool_name="query_customers", tool_params={}, user_input="hi",
        timestamp="2026-07-06T00:00:00Z", operation_type="READ",
    )
    base.update(overrides)
    return base


@pytest.fixture
def validate_client():
    return TestClient(app)


@pytest.fixture
def spy_validation_service():
    """Spy the process-wide ValidationService so a DENY-before-routing is provable by
    asserting the pipeline was never reached (and an ALLOW proves it was)."""
    svc = Mock()
    svc.validate_tool_call = AsyncMock(return_value={
        "decision": "ALLOW", "reason": "ok", "trust_score": 99.0,
        "session_id": "sess-m5", "latency_ms": 1.0,
    })
    prev = getattr(app.state, "validation_service", None)
    app.state.validation_service = svc
    try:
        yield svc
    finally:
        app.state.validation_service = prev


def _post_validate_with_ctx(client, ctx, *, latch: bool):
    """Drive POST /v1/validate with a resolved TenantContext + the latch state, without
    real JWTs/AWS (resolve_tenant_from_jwt is patched to return `ctx`)."""
    with patch("app.api.deps.resolve_tenant_from_jwt", new=AsyncMock(return_value=ctx)), \
         patch("app.config.settings.require_dataplane_credential", latch), \
         patch("app.api.routes._identity_deny", new=AsyncMock(return_value={
             "decision": "DENY", "reason": ctx.reason or "IDENTITY_UNVERIFIED",
             "trust_score": 0.0, "session_id": "sess-m5", "latency_ms": 0.0,
             "violation_type": ctx.reason or "IDENTITY_UNVERIFIED",
         })) as deny_spy:
        resp = client.post("/v1/validate", json=_validate_payload())
    return resp, deny_spy


def test_tokenless_validate_denied_at_shadow(validate_client, spy_validation_service):
    """A missing token resolves to `unverified(effective_mode=shadow)`. With the latch
    ON it is DENIED (not routed to the legacy path) even though shadow does not enforce.
    FAILS against the pre-fix code, which fell through to `validate_tool_call` at shadow."""
    ctx = TenantContext.unverified(effective_mode="shadow")
    resp, deny_spy = _post_validate_with_ctx(validate_client, ctx, latch=True)
    assert resp.status_code == 200
    assert resp.json()["decision"] == "DENY"
    deny_spy.assert_awaited_once()
    spy_validation_service.validate_tool_call.assert_not_called()


def test_tokenless_validate_denied_at_off(validate_client, spy_validation_service):
    """A missing token at effective `off` (the byte-identical-to-pre-26 posture). With
    the latch ON it is DENIED regardless — the tokenless fall-through at `off` was the
    fresh-env-open bug (§8 residual #1). FAILS against the pre-fix code."""
    ctx = TenantContext.unverified(effective_mode="off")
    resp, deny_spy = _post_validate_with_ctx(validate_client, ctx, latch=True)
    assert resp.json()["decision"] == "DENY"
    deny_spy.assert_awaited_once()
    spy_validation_service.validate_tool_call.assert_not_called()


def test_forged_jwt_denied_all_modes(validate_client, spy_validation_service):
    """A forged/bad-signature token resolves to `unverified` (credential_present False)
    in every mode. With the latch ON it is denied at shadow AND off AND enforce."""
    for mode in ("off", "shadow", "enforce"):
        spy_validation_service.validate_tool_call.reset_mock()
        ctx = TenantContext.unverified(effective_mode=mode)
        resp, deny_spy = _post_validate_with_ctx(validate_client, ctx, latch=True)
        assert resp.json()["decision"] == "DENY", f"forged token must deny at {mode}"
        spy_validation_service.validate_tool_call.assert_not_called()


def test_wellformed_unverified_allowed_only_in_soak(validate_client, spy_validation_service):
    """A well-formed VERIFIED credential during soak (shadow) is allowed onto the legacy
    path (observed, not routed) — identity_mode still governs the strictness of a
    *verified-but-not-yet-enforced* posture. The latch keys only on credential PRESENCE:
    a verified token IS present, so the latch does not deny it; shadow then observes
    without routing (validate_tool_call runs)."""
    ctx = TenantContext.verified(tenant_id="t_a", agent_id=_AGENT_ID, effective_mode="shadow")
    resp, _ = _post_validate_with_ctx(validate_client, ctx, latch=True)
    assert resp.status_code == 200
    assert resp.json()["decision"] == "ALLOW"
    spy_validation_service.validate_tool_call.assert_called_once()


def test_latch_off_preserves_tokenless_fallthrough(validate_client, spy_validation_service):
    """DEFAULT-SAFE: with the latch OFF (the live-env default), a tokenless call at
    `off`/`disabled` still falls through to the legacy path — byte-identical to pre-M5,
    so the live env (identity off, no agent sends a JWT) is unchanged. Proves the latch
    is a real gate and the change is not a silent production-breaking deny."""
    ctx = TenantContext.disabled()
    resp, _ = _post_validate_with_ctx(validate_client, ctx, latch=False)
    assert resp.status_code == 200
    assert resp.json()["decision"] == "ALLOW"
    spy_validation_service.validate_tool_call.assert_called_once()


def test_credential_present_classification():
    """Unit: `credential_present` is True only when a usable credential was presented
    (verified) or a signature verified against a real key but failed a downstream bind
    (tampered/mismatch). It is False for unverified (missing/bad/expired) and disabled —
    the states the latch must deny. This pins the exact classification the /validate and
    /trail latch checks depend on."""
    assert TenantContext.verified("t_a", "t_a-x", "enforce").credential_present is True
    assert TenantContext.tampered("t_a", "enforce").credential_present is True
    assert TenantContext.mismatch("t_a", "enforce").credential_present is True
    assert TenantContext.unverified(effective_mode="off").credential_present is False
    assert TenantContext.disabled().credential_present is False


# --------------------------------------------------------------------------- #
# M5.2 — /trail + /signals bind the verified tenant (deny at enforce; no default)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_trail_read_binds_verified_tenant():
    """A verified+enforce agent JWT binds ctx.tenant_id for the DecisionsService read
    (not the ambient default)."""
    seen = {}

    def _trail(**k):
        seen["tenant"] = tenancy.current_tenant()
        return {"ok": True}

    svc = Mock()
    svc.get_session_trail = Mock(side_effect=_trail)
    verified = TenantContext.verified(tenant_id="t_a", agent_id="t_a-x", effective_mode="enforce")
    with patch("app.api.deps.resolve_tenant_from_jwt", return_value=verified), \
         patch("app.api.routes._decisions_service", return_value=svc):
        out = await R.get_session_trail("s1", "r1", _Req())
    assert out == {"ok": True}
    assert seen["tenant"] == "t_a"  # bound to the verified tenant during the read


@pytest.mark.asyncio
async def test_signals_read_binds_verified_tenant():
    seen = {}

    def _signals(**k):
        seen["tenant"] = tenancy.current_tenant()
        return {"signals": []}

    svc = Mock()
    svc.get_session_signals = Mock(side_effect=_signals)
    verified = TenantContext.verified(tenant_id="t_b", agent_id="t_b-x", effective_mode="enforce")
    with patch("app.api.deps.resolve_tenant_from_jwt", return_value=verified), \
         patch("app.api.routes._decisions_service", return_value=svc):
        await R.get_session_signals("s1", _Req())
    assert seen["tenant"] == "t_b"


@pytest.mark.asyncio
async def test_trail_enforce_missing_jwt_denies_not_default():
    """At enforce, a missing/invalid JWT (should_deny) → 401, NEVER a read on the
    ambient default partition."""
    unver = TenantContext.unverified(effective_mode="enforce")  # should_deny is True
    svc = Mock()
    with patch("app.api.deps.resolve_tenant_from_jwt", return_value=unver), \
         patch("app.api.routes._decisions_service", return_value=svc):
        with pytest.raises(HTTPException) as ei:
            await R.get_session_trail("s1", "r1", _Req())
    assert ei.value.status_code == 401
    svc.get_session_trail.assert_not_called()


@pytest.mark.asyncio
async def test_trail_disabled_mode_reads_without_bind_change():
    """Identity OFF fleet-wide (disabled) → the read runs as before (no hard deny —
    the console must keep working before identity rolls out)."""
    svc = Mock()
    svc.get_session_trail = Mock(return_value={"ok": True})
    disabled = TenantContext.disabled()
    with patch("app.api.deps.resolve_tenant_from_jwt", return_value=disabled), \
         patch("app.api.routes._decisions_service", return_value=svc):
        out = await R.get_session_trail("s1", "r1", _Req())
    assert out == {"ok": True}


def test_trail_signals_carry_no_require_role():
    """Invariant 6: these are data-plane reads — they must NOT carry a require_role
    gate (their isolation is the JWT-tenant-bind, not RBAC)."""
    import inspect
    for handler in (R.get_session_trail, R.get_session_signals):
        params = inspect.signature(handler).parameters
        assert "ctx" not in params, f"{handler.__name__} must not carry an operator ctx gate"


# --------------------------------------------------------------------------- #
# M5.3 — operator-dependency contextvar reset (non-vacuous: single shared context)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_operator_dependency_resets_contextvar():
    """Drive resolve_operator_tenant twice within ONE asyncio Task (a single async
    test shares one context): a successful resolve binds tenant-A, then a RAISING
    resolve on the SAME context must leave the DEFAULT sentinel, not tenant-A
    (fail-secure). A two-request TestClient test would be vacuously green (Starlette
    copies context per request) and MUST NOT be used — this asserts the raising-path
    `finally` reset on a shared context."""
    import app.api.deps as deps

    m = Mock()
    m.tenant_id = "t_a"
    m.role = "admin"
    m.is_primary = True

    # 1) success → binds tenant-A on this Task's context
    deps._alb_claims_override = lambda req: {"sub": "op_a", "email": "a@x"}
    try:
        with patch("app.api.deps.get_member_store") as gms:
            gms.return_value.by_operator.return_value = [m]
            ctx = await deps.resolve_operator_tenant(_Req())
        assert ctx.tenant_id == "t_a"
        assert tenancy.current_tenant() == "t_a"

        # 2) a raising resolve on the SAME context (no membership → 403)
        deps._alb_claims_override = lambda req: {"sub": "op_none", "email": "n@x"}
        with patch("app.api.deps.get_member_store") as gms:
            gms.return_value.by_operator.return_value = []
            with pytest.raises(HTTPException):
                await deps.resolve_operator_tenant(_Req())
        # the finally reset forced the default sentinel — NOT the stale tenant-A
        assert tenancy.current_tenant() == tenancy.DEFAULT_TENANT
    finally:
        deps._alb_claims_override = None
        tenancy.set_current_tenant(tenancy.DEFAULT_TENANT)
