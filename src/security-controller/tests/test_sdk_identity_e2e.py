"""End-to-end identity proof: the REAL aegion-guard SDK signer → the controller's
verify (WS-A). This is the wire-compat gate — it imports the actual SDK
``JwtSigner`` (not the in-repo test helper) and runs its token through
``resolve_tenant_from_jwt`` against moto-backed credential + tenant tables.

If the SDK's claim shape, algorithm, ``kid`` header, or tenant-prefix rule ever
drifts from the controller, this fails. It is the only test that crosses the
SDK↔controller package boundary.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from app.config import settings
from app.utils import tenancy
from tests.mt_helpers import create_mt_tables

# Make the real SDK importable without installing it (mirrors its own conftest).
_SDK_SRC = (
    Path(__file__).resolve().parents[3]
    / "demo-agents" / "sdk" / "aegion-guard-python" / "src"
)
if str(_SDK_SRC) not in sys.path:
    sys.path.insert(0, str(_SDK_SRC))

pytest.importorskip("aegion_guard.identity", reason="aegion-guard SDK not on path")
from aegion_guard.identity import AgentIdentity, JwtSigner, generate_keypair  # noqa: E402


class FakeRequest:
    def __init__(self, headers=None):
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}


@pytest.fixture
def mt_env(monkeypatch):
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SECURITY_TOKEN", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(k, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", settings.aws_region)
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name=settings.aws_region)
        create_mt_tables(ddb)
        import app.api.deps as deps
        import app.services.credentials_service as cs
        import app.services.tenant_service as ts
        import app.utils.clients as clients

        clients._registry = None
        cs._cache = None
        cs._store = None
        ts._tenant_store = None
        ts._member_store = None
        deps._mode_cache.clear()
        yield ddb


def _run(coro):
    from tests.mt_helpers import run

    return run(coro)


def _provision(tenant_id, agent_id, identity_mode):
    """Generate a keypair in the SDK, register the public key, create the tenant.
    Returns the SDK AgentIdentity ready to sign."""
    from app.services.credentials_service import get_credential_store
    from app.services.tenant_service import get_tenant_store

    private_pem, public_pem = generate_keypair()
    kid = get_credential_store().register(tenant_id, agent_id, public_pem)
    get_tenant_store().create(display_name="E2E", tenant_id=tenant_id, identity_mode=identity_mode)
    ident = AgentIdentity(agent_id=agent_id, tenant_id=tenant_id, kid=kid, private_key=private_pem)
    return ident, kid


def test_sdk_signed_token_routes_under_enforce(mt_env, monkeypatch):
    from app.api.deps import resolve_tenant_from_jwt

    monkeypatch.setattr(settings, "tenant_identity_mode", "enforce")
    agent = "t_acme-aws-payments-ab12cd34"
    ident, _ = _provision("t_acme", agent, "enforce")

    token = JwtSigner(ident).token()  # the real SDK mints exactly what ships
    ctx = _run(resolve_tenant_from_jwt(FakeRequest({"Authorization": f"Bearer {token}"})))

    assert ctx.is_verified
    assert ctx.tenant_id == "t_acme"
    assert ctx.agent_id == agent
    assert ctx.should_route is True


def test_sdk_signed_token_shadow_observes_not_routes(mt_env, monkeypatch):
    from app.api.deps import resolve_tenant_from_jwt

    monkeypatch.setattr(settings, "tenant_identity_mode", "shadow")
    agent = "t_acme-aws-payments-ab12cd34"
    ident, _ = _provision("t_acme", agent, "shadow")
    token = JwtSigner(ident).token()
    ctx = _run(resolve_tenant_from_jwt(FakeRequest({"Authorization": f"Bearer {token}"})))
    assert ctx.is_verified and ctx.should_route is False


def test_sdk_token_with_foreign_key_is_tampered(mt_env, monkeypatch):
    """SDK signs a t_b token, but the kid resolves to a key registered under t_a
    → IDENTITY_TAMPERED (key reuse across tenants)."""
    from app.api.deps import resolve_tenant_from_jwt
    from app.services.credentials_service import get_credential_store
    from app.services.tenant_service import get_tenant_store

    monkeypatch.setattr(settings, "tenant_identity_mode", "enforce")
    private_pem, public_pem = generate_keypair()
    kid = get_credential_store().register("t_a", "t_a-aws-x-deadbeef", public_pem)
    get_tenant_store().create(display_name="A", tenant_id="t_a", identity_mode="enforce")

    # Same private key + kid, but the SDK identity claims tenant t_b.
    forged = AgentIdentity(agent_id="t_b-aws-x-deadbeef", tenant_id="t_b",
                           kid=kid, private_key=private_pem)
    token = JwtSigner(forged).token()
    ctx = _run(resolve_tenant_from_jwt(FakeRequest({"Authorization": f"Bearer {token}"})))
    assert ctx.state == "tampered" and ctx.reason == "IDENTITY_TAMPERED"
    assert ctx.claimed_tenant_id == "t_a"


def test_sdk_expired_token_is_unverified(mt_env, monkeypatch):
    from app.api.deps import resolve_tenant_from_jwt

    monkeypatch.setattr(settings, "tenant_identity_mode", "enforce")
    agent = "t_acme-aws-payments-ab12cd34"
    ident, _ = _provision("t_acme", agent, "enforce")

    # Mint with a clock two hours in the past → exp already elapsed.
    past = JwtSigner(ident, time_fn=lambda: time.time() - 7200).token()
    ctx = _run(resolve_tenant_from_jwt(FakeRequest({"Authorization": f"Bearer {past}"})))
    assert ctx.state == "unverified" and ctx.claimed_tenant_id == "t_acme"
