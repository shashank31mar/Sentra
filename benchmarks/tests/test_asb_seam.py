"""Unit tests for ASB seam fingerprint and SentraGuardedReactAgent (LLD 41 §6.3, WS-F milestone F1)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ASB_REPO_PATH = Path("/Users/ruchikkachaudhary/closed-source/ASB")
if str(ASB_REPO_PATH) not in sys.path:
    sys.path.insert(0, str(ASB_REPO_PATH))

from benchmarks.adapters.asb.agent import SentraGuardedReactAgent
from benchmarks.adapters.asb.seam import EXPECTED_SEAM_SHA256, SeamDrift, verify_seam
from pyopenagi.agents.react_agent_attack import ReactAgentAttack


def test_seam_fingerprint_matches_pinned():
    digest = verify_seam()
    assert digest == EXPECTED_SEAM_SHA256


def test_seam_drift_raises_at_startup(monkeypatch):
    from pyopenagi.agents import react_agent_attack

    original_src = react_agent_attack.ReactAgentAttack.call_tools

    def modified_call_tools(self, tool_calls, final_stage=False):
        return [], [], True

    monkeypatch.setattr(react_agent_attack.ReactAgentAttack, "call_tools", modified_call_tools)

    with pytest.raises(SeamDrift) as exc_info:
        verify_seam()
    assert "ASB call_tools source text changed" in str(exc_info.value)


@pytest.mark.parametrize(
    "tool_call_input,expected_name,expected_params",
    [
        ("tool_a", "tool_a", None),
        ({"name": "tool_b", "parameters": {"x": 1}}, "tool_b", {"x": 1}),
        ({"tool_name": "tool_c", "parameters": {"y": 2}}, "tool_c", {"y": 2}),
        ({"function": {"name": "tool_d", "arguments": {"z": 3}}}, "tool_d", {"z": 3}),
        ({"tool_use": ["tool_e"]}, "tool_e", None),
    ],
)
def test_normalize_tool_calls_is_reused_not_reimplemented(tool_call_input, expected_name, expected_params):
    # Instantiate agent without initializing full LLM/task infrastructure
    agent = SentraGuardedReactAgent.__new__(SentraGuardedReactAgent)
    res = agent.normalize_tool_calls(tool_call_input)
    assert len(res) == 1
    assert res[0]["name"] == expected_name
    assert res[0]["parameters"] == expected_params


def test_denial_splice_preserves_original_order(monkeypatch):
    agent = SentraGuardedReactAgent.__new__(SentraGuardedReactAgent)
    agent.session_id = "test_session"
    agent.guard_client = MagicMock()

    # Stub guard_client decisions: call 0 allowed, call 1 denied, call 2 allowed
    def mock_validate(tool_name, tool_params, session_id):
        dec = MagicMock()
        if tool_name == "tool_1":
            dec.allowed = False
            dec.reason = "quarantined"
        else:
            dec.allowed = True
            dec.reason = None
        return dec

    agent.guard_client.validate.side_effect = mock_validate

    # Stub super().call_tools
    def mock_super_call_tools(self, allowed_calls, final_stage=False):
        return ["action_0", "action_2"], ["obs_0", "obs_2"], True

    monkeypatch.setattr(ReactAgentAttack, "call_tools", mock_super_call_tools)

    tool_calls = [
        {"name": "tool_0", "parameters": {}},
        {"name": "tool_1", "parameters": {}},
        {"name": "tool_2", "parameters": {}},
    ]

    actions, observations, success = agent.call_tools(tool_calls)

    assert len(observations) == 3
    assert observations[0] == "obs_0"
    assert "quarantined" in observations[1]
    assert observations[2] == "obs_2"


def test_all_denied_skips_super_call(monkeypatch):
    agent = SentraGuardedReactAgent.__new__(SentraGuardedReactAgent)
    agent.session_id = "test_session"
    agent.guard_client = MagicMock()

    dec = MagicMock()
    dec.allowed = False
    dec.reason = "all_denied"
    agent.guard_client.validate.return_value = dec

    super_called = False

    def mock_super_call_tools(self, allowed_calls, final_stage=False):
        nonlocal super_called
        super_called = True
        return [], [], True

    monkeypatch.setattr(ReactAgentAttack, "call_tools", mock_super_call_tools)

    tool_calls = [{"name": "t1"}, {"name": "t2"}]
    actions, obs, success = agent.call_tools(tool_calls)

    assert super_called is False
    assert success is False
    assert len(obs) == 2
    assert "all_denied" in obs[0]
    assert "all_denied" in obs[1]


def test_denial_observation_carries_real_reason():
    agent = SentraGuardedReactAgent.__new__(SentraGuardedReactAgent)
    agent.session_id = "test_session"
    agent.guard_client = MagicMock()

    dec = MagicMock()
    dec.allowed = False
    dec.reason = "CEDAR_DENY_UNAUTHORIZED_TOOL"
    agent.guard_client.validate.return_value = dec

    actions, obs, success = agent.call_tools([{"name": "unauthorized_tool"}])
    assert "CEDAR_DENY_UNAUTHORIZED_TOOL" in obs[0]
