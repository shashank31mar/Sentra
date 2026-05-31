"""Backward-compatibility shim around the new BedrockConnector.

The implementation now lives in `src/connectors/bedrock/`. This module preserves
the original `BedrockAgentCaller` dict-returning API so existing dashboard code
(`dashboard/tabs/agents_tab.py`) keeps working unchanged while the rest of the
codebase migrates to the cross-cloud `AgentConnector` interface.

Reference: docs/bedrock-agent-architecture-clarification.md, LLD 09 §2.5.4
"""

from __future__ import annotations

import logging
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

# Walk up to whichever ancestor actually contains the `connectors/` package so
# this works in both layouts: local dev (<repo>/src/connectors/) and the
# dashboard container (/app/connectors/, copied in by docker/dashboard/Dockerfile).
def _find_connectors_root() -> Path:
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        if (ancestor / "connectors").exists():
            return ancestor
    # Fall back to the local-dev assumption; the import below will fail loudly
    # if connectors really isn't on disk anywhere.
    return here.parents[2]


_CONNECTORS_ROOT = _find_connectors_root()
if str(_CONNECTORS_ROOT) not in sys.path:
    sys.path.insert(0, str(_CONNECTORS_ROOT))

from connectors.bedrock import BedrockConnector  # noqa: E402

logger = logging.getLogger(__name__)


class BedrockAgentCaller:
    """Thin wrapper that preserves the legacy dict-returning API.

    All new code should depend on `connectors.bedrock.BedrockConnector` directly.
    """

    def __init__(self, region_name: str = "us-east-1") -> None:
        self._connector = BedrockConnector(region_name=region_name)
        self.region_name = region_name

    def invoke_agent(
        self,
        agent_id: str,
        agent_alias_id: str,
        session_id: str,
        user_message: str,
        enable_trace: bool = True,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        # Workstream 17 / LLD 17 §9.1 — when the cross-cloud runner originates
        # a request_id, forward it so BedrockConnector threads it via
        # sessionAttributes. Lambda echoes; Sentra signals correlate.
        kwargs: dict[str, Any] = {"agent_alias_id": agent_alias_id}
        if request_id:
            kwargs["request_id"] = request_id
        result = self._connector.invoke_agent(
            agent_id=agent_id,
            session_id=session_id,
            user_message=user_message,
            enable_trace=enable_trace,
            **kwargs,
        )
        payload = asdict(result)
        # AgentResponse.platform is a Platform enum; serialize to its string value.
        payload["platform"] = result.platform.value
        return payload

    def list_agent_sessions(self, agent_id: str, agent_alias_id: str) -> list:
        try:
            sessions = self._connector.list_sessions(
                agent_id=agent_id, agent_alias_id=agent_alias_id
            )
        except Exception as exc:
            logger.error("Failed to list agent sessions: %s", exc)
            return []
        return [asdict(s) for s in sessions]

    def delete_agent_session(
        self, agent_id: str, agent_alias_id: str, session_id: str
    ) -> bool:
        return self._connector.delete_session(
            agent_id=agent_id, session_id=session_id, agent_alias_id=agent_alias_id
        )
