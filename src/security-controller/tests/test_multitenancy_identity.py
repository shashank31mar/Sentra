"""Runtime tenant identity — credential store, hot-path cache & JWT verify
dependency (LLD-26 §3 / WS-A A1, A2, A3, A3.1). Covers the §8 error model.
"""
from __future__ import annotations

import asyncio

import boto3
import pytest
from moto import mock_aws

from app.config import settings
from app.utils import tenancy
from tests.mt_helpers import run, create_mt_tables, gen_keypair, sign_agent_jwt


class FakeRequest:
    """Minimal stand-in for starlette Request — deps only read `.headers`."""

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
        # Force every singleton to rebuild against the moto-backed resource.
        import app.utils.clients as clients
        import app.services.credentials_service as cs
        import app.services.tenant_service as ts
        import app.api.deps as deps
        clients._registry = None
        cs._cache = None
        cs._store = None
        ts._tenant_store = None
        ts._member_store = None
        deps._mode_cache.clear()  # process-global identity_mode cache (#4)
        yield ddb


# --------------------------------------------------------------------------- #
# ES256-only key validation (A1)
# --------------------------------------------------------------------------- #
def test_register_rejects_non_es256(mt_env):
    from app.services.credentials_service import CredentialValidationError, get_credential_store

    store = get_credential_store()
    _, public_pem = gen_keypair()
    with pytest.raises(CredentialValidationError):
        store.register("t_a", "t_a-aws-x-deadbeef", public_pem, alg="RS256")
    with pytest.raises(CredentialValidationError):
        store.register("t_a", "t_a-aws-x-deadbeef", "not-a-key", alg="ES256")


def test_register_and_kid_lookup(mt_env):
    from app.services.credentials_service import get_credential_store

    store = get_credential_store()
    _, public_pem = gen_keypair()
    kid = store.register("t_a", "t_a-aws-x-deadbeef", public_pem)
    rec = store.get_by_kid(kid)
    assert rec is not None
    assert rec.tenant_id == "t_a"
    assert rec.agent_id == "t_a-aws-x-deadbeef"
    assert rec.status == "active" and rec.is_usable
    # list never exposes private material; only this agent's keys.
    keys = store.list_for_agent("t_a", "t_a-aws-x-deadbeef")
    assert {k.kid for k in keys} == {kid}


# --------------------------------------------------------------------------- #
# Public-key cache (A3.1)
# --------------------------------------------------------------------------- #
def test_cache_hit_and_negative_miss(mt_env):
    from app.services.credentials_service import CredentialCache, get_credential_store

    store = get_credential_store()
    _, public_pem = gen_keypair()
    kid = store.register("t_a", "t_a-aws-x-deadbeef", public_pem)

    async def scenario():
        cache = CredentialCache(store=store, ttl_seconds=60, negative_ttl_seconds=60)
        first = await cache.get(kid)
        assert first is not None and first.tenant_id == "t_a"
        # unknown kid → negative cache (None), and a second call stays cached.
        assert await cache.get("no-such-kid") is None
        assert await cache.get("no-such-kid") is None
    run(scenario())


def test_cache_revoked_since_invalidates(mt_env):
    from app.services.credentials_service import CredentialCache, get_credential_store

    store = get_credential_store()
    _, public_pem = gen_keypair()
    kid = store.register("t_a", "t_a-aws-x-deadbeef", public_pem)

    async def scenario():
        # refresh interval 0 → the epoch is re-read on every get.
        cache = CredentialCache(store=store, ttl_seconds=600, refresh_interval_seconds=0)
        assert (await cache.get(kid)) is not None
        # Revoke + bump the shared epoch; the next get must see a stale entry and
        # re-read the (now revoked) credential.
        store.set_status("t_a", "t_a-aws-x-deadbeef", kid, "revoked")
        store.bump_revocation_epoch()
        rec = await cache.get(kid)
        assert rec is not None and rec.status == "revoked"
    run(scenario())


# --------------------------------------------------------------------------- #
# resolve_tenant_from_jwt — §8 error model
# --------------------------------------------------------------------------- #
def _seed(store, tenant_store, tenant_id, agent_id, identity_mode):
    _, public_pem = gen_keypair()
    priv, public_pem2 = gen_keypair()
    kid = store.register(tenant_id, agent_id, public_pem2)
    tenant_store.create(display_name="X", tenant_id=tenant_id, identity_mode=identity_mode)
    return priv, kid


def test_disabled_when_ceiling_off(mt_env, monkeypatch):
    from app.api.deps import resolve_tenant_from_jwt

    monkeypatch.setattr(settings, "tenant_identity_mode", "off")
    monkeypatch.setattr(settings, "require_dataplane_credential", False)
    ctx = run(resolve_tenant_from_jwt(FakeRequest({"Authorization": "Bearer whatever"})))
    assert ctx.state == "disabled"  # byte-identical-to-pre-26 path


def test_latch_forces_verify_even_at_ceiling_off(mt_env, monkeypatch):
    """WS-M M5.1: with `require_dataplane_credential` ON, the fleet `off` kill-switch no
    longer short-circuits to `disabled` — the resolver STILL attempts verification so
    the route can distinguish a valid token from a missing/invalid one independent of
    `identity_mode`. A missing token at fleet `off` + latch ON → `unverified` (which the
    route denies), NOT `disabled` (which the route would allow). FAILS against the
    pre-fix resolver, which returned `disabled` unconditionally at ceiling `off`."""
    from app.api.deps import resolve_tenant_from_jwt

    monkeypatch.setattr(settings, "tenant_identity_mode", "off")
    monkeypatch.setattr(settings, "require_dataplane_credential", True)
    # No token, fleet off, latch on → must NOT be `disabled` (would allow tokenless).
    ctx = run(resolve_tenant_from_jwt(FakeRequest({})))
    assert ctx.state == "unverified"
    assert ctx.credential_present is False


def test_unverified_no_token(mt_env, monkeypatch):
    from app.api.deps import resolve_tenant_from_jwt

    monkeypatch.setattr(settings, "tenant_identity_mode", "enforce")
    ctx = run(resolve_tenant_from_jwt(FakeRequest({})))
    assert ctx.state == "unverified" and ctx.reason == "IDENTITY_UNVERIFIED"
    assert ctx.audit_tenant() == tenancy.UNVERIFIED_TENANT


def test_verified_shadow_not_routed(mt_env, monkeypatch):
    from app.api.deps import resolve_tenant_from_jwt
    from app.services.credentials_service import get_credential_store
    from app.services.tenant_service import get_tenant_store

    monkeypatch.setattr(settings, "tenant_identity_mode", "shadow")
    agent = "t_a-aws-x-deadbeef"
    priv, kid = _seed(get_credential_store(), get_tenant_store(), "t_a", agent, "shadow")
    token = sign_agent_jwt(priv, kid, "t_a", agent)
    ctx = run(resolve_tenant_from_jwt(FakeRequest({"Authorization": f"Bearer {token}"})))
    assert ctx.is_verified and ctx.tenant_id == "t_a" and ctx.agent_id == agent
    assert ctx.should_route is False  # shadow observes, never routes


def test_verified_enforce_routes(mt_env, monkeypatch):
    from app.api.deps import resolve_tenant_from_jwt
    from app.services.credentials_service import get_credential_store
    from app.services.tenant_service import get_tenant_store

    monkeypatch.setattr(settings, "tenant_identity_mode", "enforce")
    agent = "t_a-aws-x-deadbeef"
    priv, kid = _seed(get_credential_store(), get_tenant_store(), "t_a", agent, "enforce")
    token = sign_agent_jwt(priv, kid, "t_a", agent)
    ctx = run(resolve_tenant_from_jwt(FakeRequest({"Authorization": f"Bearer {token}"})))
    assert ctx.is_verified and ctx.should_route is True


def test_effective_mode_clamps_to_ceiling(mt_env, monkeypatch):
    """Tenant says enforce but the fleet ceiling is shadow → effective shadow."""
    from app.api.deps import resolve_tenant_from_jwt
    from app.services.credentials_service import get_credential_store
    from app.services.tenant_service import get_tenant_store

    monkeypatch.setattr(settings, "tenant_identity_mode", "shadow")
    agent = "t_a-aws-x-deadbeef"
    priv, kid = _seed(get_credential_store(), get_tenant_store(), "t_a", agent, "enforce")
    token = sign_agent_jwt(priv, kid, "t_a", agent)
    ctx = run(resolve_tenant_from_jwt(FakeRequest({"Authorization": f"Bearer {token}"})))
    assert ctx.effective_mode == "shadow" and ctx.should_route is False


def test_tampered_tid_mismatch(mt_env, monkeypatch):
    """Token claims tid=t_b but is signed by t_a's key → IDENTITY_TAMPERED."""
    from app.api.deps import resolve_tenant_from_jwt
    from app.services.credentials_service import get_credential_store
    from app.services.tenant_service import get_tenant_store

    monkeypatch.setattr(settings, "tenant_identity_mode", "enforce")
    agent = "t_a-aws-x-deadbeef"
    priv, kid = _seed(get_credential_store(), get_tenant_store(), "t_a", agent, "enforce")
    token = sign_agent_jwt(priv, kid, "t_b", "t_b-aws-x-deadbeef")  # lies about tid
    ctx = run(resolve_tenant_from_jwt(FakeRequest({"Authorization": f"Bearer {token}"})))
    assert ctx.state == "tampered" and ctx.reason == "IDENTITY_TAMPERED"
    assert ctx.claimed_tenant_id == "t_a"


def test_mismatch_sub_not_prefixed(mt_env, monkeypatch):
    """sub does not start with tid+'-' → IDENTITY_MISMATCH (delimiter-safe)."""
    from app.api.deps import resolve_tenant_from_jwt
    from app.services.credentials_service import get_credential_store
    from app.services.tenant_service import get_tenant_store

    monkeypatch.setattr(settings, "tenant_identity_mode", "enforce")
    # Register the key under tid t_01 but with a sub that belongs to t_01hxyz.
    priv, public_pem = gen_keypair()
    store = get_credential_store()
    kid = store.register("t_01", "t_01hxyz-aws-x-deadbeef", public_pem)
    get_tenant_store().create(display_name="X", tenant_id="t_01", identity_mode="enforce")
    token = sign_agent_jwt(priv, kid, "t_01", "t_01hxyz-aws-x-deadbeef")
    ctx = run(resolve_tenant_from_jwt(FakeRequest({"Authorization": f"Bearer {token}"})))
    # tid t_01 is NOT a delimited prefix of sub t_01hxyz-… → mismatch, not a leak.
    assert ctx.state == "mismatch" and ctx.reason == "IDENTITY_MISMATCH"


def test_expired_token_unverified(mt_env, monkeypatch):
    from app.api.deps import resolve_tenant_from_jwt
    from app.services.credentials_service import get_credential_store
    from app.services.tenant_service import get_tenant_store

    monkeypatch.setattr(settings, "tenant_identity_mode", "enforce")
    agent = "t_a-aws-x-deadbeef"
    priv, kid = _seed(get_credential_store(), get_tenant_store(), "t_a", agent, "enforce")
    token = sign_agent_jwt(priv, kid, "t_a", agent, exp_offset=-3600, iat_offset=-7200)
    ctx = run(resolve_tenant_from_jwt(FakeRequest({"Authorization": f"Bearer {token}"})))
    assert ctx.state == "unverified" and ctx.claimed_tenant_id == "t_a"


def test_identity_mode_fails_closed_on_registry_error(mt_env, monkeypatch):
    """Kiro follow-up: a sentra-tenants read error must NOT drop a verified agent
    to the legacy/`default` path. The tenant is proven from the credential, so on
    error we honor the ceiling → a verified agent still routes onto its OWN tenant."""
    import app.api.deps as deps
    from app.services.credentials_service import get_credential_store
    from app.services.tenant_service import get_tenant_store

    monkeypatch.setattr(settings, "tenant_identity_mode", "enforce")
    agent = "t_a-aws-x-deadbeef"
    priv, kid = _seed(get_credential_store(), get_tenant_store(), "t_a", agent, "enforce")
    token = sign_agent_jwt(priv, kid, "t_a", agent)

    def boom(*_a, **_k):
        raise RuntimeError("ddb down")

    monkeypatch.setattr(get_tenant_store(), "get", boom)
    deps._mode_cache.clear()
    ctx = run(deps.resolve_tenant_from_jwt(FakeRequest({"Authorization": f"Bearer {token}"})))
    # Honors ceiling=enforce on the proven tenant — routes, never falls to default.
    assert ctx.is_verified and ctx.should_route is True
    # And the failed lookup was NOT cached (next request retries).
    assert "t_a" not in deps._mode_cache


def test_jwk_registered_key_verifies(mt_env, monkeypatch):
    """#6 — a key registered as a JWK (not PEM) must actually verify a token."""
    from app.api.deps import resolve_tenant_from_jwt
    from app.services.credentials_service import get_credential_store
    from app.services.tenant_service import get_tenant_store
    from tests.mt_helpers import public_pem_to_jwk

    monkeypatch.setattr(settings, "tenant_identity_mode", "shadow")
    priv, public_pem = gen_keypair()
    jwk = public_pem_to_jwk(public_pem)
    store = get_credential_store()
    agent = "t_jwk-aws-x-deadbeef"
    kid = store.register("t_jwk", agent, jwk)  # registered as JWK
    get_tenant_store().create(display_name="J", tenant_id="t_jwk", identity_mode="shadow")
    token = sign_agent_jwt(priv, kid, "t_jwk", agent)
    ctx = run(resolve_tenant_from_jwt(FakeRequest({"Authorization": f"Bearer {token}"})))
    assert ctx.is_verified and ctx.tenant_id == "t_jwk"


def test_revoked_key_unverified(mt_env, monkeypatch):
    from app.api.deps import resolve_tenant_from_jwt
    from app.services.credentials_service import get_credential_store
    from app.services.tenant_service import get_tenant_store

    monkeypatch.setattr(settings, "tenant_identity_mode", "enforce")
    agent = "t_a-aws-x-deadbeef"
    store = get_credential_store()
    priv, kid = _seed(store, get_tenant_store(), "t_a", agent, "enforce")
    store.set_status("t_a", agent, kid, "revoked")
    token = sign_agent_jwt(priv, kid, "t_a", agent)
    ctx = run(resolve_tenant_from_jwt(FakeRequest({"Authorization": f"Bearer {token}"})))
    assert ctx.state == "unverified"  # revoked key never verifies


# --------------------------------------------------------------------------- #
# WS-G G1.3 (FR-13.1) — operator tenant resolution uses MEMBERSHIP, never the
# email domain. This locks the `resolve_operator_tenant` authority so a future
# regression to domain-derivation is caught. The email domain and the membership
# tenant are DELIBERATELY DIFFERENT (`acme.io` vs `t_globex`) — if they matched, a
# domain-derivation bug would pass silently.
# --------------------------------------------------------------------------- #
def test_resolution_uses_membership_not_email_domain(mt_env, monkeypatch):
    from app.api import deps
    from app.api.deps import resolve_operator_tenant
    from app.services.tenant_service import get_member_store
    from app.utils import tenancy

    # OIDC claims: email domain = acme.io (a RED HERRING — never an authority).
    monkeypatch.setattr(
        deps, "verify_alb_oidc",
        lambda req: {"sub": "alice-sub", "email": "alice@acme.io"},
    )
    # Sole membership is in t_globex — deliberately NOT the email domain.
    get_member_store().add(
        operator_sub="alice-sub", tenant_id="t_globex", role="viewer", is_primary=True,
    )

    # Read the bound contextvar INSIDE the same coroutine — `run()` executes on a
    # Task that copies the context, so a set_current_tenant inside the dep is not
    # visible from the caller's context after the await returns.
    async def _resolve_and_read():
        c = await resolve_operator_tenant(FakeRequest({}))
        return c, tenancy.current_tenant()

    ctx, bound = run(_resolve_and_read())

    assert ctx.tenant_id == "t_globex", (
        "FR-13.1: operator tenant MUST derive from membership (t_globex), "
        f"NOT the email domain (acme.io) — got {ctx.tenant_id!r}"
    )
    assert ctx.tenant_id not in ("acme.io", "acme"), "FR-13.1: email domain must never be the tenant"
    assert bound == "t_globex", "bound tenant (deps.py:449) must be the membership tenant"
