"""WS-F Milestone F6.6 — honest error contract at the HTTP boundary (lld/35 §6f 1+2).

A total inability-to-evaluate the pipeline must surface as a real HTTP 5XX with a
CUSTOMER-SAFE body (no internal exception / stack / host / query) + a correlation id
— NOT a 200 wrapping a fabricated `{decision:DENY, violation_type:SYSTEM_ERROR}`.
A fake-200 hides the failure from every gateway/retry/monitor; the PEP's `fail_secure`
must decide from the STATUS CODE.

Drives the real app over a TestClient with `raise_server_exceptions=False` so the
registered `@app.exception_handler`s produce the response (instead of re-raising into
the test) — exactly what a real client/gateway sees.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.validation_service import PipelineError


def _payload(**overrides):
    base = dict(
        request_id="req-err-1",
        session_id="sess-err-1",
        agent_id="payment-agent",
        tool_name="process_refund",
        tool_params={"order_id": "ORD-1", "amount": 10.0},
        user_input="refund order ORD-1",
        timestamp="2026-07-05T00:00:00Z",
        operation_type="WRITE",
    )
    base.update(overrides)
    return base


@pytest.fixture
def client():
    # raise_server_exceptions=False => the exception handler's JSONResponse is
    # returned, mirroring what a real HTTP client sees.
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def crashing_service():
    """Replace the process-wide validation_service with one that raises a
    PipelineError (a total inability-to-evaluate)."""
    svc = Mock()
    svc.validate_tool_call = AsyncMock(
        side_effect=PipelineError("corr-abc123", "Internal validation error")
    )
    prev = getattr(app.state, "validation_service", None)
    app.state.validation_service = svc
    try:
        yield svc
    finally:
        app.state.validation_service = prev


@pytest.fixture
def raw_crashing_service():
    """A validation_service that raises a RAW exception carrying secret-looking
    internal detail — to prove the catch-all handler never leaks it."""
    svc = Mock()
    svc.validate_tool_call = AsyncMock(
        side_effect=RuntimeError("psql://user:SECRETPW@db-host-internal/orders failed")
    )
    prev = getattr(app.state, "validation_service", None)
    app.state.validation_service = svc
    try:
        yield svc
    finally:
        app.state.validation_service = prev


def test_pipeline_exception_returns_5xx_not_200_deny(client, crashing_service):
    """FAILING-THEN-PASSING: today's 200-body SYSTEM_ERROR DENY is GONE — a propagated
    pipeline exception surfaces as HTTP 5XX with a correlation id and NO 200 DENY."""
    resp = client.post("/v1/validate", json=_payload())
    assert resp.status_code == 500, "must be an honest 5XX, not a 200-body DENY"
    body = resp.json()
    # NOT a fabricated verdict body.
    assert body.get("decision") != "DENY"
    assert "violation_type" not in body
    # customer-safe + traceable
    assert body.get("correlation_id") == "corr-abc123"
    assert body.get("error") == "Internal validation error"


def test_exception_handler_sanitizes_body(client, raw_crashing_service):
    """F6.6 part 2: the main.py catch-all handler returns a customer-safe body for an
    unhandled exception — NO internal detail (exception text / host / query / secret)
    leaks across the API boundary; a correlation id is present."""
    resp = client.post("/v1/validate", json=_payload())
    assert resp.status_code == 500
    body = resp.json()
    raw = resp.text
    # None of the internal detail leaked.
    assert "SECRETPW" not in raw
    assert "db-host-internal" not in raw
    assert "psql://" not in raw
    assert "RuntimeError" not in raw
    # customer-safe generic message + a correlation id to quote to support.
    assert body.get("error") == "Internal server error"
    assert body.get("correlation_id")
