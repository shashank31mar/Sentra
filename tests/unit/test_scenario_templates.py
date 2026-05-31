"""Unit tests for the scenario template substituter — Workstream 18 M2.

LLD 18 §4.3 / scenario_templates.py:
  - Known tokens substitute from the registry
  - Unknown tokens log WARN and leave the placeholder
  - {request_id} / {session_id} resolve from runtime context
  - substitute_dict applies to string values only
  - find_tokens enumerates token references (for the M3 scenario validator)
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_PATH = REPO_ROOT / "src" / "dashboard" / "components" / "scenario_templates.py"


def _load_templates():
    spec = importlib.util.spec_from_file_location("scenario_templates_under_test", TEMPLATES_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["scenario_templates_under_test"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tpl():
    return _load_templates()


# ---------------------------------------------------------------------------
# substitute() — single token
# ---------------------------------------------------------------------------


def test_substitute_known_rand_state(tpl):
    out = tpl.substitute("state={rand.state}")
    assert out.startswith("state=")
    assert out != "state={rand.state}"
    # Must be one of the curated US states
    state = out[len("state="):]
    assert state in tpl._US_STATES


def test_substitute_rand_uuid_is_8_hex_chars(tpl):
    out = tpl.substitute("id={rand.uuid}")
    suffix = out[len("id="):]
    assert len(suffix) == 8
    assert all(c in "0123456789abcdef" for c in suffix)


def test_substitute_rand_customer_id_format(tpl):
    out = tpl.substitute("{rand.customer_id}")
    assert out.startswith("C")
    assert len(out) == 5  # C0042 shape
    assert out[1:].isdigit()


def test_substitute_unknown_token_leaves_placeholder(tpl, caplog):
    out = tpl.substitute("hello {rand.unknown_made_up}")
    assert out == "hello {rand.unknown_made_up}"
    # Should have logged a WARN
    assert any("unknown token" in rec.message for rec in caplog.records)


def test_substitute_no_tokens_returns_unchanged(tpl):
    assert tpl.substitute("plain string") == "plain string"
    assert tpl.substitute("") == ""
    assert tpl.substitute("no braces here") == "no braces here"


def test_substitute_none_text_returns_none(tpl):
    # Defensive: substitute(None) shouldn't crash
    assert tpl.substitute(None) is None
    assert tpl.substitute("") == ""


def test_substitute_request_id_substituted(tpl):
    out = tpl.substitute("req={request_id}", request_id="rid-abc")
    assert out == "req=rid-abc"


def test_substitute_request_id_missing_leaves_placeholder(tpl, caplog):
    out = tpl.substitute("req={request_id}", request_id=None)
    assert out == "req={request_id}"
    assert any("no request_id" in rec.message for rec in caplog.records)


def test_substitute_session_id_substituted(tpl):
    out = tpl.substitute("sess={session_id}", session_id="sess-xyz")
    assert out == "sess=sess-xyz"


def test_substitute_two_tokens_in_one_string(tpl):
    out = tpl.substitute(
        "req={request_id} sess={session_id}",
        request_id="rid", session_id="sid",
    )
    assert out == "req=rid sess=sid"


def test_substitute_same_random_token_twice_gets_different_values(tpl):
    # The substituter rolls per-call. Two {rand.uuid} occurrences in one string
    # do two independent rolls — by design.
    out = tpl.substitute("a={rand.uuid} b={rand.uuid}")
    parts = out.split()
    a_val = parts[0][len("a="):]
    b_val = parts[1][len("b="):]
    # Statistically equal collisions are 1 in 4 billion for 8-hex; safe to assert.
    assert a_val != b_val


def test_substitute_alias_state_equals_us_state(tpl):
    # {rand.state} and {rand.us_state} share the same generator.
    # Just verify they both produce valid state codes.
    s1 = tpl.substitute("{rand.state}")
    s2 = tpl.substitute("{rand.us_state}")
    assert s1 in tpl._US_STATES
    assert s2 in tpl._US_STATES


# ---------------------------------------------------------------------------
# substitute_dict() — dict-level helper
# ---------------------------------------------------------------------------


def test_substitute_dict_string_values_substituted(tpl):
    d = {"state": "{rand.state}", "id": "{rand.customer_id}"}
    out = tpl.substitute_dict(d)
    assert out["state"] in tpl._US_STATES
    assert out["id"].startswith("C")


def test_substitute_dict_non_string_values_passthrough(tpl):
    d = {"amount": 50.0, "count": 10, "flag": True, "name": "{rand.state}"}
    out = tpl.substitute_dict(d)
    assert out["amount"] == 50.0
    assert out["count"] == 10
    assert out["flag"] is True
    assert out["name"] in tpl._US_STATES


def test_substitute_dict_empty_returns_empty(tpl):
    assert tpl.substitute_dict({}) == {}
    assert tpl.substitute_dict(None) is None


def test_substitute_dict_threads_request_session_ids(tpl):
    d = {"x": "{request_id}", "y": "{session_id}"}
    out = tpl.substitute_dict(d, request_id="r1", session_id="s1")
    assert out == {"x": "r1", "y": "s1"}


# ---------------------------------------------------------------------------
# find_tokens() — used by M3 scenario validator
# ---------------------------------------------------------------------------


def test_find_tokens_lists_all_token_references(tpl):
    tokens = tpl.find_tokens("state={rand.state} id={rand.customer_id} req={request_id}")
    assert tokens == ["rand.state", "rand.customer_id", "request_id"]


def test_find_tokens_empty_string(tpl):
    assert tpl.find_tokens("") == []
    assert tpl.find_tokens(None) == []


def test_find_tokens_no_braces(tpl):
    assert tpl.find_tokens("plain text") == []


def test_find_tokens_includes_unknowns(tpl):
    # find_tokens is registry-blind; it reports every token-shaped match.
    # That's intentional — the validator uses this to detect unknown tokens.
    tokens = tpl.find_tokens("{rand.state} {rand.gibberish}")
    assert "rand.state" in tokens
    assert "rand.gibberish" in tokens


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_substitute_handles_unclosed_brace(tpl):
    # `{rand.state` without closing brace doesn't match the token regex.
    # The substituter leaves the string untouched.
    out = tpl.substitute("{rand.state")
    assert out == "{rand.state"


def test_substitute_handles_nested_brace(tpl):
    # `{rand.{nested}}` is invalid; regex doesn't match nested braces.
    out = tpl.substitute("{rand.{state}}")
    # Inner `{state}` (an unknown token) matches; outer `{rand.` stays.
    # Verify substituter doesn't crash on this edge case.
    assert isinstance(out, str)


def test_list_known_tokens_includes_runtime_tokens(tpl):
    known = tpl.list_known_tokens()
    assert "request_id" in known
    assert "session_id" in known
    assert "rand.state" in known
    assert "rand.customer_id" in known
