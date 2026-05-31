"""
Bedrock LLM Integration - Natural Language Processing
Sentra MVP - Workstream 7 + Workstream 9 (LLM formatting)

This module processes user messages through AWS Bedrock using the
provider-agnostic Converse API (instead of the Anthropic-native
invoke_model body shape). The Converse API supports tool use across
Anthropic, Amazon Nova, Mistral, and other Bedrock providers — letting
the deployed BEDROCK_MODEL_ID move freely without code changes.

Why Converse instead of invoke_model:
- Older Anthropic-native shape required `anthropic_version`, `system`,
  `messages` with `tool_use`/`tool_result` blocks. Nova and most other
  Bedrock providers reject that body. Anthropic models that drop into
  LEGACY status are also auto-disabled after 30 days of inactivity, so
  the demo couldn't reliably stay on a single Anthropic model.
- Converse normalizes the request/response across providers. Tool
  schemas use `toolConfig.tools[*].toolSpec`; tool calls in the
  response come back as `{"toolUse": {...}}` blocks; tool results are
  sent back as `{"toolResult": {...}}` blocks.

The public CUSTOMER_QUERY_TOOLS list keeps the original
Anthropic-style schema as the canonical tool definition (used by
tests and external references). It is converted at the boundary
inside `process_with_claude` via `_to_converse_tool_config`.
"""

import os
import json
import logging
import time
from typing import Dict, List, Any, Optional
from decimal import Decimal

import boto3

from app.security_integration import SecurityException
from app.tools.query_customers import query_customers
from app.tools.query_orders import query_orders
from app.tools.get_customer_by_id import get_customer_by_id
from app.tools.call_payment_agent import call_payment_agent

logger = logging.getLogger(__name__)


# Custom JSON encoder to handle Decimal types from DynamoDB
class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that converts Decimal to float"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)


# ==================== Tool Registry ====================

# Maps tool names to Python functions
TOOL_REGISTRY = {
    "query_customers": query_customers,
    "query_orders": query_orders,
    "get_customer_by_id": get_customer_by_id,
    "call_payment_agent": call_payment_agent
}


# ==================== Tool Schemas (Anthropic-native canonical form) ====================
# These remain the project's canonical tool definitions. They are
# converted to Converse `toolConfig` shape inside `process_with_claude`
# via `_to_converse_tool_config`. Keeping the canonical form lets tests
# and any external references stay unchanged.

CUSTOMER_QUERY_TOOLS = [
    {
        "name": "query_customers",
        "description": "Query customers from the database with optional filters. Use this to find customers by state, name, or email.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filters": {
                    "type": "object",
                    "description": "Optional filters to narrow down results",
                    "properties": {
                        "state": {
                            "type": "string",
                            "description": "Filter by US state (e.g., 'CA', 'TX', 'NY')"
                        },
                        "name_contains": {
                            "type": "string",
                            "description": "Filter by name substring (case-insensitive)"
                        },
                        "email_contains": {
                            "type": "string",
                            "description": "Filter by email substring"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of results to return (default 100, max 1000)"
                        }
                    }
                }
            }
        }
    },
    {
        "name": "query_orders",
        "description": "Query orders from the database. ALWAYS call this tool when a user asks to list, show, retrieve, or find orders — even without specifying a customer ID. For 'top N orders' or 'recent orders', use the limit filter (e.g., limit=5). No customer_id is required.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filters": {
                    "type": "object",
                    "description": "Optional filters to narrow down results",
                    "properties": {
                        "customer_id": {
                            "type": "string",
                            "description": "Filter by customer ID"
                        },
                        "status": {
                            "type": "string",
                            "description": "Filter by order status",
                            "enum": ["completed", "pending", "cancelled", "shipped"]
                        },
                        "min_amount": {
                            "type": "number",
                            "description": "Minimum order amount in dollars"
                        },
                        "max_amount": {
                            "type": "number",
                            "description": "Maximum order amount in dollars"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of results to return (default 100, max 1000)"
                        }
                    }
                }
            }
        }
    },
    {
        "name": "get_customer_by_id",
        "description": "Get detailed information about a specific customer by their ID",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "The unique customer identifier"
                }
            },
            "required": ["customer_id"]
        }
    },
    {
        "name": "call_payment_agent",
        "description": "REQUIRED for all refund and payment operations. Call the Payment Agent to process refunds, reverse refunds, or handle any payment-related tasks. You MUST use this tool whenever a user requests a refund - do not just describe what you will do, actually call this tool.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Natural language request to send to the Payment Agent (e.g., 'Process a $300 refund for order ord-123')"
                },
                "session_id": {
                    "type": "string",
                    "description": "Current session ID to maintain context"
                }
            },
            "required": ["message", "session_id"]
        }
    }
]


# ==================== Converse API helpers ====================

def _to_converse_tool_config(tools: List[Dict]) -> Dict:
    """Convert canonical Anthropic-style tool list to Bedrock Converse toolConfig.

    Anthropic shape:   {"name", "description", "input_schema"}
    Converse shape:    {"toolSpec": {"name", "description",
                                     "inputSchema": {"json": <jsonschema>}}}
    """
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
    """Extract concatenated text from a Converse content-block list."""
    text = ""
    for block in content_blocks or []:
        if "text" in block:
            text += block["text"]
    return text


def _extract_tool_uses(content_blocks: List[Dict]) -> List[Dict]:
    """Return list of tool-use blocks from a Converse content-block list."""
    return [block["toolUse"] for block in (content_blocks or []) if "toolUse" in block]


def _tool_result_block(tool_use_id: str, payload: Any, *, is_error: bool = False) -> Dict:
    """Build a Converse `toolResult` content block.

    Converse expects content within a toolResult to be a list of typed
    blocks. We always send JSON for both success and error payloads so
    the model sees structured input.
    """
    if isinstance(payload, str):
        # If the tool already returned a string, wrap it as JSON for consistency.
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

SYSTEM_PROMPT = """You are a Customer Query Agent for a demo customer service platform.

Your capabilities:
1. Query and retrieve customer information using query_customers or get_customer_by_id
2. Query order information using query_orders
3. Delegate refund and payment operations to the Payment Agent using call_payment_agent

CRITICAL RULES — YOU MUST FOLLOW THESE EXACTLY:

1. ORDER QUERIES: For ANY message asking about orders (list orders, show orders, top N orders, recent orders, find orders, show me orders, etc.), you MUST call the query_orders tool immediately. Do NOT say you cannot access orders. Do NOT say you lack access. CALL THE TOOL. Examples:
   - "list top 5 orders" → call query_orders with filters: {limit: 5}
   - "show me recent orders" → call query_orders with filters: {limit: 10}
   - "list orders" → call query_orders with no filters
   - "show me order ORD-12345" → call query_orders
   No customer_id is needed — you can list all orders.

2. REFUND REQUESTS: For ANY refund request, you MUST call call_payment_agent. Do NOT just describe what you will do.

3. NEVER respond with "I don't have access" or "I cannot view order information" — you HAVE access, use the query_orders tool.

4. Always wait for tool results before responding to the user.

5. Provide clear, helpful responses based on actual tool results.

Example: User says "list top 5 orders"
→ You MUST call: query_orders(filters={"limit": 5})
→ Wait for result → Summarize the orders returned

Never respond without calling the appropriate tool first."""


# ==================== Tool-call dispatch (shared by both turns) ====================

def _dispatch_tool_call(
    tool_use: Dict,
    *,
    request_id: str,
) -> Dict:
    """Execute a single tool-use block and return the matching toolResult block.

    Mirrors the original (invoke_model) error taxonomy:
      - SecurityException on a multi-agent call → re-raise so the parent agent
        gets HTTP 403 (BUG-001 contract preserved).
      - SecurityException on a single-agent call → return as toolResult so the
        model can explain the denial in natural language.
      - ValueError → returned as a structured business-logic error.
      - Any other Exception → returned as a structured system error.
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
        # Coerce non-JSON-serializable types (Decimal etc.) by round-tripping.
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

        # Multi-agent contract (BUG-001): re-raise so parent gets HTTP 403.
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

        # Single-agent: surface denial back to the model as a tool error.
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

# Maximum number of model<->tool turns before we stop and return whatever
# text the model produced. The original implementation supported up to 3
# turns (initial + post-tool + post-tool-again). 4 keeps headroom in case a
# more capable model needs an extra step.
_MAX_TURNS = 4


def process_with_claude(
    message: str,
    session_id: str,
    request_id: str,
    available_tools: Optional[List[Dict]] = None,
) -> Dict:
    """Process a user message via Bedrock Converse, executing tools inline.

    Returns:
        {"text": <natural-language reply>, "data": {}}
    """
    # Function name retained for backward compatibility with callers in
    # routes.py and tests; despite the name, this works with any Bedrock
    # Converse-compatible model (Anthropic, Nova, Mistral, etc.).
    if available_tools is None:
        available_tools = CUSTOMER_QUERY_TOOLS

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
                # Model produced its final natural-language reply.
                response_text = _extract_text(content_blocks)
                break

            # Append the assistant turn (tool_use blocks) before responding
            # with toolResult blocks — Converse requires the full turn to be
            # echoed back.
            messages.append({"role": "assistant", "content": content_blocks})

            tool_result_blocks = [
                _dispatch_tool_call(tu, request_id=request_id) for tu in tool_uses
            ]
            messages.append({"role": "user", "content": tool_result_blocks})

        else:
            # Loop exhausted without hitting an `end_turn`/text-only reply.
            logger.warning(
                "Converse turn limit reached without final text",
                extra={"request_id": request_id, "max_turns": _MAX_TURNS},
            )
            # Best-effort: pull any text from the last assistant message.
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
