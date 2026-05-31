"""Azure AI Foundry implementation of AgentConnector — Workstream 15 M3, Task 3.3.

Architecture (LLD 15 §2.1, §7.4):

    Dashboard
        | invoke_agent(...)
        v
    AzureConnector (this module)
        | 1. Loads agent_spec/azure_verification_agent.json (system prompt + tools)
        | 2. Invokes gpt-4o-mini on Azure OpenAI with function-calling tools
        | 3. For each tool_call the model emits, POSTs to the Function App's
        |    /api/tool/{tool_name} (which validates via Sentra before executing)
        | 4. Feeds tool results back to gpt-4o-mini, repeats until model finishes
        | 5. Normalizes into AgentResponse for the dashboard
        v
    Returns AgentResponse(decision="ALLOW"|"DENY", platform="azure_foundry", ...)

Security validation happens INSIDE the Function App tool_interceptor — this
connector just orchestrates the model + tool dispatch. The Sentra controller
sees one validation request per tool call regardless of where the tool was
invoked.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar, Optional

from ..base.agent_connector import AgentConnector
from ..base.exceptions import AgentInvocationError
from ..base.signals_client import SignalsClient
from ..base.models import (
    AgentResponse,
    AuditEvent,
    Platform,
    SessionSummary,
    ToolCall,
)

logger = logging.getLogger(__name__)


# Resolve the agent spec by walking ancestors until we find one that contains
# the spec file. Works in three layouts without per-env conditionals:
#   - local dev:        <repo>/src/connectors/azure_foundry/azure_connector.py
#                       -> spec at <repo>/infrastructure/azure/agent-spec/<...>.json
#   - dashboard image:  /app/connectors/azure_foundry/azure_connector.py
#                       -> spec at /app/infrastructure/azure/agent-spec/<...>.json
#                         (Dockerfile COPYs it in)
#   - Azure Function:   the Function bundles its own copy, so this resolution
#                       is not used there.
_SPEC_RELATIVE = Path("infrastructure") / "azure" / "agent-spec" / "azure_verification_agent.json"


def _resolve_spec_path() -> Path:
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        candidate = ancestor / _SPEC_RELATIVE
        if candidate.exists():
            return candidate
    # Fall back to the local-dev layout so the error message points somewhere
    # actionable if the spec genuinely isn't shipped.
    return here.parents[3] / _SPEC_RELATIVE


_SPEC_PATH = _resolve_spec_path()

# Edge-signal source per LLD 17 §4 taxonomy.
_AZURE_CONTENT_FILTER_SOURCE = "azure_content_filter"
_AZURE_CONTENT_FILTER_PRIORITY = 40


class AzureConnector(AgentConnector):
    """Invokes the Azure AI Foundry agent and normalizes the response.

    Sentra validation happens inside the Azure Function tool_interceptor (see
    Sentra/src/connectors/azure_foundry/azure_function/tool_interceptor/), not
    here. This connector loads the agent spec, drives gpt-4o-mini via Azure
    OpenAI with function-calling, and routes any tool_calls the model emits
    through the Function — so every tool dispatch is security-validated
    cross-cloud before execution.

    Config (env vars consumed):
        AZURE_OPENAI_ENDPOINT       e.g. https://aegionai-ws15-m3-openai.openai.azure.com/
        AZURE_OPENAI_API_KEY        from Azure Portal / Key Vault
        AZURE_OPENAI_DEPLOYMENT     e.g. gpt-4o-mini
        AZURE_OPENAI_API_VERSION    default 2024-08-01-preview
        AZURE_OPENAI_REGION         Azure region the deployment lives in (default: centralus)
        AZURE_FUNCTION_TOOL_URL     e.g. https://aegionai-ws15-m3-func.azurewebsites.net/api/tool
    """

    platform: ClassVar[Platform] = Platform.AZURE_FOUNDRY
    # cloud_region is per-instance (see ABC comment); defaulted in __init__ from
    # the AZURE_OPENAI_REGION env var or "centralus" if unset.

    def __init__(
        self,
        openai_endpoint: str | None = None,
        openai_api_key: str | None = None,
        openai_deployment: str | None = None,
        openai_api_version: str | None = None,
        function_tool_url: str | None = None,
        region: str | None = None,
        spec_path: Path | None = None,
        max_tool_iterations: int = 5,
        signals_client: SignalsClient | None = None,
    ):
        self.openai_endpoint = (openai_endpoint or os.environ.get("AZURE_OPENAI_ENDPOINT", "")).rstrip("/")
        self.openai_api_key = openai_api_key or os.environ.get("AZURE_OPENAI_API_KEY", "")
        self.openai_deployment = openai_deployment or os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
        self.openai_api_version = openai_api_version or os.environ.get(
            "AZURE_OPENAI_API_VERSION", "2024-08-01-preview"
        )
        self.function_tool_url = (
            function_tool_url or os.environ.get("AZURE_FUNCTION_TOOL_URL", "")
        ).rstrip("/")
        # Issue #9 (Kiro review, M4): honor an explicit region arg first so the
        # factory's YAML-derived cloud_region is actually enforced. Env var is
        # the fallback for direct-construction callers / local scripts.
        self.cloud_region = region or os.environ.get("AZURE_OPENAI_REGION", "centralus")
        self.max_tool_iterations = max_tool_iterations
        self._spec = self._load_spec(spec_path or _SPEC_PATH)
        # Signals client for the azure_content_filter edge signal emission
        # (Workstream 17 / LLD 17 §9.3). Injectable for tests; defaults
        # configured from SENTRA_API_ENDPOINT / SECURITY_CONTROLLER_URL env.
        self._signals_client = signals_client or SignalsClient()

        # Issue #13: surface missing config early so a misconfigured dashboard fails
        # at startup instead of silently DENY-ing every tool call.
        if not self.function_tool_url:
            logger.warning(
                "AzureConnector: AZURE_FUNCTION_TOOL_URL is not set — every tool "
                "call will return decision=DENY with reason 'not configured'. "
                "Set this to the Azure Function URL, e.g., "
                "https://aegionai-ws15-m3-func.azurewebsites.net/api/tool"
            )
        if not self.openai_endpoint or not self.openai_api_key:
            logger.warning(
                "AzureConnector: AZURE_OPENAI_ENDPOINT or AZURE_OPENAI_API_KEY not "
                "set — invoke_agent will return decision=ERROR."
            )

    # ------------------------------------------------------------------
    # AgentConnector contract
    # ------------------------------------------------------------------
    def invoke_agent(
        self,
        agent_id: str,
        session_id: str,
        user_message: str,
        enable_trace: bool = True,
        **cloud_specific_kwargs: Any,
    ) -> AgentResponse:
        """Run the agent on user_message until the model finishes or a tool DENYs.

        Returns an AgentResponse whose decision is:
          - ALLOW if the model finished naturally with no tool DENYs
          - DENY if any tool returned 403 from the Sentra-validated Function
          - ERROR on transport / config failure
        """
        start = time.time()
        trace: dict[str, Any] = {"iterations": [], "tool_calls": []}

        # Workstream 17 / LLD 17 §9.1 — request_id is the connector's correlation
        # key. Threaded into _call_function_tool which forwards it to the
        # Function App; the Function uses it on /v1/validate so every Sentra
        # signal correlates. The post-invoke content_filter signal also uses
        # this id.
        request_id = cloud_specific_kwargs.get("request_id") or f"azure-{uuid.uuid4().hex[:12]}"

        if agent_id != self._spec["agent_id"]:
            return self._error_response(
                f"agent_id mismatch: expected {self._spec['agent_id']}, got {agent_id}",
                start,
                trace,
            )

        if not self.openai_endpoint or not self.openai_api_key:
            return self._error_response(
                "AZURE_OPENAI_ENDPOINT or AZURE_OPENAI_API_KEY not set", start, trace
            )

        messages = [
            {"role": "system", "content": self._spec["system_prompt"]},
            {"role": "user", "content": user_message},
        ]
        tools = self._spec["tools"]

        decision = "ALLOW"
        final_text = ""
        deny_reason: str | None = None

        for iteration in range(self.max_tool_iterations):
            try:
                completion = self._chat_completion(messages, tools)
            except AzureOpenAIError as exc:
                # Distinguish content-filter rejection (security boundary fired,
                # treat as DENY with explicit source so the cross-cloud demo
                # UI can honestly label it "Azure content filter — Sentra not
                # consulted") from infra errors (treat as ERROR).
                if _is_content_filter_error(exc):
                    latency_ms = int((time.time() - start) * 1000)
                    # Workstream 17: emit the azure_content_filter signal so the
                    # combiner attributes the DENY honestly (Sentra never ran).
                    self._post_content_filter_signal(
                        session_id=session_id,
                        request_id=request_id,
                        agent_id=agent_id,
                        decision="DENY",
                        reason="azure_content_filter",
                    )
                    return AgentResponse(
                        response=(
                            "Azure OpenAI content filter blocked the prompt before it reached gpt-4o-mini. "
                            "Sentra controller was not consulted on this request."
                        ),
                        decision="DENY",
                        validation_result={
                            # The cross-cloud scenario runner keys off this exact
                            # `reason` value to attribute the DENY to Azure's CF
                            # rather than Sentra. Do not rename without updating
                            # default_azure_prompt_invoker.
                            "reason": "azure_content_filter",
                            "status_code": exc.status_code,
                            "detail": exc.body[:500],
                        },
                        latency_ms=latency_ms,
                        trace=trace,
                        error=None,
                        platform=self.platform,
                        cloud_region=self.cloud_region,
                    )
                return self._error_response(str(exc), start, trace)
            except Exception as exc:  # noqa: BLE001 — surface any transport error uniformly
                return self._error_response(f"OpenAI call failed: {exc}", start, trace)

            choice = completion["choices"][0]
            msg = choice["message"]
            finish_reason = choice.get("finish_reason", "")

            trace["iterations"].append(
                {
                    "iter": iteration,
                    "finish_reason": finish_reason,
                    "tool_calls": len(msg.get("tool_calls") or []),
                }
            )

            # Append the assistant message verbatim (must include tool_calls for tool-result framing)
            messages.append(msg)

            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                final_text = msg.get("content") or ""
                break

            # Dispatch every tool_call through the Sentra-validated Function App
            for tc in tool_calls:
                tool_name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}

                tool_result = self._call_function_tool(
                    tool_name=tool_name,
                    params=args,
                    session_id=session_id,
                    user_input=user_message,
                    request_id=request_id,
                )
                trace["tool_calls"].append(
                    {"tool_name": tool_name, "decision": tool_result.get("decision")}
                )

                if tool_result.get("decision") == "DENY":
                    decision = "DENY"
                    deny_reason = tool_result.get("reason", "denied by Sentra")
                    final_text = (
                        f"Tool {tool_name} was denied by Sentra: {deny_reason}"
                    )
                    # Feed denial back so the model can summarize for the user
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": json.dumps(tool_result),
                        }
                    )
                    break

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(tool_result.get("result", {})),
                    }
                )

            if decision == "DENY":
                # Run one more completion to let the model surface the denial in natural language
                try:
                    completion = self._chat_completion(messages, tools)
                    final_text = completion["choices"][0]["message"].get("content") or final_text
                except Exception:  # noqa: BLE001
                    pass
                break
        else:
            # only reached if the for-loop runs to completion (no `break`).
            # Issue #14: for-else runs when the loop exits via range exhaustion (not
            # via break). That means the model was still calling tools at the last
            # iteration — we never got a final assistant message. Treat as ERROR
            # rather than returning decision=ALLOW with an empty response, which
            # would silently look like a successful no-op to the dashboard.
            return self._error_response(
                f"hit max_tool_iterations={self.max_tool_iterations} without final "
                "assistant response; model may be stuck in a tool-call loop",
                start,
                trace,
            )

        latency_ms = int((time.time() - start) * 1000)
        # Symmetric emission (LLD 17 §4): the content-filter passed the prompt
        # through to gpt-4o-mini, so the edge approved. Emit ALLOW so absence
        # of signal can't be misread as "filter wasn't consulted".
        self._post_content_filter_signal(
            session_id=session_id,
            request_id=request_id,
            agent_id=agent_id,
            decision="ALLOW",
            reason=None,
        )
        return AgentResponse(
            response=final_text,
            decision=decision,
            validation_result={"reason": deny_reason} if deny_reason else None,
            latency_ms=latency_ms,
            trace=trace,
            error=None,
            platform=self.platform,
            cloud_region=self.cloud_region,
        )

    def _post_content_filter_signal(
        self,
        session_id: str,
        request_id: str,
        agent_id: str,
        decision: str,
        reason: Optional[str],
    ) -> None:
        """Edge signal emission for azure_content_filter — LLD 17 §9.3.

        Best-effort. Never raises. ALLOW on happy-path; DENY only when
        gpt-4o-mini rejected with `content_filter` error.code.
        """
        try:
            self._signals_client.post_signal(
                session_id=session_id,
                request_id=request_id,
                source=_AZURE_CONTENT_FILTER_SOURCE,
                decision=decision,
                reason=reason,
                priority=_AZURE_CONTENT_FILTER_PRIORITY,
                agent_id=agent_id,
                platform=self.platform.value,
                cloud_region=self.cloud_region,
            )
        except Exception as exc:  # noqa: BLE001 — defensive
            logger.warning("azure_content_filter signal post failed: %s", exc)

    def parse_tool_calls(self, raw_response: Any) -> list[ToolCall]:
        """Extract tool calls from a raw OpenAI completion or AgentResponse.trace.

        Accepts either:
          - A raw OpenAI chat-completion dict (with .choices[].message.tool_calls)
          - An AgentResponse.trace dict from invoke_agent (with .tool_calls list)
        """
        out: list[ToolCall] = []
        if isinstance(raw_response, dict) and "iterations" in raw_response:
            # trace dict from invoke_agent
            for tc in raw_response.get("tool_calls", []):
                out.append(
                    ToolCall(
                        tool_name=tc.get("tool_name", ""),
                        tool_params={},  # not stored in trace; would need full raw if needed
                        invoked_at=datetime.now(timezone.utc),
                        raw_event=tc,
                    )
                )
            return out

        # raw OpenAI completion shape
        try:
            tcs = raw_response["choices"][0]["message"].get("tool_calls") or []
        except (KeyError, IndexError, TypeError):
            return out

        for tc in tcs:
            try:
                params = json.loads(tc["function"]["arguments"])
            except (KeyError, json.JSONDecodeError):
                params = {}
            out.append(
                ToolCall(
                    tool_name=tc["function"]["name"],
                    tool_params=params,
                    invoked_at=datetime.now(timezone.utc),
                    raw_event=tc,
                )
            )
        return out

    def get_audit_trace(self, session_id: str) -> list[AuditEvent]:
        """Sessions and audit logs live in the Sentra controller, not in Azure.

        The dashboard already fetches cross-cloud audit via the controller's
        /v1/logs endpoint. This connector returns an empty list — the audit
        timeline is built dashboard-side from the controller's records, not
        from Azure-side state.
        """
        # Issue #2: same pattern as Bedrock — warn so callers don't treat the
        # empty list as "no events" when it actually means "not queried here".
        logger.warning(
            "AzureConnector.get_audit_trace is a Phase-1 stub returning []. "
            "Query the Sentra audit API directly via /v1/logs?session_id=%s",
            session_id,
        )
        return []

    def list_sessions(self, agent_id: str, **kwargs: Any) -> list[SessionSummary]:
        """Azure AI Foundry agents don't expose a native session listing API
        that maps cleanly to Sentra's session model. The dashboard sources
        sessions from the controller's session-context table instead.
        """
        logger.warning(
            "AzureConnector.list_sessions is a Phase-1 stub returning []. "
            "Source sessions from the controller's session-context API instead."
        )
        return []

    def delete_session(self, agent_id: str, session_id: str, **kwargs: Any) -> bool:
        """No-op on the Azure side — session state lives in Sentra's DDB
        session-context table. The dashboard deletes there, not here.
        """
        return True

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _chat_completion(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        """Call the Azure OpenAI Chat Completions API with function-calling.

        Uses urllib (stdlib) to stay dependency-light, matching the choice in
        the Function tool_interceptor. Switch to the openai SDK if/when the
        dashboard already pulls it in.

        Raises `AzureOpenAIError` carrying the server response body on non-2xx
        — without that, the cross-cloud scenario runner can't tell whether a
        400 came from content-filter rejection, an invalid tool spec, or a
        quota issue.
        """
        url = (
            f"{self.openai_endpoint}/openai/deployments/{self.openai_deployment}"
            f"/chat/completions?api-version={self.openai_api_version}"
        )
        payload = {
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": self._spec["model"].get("temperature", 0.2),
            "max_tokens": self._spec["model"].get("max_tokens", 1024),
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "api-key": self.openai_api_key},
        )
        try:
            with urllib.request.urlopen(req, timeout=30.0) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                body_text = exc.read().decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                body_text = ""
            raise AzureOpenAIError(exc.code, body_text) from exc


class AzureOpenAIError(Exception):
    """Carries the HTTP status + response body from Azure OpenAI for diagnosis."""

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        # Best-effort: surface the OpenAI/content-filter error message inline.
        snippet = body
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                err = parsed.get("error") or parsed
                msg = err.get("message") if isinstance(err, dict) else None
                code = err.get("code") if isinstance(err, dict) else None
                if msg or code:
                    snippet = f"{code or '?'}: {msg or ''}".strip(": ")
        except (ValueError, TypeError):
            pass
        super().__init__(f"Azure OpenAI HTTP {status_code} — {snippet[:300]}")


def _is_content_filter_error(exc: "AzureOpenAIError") -> bool:
    """Detect Azure OpenAI's content-filter rejection responses.

    Azure OpenAI returns HTTP 400 with `error.code in {'content_filter',
    'jailbreak'}` (or similar) when the input is blocked by the deployed
    content filter — this is a security boundary firing, not an infra issue.
    The runner should count it as DENY for cross-cloud demo purposes.
    """
    if exc.status_code != 400:
        return False
    body = (exc.body or "").lower()
    return any(k in body for k in ("content_filter", "content filter", "jailbreak", "responsibleaipolicyviolation"))

    def _call_function_tool(
        self,
        tool_name: str,
        params: dict[str, Any],
        session_id: str,
        user_input: str,
        request_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """POST to the Function App's /api/tool/{tool_name}.

        Returns the parsed JSON response. On 403 (Sentra DENY), the response
        body still has {"decision":"DENY","reason":...} which we surface upward.

        TODO (Issue #17, WS15 M3 review): no auth header on this request. Today
        the Function App accepts any HTTPS POST — fine for the demo since it's
        defended by API key + Usage Plan at AWS API Gateway downstream, but a
        real customer deployment MUST send `x-functions-key` (Function App key)
        or use Managed Identity. Otherwise any internet caller can invoke
        `/api/tool/*` directly and burn budget / log junk into Sentra.
        Tracking in best-practices.md §11 Azure as a P1 before any customer pilot.
        Also: if Function-level auth ever fails with a generic 403 (no
        decision/reason body), the fail-secure DENY below still kicks in, but
        the model thinks Sentra denied — which is fine for now since both
        outcomes are "tool didn't run".
        """
        if not self.function_tool_url:
            return {"decision": "DENY", "reason": "AZURE_FUNCTION_TOOL_URL not configured"}

        url = f"{self.function_tool_url}/{tool_name}"
        body_dict: dict[str, Any] = {
            "params": params,
            "session_id": session_id,
            "user_input": user_input,
        }
        if request_id:
            # Forwarded to /v1/validate by the Function App (Workstream 17 M5.3)
            # so every Sentra signal correlates back to this connector's
            # logical agent invocation.
            body_dict["request_id"] = request_id
        body = json.dumps(body_dict).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # 403 = Sentra DENY; the body still has decision/reason.
            try:
                return json.loads(e.read().decode("utf-8"))
            except (ValueError, AttributeError):
                return {"decision": "DENY", "reason": f"Function HTTP {e.code}"}
        except urllib.error.URLError as e:
            return {"decision": "DENY", "reason": f"Function unreachable: {e}"}

    def _load_spec(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            raise AgentInvocationError(f"Agent spec not found at {path}")
        return json.loads(path.read_text())

    def _error_response(self, message: str, start: float, trace: dict[str, Any]) -> AgentResponse:
        logger.error("AzureConnector ERROR: %s", message)
        return AgentResponse(
            response="",
            decision="ERROR",
            validation_result=None,
            latency_ms=int((time.time() - start) * 1000),
            trace=trace,
            error=message,
            platform=self.platform,
            cloud_region=self.cloud_region,
        )
