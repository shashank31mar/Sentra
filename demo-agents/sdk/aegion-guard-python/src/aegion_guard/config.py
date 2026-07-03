"""Configuration resolution + validation (LLD 23 §7).

Constructor args override environment variables. Required values (`api_base`,
`api_key`) are validated **at construction time** — we fail fast with a clear
``ConfigError`` listing what's missing, rather than letting the first tool call
explode somewhere deep in the request path.

No values are hard-coded (best-practices §2); the demo's API Gateway URL only
ever arrives via ``SENTRA_API_BASE`` or the constructor.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from .exceptions import ConfigError

# Environment variable names (single source of truth).
ENV_API_BASE = "SENTRA_API_BASE"
ENV_API_KEY = "SENTRA_API_KEY"
ENV_TIMEOUT = "SENTRA_VALIDATE_TIMEOUT_S"
ENV_FAIL_SECURE = "SENTRA_FAIL_SECURE"
ENV_CONNECT_RETRIES = "SENTRA_CONNECT_RETRIES"
# Local-floor seam (WS-A ship-now; lld/36 §4.2.2). Opt-in flag that a future
# in-process floor (lld/37) keys off. In 0.2.0 it is a NO-OP: `off` (the default)
# is exactly today's behavior (every call routes to the hosted PDP); `on` still
# routes to hosted (fail-secure) because no interpreter is installed yet — it only
# emits a one-time warning that edge enforcement is not active. Default MUST be
# False: a True default would route at a floor that does not exist.
ENV_LOCAL_FLOOR = "SENTRA_LOCAL_FLOOR_ENABLED"

# Data-plane identity (opt-in; LLD-26 §3 / WS-A). All three of tenant_id, kid and
# a private key must be supplied together — partial identity config is a hard
# error so an agent never half-signs and gets silently denied under `enforce`.
ENV_TENANT_ID = "SENTRA_TENANT_ID"
ENV_KID = "SENTRA_AGENT_KID"
ENV_PRIVATE_KEY = "SENTRA_AGENT_PRIVATE_KEY"            # PEM literal
ENV_PRIVATE_KEY_FILE = "SENTRA_AGENT_PRIVATE_KEY_FILE"  # path to a PEM file
ENV_TOKEN_TTL = "SENTRA_TOKEN_TTL_S"

_DEFAULT_TIMEOUT_S = 10.0          # hot-path default; raise for cross-cloud (§7)
_DEFAULT_CONNECT_RETRIES = 1       # connection-establishment errors only (§8)
_DEFAULT_TOKEN_TTL_S = 600.0       # ≤15 min; the token IS the revocation budget (§3.5)
_MAX_TOKEN_TTL_S = 900.0
_VALIDATE_PATH = "/v1/validate"

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    val = raw.strip().lower()
    if val in _TRUE:
        return True
    if val in _FALSE:
        return False
    raise ConfigError(
        f"{name}={raw!r} is not a valid boolean "
        f"(expected one of {sorted(_TRUE | _FALSE)})"
    )


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name}={raw!r} is not a valid number") from exc
    if value <= 0:
        raise ConfigError(f"{name} must be > 0 (got {value})")
    return value


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name}={raw!r} is not a valid integer") from exc
    if value < 0:
        raise ConfigError(f"{name} must be >= 0 (got {value})")
    return value


@dataclass(frozen=True)
class GuardConfig:
    """Resolved, validated configuration for a guard instance."""

    api_base: str
    api_key: str
    timeout_s: float
    fail_secure: bool
    connect_retries: int
    # Local-floor seam (WS-A; lld/36 §4.2.2). False = today's behavior (route every
    # call to hosted). No-op in 0.2.0 regardless (no interpreter shipped).
    local_floor_enabled: bool = False
    # Data-plane identity (None unless all three are configured together).
    tenant_id: Optional[str] = None
    kid: Optional[str] = None
    private_key: Optional[str] = None  # PKCS#8 PEM, ES256 / P-256
    token_ttl_s: float = _DEFAULT_TOKEN_TTL_S

    @property
    def validate_url(self) -> str:
        """Full URL of the validate endpoint (base already includes the stage)."""
        return f"{self.api_base}{_VALIDATE_PATH}"

    @property
    def identity_enabled(self) -> bool:
        """True when this guard will sign requests with an agent JWT (WS-A)."""
        return bool(self.tenant_id and self.kid and self.private_key)

    @classmethod
    def resolve(
        cls,
        *,
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_s: Optional[float] = None,
        fail_secure: Optional[bool] = None,
        connect_retries: Optional[int] = None,
        local_floor_enabled: Optional[bool] = None,
        tenant_id: Optional[str] = None,
        kid: Optional[str] = None,
        private_key: Optional[str] = None,
        private_key_file: Optional[str] = None,
        token_ttl_s: Optional[float] = None,
    ) -> "GuardConfig":
        """Build config from explicit args, falling back to env. Fail fast.

        Raises ``ConfigError`` listing every missing/invalid required value so
        the integrator fixes them all at once, at init, not at first call.
        """
        resolved_base = (api_base or os.environ.get(ENV_API_BASE) or "").strip()
        resolved_key = (api_key or os.environ.get(ENV_API_KEY) or "").strip()

        missing = []
        if not resolved_base:
            missing.append(f"api_base ({ENV_API_BASE})")
        if not resolved_key:
            missing.append(f"api_key ({ENV_API_KEY})")
        if missing:
            raise ConfigError(
                "AegionGuard is missing required configuration: "
                + ", ".join(missing)
                + ". Set the environment variable(s) or pass the value(s) to "
                "AegionGuard(...)."
            )

        # Normalize the base: drop a trailing slash so f"{base}/v1/validate"
        # never produces a double slash.
        resolved_base = resolved_base.rstrip("/")
        if not resolved_base.startswith(("http://", "https://")):
            raise ConfigError(
                f"api_base must be an absolute http(s) URL including the stage, "
                f"e.g. https://<id>.execute-api.<region>.amazonaws.com/prod "
                f"(got {resolved_base!r})"
            )

        if timeout_s is not None:
            if timeout_s <= 0:
                raise ConfigError(f"timeout_s must be > 0 (got {timeout_s})")
            resolved_timeout = float(timeout_s)
        else:
            resolved_timeout = _env_float(ENV_TIMEOUT, _DEFAULT_TIMEOUT_S)

        if fail_secure is not None:
            resolved_fail_secure = bool(fail_secure)
        else:
            resolved_fail_secure = _env_bool(ENV_FAIL_SECURE, True)

        if connect_retries is not None:
            if connect_retries < 0:
                raise ConfigError(
                    f"connect_retries must be >= 0 (got {connect_retries})"
                )
            resolved_retries = int(connect_retries)
        else:
            resolved_retries = _env_int(ENV_CONNECT_RETRIES, _DEFAULT_CONNECT_RETRIES)

        # Local-floor seam flag (WS-A; lld/36 §4.2.2). Reuse `_env_bool`, which
        # RAISES ConfigError on an unparseable value (fail-closed at construction),
        # so `SENTRA_LOCAL_FLOOR_ENABLED=maybe` fails now, not silently as False.
        if local_floor_enabled is not None:
            resolved_local_floor = bool(local_floor_enabled)
        else:
            resolved_local_floor = _env_bool(ENV_LOCAL_FLOOR, False)

        # ---- data-plane identity (opt-in, all-or-none) --------------------- #
        r_tenant = (tenant_id or os.environ.get(ENV_TENANT_ID) or "").strip() or None
        r_kid = (kid or os.environ.get(ENV_KID) or "").strip() or None
        r_private_key = (private_key or os.environ.get(ENV_PRIVATE_KEY) or "").strip() or None
        r_key_file = (private_key_file or os.environ.get(ENV_PRIVATE_KEY_FILE) or "").strip() or None
        if r_private_key is None and r_key_file is not None:
            try:
                with open(r_key_file, "r", encoding="utf-8") as fh:
                    r_private_key = fh.read().strip() or None
            except OSError as exc:
                raise ConfigError(
                    f"could not read private key file {r_key_file!r}: {exc}"
                ) from exc

        provided = [p for p in (r_tenant, r_kid, r_private_key) if p]
        if provided and len(provided) < 3:
            missing = []
            if not r_tenant:
                missing.append(f"tenant_id ({ENV_TENANT_ID})")
            if not r_kid:
                missing.append(f"kid ({ENV_KID})")
            if not r_private_key:
                missing.append(
                    f"private_key ({ENV_PRIVATE_KEY} or {ENV_PRIVATE_KEY_FILE})"
                )
            raise ConfigError(
                "agent identity is partially configured — set all of tenant_id, kid "
                "and a private key together, or none. Missing: " + ", ".join(missing)
            )

        if token_ttl_s is not None:
            resolved_ttl = float(token_ttl_s)
        else:
            resolved_ttl = _env_float(ENV_TOKEN_TTL, _DEFAULT_TOKEN_TTL_S)
        if not (0 < resolved_ttl <= _MAX_TOKEN_TTL_S):
            raise ConfigError(
                f"token_ttl_s must be in (0, {_MAX_TOKEN_TTL_S}] seconds (got {resolved_ttl})"
            )

        return cls(
            api_base=resolved_base,
            api_key=resolved_key,
            timeout_s=resolved_timeout,
            fail_secure=resolved_fail_secure,
            connect_retries=resolved_retries,
            local_floor_enabled=resolved_local_floor,
            tenant_id=r_tenant,
            kid=r_kid,
            private_key=r_private_key,
            token_ttl_s=resolved_ttl,
        )
