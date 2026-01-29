"""
Security Controller Integration - @secured_tool Decorator
Sentra MVP - Workstream 7

This module provides the @secured_tool decorator that integrates with the
Security Controller to validate all tool calls before execution.
"""

import functools
import logging
import time
from typing import Callable, Any, Optional, Dict
from contextvars import ContextVar

import requests
import os

logger = logging.getLogger(__name__)

# ==================== Context Variables ====================
# These hold request-scoped data (request_id, session_id, user_input, context)

_request_id: ContextVar[Optional[str]] = ContextVar('request_id', default=None)
_session_id: ContextVar[Optional[str]] = ContextVar('session_id', default=None)
_user_input: ContextVar[Optional[str]] = ContextVar('user_input', default=None)
_request_context: ContextVar[Optional[Dict]] = ContextVar('request_context', default=None)


# ==================== Context Helpers ====================

def set_request_context(request_id: str, session_id: str, user_input: str, context: Dict = None):
    """Set request-scoped context for security validation"""
    _request_id.set(request_id)
    _session_id.set(session_id)
    _user_input.set(user_input)
    _request_context.set(context or {})


def get_current_request_id() -> Optional[str]:
    """Get current request ID from context"""
    return _request_id.get()


def get_current_session_id() -> Optional[str]:
    """Get current session ID from context"""
    return _session_id.get()


def get_current_user_input() -> Optional[str]:
    """Get current user input from context"""
    return _user_input.get()


def get_current_context() -> Dict:
    """Get current request context"""
    return _request_context.get() or {}


# ==================== Multi-Agent Context Helpers ====================

def set_multi_agent_context(
    conversation_id: str,
    parent_request_id: Optional[str] = None,
    caller_agent_id: Optional[str] = None,
    call_depth: int = 0
):
    """Add multi-agent fields to existing request context"""
    context = get_current_context()
    context['conversation_id'] = conversation_id
    context['parent_request_id'] = parent_request_id
    context['caller_agent_id'] = caller_agent_id
    context['call_depth'] = call_depth
    _request_context.set(context)


def get_conversation_id() -> Optional[str]:
    """Get conversation_id from context"""
    return get_current_context().get('conversation_id')


def get_call_depth() -> int:
    """Get call depth from context (default 0)"""
    return get_current_context().get('call_depth', 0)


def clear_request_context():
    """Clear request-scoped context"""
    _request_id.set(None)
    _session_id.set(None)
    _user_input.set(None)
    _request_context.set(None)


# ==================== Security Exception ====================

class SecurityException(Exception):
    """Exception raised when Security Controller denies action"""

    def __init__(self, message: str, matched_rules: list = None, decision: dict = None):
        super().__init__(message)
        self.matched_rules = matched_rules or []
        self.decision = decision or {}


# ==================== Retry Decorator ====================

def retry_with_exponential_backoff(max_retries: int = 3, base_delay: float = 1.0):
    """
    Decorator for retrying functions with exponential backoff

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds (doubles each retry)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                    if attempt == max_retries - 1:
                        # Last attempt failed, raise the error
                        raise

                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        f"Security Controller request failed (attempt {attempt + 1}/{max_retries}), "
                        f"retrying in {delay}s",
                        extra={"error": str(e), "attempt": attempt + 1}
                    )
                    time.sleep(delay)
            return None
        return wrapper
    return decorator


# ==================== Security Controller Client ====================

@retry_with_exponential_backoff(max_retries=3, base_delay=1.0)
def call_security_controller(validation_request: Dict) -> Dict:
    """
    Call Security Controller /v1/validate endpoint with retry logic

    Args:
        validation_request: Validation request payload

    Returns:
        Validation decision from Security Controller

    Raises:
        SecurityException: If Security Controller denies the action
        requests.exceptions.RequestException: If request fails after retries
    """
    security_controller_url = os.environ.get(
        'SECURITY_CONTROLLER_URL',
        'http://security-controller.sentra.internal:8080'
    )

    logger.info(
        "Calling Security Controller for validation",
        extra={
            "request_id": validation_request.get("request_id"),
            "session_id": validation_request.get("session_id"),
            "tool_name": validation_request.get("tool_name")
        }
    )

    response = requests.post(
        f"{security_controller_url}/v1/validate",
        json=validation_request,
        timeout=5.0  # 5 second timeout
    )

    if response.status_code != 200:
        logger.error(
            f"Security Controller returned non-200 status: {response.status_code}",
            extra={
                "status_code": response.status_code,
                "response": response.text
            }
        )
        raise SecurityException(
            f"Security Controller error: HTTP {response.status_code}",
            decision={"decision": "ERROR", "reason": f"HTTP {response.status_code}"}
        )

    decision = response.json()

    logger.info(
        "Security Controller validation complete",
        extra={
            "request_id": validation_request.get("request_id"),
            "decision": decision.get("decision"),
            "matched_rules": decision.get("matched_rules", [])
        }
    )

    return decision


# ==================== @secured_tool Decorator ====================

def secured_tool(func: Callable) -> Callable:
    """
    Decorator that validates tool calls with Security Controller before execution

    Flow:
    1. Intercept function call
    2. Build validation request from context + function args
    3. Send validation request to Security Controller
    4. If ALLOW → execute function and return result
    5. If DENY → raise SecurityException (do NOT execute function)
    6. Log audit trail

    Usage:
        @secured_tool
        def query_customers(filters: dict) -> list:
            # Tool implementation
            pass

    Raises:
        SecurityException: If Security Controller denies the action
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Get current request context
        request_id = get_current_request_id()
        session_id = get_current_session_id()
        user_input = get_current_user_input()
        context = get_current_context()

        agent_id = os.environ.get('SERVICE_NAME', 'customer-query-agent')

        # Determine operation type based on tool name
        # READ tools: query, get, list, check
        # WRITE tools: process, update, delete, create, reverse
        tool_name_lower = func.__name__.lower()
        if any(prefix in tool_name_lower for prefix in ['query', 'get', 'list', 'check', 'search', 'find']):
            operation_type = 'READ'
        else:
            operation_type = 'WRITE'

        # Build context with additional validation data (includes multi-agent fields)
        validation_context = {
            # User context
            "authorization_level": context.get("authorization_level", "standard"),
            "user_id": context.get("user_id"),
            "ip_address": context.get("ip_address"),
            "previous_actions": context.get("previous_actions", []),
            # Multi-agent context
            "conversation_id": context.get("conversation_id"),
            "parent_request_id": context.get("parent_request_id"),
            "caller_agent_id": context.get("caller_agent_id"),
            "call_depth": context.get("call_depth", 0)
        }

        # Build validation request (must match ValidationRequest schema)
        validation_request = {
            "request_id": request_id,
            "session_id": session_id,
            "agent_id": agent_id,
            "tool_name": func.__name__,
            "tool_params": kwargs,  # Only kwargs (named parameters)
            "user_input": user_input,
            "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),  # ISO 8601 UTC
            "operation_type": operation_type,
            "context": validation_context
        }

        logger.info(
            f"Validating tool call: {func.__name__}",
            extra={
                "request_id": request_id,
                "session_id": session_id,
                "tool_name": func.__name__,
                "tool_params": kwargs
            }
        )

        try:
            # Call Security Controller for validation
            decision = call_security_controller(validation_request)

            # Check decision
            if decision.get('decision') == 'DENY':
                reason = decision.get('reason', 'Security policy violation')
                matched_rules = decision.get('matched_rules', [])

                logger.warning(
                    f"Security Controller DENIED tool call: {func.__name__}",
                    extra={
                        "request_id": request_id,
                        "session_id": session_id,
                        "tool_name": func.__name__,
                        "reason": reason,
                        "matched_rules": matched_rules
                    }
                )

                raise SecurityException(
                    f"Security validation failed: {reason}",
                    matched_rules=matched_rules,
                    decision=decision
                )

            # Decision is ALLOW - execute the tool function
            logger.info(
                f"Security Controller ALLOWED tool call: {func.__name__}",
                extra={
                    "request_id": request_id,
                    "session_id": session_id,
                    "tool_name": func.__name__
                }
            )

            result = func(*args, **kwargs)

            logger.info(
                f"Tool executed successfully: {func.__name__}",
                extra={
                    "request_id": request_id,
                    "session_id": session_id,
                    "tool_name": func.__name__
                }
            )

            return result

        except SecurityException:
            # Re-raise SecurityException (already logged above)
            raise

        except requests.exceptions.RequestException as e:
            # Security Controller communication error
            logger.error(
                f"Failed to communicate with Security Controller",
                extra={
                    "request_id": request_id,
                    "session_id": session_id,
                    "tool_name": func.__name__,
                    "error": str(e)
                }
            )
            raise SecurityException(
                f"Security Controller unavailable: {str(e)}",
                decision={"decision": "ERROR", "reason": "Controller unavailable"}
            )

        except Exception as e:
            # BUG-001 FIX: Don't log ToolDeniedError as unexpected error
            # It's expected in multi-agent workflows
            from app.exceptions import ToolDeniedError
            if isinstance(e, ToolDeniedError):
                # Re-raise without logging as error (already logged by call_payment_agent)
                raise

            # Unexpected error during validation or execution
            logger.exception(
                f"Unexpected error during secured tool execution: {func.__name__}",
                extra={
                    "request_id": request_id,
                    "session_id": session_id,
                    "tool_name": func.__name__,
                    "error": str(e)
                }
            )
            raise

    return wrapper
