"""Cloud event adapters (LLD 23 §6).

Turn a raw cloud event into the ``(session_id, user_input, tool_name, params)``
an executor needs, so per-cloud wiring stays ~10 lines. These mirror the parsing
in the production interceptors:
  * Bedrock: ``lambda/bedrock_agent_actions/index.py``
  * Azure:   ``src/connectors/.../tool_interceptor/function_app.py``

Each returns a plain dict:
    {"session_id": str, "user_input": str, "tool_name": str,
     "params": dict, "request_id": str | None}

``request_id`` is included when the event carries a runner-threaded id (so
multi-signal correlation works, LLD 17 §9.1); otherwise it is ``None`` and the
guard mints one per call.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

AdapterResult = Dict[str, Any]


def from_bedrock_event(event: Dict[str, Any]) -> AdapterResult:
    """Parse a Bedrock Agent action-group invocation event.

    Mirrors index.py: tool = apiPath without slashes; params from
    ``requestBody.content['application/json'].properties`` (preferred) else the
    ``parameters`` array; ``sessionId`` + ``inputText``; request_id threaded via
    ``sessionAttributes.sentra_request_id`` when present.
    """
    if not isinstance(event, dict):
        raise ValueError("bedrock event must be a dict")

    api_path = event.get("apiPath", "") or ""
    tool_name = api_path.replace("/", "")
    session_id = event.get("sessionId") or "unknown"
    user_input = event.get("inputText") or ""

    params: Dict[str, Any] = {}
    request_body = event.get("requestBody") or {}
    if request_body:
        properties = (
            request_body.get("content", {})
            .get("application/json", {})
            .get("properties", [])
        )
        params = {p["name"]: p.get("value") for p in properties if "name" in p}
    if not params:
        params = {
            p["name"]: p.get("value")
            for p in (event.get("parameters") or [])
            if "name" in p
        }

    session_attrs = event.get("sessionAttributes") or {}
    request_id: Optional[str] = session_attrs.get("sentra_request_id")

    return {
        "session_id": session_id,
        "user_input": user_input,
        "tool_name": tool_name,
        "params": params,
        "request_id": request_id,
    }


def from_azure_request(req: Any) -> AdapterResult:
    """Parse an Azure Functions ``HttpRequest`` (or a compatible shape).

    Mirrors function_app.py: ``tool_name`` from the ``{tool_name}`` route param,
    params/session_id/user_input from the JSON body; request_id threaded in the
    body by the AzureConnector when present.

    Accepts either an azure.functions.HttpRequest (with ``.route_params`` and
    ``.get_json()``) or a plain dict ``{"route_params": {...}, "body": {...}}``
    so adapters are unit-testable without the azure package installed.
    """
    route_params, body = _extract_azure(req)

    tool_name = route_params.get("tool_name") or body.get("tool_name") or ""
    session_id = body.get("session_id") or "unknown"
    user_input = body.get("user_input") or ""
    params = body.get("params")
    if not isinstance(params, dict):
        # Some callers put tool params at the body top level alongside the
        # control fields; fall back to the body minus known control keys.
        control = {"tool_name", "session_id", "user_input", "params", "request_id"}
        params = {k: v for k, v in body.items() if k not in control}
    request_id: Optional[str] = body.get("request_id")

    return {
        "session_id": session_id,
        "user_input": user_input,
        "tool_name": tool_name,
        "params": params,
        "request_id": request_id,
    }


def _extract_azure(req: Any) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Pull (route_params, json_body) from an HttpRequest or a plain dict."""
    if isinstance(req, dict):
        route_params = req.get("route_params") or {}
        body = req.get("body") or {}
        if isinstance(body, (bytes, str)):
            body = _loads(body)
        return dict(route_params), dict(body)

    # Duck-typed azure.functions.HttpRequest.
    route_params = dict(getattr(req, "route_params", {}) or {})
    body: Dict[str, Any]
    get_json = getattr(req, "get_json", None)
    if callable(get_json):
        try:
            body = get_json() or {}
        except ValueError:
            body = {}
    else:
        raw = getattr(req, "get_body", lambda: b"")()
        body = _loads(raw)
    return route_params, dict(body)


def _loads(raw: Any) -> Dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
