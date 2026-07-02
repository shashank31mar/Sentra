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
import time
from typing import Dict, List

from app.api.models import ValidationRequest, ValidationResult, _CONTENT_FIELD
from app.combiners import Source
from app.services.scheduler.node import CostTier, ValidatorNode

logger = logging.getLogger(__name__)

# Phases that carry a free-text `content_text` field the Tier-2 NER barrier
# redacts (LLD 29 §4.1). The `request` phase carries NO content field and gets NO
# barrier node — so WS-C's request-phase verdict-equivalence golden baseline is
# untouched (LLD 29 §4.1 FOOTGUN 3). Sourced from WS-B's canonical map, not a
# second spelling.
_CONTENT_PHASES = frozenset(_CONTENT_FIELD)  # {content, output, memory}

# The held-content sentinel the barrier writes into `content_text` when the Tier-2
# redactor is unavailable (E3 egress-fail-closed, LLD 29 §16). The unredactable raw
# is DROPPED (never forwarded/persisted); the safe fields still process and the
# action is NOT blanket-DENYed. NEVER the raw value.
_EGRESS_HELD_MARKER = "⟦AEGR:egress_held⟧"

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
        #
        # OBSERVABILITY (integration-sentinel FIX-B LOW): the pre-DAG pipeline
        # emitted TWO distinct timing entries for this step — `abuse_policy_load`
        # (the agent-policy fetch) and `abuse` (the rate-limit check). The DAG's
        # per-node `timed(node.source, ...)` in run_dag only labels the whole node
        # body as `sentra.abuse`, so the sub-step `abuse_policy_load` metric was
        # silently dropped from `validation.timing` (LLD 31 §6.6 claims per-node
        # timing is preserved byte-for-byte). Restore the sub-step label here — the
        # same in-node instrumentation pattern `_run_policy_step` uses for its own
        # `policy` / `policy_fallback` sub-labels. `_timed` is imported lazily to
        # avoid the validation_service ↔ scheduler import cycle (the same deferred-
        # import the pipeline seam uses).
        from app.services.validation_service import _timed

        policy = await _timed(
            "abuse_policy_load", service.policy_engine.get_agent_policy(req.agent_id)
        )
        return await service.abuse_detector.check_rate_limit(sess, policy)

    async def _run_ml(req: ValidationRequest, sess: Dict) -> ValidationResult:
        # Tier-1 ML node. NO-FLAG: ML ALWAYS ENFORCES. The wrapper stamps
        # metadata["enforce"]=True on every concrete verdict so a live ML DENY
        # can decide (_is_hard_deny). There is no shadow-mode relocation any
        # more — the ML shadow toggle is removed.
        result = await service.ml_classifier.validate(req)
        return _apply_ml_enforce_wrapper(result)

    async def _run_ner_barrier(req: ValidationRequest, sess: Dict) -> ValidationResult:
        # WS-E2 / LLD 29 §4.1 (F1) — the Tier-2 free-text PHI redaction BARRIER.
        #
        # Added ONLY on content/output/memory phases carrying a `content_text`.
        # `run_dag` recognizes `Source.REDACTION_NER` as a barrier (`_is_barrier`)
        # and runs it FIRST and ALONE, before the tier-0/tier-1 split. It redacts
        # `request.content_text` IN PLACE, so — because `run_dag` passes the SAME
        # mutable `request` to every
        # node and `_handle_deny`/`_handle_allow` pass `request.model_dump()` to the
        # audit/feedback write — the phase's deep-detector nodes, the audit write,
        # and the feedback write all inherit the post-NER redacted view in ONE pass
        # (the happens-before barrier gating all three consumers, §5.3).
        #
        # It returns ALLOW/ABSTAIN: the node's job is REDACTION, not a verdict — it
        # never DENYs on PHI presence. On a Tier-2 OUTAGE (NerUnavailable) it fails
        # closed ON EGRESS (E3): the unredactable content is HELD (replaced by the
        # egress-held marker, NEVER forwarded/persisted raw), the safe fields still
        # process, and the action is NOT blanket-DENYed. Metrics are fire-and-forget.
        from app.redaction.phi_ner import NerUnavailable, get_phi_ner_client

        text = getattr(req, "content_text", None)
        if text is None:
            # Nothing to redact (guarded by build_dag's append condition too). This
            # IS a completed (no-op) redaction pass — mirror PhiNerClient.redact_free_text's
            # None/empty handling (phi_ner.py: a None/empty field is a redacted no-op
            # view) and stamp `redacted=True`. Without it, an opted-in tenant's genuine
            # null-content record would be REFUSED by the feedback eval-gate as
            # `not-redacted` and logged as a "residual record; skipped (correct)" —
            # surfacing a benign no-op as a redaction-gate residual (LLD 29 §5.3 pt 3).
            req.redacted = True
            return ValidationResult.abstain("redaction.ner: no content_text")

        # WS-E2 / LLD 29 §3.6 (E6.2/E6.3) — IMAGE FIELD ROUTING (the E6 router's LIVE
        # call site). The Tier-1 edge tagged a whole-value image/binary blob into
        # `content_text` as an `⟦AEGR:{nonce}:IMAGE⟧` marker (the raw pixels were
        # dropped at the edge — only the marker travels). An image field is NOT free
        # text (the NER redactor cannot scrub pixels), so it is routed by the per-tool
        # MODE here, on the content path, BEFORE the free-text NER pass. The mode is
        # resolved FAIL-SECURE from the tool registry (default / unresolvable →
        # `block`, §3.6 FOOTGUN — never `evaluate` by omission):
        #   * evaluate → forward the image INTACT to the fraud/threat evaluator;
        #   * redact   → replace with the redact-pending sentinel (engine = later build);
        #   * block    → refuse egress (replace with the block sentinel).
        # The routed value is stamped redacted=True (a routing decision IS a completed
        # content pass — the raw is gone), so the audit/feedback consumers inherit the
        # routed value, never a raw image. Only `evaluate` leaves the field intact.
        from app.redaction.image_mode import (
            content_has_image,
            resolve_tool_image_mode,
            route_image_content,
        )

        if content_has_image(text):
            raw_mode = resolve_tool_image_mode(service, getattr(req, "tool_name", None))
            route = route_image_content(text, raw_mode=raw_mode)
            req.content_text = route.content_text
            req.redacted = True
            logger.info(
                "redaction.image routed phase=%s tool=%s mode=%s intact=%s agent=%s",
                getattr(req, "phase", "?"), getattr(req, "tool_name", "?"),
                route.mode.value, route.forwarded_intact, req.agent_id,
            )
            return ValidationResult(
                decision="ALLOW",
                reason=f"redaction.image: routed mode={route.mode.value}",
                should_deny=False,
                source=Source.REDACTION_NER,
                metadata={"image_mode": route.mode.value,
                          "image_forwarded_intact": route.forwarded_intact},
            )

        nonce = getattr(req, "redaction_nonce", None)
        tenant_id = _tenant_for_ner(sess)
        started = time.perf_counter()
        try:
            view = get_phi_ner_client().redact_free_text(
                text, nonce=nonce, tenant_id=tenant_id
            )
            # BARRIER: mutate the top-level scalar in place. `run_dag` runs this
            # barrier node FIRST and ALONE (awaited before the tier-0/tier-1 split;
            # see `_is_barrier` + the barrier pass in run_dag) so this write
            # happens-before every detector node AND before any concurrent tier-1
            # reader — a real happens-before barrier, not merely a `depends_on` edge
            # (LLD 29 §4.1 FOOTGUN 4). Do NOT mutate nested session/tool_params
            # structures.
            req.content_text = view.text
            # Stamp the redaction-provenance flag (LLD 29 §5.3 point 3): a Tier-2
            # pass ran over content_text, so the downstream persist-gate (Check 1)
            # keeps the redacted content instead of dropping it, and the opt-in
            # feedback write sees `redacted=True`. Without this the audit row drops
            # the (legitimately-redacted) content and the feedback store refuses
            # every record on the happy path.
            req.redacted = True
            _emit_ner_latency(service, started)
            return ValidationResult(
                decision="ALLOW",
                reason="redaction.ner: content_text redacted",
                should_deny=False,
                source=Source.REDACTION_NER,
                metadata={"redaction_classes": view.found_classes},
            )
        except NerUnavailable as exc:
            # E3 egress-fail-closed: HOLD the unredactable content (drop the raw),
            # process the safe fields, do NOT blanket-DENY. The raw NEVER reaches a
            # downstream reader/store — the marker replaces it. "Skip-store but
            # forward raw" is the one forbidden path (§7.2) and cannot happen here.
            req.content_text = _EGRESS_HELD_MARKER
            # The raw is GONE (replaced by the marker), so this IS a completed
            # redaction pass for persist-gate purposes: flag it so the audit row
            # keeps the held marker (a visible "content withheld" record) rather
            # than the persist-gate dropping it for want of the provenance flag.
            req.redacted = True
            _emit_egress_held(service)
            logger.warning(
                "redaction.ner unavailable for phase=%s agent=%s; content HELD "
                "(egress-fail-closed, raw dropped): %s",
                getattr(req, "phase", "?"), req.agent_id, exc,
            )
            return ValidationResult.abstain(
                "redaction.ner: NER unavailable; content_text held (egress-fail-closed)"
            )

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

    # WS-E2 / LLD 29 §4.1 (F1): add the Tier-2 NER barrier ONLY for a content-
    # bearing phase (content/output/memory). `run_dag` recognizes the
    # `Source.REDACTION_NER` node as a pre-DAG BARRIER (`_is_barrier`) and runs it
    # FIRST, alone (awaited before the tier-0/tier-1 split), so the redaction of
    # `content_text` happens-before EVERY detector node reads the request AND before
    # any concurrent tier-1 reader — the real happens-before barrier the §5.3
    # invariant needs, not merely a `depends_on` edge (which, against independent
    # tier-1 peers, orders nothing — the defect the tier-split scheduler exposed).
    # `build_dag` does not receive the request, so the node itself cheaply ABSTAINs
    # when there is no `content_text` (nothing to redact) — the append is keyed on
    # the PHASE only. The `request`-phase DAG is left untouched → WS-C's request-
    # phase verdict-equivalence golden baseline is unaffected (FOOTGUN 3). NER is
    # `content_text`-only; `tool_params`/`user_input` keep their Tier-1 tokens
    # (FOOTGUN 1 — never blanket-redact, it would blind detection). `cost_tier` is
    # documentary for this node — `run_dag` lifts it out of the tier split entirely.
    if phase in _CONTENT_PHASES:
        nodes.append(
            ValidatorNode(
                source=Source.REDACTION_NER,
                cost_tier=CostTier.EXPENSIVE_MODEL,
                run=_run_ner_barrier,
                depends_on=(),          # barrier — run_dag runs it first & alone
                order_key=0,            # documentary (run_dag lifts it out of tiers)
            )
        )

    return nodes


def _tenant_for_ner(session: Dict) -> str:
    """Resolve the tenant id for the NER pass without importing the tenancy module
    at graph-build time (keeps the barrier node a leaf). Prefer the request's
    resolved tenant contextvar; fall back to the session's agent-derived id."""
    try:
        from app.utils import tenancy
        return tenancy.current_tenant()
    except Exception:  # noqa: BLE001 — a tenant-resolution hiccup must not break redaction
        return str(session.get("tenant_id") or "default")


def _emit_ner_latency(service, started: float) -> None:
    """Fire-and-forget `RedactionTier2NerLatencyMs` (off the response path, §9.5).
    A metrics gap must never block or change a verdict."""
    _fire_metric(service, "publish_redaction_ner_latency",
                 latency_ms=round((time.perf_counter() - started) * 1000, 2))


def _emit_egress_held(service) -> None:
    """Fire-and-forget `EgressHeldCount` + `NerUnavailableCount` (E3, §9.5)."""
    _fire_metric(service, "publish_redaction_egress_held")


def _fire_metric(service, method_name: str, **kwargs) -> None:
    """Best-effort fire-and-forget of a metrics_publisher coroutine from inside a
    DAG node. Uses validation_service._fire_and_forget so the task is retained
    (not GC'd) and any failure is swallowed — telemetry never blocks the verdict."""
    publisher = getattr(service, "metrics_publisher", None)
    emit = getattr(publisher, method_name, None)
    if emit is None:
        return
    try:
        from app.services.validation_service import _fire_and_forget
        _fire_and_forget(emit(**kwargs), "metrics")
    except Exception:  # noqa: BLE001 — telemetry must never block a verdict
        logger.debug("redaction metric emit skipped (%s)", method_name, exc_info=True)


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
