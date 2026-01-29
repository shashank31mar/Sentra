"""
Bedrock Claude Integration - Natural Language Processing
Sentra MVP - Workstream 7 + Workstream 9 (LLM formatting)

This module processes user messages with AWS Bedrock Claude Sonnet,
handling tool execution with Security Controller validation,
and formats responses using LLMResponseGenerator.
"""

import os
import json
import logging
import sys
from pathlib import Path
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


# ==================== Tool Schemas for Claude ====================

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
        "description": "Query orders from the database with optional filters. Use this to find orders by customer, status, or amount.",
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


# ==================== System Prompt ====================

SYSTEM_PROMPT = """You are a Customer Query Agent for Sentra, a customer service platform.

Your capabilities:
1. Query and retrieve customer information using query_customers or get_customer_by_id
2. Query order information using query_orders
3. Delegate refund and payment operations to the Payment Agent using call_payment_agent

IMPORTANT RULES:
- For ANY refund request, you MUST use the call_payment_agent tool. Do NOT just say you will process it - actually call the tool.
- When a user asks to process a refund, ALWAYS call call_payment_agent with the refund details.
- First gather customer/order information if needed, then call call_payment_agent for the actual refund.
- Always wait for tool results before responding to the user.
- Provide clear, helpful responses based on the actual tool results.

Example flow for refund request:
1. User: "Process a $300 refund for order ord-123"
2. You: Call call_payment_agent with message "Process a $300 refund for order ord-123"
3. Wait for result from Payment Agent
4. Respond to user with the actual refund result

Never respond with "I will process" or "Let me process" without actually calling the appropriate tool."""


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
        available_tools: List of tool schemas (default: CUSTOMER_QUERY_TOOLS)

    Returns:
        Dict with:
            - text: Natural language response from Claude
            - data: Optional structured data
    """
    if available_tools is None:
        available_tools = CUSTOMER_QUERY_TOOLS

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

    # Initial request to Claude with system prompt
    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "system": SYSTEM_PROMPT,
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
                        # Business logic error (e.g., record not found, invalid parameters)
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

            # Get final response from Claude - include system prompt and tools for multi-turn
            final_request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "system": SYSTEM_PROMPT,
                "messages": messages,
                "tools": available_tools,
                "max_tokens": 4096
            }

            final_response = bedrock.invoke_model(
                modelId=bedrock_model_id,
                body=json.dumps(final_request_body)
            )

            final_body = json.loads(final_response['body'].read())

            logger.info(
                "Claude final response received",
                extra={
                    "request_id": request_id,
                    "stop_reason": final_body.get('stop_reason')
                }
            )

            # Check if Claude wants to use more tools (multi-step workflow)
            if final_body.get('stop_reason') == 'tool_use':
                # Process additional tool calls
                additional_tool_results = []
                
                for content_block in final_body['content']:
                    if content_block.get('type') == 'tool_use':
                        tool_name = content_block['name']
                        tool_params = content_block['input']
                        tool_use_id = content_block['id']

                        logger.info(
                            f"Claude requested additional tool: {tool_name}",
                            extra={
                                "request_id": request_id,
                                "tool_name": tool_name,
                                "tool_use_id": tool_use_id
                            }
                        )

                        try:
                            tool_start = time.time()
                            result = execute_tool(tool_name, tool_params)
                            tool_latency = (time.time() - tool_start) * 1000

                            additional_tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": json.dumps(result, cls=DecimalEncoder) if not isinstance(result, str) else result
                            })

                            logger.info(
                                f"Additional tool executed successfully: {tool_name}",
                                extra={
                                    "request_id": request_id,
                                    "tool_name": tool_name,
                                    "tool_use_id": tool_use_id,
                                    "tool_latency_ms": round(tool_latency, 2)
                                }
                            )

                        except SecurityException as e:
                            logger.warning(
                                f"Security Controller denied additional tool: {tool_name}",
                                extra={
                                    "request_id": request_id,
                                    "tool_name": tool_name,
                                    "tool_use_id": tool_use_id,
                                    "reason": str(e)
                                }
                            )
                            additional_tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": json.dumps({
                                    "error": "security_denial",
                                    "reason": str(e),
                                    "matched_rules": e.matched_rules
                                }, cls=DecimalEncoder),
                                "is_error": True
                            })

                        except Exception as e:
                            logger.error(
                                f"Additional tool execution failed: {tool_name}",
                                extra={
                                    "request_id": request_id,
                                    "tool_name": tool_name,
                                    "error": str(e)
                                }
                            )
                            additional_tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": json.dumps({
                                    "error": "execution_error",
                                    "message": str(e)
                                }, cls=DecimalEncoder),
                                "is_error": True
                            })

                # Send additional tool results back to Claude
                messages.append({"role": "assistant", "content": final_body['content']})
                messages.append({"role": "user", "content": additional_tool_results})

                # Get truly final response
                truly_final_request = {
                    "anthropic_version": "bedrock-2023-05-31",
                    "system": SYSTEM_PROMPT,
                    "messages": messages,
                    "max_tokens": 4096
                }

                truly_final_response = bedrock.invoke_model(
                    modelId=bedrock_model_id,
                    body=json.dumps(truly_final_request)
                )

                truly_final_body = json.loads(truly_final_response['body'].read())

                logger.info(
                    "Claude truly final response received",
                    extra={
                        "request_id": request_id,
                        "stop_reason": truly_final_body.get('stop_reason')
                    }
                )

                response_text = ""
                for content_block in truly_final_body['content']:
                    if content_block.get('type') == 'text':
                        response_text += content_block['text']

                return {
                    "text": response_text,
                    "data": {}
                }

            # Extract text response
            response_text = ""
            for content_block in final_body['content']:
                if content_block.get('type') == 'text':
                    response_text += content_block['text']

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

            logger.info(
                "Claude responded without tools",
                extra={
                    "request_id": request_id,
                    "response_length": len(response_text)
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
