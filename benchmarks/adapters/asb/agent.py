"""Sentra guarded ReactAgentAttack subclass for ASB (LLD 41 §6.2, WS-F milestone F1/F2)."""

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ASB_REPO_PATH = Path("/Users/ruchikkachaudhary/closed-source/ASB")
if str(ASB_REPO_PATH) not in sys.path:
    sys.path.insert(0, str(ASB_REPO_PATH))

from pyopenagi.agents.react_agent_attack import ReactAgentAttack


class SentraGuardedReactAgent(ReactAgentAttack):
    """Subclasses ReactAgentAttack to enforce Sentra GuardClient policy on tool execution."""

    def __init__(self, *args: Any, guard_client: Any = None, session_id: Optional[str] = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.guard_client = guard_client
        self.session_id = session_id or "asb_default_session"

    def call_tools(self, tool_calls: Any, final_stage: bool = False) -> Tuple[List[str], List[str], bool]:
        """Override call_tools to validate each tool call against GuardClient before dispatch."""
        normalized_calls = self.normalize_tool_calls(tool_calls)
        if not normalized_calls or self.guard_client is None:
            return super().call_tools(tool_calls, final_stage=final_stage)

        denial_map: Dict[int, str] = {}
        allowed_subset: List[Dict[str, Any]] = []

        for idx, call in enumerate(normalized_calls):
            tool_name = call.get("name")
            tool_params = call.get("parameters") if isinstance(call.get("parameters"), dict) else {}

            if not tool_name:
                continue

            dec = self.guard_client.validate(
                tool_name=tool_name,
                tool_params=tool_params,
                session_id=self.session_id,
            )

            if dec.allowed:
                allowed_subset.append({"name": tool_name, "parameters": tool_params})
            else:
                reason_str = dec.reason or "Policy violation"
                denial_map[idx] = f"Tool call '{tool_name}' denied by Sentra Guard: {reason_str}"

        # If no calls were denied, pass through directly
        if not denial_map:
            return super().call_tools(tool_calls, final_stage=final_stage)

        # If ALL calls were denied, skip super().call_tools entirely
        if len(denial_map) == len(normalized_calls):
            actions = ["I fail to call any tools."]
            observations = [denial_map[i] for i in range(len(normalized_calls))]
            return actions, observations, False

        # Partially denied: execute allowed calls through super().call_tools
        actions_sub, obs_sub, success_sub = super().call_tools(allowed_subset, final_stage=final_stage)

        # Splice observations in original order
        spliced_observations: List[str] = []
        obs_idx = 0
        for i in range(len(normalized_calls)):
            if i in denial_map:
                spliced_observations.append(denial_map[i])
            else:
                if obs_idx < len(obs_sub):
                    spliced_observations.append(obs_sub[obs_idx])
                    obs_idx += 1
                else:
                    spliced_observations.append("Allowed call executed.")

        return actions_sub, spliced_observations, success_sub
