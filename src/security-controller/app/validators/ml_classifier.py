"""ML-based threat classifier — LLD 19.

Runs on every /v1/validate call (when enabled) as a peer of sigma_engine and
policy_engine. Emits one Signal(source=SENTRA_ML_CLASSIFIER) per call via the
@stamps plumbing (LLD 17 §4). Decisions combine via deny-overrides in the
existing combiner. Like every other validator in the chain, a DENY result
short-circuits the pipeline (validation_service._run_validation_pipeline);
this validator has no special "no-short-circuit" treatment — it's a peer.

Tiered execution (LLD 19 §5.2 + §4):
  - Hot path: Claude Haiku 4.5 via the aegionai-ml-classifier Application
    Inference Profile (LLD 19 §2.4 — isolates from the existing Bedrock-agent
    workload that already consumes Haiku/Sonnet quota with its own guardrail).
  - Escalation: Claude Sonnet 4.6 when Haiku confidence is in the borderline
    band. Sonnet has no co-tenancy concern, so it's invoked by foundation-model
    ID directly (no inference profile needed).

Total budget (LLD 19 §3.2.1, §8.1): hot + escalation combined cannot exceed
ML_CLASSIFIER_TOTAL_BUDGET_SECONDS. Per-tier timeout is the per-call ceiling;
the total budget is the pipeline-latency ceiling that bounds /v1/validate p99.

Fail mode is ABSTAIN — emit no signal so the combiner falls back to sigma +
policy alone (LLD 19 §9). Failing-DENY on Bedrock outage would translate a
99.9% Bedrock SLA into ~8h/year of customer downtime.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Optional

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from app.api.models import ValidationRequest, ValidationResult
from app.combiners import Source
from app.config import settings
from app.validators._signal_stamp import stamps
from app.validators.ml_classifier_prompts import SYSTEM_PROMPT, build_messages
from app.validators.ml_classifier_schema import TOOL_CHOICE, TOOL_NAME, TOOL_SPEC

logger = logging.getLogger(__name__)


# Never let the per-call timeout fall below this — sub-100ms is effectively
# "skip the call" and just wastes a request to Bedrock.
_MIN_PER_CALL_TIMEOUT_SEC = 0.1


class _ModelVerdict:
    """Parsed result of one Bedrock Converse invocation. Internal only —
    callers wrap this back into ValidationResult via _to_validation_result."""

    __slots__ = ("decision", "threat_type", "confidence", "reason", "model_id")

    def __init__(self, decision: str, threat_type: str, confidence: float, reason: str, model_id: str):
        self.decision = decision
        self.threat_type = threat_type
        self.confidence = confidence
        self.reason = reason
        self.model_id = model_id


class MLClassifierValidator:
    """LLM-driven semantic threat classifier."""

    def __init__(self, bedrock_client=None):
        # bedrock_client is injectable for tests; production resolves the
        # default boto3 client against the controller's task role + region.
        #
        # read/connect timeouts are set just slightly above the per-tier asyncio
        # timeout so the boto3 HTTP call aborts on its own rather than just the
        # asyncio wrapper cancelling — without this, asyncio.wait_for would
        # return but the underlying socket would keep the thread alive holding
        # an http connection (asyncio.to_thread futures aren't interruptible).
        # retries=0 because we want our own tiered escalation, not boto's
        # automatic same-tier retry.
        self.bedrock = bedrock_client or boto3.client(
            "bedrock-runtime",
            region_name=settings.aws_region,
            config=BotoConfig(
                read_timeout=settings.ml_classifier_timeout_seconds + 0.5,
                connect_timeout=2.0,
                retries={"max_attempts": 0, "mode": "standard"},
            ),
        )
        # Hot-path target: prefer the Application Inference Profile ARN (gives
        # workload-isolated cost/metrics/quota — LLD 19 §2.4). Fall back to the
        # raw foundation-model ID during early dev before the profile exists.
        self.hot_target = (
            settings.ml_classifier_inference_profile_arn
            or settings.ml_classifier_hot_model_id
        )
        # Escalation has no co-tenancy concern; always invoke by model ID.
        self.escalation_model_id = settings.ml_classifier_escalation_model_id
        self.trust_threshold = settings.ml_confidence_trust_threshold
        self.abstain_threshold = settings.ml_confidence_abstain_threshold
        self.timeout_seconds = settings.ml_classifier_timeout_seconds
        self.total_budget_seconds = settings.ml_classifier_total_budget_seconds

        # Startup sanity warning: in any non-local environment with the
        # validator ENABLED, a missing AIP ARN means we're invoking by
        # foundation-model ID, defeating the LLD 19 §2.4 workload-isolation
        # lever (no separate quota / cost / CloudWatch metrics from co-tenant
        # Bedrock consumers).
        #
        # Gated on ml_classifier_enabled so the warning doesn't fire when the
        # validator's instantiated-but-flag-off (the default — and the state
        # under pytest), where a missing ARN is moot. This avoids the pytest
        # noise problem AND keeps the warning firing if a real environment
        # happens to be named "test".
        env_name = (getattr(settings, "environment", "") or "").lower()
        if (
            settings.ml_classifier_enabled
            and not settings.ml_classifier_inference_profile_arn
            and env_name not in ("", "local", "dev-local")
        ):
            logger.warning(
                "ml_classifier: ML_CLASSIFIER_INFERENCE_PROFILE_ARN is empty in "
                "environment=%r with classifier ENABLED — falling back to "
                "foundation-model invocation. Workload isolation (LLD 19 §2.4) "
                "is NOT active; provision the aegionai-ml-classifier AIP and "
                "update the env var.",
                env_name,
            )

    # ----------------------------------------------------------------------
    # Public entrypoint
    # ----------------------------------------------------------------------

    @stamps(Source.SENTRA_ML_CLASSIFIER)
    async def validate(self, request: ValidationRequest) -> ValidationResult:
        # Feature flag — default off until eval harness signs off (WS19 M2).
        if not settings.ml_classifier_enabled:
            return ValidationResult.abstain("ml_classifier disabled")

        start = time.monotonic()

        def remaining() -> float:
            return self.total_budget_seconds - (time.monotonic() - start)

        # ----- Hot path (Haiku 4.5 via inference profile) -----
        hot_verdict = await self._invoke(
            self.hot_target,
            request,
            timeout=min(self.timeout_seconds, remaining()),
        )

        if hot_verdict is None:
            # Hot tier failed; try escalation if any budget remains.
            if remaining() <= _MIN_PER_CALL_TIMEOUT_SEC:
                return ValidationResult.abstain("budget exhausted after hot-path failure")
            esc = await self._invoke(
                self.escalation_model_id,
                request,
                timeout=min(self.timeout_seconds, remaining()),
            )
            if esc is None:
                return ValidationResult.abstain("both hot and escalation tiers failed")
            return self._to_validation_result(esc, model_used="escalation_only")

        # ----- Confident — accept Haiku verdict -----
        if hot_verdict.confidence >= self.trust_threshold:
            return self._to_validation_result(hot_verdict, model_used="hot")

        # ----- Out of budget — use Haiku despite low confidence -----
        if remaining() <= _MIN_PER_CALL_TIMEOUT_SEC:
            return self._to_validation_result(hot_verdict, model_used="hot_only_budget_exhausted")

        # ----- Ambiguous band [abstain_threshold, trust_threshold) — escalate -----
        if hot_verdict.confidence >= self.abstain_threshold:
            esc = await self._invoke(
                self.escalation_model_id,
                request,
                timeout=min(self.timeout_seconds, remaining()),
            )
            if esc is None:
                return self._to_validation_result(hot_verdict, model_used="hot_only_low_conf")
            return self._to_validation_result(esc, model_used="escalated")

        # ----- Very low confidence — escalate, but ABSTAIN if escalation
        # can't reach trust either.
        esc = await self._invoke(
            self.escalation_model_id,
            request,
            timeout=min(self.timeout_seconds, remaining()),
        )
        if esc is not None and esc.confidence >= self.trust_threshold:
            return self._to_validation_result(esc, model_used="escalated_from_abstain")
        esc_conf_str = f"{esc.confidence:.2f}" if esc is not None else "tier-failed"
        return ValidationResult.abstain(
            f"both hot+escalation low confidence "
            f"(hot={hot_verdict.confidence:.2f}, esc={esc_conf_str})"
        )

    # ----------------------------------------------------------------------
    # Bedrock plumbing
    # ----------------------------------------------------------------------

    async def _invoke(
        self,
        model_target: str,
        request: ValidationRequest,
        timeout: float,
    ) -> Optional[_ModelVerdict]:
        """Single Bedrock Converse call. Returns None on any failure so the
        caller can pivot to escalation or abstain. Wraps the sync boto3 client
        in asyncio.to_thread so the 600ms Bedrock RTT doesn't block the loop."""
        capped_timeout = max(_MIN_PER_CALL_TIMEOUT_SEC, timeout)
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(self._converse_sync, model_target, request),
                timeout=capped_timeout,
            )
        except asyncio.CancelledError:
            # Never swallow cancellation — the outer task or pipeline must be
            # able to abort the validator cleanly. CancelledError is a
            # BaseException in Py3.8+ so the bare-Exception branch below
            # already wouldn't catch it, but being explicit documents intent.
            raise
        except asyncio.TimeoutError:
            logger.warning(
                "ml_classifier %s: Bedrock call exceeded %.2fs",
                model_target, capped_timeout,
            )
            return None
        except (BotoCoreError, ClientError) as exc:
            # 4xx (quota/auth) → CRITICAL; 5xx + transport → WARNING. Both
            # ABSTAIN to keep customer traffic flowing (LLD 19 §9.1).
            level = logging.CRITICAL if _is_client_error(exc) else logging.WARNING
            logger.log(level, "ml_classifier %s: Bedrock error: %s", model_target, exc)
            return None
        except Exception:
            logger.exception("ml_classifier %s: unexpected error", model_target)
            return None

        return self._parse_verdict(response, model_target)

    def _converse_sync(self, model_target: str, request: ValidationRequest) -> dict:
        """Synchronous Bedrock Converse call. Called via asyncio.to_thread
        from _invoke so the event loop stays free during the ~600ms RTT.

        `model_target` is either an Application Inference Profile ARN (hot
        path) or a foundation-model ID (escalation). Converse accepts either
        in the `modelId` field — Bedrock resolves the routing target.
        """
        return self.bedrock.converse(
            modelId=model_target,
            system=[{"text": SYSTEM_PROMPT}],
            messages=build_messages(
                tool_name=request.tool_name,
                tool_params=request.tool_params or {},
                user_input=request.user_input,
                agent_id=request.agent_id,
            ),
            toolConfig={
                "tools": [TOOL_SPEC],
                "toolChoice": TOOL_CHOICE,
            },
            inferenceConfig={
                "maxTokens": 512,
                # Temperature=0.0 only (no topP). Haiku 4.5 rejects both being
                # set simultaneously with "temperature and top_p cannot both be
                # specified for this model" — pick one. Temperature wins because
                # we want deterministic classification, not nucleus sampling.
                "temperature": 0.0,
            },
        )

    def _parse_verdict(self, response: dict, model_target: str) -> Optional[_ModelVerdict]:
        """Extract the emit_security_verdict tool call from the Converse
        response. tool-use + forced toolChoice guarantees this exists; if it
        doesn't, treat as a parse failure (ABSTAIN)."""
        try:
            content = response["output"]["message"]["content"]
        except (KeyError, TypeError):
            logger.warning("ml_classifier %s: malformed response shape: %r", model_target, response)
            return None

        tool_input: Optional[dict] = None
        for block in content:
            tool_use = block.get("toolUse") if isinstance(block, dict) else None
            if tool_use and tool_use.get("name") == TOOL_NAME:
                tool_input = tool_use.get("input")
                # Some SDKs return input as a JSON string; normalize.
                if isinstance(tool_input, str):
                    try:
                        tool_input = json.loads(tool_input)
                    except json.JSONDecodeError:
                        logger.warning(
                            "ml_classifier %s: toolUse input was non-JSON string",
                            model_target,
                        )
                        return None
                break

        if not isinstance(tool_input, dict):
            logger.warning(
                "ml_classifier %s: response did not call %s tool",
                model_target, TOOL_NAME,
            )
            return None

        try:
            return _ModelVerdict(
                decision=tool_input["decision"],
                threat_type=tool_input["threat_type"],
                confidence=float(tool_input["confidence"]),
                reason=str(tool_input["reason"]),
                model_id=model_target,
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "ml_classifier %s: tool input missing/invalid field: %s",
                model_target, exc,
            )
            return None

    # ----------------------------------------------------------------------
    # Mapping
    # ----------------------------------------------------------------------

    def _to_validation_result(self, verdict: _ModelVerdict, *, model_used: str) -> ValidationResult:
        """Map a parsed model verdict into the ValidationResult shape the
        pipeline + audit log expect."""
        is_deny = verdict.decision == "DENY"
        # Threat_type is the stable contract (LLD 19 §2.3) — surface it on the
        # ValidationResult so the dashboard expander + scenario assertions
        # can match on threat_type rather than the model-generated reason text.
        threat_type = verdict.threat_type if verdict.threat_type != "NONE" else None

        return ValidationResult(
            decision=verdict.decision,
            reason=verdict.reason,
            violation_type=threat_type,
            threat_type=threat_type,
            penalty=(-10 if is_deny else 0),
            should_deny=is_deny,
            confidence=verdict.confidence,
            metadata={
                "model_used": model_used,
                "model_id": verdict.model_id,
            },
        )


def _is_client_error(exc: Exception) -> bool:
    """Bedrock 4xx (quota / auth / invalid params) → page on-call. 5xx +
    transport errors → warning only (transient, retry/abstain)."""
    if not isinstance(exc, ClientError):
        return False
    code = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return isinstance(code, int) and 400 <= code < 500
