"""Shared fixtures for the aegion-guard test suite.

All unit tests run against a fake validate client (monkeypatched ``post``) — no
network, no deployed agent. A live contract test lives in
``test_contract_live.py`` and is gated on ``RUN_INTEGRATION=1``.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List

import pytest

# Make the package importable from src/ without an install step.
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Give every mock-based test a known dummy config via env.

    EXCEPTION: when RUN_INTEGRATION=1, leave SENTRA_API_BASE/KEY untouched so the gated live
    contract test (test_contract_live.py) hits the real endpoint with the real key the operator set —
    otherwise this would clobber them with the dummy host and every live call would fail-secure.
    """
    if os.environ.get("RUN_INTEGRATION") == "1":
        return
    monkeypatch.setenv("SENTRA_API_BASE", "https://example.execute-api.us-east-1.amazonaws.com/prod")
    monkeypatch.setenv("SENTRA_API_KEY", "test-key-do-not-log")
    monkeypatch.delenv("SENTRA_VALIDATE_TIMEOUT_S", raising=False)
    monkeypatch.delenv("SENTRA_FAIL_SECURE", raising=False)
    monkeypatch.delenv("SENTRA_CONNECT_RETRIES", raising=False)


class FakeClient:
    """Stand-in for ValidateClient. Records sent payloads; returns canned bodies."""

    def __init__(self) -> None:
        self.sent: List[Dict[str, Any]] = []
        self._responses: List[Any] = []
        self._default: Any = {"decision": "ALLOW", "reason": "ok", "trust_score": 99.0,
                              "latency_ms": 12.0}

    def queue(self, response: Any) -> "FakeClient":
        """Queue a response (dict to return, or an Exception to raise)."""
        self._responses.append(response)
        return self

    def set_default(self, response: Any) -> "FakeClient":
        self._default = response
        return self

    def post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.sent.append(payload)
        response = self._responses.pop(0) if self._responses else self._default
        if isinstance(response, BaseException):
            raise response
        return response

    @property
    def last(self) -> Dict[str, Any]:
        return self.sent[-1]


@pytest.fixture
def fake_client() -> FakeClient:
    """A FakeClient the tests can queue responses on."""
    return FakeClient()


@pytest.fixture
def make_guard(fake_client):
    """Factory: build an AegionGuard whose client is the FakeClient.

    Config is still resolved/validated normally (so config tests are real); only
    the transport is swapped after construction.
    """
    from aegion_guard import AegionGuard

    def _factory(**kwargs: Any) -> AegionGuard:
        agent_id = kwargs.pop("agent_id", "test-agent")
        g = AegionGuard(agent_id, **kwargs)
        g._client = fake_client  # type: ignore[attr-defined]
        return g

    return _factory
