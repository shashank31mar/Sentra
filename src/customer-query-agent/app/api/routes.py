"""
API Routes for Customer Query Agent
POST /v1/agents/customer-query/query - Read operations (Claude-based)
POST /v1/agents/customer-query/action - Write operations (Claude-based)
"""

import logging
import uuid
import time
from typing import Dict, Any, Optional
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.claude_processor import process_with_claude
from app.security_integration import (
    set_request_context,
    set_multi_agent_context,
    clear_request_context,
    SecurityException
)
from app.exceptions import ToolDeniedError

logger = logging.getLogger(__name__)

# Create API router
router = APIRouter()


# ==================== Request/Response Models ====================

class AgentRequest(BaseModel):
    """Unified agent request model"""
    message: str = Field(..., min_length=1, max_length=10000, description="Natural language message")
    session_id: Optional[str] = Field(None, description="Session identifier (auto-generated if not provided)")
    context: Dict[str, Any] = Field(default_factory=dict, description="Additional context (user_id, authorization_level, etc.)")

    class Config:
        json_schema_extra = {
            "example": {
                "message": "Show me all customers from California",
                "session_id": "session-demo-001",
                "context": {
                    "user_id": "manager@sentra.com",
                    "authorization_level": "manager"
                }
            }
        }


class AgentResponse(BaseModel):
    """Unified agent response model"""
    response: str = Field(..., description="Natural language response from agent")
    data: Dict[str, Any] = Field(default_factory=dict, description="Optional structured data")
    session_id: str = Field(..., description="Session identifier")
    request_id: str = Field(..., description="Request identifier")

    class Config:
        json_schema_extra = {
            "example": {
                "response": "I found 150 customers from California.",
                "data": {"count": 150},
                "session_id": "session-demo-001",
                "request_id": "req-abc-123"
            }
        }


class AgentError(BaseModel):
    """Unified agent error model"""
    error: str = Field(..., description="Error message")
    error_code: str = Field(..., description="Error code")
    session_id: str = Field(..., description="Session identifier")
    request_id: str = Field(..., description="Request identifier")
    matched_rules: list = Field(default_factory=list, description="Matched security rules (if applicable)")

    class Config:
        json_schema_extra = {
            "example": {
                "error": "Security validation failed: Prompt injection detected",
                "error_code": "SECURITY_VALIDATION_FAILED",
                "session_id": "session-demo-001",
                "request_id": "req-abc-123",
                "matched_rules": [
                    {
                        "rule_id": "LLM_JAILBREAK_001",
                        "title": "LLM Jailbreak Attempt"
                    }
                ]
            }
        }


# ==================== Helper Functions ====================

def _generate_request_id() -> str:
    """Generate unique request ID"""
    return f"req-cqa-{uuid.uuid4().hex[:12]}"


def _generate_session_id() -> str:
    """Generate unique session ID"""
    return f"session-cqa-{uuid.uuid4().hex[:12]}"


# ==================== Endpoints ====================

@router.post("/v1/agents/customer-query/query", response_model=AgentResponse)
async def handle_query(request: AgentRequest) -> AgentResponse:
    """
    Handle natural language queries (read operations)

    Flow:
    1. Generate request_id and session_id (if missing)
    2. Set request context for security validation
    3. Process message with Claude (Bedrock)
    4. Claude determines which tools to call
    5. For each tool: validate with Security Controller → execute
    6. Return natural language response

    Args:
        request: Agent request with message and optional session_id/context

    Returns:
        AgentResponse with natural language response and optional structured data

    Raises:
        HTTPException: 400 (validation error), 403 (security denial), 500 (internal error)
    """
    # Generate IDs
    request_id = _generate_request_id()
    session_id = request.session_id or _generate_session_id()

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
            "message_length": len(request.message),
            "has_context": bool(request.context)
        }
    )

    try:
        # Set request context for security validation
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
        result = process_with_claude(
            message=request.message,
            session_id=session_id,
            request_id=request_id
        )

        logger.info(
            "Query request successful",
            extra={
                "request_id": request_id,
                "session_id": session_id,
                "response_length": len(result['text'])
            }
        )

        return AgentResponse(
            response=result['text'],
            data=result.get('data', {}),
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

        # Propagate same status code as child agent (403, 429, etc.)
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
        # Security Controller denied action
        logger.warning(
            "Query request denied by Security Controller",
            extra={
                "request_id": request_id,
                "session_id": session_id,
                "reason": str(e),
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

    except ValueError as e:
        # Validation error (e.g., invalid parameters)
        logger.error(
            "Query request validation error",
            extra={
                "request_id": request_id,
                "session_id": session_id,
                "error": str(e)
            }
        )

        raise HTTPException(
            status_code=400,
            detail={
                "error": str(e),
                "error_code": "VALIDATION_ERROR",
                "session_id": session_id,
                "request_id": request_id
            }
        )

    except Exception as e:
        # Internal error
        logger.exception(
            "Query request failed with internal error",
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


@router.post("/v1/agents/customer-query/action", response_model=AgentResponse)
async def handle_action(request: AgentRequest) -> AgentResponse:
    """
    Handle natural language actions (write operations)

    Note: For Customer Query Agent, this endpoint has the same implementation
    as /query since this agent is primarily read-only. The endpoint exists for
    consistency with the unified agent interface.

    For agents with write operations (e.g., Payment Agent), this endpoint would
    have stricter validation and use different tools.

    Flow: Same as /query endpoint

    Args:
        request: Agent request with message and optional session_id/context

    Returns:
        AgentResponse with natural language response and optional structured data

    Raises:
        HTTPException: 400 (validation error), 403 (security denial), 500 (internal error)
    """
    # Generate IDs
    request_id = _generate_request_id()
    session_id = request.session_id or _generate_session_id()

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
            "message_length": len(request.message),
            "has_context": bool(request.context)
        }
    )

    try:
        # Set request context for security validation
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

        # Process with Claude (same as query endpoint for CQA)
        result = process_with_claude(
            message=request.message,
            session_id=session_id,
            request_id=request_id
        )

        logger.info(
            "Action request successful",
            extra={
                "request_id": request_id,
                "session_id": session_id,
                "response_length": len(result['text'])
            }
        )

        return AgentResponse(
            response=result['text'],
            data=result.get('data', {}),
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

        # Propagate same status code as child agent (403, 429, etc.)
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
        # Security Controller denied action
        logger.warning(
            "Action request denied by Security Controller",
            extra={
                "request_id": request_id,
                "session_id": session_id,
                "reason": str(e),
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

    except ValueError as e:
        # Validation error
        logger.error(
            "Action request validation error",
            extra={
                "request_id": request_id,
                "session_id": session_id,
                "error": str(e)
            }
        )

        raise HTTPException(
            status_code=400,
            detail={
                "error": str(e),
                "error_code": "VALIDATION_ERROR",
                "session_id": session_id,
                "request_id": request_id
            }
        )

    except Exception as e:
        # Internal error
        logger.exception(
            "Action request failed with internal error",
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
