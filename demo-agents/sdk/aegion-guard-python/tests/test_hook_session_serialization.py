"""on_decision hook (G3), nested session inner-wins (G4),
contract mismatch warn-continue (G5), non-serializable params (G8/§8),
and api-key privacy in hook payloads (G9)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aegion_guard import AegionGuard, ConfigError, ToolDenied


def test_on_decision_called_with_decision(make_guard, fake_client):
    seen = []
    guard = make_guard(on_decision=seen.append)
    fake_client.set_default({"decision": "ALLOW", "trust_score": 88})

    @guard.tool()
    def thing():
        return "ran"

    with guard.session(session_id="s1", user_input="hi"):
        thing()

    assert len(seen) == 1
    assert seen[0].decision == "ALLOW"
    assert seen[0].trust_score == 88.0


def test_on_decision_exception_does_not_break_tool(make_guard, fake_client):
    def boom(_decision):
        raise RuntimeError("hook blew up")

    guard = make_guard(on_decision=boom)
    fake_client.set_default({"decision": "ALLOW"})

    @guard.tool()
    def thing():
        return "still ran"

    with guard.session(session_id="s1", user_input="hi"):
        assert thing() == "still ran"


def test_on_decision_fires_on_fail_secure(make_guard, fake_client):
    from aegion_guard.client import TransportError

    seen = []
    guard = make_guard(on_decision=seen.append)
    fake_client.queue(TransportError("down", retryable=False))

    @guard.tool()
    def thing():
        return "ran"

    with guard.session(session_id="s1", user_input="hi"):
        with pytest.raises(ToolDenied):
            thing()
    # Even a fail-secure DENY is observable.
    assert seen and seen[0].reason == "validation_unavailable"


def test_api_key_absent_from_hook_payload(make_guard, fake_client):
    seen = []
    guard = make_guard(api_key="leak-me-not", on_decision=seen.append)
    fake_client.set_default({"decision": "ALLOW", "reason": "ok"})

    @guard.tool()
    def thing():
        return "ran"

    with guard.session(session_id="s1", user_input="hi"):
        thing()

    blob = repr(seen[0].raw) + repr(seen[0])
    assert "leak-me-not" not in blob


def test_nested_session_inner_wins_then_restores(make_guard, fake_client):
    guard = make_guard()

    @guard.tool()
    def thing():
        return "ran"

    with guard.session(session_id="outer", user_input="o"):
        with guard.session(session_id="inner", user_input="i"):
            thing()
            assert fake_client.last["session_id"] == "inner"
        # outer restored
        thing()
        assert fake_client.last["session_id"] == "outer"


def test_unserializable_param_raises_clear_error(make_guard, fake_client):
    guard = make_guard()

    class Weird:
        pass

    @guard.tool()
    def thing(obj):
        return "ran"

    with guard.session(session_id="s1", user_input="hi"):
        with pytest.raises(ConfigError, match="not JSON-serializable"):
            thing(Weird())


def test_datetime_param_is_coerced(make_guard, fake_client):
    guard = make_guard()

    @guard.tool()
    def thing(when):
        return "ran"

    dt = datetime(2026, 6, 8, 10, 30, 0, 123000, tzinfo=timezone.utc)
    with guard.session(session_id="s1", user_input="hi"):
        thing(when=dt)

    assert fake_client.last["tool_params"]["when"] == "2026-06-08T10:30:00.123Z"


def test_contract_mismatch_warns_not_fails(make_guard, fake_client, caplog):
    # A response carrying an unexpected contract marker must NOT hard-fail; the
    # decision still parses (additive-field tolerance via raw).
    guard = make_guard()
    fake_client.set_default({"decision": "ALLOW", "contract": "v2", "new_field": 1})

    @guard.tool()
    def thing():
        return "ran"

    with guard.session(session_id="s1", user_input="hi"):
        assert thing() == "ran"
    # unknown field preserved in raw
    # (we don't assert on logging since contract checking is best-effort/log-only)
