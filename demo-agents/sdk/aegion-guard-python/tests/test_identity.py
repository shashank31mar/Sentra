"""Tests for data-plane identity (WS-A) — keypair gen, JWT minting, refresh, and
that the Bearer token reaches the transport and is wire-compatible with the
controller's verify (app/api/deps.resolve_tenant_from_jwt)."""
from __future__ import annotations

import sys
import time

import jwt  # the `identity`/`dev` extra provides PyJWT[crypto]
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import (
    load_pem_private_key,
    load_pem_public_key,
)

from aegion_guard import AegionGuard, AgentIdentity, JwtSigner, generate_keypair
from aegion_guard.exceptions import ConfigError, IdentityError
from aegion_guard.identity import AUD, ISS

TENANT = "t_acme"
AGENT = "t_acme-aws-payments-ab12cd34"  # canonical {tenant}-{cloud}-{slug}-{hash}


def _new_identity(**overrides) -> AgentIdentity:
    private_pem, public_pem = generate_keypair()
    kwargs = dict(agent_id=AGENT, tenant_id=TENANT, kid="kid-1", private_key=private_pem)
    kwargs.update(overrides)
    ident = AgentIdentity(**kwargs)
    return ident, public_pem  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# keypair generation
# --------------------------------------------------------------------------- #
def test_generate_keypair_is_p256():
    private_pem, public_pem = generate_keypair()
    priv = load_pem_private_key(private_pem.encode(), password=None)
    pub = load_pem_public_key(public_pem.encode())
    assert isinstance(priv, ec.EllipticCurvePrivateKey)
    assert isinstance(priv.curve, ec.SECP256R1)
    assert isinstance(pub, ec.EllipticCurvePublicKey)


# --------------------------------------------------------------------------- #
# minting + wire-compat with the controller's verify
# --------------------------------------------------------------------------- #
def test_token_verifies_exactly_as_controller_does():
    ident, public_pem = _new_identity()
    token = JwtSigner(ident).token()

    # The controller verifies with these exact constraints (deps.py).
    claims = jwt.decode(
        token, public_pem, algorithms=["ES256"], audience=AUD, issuer=ISS, leeway=60
    )
    assert claims["sub"] == AGENT
    assert claims["tid"] == TENANT
    assert claims["sub"].startswith(claims["tid"] + "-")  # the isolation check
    assert claims["exp"] > claims["iat"]

    header = jwt.get_unverified_header(token)
    assert header["alg"] == "ES256"
    assert header["kid"] == "kid-1"


def test_wrong_public_key_fails_verification():
    ident, _ = _new_identity()
    token = JwtSigner(ident).token()
    _, other_public = generate_keypair()
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(token, other_public, algorithms=["ES256"], audience=AUD, issuer=ISS)


# --------------------------------------------------------------------------- #
# caching + silent refresh (injected clock)
# --------------------------------------------------------------------------- #
def test_token_cached_within_margin():
    ident, _ = _new_identity(token_ttl_s=600, refresh_margin_s=60)
    clock = {"t": 1_000_000.0}
    signer = JwtSigner(ident, time_fn=lambda: clock["t"])
    a = signer.token()
    b = signer.token()  # same clock → cached, identical token
    assert a == b


def test_token_refreshes_before_expiry():
    ident, public_pem = _new_identity(token_ttl_s=600, refresh_margin_s=60)
    clock = {"t": 1_000_000.0}
    signer = JwtSigner(ident, time_fn=lambda: clock["t"])
    first = signer.token()
    # Advance past (ttl - margin) = 540s → must re-mint a fresh token.
    clock["t"] += 541
    second = signer.token()
    assert first != second
    # Both decode against the same key; the second has a later iat.
    c1 = jwt.decode(first, public_pem, algorithms=["ES256"], audience=AUD, issuer=ISS,
                    options={"verify_exp": False})
    c2 = jwt.decode(second, public_pem, algorithms=["ES256"], audience=AUD, issuer=ISS,
                    options={"verify_exp": False})
    assert c2["iat"] > c1["iat"]


# --------------------------------------------------------------------------- #
# fail-fast validation
# --------------------------------------------------------------------------- #
def test_agent_id_must_be_tenant_prefixed():
    private_pem, _ = generate_keypair()
    with pytest.raises(ConfigError):
        AgentIdentity(agent_id="other-aws-x-1234", tenant_id=TENANT, kid="k", private_key=private_pem)


def test_bare_prefix_without_delimiter_rejected():
    # `t_acme2-...` must NOT pass as tenant `t_acme` (delimiter safety).
    private_pem, _ = generate_keypair()
    with pytest.raises(ConfigError):
        AgentIdentity(agent_id="t_acme2-aws-x-1234", tenant_id=TENANT, kid="k", private_key=private_pem)


def test_ttl_capped_at_15_minutes():
    private_pem, _ = generate_keypair()
    with pytest.raises(ConfigError):
        AgentIdentity(agent_id=AGENT, tenant_id=TENANT, kid="k", private_key=private_pem,
                      token_ttl_s=1000)


def test_non_p256_key_rejected():
    # A P-384 key is a valid EC key but the wrong curve for ES256.
    key = ec.generate_private_key(ec.SECP384R1())
    from cryptography.hazmat.primitives import serialization

    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    with pytest.raises(ConfigError):
        AgentIdentity(agent_id=AGENT, tenant_id=TENANT, kid="k", private_key=pem)


def test_missing_extra_raises_identity_error(monkeypatch):
    import aegion_guard.identity as idm

    monkeypatch.setitem(sys.modules, "jwt", None)  # makes `import jwt` raise
    with pytest.raises(IdentityError):
        idm._require_jwt()


# --------------------------------------------------------------------------- #
# config all-or-none + guard wiring
# --------------------------------------------------------------------------- #
def test_partial_identity_config_is_error(monkeypatch):
    monkeypatch.setenv("SENTRA_TENANT_ID", TENANT)  # tenant only, no kid/key
    monkeypatch.delenv("SENTRA_AGENT_KID", raising=False)
    monkeypatch.delenv("SENTRA_AGENT_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("SENTRA_AGENT_PRIVATE_KEY_FILE", raising=False)
    with pytest.raises(ConfigError):
        AegionGuard(AGENT)


def test_guard_without_identity_is_unsigned():
    g = AegionGuard(AGENT)  # no identity env → core path, no signing
    assert g.identity_enabled is False


def test_guard_with_identity_signs(monkeypatch, tmp_path):
    private_pem, _ = generate_keypair()
    key_file = tmp_path / "agent.pem"
    key_file.write_text(private_pem)
    monkeypatch.setenv("SENTRA_TENANT_ID", TENANT)
    monkeypatch.setenv("SENTRA_AGENT_KID", "kid-xyz")
    monkeypatch.setenv("SENTRA_AGENT_PRIVATE_KEY_FILE", str(key_file))
    g = AegionGuard(AGENT)
    assert g.identity_enabled is True


# --------------------------------------------------------------------------- #
# the Bearer token actually reaches the transport
# --------------------------------------------------------------------------- #
class _FakeResp:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n: int = -1) -> bytes:
        return self._body


def test_bearer_header_sent_and_verifiable(monkeypatch):
    from aegion_guard import client as client_mod

    private_pem, public_pem = generate_keypair()
    ident = AgentIdentity(agent_id=AGENT, tenant_id=TENANT, kid="kid-1", private_key=private_pem)
    signer = JwtSigner(ident)

    captured = {}

    def fake_urlopen(req, timeout=None, context=None):
        captured["headers"] = dict(req.headers)
        return _FakeResp(b'{"decision":"ALLOW"}')

    monkeypatch.setattr(client_mod.urllib.request, "urlopen", fake_urlopen)

    c = client_mod.ValidateClient(
        validate_url="https://example.test/v1/validate",
        api_key="k",
        timeout_s=5,
        connect_retries=0,
        user_agent="ua",
        token_provider=signer.token,
    )
    body = c.post({"agent_id": AGENT})
    assert body["decision"] == "ALLOW"

    # urllib title-cases header keys.
    auth = captured["headers"].get("Authorization")
    assert auth and auth.startswith("Bearer ")
    token = auth.split(" ", 1)[1]
    claims = jwt.decode(token, public_pem, algorithms=["ES256"], audience=AUD, issuer=ISS, leeway=60)
    assert claims["tid"] == TENANT and claims["sub"] == AGENT


def test_no_bearer_when_identity_disabled(monkeypatch):
    from aegion_guard import client as client_mod

    captured = {}

    def fake_urlopen(req, timeout=None, context=None):
        captured["headers"] = dict(req.headers)
        return _FakeResp(b'{"decision":"ALLOW"}')

    monkeypatch.setattr(client_mod.urllib.request, "urlopen", fake_urlopen)
    c = client_mod.ValidateClient(
        validate_url="https://example.test/v1/validate",
        api_key="k", timeout_s=5, connect_retries=0, user_agent="ua",
    )
    c.post({"agent_id": AGENT})
    assert "Authorization" not in captured["headers"]


def test_sign_failure_is_failsecure_transport_error(monkeypatch):
    from aegion_guard import client as client_mod
    from aegion_guard.client import TransportError

    def boom():
        raise RuntimeError("hsm offline")

    c = client_mod.ValidateClient(
        validate_url="https://example.test/v1/validate",
        api_key="k", timeout_s=5, connect_retries=2, user_agent="ua",
        token_provider=boom,
    )
    with pytest.raises(TransportError) as ei:
        c.post({"agent_id": AGENT})
    assert ei.value.retryable is False  # not retried; guard turns this into DENY
