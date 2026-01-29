"""
Tool: call_payment_agent
Call Payment Agent for refund/payment operations (inter-agent communication)

Workstream: 12 - Multi-Agent Workflow (Milestone 1)
"""

import os
import logging
from typing import Dict

import requests

from app.security_integration import (
    secured_tool,
    get_current_request_id,
    get_current_context,
    get_conversation_id,
    get_call_depth
)
from app.exceptions import ToolDeniedError

logger = logging.getLogger(__name__)

# Structured logging prefix for CloudWatch filtering
LOG_PREFIX = "[WS12-M1-INTER-AGENT]"


@secured_tool
def call_payment_agent(message: str, session_id: str) -> Dict:
    """
    Call Payment Agent for refund/payment operations

    Args:
        message: Natural language request for Payment Agent
        session_id: Session ID (passed through)

    Returns:
        Payment Agent response

    Security Validations:
    - Security Controller validates the inter-agent call
    - Payment Agent validates the tool call again (defense in depth)
    """
    # Get environment configuration
    payment_agent_url = os.environ.get(
        'PAYMENT_AGENT_URL',
        'http://payment-agent.sentra.internal:8080'
    )

    # Get current request ID to pass as parent_request_id
    parent_request_id = get_current_request_id()

    # Get multi-agent context
    conversation_id = get_conversation_id()
    call_depth = get_call_depth()

    # Get original user context to propagate
    current_context = get_current_context()
    user_id = current_context.get('user_id')
    auth_level = current_context.get('authorization_level', 'manager')

    logger.info(
        f"{LOG_PREFIX} Initiating inter-agent call to Payment Agent",
        extra={
            "tool": "call_payment_agent",
            "payment_agent_url": payment_agent_url,
            "session_id": session_id,
            "parent_request_id": parent_request_id,
            "conversation_id": conversation_id,
            "call_depth": call_depth,
            "message_length": len(message),
            "workstream": "12",
            "milestone": "1"
        }
    )

    # Build request payload with multi-agent context
    payload = {
        "message": message,
        "session_id": session_id,
        "context": {
            # Multi-agent tracking
            "caller_agent_id": "customer-query-agent",
            "parent_request_id": parent_request_id,
            "conversation_id": conversation_id,
            "call_depth": call_depth + 1,
            # Propagate user context
            "user_id": user_id,
            "authorization_level": auth_level
        }
    }

    try:
        # Call Payment Agent /action endpoint
        response = requests.post(
            f"{payment_agent_url}/v1/agents/payment/action",
            json=payload,
            timeout=30.0  # 30 second timeout for agent-to-agent calls
        )

        if response.status_code == 200:
            result = response.json()
            
            logger.info(
                f"{LOG_PREFIX} Inter-agent call successful",
                extra={
                    "tool": "call_payment_agent",
                    "session_id": session_id,
                    "status_code": response.status_code,
                    "conversation_id": conversation_id,
                    "response_preview": str(result.get("response", ""))[:100]
                }
            )
            
            logger.info(
                f"{LOG_PREFIX} Payment Agent response received",
                extra={
                    "tool": "call_payment_agent",
                    "session_id": session_id,
                    "status_code": response.status_code,
                    "call_depth": call_depth
                }
            )
            return result

        else:
            # Payment Agent returned error (403, 429, 500, etc.)
            # BUG-001 FIX: Raise exception instead of returning error dict
            # This ensures parent agent propagates child denials correctly

            error_detail = {
                "status_code": response.status_code,
                "response": response.text,
                "agent_id": "payment-agent",
                "conversation_id": conversation_id
            }

            logger.error(
                f"{LOG_PREFIX} Inter-agent call denied by child agent",
                extra={
                    "tool": "call_payment_agent",
                    "session_id": session_id,
                    "status_code": response.status_code,
                    "conversation_id": conversation_id,
                    "response_preview": response.text[:200]
                }
            )

            # Raise exception to propagate child denial to parent agent
            raise ToolDeniedError(
                message=f"Payment Agent denied request: HTTP {response.status_code}",
                status_code=response.status_code,
                detail=error_detail,
                agent_id="payment-agent"
            )

    except requests.exceptions.RequestException as e:
        logger.error(
            f"{LOG_PREFIX} Inter-agent call failed - Connection error",
            extra={
                "tool": "call_payment_agent",
                "session_id": session_id,
                "conversation_id": conversation_id,
                "error": str(e),
                "error_type": type(e).__name__
            },
            exc_info=True
        )

        return {
            "error": f"Failed to communicate with Payment Agent: {str(e)}",
            "status_code": 503
        }
