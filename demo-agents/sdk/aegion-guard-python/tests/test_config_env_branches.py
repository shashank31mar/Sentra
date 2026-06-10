"""Env-var parsing branches in config.py and context.require_current()."""
from __future__ import annotations

import pytest

from aegion_guard import ConfigError
from aegion_guard import context as ctx
from aegion_guard.config import GuardConfig


def _base():
    return dict(api_base="https://x.example.com/prod", api_key="k")


def test_env_timeout_parsed(monkeypatch):
    monkeypatch.setenv("SENTRA_VALIDATE_TIMEOUT_S", "30")
    cfg = GuardConfig.resolve(**_base())
    assert cfg.timeout_s == 30.0


def test_env_timeout_invalid(monkeypatch):
    monkeypatch.setenv("SENTRA_VALIDATE_TIMEOUT_S", "soon")
    with pytest.raises(ConfigError):
        GuardConfig.resolve(**_base())


def test_env_timeout_nonpositive(monkeypatch):
    monkeypatch.setenv("SENTRA_VALIDATE_TIMEOUT_S", "0")
    with pytest.raises(ConfigError):
        GuardConfig.resolve(**_base())


def test_env_fail_secure_false(monkeypatch):
    monkeypatch.setenv("SENTRA_FAIL_SECURE", "false")
    cfg = GuardConfig.resolve(**_base())
    assert cfg.fail_secure is False


def test_env_connect_retries(monkeypatch):
    monkeypatch.setenv("SENTRA_CONNECT_RETRIES", "3")
    cfg = GuardConfig.resolve(**_base())
    assert cfg.connect_retries == 3


def test_env_connect_retries_invalid(monkeypatch):
    monkeypatch.setenv("SENTRA_CONNECT_RETRIES", "lots")
    with pytest.raises(ConfigError):
        GuardConfig.resolve(**_base())


def test_env_connect_retries_negative(monkeypatch):
    monkeypatch.setenv("SENTRA_CONNECT_RETRIES", "-1")
    with pytest.raises(ConfigError):
        GuardConfig.resolve(**_base())


def test_explicit_connect_retries_negative_rejected():
    with pytest.raises(ConfigError):
        GuardConfig.resolve(**_base(), connect_retries=-1)


def test_require_current_outside_session_raises():
    # No active session bound → clear, actionable error.
    with pytest.raises(RuntimeError, match="No active Aegion session"):
        ctx.require_current()


def test_set_reset_current_round_trip():
    rc = ctx.RequestContext(session_id="s", user_input="u")
    token = ctx.set_current(rc)
    try:
        assert ctx.current() is rc
    finally:
        ctx.reset_current(token)
    assert ctx.current() is None
