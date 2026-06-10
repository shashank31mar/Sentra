"""AWS Payments agent — Bedrock Action Group Lambda (LLD 22 §6.1.1, §2).

This is the **tool executor**: Bedrock (Nova Lite) emits a tool call, this Lambda runs it — but every
tool is wrapped with ``@guard.tool`` so the call is validated by Sentra *before* it executes. On DENY
the tool body never runs and the Lambda returns a denial the model explains in natural language.

The integration is the whole point of the demo: a customer adds the ``aegion-guard`` decorator + a
``guard.session(...)`` block and threads the Bedrock event through ``from_bedrock_event``. Nothing
here imports Sentra core code.

Packaging: the deploy script vendors ``aegion_guard`` and ``common/`` into the zip, and sets
``SENTRA_API_BASE`` / ``SENTRA_API_KEY`` / ``AEGION_DEMO_BACKEND=ddb`` in the function env.
"""
from __future__ import annotations

import json
import logging
import pathlib
import sys
from decimal import Decimal
from typing import Any, Dict

# Make ``common`` importable both in the Lambda zip (root) and locally.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # demo-agents/

from aegion_guard import AegionGuard, ToolDenied, from_bedrock_event  # noqa: E402
from common import store  # noqa: E402

logger = logging.getLogger("acme-payments-agent")
logger.setLevel(logging.INFO)

AGENT_ID = "acme-payments-agent"

# One guard per cold start. Config is read from env (fail-fast at import if missing) — exactly what a
# customer wires up. Same-cloud (Lambda -> APIGW) so the SDK's 10s default timeout is right.
guard = AegionGuard(agent_id=AGENT_ID, platform="bedrock", cloud_region="us-east-1")


# --------------------------------------------------------------------------- tools (guarded)
@guard.tool(operation_type="READ")
def lookup_account(account_id: str) -> Dict[str, Any]:
    return store.get_account(account_id)


@guard.tool(operation_type="READ")
def get_transactions(account_id: str, limit: int = 10) -> Dict[str, Any]:
    return {"account_id": account_id, "transactions": store.get_transactions(account_id, limit)}


@guard.tool(operation_type="WRITE")
def process_refund(account_id: str, amount: float, txn_id: str = None) -> Dict[str, Any]:
    return store.process_refund(account_id, amount, txn_id)


@guard.tool(operation_type="WRITE")
def transfer_funds(from_account: str, to_account: str, amount: float) -> Dict[str, Any]:
    return store.transfer_funds(from_account, to_account, amount)


TOOLS = {
    "lookup_account": lookup_account,
    "get_transactions": get_transactions,
    "process_refund": process_refund,
    "transfer_funds": transfer_funds,
}


# --------------------------------------------------------------------------- Bedrock plumbing
def _json(obj: Any) -> str:
    return json.dumps(obj, default=lambda x: float(x) if isinstance(x, Decimal) else str(x))


def _bedrock_response(event: Dict[str, Any], status: int, body: Dict[str, Any]) -> Dict[str, Any]:
    """Wrap a tool result/denial in the Bedrock Action Group response envelope."""
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": event.get("actionGroup"),
            "apiPath": event.get("apiPath"),
            "httpMethod": event.get("httpMethod", "POST"),
            "httpStatusCode": status,
            "responseBody": {"application/json": {"body": _json(body)}},
        },
        "sessionAttributes": event.get("sessionAttributes", {}) or {},
        "promptSessionAttributes": event.get("promptSessionAttributes", {}) or {},
    }


def handler(event: Dict[str, Any], context: Any = None) -> Dict[str, Any]:
    ctx = from_bedrock_event(event)
    tool_name = ctx["tool_name"]
    logger.info("tool=%s session=%s params=%s", tool_name, ctx["session_id"], list(ctx["params"]))

    if tool_name not in TOOLS:
        return _bedrock_response(event, 404, {"error": f"unknown tool: {tool_name}"})

    try:
        with guard.session(ctx["session_id"], ctx["user_input"], request_id=ctx["request_id"]):
            result = TOOLS[tool_name](**ctx["params"])
        return _bedrock_response(event, 200, result)
    except ToolDenied as denied:
        # Sentra blocked it (or fail-secure tripped) — the model explains the block to the user.
        logger.warning("DENY tool=%s reason=%s", tool_name, denied.reason)
        return _bedrock_response(event, 403, {"decision": "DENY", "reason": denied.reason,
                                              "threat_type": denied.threat_type})
    except store.NotFound as nf:
        return _bedrock_response(event, 404, {"error": str(nf)})
    except (TypeError, ValueError) as bad:
        return _bedrock_response(event, 400, {"error": f"bad tool params: {bad}"})
