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
from typing import Dict, List, Optional

from app.api.models import ValidationRequest, ValidationResult
from app.config import settings
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
        from app.validators.ml_classifier import MLClassifierValidator

        self.trust_checker = TrustChecker()  # Task 4 ✅
        self.policy_engine = PolicyEngine()  # Task 5 ✅
        self.cross_agent_validator = CrossAgentValidator()  # Workstream 12 ✅
        self.sigma_engine = SigmaEngine()  # Task 6 ✅
        # Workstream 15: inject policy_engine so context_validator can resolve
        # cross_cloud_dependencies from the agent's policy.
        self.context_validator = ContextValidator(policy_engine=self.policy_engine)  # Task 7 ✅ + W15
        self.abuse_detector = AbuseDetector()  # Task 8 ✅
        # Workstream 19 / LLD 19: ML threat classifier. Disabled by default via
        # settings.ml_classifier_enabled; instance is still created so the loader
        # logs surface "validator present, flag off" instead of "validator missing".
        self.ml_classifier = MLClassifierValidator()  # WS19 ✅
        
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
            
            # Run 5-step validation pipeline. signals[] collects every
            # validator's contribution (Workstream 17 / LLD 17 §3.2). The
            # final ValidationResult is the verdict (short-circuited DENY
            # or full-pipeline ALLOW); signals[] is the full breakdown for
            # the audit logger's dual-write and the dashboard's "By" column.
            validation_result, signals = await self._run_validation_pipeline(request, session)

            # Handle DENY
            if validation_result.should_deny:
                return await self._handle_deny(
                    request,
                    session,
                    validation_result,
                    start_time,
                    signals=signals,
                )

            # Handle ALLOW — pass the validation_result so cross-cloud fields
            # (platform, cloud_region) on it can be surfaced in the response.
            return await self._handle_allow(
                request,
                session,
                start_time,
                validation_result=validation_result,
                signals=signals,
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
    ):
        """
        Execute 5-step validation pipeline.
        Short-circuits on first DENY.

        Returns:
            (ValidationResult, list[Signal]) — the verdict plus every
            validator's contribution captured for the audit dual-write.
            Workstream 17 / LLD 17 §3.2.
        """
        # Collect every Signal produced by validators that ran. On a
        # short-circuit DENY this list is the prefix up to and including
        # the denier; on full-pipeline ALLOW it contains all six.
        signals = []

        def _capture(result: ValidationResult):
            """Append the validator's signal to the run's collection.

            Abstain results (LLD 17 §4, LLD 19 §5.2) emit NO signal — the
            combiner treats absence as "this producer wasn't on the path."
            Used by the ML classifier on Bedrock outage / disabled / very-low
            confidence so the combiner falls back to sigma + policy alone.
            """
            if result.is_abstain:
                return result
            try:
                signal = result.to_signal()
                if signal is not None:
                    signals.append(signal)
            except ValueError as exc:
                # Defensive: a validator that didn't apply @stamps would land
                # here. Log loudly so the gap is fixed, but don't break the
                # pipeline — fall back to a synthetic Signal so audit dual-
                # write still has something to write.
                logger.warning(
                    "validator emitted unstamped result; using synthetic signal: %s",
                    exc,
                )
            return result

        # ============================================================
        # STEP 1: Trust Score Check (Task 4 ✅)
        # ============================================================
        # KNOWN GAP (WS15 M2 review, Issue #6): a trust-check DENY here returns
        # before policy_engine runs, so the response carries platform=None and
        # cloud_region=None UNLESS the interceptor (Bedrock Lambda / Azure
        # Function) already stamped them on the inbound request. The downstream
        # `_handle_deny` does fall back to request.platform / request.cloud_region,
        # so interceptors that send those fields produce correct audit entries.
        # If a future interceptor doesn't, the trust-check-DENY audit row will
        # be missing the cross-cloud columns. Accepted gap; document in audit
        # query tooling so consumers know "platform=NULL on a trust DENY" is
        # not a data corruption — it's a quarantined session that bypassed
        # policy lookup. Fixing properly would require trust_checker to fetch
        # the policy itself, adding latency to every validation call.
        trust_result = _capture(await self.trust_checker.check(session, request))
        if trust_result.should_deny:
            return trust_result, signals

        # ============================================================
        # STEP 2: Policy Engine (Task 5 ✅)
        # ============================================================
        policy_result = _capture(await self.policy_engine.validate(request))
        if policy_result.should_deny:
            return policy_result, signals
        # Workstream 15: capture cross-cloud fields from the policy result so
        # they can be propagated onto every downstream result (DENY or ALLOW).
        platform_from_policy = policy_result.platform
        cloud_region_from_policy = policy_result.cloud_region

        def _stamp(result: ValidationResult) -> ValidationResult:
            """Attach the policy-derived cross-cloud fields to a result that
            didn't natively carry them (sigma, context, abuse, cross-agent)."""
            if result.platform is None:
                result.platform = platform_from_policy
            if result.cloud_region is None:
                result.cloud_region = cloud_region_from_policy
            return result

        # ============================================================
        # STEP 2.5: Cross-Agent Validator (Workstream 12 ✅)
        # ============================================================
        cross_agent_result = _capture(await self.cross_agent_validator.validate(request))
        if cross_agent_result.should_deny:
            return _stamp(cross_agent_result), signals

        # ============================================================
        # STEP 3: Sigma Rule Engine (Task 6 ✅)
        # ============================================================
        sigma_result = _capture(await self.sigma_engine.match_rules(request.user_input))
        if sigma_result.should_deny:
            return _stamp(sigma_result), signals

        # ============================================================
        # STEP 3.5: ML Threat Classifier (Workstream 19 / LLD 19)
        # ============================================================
        # Slotted AFTER sigma deliberately: sigma is ~50ms deterministic; ML is
        # ~600ms LLM. Running sigma first lets us short-circuit on known patterns
        # without paying the ML latency tax (LLD 19 deviation from §3.1's
        # parallel-gather diagram — the actual pipeline is sequential with
        # short-circuit-on-DENY, and that's more efficient for the attack path).
        # When the flag is off (default), this validator returns ABSTAIN with
        # zero Bedrock cost.
        ml_result = _capture(await self.ml_classifier.validate(request))
        # Shadow mode (WS19 M3): the validator ran and its Signal is already in
        # signals[] via _capture, but we MUST NOT let its DENY short-circuit the
        # pipeline — the combined verdict has to fall back to sigma + policy
        # alone so we can measure ML's incremental value against the real
        # customer-facing decision. Live = should_deny respected; shadow =
        # should_deny ignored (signal still recorded for offline analysis).
        if ml_result.should_deny and not settings.ml_classifier_shadow_mode:
            return _stamp(ml_result), signals

        # ============================================================
        # STEP 4: Context Validator (Task 7 ✅)
        # ============================================================
        context_result = _capture(await self.context_validator.validate_sequence(session, request))
        if context_result.should_deny:
            return _stamp(context_result), signals

        # ============================================================
        # STEP 5: Abuse Detector (Task 8 ✅)
        # ============================================================
        # Get policy for rate limit check
        policy = await self.policy_engine.get_agent_policy(request.agent_id)
        abuse_result = _capture(await self.abuse_detector.check_rate_limit(session, policy))
        if abuse_result.should_deny:
            return _stamp(abuse_result), signals

        # All checks passed. Workstream 15: propagate platform + cloud_region
        # captured from the policy result so downstream response/audit-log code
        # can surface them uniformly with the DENY path.
        return ValidationResult(
            decision="ALLOW",
            reason="All validation checks passed",
            should_deny=False,
            platform=platform_from_policy,
            cloud_region=cloud_region_from_policy,
        ), signals
    
    async def _handle_deny(
        self,
        request: ValidationRequest,
        session: Dict,
        validation_result: ValidationResult,
        start_time: float,
        signals: Optional[List] = None,
    ) -> Dict:
        """
        Handle DENY decision - update trust score and return response.

        signals: list of Signal objects produced during the pipeline run.
            Workstream 17 / LLD 17 — forwarded to audit_logger.log_signals
            for the DDB + CloudWatch dual-write.
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

        # Workstream 15: surface cross-cloud fields. Prefer the policy-derived
        # values stashed on validation_result; fall back to interceptor-supplied
        # request hints. If neither is present (e.g., early trust_checker DENY
        # on a session with no resolved policy yet), leave as null.
        platform = validation_result.platform or request.platform
        cloud_region = validation_result.cloud_region or request.cloud_region
        if platform:
            response["platform"] = platform
        if cloud_region:
            response["cloud_region"] = cloud_region
        
        # Audit dual-write — Workstream 17. log_signals routes both
        # DDB and CloudWatch; log_decision is now a thin back-compat wrapper.
        if signals:
            await self.audit_logger.log_signals(
                request=request.model_dump(),
                session=session,
                signals=signals,
                latency_ms=latency_ms,
            )
        else:
            await self.audit_logger.log_decision(
                decision="DENY",
                request=request.model_dump(),
                session=session,
                validation_result=validation_result.model_dump(),
                latency_ms=latency_ms,
            )

        # NOTE (2025-12-02): Metrics publishing removed from here.
        # Metrics should be published by agents AFTER actual execution,
        # not during validation. See Milestone 4 in workstream-9.

        return response
    
    async def _handle_allow(
        self,
        request: ValidationRequest,
        session: Dict,
        start_time: float,
        validation_result: Optional[ValidationResult] = None,
        signals: Optional[List] = None,
    ) -> Dict:
        """
        Handle ALLOW decision - update trust score and return response.

        Workstream 15: validation_result carries policy-derived platform and
        cloud_region (populated by policy_engine + propagated through the
        pipeline). Surfaced in the response when present.
        """
        # Update session with ALLOW. Workstream 15: pass agent_id so the tool
        # history records which agent invoked the tool, enabling cross-cloud
        # dependency validation downstream.
        updated_session = await self.session_manager.update_trust_score_allow(
            request.session_id,
            request.tool_name,
            agent_id=request.agent_id,
        )
        
        # Generate action_id for reversible actions
        action_id = self._generate_action_id(request)
        
        latency_ms = (time.time() - start_time) * 1000
        
        logger.info(
            f"ALLOW: session={request.session_id}, agent={request.agent_id}, "
            f"tool={request.tool_name}, trust_score={updated_session['trust_score']:.1f}, "
            f"latency={latency_ms:.1f}ms"
        )
        
        # Audit dual-write — Workstream 17.
        if signals:
            await self.audit_logger.log_signals(
                request=request.model_dump(),
                session=session,
                signals=signals,
                latency_ms=latency_ms,
            )
        else:
            await self.audit_logger.log_decision(
                decision="ALLOW",
                request=request.model_dump(),
                session=session,
                validation_result=None,
                latency_ms=latency_ms,
            )

        # NOTE (2025-12-02): Metrics publishing removed from here.
        # Metrics should be published by agents AFTER actual execution,
        # not during validation. See Milestone 4 in workstream-9.

        response = {
            "decision": "ALLOW",
            "reason": "All validation checks passed",
            "trust_score": updated_session['trust_score'],
            "session_id": request.session_id,
            "latency_ms": latency_ms,
            "action_id": action_id,
        }

        # Workstream 15: surface policy-derived cross-cloud fields when
        # available. Prefer validation_result; fall back to interceptor hints.
        platform = (validation_result.platform if validation_result else None) or request.platform
        cloud_region = (validation_result.cloud_region if validation_result else None) or request.cloud_region
        if platform:
            response["platform"] = platform
        if cloud_region:
            response["cloud_region"] = cloud_region

        return response
    
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
