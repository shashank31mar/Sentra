"""
Trust Checker - Step 1 of Validation Pipeline

Checks trust score and quarantine status before allowing operations.
Implements fail-fast logic for suspended/quarantined sessions.

TODO: Implement in Task 4
Requirements: LLD 03 Section 3.1, 6.2, 8.1
"""
import logging
from typing import Dict

from app.api.models import ValidationRequest, ValidationResult

logger = logging.getLogger(__name__)


class TrustChecker:
    """
    Validates trust score and quarantine status.
    
    Rules:
    - Suspended (trust_score < 10): DENY all operations
    - Quarantined (10 <= trust_score < 40): DENY WRITE, ALLOW READ
    - Warning (40 <= trust_score < 70): ALLOW all + alerts
    - Active (trust_score >= 70): ALLOW all
    """
    
    def __init__(self):
        # Configuration
        self.SUSPEND_THRESHOLD = 10.0
        self.QUARANTINE_THRESHOLD = 40.0
        self.WARNING_THRESHOLD = 70.0
    
    async def check(self, session: Dict, request: ValidationRequest) -> ValidationResult:
        """
        Check trust score and quarantine status.
        
        Args:
            session: Session data from DynamoDB
            request: Validation request
            
        Returns:
            ValidationResult with decision (ALLOW/DENY)
        """
        try:
            trust_score = session.get('trust_score', 100.0)
            quarantine_status = session.get('quarantine_status', 'active')
            
            logger.debug(
                f"Trust check for session {session.get('session_id')}: "
                f"trust_score={trust_score}, status={quarantine_status}, "
                f"operation={request.operation_type}"
            )
            
            # Check 1: Suspended sessions (trust_score < 10) - DENY ALL
            if quarantine_status == "suspended":
                logger.warning(
                    f"Session {session.get('session_id')} is SUSPENDED "
                    f"(trust_score={trust_score})"
                )
                return ValidationResult(
                    decision="DENY",
                    reason=f"Session suspended due to low trust score ({trust_score:.1f})",
                    violation_type="SESSION_SUSPENDED",
                    penalty=0,  # Already at minimum
                    should_deny=True
                )
            
            # Check 2: Quarantined sessions (10 <= trust_score < 40) - DENY WRITE only
            if quarantine_status == "quarantined" and request.operation_type == "WRITE":
                logger.warning(
                    f"Session {session.get('session_id')} is QUARANTINED - "
                    f"blocking WRITE operation (trust_score={trust_score})"
                )
                return ValidationResult(
                    decision="DENY",
                    reason=f"Write operations blocked while quarantined (trust_score={trust_score:.1f})",
                    violation_type="QUARANTINE_WRITE_BLOCKED",
                    penalty=0,  # Don't penalize further
                    should_deny=True
                )
            
            # All checks passed
            logger.debug(f"Trust check PASSED for session {session.get('session_id')}")
            return ValidationResult(
                decision="ALLOW",
                reason="Trust score check passed",
                should_deny=False
            )
            
        except Exception as e:
            logger.exception(f"Trust checker error: {e}")
            # Fail-secure: deny on errors
            return ValidationResult(
                decision="DENY",
                reason="Trust score check failed",
                violation_type="SYSTEM_ERROR",
                penalty=-10,
                should_deny=True
            )
