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

_DEFAULT_TIMEOUT_S = 10.0          # hot-path default; raise for cross-cloud (§7)
_DEFAULT_CONNECT_RETRIES = 1       # connection-establishment errors only (§8)
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

    @property
    def validate_url(self) -> str:
        """Full URL of the validate endpoint (base already includes the stage)."""
        return f"{self.api_base}{_VALIDATE_PATH}"

    @classmethod
    def resolve(
        cls,
        *,
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_s: Optional[float] = None,
        fail_secure: Optional[bool] = None,
        connect_retries: Optional[int] = None,
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

        return cls(
            api_base=resolved_base,
            api_key=resolved_key,
            timeout_s=resolved_timeout,
            fail_secure=resolved_fail_secure,
            connect_retries=resolved_retries,
        )
