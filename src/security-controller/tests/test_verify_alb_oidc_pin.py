"""ALB-OIDC signer + issuer PIN tests (WS-M M1.0 / lld/39 §3.1).

Plain ES256 verify accepts a token signed by ANY in-region ALB and ANY Cognito
pool. Account 531109575379 hosts multiple stacks, so a sibling ALB's
signature-valid token would otherwise pass ``verify_alb_oidc`` and reach the
control plane. The pin asserts the JWT header ``signer`` is in the expected
allowlist and ``iss`` matches the expected pool — on BOTH header paths
(``x-sentra-oidc-data`` and the native ``x-amzn-oidc-data``), so the fallback
can't bypass it.
"""
from __future__ import annotations

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.config import settings

EXPECTED_SIGNER = "arn:aws:elasticloadbalancing:us-east-1:531109575379:loadbalancer/app/sentra/aaa"
FOREIGN_SIGNER = "arn:aws:elasticloadbalancing:us-east-1:531109575379:loadbalancer/app/evil/bbb"
EXPECTED_ISS = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_expectedpool"


def _keypair():
    key = ec.generate_private_key(ec.SECP256R1())
    from cryptography.hazmat.primitives import serialization
    priv = key.private_bytes(serialization.Encoding.PEM,
                             serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()
    pub = key.public_key().public_bytes(serialization.Encoding.PEM,
                                         serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return priv, pub


def _sign(priv, *, signer, iss, kid="kid-1"):
    import time
    return jwt.encode(
        {"sub": "op-1", "email": "op@x", "iss": iss, "exp": int(time.time()) + 300},
        priv, algorithm="ES256", headers={"kid": kid, "signer": signer})


class _Req:
    def __init__(self, headers):
        self.headers = headers


@pytest.fixture
def pinned(monkeypatch):
    """Populate the pin allowlists + stub the ALB key cache to our test pubkey."""
    priv, pub = _keypair()
    monkeypatch.setattr(settings, "alb_oidc_expected_signers", EXPECTED_SIGNER)
    monkeypatch.setattr(settings, "alb_oidc_expected_issuer", EXPECTED_ISS)
    import app.api.deps as deps
    monkeypatch.setattr(deps._alb_keys, "get", lambda kid, region: pub)
    # Ensure the test seam is off so the real verify path runs.
    monkeypatch.setattr(deps, "_alb_claims_override", None)
    return priv, pub, deps


def test_pin_rejects_foreign_alb_signer(pinned):
    priv, _pub, deps = pinned
    tok = _sign(priv, signer=FOREIGN_SIGNER, iss=EXPECTED_ISS)
    with pytest.raises(Exception) as ei:
        deps.verify_alb_oidc(_Req({"x-amzn-oidc-data": tok}))
    assert getattr(ei.value, "status_code", None) == 401


def test_pin_rejects_wrong_issuer(pinned):
    priv, _pub, deps = pinned
    tok = _sign(priv, signer=EXPECTED_SIGNER, iss="https://cognito-idp.us-east-1.amazonaws.com/us-east-1_evil")
    with pytest.raises(Exception) as ei:
        deps.verify_alb_oidc(_Req({"x-amzn-oidc-data": tok}))
    assert getattr(ei.value, "status_code", None) == 401


def test_pin_accepts_expected_signer_and_issuer(pinned):
    priv, _pub, deps = pinned
    tok = _sign(priv, signer=EXPECTED_SIGNER, iss=EXPECTED_ISS)
    claims = deps.verify_alb_oidc(_Req({"x-amzn-oidc-data": tok}))
    assert claims["sub"] == "op-1"


def test_pin_enforced_on_x_sentra_oidc_data_path(pinned):
    """The console re-emits under `x-sentra-oidc-data` (read first). The pin must
    apply there too — a foreign signer on that header is still rejected."""
    priv, _pub, deps = pinned
    tok = _sign(priv, signer=FOREIGN_SIGNER, iss=EXPECTED_ISS)
    with pytest.raises(Exception) as ei:
        deps.verify_alb_oidc(_Req({"x-sentra-oidc-data": tok}))
    assert getattr(ei.value, "status_code", None) == 401


def test_pin_enforced_on_x_amzn_oidc_data_path(pinned):
    """The native `x-amzn-oidc-data` fallback path enforces the pin identically —
    the fallback can't be used to bypass it."""
    priv, _pub, deps = pinned
    tok = _sign(priv, signer=FOREIGN_SIGNER, iss=EXPECTED_ISS)
    with pytest.raises(Exception) as ei:
        deps.verify_alb_oidc(_Req({"x-amzn-oidc-data": tok}))
    assert getattr(ei.value, "status_code", None) == 401


def test_no_pin_when_allowlists_empty(monkeypatch):
    """Empty allowlists (dev/test/transition) → no pin: a signature-valid token
    passes regardless of signer/iss (the mechanism is inert until configured)."""
    priv, pub = _keypair()
    monkeypatch.setattr(settings, "alb_oidc_expected_signers", "")
    monkeypatch.setattr(settings, "alb_oidc_expected_issuer", "")
    import app.api.deps as deps
    monkeypatch.setattr(deps._alb_keys, "get", lambda kid, region: pub)
    monkeypatch.setattr(deps, "_alb_claims_override", None)
    tok = _sign(priv, signer=FOREIGN_SIGNER, iss="whatever")
    claims = deps.verify_alb_oidc(_Req({"x-amzn-oidc-data": tok}))
    assert claims["sub"] == "op-1"


# --------------------------------------------------------------------------- #
# Prod-readiness config gate (WS-M M1.0 gap-fix / lld/39 §3.1).
# The pin is correct + tested for both populated and empty, but nothing asserted
# that a PRODUCTION deployment actually sets the two env vars — so prod stayed
# unpinned until an operator remembered. `assert_alb_oidc_pin_ready_for_prod`
# codifies that requirement so the deploy runbook / CI can trip on a genuinely
# unpinned prod (rather than shipping the multi-stack forgery the pin exists to
# stop). These tests are the arbiter of that gate.
# --------------------------------------------------------------------------- #
def test_pin_active_requires_both_halves(monkeypatch):
    """The pin only fires when BOTH signer allowlist AND issuer are set — either
    half empty = inert (matches the per-half verify_alb_oidc behaviour)."""
    monkeypatch.setattr(settings, "alb_oidc_expected_signers", EXPECTED_SIGNER)
    monkeypatch.setattr(settings, "alb_oidc_expected_issuer", "")
    assert settings.alb_oidc_pin_active() is False
    monkeypatch.setattr(settings, "alb_oidc_expected_issuer", EXPECTED_ISS)
    assert settings.alb_oidc_pin_active() is True


def test_prod_gate_raises_when_pin_unset(monkeypatch):
    """A production environment with an unset pin MUST fail the readiness gate —
    this is the check the deploy runbook runs before a money-movement enforce flip.
    (Reverting the pin to empty in prod would trip this — non-vacuous.)"""
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "alb_oidc_expected_signers", "")
    monkeypatch.setattr(settings, "alb_oidc_expected_issuer", "")
    with pytest.raises(RuntimeError) as ei:
        settings.assert_alb_oidc_pin_ready_for_prod()
    assert "ALB_OIDC_EXPECTED_SIGNERS" in str(ei.value)


def test_prod_gate_passes_when_pin_set(monkeypatch):
    """A production environment with both pins populated passes the gate."""
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "alb_oidc_expected_signers", EXPECTED_SIGNER)
    monkeypatch.setattr(settings, "alb_oidc_expected_issuer", EXPECTED_ISS)
    settings.assert_alb_oidc_pin_ready_for_prod()  # no raise


def test_prod_gate_inert_for_non_prod_env(monkeypatch):
    """Dev/test/transition (environment != 'production') is allowed to run unpinned
    — the gate must NOT trip there (empty pins are correct outside prod)."""
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "alb_oidc_expected_signers", "")
    monkeypatch.setattr(settings, "alb_oidc_expected_issuer", "")
    settings.assert_alb_oidc_pin_ready_for_prod()  # no raise
