from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class Platform(str, Enum):
    BEDROCK = "bedrock"
    AZURE_FOUNDRY = "azure_foundry"
    VERTEX_AI = "vertex_ai"


@dataclass
class ToolCall:
    """A single tool invocation surfaced by an agent, normalized across clouds."""

    tool_name: str
    tool_params: dict[str, Any]
    invoked_at: datetime
    raw_event: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationContext:
    """Per-invocation context the connector forwards to /v1/validate."""

    request_id: str
    session_id: str
    agent_id: str
    user_input: str
    platform: Platform
    cloud_region: str
    operation_type: str = "READ"  # READ | WRITE — surfaced to the policy engine


@dataclass
class AgentResponse:
    """Normalized response from invoke_agent, regardless of cloud."""

    response: str
    decision: str  # ALLOW | DENY | ERROR
    validation_result: Optional[dict[str, Any]]
    latency_ms: int
    trace: dict[str, Any]
    error: Optional[str]
    platform: Platform
    cloud_region: str


@dataclass
class AuditEvent:
    """A single entry in a session's cross-cloud audit timeline."""

    timestamp: datetime
    agent_id: str
    platform: Platform
    cloud_region: str
    event_type: str  # tool_call | validation | quarantine | response
    payload: dict[str, Any]


@dataclass
class SessionSummary:
    """Cloud-agnostic session listing entry."""

    session_id: str
    agent_id: str
    platform: Platform
    # Optional because some cloud session APIs omit timestamps; better to
    # surface None than fabricate a fresh utcnow() that mixes silently into
    # a list of real historical timestamps (Issue #5, WS15 M1 review).
    started_at: Optional[datetime] = None
    last_active_at: Optional[datetime] = None
