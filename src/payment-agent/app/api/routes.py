"""
Payment Agent API Routes
Sentra MVP - Workstream 7, Task 8

POST /v1/agents/payment/query - Read operations (query refund status)
POST /v1/agents/payment/action - Write operations (process refunds, reverse refunds)
"""

import os
import logging
import uuid
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.claude_processor import process_with_claude
from app.security_integration import (
    SecurityException,
    set_request_context,
    set_multi_agent_context,
    clear_request_context
)
from app.exceptions import ToolDeniedError

logger = logging.getLogger(__name__)

router = APIRouter()


# ==================== Request/Response Models ====================

class AgentRequest(BaseModel):
    """Unified agent request model"""
    message: str = Field(..., min_length=1, max_length=10000, description="Natural language message")
    session_id: Optional[str] = Field(None, description="Session identifier")
    context: Dict[str, Any] = Field(default_factory=dict, description="Additional context")


class AgentResponse(BaseModel):
    """Unified agent response model"""
    response: str = Field(..., description="Natural language response")
    data: Dict[str, Any] = Field(default_factory=dict, description="Structured data")
    session_id: str = Field(..., description="Session identifier")
    request_id: str = Field(..., description="Request identifier")


class AgentError(BaseModel):
    """Unified agent error model"""
    error: str = Field(..., description="Error message")
    error_code: str = Field(..., description="Error code")
    session_id: str = Field(..., description="Session identifier")
    request_id: str = Field(..., description="Request identifier")
    matched_rules: list = Field(default_factory=list, description="Matched security rules")


# ==================== API Endpoints ====================

@router.post("/v1/agents/payment/query", response_model=AgentResponse)
async def handle_query(request: AgentRequest) -> AgentResponse:
    """
    Handle natural language queries (read operations)

    Flow:
    1. Generate request_id and session_id (if missing)
    2. Set request context for security validation
    3. Call Claude to process request
    4. Return natural language response + structured data

    Args:
        request: Agent request with natural language message

    Returns:
        Natural language response from agent

    Raises:
        HTTPException: 403 if security denied, 500 if internal error
    """
    request_id = str(uuid.uuid4())
    session_id = request.session_id or str(uuid.uuid4())

    # Multi-agent context: extract or generate conversation_id
    conversation_id = request.context.get('conversation_id') or f"conv-{uuid.uuid4().hex[:12]}"
    parent_request_id = request.context.get('parent_request_id')
    caller_agent_id = request.context.get('caller_agent_id')
    call_depth = request.context.get('call_depth', 0)

    logger.info(
        "Query request received",
        extra={
            "request_id": request_id,
            "session_id": session_id,
            "conversation_id": conversation_id,
            "call_depth": call_depth,
            "message_length": len(request.message)
        }
    )

    try:
        # Set request context for @secured_tool decorator
        set_request_context(
            request_id=request_id,
            session_id=session_id,
            user_input=request.message,
            context=request.context
        )

        # Set multi-agent context
        set_multi_agent_context(
            conversation_id=conversation_id,
            parent_request_id=parent_request_id,
            caller_agent_id=caller_agent_id,
            call_depth=call_depth
        )

        # Process with Claude
        response = process_with_claude(
            message=request.message,
            session_id=session_id,
            request_id=request_id
        )

        logger.info(
            "Query request completed",
            extra={
                "request_id": request_id,
                "session_id": session_id,
                "response_length": len(response.get("text", ""))
            }
        )

        return AgentResponse(
            response=response["text"],
            data=response.get("data", {}),
            session_id=session_id,
            request_id=request_id
        )

    except ToolDeniedError as e:
        # BUG-001 FIX: Child agent denied request - propagate denial
        logger.warning(
            "Child agent denied request in multi-agent workflow",
            extra={
                "request_id": request_id,
                "session_id": session_id,
                "conversation_id": conversation_id,
                "child_agent": e.agent_id,
                "child_status_code": e.status_code,
                "reason": str(e)
            }
        )

        raise HTTPException(
            status_code=e.status_code,
            detail={
                "error": str(e),
                "error_code": "CHILD_AGENT_DENIED",
                "child_agent": e.agent_id,
                "child_status_code": e.status_code,
                "conversation_id": conversation_id,
                "request_id": request_id,
                "session_id": session_id
            }
        )

    except SecurityException as e:
        logger.warning(
            "Security validation failed",
            extra={
                "request_id": request_id,
                "session_id": session_id,
                "error": str(e),
                "matched_rules": e.matched_rules
            }
        )
        raise HTTPException(
            status_code=403,
            detail={
                "error": str(e),
                "error_code": "SECURITY_VALIDATION_FAILED",
                "session_id": session_id,
                "request_id": request_id,
                "matched_rules": e.matched_rules
            }
        )

    except Exception as e:
        logger.exception(
            "Internal error processing query",
            extra={
                "request_id": request_id,
                "session_id": session_id,
                "error": str(e)
            }
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Internal server error",
                "error_code": "INTERNAL_ERROR",
                "session_id": session_id,
                "request_id": request_id
            }
        )

    finally:
        # Clear request context
        clear_request_context()


@router.post("/v1/agents/payment/action", response_model=AgentResponse)
async def handle_action(request: AgentRequest) -> AgentResponse:
    """
    Handle natural language actions (write operations like refunds)

    Same flow as /query but for write operations.
    Uses same Claude processing pipeline with security validation.

    Args:
        request: Agent request with natural language message

    Returns:
        Natural language response from agent

    Raises:
        HTTPException: 403 if security denied, 500 if internal error
    """
    request_id = str(uuid.uuid4())
    session_id = request.session_id or str(uuid.uuid4())

    # Multi-agent context: extract or generate conversation_id
    conversation_id = request.context.get('conversation_id') or f"conv-{uuid.uuid4().hex[:12]}"
    parent_request_id = request.context.get('parent_request_id')
    caller_agent_id = request.context.get('caller_agent_id')
    call_depth = request.context.get('call_depth', 0)

    logger.info(
        "Action request received",
        extra={
            "request_id": request_id,
            "session_id": session_id,
            "conversation_id": conversation_id,
            "call_depth": call_depth,
            "message_length": len(request.message)
        }
    )

    try:
        # Set request context for @secured_tool decorator
        set_request_context(
            request_id=request_id,
            session_id=session_id,
            user_input=request.message,
            context=request.context
        )

        # Set multi-agent context
        set_multi_agent_context(
            conversation_id=conversation_id,
            parent_request_id=parent_request_id,
            caller_agent_id=caller_agent_id,
            call_depth=call_depth
        )

        # Process with Claude (same as query)
        response = process_with_claude(
            message=request.message,
            session_id=session_id,
            request_id=request_id
        )

        logger.info(
            "Action request completed",
            extra={
                "request_id": request_id,
                "session_id": session_id,
                "response_length": len(response.get("text", ""))
            }
        )

        return AgentResponse(
            response=response["text"],
            data=response.get("data", {}),
            session_id=session_id,
            request_id=request_id
        )

    except ToolDeniedError as e:
        # BUG-001 FIX: Child agent denied request - propagate denial
        logger.warning(
            "Child agent denied request in multi-agent workflow",
            extra={
                "request_id": request_id,
                "session_id": session_id,
                "conversation_id": conversation_id,
                "child_agent": e.agent_id,
                "child_status_code": e.status_code,
                "reason": str(e)
            }
        )

        raise HTTPException(
            status_code=e.status_code,
            detail={
                "error": str(e),
                "error_code": "CHILD_AGENT_DENIED",
                "child_agent": e.agent_id,
                "child_status_code": e.status_code,
                "conversation_id": conversation_id,
                "request_id": request_id,
                "session_id": session_id
            }
        )

    except SecurityException as e:
        logger.warning(
            "Security validation failed",
            extra={
                "request_id": request_id,
                "session_id": session_id,
                "error": str(e),
                "matched_rules": e.matched_rules
            }
        )
        raise HTTPException(
            status_code=403,
            detail={
                "error": str(e),
                "error_code": "SECURITY_VALIDATION_FAILED",
                "session_id": session_id,
                "request_id": request_id,
                "matched_rules": e.matched_rules
            }
        )

    except Exception as e:
        logger.exception(
            "Internal error processing action",
            extra={
                "request_id": request_id,
                "session_id": session_id,
                "error": str(e)
            }
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Internal server error",
                "error_code": "INTERNAL_ERROR",
                "session_id": session_id,
                "request_id": request_id
            }
        )

    finally:
        # Clear request context
        clear_request_context()

