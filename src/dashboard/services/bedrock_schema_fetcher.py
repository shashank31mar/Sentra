"""Bedrock Action Group OpenAPI schema fetcher — LLD 18 §4.2.3 / Workstream 18 M3.2.

Caches per-agent OpenAPI schemas so the direct-invoke runner can emit
properly-typed `requestBody.content["application/json"].properties` entries
(integer as integer, boolean as boolean, etc.). Without this the synthetic
event would stringify every param and `process_refund.amount` (declared as
OpenAPI `number`) would arrive at the Lambda as `"50.0"` instead of `50.0`.

Failure mode: if the Lambda or agent isn't reachable at first use, the
fetcher raises `BedrockSchemaUnavailable`. Callers should treat this as a
config error — the deployed Bedrock agent probably has no action group
registered, which is a deploy-time bug, not a per-invocation one.

Cache is process-lifetime. Bedrock action group definitions change rarely
(via CDK redeploy); a Streamlit rerun loads fresh anyway. No TTL.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Optional

import boto3

logger = logging.getLogger(__name__)


# OpenAPI primitive type → Bedrock Action Group event property type.
# Bedrock accepts: string | integer | boolean | number | array.
# "object" parameters are flattened by Bedrock at runtime — emit as string
# (the Lambda's existing parser handles object-as-JSON-string fallback).
_OPENAPI_TO_BEDROCK_TYPE = {
    "string": "string",
    "integer": "integer",
    "number": "number",
    "boolean": "boolean",
    "array": "array",
    "object": "string",
}


class BedrockSchemaUnavailable(Exception):
    """Raised when the agent's action group OpenAPI schema can't be loaded.

    Always a deploy-time error (agent missing action group, IAM gap, region
    typo). Not retryable on the validation path — the runner should surface
    this loudly so the developer fixes the deployment, not the scenario.
    """


class BedrockSchemaFetcher:
    """Fetches + caches Bedrock Action Group OpenAPI schemas per agent.

    One instance per dashboard process. Thread-safe (Streamlit's
    multi-session model means concurrent agent invocations share the cache).

    Usage:
        fetcher = BedrockSchemaFetcher()
        schema = fetcher.get("sentra-mvp-customer-service-agent")
        # schema -> {"query_customers": {"parameters": {"state": {"type": "string", "required": True}}}, ...}
    """

    # Default action group name. v0.1 hardcodes this per LLD 18 §4.2.2 — all
    # current demo agents use customer_tools. Lift to per-agent lookup when a
    # demo agent grows a second action group.
    DEFAULT_ACTION_GROUP = "customer_tools"

    def __init__(
        self,
        *,
        region: str = "us-east-1",
        action_group_name: str = DEFAULT_ACTION_GROUP,
        client: Optional[Any] = None,
        discover_fn: Optional[Any] = None,
    ) -> None:
        self._region = region
        self._action_group_name = action_group_name
        self._client = client or boto3.client("bedrock-agent", region_name=region)
        # discover_fn maps the symbolic agent name (e.g.
        # "sentra-mvp-customer-service-agent") to the real Bedrock agent_id.
        # The dashboard already has services.bedrock_agent_service for this;
        # injectable so unit tests don't need a real Bedrock client.
        self._discover_fn = discover_fn
        self._cache: dict[str, dict[str, dict]] = {}
        self._lock = threading.Lock()

    def get(self, agent_id: str) -> dict[str, dict]:
        """Return parsed schema for the agent. Cached after first call.

        Returns shape:
            {
                "<tool_name>": {
                    "parameters": {
                        "<param_name>": {"type": "<bedrock_type>", "required": bool},
                        ...
                    }
                },
                ...
            }
        """
        with self._lock:
            cached = self._cache.get(agent_id)
            if cached is not None:
                return cached

        # Cache miss — fetch outside the lock so concurrent misses don't
        # serialize on the bedrock-agent API call. The lock-and-write below
        # protects against the rare double-fetch race.
        schema = self._fetch(agent_id)
        with self._lock:
            self._cache[agent_id] = schema
        return schema

    def invalidate(self, agent_id: Optional[str] = None) -> None:
        """Drop the cached schema(s). Useful after a redeploy."""
        with self._lock:
            if agent_id is None:
                self._cache.clear()
            else:
                self._cache.pop(agent_id, None)

    def _resolve_bedrock_agent_id(self, symbolic_agent_id: str) -> str:
        """Translate a symbolic agent name to the real Bedrock agent ID."""
        if self._discover_fn:
            info = self._discover_fn(symbolic_agent_id)
            if not info or not info.get("id"):
                raise BedrockSchemaUnavailable(
                    f"Agent discovery returned no Bedrock agent_id for "
                    f"symbolic name {symbolic_agent_id!r}"
                )
            return info["id"]
        # No discover_fn injected — assume caller passed a real Bedrock
        # agent_id directly. Convenient for unit tests with mock clients.
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
                f"get_agent_action_group failed for {agent_id}/"
                f"{self._action_group_name}: {exc}"
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
            "BedrockSchemaFetcher: cached schema for %s — tools: %s",
            agent_id,
            list(parsed.keys()),
        )
        return parsed

    @staticmethod
    def _parse_openapi(openapi: dict) -> dict[str, dict]:
        """Extract per-tool parameter type info from an OpenAPI 3 document.

        Bedrock Action Group schemas declare tools as paths (e.g. `/query_customers`)
        with a POST verb whose requestBody describes the params. We normalize
        to a flat `{tool_name: {parameters: {name: {type, required}}}}` map.
        """
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

    def coerce_param(self, openapi_type: str, value: Any) -> Any:
        """Coerce a Python value into the Bedrock event-shape representation.

        Bedrock expects `value` as a string when type is "string", but as the
        native type for "integer" / "number" / "boolean". This handles the
        common case where the YAML supplies a string (e.g. `amount: "50.0"`)
        but the OpenAPI declares a number — we cast it.
        """
        bedrock_type = _OPENAPI_TO_BEDROCK_TYPE.get(openapi_type, "string")
        if bedrock_type == "string":
            return str(value)
        if bedrock_type == "integer":
            return int(value)
        if bedrock_type == "number":
            return float(value)
        if bedrock_type == "boolean":
            if isinstance(value, bool):
                return value
            return str(value).lower() in ("true", "1", "yes")
        if bedrock_type == "array":
            return value if isinstance(value, list) else [value]
        return value

    @staticmethod
    def bedrock_type_for(openapi_type: str) -> str:
        return _OPENAPI_TO_BEDROCK_TYPE.get(openapi_type, "string")
