"""
Validation Service - Orchestrator for Tool Call Validation

Orchestrates the 6-step deterministic validation pipeline (trust → policy →
cross-agent → prompt-signature → context → abuse, then ML-last) via the WS-C
cost-annotated DAG scheduler (FR-2.8 / ADR-030), delegating to individual
validators. Manages session updates and response generation.

Architecture:
- This service is the orchestrator only
- Individual validators are in app/validators/ (Tasks 4-8)
- Keeps business logic modular and testable
"""
import time
import secrets
import logging
import asyncio
import contextvars
from typing import Dict, List, Optional

from app.api.models import ValidationRequest, ValidationResult
from app.config import settings
from app.utils import tenancy
from app.utils.session_manager import SessionManager, SessionUpdateError

logger = logging.getLogger(__name__)


# --- M1 latency instrumentation (LLD 24 / WS24) ---------------------------------
# Per-request per-step wall-clock timings, kept in a contextvar so concurrent
# requests don't collide (each request runs in its own asyncio task → its own
# copy). Wrap any awaited step in `_timed("label", coro)`; emitted once per
# request as the structured `validation.timing` log line.
_step_timings: "contextvars.ContextVar" = contextvars.ContextVar("step_timings", default=None)


async def _timed(label: str, coro):
    """Await `coro`, recording its elapsed ms under `label` in the per-request
    timings dict (no-op if instrumentation isn't initialized for this request)."""
    t = time.perf_counter()
    try:
        return await coro
    finally:
        d = _step_timings.get()
        if d is not None:
            d[label] = round((time.perf_counter() - t) * 1000, 1)


# Background telemetry (WS24 M4.2): audit + metrics are emitted OFF the response
# path so the ALLOW/DENY returns immediately. Tasks are retained in a module-level
# set (a bare create_task can be GC'd mid-flight) and a done-callback logs any
# failure — telemetry must never surface to the caller. The CloudWatch dual-write
# (best-practices §12.5) and the DDB signal write still run, just asynchronously;
# crash-durability is the WS24 M7 shipper's job.
_bg_tasks: "set" = set()
# Soft cap: a large backlog means CloudWatch/DDB is slow and telemetry tasks are
# accumulating (memory + connection pressure). We warn rather than drop — losing a
# security-audit write is worse than the backlog — and the M7 durable shipper
# removes this in-process queue entirely.
_BG_TASKS_SOFT_CAP = 1000


# --- WS-I I2.2: fail-secure DENY for the legacy-retired end state -----------------
# A new, distinct violation type (NOT POLICY_ERROR) so the audit trail separates
# "Cedar evaluator errored" from "no .cedar co-artifact while legacy is retired"
# (LLD 28 §4.3). Dangerous-tier penalty −15, matching POLICY_NOT_FOUND/POLICY_DISABLED.
POLICY_NOT_MIGRATED = "POLICY_NOT_MIGRATED"
_POLICY_NOT_MIGRATED_PENALTY = -15


def _fail_secure_deny(violation_type: str, penalty: int, reason: str) -> ValidationResult:
    """Build a fail-secure DENY ValidationResult in the engine `_deny` shape
    (engine.py:238). Used when Cedar abstains under `legacy_retired` — there is no
    legacy engine left to fall back to, so the safe verdict is DENY, not allow."""
    return ValidationResult(
        decision="DENY", reason=reason, violation_type=violation_type,
        violated_policy=None, penalty=penalty, should_deny=True)


def _append_signal(signals: List, result: ValidationResult) -> None:
    """Append a validator's Signal to the run's collection — Workstream 17 /
    LLD 17 §3.2. Shared by the DAG scheduler's `_capture` closure (LLD 31 §6.6)
    so signal-capture semantics are byte-for-byte identical wherever a node runs.

    Abstain results (LLD 17 §4, LLD 19 §5.2) emit NO signal — the combiner treats
    absence as "this producer wasn't on the path" (used by the ML classifier on
    Bedrock outage / disabled / very-low confidence so the combiner falls back to
    the deterministic frontier alone). A validator that forgot to @stamp its
    source lands in the ValueError branch: log loudly (the gap must be fixed) but
    never break the pipeline over a telemetry defect.
    """
    if result.is_abstain:
        return
    try:
        signal = result.to_signal()
        if signal is not None:
            signals.append(signal)
    except ValueError as exc:
        logger.warning(
            "validator emitted unstamped result; signal dropped: %s", exc,
        )


def _fire_and_forget(coro, label: str) -> None:
    if len(_bg_tasks) > _BG_TASKS_SOFT_CAP:
        logger.warning(
            "telemetry backlog high: %d pending background tasks "
            "(slow CloudWatch/DDB?)", len(_bg_tasks))
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)

    def _on_done(t: "asyncio.Task") -> None:
        _bg_tasks.discard(t)
        try:
            exc = t.exception()
        except asyncio.CancelledError:
            return
        if exc is not None:
            logger.warning("background %s task failed: %s", label, exc)

    task.add_done_callback(_on_done)


async def write_redacted_feedback(
    request: ValidationRequest,
    *,
    decision: str,
    reason: str,
    winning_source: str,
    detector_outcomes: Dict,
) -> None:
    """Off-path opt-in redacted-feedback write (WS-E2 / LLD 29 §6.5, E5.3).

    Fired fire-and-forget AFTER the verdict, ONLY for a content-bearing phase whose
    `content_text` has already passed the Tier-2 barrier (so it is the post-NER
    redacted view, `redacted=True`). Gated by the tenant's DPA-scoped opt-in flag
    (default OFF — a non-opted-in tenant writes NO record) and the stronger
    independent eval-gate (a residual → skip + `FeedbackRedactionGateFail`, never
    stored). NEVER blocks a verdict; swallows every error (a feedback-store hiccup
    must never surface). NOT the billing ledger (WS-H), NOT the audit store (LLD 17).

    Inert on the request phase and for un-opted-in tenants — the safe default. It
    composes automatically when the content-phase handlers wire this call site.
    """
    phase = getattr(request, "phase", "request") or "request"
    from app.api.models import _CONTENT_FIELD

    if phase not in _CONTENT_FIELD:
        return  # request phase carries no persistable free-text content
    try:
        from app.redaction.feedback_store import (
            FeedbackGateFail,
            FeedbackRecord,
            get_feedback_store,
            tenant_feedback_opt_in,
        )

        tenant_id = tenancy.current_tenant()
        opted_in = tenant_feedback_opt_in(tenant_id)
        if not opted_in:
            return  # §6.5: no record for a non-opted-in tenant (default OFF)

        content_text = getattr(request, "content_text", None)
        record = FeedbackRecord(
            tenant_id=tenant_id,
            phase=phase,
            redacted_payload={"content_text": content_text},
            decision=decision,
            reason=reason,
            winning_source=winning_source,
            detector_outcomes=detector_outcomes or {},
            ttl_days=settings.feedback_store_ttl_days,
        )
        # The barrier stamped `request.redacted`? For a content phase the barrier ran
        # and set content_text to the redacted view; the request-level `redacted`
        # flag is the provenance signal the store's redacted-only check reads.
        get_feedback_store().write_if_opted_in(
            record,
            opted_in=opted_in,
            redacted=bool(getattr(request, "redacted", False)),
            subject_key=(request.context or {}).get("subject_id") if request.context else None,
        )
    except FeedbackGateFail:
        # Eval-gate residual: the write is correctly SKIPPED (alarm already emitted
        # inside the store). Not an error to propagate.
        logger.warning("feedback eval-gate blocked a residual record; skipped (correct)")
    except Exception:  # noqa: BLE001 — feedback is off-path; never surface to caller
        logger.debug("redacted-feedback write skipped (non-blocking)", exc_info=True)


class ValidationService:
    """
    Orchestrates the 6-step deterministic validation pipeline (trust → policy →
    cross-agent → prompt-signature → context → abuse, then ML-last) via the
    WS-C DAG scheduler.

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
        from app.validators.sigma_engine import get_sigma_engine
        from app.validators.context_validator import ContextValidator
        from app.validators.abuse_detector import AbuseDetector
        from app.validators.ml_classifier import MLClassifierValidator

        self.trust_checker = TrustChecker()  # Task 4 ✅
        self.policy_engine = PolicyEngine()  # Task 5 ✅
        self.cross_agent_validator = CrossAgentValidator()  # Workstream 12 ✅
        # WS24 M3.2: shared singleton so a rule write (sigma_rules_service) can
        # write-through-invalidate this same enforcement cache.
        self.sigma_engine = get_sigma_engine()  # Task 6 ✅
        # Workstream 15: inject policy_engine so context_validator can resolve
        # cross_cloud_dependencies from the agent's policy.
        self.context_validator = ContextValidator(policy_engine=self.policy_engine)  # Task 7 ✅ + W15
        self.abuse_detector = AbuseDetector()  # Task 8 ✅
        # Workstream 19 / LLD 19: ML threat classifier. Disabled by default via
        # settings.ml_classifier_enabled; instance is still created so the loader
        # logs surface "validator present, flag off" instead of "validator missing".
        self.ml_classifier = MLClassifierValidator()  # WS19 ✅

        # Cedar policy engine (feature: cedar-policy). Constructed only when
        # enabled; it reuses self.policy_engine for binding resolution + cloud
        # stamping. In shadow mode it runs alongside the legacy engine at STEP 2
        # and records disagreements without affecting the live verdict (CT07).
        self.cedar_engine = None
        if settings.cedar_enabled:
            from app.validators.cedar.engine import CedarPolicyEngine
            self.cedar_engine = CedarPolicyEngine(policy_engine=self.policy_engine)

        # Audit logging and metrics (Task 9)
        from app.utils.audit_logger import AuditLogger
        from app.utils.metrics_publisher import MetricsPublisher
        
        self.audit_logger = AuditLogger()  # Task 9 ✅
        self.metrics_publisher = MetricsPublisher()  # Task 9 ✅

    def _emit_cedar_abstain_metric(self, *, denied: bool, agent_id: str) -> None:
        """WS-I I2.3: fire-and-forget the Cedar-abstain outcome metric. Guarded so a
        missing/partial metrics_publisher (e.g. in unit pipelines) NEVER turns a
        telemetry gap into a broken verdict — telemetry is off the response path."""
        publisher = getattr(self, "metrics_publisher", None)
        emit = getattr(publisher, "publish_cedar_abstain_metric", None)
        if emit is None:
            return
        try:
            _fire_and_forget(emit(
                denied=denied, agent_id=agent_id, tenant_id=tenancy.current_tenant()),
                "metrics")
        except Exception:  # noqa: BLE001 — telemetry must never block a verdict
            logger.debug("cedar-abstain metric emit skipped", exc_info=True)

    async def validate_tool_call(self, request: ValidationRequest) -> Dict:
        """
        Main validation pipeline orchestrator.
        
        Args:
            request: Validation request with tool call details
            
        Returns:
            Dict with decision (ALLOW/DENY), trust_score, latency, etc.
        """
        start_time = time.time()
        _step_timings.set({})  # M1 (LLD 24): start per-request step timing

        try:
            # Load or create session
            session = await _timed("session", self.session_manager.get_or_create_session(
                request.session_id,
                user_id="unknown",  # Will be populated by agents
                agent_id=request.agent_id
            ))

            # Run the 6-step deterministic pipeline (trust → policy →
            # cross-agent → prompt-signature → context → abuse) + ML-last via
            # the WS-C DAG scheduler. signals[] collects every
            # validator's contribution (Workstream 17 / LLD 17 §3.2). The
            # final ValidationResult is the verdict (short-circuited DENY
            # or full-pipeline ALLOW); signals[] is the full breakdown for
            # the audit logger's dual-write and the dashboard's "By" column.
            validation_result, signals = await _timed(
                "pipeline", self._run_validation_pipeline(request, session))

            # Handle DENY / ALLOW (handle = trust update + audit + metrics today;
            # see WS24 M4 for moving audit+metrics off this path).
            if validation_result.should_deny:
                response = await _timed("handle", self._handle_deny(
                    request,
                    session,
                    validation_result,
                    start_time,
                    signals=signals,
                ))
            else:
                # ALLOW — pass validation_result so cross-cloud fields
                # (platform, cloud_region) can be surfaced in the response.
                response = await _timed("handle", self._handle_allow(
                    request,
                    session,
                    start_time,
                    validation_result=validation_result,
                    signals=signals,
                ))

            # M1 (LLD 24 / WS24): single structured line with the per-step
            # breakdown so we can re-baseline post-singleton and target the
            # dominant cost (ML vs sigma vs policy vs the rest).
            logger.info(
                "validation.timing",
                extra={
                    "timing_ms": _step_timings.get() or {},
                    "total_ms": response.get("latency_ms"),
                    "decision": response.get("decision"),
                    "agent_id": request.agent_id,
                },
            )
            return response

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
    
    async def _run_policy_step(self, request: ValidationRequest) -> ValidationResult:
        """STEP 2 policy-engine selection — the Cedar cutover/shadow/legacy
        branch, extracted so the DAG scheduler's `sentra.policy` node runs it
        verbatim (WS-C / LLD 31 §5.3). The scheduler stays policy-engine-agnostic:
        Cedar-vs-legacy selection is encapsulated HERE, never flattened into the
        scheduler.

        Authoritative policy engine selection:
          * cedar_enabled & NOT shadow  → CedarPolicyEngine IS the decision (CT10 cutover).
          * cedar_enabled & shadow      → legacy decides; Cedar runs alongside, logs
                                          disagreements, no influence (CT07).
          * cedar disabled (default)    → legacy decides; Cedar never runs.
        Cedar fails secure on its own evaluator error (returns POLICY_ERROR DENY).
        A Cedar POLICY_ERROR stays a 200-DENY verdict (a considered decision, not
        an inability-to-evaluate); a genuine crash bubbles to the outer handler.

        Returns the policy ValidationResult (NOT captured — the node's `_capture`
        closure captures it and applies the short-circuit).
        """
        cedar = getattr(self, "cedar_engine", None)
        cutover = cedar is not None and settings.cedar_enabled and not settings.cedar_shadow_mode

        if cutover:
            policy_result = await _timed("policy", cedar.validate(request))
            if policy_result.is_abstain:
                if settings.legacy_retired:
                    # End state (FR-2.4 / LLD 28 §4.3): legacy is retired. An abstain
                    # here means a policy that SHOULD carry a .cedar co-artifact does
                    # not — a defect. There is no legacy engine to fall back to, so we
                    # fail SECURE to DENY (POLICY_NOT_MIGRATED), never permissively.
                    logger.error(
                        "Cedar abstained under legacy_retired for %s; fail-secure DENY",
                        request.agent_id)
                    self._emit_cedar_abstain_metric(denied=True, agent_id=request.agent_id)
                    policy_result = _fail_secure_deny(
                        violation_type=POLICY_NOT_MIGRATED,
                        penalty=_POLICY_NOT_MIGRATED_PENALTY,
                        reason="Policy not Cedar-migrated; legacy engine retired (fail-secure)")
                else:
                    # Rollout era (legacy_retired=false): keep the existing permissive
                    # fallback so there is never an un-enforced window during the
                    # CT08 backfill. This branch MUST stay byte-for-byte the legacy
                    # fallback — the existing test pins it (LLD 28 §14.1).
                    logger.info(
                        "Cedar abstained (not migrated) for %s; falling back to legacy engine",
                        request.agent_id)
                    self._emit_cedar_abstain_metric(denied=False, agent_id=request.agent_id)
                    policy_result = await _timed("policy_fallback", self.policy_engine.validate(request))
        else:
            policy_result = await _timed("policy", self.policy_engine.validate(request))
            # Cedar shadow comparison (CT07): run Cedar alongside, record any
            # disagreement, but the live decision stays the legacy engine's. Must
            # run BEFORE the should_deny short-circuit so both verdicts are
            # compared even on a policy DENY. Never raises — shadow is best-effort.
            if cedar is not None and settings.cedar_shadow_mode:
                await self._cedar_shadow_compare(request, policy_result)

        return policy_result

    async def _run_validation_pipeline(
        self,
        request: ValidationRequest,
        session: Dict
    ):
        """Run the validation pipeline via the cost-annotated DAG scheduler
        (WS-C / FR-2.8 / ADR-030 / LLD 31 §6).

        NO-FLAG cutover: the DAG is the ONLY pipeline — there is no
        scheduler-enable flag and no retained fixed-sequential body; rollback is
        git-revert + redeploy, not a config flip. The scheduler runs the tier-0
        cheap-deterministic frontier (short-circuit on the first DENY), then the
        tier-1 models parallel-gathered for tier-0 survivors, and returns the
        SAME `(ValidationResult, list[Signal])` contract the caller at
        validate_tool_call expects. Equivalence to the frozen golden baseline
        (T-EQUIV, ML ENFORCING) is on the final `(decision, should_deny,
        winning_source)` tuple — LLD 31 §3.

        Reuses this service's `_capture`/`_stamp`/`_timed` semantics so the return
        contract, per-node timing, abstain handling, and cross-cloud stamping are
        byte-for-byte what the pre-DAG pipeline emitted (LLD 31 §6.6).

        Returns:
            (ValidationResult, list[Signal]) — the verdict plus every validator's
            contribution captured for the audit dual-write (Workstream 17 / LLD 17
            §3.2).
        """
        from app.services import scheduler as scheduler_pkg
        from app.services.scheduler.run import FAIL_FAST, EVALUATE_ALL

        # signals[] collects every node's Signal (abstain → no signal). On a
        # tier-0 short-circuit DENY it is the prefix up to the denier; on the
        # all-ALLOW tail it holds every node that ran.
        signals: List = []

        def _capture(result: ValidationResult) -> ValidationResult:
            _append_signal(signals, result)
            return result

        # stamp_ctx is populated by the sentra.policy node's run with the
        # agent-sourced cross-cloud fields (reproduces the sequential
        # platform_from_policy / cloud_region_from_policy capture — agent-policy-
        # management §2.3/C2). Read by _stamp to attach them to downstream results.
        stamp_ctx: Dict = {"platform": None, "cloud_region": None}

        def _stamp(result: ValidationResult) -> ValidationResult:
            """Attach the agent-sourced cross-cloud fields to a result that didn't
            natively carry them (sigma, context, abuse, cross-agent, ML, D1-D7) —
            reused, not reimplemented (LLD 31 §6.6)."""
            if result.platform is None:
                result.platform = stamp_ctx.get("platform")
            if result.cloud_region is None:
                result.cloud_region = stamp_ctx.get("cloud_region")
            return result

        async def _timed_node(label: str, coro):
            # Per-node timing preserved so validation.timing still emits the
            # per-validator ms breakdown (LLD 24 M1 / LLD 31 §6.6).
            return await _timed(label, coro)

        def _all_allow() -> ValidationResult:
            # Reproduces the synthetic ALLOW at the sequential tail, carrying the
            # policy-sourced cross-cloud fields (was validation_service ALLOW's
            # platform_from_policy / cloud_region_from_policy).
            return ValidationResult(
                decision="ALLOW",
                reason="All validation checks passed",
                should_deny=False,
                platform=stamp_ctx.get("platform"),
                cloud_region=stamp_ctx.get("cloud_region"),
            )

        # Per-phase node selection (LLD 31 §5.4). WS-A adds the FR-3.4 `phase`
        # field to ValidationRequest (default "request"); if it has not landed,
        # degrade to request-only (getattr default). build_dag is looked up on
        # the package (not imported by name) so tests can patch the seam.
        phase = getattr(request, "phase", "request") or "request"
        nodes = scheduler_pkg.build_dag(self, phase, stamp_ctx)
        mode = settings.dag_run_mode if settings.dag_run_mode in (FAIL_FAST, EVALUATE_ALL) else FAIL_FAST

        return await scheduler_pkg.run_dag(
            nodes,
            request,
            session,
            _capture,
            _stamp,
            _timed_node,
            mode=mode,
            all_allow=_all_allow,
            signals=signals,
        )

    async def _cedar_shadow_compare(
        self, request: ValidationRequest, live_result: ValidationResult
    ) -> None:
        """Run CedarPolicyEngine in shadow and record any disagreement vs the
        legacy engine's `live_result` (CT07). Side-effect only: emits the
        `CedarShadowDiscrepancy` metric + a structured log. NEVER raises and
        NEVER touches the live verdict or the combiner's signals.

        Disagreement kinds (for CT09 triage):
          * ``cedar_abstain`` — agent not Cedar-migrated; not counted as a diff.
          * ``cedar_error``   — Cedar emitted POLICY_ERROR where legacy didn't.
          * ``verdict``       — ALLOW/DENY differ.
          * ``violation_type``— same verdict, different violation_type
                                (matters for invoke_agent reasons, §7 collapse).
          * ``none``          — agreement.
        """
        try:
            cedar_result = await self.cedar_engine.validate(request)

            if cedar_result.is_abstain:
                await self.metrics_publisher.publish_cedar_shadow_metric(
                    agreed=True, disagreement_kind="cedar_abstain")
                return

            live_deny = bool(live_result.should_deny)
            cedar_deny = bool(cedar_result.should_deny)

            if cedar_result.violation_type == "POLICY_ERROR" and live_result.violation_type != "POLICY_ERROR":
                kind = "cedar_error"
            elif live_deny != cedar_deny:
                kind = "verdict"
            elif live_deny and cedar_deny and live_result.violation_type != cedar_result.violation_type:
                kind = "violation_type"
            else:
                kind = "none"

            if kind != "none":
                logger.warning(
                    "Cedar shadow disagreement [%s] agent=%s tool=%s "
                    "legacy=(%s/%s/%s) cedar=(%s/%s/%s)",
                    kind, request.agent_id, request.tool_name,
                    live_result.decision, live_result.violation_type, live_result.violated_policy,
                    cedar_result.decision, cedar_result.violation_type, cedar_result.violated_policy,
                )

            await self.metrics_publisher.publish_cedar_shadow_metric(
                agreed=(kind == "none"), disagreement_kind=kind)
        except Exception:
            # Shadow must never break the live path.
            logger.exception("Cedar shadow comparison failed (non-blocking)")

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

        # WS-21 T01: emit DECISION metrics at validation time. This consciously
        # reverses the 2025-12-02 WS-9 M4 removal: that decision was about
        # *execution* metrics (did the agent's action succeed?), which belong
        # post-execution. These are *decision* metrics — what the controller
        # decided — which are correctly measured here. No post-execution emitter
        # exists, so there is no double-count. Emitted OFF the response path
        # (WS24 M4.2) — the DENY is already returning; metrics must not block it.
        #
        # WS-I I2.4 (LLD 28 §12): a POLICY_NOT_MIGRATED DENY is AUDIT-ONLY — it is
        # surfaced in the audit log + the CedarAbstainDenied metric (emitted at the
        # abstain branch), but EXCLUDED from the metered Decisions/quota series so a
        # missing-co-artifact defect cannot exhaust a victim tenant's budget. Mirrors
        # the identity-gate-DENY-not-metered intent. A flat console "decisions" panel
        # for these is the EXPECTED outcome, not a regression.
        if violation_type != POLICY_NOT_MIGRATED:
            _fire_and_forget(self.metrics_publisher.publish_validation_metrics(
                decision="DENY",
                latency_ms=latency_ms,
                agent_id=request.agent_id,
                trust_score=float(updated_session['trust_score']),
                threat_type=validation_result.threat_type,
                severity=validation_result.severity,
            ), "metrics")

        # Surface cross-cloud fields (agent-policy-management §2.3/C2: these are
        # AGENT-sourced — stamped from the registry by the policy engine, or by the
        # STEP 1 early-DENY path). Fall back to interceptor-supplied request hints.
        # Downstream audit_logger / decisions_service inherit these with no change.
        platform = validation_result.platform or request.platform
        cloud_region = validation_result.cloud_region or request.cloud_region
        if platform:
            response["platform"] = platform
        if cloud_region:
            response["cloud_region"] = cloud_region
        
        # Audit dual-write — Workstream 17 (DDB + CloudWatch). Off the response
        # path (WS24 M4.2); the dual-write still happens, just asynchronously.
        if signals:
            _fire_and_forget(self.audit_logger.log_signals(
                request=request.model_dump(),
                session=session,
                signals=signals,
                latency_ms=latency_ms,
            ), "audit")
        else:
            _fire_and_forget(self.audit_logger.log_decision(
                decision="DENY",
                request=request.model_dump(),
                session=session,
                validation_result=validation_result.model_dump(),
                latency_ms=latency_ms,
            ), "audit")

        # WS-E2 (LLD 29 §6.5) — off-path opt-in redacted-feedback write, fired
        # ALONGSIDE the audit write. Inert on the request phase / un-opted-in
        # tenants; composes when the content-phase handlers reach here.
        _fire_and_forget(write_redacted_feedback(
            request,
            decision="DENY",
            reason=validation_result.reason,
            winning_source=(validation_result.source or "sentra.combined"),
            detector_outcomes={"violation_type": violation_type},
        ), "feedback")

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
        
        # Audit dual-write — Workstream 17 (DDB + CloudWatch). Off the response
        # path (WS24 M4.2); the dual-write still happens, just asynchronously.
        if signals:
            _fire_and_forget(self.audit_logger.log_signals(
                request=request.model_dump(),
                session=session,
                signals=signals,
                latency_ms=latency_ms,
            ), "audit")
        else:
            _fire_and_forget(self.audit_logger.log_decision(
                decision="ALLOW",
                request=request.model_dump(),
                session=session,
                validation_result=None,
                latency_ms=latency_ms,
            ), "audit")

        # WS-E2 (LLD 29 §6.5) — off-path opt-in redacted-feedback write. Inert on
        # the request phase / un-opted-in tenants; composes when the content-phase
        # handlers reach here.
        _fire_and_forget(write_redacted_feedback(
            request,
            decision="ALLOW",
            reason="All validation checks passed",
            winning_source=((validation_result.source if validation_result else None) or "sentra.combined"),
            detector_outcomes={},
        ), "feedback")

        # WS-21 T01: emit DECISION metrics at validation time (see _handle_deny
        # for the WS-9 M4 reversal rationale — decision vs execution metrics).
        # Off the response path (WS24 M4.2).
        _fire_and_forget(self.metrics_publisher.publish_validation_metrics(
            decision="ALLOW",
            latency_ms=latency_ms,
            agent_id=request.agent_id,
            trust_score=float(updated_session['trust_score']),
        ), "metrics")

        response = {
            "decision": "ALLOW",
            "reason": "All validation checks passed",
            "trust_score": updated_session['trust_score'],
            "session_id": request.session_id,
            "latency_ms": latency_ms,
            "action_id": action_id,
        }

        # Surface agent-sourced cross-cloud fields (agent-policy-management
        # §2.3/C2). Prefer validation_result; fall back to interceptor hints.
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
