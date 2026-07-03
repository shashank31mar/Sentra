"""Config resolution + init-time fail-fast (G2) and api-key privacy (G9)."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

import aegion_guard
from aegion_guard import AegionGuard, ConfigError
from aegion_guard.config import GuardConfig

_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _pyproject_version() -> str:
    """Parse the [project] version from pyproject without a toml runtime dep.

    tomllib is 3.11+; the SDK targets 3.9+. Prefer tomllib, else parse the single
    `version = "..."` line under [project] (stdlib-only, matching the redactor
    invariant the release must not break).
    """
    text = _PYPROJECT.read_text(encoding="utf-8")
    if sys.version_info >= (3, 11):
        import tomllib

        return tomllib.loads(text)["project"]["version"]
    in_project = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_project = stripped == "[project]"
            continue
        if in_project and stripped.startswith("version") and "=" in stripped:
            return ast.literal_eval(stripped.split("=", 1)[1].strip())
    raise AssertionError("no `version` key found under [project]")


# ================================================================ WS-A (lld/36)
# A1.1: the two version sites must not drift; __contract__ stays the bare "v1".


def test_version_and_contract_pin():
    """Release-gate (A1.1): __version__ is 0.2.0 at BOTH sites (package +
    pyproject) and __contract__ stays the bare wire string "v1" (not "/v1").

    Non-vacuous: the assert on equal-strings fails if either site is bumped
    without the other (the silent-drift footgun) or if the wire contract is
    perturbed. Must fail if a reviewer forgets one of the two sites."""
    assert aegion_guard.__version__ == "0.2.0"
    assert _pyproject_version() == "0.2.0"
    assert aegion_guard.__version__ == _pyproject_version(), (
        "the two version sites drifted — bump both __init__.py and pyproject.toml"
    )
    # The /v1/validate wire contract is unchanged: a bare "v1", not "/v1".
    assert aegion_guard.__contract__ == "v1"


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
