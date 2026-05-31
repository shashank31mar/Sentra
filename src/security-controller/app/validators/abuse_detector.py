"""
Abuse Detector - Step 5 of Validation Pipeline

Implements rate limiting to prevent abuse.
Simple per-session rate limiting with per-minute counter reset.

Requirements: LLD 03 Section 3.5, 8.1
"""
import logging
import time
from typing import Dict

from app.api.models import ValidationRequest, ValidationResult
from app.combiners import Source
from app.validators._signal_stamp import stamps

logger = logging.getLogger(__name__)


class AbuseDetector:
    """
    Detects abuse through rate limiting.

    MVP Implementation:
    - Per-session rate limiting (NOT per-user)
    - Simple per-minute counter with reset
    - Limitation: User can bypass by creating multiple sessions

    Phase 2 Enhancement:
    - Track by user_id across all sessions
    - Cross-session rate limiting
    - More sophisticated abuse patterns
    """

    def __init__(self):
        pass

    @stamps(Source.SENTRA_ABUSE)
    async def check_rate_limit(
        self, session: Dict, policy: Dict
    ) -> ValidationResult:
        """
        Check if session has exceeded rate limit.

        Args:
            session: Session data with abuse_counters
            policy: Agent policy with max_calls_per_minute

        Returns:
            ValidationResult with decision (ALLOW/DENY)
        """
        try:
            current_time = int(time.time())
            current_minute = current_time // 60

            # Get abuse counters from session
            abuse_counters = session.get("abuse_counters", {})
            calls_this_minute = abuse_counters.get("calls_this_minute", 0)
            last_minute_reset = abuse_counters.get("last_minute_reset", 0)

            # Get rate limit from policy
            max_calls_per_minute = policy.get("max_calls_per_minute", 100)

            logger.debug(
                f"Rate limit check: session={session.get('session_id')}, "
                f"calls={calls_this_minute}/{max_calls_per_minute}, "
                f"current_minute={current_minute}, last_reset={last_minute_reset}"
            )

            # Check if we're in a new minute
            if last_minute_reset != current_minute:
                # New minute - reset counter
                calls_this_minute = 1
                logger.debug(
                    f"New minute detected, resetting counter to 1 "
                    f"(was {abuse_counters.get('calls_this_minute', 0)})"
                )
            else:
                # Same minute - increment counter
                calls_this_minute += 1

            # Check if limit exceeded
            if calls_this_minute > max_calls_per_minute:
                logger.warning(
                    f"Rate limit exceeded: {calls_this_minute}/{max_calls_per_minute} "
                    f"calls/min for session {session.get('session_id')}"
                )
                return ValidationResult(
                    decision="DENY",
                    reason=f"Rate limit exceeded: {calls_this_minute}/{max_calls_per_minute} calls/min",
                    violation_type="RATE_LIMIT_EXCEEDED",
                    penalty=-10,
                    should_deny=True,
                )

            # Within limit - update counters in session (will be persisted by caller)
            session["abuse_counters"] = {
                "calls_this_minute": calls_this_minute,
                "last_minute_reset": current_minute,
            }

            logger.debug(
                f"Rate limit check passed: {calls_this_minute}/{max_calls_per_minute}"
            )
            return ValidationResult(
                decision="ALLOW",
                reason="Within rate limit",
                should_deny=False,
            )

        except Exception as e:
            logger.exception(f"Abuse detection error: {e}")
            # Fail-secure: deny on errors
            return ValidationResult(
                decision="DENY",
                reason="Rate limit check failed",
                violation_type="SYSTEM_ERROR",
                penalty=-10,
                should_deny=True,
            )
