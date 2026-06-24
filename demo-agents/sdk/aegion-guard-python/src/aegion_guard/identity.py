"""Agent runtime identity — ES256 JWT minting for the data plane (LLD-26 §3 / WS-A; LLD-23 signing).

The controller derives ``(tenant_id, agent_id)`` from a *verified* asymmetric token,
never from the request body. This module is the agent-side half: it holds the agent's
**private** ES256 (P-256) signing key and mints short-lived tokens that the controller
verifies against the **public** key registered under ``sentra-agent-credentials``. A
compromised controller DB can verify but never forge an agent token.

Why identity is an OPT-IN extra (``pip install 'aegion-guard[identity]'``)
-------------------------------------------------------------------------
The SDK's hot validation path is deliberately stdlib-only (LLD 23 §2) so it vendors
unchanged into a Lambda zip / Azure Function. ES256 signing is impossible in pure stdlib
(no asymmetric crypto), so signing pulls ``PyJWT[crypto]``. Agents that run under a tenant
in ``enforce`` install the extra; agents that don't need identity keep the zero-dep core.
The lazy imports below mean merely importing this module does not require the extra — only
actually minting a token (or generating a keypair) does.

Token contract — MUST match ``app/api/deps.resolve_tenant_from_jwt`` on the controller::

    header: {"alg": "ES256", "kid": <uuid>, "typ": "JWT"}
    claims: {"iss": "aegion-guard", "aud": "sentra-controller",
             "sub": <canonical agent_id>, "tid": <tenant_id>, "iat": ..., "exp": ...}

``sub`` is the canonical ``{tenant}-{cloud}-{slug}-{hash}`` agent_id and the controller
asserts it is a **delimited** prefix of ``tid`` (``tid + "-"``) — so we validate that
relationship at construction and fail fast, rather than minting tokens the controller will
silently DENY with ``IDENTITY_MISMATCH``.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from .exceptions import ConfigError, IdentityError

# Claim constants — fixed by the controller's verify (deps._JWT_ISS / _JWT_AUD).
ISS = "aegion-guard"
AUD = "sentra-controller"
ALG = "ES256"

# Token lifetime bounds. Short tokens ARE the revocation budget (LLD-26 §3.5): a
# revoked key stops verifying within ~min(token TTL, controller cache TTL). The
# controller rejects anything older than its skew window, so we cap at 15 min.
DEFAULT_TOKEN_TTL_S = 600.0
MAX_TOKEN_TTL_S = 900.0
# Re-mint this many seconds BEFORE expiry so an in-flight request never carries a
# token that expires mid-validation (and to absorb controller clock skew).
DEFAULT_REFRESH_MARGIN_S = 60.0


def _require_jwt():
    """Import PyJWT lazily; raise a clear install hint if the extra is missing."""
    try:
        import jwt  # noqa: PLC0415 — intentional lazy import (keeps core zero-dep)
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch
        raise IdentityError(
            "agent identity requires the 'identity' extra. Install it with: "
            "pip install 'aegion-guard[identity]'"
        ) from exc
    return jwt


def _require_crypto():
    """Import the ``cryptography`` primitives lazily (keypair gen / key validation)."""
    try:
        from cryptography.hazmat.primitives import serialization  # noqa: PLC0415
        from cryptography.hazmat.primitives.asymmetric import ec  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise IdentityError(
            "agent identity requires the 'identity' extra. Install it with: "
            "pip install 'aegion-guard[identity]'"
        ) from exc
    return serialization, ec


def generate_keypair() -> Tuple[str, str]:
    """Generate a fresh ES256 / P-256 keypair.

    Returns ``(private_pem, public_pem)`` — the private key in PKCS#8 PEM (held by
    the agent, never sent to Sentra) and the public key in SubjectPublicKeyInfo PEM
    (registered with the controller). Used by the provisioning helper.
    """
    serialization, ec = _require_crypto()
    key = ec.generate_private_key(ec.SECP256R1())
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


def _validate_private_key(private_key_pem: str) -> None:
    """Assert the PEM is a usable EC P-256 private key, failing fast at init."""
    serialization, ec = _require_crypto()
    try:
        from cryptography.hazmat.primitives.serialization import load_pem_private_key

        key = load_pem_private_key((private_key_pem or "").encode(), password=None)
    except Exception as exc:  # noqa: BLE001
        raise ConfigError("private_key is not a valid PEM private key") from exc
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(
        key.curve, ec.SECP256R1
    ):
        raise ConfigError("private_key must be an EC P-256 (ES256) key")


@dataclass(frozen=True)
class AgentIdentity:
    """Everything needed to mint a tenant-bound agent token.

    Validated at construction (fail fast): ``agent_id`` must be a delimited prefix
    match of ``tenant_id`` (the controller's isolation check), the TTL must be in
    ``(0, 900]`` seconds, and ``private_key`` must parse as EC P-256.
    """

    agent_id: str
    tenant_id: str
    kid: str
    private_key: str  # PKCS#8 PEM, ES256 / P-256
    token_ttl_s: float = DEFAULT_TOKEN_TTL_S
    refresh_margin_s: float = DEFAULT_REFRESH_MARGIN_S

    def __post_init__(self) -> None:
        for name in ("agent_id", "tenant_id", "kid", "private_key"):
            if not str(getattr(self, name) or "").strip():
                raise ConfigError(f"identity {name} is required and must be non-empty")
        # The controller asserts sub.startswith(tid + "-"); enforce it here so a
        # misconfigured agent fails at startup, not as a silent runtime DENY.
        if not self.agent_id.startswith(self.tenant_id + "-"):
            raise ConfigError(
                f"agent_id {self.agent_id!r} must be tenant-scoped: it must start "
                f"with {self.tenant_id + '-'!r} (canonical id is "
                f"'{{tenant}}-{{cloud}}-{{slug}}-{{hash}}')"
            )
        if not (0 < self.token_ttl_s <= MAX_TOKEN_TTL_S):
            raise ConfigError(
                f"token_ttl_s must be in (0, {MAX_TOKEN_TTL_S}] seconds "
                f"(got {self.token_ttl_s})"
            )
        if self.refresh_margin_s < 0 or self.refresh_margin_s >= self.token_ttl_s:
            raise ConfigError(
                "refresh_margin_s must be in [0, token_ttl_s); "
                f"got margin={self.refresh_margin_s}, ttl={self.token_ttl_s}"
            )
        _validate_private_key(self.private_key)


class JwtSigner:
    """Mints and caches a short-lived agent JWT, re-minting before expiry.

    Thread-safe: the sync validate path may run inside ``asyncio.to_thread`` worker
    threads, so ``token()`` guards the cache with a lock. Minting from a held
    private key is cheap, but caching keeps the steady state to one signature per
    ``token_ttl_s - refresh_margin_s`` window rather than one per validate call.
    """

    def __init__(self, identity: AgentIdentity, *, time_fn: Callable[[], float] = time.time) -> None:
        self._id = identity
        self._now = time_fn
        self._lock = threading.Lock()
        self._cached: Optional[str] = None
        self._cached_exp: float = 0.0

    @property
    def identity(self) -> AgentIdentity:
        return self._id

    def token(self) -> str:
        """Return a currently-valid compact JWT, minting a fresh one when the
        cached token is within ``refresh_margin_s`` of expiry."""
        now = self._now()
        with self._lock:
            if self._cached is not None and now < self._cached_exp - self._id.refresh_margin_s:
                return self._cached
            tok, exp = self._mint(now)
            self._cached, self._cached_exp = tok, exp
            return tok

    def _mint(self, now: float) -> Tuple[str, float]:
        jwt = _require_jwt()
        exp = now + self._id.token_ttl_s
        claims = {
            "iss": ISS,
            "aud": AUD,
            "sub": self._id.agent_id,
            "tid": self._id.tenant_id,
            "iat": int(now),
            "exp": int(exp),
        }
        try:
            tok = jwt.encode(
                claims,
                self._id.private_key,
                algorithm=ALG,
                headers={"kid": self._id.kid},
            )
        except Exception as exc:  # noqa: BLE001 — surface as identity failure, never silent
            raise IdentityError(f"failed to mint agent token: {exc}") from exc
        # PyJWT < 2 returned bytes; normalize so callers always get str.
        return (tok.decode() if isinstance(tok, bytes) else tok), exp
