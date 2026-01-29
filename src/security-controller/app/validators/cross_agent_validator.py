"""
Cross-Agent Validator - Step 2.5 of Validation Pipeline

Validates inter-agent calls to prevent privilege escalation and infinite recursion.

Checks:
1. Call depth limit (prevent infinite loops)
2. Caller authorization (is caller in target's allowed_callers?)

Requirements: LLD 12 Section 4.2
Workstream: 12 - Multi-Agent Workflow (Milestone 2)
"""
import logging
from typing import Optional

from app.api.models import ValidationRequest, ValidationResult

logger = logging.getLogger(__name__)

# Structured logging prefix for CloudWatch filtering
LOG_PREFIX = "[WS12-M2-CROSS-AGENT]"


class CrossAgentValidator:
    """
    Validates cross-agent calls.

    Runs AFTER PolicyEngine (Step 2) but before SigmaEngine (Step 3).
    Only applies when caller_agent_id is present in request context.
    """

    MAX_CALL_DEPTH = 5

    def __init__(self):
        # Import here to avoid circular dependency
        from app.validators.policy_engine import PolicyEngine
        self.policy_engine = PolicyEngine()

    async def validate(self, request: ValidationRequest) -> ValidationResult:
        """
        Validate cross-agent call.

        Args:
            request: Validation request with context

        Returns:
            ValidationResult (ALLOW if valid, DENY if invalid)
        """
        # Extract multi-agent context
        context = request.context or {}
        caller_agent_id = context.get('caller_agent_id')
        parent_request_id = context.get('parent_request_id')
        call_depth = context.get('call_depth', 0)

        # No cross-agent call - skip validation
        if not caller_agent_id or not parent_request_id:
            logger.debug(
                f"{LOG_PREFIX} Not a cross-agent call, skipping validation",
                extra={
                    "request_id": request.request_id,
                    "agent_id": request.agent_id
                }
            )
            return ValidationResult(
                decision="ALLOW",
                reason="Not a cross-agent call",
                should_deny=False
            )

        logger.info(
            f"{LOG_PREFIX} Validating cross-agent call",
            extra={
                "request_id": request.request_id,
                "caller": caller_agent_id,
                "target": request.agent_id,
                "call_depth": call_depth,
                "parent_request_id": parent_request_id,
                "workstream": "12",
                "milestone": "2"
            }
        )

        # Check 1: Call depth limit
        if call_depth > self.MAX_CALL_DEPTH:
            logger.warning(
                f"{LOG_PREFIX} DENY - Call depth exceeded maximum",
                extra={
                    "request_id": request.request_id,
                    "caller": caller_agent_id,
                    "target": request.agent_id,
                    "call_depth": call_depth,
                    "max_call_depth": self.MAX_CALL_DEPTH,
                    "decision": "DENY",
                    "violation_type": "MAX_CALL_DEPTH_EXCEEDED"
                }
            )
            return ValidationResult(
                decision="DENY",
                reason=f"Max call depth exceeded ({call_depth} > {self.MAX_CALL_DEPTH})",
                violation_type="MAX_CALL_DEPTH_EXCEEDED",
                penalty=-20,
                should_deny=True
            )

        # Check 2: Is caller authorized to invoke this agent?
        try:
            policy = await self.policy_engine.get_agent_policy(request.agent_id)
        except Exception as e:
            logger.exception(
                f"{LOG_PREFIX} Failed to load policy for target agent",
                extra={
                    "target_agent": request.agent_id,
                    "caller": caller_agent_id
                }
            )
            return ValidationResult(
                decision="DENY",
                reason=f"Failed to load agent policy for {request.agent_id}",
                violation_type="POLICY_LOAD_ERROR",
                penalty=-15,
                should_deny=True
            )

        # Get allowed callers from target agent's policy
        # Empty list = allow all (backward compatible with existing policies)
        allowed_callers = policy.get('allowed_callers', [])

        # Empty list means open policy - allow any caller
        if not allowed_callers:
            logger.info(
                f"{LOG_PREFIX} ALLOW - Cross-agent call authorized (open policy)",
                extra={
                    "caller": caller_agent_id,
                    "target": request.agent_id,
                    "decision": "ALLOW",
                    "reason": "open_policy"
                }
            )
            return ValidationResult(
                decision="ALLOW",
                reason="Cross-agent call authorized (open policy)",
                should_deny=False
            )

        # Check if caller is in allowed list or wildcard
        if caller_agent_id in allowed_callers or '*' in allowed_callers:
            logger.info(
                f"{LOG_PREFIX} ALLOW - Cross-agent call authorized",
                extra={
                    "caller": caller_agent_id,
                    "target": request.agent_id,
                    "allowed_callers": allowed_callers,
                    "decision": "ALLOW"
                }
            )
            return ValidationResult(
                decision="ALLOW",
                reason="Cross-agent call authorized",
                should_deny=False
            )

        # Caller not authorized
        logger.warning(
            f"{LOG_PREFIX} DENY - Unauthorized cross-agent call",
            extra={
                "caller": caller_agent_id,
                "target": request.agent_id,
                "allowed_callers": allowed_callers,
                "decision": "DENY",
                "violation_type": "UNAUTHORIZED_CROSS_AGENT_CALL"
            }
        )
        return ValidationResult(
            decision="DENY",
            reason=f"Agent '{caller_agent_id}' not authorized to call '{request.agent_id}'",
            violation_type="UNAUTHORIZED_CROSS_AGENT_CALL",
            penalty=-25,
            should_deny=True
        )
