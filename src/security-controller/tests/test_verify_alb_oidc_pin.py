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


# --------------------------------------------------------------------------- #
# FIX-B (green≠correct gaps): (1) env-token vocabulary drift — the gate keyed on
# the literal "production" but the CDK config yamls set "prod"/"dev"/"staging", so
# the gate silently no-op'd on any real deploy; (2) the gate had NO production
# caller — nothing invoked it, so the pin could ship empty in prod with no backstop.
# These tests pin BOTH: the token-vocabulary match, and the live boot-time caller.
# --------------------------------------------------------------------------- #
def test_is_production_env_recognizes_cdk_prod_token(monkeypatch):
    """The prod.yaml token is "prod", NOT "production" — the drift the gap flagged.
    `is_production_env` MUST recognize it (this test FAILS against the old
    `== "production"` literal gate — that is the point)."""
    monkeypatch.setattr(settings, "environment", "prod")
    assert settings.is_production_env() is True
    monkeypatch.setattr(settings, "environment", "PROD")  # case-insensitive
    assert settings.is_production_env() is True
    monkeypatch.setattr(settings, "environment", "production")  # code default
    assert settings.is_production_env() is True


def test_is_production_env_false_for_dev_and_staging(monkeypatch):
    """Genuine non-prod tokens must NOT be treated as prod (else a local dev box or
    the staging stack would be bricked by the boot gate)."""
    for tok in ("dev", "staging", "development", "test", ""):
        monkeypatch.setattr(settings, "environment", tok)
        assert settings.is_production_env() is False, tok


def test_prod_gate_raises_under_cdk_prod_token(monkeypatch):
    """The drift-fix, end-to-end at the gate: `environment="prod"` (the yaml token)
    + empty pins MUST raise. Against the old literal-"production" gate this silently
    passed — the exact multi-stack forgery no-op the gap called out."""
    monkeypatch.setattr(settings, "environment", "prod")
    monkeypatch.setattr(settings, "alb_oidc_expected_signers", "")
    monkeypatch.setattr(settings, "alb_oidc_expected_issuer", "")
    with pytest.raises(RuntimeError):
        settings.assert_alb_oidc_pin_ready_for_prod()


def test_boot_gate_inert_when_flag_off(monkeypatch):
    """Default posture (flag off) — local dev / the hermetic pytest suite boot the
    app unpinned and MUST NOT be bricked, even on the `production` code-default."""
    monkeypatch.setattr(settings, "alb_oidc_pin_enforce_at_boot", False)
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "alb_oidc_expected_signers", "")
    monkeypatch.setattr(settings, "alb_oidc_expected_issuer", "")
    settings.assert_alb_oidc_pin_ready_at_boot()  # no raise


def test_boot_gate_raises_when_flag_on_and_unpinned(monkeypatch):
    """A real deployment (flag True via compute_stack.py) with empty pins MUST fail
    to boot — the live backstop. Decoupled from the env token: this holds even on
    the live dev-is-prod stack (`environment="dev"`) where a token-only gate would
    wrongly no-op."""
    monkeypatch.setattr(settings, "alb_oidc_pin_enforce_at_boot", True)
    monkeypatch.setattr(settings, "environment", "dev")  # live dev-is-prod stack
    monkeypatch.setattr(settings, "alb_oidc_expected_signers", "")
    monkeypatch.setattr(settings, "alb_oidc_expected_issuer", "")
    with pytest.raises(RuntimeError) as ei:
        settings.assert_alb_oidc_pin_ready_at_boot()
    assert "ALB_OIDC_EXPECTED_SIGNERS" in str(ei.value)


def test_boot_gate_passes_when_flag_on_and_pinned(monkeypatch):
    """A boot-enforced deployment with both pins populated boots normally."""
    monkeypatch.setattr(settings, "alb_oidc_pin_enforce_at_boot", True)
    monkeypatch.setattr(settings, "environment", "prod")
    monkeypatch.setattr(settings, "alb_oidc_expected_signers", EXPECTED_SIGNER)
    monkeypatch.setattr(settings, "alb_oidc_expected_issuer", EXPECTED_ISS)
    settings.assert_alb_oidc_pin_ready_at_boot()  # no raise


def test_lifespan_calls_boot_pin_gate(monkeypatch):
    """The Gap-2 arbiter: prove main.py's lifespan ACTUALLY invokes the boot gate
    (the gap was 'no caller anywhere'). We spy on the settings method and drive the
    lifespan startup; the spy MUST have been called. A regression that drops the
    call from lifespan makes this test fail."""
    import asyncio
    import app.main as main_mod

    called = {"n": 0}

    def _spy(self):
        called["n"] += 1

    # Patch on the Settings CLASS — pydantic BaseSettings guards instance-attribute
    # assignment (methods are not model fields), so `setattr(settings, method, ...)`
    # raises; the class dict is not guarded.
    monkeypatch.setattr(type(main_mod.settings), "assert_alb_oidc_pin_ready_at_boot", _spy)
    # Don't do the real (network-touching) service build — stub the two other
    # startup steps so we isolate the pin-gate call.
    import app.services as services_mod
    monkeypatch.setattr(services_mod, "ValidationService", lambda: object())
    import app.services.scheduler as sched_mod
    monkeypatch.setattr(sched_mod, "assert_registration_complete", lambda svc: None)

    async def _drive():
        app_stub = main_mod.app
        async with main_mod.lifespan(app_stub):
            pass

    asyncio.run(_drive())
    assert called["n"] == 1, "lifespan did not call assert_alb_oidc_pin_ready_at_boot"


def test_lifespan_refuses_boot_when_unpinned_and_enforced(monkeypatch):
    """End-to-end fail-secure: an unpinned + boot-enforced app RAISES out of the
    lifespan startup (the ECS task would never become healthy). This is the live
    behaviour the missing-caller gap left absent."""
    import asyncio
    import app.main as main_mod

    monkeypatch.setattr(main_mod.settings, "alb_oidc_pin_enforce_at_boot", True)
    monkeypatch.setattr(main_mod.settings, "environment", "prod")
    monkeypatch.setattr(main_mod.settings, "alb_oidc_expected_signers", "")
    monkeypatch.setattr(main_mod.settings, "alb_oidc_expected_issuer", "")

    async def _drive():
        async with main_mod.lifespan(main_mod.app):
            pass

    with pytest.raises(RuntimeError):
        asyncio.run(_drive())


# ---------------------------------------------------------------------------
# Deploy-brick guard (WS-M M1.0 FIX-B — the coverage gap the green suite hid).
#
# Every test above monkeypatches `settings`, so NONE of them exercise the real
# path a `cdk deploy` takes: cdk/config/<env>.yaml -> compute_stack.py's
# `config.get(...)` defaults -> the ECS task env -> a real Settings() -> the boot
# gate. That path is where the outage lives: compute_stack DEFAULTS
# ALB_OIDC_PIN_ENFORCE_AT_BOOT to `true`, and if a shipped config sets neither
# alb_oidc_expected_signers nor alb_oidc_expected_issuer, the container RAISES at
# lifespan startup -> the ECS task never becomes healthy -> control-plane OUTAGE.
# These tests reconstruct that exact chain from the on-disk yaml and assert the
# shipped combination cannot brick boot. They FAIL if a config re-introduces the
# unpinned-but-boot-enforced combination (the regression these tests exist to catch).
# ---------------------------------------------------------------------------

import pathlib

import yaml

from app.config import Settings

# The three env tokens whose yaml compute_stack.py loads (cdk/app.py: {env}.yaml).
_CDK_CONFIG_ENVS = ("dev", "prod", "staging")

# The ECS task env keys compute_stack.py emits for the ALB-OIDC pin + boot gate.
_ALB_PIN_ENV_KEYS = (
    "ALB_OIDC_EXPECTED_SIGNERS",
    "ALB_OIDC_EXPECTED_ISSUER",
    "ALB_OIDC_PIN_ENFORCE_AT_BOOT",
)


def _repo_root() -> pathlib.Path:
    # tests/ -> security-controller/ -> src/ -> repo root
    return pathlib.Path(__file__).resolve().parents[3]


def _emitted_task_env(cfg: dict) -> dict:
    """Replicate compute_stack.py's ALB-OIDC env emission verbatim (the three lines
    at cdk/stacks/compute_stack.py that set the task-definition environment). If
    compute_stack's defaults change, mirror them here so the test keeps guarding the
    real deploy path. The `alb_oidc_pin_enforce_at_boot` default of True is the
    load-bearing bit — it is what bricks an unpinned deploy."""
    return {
        "ALB_OIDC_EXPECTED_SIGNERS": str(cfg.get("alb_oidc_expected_signers", "")),
        "ALB_OIDC_EXPECTED_ISSUER": str(cfg.get("alb_oidc_expected_issuer", "")),
        "ALB_OIDC_PIN_ENFORCE_AT_BOOT": str(
            cfg.get("alb_oidc_pin_enforce_at_boot", True)
        ).lower(),
    }


def _settings_from_task_env(monkeypatch, env: dict) -> Settings:
    """Build a real Settings from the ECS task env the way the container does —
    through actual environment variables + pydantic-settings parsing (str->bool for
    the flag), NOT via monkeypatch.setattr on a live instance. This exercises the
    same code path a booting container hits."""
    for k in _ALB_PIN_ENV_KEYS:
        monkeypatch.setenv(k, env[k])
    return Settings()


@pytest.mark.parametrize("env_token", _CDK_CONFIG_ENVS)
def test_shipped_cdk_config_does_not_brick_boot(monkeypatch, env_token):
    """THE arbiter for the deploy-brick gap: for every shipped cdk/config/<env>.yaml,
    the boot gate the container runs at startup MUST NOT raise. A config that leaves
    ALB_OIDC_PIN_ENFORCE_AT_BOOT at its compute_stack `true` default while both pins
    are empty makes assert_alb_oidc_pin_ready_at_boot() raise -> the ECS task never
    boots -> outage. This reads the real yaml + real compute_stack defaults, builds a
    real Settings from the emitted env, and fails if the deployable combination cannot
    boot. It FAILS on the pre-fix config (flag defaults true + empty pins)."""
    cfg_path = _repo_root() / "cdk" / "config" / f"{env_token}.yaml"
    cfg = yaml.safe_load(cfg_path.read_text()) or {}
    env = _emitted_task_env(cfg)
    settings_at_boot = _settings_from_task_env(monkeypatch, env)
    # Must not raise — else the next `cdk deploy` of the controller bricks the task.
    settings_at_boot.assert_alb_oidc_pin_ready_at_boot()


@pytest.mark.parametrize("env_token", _CDK_CONFIG_ENVS)
def test_shipped_cdk_config_boot_enforce_only_when_pinned(monkeypatch, env_token):
    """The invariant behind the fix, stated positively so it can't be satisfied by an
    accidental change: a shipped config may enable boot-enforcement (flag true) ONLY
    if BOTH pins are populated. Enforce-on with an empty pin is the bricking combo and
    is forbidden. Enforce-off (the transition-window posture) is always allowed."""
    cfg_path = _repo_root() / "cdk" / "config" / f"{env_token}.yaml"
    cfg = yaml.safe_load(cfg_path.read_text()) or {}
    env = _emitted_task_env(cfg)
    s = _settings_from_task_env(monkeypatch, env)
    if s.alb_oidc_pin_enforce_at_boot:
        assert s.alb_oidc_pin_active(), (
            f"{env_token}.yaml enables ALB_OIDC_PIN_ENFORCE_AT_BOOT but leaves the "
            f"signer/issuer pin empty — this bricks the ECS task at boot. Populate "
            f"alb_oidc_expected_signers + alb_oidc_expected_issuer, or hold the flag "
            f"false during the transition window."
        )


def test_deploy_brick_reproduction_is_real(monkeypatch):
    """Non-vacuity guard: prove the boot gate WOULD brick the exact bad combination
    (flag true + empty pins) — the scenario the two guards above certify the shipped
    configs avoid. If this ever stops raising, the gate itself has been weakened and
    the guards above have gone vacuous, so they must be re-examined."""
    bricking = _settings_from_task_env(
        monkeypatch,
        {
            "ALB_OIDC_EXPECTED_SIGNERS": "",
            "ALB_OIDC_EXPECTED_ISSUER": "",
            "ALB_OIDC_PIN_ENFORCE_AT_BOOT": "true",
        },
    )
    with pytest.raises(RuntimeError):
        bricking.assert_alb_oidc_pin_ready_at_boot()
