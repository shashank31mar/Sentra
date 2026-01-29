"""
Bedrock Claude Integration - Natural Language Processing
Sentra MVP - Workstream 7 + Workstream 9 (LLM formatting), Task 6

This module processes user messages with AWS Bedrock Claude Sonnet,
handling tool execution with Security Controller validation,
and formats responses using LLMResponseGenerator.
"""

import os
import json
import logging
from typing import Dict, List, Any, Optional
from decimal import Decimal

import sys
from pathlib import Path
import boto3

from app.security_integration import SecurityException
from app.tools.query_refund_status import query_refund_status
from app.tools.process_refund import process_refund
from app.tools.reverse_refund import reverse_refund
from app.tools.list_orders import list_orders

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
    "query_refund_status": query_refund_status,
    "process_refund": process_refund,
    "reverse_refund": reverse_refund,
    "list_orders": list_orders
}


# ==================== Tool Schemas for Claude ====================

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


# ==================== Tool Execution ====================

def execute_tool(tool_name: str, tool_params: Dict) -> Any:
    """
    Execute a tool by name

    Args:
        tool_name: Name of the tool to execute
        tool_params: Parameters to pass to the tool

    Returns:
        Tool execution result

    Raises:
        ValueError: If tool not found
        SecurityException: If Security Controller denies the action
    """
    tool_function = TOOL_REGISTRY.get(tool_name)

    if not tool_function:
        raise ValueError(f"Tool '{tool_name}' not found in registry")

    logger.info(
        f"Executing tool: {tool_name}",
        extra={
            "tool_name": tool_name,
            "params": tool_params
        }
    )

    # Call tool (will be validated by @secured_tool decorator)
    result = tool_function(**tool_params)

    return result


# ==================== Claude Processing ====================

def process_with_claude(
    message: str,
    session_id: str,
    request_id: str,
    available_tools: Optional[List[Dict]] = None
) -> Dict:
    """
    Process user message with AWS Bedrock Claude, handling tool execution

    Flow:
    1. Send message + tools to Claude
    2. Claude returns tool_use blocks (if needed)
    3. For each tool_use:
       a. Execute tool via registry (validated by @secured_tool)
       b. If SecurityException → send denial as tool_result (not raise exception)
       c. Otherwise → send tool result
    4. Send tool results back to Claude
    5. Claude generates final natural language response
    6. Return response to user

    Args:
        message: User's natural language message
        session_id: Session identifier
        request_id: Request identifier
        available_tools: List of tool schemas (default: PAYMENT_TOOLS)

    Returns:
        Dict with:
            - text: Natural language response from Claude
            - data: Optional structured data
    """
    if available_tools is None:
        available_tools = PAYMENT_TOOLS

    # Get environment configuration
    # Default to Sonnet 3.5 v2 (optimized for agentic tasks - faster and cheaper than Opus 4)
    # Using inference profile for v2 (required for on-demand throughput)
    bedrock_model_id = os.environ.get('BEDROCK_MODEL_ID', 'us.anthropic.claude-3-5-sonnet-20241022-v2:0')
    region = os.environ.get('AWS_REGION', 'us-east-1')

    # Initialize Bedrock client
    bedrock = boto3.client('bedrock-runtime', region_name=region)

    import time
    start_time = time.time()
    
    logger.info(
        "Processing message with Claude",
        extra={
            "request_id": request_id,
            "session_id": session_id,
            "message_length": len(message),
            "model": bedrock_model_id
        }
    )

    # Build initial messages
    messages = [{"role": "user", "content": message}]

    # Define system prompt for payment agent role
    system_prompt = """You are a helpful payment and refund assistant for an e-commerce company.
You have access to tools that allow you to:
- List customer orders (list_orders)
- Query refund status for orders (query_refund_status)
- Process refunds for orders (process_refund)
- Reverse previously processed refunds (reverse_refund)

When users ask about orders, refunds, or payments, use the available tools to help them.
Always be professional, clear, and helpful. If a tool returns an error or security denial,
explain it to the user in a friendly way."""

    # Initial request to Claude
    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "system": system_prompt,
        "messages": messages,
        "tools": available_tools,
        "max_tokens": 4096
    }

    try:
        bedrock_start = time.time()
        response = bedrock.invoke_model(
            modelId=bedrock_model_id,
            body=json.dumps(request_body)
        )
        bedrock_latency = (time.time() - bedrock_start) * 1000

        response_body = json.loads(response['body'].read())

        logger.info(
            "Claude initial response received",
            extra={
                "request_id": request_id,
                "stop_reason": response_body.get('stop_reason'),
                "bedrock_latency_ms": round(bedrock_latency, 2)
            }
        )

        # Check if Claude wants to use tools
        if response_body.get('stop_reason') == 'tool_use':
            tool_results = []

            for content_block in response_body['content']:
                if content_block.get('type') == 'tool_use':
                    tool_name = content_block['name']
                    tool_params = content_block['input']
                    tool_use_id = content_block['id']

                    logger.info(
                        f"Claude requested tool: {tool_name}",
                        extra={
                            "request_id": request_id,
                            "tool_name": tool_name,
                            "tool_use_id": tool_use_id
                        }
                    )

                    try:
                        # Execute tool (validated by @secured_tool decorator)
                        tool_start = time.time()
                        result = execute_tool(tool_name, tool_params)
                        tool_latency = (time.time() - tool_start) * 1000

                        # Success - tool executed
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": json.dumps(result, cls=DecimalEncoder) if not isinstance(result, str) else result
                        })

                        logger.info(
                            f"Tool executed successfully: {tool_name}",
                            extra={
                                "request_id": request_id,
                                "tool_name": tool_name,
                                "tool_use_id": tool_use_id,
                                "tool_latency_ms": round(tool_latency, 2)
                            }
                        )

                    except SecurityException as e:
                        # BUG-001 FIX: Different handling for single vs multi-agent calls
                        logger.warning(
                            f"Security Controller denied tool: {tool_name}",
                            extra={
                                "request_id": request_id,
                                "tool_name": tool_name,
                                "tool_use_id": tool_use_id,
                                "reason": str(e),
                                "matched_rules": e.matched_rules
                            }
                        )

                        # Detect if this is a multi-agent call
                        from app.security_integration import get_current_context
                        context = get_current_context()
                        is_multi_agent_call = bool(context.get('parent_request_id'))

                        if is_multi_agent_call:
                            # Multi-agent workflow: Re-raise so parent gets HTTP 403
                            logger.info(
                                f"Re-raising SecurityException for multi-agent call",
                                extra={
                                    "request_id": request_id,
                                    "parent_request_id": context.get('parent_request_id'),
                                    "caller_agent_id": context.get('caller_agent_id')
                                }
                            )
                            raise
                        else:
                            # Single-agent call: Let Claude explain denial to end user
                            logger.info(
                                f"Returning denial as tool_result for single-agent call",
                                extra={"request_id": request_id}
                            )
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": json.dumps({
                                    "error": "security_denial",
                                    "reason": str(e),
                                    "matched_rules": e.matched_rules,
                                    "user_friendly_hint": "This action was blocked by security policies."
                                }, cls=DecimalEncoder),
                                "is_error": True
                            })

                    except ValueError as e:
                        # Business logic error (e.g., order not found, invalid amount)
                        logger.warning(
                            f"Tool validation failed (business logic): {tool_name}",
                            extra={
                                "request_id": request_id,
                                "tool_name": tool_name,
                                "tool_use_id": tool_use_id,
                                "error": str(e)
                            }
                        )

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": json.dumps({
                                "error": "validation_error",
                                "error_type": "business_logic",
                                "message": str(e),
                                "hint": "This is a business validation issue, not a security block."
                            }, cls=DecimalEncoder),
                            "is_error": True
                        })

                    except Exception as e:
                        # Tool execution error (system/database issues)
                        logger.error(
                            f"Tool execution failed: {tool_name}",
                            extra={
                                "request_id": request_id,
                                "tool_name": tool_name,
                                "tool_use_id": tool_use_id,
                                "error": str(e),
                                "error_type": type(e).__name__
                            },
                            exc_info=True  # Include full stack trace
                        )

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": json.dumps({
                                "error": "execution_error",
                                "error_type": "system_error",
                                "message": str(e)
                            }, cls=DecimalEncoder),
                            "is_error": True
                        })

            # Send tool results back to Claude for final natural language response
            messages.append({"role": "assistant", "content": response_body['content']})
            messages.append({"role": "user", "content": tool_results})

            # Get final response from Claude
            final_request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "system": system_prompt,
                "messages": messages,
                "max_tokens": 4096
            }

            final_bedrock_start = time.time()
            final_response = bedrock.invoke_model(
                modelId=bedrock_model_id,
                body=json.dumps(final_request_body)
            )
            final_bedrock_latency = (time.time() - final_bedrock_start) * 1000

            final_body = json.loads(final_response['body'].read())

            logger.info(
                "Claude final response received",
                extra={
                    "request_id": request_id,
                    "stop_reason": final_body.get('stop_reason'),
                    "final_bedrock_latency_ms": round(final_bedrock_latency, 2)
                }
            )

            # Extract text response
            response_text = ""
            for content_block in final_body['content']:
                if content_block.get('type') == 'text':
                    response_text += content_block['text']

            total_latency = (time.time() - start_time) * 1000
            
            logger.info(
                "Claude response text",
                extra={
                    "request_id": request_id,
                    "response_text": response_text[:500],  # Log first 500 chars
                    "response_length": len(response_text)
                }
            )
            
            logger.info(
                "Request completed with tools",
                extra={
                    "request_id": request_id,
                    "total_latency_ms": round(total_latency, 2),
                    "initial_bedrock_ms": round(bedrock_latency, 2),
                    "final_bedrock_ms": round(final_bedrock_latency, 2)
                }
            )
            
            return {
                "text": response_text,
                "data": {}
            }

        else:
            # Claude responded directly without using tools
            response_text = ""
            for content_block in response_body['content']:
                if content_block.get('type') == 'text':
                    response_text += content_block['text']

            total_latency = (time.time() - start_time) * 1000
            
            logger.info(
                "Claude response text",
                extra={
                    "request_id": request_id,
                    "response_text": response_text[:500],  # Log first 500 chars
                    "response_length": len(response_text)
                }
            )
            
            logger.info(
                "Claude responded without tools",
                extra={
                    "request_id": request_id,
                    "response_length": len(response_text),
                    "total_latency_ms": round(total_latency, 2),
                    "bedrock_latency_ms": round(bedrock_latency, 2)
                }
            )

            return {
                "text": response_text,
                "data": {}
            }

    except Exception as e:
        logger.exception(
            "Bedrock API error",
            extra={
                "request_id": request_id,
                "error": str(e)
            }
        )
        raise
