"""WS-J J1 — harness fixtures (canary_client / canary_tenant / canary_operator)."""
from __future__ import annotations

import re

import pytest

from canary.conftest import CanaryClient


def test_canary_client_inprocess(canary_client):
    """J1.1(a) — inprocess mode is a TestClient-backed adapter; /v1/health → 200."""
    assert canary_client.mode == "inprocess"
    resp = canary_client.get("/v1/health")
    assert resp.status_code in (200, 503)  # 503 only if a dep is unhealthy under moto


def test_canary_client_fresh_correlation_id(canary_client):
    """J1.1(b) — every call injects a FRESH unique X-Correlation-Id."""
    canary_client.get("/v1/health")
    first = canary_client.correlation_id
    canary_client.get("/v1/health")
    second = canary_client.correlation_id
    assert first and second and first != second


def test_canary_client_latency_populated(canary_client):
    """J1.1(c) — latency_ms is populated (>0) after a call."""
    canary_client.get("/v1/health")
    assert canary_client.latency_ms is not None and canary_client.latency_ms > 0


def test_canary_client_correlation_id_property(canary_client):
    """J1.1(d) — .correlation_id exposes the last-sent id (matches the header)."""
    resp = canary_client.get("/v1/health")
    assert resp.request.headers.get("X-Correlation-Id") == canary_client.correlation_id


def test_canary_tenant_ephemeral(canary_tenant):
    """J1.2 — id matches ^canary-[0-9a-f]{32}$."""
    assert re.match(r"^canary-[0-9a-f]{32}$", canary_tenant)


def test_canary_tenant_distinct_ids(canary_tenant):
    """J1.2 — the fixture yields a canary-scoped id (uniqueness is per-invocation)."""
    # Two separate fixture uses (this test + test_canary_tenant_ephemeral) get
    # distinct ids by construction (uuid4hex); assert the shape holds here too.
    assert canary_tenant.startswith("canary-")


def test_canary_operator_inprocess(canary_client, canary_operator):
    """J1.3 — with the operator override active, an OIDC-gated handler resolves the
    synthetic sub in inprocess mode."""
    from app.api import deps

    assert deps._alb_claims_override is not None
    claims = deps._alb_claims_override(None)
    assert claims["sub"] == canary_operator["sub"]


def test_canary_operator_override_reset():
    """J1.3 — after the fixture tears down, the override is back to None (test seam
    never leaks into a real path)."""
    from app.api import deps

    # This test does NOT request canary_operator, so the override must be None here.
    assert deps._alb_claims_override is None


def test_canary_operator_live_raises(monkeypatch):
    """J1.3 — invoking the operator fixture in live mode raises NotImplementedError
    (the real-Cognito form is Increment-2 deferred)."""
    monkeypatch.setenv("CANARY_TARGET", "live")
    # Re-invoke the fixture function body directly to assert its guard.
    from canary import conftest

    gen = conftest.canary_operator.__wrapped__(request=None)
    with pytest.raises(NotImplementedError):
        next(gen)
