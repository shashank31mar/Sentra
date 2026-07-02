"""The DAG node registry — WS-C / LLD 31 §5.2.

`build_dag(service, phase, stamp_ctx)` registers the seven existing validators
as `ValidatorNode`s for the request phase and returns the node set. Each node's
`run` wraps the EXACT call the sequential pipeline made before the DAG cutover:

  trust → policy → {cross_agent, sigma, context, abuse}  (tier-0, short-circuit)
  ml_classifier                                            (tier-1, parallel)

The `sentra.policy` node encapsulates the Cedar cutover/shadow/legacy selection
(LLD 31 §5.3) so the scheduler stays policy-engine-agnostic, and it publishes
the agent-sourced `platform`/`cloud_region` into `stamp_ctx` so the reused
`_stamp` closure can attach them to downstream results — reproducing the
sequential code's `platform_from_policy`/`cloud_region_from_policy` capture.

NO-FLAG cutover (ADR-030): the DAG is the ONLY pipeline. There is no
scheduler-enable gate and no retained sequential body — rollback is git-revert +
redeploy, not a config flip. Consistent with that, the `sentra.ml_classifier`
tier-1 node ALWAYS ENFORCES: the ML shadow-mode toggle has been removed entirely,
so the ML wrapper stamps `metadata["enforce"]=True` on every concrete verdict and
a live ML DENY can decide (`_is_hard_deny`). The separate `ml_classifier_enabled`
on/off Field STILL gates whether the classifier runs at all (default False; the
config YAMLs set it true) — a disabled classifier returns an abstain and emits no
signal.

WS-D adds D1–D7 as additional tier-1 nodes here (with their own `depends_on`
edges) WITHOUT editing the scheduler core — the `ValidatorNode`/`depends_on`/
`cost_tier` vocabulary is the shared contract.
"""

from __future__ import annotations

import logging
from typing import Dict, List

from app.api.models import ValidationRequest, ValidationResult
from app.combiners import Source
from app.services.scheduler.node import CostTier, ValidatorNode

logger = logging.getLogger(__name__)

# Legacy step order (the pre-DAG validation_service STEP 1..6) — the
# deterministic tie-break for topologically-independent tier-0 nodes (LLD 31
# §6.2). Pinned to the legacy step index, NOT alphabetical, so a
# two-simultaneous-DENY short-circuit returns the same denier's result (and
# reason) the fixed-sequential chain returned.
_ORDER = {
    Source.SENTRA_TRUST: 1,
    Source.SENTRA_POLICY: 2,
    Source.SENTRA_CROSS_AGENT: 3,   # STEP 2.5
    Source.SENTRA_SIGMA: 4,         # STEP 3
    Source.SENTRA_CONTEXT: 5,       # STEP 4
    Source.SENTRA_ABUSE: 6,         # STEP 5
    Source.SENTRA_ML_CLASSIFIER: 7,  # STEP 6 (tier-1)
}


def build_dag(service, phase: str, stamp_ctx: Dict) -> List[ValidatorNode]:
    """Return the `ValidatorNode` set for `phase` (LLD 31 §5.2, §5.4).

    `service` is the `ValidationService` whose validators the node callables
    delegate to. `stamp_ctx` is a mutable dict the `sentra.policy` node writes
    `platform`/`cloud_region` into so the reused `_stamp` closure can read them
    (matching the sequential capture at validation_service.py:377-378).

    Per-phase node selection (LLD 31 §5.4): only `phase == "request"` has nodes
    today; content/output/memory nodes are WS-D's deliverable. An unknown/absent
    phase degrades to the request node set (deny-by-default posture — the
    request-side floor still runs, never "no checks").
    """
    if phase != "request":
        # WS-C ships only the request phase; other phases have no WS-C nodes yet
        # (WS-D adds them). Degrade to the request floor rather than run nothing.
        pass

    async def _run_trust(req: ValidationRequest, sess: Dict) -> ValidationResult:
        result = await service.trust_checker.check(sess, req)
        # Trust runs FIRST — before the policy node populates stamp_ctx — so a
        # trust DENY would otherwise carry platform=None/cloud_region=None. The
        # pre-DAG pipeline resolved cloud identity from the agent registry on the
        # trust-DENY path (one cheap get_item, only on DENY — agent-policy-
        # management K9/C2). Preserve that audit metadata here. Best-effort: a
        # resolution hiccup must never turn a clean security DENY into a 5xx.
        if result.should_deny and (result.platform is None or result.cloud_region is None):
            try:
                a_platform, a_region = service.policy_engine.get_agent_cloud_identity(req.agent_id)
            except Exception:
                a_platform, a_region = None, None
                logger.debug("trust-DENY cloud stamp skipped", exc_info=True)
            if result.platform is None:
                result.platform = a_platform or req.platform
            if result.cloud_region is None:
                result.cloud_region = a_region or req.cloud_region
        return result

    async def _run_policy(req: ValidationRequest, sess: Dict) -> ValidationResult:
        # STEP 2 — the Cedar cutover/shadow/legacy selection, lifted verbatim
        # from validation_service.py (LLD 31 §5.3). The scheduler never sees
        # Cedar. Publishes the agent-sourced cross-cloud fields into stamp_ctx.
        result = await service._run_policy_step(req)
        if not result.should_deny:
            stamp_ctx["platform"] = result.platform
            stamp_ctx["cloud_region"] = result.cloud_region
        return result

    async def _run_cross_agent(req: ValidationRequest, sess: Dict) -> ValidationResult:
        return await service.cross_agent_validator.validate(req)

    async def _run_sigma(req: ValidationRequest, sess: Dict) -> ValidationResult:
        return await service.sigma_engine.match_rules(req.user_input)

    async def _run_context(req: ValidationRequest, sess: Dict) -> ValidationResult:
        return await service.context_validator.validate_sequence(sess, req)

    async def _run_abuse(req: ValidationRequest, sess: Dict) -> ValidationResult:
        # The agent policy is loaded here exactly as STEP 5 did; the policy cache
        # absorbs the second resolution (LLD 31 §11 — no 3× reload). This is the
        # node's OWN (get_agent_policy -> check_rate_limit) pair; we deliberately
        # do NOT thread a shared policy-context object through the scheduler.
        policy = await service.policy_engine.get_agent_policy(req.agent_id)
        return await service.abuse_detector.check_rate_limit(sess, policy)

    async def _run_ml(req: ValidationRequest, sess: Dict) -> ValidationResult:
        # Tier-1 ML node. NO-FLAG: ML ALWAYS ENFORCES. The wrapper stamps
        # metadata["enforce"]=True on every concrete verdict so a live ML DENY
        # can decide (_is_hard_deny). There is no shadow-mode relocation any
        # more — the ML shadow toggle is removed.
        result = await service.ml_classifier.validate(req)
        return _apply_ml_enforce_wrapper(result)

    nodes: List[ValidatorNode] = [
        ValidatorNode(
            source=Source.SENTRA_TRUST,
            cost_tier=CostTier.DETERMINISTIC,
            run=_run_trust,
            depends_on=(),
            order_key=_ORDER[Source.SENTRA_TRUST],
        ),
        ValidatorNode(
            source=Source.SENTRA_POLICY,
            cost_tier=CostTier.DETERMINISTIC,
            run=_run_policy,
            depends_on=(Source.SENTRA_TRUST,),
            order_key=_ORDER[Source.SENTRA_POLICY],
        ),
        ValidatorNode(
            source=Source.SENTRA_CROSS_AGENT,
            cost_tier=CostTier.DETERMINISTIC,
            run=_run_cross_agent,
            depends_on=(Source.SENTRA_POLICY,),
            order_key=_ORDER[Source.SENTRA_CROSS_AGENT],
        ),
        ValidatorNode(
            source=Source.SENTRA_SIGMA,
            cost_tier=CostTier.DETERMINISTIC,
            run=_run_sigma,
            depends_on=(Source.SENTRA_POLICY,),
            order_key=_ORDER[Source.SENTRA_SIGMA],
        ),
        ValidatorNode(
            source=Source.SENTRA_CONTEXT,
            cost_tier=CostTier.DETERMINISTIC,
            run=_run_context,
            depends_on=(Source.SENTRA_POLICY,),
            order_key=_ORDER[Source.SENTRA_CONTEXT],
        ),
        ValidatorNode(
            source=Source.SENTRA_ABUSE,
            cost_tier=CostTier.DETERMINISTIC,
            run=_run_abuse,
            depends_on=(Source.SENTRA_POLICY,),
            order_key=_ORDER[Source.SENTRA_ABUSE],
        ),
        ValidatorNode(
            source=Source.SENTRA_ML_CLASSIFIER,
            cost_tier=CostTier.EXPENSIVE_MODEL,
            run=_run_ml,
            depends_on=(Source.SENTRA_POLICY,),
            order_key=_ORDER[Source.SENTRA_ML_CLASSIFIER],
        ),
    ]
    return nodes


def _apply_ml_enforce_wrapper(result: ValidationResult) -> ValidationResult:
    """Stamp the tier-1 ML node's result as ENFORCE — LLD 31 §6.5 (NO-FLAG).

    Under the NO-FLAG cutover there is no shadow mode: the ML classifier tier-1
    node ALWAYS enforces. Abstains pass through untouched (no signal either way —
    e.g. the classifier disabled via `ml_classifier_enabled=False`, or its own
    handled Bedrock-outage abstain). For a CONCRETE verdict, stamp
    `metadata["enforce"]=True` so `_is_hard_deny` lets a live ML DENY decide the
    verdict. The result is copied before mutation so the classifier's returned
    object is not aliased/mutated in place.

    This deliberately drops the removed shadow branch (the old rewrite-to-non-
    deciding). The T-ML-ENFORCE test pins the one intended verdict change: an ML
    DENY now blocks (winning_source=sentra.ml_classifier) where the old shadow
    path let it fall through to ALLOW.
    """
    if result.is_abstain:
        return result

    wrapped = result.model_copy(deep=True)
    meta = dict(wrapped.metadata or {})
    meta["enforce"] = True
    wrapped.metadata = meta
    return wrapped
