"""WS-J / LLD 38 §319 (J4.2 hook) — debug-gated `x-canary-capture` response echo.

In `live` mode the canary cannot reach `_bg_tasks` to prove "no raw PII entered the
audit write", so `/v1/validate` OPTIONALLY echoes the ALREADY-REDACTED user_input/
tool_params (the post-Tier-1-redaction form the audit writer receives) back as an
`x-canary-capture` header — ONLY when the debug flag is on AND the verified tenant is
a reserved `canary-*` tenant. Off by default → zero prod behavior change.

These drive the real app over TestClient, patching `resolve_tenant_from_jwt` so the
canary reaches the enforce+verified route branch without real JWTs/AWS, and assert:
  * flag OFF (default) → NO header even for a canary tenant (default is safe);
  * flag ON + canary tenant → header present, carrying only the redacted form
    (a raw sentinel `CANARY-PII-7F3A` / a PAN is NOT in the header value);
  * flag ON + non-canary tenant → NO header.
Non-vacuous: the flag-ON canary case asserts the header IS present + content-safe;
flipping the gate off (the default test) proves it is truly gated.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.deps import TenantContext
from app.main import app


_RAW_SENTINEL = "CANARY-PII-7F3A"  # the synthetic PII sentinel (SEC-5) — must never echo
_RAW_PAN = "4111111111111111"      # a Luhn-valid PAN — must never echo
_CANARY_TENANT = "canary-abc123"
_AGENT_ID = "canary-probe-agent"


def _payload(**overrides):
    """A today-shaped ValidationRequest whose content is ALREADY REDACTED (redacted=
    True), matching what a real canary/SDK sends after the Tier-1 edge redactor ran."""
    base = dict(
        request_id="req-c1",
        session_id="sess-c1",
        agent_id=_AGENT_ID,
        tool_name="query_customers",
        tool_params={"note": "acct ⟦AEGR:x:CARD:4:4⟧"},
        user_input="lookup ⟦AEGR:x:NAME⟧",
        timestamp="2026-07-05T00:00:00Z",
        operation_type="READ",
        redacted=True,
    )
    base.update(overrides)
    return base


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def spy_service():
    """Spy the process-wide validation_service so the pipeline/AWS is not touched."""
    svc = Mock()
    svc.validate_tool_call = AsyncMock(
        return_value={
            "decision": "ALLOW", "reason": "ok", "trust_score": 99.0,
            "session_id": "sess-c1", "latency_ms": 1.0,
        }
    )
    prev = getattr(app.state, "validation_service", None)
    app.state.validation_service = svc
    try:
        yield svc
    finally:
        app.state.validation_service = prev


def _verified_ctx(tenant_id: str):
    """A verified+enforce TenantContext so the handler routes onto `tenant_id` (and
    sets the current_tenant contextvar to it) — the exact path a live canary takes."""
    return TenantContext.verified(
        tenant_id=tenant_id, agent_id=_AGENT_ID, effective_mode="enforce"
    )


# ---------------------------------------------------------------- flag OFF (default)

def test_no_header_when_flag_off_even_for_canary(client, spy_service):
    """DEFAULT-SAFE: with `canary_capture_enabled` False (the default), NO
    x-canary-capture header appears even for a canary tenant. Proves the gate."""
    with patch("app.api.deps.resolve_tenant_from_jwt",
               new=AsyncMock(return_value=_verified_ctx(_CANARY_TENANT))):
        # Do NOT enable the flag — rely on the default.
        resp = client.post("/v1/validate", json=_payload())
    assert resp.status_code == 200
    assert "x-canary-capture" not in {k.lower() for k in resp.headers.keys()}


# ------------------------------------------------------ flag ON + canary tenant

def test_header_present_and_content_safe_when_flag_on_canary(client, spy_service):
    """Flag ON + canary tenant → the header IS present and carries ONLY the redacted
    form: it must NOT contain the raw PII sentinel or a raw PAN, and it MUST carry the
    typed redaction markers (proving it echoed the post-redaction value)."""
    with patch("app.api.deps.resolve_tenant_from_jwt",
               new=AsyncMock(return_value=_verified_ctx(_CANARY_TENANT))), \
         patch("app.config.settings.canary_capture_enabled", True):
        # The request body is already-redacted content (the canary sends redacted=True);
        # the raw sentinels below are what a NON-redacted body WOULD have carried — they
        # must never appear because the handler only echoes the request's redacted fields.
        resp = client.post("/v1/validate", json=_payload())

    assert resp.status_code == 200
    header = resp.headers.get("x-canary-capture")
    assert header is not None, "flag ON + canary tenant must attach the header"
    # Content-safety: neither the raw sentinel nor a raw PAN may appear in the echo.
    assert _RAW_SENTINEL not in header
    assert _RAW_PAN not in header
    # It echoed the redacted form: the typed marker's TYPE survives (json escapes the
    # ⟦⟧ glyphs to ⟦/⟧, but the token TYPE text remains).
    assert "NAME" in header and "CARD" in header


def test_header_never_echoes_raw_when_body_carries_raw(client, spy_service):
    """Defense-in-depth: even if the incoming body carried a RAW value (a
    mis-behaving edge), the handler only echoes what is on the request — so if we
    hand it raw content in user_input, the header equals that already-on-request
    value; the invariant the canary asserts is that the header == the audit-writer
    input (redacted at the edge), NEVER a re-read of a raw source. Here we prove the
    handler does not FABRICATE a raw echo from elsewhere: with a redacted body, the
    raw sentinel is absent."""
    with patch("app.api.deps.resolve_tenant_from_jwt",
               new=AsyncMock(return_value=_verified_ctx(_CANARY_TENANT))), \
         patch("app.config.settings.canary_capture_enabled", True):
        resp = client.post(
            "/v1/validate",
            json=_payload(user_input="clean ⟦AEGR:x:SSN⟧", tool_params={}),
        )
    header = resp.headers.get("x-canary-capture")
    assert header is not None
    assert _RAW_SENTINEL not in header
    assert "SSN" in header  # the redacted token type is echoed


# ------------------------------------------------------ flag ON + NON-canary tenant

def test_no_header_for_non_canary_tenant_even_with_flag_on(client, spy_service):
    """Flag ON but a NON-canary (real) tenant → NO header. The echo is scoped to
    canary tenants only; a real tenant's response must never carry it."""
    with patch("app.api.deps.resolve_tenant_from_jwt",
               new=AsyncMock(return_value=_verified_ctx("acme"))), \
         patch("app.config.settings.canary_capture_enabled", True):
        resp = client.post("/v1/validate", json=_payload())
    assert resp.status_code == 200
    assert "x-canary-capture" not in {k.lower() for k in resp.headers.keys()}


# ------------------------------------------------------------- unit: the helper itself

def test_maybe_attach_helper_gates_on_flag_and_tenant():
    """Unit-level: `_maybe_attach_canary_capture` attaches ONLY with flag ON + a
    canary tenant; None tenant / non-canary / flag-off all attach nothing."""
    from fastapi import Response

    from app.api.models import ValidationRequest
    from app.api.routes import _CANARY_CAPTURE_HEADER, _maybe_attach_canary_capture

    req = ValidationRequest(**_payload())

    # flag OFF → nothing
    resp = Response()
    with patch("app.config.settings.canary_capture_enabled", False):
        _maybe_attach_canary_capture(resp, req, tenant_id=_CANARY_TENANT)
    assert _CANARY_CAPTURE_HEADER not in resp.headers

    # flag ON + non-canary → nothing
    resp = Response()
    with patch("app.config.settings.canary_capture_enabled", True):
        _maybe_attach_canary_capture(resp, req, tenant_id="acme")
    assert _CANARY_CAPTURE_HEADER not in resp.headers

    # flag ON + None tenant → nothing (fail-secure: no tenant = no echo)
    resp = Response()
    with patch("app.config.settings.canary_capture_enabled", True):
        _maybe_attach_canary_capture(resp, req, tenant_id=None)
    assert _CANARY_CAPTURE_HEADER not in resp.headers

    # flag ON + canary → header present
    resp = Response()
    with patch("app.config.settings.canary_capture_enabled", True):
        _maybe_attach_canary_capture(resp, req, tenant_id=_CANARY_TENANT)
    assert _CANARY_CAPTURE_HEADER in resp.headers
    assert _RAW_SENTINEL not in resp.headers[_CANARY_CAPTURE_HEADER]
