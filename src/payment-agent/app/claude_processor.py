"""
Bedrock LLM Integration - Natural Language Processing
Sentra MVP - Workstream 7 + Workstream 9 (LLM formatting), Task 6

This module processes user messages through AWS Bedrock using the
provider-agnostic Converse API (instead of the Anthropic-native
invoke_model body shape). The Converse API supports tool use across
Anthropic, Amazon Nova, Mistral, and other Bedrock providers — letting
the deployed BEDROCK_MODEL_ID move freely without code changes.

See customer-query-agent/app/claude_processor.py for the long-form
rationale; this module mirrors that structure with the payment-agent
tool set.
"""

import os
import json
import logging
import time
from typing import Dict, List, Any, Optional
from decimal import Decimal

import boto3

from app.security_integration import SecurityException
from app.tools.query_refund_status import query_refund_status
from app.tools.process_refund import process_refund
from app.tools.reverse_refund import reverse_refund
from app.tools.list_orders import list_orders

logger = logging.getLogger(__name__)


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that converts Decimal to float."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)


# ==================== Tool Registry ====================

TOOL_REGISTRY = {
    "query_refund_status": query_refund_status,
    "process_refund": process_refund,
    "reverse_refund": reverse_refund,
    "list_orders": list_orders,
}


# ==================== Tool Schemas (Anthropic-native canonical form) ====================
# Converted to Converse `toolConfig` shape at the boundary by
# `_to_converse_tool_config`.

PAYMENT_TOOLS = [
    {
        "name": "list_orders",
        "description": "List recent orders with optional filters. Use this to discover order IDs before processing refunds or to check order status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Optional: Filter by customer ID"
                },
                "status": {
                    "type": "string",
                    "description": "Optional: Filter by order status (completed, pending, refunded)",
                    "enum": ["completed", "pending", "refunded"]
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of orders to return (default 10, max 50)",
                    "minimum": 1,
                    "maximum": 50
                }
            },
            "required": []
        }
    },
    {
        "name": "query_refund_status",
        "description": "Query the refund status for an order. Use this to check if a refund has been processed and get refund details.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "The unique order identifier"
                }
            },
            "required": ["order_id"]
        }
    },
    {
        "name": "process_refund",
        "description": "Process a refund for an order. This action requires proper authorization and is subject to refund limit policies.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "The order ID to refund"
                },
                "amount": {
                    "type": "number",
                    "description": "Refund amount in dollars"
                },
                "reason": {
                    "type": "string",
                    "description": "Reason for the refund"
                }
            },
            "required": ["order_id", "amount", "reason"]
        }
    },
    {
        "name": "reverse_refund",
        "description": "Reverse a previously processed refund. This is a manual rollback operation that requires director authorization.",
        "input_schema": {
            "type": "object",
            "properties": {
                "transaction_id": {
                    "type": "string",
                    "description": "The transaction ID of the refund to reverse"
                },
                "reason": {
                    "type": "string",
                    "description": "Reason for reversing the refund"
                }
            },
            "required": ["transaction_id", "reason"]
        }
    }
]


# ==================== Converse API helpers ====================

def _to_converse_tool_config(tools: List[Dict]) -> Dict:
    return {
        "tools": [
            {
                "toolSpec": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "inputSchema": {"json": t["input_schema"]},
                }
            }
            for t in tools
        ]
    }


def _extract_text(content_blocks: List[Dict]) -> str:
    text = ""
    for block in content_blocks or []:
        if "text" in block:
            text += block["text"]
    return text


def _extract_tool_uses(content_blocks: List[Dict]) -> List[Dict]:
    return [block["toolUse"] for block in (content_blocks or []) if "toolUse" in block]


def _tool_result_block(tool_use_id: str, payload: Any, *, is_error: bool = False) -> Dict:
    if isinstance(payload, str):
        json_payload = {"text": payload}
    else:
        json_payload = payload
    return {
        "toolResult": {
            "toolUseId": tool_use_id,
            "content": [{"json": json_payload}],
            **({"status": "error"} if is_error else {}),
        }
    }


# ==================== Tool Execution ====================

def execute_tool(tool_name: str, tool_params: Dict) -> Any:
    """Execute a tool by name (validated by @secured_tool decorator)."""
    tool_function = TOOL_REGISTRY.get(tool_name)
    if not tool_function:
        raise ValueError(f"Tool '{tool_name}' not found in registry")

    logger.info(
        f"Executing tool: {tool_name}",
        extra={"tool_name": tool_name, "params": tool_params},
    )
    return tool_function(**tool_params)


# ==================== System Prompt ====================

SYSTEM_PROMPT = """You are a helpful payment and refund assistant for an e-commerce company.
You have access to tools that allow you to:
- List customer orders (list_orders)
- Query refund status for orders (query_refund_status)
- Process refunds for orders (process_refund)
- Reverse previously processed refunds (reverse_refund)

When users ask about orders, refunds, or payments, use the available tools to help them.
Always be professional, clear, and helpful. If a tool returns an error or security denial,
explain it to the user in a friendly way."""


# ==================== Tool-call dispatch ====================

def _dispatch_tool_call(tool_use: Dict, *, request_id: str) -> Dict:
    """Execute a single tool-use block and return the matching toolResult block.

    Preserves the BUG-001 multi-agent contract: SecurityException on a
    multi-agent call is re-raised so the parent agent gets HTTP 403.
    """
    tool_name = tool_use["name"]
    tool_params = tool_use.get("input") or {}
    tool_use_id = tool_use["toolUseId"]

    logger.info(
        f"Model requested tool: {tool_name}",
        extra={"request_id": request_id, "tool_name": tool_name, "tool_use_id": tool_use_id},
    )

    try:
        tool_start = time.time()
        result = execute_tool(tool_name, tool_params)
        tool_latency = (time.time() - tool_start) * 1000
        logger.info(
            f"Tool executed successfully: {tool_name}",
            extra={
                "request_id": request_id,
                "tool_name": tool_name,
                "tool_use_id": tool_use_id,
                "tool_latency_ms": round(tool_latency, 2),
            },
        )
        coerced = json.loads(json.dumps(result, cls=DecimalEncoder)) if not isinstance(result, str) else result
        return _tool_result_block(tool_use_id, coerced)

    except SecurityException as e:
        logger.warning(
            f"Security Controller denied tool: {tool_name}",
            extra={
                "request_id": request_id,
                "tool_name": tool_name,
                "tool_use_id": tool_use_id,
                "reason": str(e),
                "matched_rules": e.matched_rules,
            },
        )

        from app.security_integration import get_current_context
        context = get_current_context()
        if context.get("parent_request_id"):
            logger.info(
                "Re-raising SecurityException for multi-agent call",
                extra={
                    "request_id": request_id,
                    "parent_request_id": context.get("parent_request_id"),
                    "caller_agent_id": context.get("caller_agent_id"),
                },
            )
            raise

        return _tool_result_block(
            tool_use_id,
            {
                "error": "security_denial",
                "reason": str(e),
                "matched_rules": e.matched_rules,
                "user_friendly_hint": "This action was blocked by security policies.",
            },
            is_error=True,
        )

    except ValueError as e:
        logger.warning(
            f"Tool validation failed (business logic): {tool_name}",
            extra={
                "request_id": request_id,
                "tool_name": tool_name,
                "tool_use_id": tool_use_id,
                "error": str(e),
            },
        )
        return _tool_result_block(
            tool_use_id,
            {
                "error": "validation_error",
                "error_type": "business_logic",
                "message": str(e),
                "hint": "This is a business validation issue, not a security block.",
            },
            is_error=True,
        )

    except Exception as e:
        logger.error(
            f"Tool execution failed: {tool_name}",
            extra={
                "request_id": request_id,
                "tool_name": tool_name,
                "tool_use_id": tool_use_id,
                "error": str(e),
                "error_type": type(e).__name__,
            },
            exc_info=True,
        )
        return _tool_result_block(
            tool_use_id,
            {
                "error": "execution_error",
                "error_type": "system_error",
                "message": str(e),
            },
            is_error=True,
        )


# ==================== Main entry point ====================

_MAX_TURNS = 4


def process_with_claude(
    message: str,
    session_id: str,
    request_id: str,
    available_tools: Optional[List[Dict]] = None,
) -> Dict:
    """Process a user message via Bedrock Converse, executing tools inline.

    Function name retained for backward compatibility with callers in
    routes.py and tests; works with any Bedrock Converse-compatible model.

    Returns:
        {"text": <natural-language reply>, "data": {}}
    """
    if available_tools is None:
        available_tools = PAYMENT_TOOLS

    bedrock_model_id = os.environ.get(
        "BEDROCK_MODEL_ID", "us.amazon.nova-pro-v1:0"
    )
    region = os.environ.get("AWS_REGION", "us-east-1")
    bedrock = boto3.client("bedrock-runtime", region_name=region)

    start_time = time.time()
    logger.info(
        "Processing message via Bedrock Converse",
        extra={
            "request_id": request_id,
            "session_id": session_id,
            "message_length": len(message),
            "model": bedrock_model_id,
        },
    )

    tool_config = _to_converse_tool_config(available_tools)
    system = [{"text": SYSTEM_PROMPT}]
    messages: List[Dict] = [{"role": "user", "content": [{"text": message}]}]

    initial_latency_ms: Optional[float] = None
    response_text = ""

    try:
        for turn in range(_MAX_TURNS):
            converse_start = time.time()
            response = bedrock.converse(
                modelId=bedrock_model_id,
                system=system,
                messages=messages,
                toolConfig=tool_config,
                inferenceConfig={"maxTokens": 4096},
            )
            converse_latency = (time.time() - converse_start) * 1000
            if turn == 0:
                initial_latency_ms = converse_latency

            stop_reason = response.get("stopReason")
            output_message = response.get("output", {}).get("message", {})
            content_blocks = output_message.get("content", [])

            logger.info(
                "Converse response received",
                extra={
                    "request_id": request_id,
                    "turn": turn,
                    "stop_reason": stop_reason,
                    "converse_latency_ms": round(converse_latency, 2),
                },
            )

            tool_uses = _extract_tool_uses(content_blocks)

            if stop_reason != "tool_use" or not tool_uses:
                response_text = _extract_text(content_blocks)
                break

            messages.append({"role": "assistant", "content": content_blocks})

            tool_result_blocks = [
                _dispatch_tool_call(tu, request_id=request_id) for tu in tool_uses
            ]
            messages.append({"role": "user", "content": tool_result_blocks})

        else:
            logger.warning(
                "Converse turn limit reached without final text",
                extra={"request_id": request_id, "max_turns": _MAX_TURNS},
            )
            response_text = _extract_text(content_blocks)

        total_latency = (time.time() - start_time) * 1000
        logger.info(
            "Request completed",
            extra={
                "request_id": request_id,
                "total_latency_ms": round(total_latency, 2),
                "initial_bedrock_ms": (
                    round(initial_latency_ms, 2) if initial_latency_ms is not None else None
                ),
                "response_length": len(response_text),
            },
        )

        return {"text": response_text, "data": {}}

    except Exception as e:
        logger.exception(
            "Bedrock Converse error",
            extra={"request_id": request_id, "error": str(e)},
        )
        raise
