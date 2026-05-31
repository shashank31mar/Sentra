"""AWS Bedrock implementation of AgentConnector."""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any, ClassVar, Optional

import boto3

from ..base.agent_connector import AgentConnector
from ..base.exceptions import AgentInvocationError
from ..base.models import AgentResponse, AuditEvent, Platform, SessionSummary, ToolCall
from ..base.signals_client import SignalsClient
from .event_translator import parse_guardrail_trace

logger = logging.getLogger(__name__)

# Edge-signal source per LLD 17 §4 taxonomy. Locked here so the Bedrock
# connector and the controller's combiner stay in sync.
_BEDROCK_GUARDRAIL_SOURCE = "bedrock_guardrail"
_BEDROCK_GUARDRAIL_PRIORITY = 40


class BedrockConnector(AgentConnector):
    """Invokes AWS Bedrock Agents and normalizes the response.

    Sentra validation happens inside the Action Group Lambda (see
    Sentra/lambda/bedrock_agent_actions/index.py), not here. This connector
    invokes the agent, streams the response, and extracts validation results
    from the guardrail trace so the dashboard can compare them with other
    clouds uniformly.
    """

    platform: ClassVar[Platform] = Platform.BEDROCK
    # cloud_region is per-instance (see ABC comment); set in __init__ below.

    def __init__(
        self,
        region_name: str = "us-east-1",
        signals_client: Optional[SignalsClient] = None,
    ) -> None:
        self.cloud_region = region_name
        self.bedrock_agent_runtime = boto3.client(
            service_name="bedrock-agent-runtime",
            region_name=region_name,
        )
        # Signals client for the post-invoke bedrock_guardrail emission
        # (Workstream 17 / LLD 17 §9.1). Injectable for tests; defaults to a
        # fresh client reading SENTRA_API_ENDPOINT / SECURITY_CONTROLLER_URL.
        self._signals_client = signals_client or SignalsClient()
        logger.info("BedrockConnector initialized for region: %s", region_name)

    def _resolve_agent_alias_id(self, cloud_specific_kwargs: dict[str, Any]) -> str:
        """Resolve agent_alias_id from kwargs or env, fail loud if neither set.

        Removes the legacy `TSTALIASID` silent default that returned 0 sessions
        against any real prod agent and produced confusing empty results in the
        dashboard (Workstream 15 M1 review, Issue #3).
        """
        alias = cloud_specific_kwargs.get("agent_alias_id") or os.environ.get(
            "BEDROCK_AGENT_ALIAS_ID"
        )
        if not alias:
            raise AgentInvocationError(
                "agent_alias_id is required. Pass via cloud_specific_kwargs "
                "(`agent_alias_id=<alias>`) or set the BEDROCK_AGENT_ALIAS_ID env "
                "var. The previous `TSTALIASID` default silently broke against "
                "real Bedrock prod agents."
            )
        return alias

    def invoke_agent(
        self,
        agent_id: str,
        session_id: str,
        user_message: str,
        enable_trace: bool = True,
        **cloud_specific_kwargs: Any,
    ) -> AgentResponse:
        agent_alias_id = self._resolve_agent_alias_id(cloud_specific_kwargs)
        start_time = time.time()

        # Workstream 17 / LLD 17 §9.1 — request_id is the connector's correlation
        # key. Threaded via Bedrock sessionAttributes so the Action Group Lambda
        # echoes the same id into /v1/validate; the post-invoke signal POST
        # below uses the same id so the controller's combiner sees both rows
        # under one request_id. Caller-provided value wins so the dashboard
        # runner can pick the id that matches its per-step row.
        request_id = cloud_specific_kwargs.get("request_id") or f"bedrock-{uuid.uuid4().hex[:12]}"

        try:
            response = self.bedrock_agent_runtime.invoke_agent(
                agentId=agent_id,
                agentAliasId=agent_alias_id,
                sessionId=session_id,
                inputText=user_message,
                enableTrace=enable_trace,
                sessionState={
                    "sessionAttributes": {"sentra_request_id": request_id},
                },
            )

            event_stream = response.get("completion", [])
            full_response = ""
            validation_result = None
            trace_data: dict[str, Any] = {}

            for event in event_stream:
                if "chunk" in event:
                    chunk = event["chunk"]
                    if "bytes" in chunk:
                        full_response += chunk["bytes"].decode("utf-8")

                if "trace" in event and enable_trace:
                    trace = event["trace"].get("trace", {})

                    if "orchestrationTrace" in trace:
                        trace_data["orchestration"] = trace["orchestrationTrace"]

                    if "guardrailTrace" in trace:
                        validation_result = parse_guardrail_trace(trace["guardrailTrace"])

                        if validation_result and validation_result.get("decision") == "DENY":
                            latency_ms = int((time.time() - start_time) * 1000)
                            # Post the edge signal BEFORE returning so the
                            # combiner sees it on the next /decisions read.
                            self._post_guardrail_signal(
                                session_id=session_id,
                                request_id=request_id,
                                agent_id=agent_id,
                                decision="DENY",
                                reason=validation_result.get("reason"),
                            )
                            return AgentResponse(
                                response=validation_result.get(
                                    "reason", "⚠️ Request blocked by security policy"
                                ),
                                decision="DENY",
                                validation_result=validation_result,
                                latency_ms=latency_ms,
                                trace=trace_data,
                                error=None,
                                platform=self.platform,
                                cloud_region=self.cloud_region,
                            )

            latency_ms = int((time.time() - start_time) * 1000)
            # Symmetric emission (LLD 17 §4): post ALLOW so an absence of signal
            # can't be misread as "guardrail wasn't consulted". The DENY path
            # already early-returned above (line ~124), so reaching here means
            # the guardrail produced no DENY trace — emit ALLOW unconditionally.
            self._post_guardrail_signal(
                session_id=session_id,
                request_id=request_id,
                agent_id=agent_id,
                decision="ALLOW",
                reason=None,
            )
            return AgentResponse(
                response=full_response,
                decision="ALLOW",
                validation_result=validation_result,
                latency_ms=latency_ms,
                trace=trace_data,
                error=None,
                platform=self.platform,
                cloud_region=self.cloud_region,
            )

        except Exception as exc:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.error("Bedrock agent invocation failed: %s", exc)
            return AgentResponse(
                response=f"⚠️ Error invoking agent: {exc}",
                decision="ERROR",
                validation_result=None,
                latency_ms=latency_ms,
                trace={},
                error=str(exc),
                platform=self.platform,
                cloud_region=self.cloud_region,
            )

    def _post_guardrail_signal(
        self,
        session_id: str,
        request_id: str,
        agent_id: str,
        decision: str,
        reason: Optional[str],
    ) -> None:
        """Edge signal emission for bedrock_guardrail — LLD 17 §9.1.4.

        Best-effort. Never raises. A missed signal degrades the dashboard
        expander but doesn't affect the verdict — Sentra's signals already
        landed during the Action Group Lambda's /v1/validate call.
        """
        try:
            self._signals_client.post_signal(
                session_id=session_id,
                request_id=request_id,
                source=_BEDROCK_GUARDRAIL_SOURCE,
                decision=decision,
                reason=reason,
                priority=_BEDROCK_GUARDRAIL_PRIORITY,
                agent_id=agent_id,
                platform=self.platform.value,
                cloud_region=self.cloud_region,
            )
        except Exception as exc:  # noqa: BLE001 — defensive belt-and-braces
            logger.warning("bedrock_guardrail signal post failed: %s", exc)

    def parse_tool_calls(self, raw_response: Any) -> list[ToolCall]:
        """Tool calls in Bedrock arrive inside orchestrationTrace.invocationInput.
        For Phase 1 the connector does not synthesize these from the stream — the
        Action Group Lambda is the authoritative source of tool-call audit events.
        """
        # Issue #2: surface the stub loudly so a factory consumer building a
        # cross-cloud audit timeline doesn't silently miss Bedrock events.
        logger.warning(
            "BedrockConnector.parse_tool_calls is a Phase-1 stub returning []. "
            "Query the Sentra audit API directly via /v1/logs?session_id=..."
        )
        return []

    def get_audit_trace(self, session_id: str) -> list[AuditEvent]:
        """Audit events for Bedrock live in CloudWatch + the Sentra audit log.
        Phase 1: callers should query the Sentra audit API directly. This method
        is a placeholder so the AgentConnector contract is satisfied.
        """
        # Issue #2: same as parse_tool_calls — explicit warning so callers don't
        # treat an empty list as "no events" when it actually means "not queried".
        logger.warning(
            "BedrockConnector.get_audit_trace is a Phase-1 stub returning []. "
            "Query the Sentra audit API directly via /v1/logs?session_id=%s",
            session_id,
        )
        return []

    def list_sessions(
        self, agent_id: str, **cloud_specific_kwargs: Any
    ) -> list[SessionSummary]:
        agent_alias_id = self._resolve_agent_alias_id(cloud_specific_kwargs)
        try:
            response = self.bedrock_agent_runtime.list_sessions(
                agentId=agent_id,
                agentAliasId=agent_alias_id,
            )
        except Exception as exc:
            logger.error("Failed to list Bedrock sessions: %s", exc)
            raise AgentInvocationError(str(exc)) from exc

        # Issue #5: pass None (not utcnow()) when Bedrock omits a timestamp so
        # the dashboard can distinguish "unknown" from "just now".
        return [
            SessionSummary(
                session_id=s.get("sessionId", ""),
                agent_id=agent_id,
                platform=self.platform,
                started_at=s.get("createdAt"),
                last_active_at=s.get("lastUpdatedAt"),
            )
            for s in response.get("sessionSummaries", [])
        ]

    def delete_session(
        self, agent_id: str, session_id: str, **cloud_specific_kwargs: Any
    ) -> bool:
        agent_alias_id = self._resolve_agent_alias_id(cloud_specific_kwargs)
        try:
            self.bedrock_agent_runtime.delete_session(
                agentId=agent_id,
                agentAliasId=agent_alias_id,
                sessionId=session_id,
            )
            return True
        except Exception as exc:
            logger.error("Failed to delete Bedrock session %s: %s", session_id, exc)
            return False
