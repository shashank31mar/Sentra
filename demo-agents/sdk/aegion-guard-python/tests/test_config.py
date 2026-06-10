"""Config resolution + init-time fail-fast (G2) and api-key privacy (G9)."""
from __future__ import annotations

import pytest

from aegion_guard import AegionGuard, ConfigError
from aegion_guard.config import GuardConfig


def test_missing_both_raises_listing_both(monkeypatch):
    monkeypatch.delenv("SENTRA_API_BASE", raising=False)
    monkeypatch.delenv("SENTRA_API_KEY", raising=False)
    with pytest.raises(ConfigError) as exc:
        AegionGuard("agent")
    msg = str(exc.value)
    assert "api_base" in msg and "api_key" in msg


def test_missing_key_only(monkeypatch):
    monkeypatch.delenv("SENTRA_API_KEY", raising=False)
    with pytest.raises(ConfigError) as exc:
        AegionGuard("agent")
    assert "api_key" in str(exc.value)
    assert "api_base" not in str(exc.value)


def test_fail_fast_at_init_not_first_call(monkeypatch):
    # The error must surface at construction, before any tool is defined/called.
    monkeypatch.delenv("SENTRA_API_BASE", raising=False)
    with pytest.raises(ConfigError):
        AegionGuard("agent")


def test_constructor_overrides_env(monkeypatch):
    monkeypatch.setenv("SENTRA_API_BASE", "https://env.example.com/prod")
    g = AegionGuard("agent", api_base="https://override.example.com/prod", api_key="k")
    assert g._config.api_base == "https://override.example.com/prod"


def test_base_trailing_slash_normalized(monkeypatch):
    g = AegionGuard("agent", api_base="https://x.example.com/prod/", api_key="k")
    assert g._config.validate_url == "https://x.example.com/prod/v1/validate"


def test_non_http_base_rejected():
    with pytest.raises(ConfigError, match="absolute http"):
        AegionGuard("agent", api_base="x.example.com/prod", api_key="k")


def test_empty_agent_id_rejected():
    with pytest.raises(ConfigError, match="agent_id"):
        AegionGuard("   ", api_base="https://x.example.com/prod", api_key="k")


def test_bad_bool_env_rejected(monkeypatch):
    monkeypatch.setenv("SENTRA_FAIL_SECURE", "maybe")
    with pytest.raises(ConfigError):
        AegionGuard("agent", api_base="https://x.example.com/prod", api_key="k")


def test_negative_timeout_rejected():
    with pytest.raises(ConfigError):
        AegionGuard("a", api_base="https://x.example.com/prod", api_key="k", timeout_s=-1)


def test_defaults(monkeypatch):
    cfg = GuardConfig.resolve(api_base="https://x.example.com/prod", api_key="k")
    assert cfg.timeout_s == 10.0
    assert cfg.fail_secure is True
    assert cfg.connect_retries == 1


def test_api_key_not_in_repr(monkeypatch):
    # G9: the key must not leak through the guard's repr/str.
    g = AegionGuard("agent", api_base="https://x.example.com/prod", api_key="super-secret-key")
    assert "super-secret-key" not in repr(g)
