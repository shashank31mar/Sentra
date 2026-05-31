from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from .models import AgentResponse, AuditEvent, Platform, SessionSummary, ToolCall


class AgentConnector(ABC):
    """Contract every cross-cloud agent connector must implement.

    The security controller's /v1/validate endpoint is already platform-agnostic.
    A connector is the thin adapter that:
      1. Invokes a native cloud agent (Bedrock / Azure Foundry / Vertex)
      2. Normalizes the response into AgentResponse so the dashboard and
         demo orchestrator can compare results across clouds uniformly.

    The *interceptor* deployed inside the foreign cloud (Lambda, Azure Function,
    Cloud Run) is not an AgentConnector — it lives inside the foreign cloud's
    runtime. It only shares the translation contract: foreign tool-call event →
    ValidationRequest → POST /v1/validate → foreign response.
    """

    platform: ClassVar[Platform]
    # NOT ClassVar — concrete connectors set this per-instance in __init__ because
    # the same connector class can serve multiple regions (e.g., BedrockConnector
    # for us-east-1 vs eu-west-1). Class-level access (`BedrockConnector.cloud_region`)
    # is intentionally unsupported; route via instances or the dashboard factory.
    cloud_region: str

    @abstractmethod
    def invoke_agent(
        self,
        agent_id: str,
        session_id: str,
        user_message: str,
        enable_trace: bool = True,
        **cloud_specific_kwargs: Any,
    ) -> AgentResponse:
        """Invoke a native cloud agent and return a normalized AgentResponse.

        Cloud-specific arguments (e.g., Bedrock's agent_alias_id) flow through
        cloud_specific_kwargs without polluting the cross-cloud contract.
        """

    @abstractmethod
    def parse_tool_calls(self, raw_response: Any) -> list[ToolCall]:
        """Extract tool calls from a native cloud response into normalized ToolCall objects."""

    @abstractmethod
    def get_audit_trace(self, session_id: str) -> list[AuditEvent]:
        """Return the cross-cloud-comparable audit trace for a session."""

    @abstractmethod
    def list_sessions(self, agent_id: str, **cloud_specific_kwargs: Any) -> list[SessionSummary]:
        """List active sessions for an agent on this platform."""

    @abstractmethod
    def delete_session(
        self, agent_id: str, session_id: str, **cloud_specific_kwargs: Any
    ) -> bool:
        """Delete a session on this platform; return True on success."""
