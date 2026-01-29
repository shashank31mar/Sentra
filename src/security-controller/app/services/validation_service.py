"""
Validation Service - Orchestrator for Tool Call Validation

Orchestrates the 5-step validation pipeline by delegating to individual validators.
Manages session updates and response generation.

Architecture:
- This service is the orchestrator only
- Individual validators are in app/validators/ (Tasks 4-8)
- Keeps business logic modular and testable
"""
import time
import secrets
import logging
from typing import Dict, Optional

from app.api.models import ValidationRequest, ValidationResult
from app.utils.session_manager import SessionManager, SessionUpdateError

logger = logging.getLogger(__name__)


class ValidationService:
    """
    Orchestrates the 5-step validation pipeline.
    
    Delegates to individual validators (to be implemented in Tasks 4-8):
    - TrustChecker (Step 1) - app/validators/trust_checker.py
    - PolicyEngine (Step 2) - app/validators/policy_engine.py
    - SigmaEngine (Step 3) - app/validators/sigma_engine.py
    - ContextValidator (Step 4) - app/validators/context_validator.py
    - AbuseDetector (Step 5) - app/validators/abuse_detector.py
    
    Handles:
    - Session management
    - Trust score updates
    - Action ID generation
    - Response formatting
    """
    
    def __init__(self):
        self.session_manager = SessionManager()
        
        # Validators (Tasks 4-8)
        from app.validators.trust_checker import TrustChecker
        from app.validators.policy_engine import PolicyEngine
        from app.validators.cross_agent_validator import CrossAgentValidator
        from app.validators.sigma_engine import SigmaEngine
        from app.validators.context_validator import ContextValidator
        from app.validators.abuse_detector import AbuseDetector
        
        self.trust_checker = TrustChecker()  # Task 4 ✅
        self.policy_engine = PolicyEngine()  # Task 5 ✅
        self.cross_agent_validator = CrossAgentValidator()  # Workstream 12 ✅
        self.sigma_engine = SigmaEngine()  # Task 6 ✅
        self.context_validator = ContextValidator()  # Task 7 ✅
        self.abuse_detector = AbuseDetector()  # Task 8 ✅
        
        # Audit logging and metrics (Task 9)
        from app.utils.audit_logger import AuditLogger
        from app.utils.metrics_publisher import MetricsPublisher
        
        self.audit_logger = AuditLogger()  # Task 9 ✅
        self.metrics_publisher = MetricsPublisher()  # Task 9 ✅
    
    async def validate_tool_call(self, request: ValidationRequest) -> Dict:
        """
        Main validation pipeline orchestrator.
        
        Args:
            request: Validation request with tool call details
            
        Returns:
            Dict with decision (ALLOW/DENY), trust_score, latency, etc.
        """
        start_time = time.time()
        
        try:
            # Load or create session
            session = await self.session_manager.get_or_create_session(
                request.session_id,
                user_id="unknown",  # Will be populated by agents
                agent_id=request.agent_id
            )
            
            # Run 5-step validation pipeline
            validation_result = await self._run_validation_pipeline(request, session)
            
            # Handle DENY
            if validation_result.should_deny:
                return await self._handle_deny(
                    request,
                    session,
                    validation_result,
                    start_time
                )
            
            # Handle ALLOW
            return await self._handle_allow(
                request,
                session,
                start_time
            )
            
        except SessionUpdateError as e:
            logger.exception(f"Session update error: {e}")
            return self._create_error_response(
                request.session_id,
                "Session management error",
                start_time
            )
        except Exception as e:
            logger.exception(f"Validation pipeline error: {e}")
            return self._create_error_response(
                request.session_id,
                "Internal validation error",
                start_time
            )
    
    async def _run_validation_pipeline(
        self,
        request: ValidationRequest,
        session: Dict
    ) -> ValidationResult:
        """
        Execute 5-step validation pipeline.
        Short-circuits on first DENY.
        
        Returns:
            ValidationResult with decision and details
        """
        # ============================================================
        # STEP 1: Trust Score Check (Task 4 ✅)
        # ============================================================
        trust_result = await self.trust_checker.check(session, request)
        if trust_result.should_deny:
            return trust_result
        
        # ============================================================
        # STEP 2: Policy Engine (Task 5 ✅)
        # ============================================================
        policy_result = await self.policy_engine.validate(request)
        if policy_result.should_deny:
            return policy_result
        
        # ============================================================
        # STEP 2.5: Cross-Agent Validator (Workstream 12 ✅)
        # ============================================================
        cross_agent_result = await self.cross_agent_validator.validate(request)
        if cross_agent_result.should_deny:
            return cross_agent_result
        
        # ============================================================
        # STEP 3: Sigma Rule Engine (Task 6 ✅)
        # ============================================================
        sigma_result = await self.sigma_engine.match_rules(request.user_input)
        if sigma_result.should_deny:
            return sigma_result
        
        # ============================================================
        # STEP 4: Context Validator (Task 7 ✅)
        # ============================================================
        context_result = await self.context_validator.validate_sequence(session, request)
        if context_result.should_deny:
            return context_result
        
        # ============================================================
        # STEP 5: Abuse Detector (Task 8 ✅)
        # ============================================================
        # Get policy for rate limit check
        policy = await self.policy_engine.get_agent_policy(request.agent_id)
        abuse_result = await self.abuse_detector.check_rate_limit(session, policy)
        if abuse_result.should_deny:
            return abuse_result
        
        # All checks passed
        return ValidationResult(
            decision="ALLOW",
            reason="All validation checks passed",
            should_deny=False
        )
    
    async def _handle_deny(
        self,
        request: ValidationRequest,
        session: Dict,
        validation_result: ValidationResult,
        start_time: float
    ) -> Dict:
        """
        Handle DENY decision - update trust score and return response.
        """
        # Update trust score with penalty
        violation_type = (
            validation_result.violation_type or
            validation_result.threat_type or
            "VALIDATION_FAILED"
        )
        
        updated_session = await self.session_manager.update_trust_score_deny(
            request.session_id,
            violation_type,
            validation_result.reason
        )
        
        latency_ms = (time.time() - start_time) * 1000
        
        logger.warning(
            f"DENY: session={request.session_id}, agent={request.agent_id}, "
            f"tool={request.tool_name}, violation={violation_type}, "
            f"trust_score={updated_session['trust_score']:.1f}, "
            f"latency={latency_ms:.1f}ms"
        )
        
        response = {
            "decision": "DENY",
            "reason": validation_result.reason,
            "trust_score": updated_session['trust_score'],
            "session_id": request.session_id,
            "latency_ms": latency_ms,
            "violation_type": violation_type
        }
        
        # Add threat-specific fields if present
        if validation_result.threat_type:
            response["threat_type"] = validation_result.threat_type
        if validation_result.matched_rule:
            response["matched_rule"] = validation_result.matched_rule
        if validation_result.severity:
            response["severity"] = validation_result.severity
        
        # Task 9: Write audit log (fire-and-forget)
        await self.audit_logger.log_decision(
            decision="DENY",
            request=request.model_dump(),
            session=session,
            validation_result=validation_result.model_dump(),
            latency_ms=latency_ms
        )

        # NOTE (2025-12-02): Metrics publishing removed from here.
        # Metrics should be published by agents AFTER actual execution,
        # not during validation. See Milestone 4 in workstream-9.

        return response
    
    async def _handle_allow(
        self,
        request: ValidationRequest,
        session: Dict,
        start_time: float
    ) -> Dict:
        """
        Handle ALLOW decision - update trust score and return response.
        """
        # Update session with ALLOW
        updated_session = await self.session_manager.update_trust_score_allow(
            request.session_id,
            request.tool_name
        )
        
        # Generate action_id for reversible actions
        action_id = self._generate_action_id(request)
        
        latency_ms = (time.time() - start_time) * 1000
        
        logger.info(
            f"ALLOW: session={request.session_id}, agent={request.agent_id}, "
            f"tool={request.tool_name}, trust_score={updated_session['trust_score']:.1f}, "
            f"latency={latency_ms:.1f}ms"
        )
        
        # Task 9: Write audit log (fire-and-forget)
        await self.audit_logger.log_decision(
            decision="ALLOW",
            request=request.model_dump(),
            session=session,
            validation_result=None,
            latency_ms=latency_ms
        )

        # NOTE (2025-12-02): Metrics publishing removed from here.
        # Metrics should be published by agents AFTER actual execution,
        # not during validation. See Milestone 4 in workstream-9.

        return {
            "decision": "ALLOW",
            "reason": "All validation checks passed",
            "trust_score": updated_session['trust_score'],
            "session_id": request.session_id,
            "latency_ms": latency_ms,
            "action_id": action_id
        }
    
    def _generate_action_id(self, request: ValidationRequest) -> Optional[str]:
        """
        Generate unique action ID for reversible actions.
        
        Format: act-{tool_name}-{timestamp}-{random_hex}
        Example: act-process_refund-1737201635-a7b3c9
        
        Args:
            request: Validation request
            
        Returns:
            Action ID string or None if not reversible
        """
        # Only generate for WRITE operations on reversible tools
        if request.operation_type == "WRITE" and request.tool_name in ["process_refund"]:
            timestamp = int(time.time())
            random_hex = secrets.token_hex(3)
            return f"act-{request.tool_name}-{timestamp}-{random_hex}"
        
        return None
    
    def _create_error_response(
        self,
        session_id: str,
        reason: str,
        start_time: float
    ) -> Dict:
        """
        Create error response for system failures.
        Fail-secure: always returns DENY.
        """
        return {
            "decision": "DENY",
            "reason": reason,
            "trust_score": 0.0,
            "session_id": session_id,
            "latency_ms": (time.time() - start_time) * 1000,
            "violation_type": "SYSTEM_ERROR"
        }
