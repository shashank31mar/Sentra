"""CedarPolicyEngine (CT04) — the Cedar-backed replacement for the authorization
step of `policy_engine.PolicyEngine`.

It produces a `ValidationResult` shaped EXACTLY like the legacy engine's — same
`decision`, `violation_type`, `violated_policy`, and **`penalty`** — because
`penalty` drives trust scoring (`audit_logger.py`), and a flat penalty would
silently drift quarantine timing. The full contract it reproduces (verified
against `policy_engine.py`):

    UNAUTHORIZED_TOOL                              —                          -15
    POLICY_VIOLATION       max_refund_amount       (the ONLY -10 tier)        -10
    POLICY_VIOLATION       high_fraud_identity_block                          -15
    INVALID_AGENT_INVOCATION (missing target, pre-Cedar)                      -15
    UNAUTHORIZED_AGENT_INVOCATION                  —                          -15
    POLICY_NOT_FOUND / POLICY_DISABLED             —                          -15
    POLICY_ERROR (evaluator / fail-secure catch-all)                         -15

`invoke_agent` is the one tool that is NOT a 1:1 port: it is TWO `isAuthorized`
calls AND-ed (UseTool on Tool::"invoke_agent" ∈ allowed_tools, then InvokeAgent
on Agent::target ∈ allowed_agents), with a structural pre-check for a missing
target. Call-1 wins on disagreement (matches the legacy check order: tool-auth
first, then target). The determining-policy set collapses to a singular
`violated_policy` for the audit reason.

Scope: this engine reproduces ONLY `policy_engine`'s authorization step. Cross-
cloud sequence enforcement (`cross_cloud_dependencies`) and rate limiting stay in
`context_validator`/`abuse_detector` — `policy_engine` never enforced them, so
neither does Cedar; this keeps strict parity. Moving the "Cedar decides, pipeline
computes" cross-cloud model (feature §5) into Cedar is a future enhancement and is
intentionally NOT implemented (see baseline-v1.cedar).
"""
from __future__ import annotations

import logging
from typing import Optional

from app.api.models import ValidationRequest, ValidationResult
from app.combiners import Source
from app.utils import tenancy
from app.utils.cloud import resolve_cloud_region
from app.validators._signal_stamp import stamps
from app.validators.cedar import context as cedar_context
from app.validators.cedar import entities as cedar_entities
from app.validators.cedar.evaluator import CedarDecision, CedarEvaluationError, CedarEvaluator
from app.validators.cedar.policy_loader import CedarPolicyLoader, PolicyNotMigratedError
from app.validators.policy_engine import (
    PolicyDisabledError,
    PolicyEngine,
    PolicyNotFoundError,
)

logger = logging.getLogger(__name__)

# Cedar action uid strings.
ACTION_USE_TOOL = 'Action::"UseTool"'
ACTION_INVOKE_AGENT = 'Action::"InvokeAgent"'

# Determining-rule id (baseline-v1.cedar @id) -> (violation_type, violated_policy, penalty).
# Absence of any forbid (plain default-deny) maps to UNAUTHORIZED_TOOL below.
# Determining-rule id → (violation_type, violated_policy, penalty), in DETERMINISTIC
# PRIORITY ORDER (first match wins). Order is explicit, NOT the alphabetical order
# of @id strings — the baseline forbids are resource-scoped so they don't co-fire
# today, but the collapse must be deterministic by design, not by lexical accident.
_FORBID_PRIORITY = (
    ("forbid_high_fraud_identity", ("POLICY_VIOLATION", "high_fraud_identity_block", -15)),
    ("forbid_refund_over_cap", ("POLICY_VIOLATION", "max_refund_amount", -10)),
    ("forbid_refund_missing_amount", ("POLICY_VIOLATION", "max_refund_amount", -10)),
)


class CedarPolicyEngine:
    """Drop-in authorization validator backed by Cedar. Shares binding resolution
    with the legacy `PolicyEngine` so cloud-from-agent stamping and the GSI
    fallback behave identically."""

    def __init__(self, policy_engine: Optional[PolicyEngine] = None):
        self._policy_engine = policy_engine or PolicyEngine()
        self._loader = CedarPolicyLoader(self._policy_engine)

    def _principal_identity(self, request: ValidationRequest) -> tuple[str, str]:
        """The (tenant_id, agent_id) used to build the Cedar principal.

        ISOLATED here (C5/§14): today it's the current tenant + the request's
        agent_id; multicloud-import §14 swaps the agent_id for the verified JWT
        claim with NO other change to this engine."""
        return tenancy.current_tenant(), request.agent_id

    @stamps(Source.SENTRA_POLICY)
    async def validate(self, request: ValidationRequest) -> ValidationResult:
        # Resolve cloud identity up front so a DENY before/at policy-load still
        # carries the agent's correct platform/cloud_region (R4/K9), mirroring
        # policy_engine. Overridden by the loaded policy on the success path.
        platform, cloud_region = self._policy_engine.get_agent_cloud_identity(request.agent_id)

        try:
            try:
                loaded = await self._loader.load(request.agent_id)
            except PolicyDisabledError:
                logger.warning(f"Bound policy disabled for agent {request.agent_id}")
                return self._deny("POLICY_DISABLED", None, -15,
                                  f"Policy for agent {request.agent_id} is disabled",
                                  platform, cloud_region)
            except PolicyNotFoundError:
                logger.error(f"Policy not found for agent {request.agent_id}")
                return self._deny("POLICY_NOT_FOUND", None, -15,
                                  f"No policy found for agent {request.agent_id}",
                                  platform, cloud_region)
            except PolicyNotMigratedError:
                # Pre-cutover: this agent isn't on Cedar yet. ABSTAIN rather than
                # fabricate a disagreement (shadow) or a spurious DENY.
                logger.info(f"Agent {request.agent_id} policy not Cedar-migrated; abstaining")
                return ValidationResult.abstain(
                    f"Cedar not applicable: agent {request.agent_id} not migrated")

            policy = loaded.policy
            platform = policy.get("platform")
            cloud_region = policy.get("cloud_region")

            tenant_id, agent_id = self._principal_identity(request)
            principal = cedar_entities.agent_uid(tenant_id, agent_id)
            ctx = cedar_context.build_context(request.tool_params, cloud_region=cloud_region)
            evaluator = CedarEvaluator(loaded.compiled_cedar)

            if request.tool_name == "invoke_agent":
                return self._validate_invoke_agent(
                    request, evaluator, principal, ctx, policy, tenant_id, platform, cloud_region)

            # Single UseTool authorization for every other tool.
            entities = cedar_entities.synthesize_entities(
                tenant_id=tenant_id, agent_id=agent_id, policy=policy,
                requested_tool=request.tool_name)
            decision = evaluator.is_authorized(
                principal=principal, action=ACTION_USE_TOOL,
                resource=cedar_entities.tool_uid(request.tool_name), context=ctx, entities=entities)

            if decision.errors:
                return self._deny("POLICY_ERROR", None, -15,
                                  "Policy evaluation error", platform, cloud_region)
            if decision.allow:
                return self._allow(platform, cloud_region)
            vt, vp, penalty = self._map_use_tool_deny(
                decision, request.tool_name, policy.get("allowed_tools"))
            return self._deny(vt, vp, penalty,
                              self._deny_reason(vt, request, vp), platform, cloud_region)

        except CedarEvaluationError:
            logger.exception(f"Cedar evaluation failed for agent {request.agent_id}")
            return self._deny("POLICY_ERROR", None, -15, "Policy evaluation error",
                              platform, cloud_region)
        except Exception:
            logger.exception(f"Cedar policy validation error for agent {request.agent_id}")
            return self._deny("POLICY_ERROR", None, -15, "Policy validation failed",
                              platform, cloud_region)

    def _validate_invoke_agent(self, request, evaluator, principal, ctx, policy,
                               tenant_id, platform, cloud_region) -> ValidationResult:
        """Two AND-ed authorizations + a structural pre-check, in legacy order:
        tool-auth (call-1) → missing-target → target-auth (call-2)."""
        target_agent = request.tool_params.get("agent_id")
        agent_id = request.agent_id

        # Call 1 — is the agent allowed to invoke at all? (invoke_agent ∈ allowed_tools)
        entities = cedar_entities.synthesize_entities(
            tenant_id=tenant_id, agent_id=agent_id, policy=policy,
            requested_tool="invoke_agent", target_agent=target_agent)
        d1 = evaluator.is_authorized(
            principal=principal, action=ACTION_USE_TOOL,
            resource=cedar_entities.tool_uid("invoke_agent"), context=ctx, entities=entities)
        if d1.errors:
            return self._deny("POLICY_ERROR", None, -15, "Policy evaluation error",
                              platform, cloud_region)
        if not d1.allow:
            # Call-1 wins. Map exactly like a normal UseTool deny (allow-list first).
            vt, vp, penalty = self._map_use_tool_deny(d1, "invoke_agent", policy.get("allowed_tools"))
            return self._deny(vt, vp, penalty,
                              self._deny_reason(vt, request, vp), platform, cloud_region)

        # Structural pre-check — no Agent::target to build, so it precedes call-2.
        if not target_agent:
            logger.warning("invoke_agent called without target agent_id")
            return self._deny("INVALID_AGENT_INVOCATION", None, -15,
                              "invoke_agent requires target agent_id parameter",
                              platform, cloud_region)

        # Call 2 — is THAT target allowed? (target ∈ allowed_agents)
        d2 = evaluator.is_authorized(
            principal=principal, action=ACTION_INVOKE_AGENT,
            resource=cedar_entities.agent_uid(tenant_id, target_agent), context=ctx, entities=entities)
        if d2.errors:
            return self._deny("POLICY_ERROR", None, -15, "Policy evaluation error",
                              platform, cloud_region)
        if not d2.allow:
            return self._deny("UNAUTHORIZED_AGENT_INVOCATION", None, -15,
                              f"Agent '{agent_id}' cannot invoke '{target_agent}'",
                              platform, cloud_region)

        return self._allow(platform, cloud_region)

    @staticmethod
    def _map_use_tool_deny(decision: CedarDecision, tool_name: str, allowed_tools):
        """Collapse a UseTool DENY → singular (violation_type, violated_policy,
        penalty), matching legacy `policy_engine`'s check ORDER.

        Allow-list FIRST (legacy Check 1): a tool not in `allowed_tools` is always
        UNAUTHORIZED_TOOL (−15), regardless of which resource-scoped forbid also
        fired — e.g. an over-cap amount on a `process_refund` the agent isn't even
        allowed to call must report UNAUTHORIZED_TOOL/−15, not the refund cap's
        POLICY_VIOLATION/−10. Otherwise collapse the determining forbids by
        explicit priority."""
        if tool_name not in (allowed_tools or []):
            return "UNAUTHORIZED_TOOL", None, -15
        determining = decision.determining_policy_ids
        for rule_id, mapping in _FORBID_PRIORITY:
            if rule_id in determining:
                return mapping
        # Tool IS allowed but an unrecognized forbid denied it — unreachable with
        # the current baseline. Fail secure without mislabeling as UNAUTHORIZED_TOOL.
        logger.warning(
            "Cedar DENY for allowed tool %s with unmapped determining policies %s",
            tool_name, determining)
        return "POLICY_VIOLATION", None, -15

    @staticmethod
    def _deny_reason(violation_type: str, request: ValidationRequest, violated_policy: Optional[str]) -> str:
        if violation_type == "UNAUTHORIZED_TOOL":
            return f"Tool '{request.tool_name}' not authorized for {request.agent_id}"
        if violated_policy == "max_refund_amount":
            return f"Refund denied by policy cap for {request.agent_id}"
        if violated_policy == "high_fraud_identity_block":
            return "Identity verification refused: subject flagged high fraud risk"
        return f"Tool '{request.tool_name}' denied by policy for {request.agent_id}"

    @staticmethod
    def _allow(platform, cloud_region) -> ValidationResult:
        return ValidationResult(decision="ALLOW", reason="Policy checks passed",
                                should_deny=False, platform=platform, cloud_region=cloud_region)

    @staticmethod
    def _deny(violation_type, violated_policy, penalty, reason, platform, cloud_region) -> ValidationResult:
        return ValidationResult(decision="DENY", reason=reason, violation_type=violation_type,
                                violated_policy=violated_policy, penalty=penalty, should_deny=True,
                                platform=platform, cloud_region=cloud_region)
