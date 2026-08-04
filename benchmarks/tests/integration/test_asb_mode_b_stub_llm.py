"""Integration test for ASB Mode B loop with stubbed LLM and GuardClient (LLD 41 §6, WS-F)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

ASB_REPO_PATH = Path("/Users/ruchikkachaudhary/closed-source/ASB")
if str(ASB_REPO_PATH) not in sys.path:
    sys.path.insert(0, str(ASB_REPO_PATH))

from benchmarks.adapters.asb.agent import SentraGuardedReactAgent
from benchmarks.core.attribution import extract_attribution
from pyopenagi.agents.react_agent_attack import ReactAgentAttack


def test_asb_mode_b_stub_llm_dpi_and_mp(monkeypatch):
    """Run DPI episode and MP episode through SentraGuardedReactAgent against a stubbed client."""
    agent = SentraGuardedReactAgent.__new__(SentraGuardedReactAgent)
    agent.session_id = "asb_ep_001"

    # Stub GuardClient
    guard_client = MagicMock()

    def mock_validate(tool_name, tool_params, session_id):
        dec = MagicMock()
        if tool_name == "system_command":
            dec.allowed = False
            dec.reason = "CEDAR_DENY_UNAUTHORIZED_SYSTEM_COMMAND"
            dec.source = "cedar"
        else:
            dec.allowed = True
            dec.reason = None
            dec.source = "none"
        return dec

    guard_client.validate.side_effect = mock_validate
    agent.guard_client = guard_client

    # Stub super().call_tools
    def mock_super_call_tools(self, allowed_calls, final_stage=False):
        return ["I call allowed tools"], ["Executed allowed tool"], True

    monkeypatch.setattr(ReactAgentAttack, "call_tools", mock_super_call_tools)

    tool_calls = [
        {"name": "file_reader", "parameters": {"path": "doc.txt"}},
        {"name": "system_command", "parameters": {"cmd": "rm -rf /"}},
    ]

    actions, observations, success = agent.call_tools(tool_calls)

    assert len(observations) == 2
    assert observations[0] == "Executed allowed tool"
    assert "CEDAR_DENY_UNAUTHORIZED_SYSTEM_COMMAND" in observations[1]

    # Test extract_attribution
    val_result = MagicMock()
    val_result.should_deny = True
    val_result.violation_type = "CEDAR_DENY"
    val_result.reason = "CEDAR_DENY"

    comb_signal = MagicMock()
    comb_signal.allowed = False
    comb_signal.metadata = {"winning_source": "cedar"}
    comb_signal.reason = "CEDAR_DENY"

    attr = extract_attribution(
        (val_result, [comb_signal]),
        session={"trust_score": 85.0, "quarantine_status": "ok"},
    )

    assert attr["deciding_source"] in ("cedar", "combined")
    assert attr["trust_score_after"] == 85.0
    assert attr["quarantined"] is False
