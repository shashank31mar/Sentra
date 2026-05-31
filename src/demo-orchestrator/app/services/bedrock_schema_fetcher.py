"""Bedrock Action Group OpenAPI schema fetcher (orchestrator side) — Workstream 18 M3.2.

Mirrors src/dashboard/services/bedrock_schema_fetcher.py but lives in the
demo-orchestrator. The scenario validator (M3.1) uses this at startup to
cross-check every `tool:` step's `tool_params` against the agent's
declared OpenAPI schema. Catches typos like `tool_params: {state_code: CA}`
when the actual schema requires `state`, before the scenario can fail at
demo time.

Single-action-group constraint (LLD 18 §4.2.2): v0.1 assumes one Action
Group per agent. If a demo agent grows a second action group, this fetcher
raises BedrockSchemaUnavailable with a clear pointer.

Symbolic agent IDs (e.g. `bedrock-secured`, `sentra-mvp-customer-service-agent`)
are resolved via BedrockAgentClient.discover_agents() — already loaded at
orchestrator startup, so we can reuse the discovered map.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Optional

import boto3

logger = logging.getLogger(__name__)


# OpenAPI primitive type → Bedrock Action Group event property type.
# Must match the dashboard's bedrock_schema_fetcher.py so the validator's
# type-check produces the same outcome the runner would at execution time.
_OPENAPI_TO_BEDROCK_TYPE = {
    "string": "string",
    "integer": "integer",
    "number": "number",
    "boolean": "boolean",
    "array": "array",
    "object": "string",
}


class BedrockSchemaUnavailable(Exception):
    """Raised when an agent's action-group OpenAPI schema can't be loaded.

    Always a deploy-time error (agent missing AG, IAM gap, region typo).
    The orchestrator's startup hook surfaces these so demo authors fix
    deployments, not scenario YAMLs.
    """


class BedrockSchemaFetcher:
    """Fetch + cache Bedrock Action Group OpenAPI schemas at orchestrator boot."""

    DEFAULT_ACTION_GROUP = "customer_tools"

    def __init__(
        self,
        *,
        region: str = "us-east-1",
        action_group_name: str = DEFAULT_ACTION_GROUP,
        client: Optional[Any] = None,
        agent_id_resolver: Optional[Any] = None,
    ) -> None:
        self._region = region
        self._action_group_name = action_group_name
        self._client = client or boto3.client("bedrock-agent", region_name=region)
        # Callable that takes a symbolic agent_id and returns the real
        # Bedrock agent_id (or None). Injected from the orchestrator's
        # BedrockAgentClient.get_discovered_agents() data.
        self._agent_id_resolver = agent_id_resolver
        self._cache: dict[str, dict[str, dict]] = {}
        self._lock = threading.Lock()

    def get(self, agent_id: str) -> dict[str, dict]:
        with self._lock:
            cached = self._cache.get(agent_id)
            if cached is not None:
                return cached
        schema = self._fetch(agent_id)
        with self._lock:
            self._cache[agent_id] = schema
        return schema

    def invalidate(self, agent_id: Optional[str] = None) -> None:
        with self._lock:
            if agent_id is None:
                self._cache.clear()
            else:
                self._cache.pop(agent_id, None)

    def _resolve_bedrock_agent_id(self, symbolic_agent_id: str) -> str:
        if self._agent_id_resolver:
            resolved = self._agent_id_resolver(symbolic_agent_id)
            if not resolved:
                raise BedrockSchemaUnavailable(
                    f"Agent discovery returned no Bedrock agent_id for "
                    f"symbolic name {symbolic_agent_id!r}. Cannot fetch schema."
                )
            return resolved
        return symbolic_agent_id

    def _fetch(self, agent_id: str) -> dict[str, dict]:
        bedrock_agent_id = self._resolve_bedrock_agent_id(agent_id)
        try:
            list_resp = self._client.list_agent_action_groups(
                agentId=bedrock_agent_id,
                agentVersion="DRAFT",
            )
        except Exception as exc:
            raise BedrockSchemaUnavailable(
                f"list_agent_action_groups failed for {agent_id} "
                f"(bedrock_id={bedrock_agent_id}): {exc}"
            ) from exc

        summaries = list_resp.get("actionGroupSummaries") or []
        # v0.1 single-AG constraint — flag multi-AG agents loudly.
        if len(summaries) > 1:
            raise BedrockSchemaUnavailable(
                f"Agent {agent_id} has {len(summaries)} action groups; "
                f"v0.1 only supports single-AG agents (LLD 18 §4.2.2). "
                f"Names: {[s.get('actionGroupName') for s in summaries]}"
            )

        target = next(
            (s for s in summaries if s.get("actionGroupName") == self._action_group_name),
            None,
        )
        if not target:
            names = [s.get("actionGroupName") for s in summaries]
            raise BedrockSchemaUnavailable(
                f"Agent {agent_id} has no action group named "
                f"{self._action_group_name!r}. Found: {names}"
            )

        try:
            ag_resp = self._client.get_agent_action_group(
                agentId=bedrock_agent_id,
                agentVersion="DRAFT",
                actionGroupId=target["actionGroupId"],
            )
        except Exception as exc:
            raise BedrockSchemaUnavailable(
                f"get_agent_action_group failed for {agent_id}: {exc}"
            ) from exc

        api_schema = (ag_resp.get("agentActionGroup") or {}).get("apiSchema") or {}
        payload = api_schema.get("payload")
        if not payload:
            raise BedrockSchemaUnavailable(
                f"Action group {self._action_group_name} for {agent_id} has "
                "no inline apiSchema.payload (S3-stored schemas not supported in v0.1)"
            )

        try:
            openapi = json.loads(payload)
        except (TypeError, ValueError) as exc:
            raise BedrockSchemaUnavailable(
                f"Action group {self._action_group_name} schema is not valid JSON: {exc}"
            ) from exc

        parsed = self._parse_openapi(openapi)
        logger.info(
            "BedrockSchemaFetcher (orchestrator): cached schema for %s — tools: %s",
            agent_id,
            list(parsed.keys()),
        )
        return parsed

    @staticmethod
    def _parse_openapi(openapi: dict) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for path, methods in (openapi.get("paths") or {}).items():
            tool_name = path.lstrip("/")
            spec = methods.get("post") or methods.get("get") or {}
            request_body = spec.get("requestBody") or {}
            content = request_body.get("content") or {}
            json_schema = (content.get("application/json") or {}).get("schema") or {}
            props = json_schema.get("properties") or {}
            required = set(json_schema.get("required") or [])
            params: dict[str, dict] = {}
            for param_name, param_schema in props.items():
                openapi_type = (param_schema or {}).get("type", "string")
                params[param_name] = {
                    "type": _OPENAPI_TO_BEDROCK_TYPE.get(openapi_type, "string"),
                    "openapi_type": openapi_type,
                    "required": param_name in required,
                }
            out[tool_name] = {"parameters": params}
        return out
