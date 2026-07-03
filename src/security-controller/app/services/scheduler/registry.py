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

WS-L adds D1–D3 (P0) as additional tier-1 nodes here (with their own `depends_on`
edges) plus the distilled front-runner (M6); D4–D8 are scaffolded (Source
constant + priority + label), not built. This is done WITHOUT editing the
scheduler core — the `ValidatorNode`/`depends_on`/`cost_tier` vocabulary is the
shared contract.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, List

from app.api.models import ValidationRequest, ValidationResult, _CONTENT_FIELD
from app.combiners import Source
from app.config import settings
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
    # WS-L request-phase D-nodes. Each carries its OWN _ORDER key (invariant #8a:
    # `_ORDER` is one of the three co-equal sets the trail drift-guard checks, so a
    # request-phase node with no key leaves `set(_ORDER)` short of the fallback
    # order → guard RED). NOT a reuse of ML's key. The model-chain run order is
    # decided by `depends_on` (distilled → ml), not order_key, so ML's key stays 7
    # (T-EQUIV byte-identity of the existing 7 nodes' order_key is preserved).
    Source.SENTRA_DISTILLED: 8,      # distilled chain-HEAD (M6), runs before ml via depends_on
    Source.SENTRA_TRAJECTORY: 9,     # D1 trajectory signal (M4)
}


def build_dag(service, phase: str, stamp_ctx: Dict) -> List[ValidatorNode]:
    """Return the `ValidatorNode` set for `phase` (LLD 31 §5.2, §5.4).

    `service` is the `ValidationService` whose validators the node callables
    delegate to. `stamp_ctx` is a mutable dict the `sentra.policy` node writes
    `platform`/`cloud_region` into so the reused `_stamp` closure can read them
    (matching the sequential capture at validation_service.py:377-378).

    Per-phase node selection (WS-L / LLD 32 §6.1/§6.2, replacing WS-C's no-op
    degradation): `request` returns the existing floor + the two additive WS-L
    request nodes (distilled front-runner M6 + D1 trajectory M4); `content` and
    `memory` return their own deep-detector node sets (D2 / D3, NO action floor —
    invariant 4); `output` and any unknown/absent phase degrade to the request
    floor (deny-by-default posture — the request-side floor still runs, never "no
    checks"). See the per-phase node-set builder near the tail of this function.
    """
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

    async def _run_distilled(req: ValidationRequest, sess: Dict) -> ValidationResult:
        # WS-L M6.1 — the LIVE cheap tier-1 chain-HEAD (LLD 32 §4.1/§4.3). ONE
        # awaitable, NO asyncio.gather (the sole gather is _run_tier1_with_edges,
        # run.py). Hard <100ms wall; on timeout OR error return a CONCRETE escalate
        # verdict (→ Haiku runs), NEVER abstain (an abstain aborts the chain,
        # skipping Haiku) and NEVER a silent ALLOW (fail-secure fallback,
        # founder-locked §4.1 — an errored distilled call is treated as "run Haiku",
        # never as clean).
        try:
            result = await asyncio.wait_for(
                service.distilled_classifier.classify(req),
                timeout=settings.distilled_timeout_ms / 1000,
            )
            return result
        except Exception as exc:  # noqa: BLE001 — timeout/4XX/5XX → escalate to Haiku (fail-secure)
            logger.warning("distilled classify failed; escalating to Haiku: %s", exc)
            return ValidationResult(
                decision="ALLOW",
                reason="distilled: error/timeout → escalate to Haiku (fail-secure)",
                should_deny=False,
                confidence=0.0,
                source=Source.SENTRA_DISTILLED,
                metadata={"escalate": True, "distilled_error": True},
            )

    async def _run_ml(req: ValidationRequest, sess: Dict) -> ValidationResult:
        # Tier-1 ML node (Haiku), the chain-TAIL behind the distilled chain-head.
        #
        # WS-L M6.2 — the LIVE short-circuit (LLD 32 §4.1/SEC-7). The short-circuit
        # is INTRINSIC: there is NO enable flag; it fires whenever the upstream
        # distilled verdict (threaded via ctx into `sess[SENTRA_DISTILLED]`) is
        # CONFIDENT (not the escalate path, confidence ≥ the distilled OWN
        # threshold — NOT ml_confidence_trust_threshold; FIX-A3). A confident
        # distilled verdict skips Haiku entirely — this node abstains so it emits no
        # signal, and the distilled node's own captured verdict (ALLOW or DENY) is
        # what the combiner sees. Read `sess[SENTRA_DISTILLED]`, never re-invoke the
        # classifier (double-run + breaks the single-awaitable contract).
        distilled = sess.get(Source.SENTRA_DISTILLED)
        if (distilled is not None
                and not (distilled.metadata or {}).get("escalate")
                and distilled.confidence is not None
                and distilled.confidence >= settings.distilled_confidence_trust_threshold):
            return ValidationResult.abstain("distilled_shortcircuit")

        # else — low-confidence / escalate / error / interim distilled → run Haiku.
        # NO-FLAG: ML ALWAYS ENFORCES. The wrapper stamps metadata["enforce"]=True on
        # every concrete verdict so a live ML DENY can decide (_is_hard_deny).
        result = await service.ml_classifier.validate(req)
        return _apply_ml_enforce_wrapper(result)

    async def _run_trajectory(req: ValidationRequest, sess: Dict) -> ValidationResult:
        # WS-L M4 — D1 conversation-trajectory (request phase). An additive tier-1
        # node (LLM-judge v1). A SIGNAL, never a standalone gate: it starts SHADOW
        # (advisory) — the enforce wrapper is NOT applied, so `_is_hard_deny` is
        # false and a D1 DENY does not decide the verdict (LLD 32 §5.1 solvability
        # ceiling; graduate shadow→enforce on evidence, M4.3). Reads server-side
        # transcript only (SEC-3).
        from app.validators.trajectory import TrajectoryValidator
        return await TrajectoryValidator(service).validate(req, sess)

    async def _run_indirect(req: ValidationRequest, sess: Dict) -> ValidationResult:
        # WS-L M2 — D2 indirect/second-order injection (content phase). Reads the
        # REDACTED content_text (the NER barrier ran first). Live-enforce, FP-gated
        # (R5-C): advisory until the M5 harness clears the FP budget, then enforce
        # via the tier-1 enforce mechanism (metadata["enforce"]=True → _is_hard_deny).
        from app.validators.indirect_injection import IndirectInjectionValidator
        result = await IndirectInjectionValidator(service).validate(req)
        return _apply_enforce_if(result, settings.d2_enforce_enabled)

    async def _run_memory(req: ValidationRequest, sess: Dict) -> ValidationResult:
        # WS-L M3 — D3 memory-integrity (memory phase). Reads the REDACTED memory
        # candidate. Live-enforce, FP-gated (same mechanism as D2, R5-C).
        from app.validators.memory_write import MemoryWriteValidator
        result = await MemoryWriteValidator(service).validate(req)
        return _apply_enforce_if(result, settings.d3_enforce_enabled)

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

    def _ner_barrier_node() -> ValidatorNode:
        # WS-E2 / LLD 29 §4.1 (F1) — the Tier-2 NER redaction BARRIER. `run_dag`
        # recognizes `Source.REDACTION_NER` (`_is_barrier`) and runs it FIRST + ALONE
        # so it redacts `content_text` happens-before every content/memory detector
        # node reads the request. `cost_tier` is documentary (run_dag lifts it out of
        # the tier split). `content_text`-only (FOOTGUN 1 — never blanket-redact).
        return ValidatorNode(
            source=Source.REDACTION_NER,
            cost_tier=CostTier.EXPENSIVE_MODEL,
            run=_run_ner_barrier,
            depends_on=(),          # barrier — run_dag runs it first & alone
            order_key=0,            # documentary (run_dag lifts it out of tiers)
        )

    def _request_floor() -> List[ValidatorNode]:
        # The seven EXISTING request-phase nodes, BYTE-FOR-BYTE (FIX-E / T-EQUIV).
        # Their source/cost_tier/run/order_key do not move. The one exception is the
        # ml node's `depends_on`: when the distilled front-runner is enabled (default)
        # ml chains BEHIND distilled (`depends_on=(SENTRA_DISTILLED,)`) so
        # `_build_chains` groups distilled → ml (M6.1); when the kill-switch is OFF ml
        # keeps `(SENTRA_POLICY,)` — the byte-identical rollback graph.
        ml_depends_on = (
            (Source.SENTRA_DISTILLED,) if settings.distilled_enabled
            else (Source.SENTRA_POLICY,)
        )
        return [
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
                depends_on=ml_depends_on,
                order_key=_ORDER[Source.SENTRA_ML_CLASSIFIER],
            ),
        ]

    def _request_nodes() -> List[ValidatorNode]:
        # The request node set = the frozen 7-node floor PLUS the two ADDITIVE WS-L
        # request-phase nodes: the distilled chain-HEAD (M6, LIVE by default) and the
        # D1 trajectory signal (M4, additive). Both are tier-1. T-EQUIV holds via
        # VERDICT-equivalence, not byte-identity (the interim distilled always
        # escalates so Haiku still decides; D1 is a non-deciding signal).
        nodes = _request_floor()
        if settings.distilled_enabled:                   # DEFAULT True — live front-runner
            nodes.append(ValidatorNode(
                source=Source.SENTRA_DISTILLED,          # M1.1 constant, priority 66 (M1.2)
                cost_tier=CostTier.EXPENSIVE_MODEL,      # tier-1 model node; NOT a new CostTier
                run=_run_distilled,
                depends_on=(Source.SENTRA_POLICY,),      # runs after the tier-0 floor resolves
                order_key=_ORDER[Source.SENTRA_DISTILLED],  # its OWN _ORDER key — NOT a reuse of ML's
            ))
        nodes.append(ValidatorNode(
            source=Source.SENTRA_TRAJECTORY,             # D1 (M4), priority 68
            cost_tier=CostTier.EXPENSIVE_MODEL,
            run=_run_trajectory,
            depends_on=(Source.SENTRA_POLICY,),          # documentary; independent tier-1 node
            order_key=_ORDER[Source.SENTRA_TRAJECTORY],
        ))
        return nodes

    # --- per-phase node-set builder (WS-L M1.5, LLD 32 §6.1/§6.2) ---------------
    # `request` → the existing floor + the two additive WS-L request nodes (above).
    # `content` → D2 set (NO action floor — invariant 4): NER barrier + trust +
    #             abuse + sentra.indirect_injection.
    # `memory`  → D3 set (NO action floor): NER barrier + trust + abuse + sentra.memory.
    # `output` / any other known-but-unbuilt / unknown phase → degrade to the request
    #             floor (deny-by-default posture; `output`'s LIVE handler is NOT built —
    #             routes.py keeps it on the WS-B `phase_handler_not_implemented:output`
    #             stub, so build_dag is not reached for output in practice).
    if phase == "content":
        return [
            _ner_barrier_node(),
            ValidatorNode(
                source=Source.SENTRA_TRUST,
                cost_tier=CostTier.DETERMINISTIC,
                run=_run_trust,
                depends_on=(),
                order_key=_ORDER[Source.SENTRA_TRUST],
            ),
            ValidatorNode(
                source=Source.SENTRA_ABUSE,
                cost_tier=CostTier.DETERMINISTIC,
                run=_run_abuse,
                depends_on=(),
                order_key=_ORDER[Source.SENTRA_ABUSE],
            ),
            ValidatorNode(
                source=Source.SENTRA_INDIRECT,           # D2 (M2.3)
                cost_tier=CostTier.EXPENSIVE_MODEL,
                run=_run_indirect,
                depends_on=(Source.SENTRA_POLICY,),      # documentary; dropped cleanly on content
                order_key=0,
            ),
        ]

    if phase == "memory":
        return [
            _ner_barrier_node(),
            ValidatorNode(
                source=Source.SENTRA_TRUST,
                cost_tier=CostTier.DETERMINISTIC,
                run=_run_trust,
                depends_on=(),
                order_key=_ORDER[Source.SENTRA_TRUST],
            ),
            ValidatorNode(
                source=Source.SENTRA_ABUSE,
                cost_tier=CostTier.DETERMINISTIC,
                run=_run_abuse,
                depends_on=(),
                order_key=_ORDER[Source.SENTRA_ABUSE],
            ),
            ValidatorNode(
                source=Source.SENTRA_MEMORY,             # D3 (M3.1)
                cost_tier=CostTier.EXPENSIVE_MODEL,
                run=_run_memory,
                depends_on=(Source.SENTRA_POLICY,),      # documentary; dropped cleanly on memory
                order_key=0,
            ),
        ]

    # request (and any degrade-to-request phase). `output`/unknown fall here. A
    # content-bearing degrade phase (`output`) keeps the Tier-2 NER redaction barrier
    # ON TOP of the request floor so content_text is still redacted before any
    # detector reads it — defense-in-depth for the case `build_dag` is reached for
    # `output` (its LIVE handler is not built; routes.py keeps it on the WS-B stub,
    # so this is belt-and-suspenders, not the live path). `request` itself never gets
    # the barrier (FOOTGUN 3 / T-EQUIV).
    nodes = _request_nodes()
    if phase in _CONTENT_PHASES:            # {content, output, memory} — content/memory
        nodes.append(_ner_barrier_node())   # returned above; this only adds it for output
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


def _apply_enforce_if(result: ValidationResult, enforce: bool) -> ValidationResult:
    """FP-budget-gated enforce stamp for D2/D3 (WS-L M2.4/M3.3, R5-C).

    D2/D3 are live-enforce, gated on the measured FP/precision budget. When
    `enforce` is True (the M5 harness cleared the budget) a concrete DENY is stamped
    `metadata["enforce"]=True` so `_is_hard_deny` lets it decide the verdict. When
    False the result passes through UN-stamped → captured ADVISORY (does not decide)
    — NOT relocated to a shadow node (R5-C: a forgotten enable under-blocks, never a
    surprise FP outage). Abstains pass through untouched. Copied before mutation.
    """
    if result.is_abstain or not enforce:
        return result
    wrapped = result.model_copy(deep=True)
    meta = dict(wrapped.metadata or {})
    meta["enforce"] = True
    wrapped.metadata = meta
    return wrapped


# Every phase build_dag can produce a LIVE handler for. `output` stays on the
# WS-B stub (routes.py), so it is not a live-handler phase here.
_LIVE_HANDLER_PHASES = ("request", "content", "memory")


def assert_registration_complete(service) -> None:
    """Boot-time registration-completeness invariant (WS-L M1.4 / SEC-5, LLD 32 §9.3).

    Every registered `ValidatorNode.source` (across every phase build_dag produces a
    live node set for) MUST be present in `DEFAULT_PRIORITIES` AND
    `SOURCE_DISPLAY_NAMES`, and — for REQUEST-phase sources only — in
    `STATIC_FALLBACK_ORDER`. A missing entry fails fast at boot rather than letting an
    unregistered source silently rank priority 0 and lose tie-breaks (audit
    mis-attribution). Fail-secure: raise, do not warn-and-continue.

    The fallback-order half is REQUEST-PHASE ONLY (FIX-K, invariant 8): content/memory
    sources (`sentra.indirect_injection`, `sentra.memory`) are phase-specific and MUST
    stay OUT of the request-phase `STATIC_FALLBACK_ORDER` (LLD 32 §9.4).
    """
    from app.combiners.sources import (
        DEFAULT_PRIORITIES,
        SOURCE_DISPLAY_NAMES,
        STATIC_FALLBACK_ORDER,
    )

    stamp_ctx: Dict = {"platform": None, "cloud_region": None}
    fallback = set(STATIC_FALLBACK_ORDER)
    for phase in _LIVE_HANDLER_PHASES:
        for node in build_dag(service, phase, dict(stamp_ctx)):
            src = node.source
            if src not in DEFAULT_PRIORITIES:
                raise RuntimeError(
                    f"registration-incomplete: node source {src!r} (phase {phase!r}) "
                    f"is missing from DEFAULT_PRIORITIES (SEC-5)"
                )
            if src not in SOURCE_DISPLAY_NAMES:
                raise RuntimeError(
                    f"registration-incomplete: node source {src!r} (phase {phase!r}) "
                    f"is missing from SOURCE_DISPLAY_NAMES (SEC-5)"
                )
            if phase == "request" and src not in fallback:
                raise RuntimeError(
                    f"registration-incomplete: REQUEST-phase source {src!r} is missing "
                    f"from STATIC_FALLBACK_ORDER (FIX-K / T-TRAIL-14(a))"
                )
