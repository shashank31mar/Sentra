"""The DAG scheduler algorithm — WS-C / LLD 31 §6.

`run_dag` executes the cost-annotated DAG and returns the SAME
`(ValidationResult, list[Signal])` contract the sequential
`_run_validation_pipeline` returns today (LLD 31 §6.4). It NEVER calls
`DenyOverrides.combine()` on the hot path — the verdict is the denier's own
`ValidationResult`; `combine()` stays downstream where it computes
`winning_source` today (LLD 31 §3.2).

Two-tier execution:
  * tier-0 — the cheap deterministic frontier, run in Kahn-topological order,
    with a `fail_fast` short-circuit on the first DENY (no model invoked).
  * tier-1 — the expensive models, parallel-gathered only for tier-0 survivors;
    independent nodes gather concurrently (wall-time = max), dependency chains
    (D2→D4→D5) run sequentially (wall-time = sum), so total tier-1 latency is
    `max(independents, longest chain)` — LLD 31 §9.

Fail-secure (LLD 31 §7, §8 — reconciled with the verdict-equivalence bar §3):
  * a tier-0 node exception is NOT caught here — it bubbles to
    `validate_tool_call`'s outer handler which returns an error→DENY;
  * a tier-1 node that *raises an unexpected exception* is harvested via
    `gather(return_exceptions=True)` (so peers are not cancelled) and then
    RE-RAISED → the outer handler returns a fail-secure error→DENY, byte-for-byte
    what the pre-DAG sequential path did. `return_exceptions=True`
    prevents peer-cancellation, NOT fail-open: a real crash never becomes a silent
    ALLOW (integration-sentinel HIGH-#2; Tenet 2 fail-secure);
  * a tier-1 node that *returns* `ValidationResult.abstain(...)` (the ML
    classifier's own handled Bedrock-outage path — it never raises) flows through
    as an abstain → the deterministic tier-0 floor decides (RES-4, matches
    production);
  * a chain-upstream *returned* abstain fails the downstream chain node to the
    deterministic floor (abstain), never treats a missing signal as "clean"
    (RES-3); a chain-upstream *raise* fails the request secure (re-raised as
    above).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Dict, List, Sequence, Tuple

from app.api.models import ValidationRequest, ValidationResult
from app.combiners import pick_top_denier
from app.services.scheduler.node import CostTier, ValidatorNode

logger = logging.getLogger(__name__)

# Run modes (LLD 31 §6.7). Kept as module constants so the scheduler and the
# config validator name the same strings.
FAIL_FAST = "fail_fast"
EVALUATE_ALL = "evaluate_all"


def _is_barrier(node: ValidatorNode) -> bool:
    """Is this node a pre-DAG happens-before barrier (WS-E2 / LLD 29 §4.1 F1)?

    A barrier mutates the shared `request` in place and every other node must read
    the mutated view, so it cannot be a gathered/short-circuited graph peer — it is
    lifted out of the tier split and run FIRST, alone. The Tier-2 NER redactor
    (`Source.REDACTION_NER`) is the only barrier today. Keyed on the canonical
    source string (imported lazily to keep `run` free of a combiner import at
    module load — the same deferred-import the rest of the seam uses)."""
    from app.combiners import Source

    return node.source == Source.REDACTION_NER


def _is_hard_deny(result: ValidationResult) -> bool:
    """Is this tier-1 DENY allowed to decide the verdict? — LLD 31 §6.5.

    A tier-1 DENY decides ONLY if the node explicitly asserted enforce-mode
    (``metadata["enforce"] is True``). A node that says nothing (absent/None
    metadata, forgotten flag) defaults to ADVISORY (non-deciding): a forgotten
    flag under-blocks (a missed detection, caught by shadow metrics), it NEVER
    becomes a surprise hard blocking DENY / false-positive outage. `metadata`
    may be None (models.py Optional[Dict]), so guard the `.get`. Tier-0
    (deterministic) DENYs are always hard — this helper is tier-1-only.
    """
    return result.should_deny and bool((result.metadata or {}).get("enforce", False))


def _top_tier1_denier(hard_denies: List[ValidationResult]) -> ValidationResult:
    """Pick the deciding tier-1 DENY via the ONE shared ranking — LLD 31 §6.4.

    `run_dag` must return the denier's own `ValidationResult` (its
    operator-facing `reason`/`source`), but the ranking source of truth is the
    combiner's `pick_top_denier` (deny_overrides.py:71), which ranks `Signal`s by
    `(priority, confidence, _neg_source(source))`. Each result's `to_signal()`
    stamps `default_priority(source)` — the SAME priority the downstream
    `combine()` uses — so ranking the results' signals here yields byte-for-byte
    the source the downstream combiner will name as `winning_source`. We convert
    to signals, let `pick_top_denier` choose, then map the winning `source` back
    to its `ValidationResult`.

    Determinism note: the source tie-break in `pick_top_denier` is unique per
    source, so at most one result maps to the winning source. The list is
    single-element in the common case (returned unchanged, no signal round-trip).
    """
    if len(hard_denies) == 1:
        return hard_denies[0]
    by_source: Dict[str, ValidationResult] = {}
    signals = []
    for r in hard_denies:
        sig = r.to_signal()
        if sig is None:  # defensive: hard-DENYs are never abstains, so never None
            continue
        signals.append(sig)
        # First writer wins per source — deterministic given the input list order,
        # and tier-1 sources are distinct nodes so collisions are not expected.
        by_source.setdefault(sig.source, r)
    winner = pick_top_denier(signals)
    if winner is None:  # unreachable given hard_denies is non-empty
        return hard_denies[0]
    return by_source.get(winner.source, hard_denies[0])


def _advisory_for_trail(result: ValidationResult) -> ValidationResult:
    """Rewrite a tier-1 result to ADVISORY (non-deciding) for the trail — the
    verdict-neutrality guard for `evaluate_all` (LLD 31 §6.7).

    In `evaluate_all`, tier-1 nodes run even after a tier-0 hard DENY has already
    decided the verdict (the point of the mode is "record what the deep tier
    would have said"). But `fail_fast` NEVER runs those nodes, so their signals
    are absent from `fail_fast`'s `signals[]`. The downstream combiner
    (audit_logger.py / decisions_service.py) recomputes `winning_source` over the
    WHOLE captured set — so if an `evaluate_all` tier-1 DENY landed as a real
    DENY signal it could OUTRANK the tier-0 denier (e.g. live ML @65 over a
    context DENY @60) and flip `winning_source` by run mode for the SAME request.
    That is the verdict-neutrality violation integration-sentinel reproduced.

    The guard makes the recorded signal non-deciding — `should_deny=False`,
    `decision="ALLOW"` so it does NOT land in the combiner's `denies` list and
    cannot surface as `winning_source` — while PRESERVING the node's real opinion
    under `metadata` so the WS-D trail still shows the deep tier ran and what it
    thought. Abstains pass through untouched (they emit no signal anyway). The
    result is deep-copied before mutation so the node's returned object is never
    aliased/mutated in place.
    """
    if result.is_abstain:
        return result
    advisory = result.model_copy(deep=True)
    meta = dict(advisory.metadata or {})
    # Preserve what the node actually decided, for the trail / advisory metrics.
    meta["trail_advisory"] = True
    meta["advisory_decision"] = advisory.decision
    meta["advisory_should_deny"] = advisory.should_deny
    meta["enforce"] = False  # never deciding
    advisory.metadata = meta
    advisory.should_deny = False
    advisory.decision = "ALLOW"
    return advisory


def _toposort(nodes: Sequence[ValidatorNode]) -> List[ValidatorNode]:
    """Kahn topological sort of `nodes` by their `depends_on` edges, breaking
    ties by `order_key` (the legacy step index) for a DETERMINISTIC run order —
    LLD 31 §6.2.

    Only edges to nodes WITHIN this set count (a tier-0 node's edge onto
    `sentra.policy` orders the tier-0 run; a tier-1 node's edge onto a tier-0
    node is not part of the tier-0 toposort). Tie-break is `order_key` then
    `source`, NOT alphabetical-only, so a two-simultaneous-DENY short-circuit
    returns the same denier's result (and reason) the sequential chain returns.

    Raises ValueError on a cycle (a programming error in the graph → fail at
    construction/startup, not at request time).
    """
    by_source = {n.source: n for n in nodes}
    present = set(by_source)
    # in-degree counts only edges whose target is in this node set
    indegree: Dict[str, int] = {
        n.source: len([d for d in n.depends_on if d in present]) for n in nodes
    }
    # adjacency: dependency -> dependents
    dependents: Dict[str, List[str]] = {n.source: [] for n in nodes}
    for n in nodes:
        for dep in n.depends_on:
            if dep in present:
                dependents[dep].append(n.source)

    def _tie(source: str) -> Tuple[int, str]:
        node = by_source[source]
        return (node.order_key, node.source)

    ready = sorted((s for s, deg in indegree.items() if deg == 0), key=_tie)
    ordered: List[ValidatorNode] = []
    while ready:
        source = ready.pop(0)
        ordered.append(by_source[source])
        newly_ready: List[str] = []
        for dependent in dependents[source]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                newly_ready.append(dependent)
        if newly_ready:
            ready = sorted(ready + newly_ready, key=_tie)

    if len(ordered) != len(nodes):
        raise ValueError(
            "DAG cycle detected among nodes: "
            f"{sorted(present - {n.source for n in ordered})}"
        )
    return ordered


def _build_chains(chain_nodes: Sequence[ValidatorNode]) -> List[List[ValidatorNode]]:
    """Group tier-1 nodes that have a `depends_on` edge onto ANOTHER tier-1 node
    into ordered sequential chains (e.g. D2→D4→D5) — LLD 31 §6.3.

    Each chain is toposorted internally so an upstream node runs before its
    downstream consumer. A chain is anchored by its earliest member (the one
    with no tier-1 dependency inside the chain set).
    """
    if not chain_nodes:
        return []
    chain_names = {n.source for n in chain_nodes}
    by_source = {n.source: n for n in chain_nodes}

    # union-find over the tier-1 dependency edges so co-dependent nodes land in
    # the same chain regardless of declaration order.
    parent: Dict[str, str] = {n.source: n.source for n in chain_nodes}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        parent[find(a)] = find(b)

    for node in chain_nodes:
        for dep in node.depends_on:
            if dep in chain_names:
                union(node.source, dep)

    groups: Dict[str, List[ValidatorNode]] = {}
    for node in chain_nodes:
        groups.setdefault(find(node.source), []).append(node)

    return [_toposort(members) for members in groups.values()]


def _abstain_chain_remainder(node: ValidatorNode) -> ValidationResult:
    """A chain node whose upstream abstained/errored MUST fail to the
    deterministic floor — never treat a missing upstream signal as "clean"
    (HLD §A invariant 2 / LLD 31 §6.3, §8 RES-3). Returned as an abstain: the
    combiner sees absence, the deterministic tier-0 floor decides.
    """
    return ValidationResult.abstain(
        f"{node.source}: upstream dependency abstained/failed; fail to deterministic floor"
    )


async def _run_tier1_with_edges(
    tier1: Sequence[ValidatorNode],
    request: ValidationRequest,
    session: Dict,
    stamp: Callable[[ValidationResult], ValidationResult],
    timed: Callable[[str, Awaitable], Awaitable],
) -> List[ValidationResult]:
    """Run the tier-1 nodes: gather independents in parallel, sequence chains —
    LLD 31 §6.3.

    `return_exceptions=True` is MANDATORY: a bare gather would propagate the
    first exception out and CANCEL every in-flight peer, discarding their
    results. With it, peers' verdicts are harvested; then an UNEXPECTED raise is
    RE-RAISED (below) so it fails secure via the outer handler (never a silent
    ALLOW) — the equivalence-preserving reconciliation of §7/§8 with the §3 bar
    (integration-sentinel HIGH-#2). A node's OWN returned abstain (the ML
    Bedrock-outage path) is not a raise and flows through as abstain→floor.
    (`asyncio.TaskGroup` is NOT a substitute — it cancels siblings on the first
    failure, defeating peer-harvesting.)
    """
    if not tier1:
        return []

    t1_names = {n.source for n in tier1}
    # A node participates in a chain if it has a tier-1 dependency (a downstream
    # consumer like D4→D2) OR another tier-1 node depends on it (an upstream
    # anchor like D2, which itself has no tier-1 dep but must run inside the
    # chain so it can thread its result forward). Everything else is independent.
    depended_on: set = set()
    for n in tier1:
        for dep in n.depends_on:
            if dep in t1_names:
                depended_on.add(dep)
    chain_members = [
        n for n in tier1 if (set(n.depends_on) & t1_names) or (n.source in depended_on)
    ]
    chain_names = {n.source for n in chain_members}
    independent = [n for n in tier1 if n.source not in chain_names]
    chains = _build_chains(chain_members)

    async def run_independent(node: ValidatorNode) -> ValidationResult:
        return stamp(await timed(node.source, node.run(request, session)))

    async def run_chain(chain: List[ValidatorNode]) -> List[ValidationResult]:
        # ctx is chain-LOCAL and threads the upstream result forward (D4 reads
        # D2's taint label). A FRESH top-level dict per node (`{**session,
        # **ctx}`) means a top-level rebind cannot leak across gathered
        # coroutines. Tier-1 (gathered) nodes are READ-ONLY on session by
        # contract (LLD 31 §6.3); ctx keys are upstream SOURCE names, never real
        # session keys, so the merge cannot shadow a session field.
        #
        # DENY-vs-abstain upstream semantics (LLD 31 §6.3, integration-sentinel
        # FIX-B LOW): an upstream *abstain/error* aborts the chain — every
        # downstream node fails to the deterministic floor (never treats a
        # missing taint label as clean). An upstream hard-DENY does NOT abort:
        # the DENY is a real, captured verdict (the deny-overrides combiner is
        # order-independent, so it wins regardless), and the downstream node
        # still runs with the denier's result threaded into ctx — defense-in-
        # depth keeps evaluating the deep tier for the full trail rather than
        # discarding a downstream detection because an upstream already denied.
        ctx: Dict[str, ValidationResult] = {}
        results: List[ValidationResult] = []
        aborted = False
        for node in chain:
            if aborted:
                # Once an upstream in the chain abstained/failed, every
                # downstream node fails to the floor (does NOT run).
                results.append(_abstain_chain_remainder(node))
                continue
            try:
                r = stamp(await timed(node.source, node.run(request, {**session, **ctx})))
            except BaseException as exc:  # noqa: BLE001 — re-raised, annotated for diagnostics
                # Annotate WHICH chain node raised so the outer harvester logs
                # the actual raiser, not the chain's anchor (c[0]). Still
                # re-raised below → fail-secure via the outer handler; this only
                # fixes the diagnostic attribution (integration-sentinel FIX-B
                # LOW, run.py node_order reconstruction).
                setattr(exc, "_sentra_raising_source", node.source)
                raise
            results.append(r)
            if r.is_abstain:
                aborted = True
                continue
            ctx[node.source] = r
        return results

    coros: List[Awaitable] = [run_independent(n) for n in independent]
    coros += [run_chain(c) for c in chains]

    settled = await asyncio.gather(*coros, return_exceptions=True)

    # Flatten chain lists. `return_exceptions=True` is MANDATORY so a raise in one
    # coroutine does NOT cancel its in-flight peers (we still harvest every peer's
    # verdict below). But an UNEXPECTED raise is NOT swallowed to a silent abstain:
    # it is RE-RAISED after peers are harvested so it bubbles to
    # validate_tool_call's outer `except Exception` -> `_create_error_response`
    # fail-secure error->DENY (Tenet 2: fail secure, never fail open). A genuine
    # inability-to-evaluate must surface as a 5xx (which the SDK/PEP maps to a
    # fail-secure DENY), never a fabricated 200-DENY or a silent ALLOW.
    #
    # This preserves the frozen golden baseline (T-EQUIV): a real tier-1 crash
    # fails secure exactly as the pre-DAG pipeline did (no local try/except at the
    # ML step, so a raised ml_classifier.validate propagated to the outer handler
    # -> non-ALLOW). A verdict-equivalent refactor must not open a fail-secure hole.
    #
    # Crucially, this does NOT re-block the legitimate Bedrock-outage case: the ML
    # classifier catches its OWN Bedrock/timeout/transport failures inside
    # `validate()` and RETURNS `ValidationResult.abstain(...)` (ml_classifier.py
    # `_invoke` returns None on any failure -> abstain), never RAISING. A returned
    # abstain flows through this branch untouched (abstain -> floor), matching
    # production (RES-4). Only an *unexpected* raise (a real bug/crash the
    # validator did not handle) fails secure — exactly as production does today.
    # `settled` is one entry per coroutine: an independent node's own result, or
    # a chain's list. `node_order[i]` is that coroutine's anchor node — for a
    # chain it is the topo-FIRST node (c[0]), NOT necessarily the raiser. When a
    # chain raises in a middle/late node, `run_chain` stamps the actual raiser's
    # source onto the exception (`_sentra_raising_source`) so the diagnostic log
    # names the real raiser, not the anchor (integration-sentinel FIX-B LOW).
    node_order: List[ValidatorNode] = list(independent) + [c[0] for c in chains]
    results: List[ValidationResult] = []
    for source_node, outcome in zip(node_order, settled):
        if isinstance(outcome, BaseException):
            raising_source = getattr(outcome, "_sentra_raising_source", source_node.source)
            logger.error(
                "tier-1 node raised unexpectedly; failing secure (re-raise -> "
                "outer handler DENY): %s (%s)",
                raising_source,
                outcome,
            )
            raise outcome
        elif isinstance(outcome, list):
            results.extend(outcome)
        else:
            results.append(outcome)
    return results


async def run_dag(
    nodes: Sequence[ValidatorNode],
    request: ValidationRequest,
    session: Dict,
    capture: Callable[[ValidationResult], ValidationResult],
    stamp: Callable[[ValidationResult], ValidationResult],
    timed: Callable[[str, Awaitable], Awaitable],
    *,
    mode: str,
    all_allow: Callable[[], ValidationResult],
    signals: List,
) -> Tuple[ValidationResult, List]:
    """Verdict-equivalent DAG execution — LLD 31 §6.1.

    Returns the SAME `(ValidationResult, list[Signal])` tuple
    `_run_validation_pipeline` returns today. `signals` is the caller-owned list
    `capture` appends into (the SAME list the caller reads back / passes to the
    audit path — the scheduler must not own a separate copy); `capture` appends
    each node's Signal (abstain → no signal); `stamp` attaches cross-cloud
    fields; `timed` wraps each node in the per-step timing instrumentation;
    `all_allow` builds the synthetic ALLOW.

    `mode` is `fail_fast` (default — stop at the first DENY) or `evaluate_all`
    (run every node for the trail; the returned verdict is IDENTICAL to
    `fail_fast` on the same request — verdict-neutral, LLD 31 §6.7).
    """
    # --- pre-DAG barrier pass (WS-E2 / LLD 29 §4.1 F1) -----------------------
    # A `redaction.ner` node is a happens-before BARRIER, not a graph peer: it
    # mutates `request.content_text` IN PLACE and every subsequent reader (tier-0
    # detectors, gathered tier-1 models, AND the post-run audit/feedback
    # model_dump()) must observe the redacted view. `depends_on=()` does NOT give
    # that ordering — an entry node with no dependents provides no happens-before
    # vs INDEPENDENT peers, and a barrier classified as tier-1 would run AFTER the
    # whole tier-0 frontier already read the raw content AND be parallel-gathered
    # concurrently with the ML classifier (a read/write data race on the shared
    # request). So the barrier is lifted out of the tier split and run FIRST,
    # ALONE, awaited to completion before any other node starts. It returns
    # ALLOW/ABSTAIN (never a verdict; source priority 0) and its signal is captured
    # for the trail — it can never be `winning_source`.
    barrier_nodes = [n for n in nodes if _is_barrier(n)]
    graph_nodes = [n for n in nodes if not _is_barrier(n)]
    for barrier in barrier_nodes:
        raw = await timed(barrier.source, barrier.run(request, session))
        capture(raw)

    tier0 = [n for n in graph_nodes if n.cost_tier == CostTier.DETERMINISTIC]
    tier1 = [n for n in graph_nodes if n.cost_tier == CostTier.EXPENSIVE_MODEL]

    def _cap_stamp(result: ValidationResult, *, advisory: bool = False) -> ValidationResult:
        # capture reads the (un-stamped) result to build the signal — exactly as
        # the sequential code does — then stamp the returned object so its
        # cross-cloud fields propagate onto the response, matching :394/:401/etc.
        # When `advisory` is set (evaluate_all, AFTER a tier-0 denier already
        # decided the verdict), capture the result as ADVISORY-for-trail so it
        # lands as a non-deciding signal and cannot outrank the deciding denier
        # in the downstream combiner (see the `_advisory_for_trail` rationale and
        # the tier-1 mirror below). The RETURNED object is still the real result
        # (its cross-cloud stamp propagates); only the captured signal is advisory.
        capture(_advisory_for_trail(result) if advisory else result)
        return stamp(result)

    # --- tier-0: cheap deterministic frontier, topological, short-circuit ----
    first_deny: ValidationResult | None = None
    for node in _toposort(tier0):
        raw = await timed(node.source, node.run(request, session))
        # In evaluate_all, once a tier-0 hard DENY has decided the verdict, every
        # SUBSEQUENT tier-0 DENY must be captured ADVISORY — same verdict-neutrality
        # lever the tier-1 path uses (LLD 31 §6.7). fail_fast short-circuits at the
        # FIRST (topo-order) tier-0 DENY, so its captured signals[] holds exactly
        # that one denier and `winning_source` = the topo-first denier. If
        # evaluate_all captured its later tier-0 DENYs as REAL signals, the
        # downstream combiner would rank them by priority and could name a
        # HIGHER-priority-but-later denier (e.g. sigma@70 after cross_agent@50) as
        # `winning_source` — a run-mode-dependent deciding source for the SAME
        # request, and a returned-result/winning_source disagreement WITHIN
        # evaluate_all (integration-sentinel FIX-B CRITICAL, run.py:374). Advisory-
        # capturing the later DENYs keeps the deciding source the topo-first denier
        # in BOTH modes, while STILL recording that the rest of the frontier ran.
        after_decider = mode == EVALUATE_ALL and first_deny is not None
        result = _cap_stamp(raw, advisory=after_decider and raw.should_deny)
        if result.should_deny:
            if mode == FAIL_FAST:
                # Short-circuit BEFORE any model runs (tenet 5). This reproduces
                # today's STEP-1..5 short-circuit exactly.
                return result, signals
            # evaluate_all: the FIRST (topo-order) tier-0 denier decides the
            # verdict; keep running the whole frontier (later DENYs captured
            # advisory above so they never flip winning_source — §6.7).
            first_deny = first_deny or result

    # --- tier-1: parallel-gather survivors, respecting dependency chains -----
    # fail_fast only reaches here when tier-0 all-ALLOWed; evaluate_all always
    # runs tier-1 (record what ran) but its verdict stays the tier-0 denier.
    #
    # `tier0_already_decided` is the verdict-neutrality lever (LLD 31 §6.7): when
    # a tier-0 hard DENY has ALREADY decided the verdict (only possible in
    # evaluate_all — fail_fast short-circuited above), the tier-1 nodes run for
    # the trail but their signals must be captured ADVISORY (non-deciding) so the
    # downstream combiner cannot rank a higher-priority tier-1 DENY (e.g. live ML
    # @65) over the tier-0 denier (e.g. context @60) and flip `winning_source` by
    # run mode. In fail_fast those nodes never ran at all; advisory-capture is the
    # faithful reproduction — same deciding winning_source, PLUS a trail record.
    tier0_already_decided = first_deny is not None
    if first_deny is None or mode == EVALUATE_ALL:
        tier1_results = await _run_tier1_with_edges(tier1, request, session, stamp, timed)
        hard_denies: List[ValidationResult] = []
        for r in tier1_results:
            if tier0_already_decided:
                # Verdict already decided by tier-0; record the deep tier as
                # advisory-for-trail — never let it become the deciding source.
                capture(_advisory_for_trail(r))
                continue
            # A tier-1 DENY is a candidate deciding-verdict ONLY if it asserted
            # enforce-mode (`_is_hard_deny`). NO-FLAG: the ML node's wrapper stamps
            # enforce=True on every concrete verdict, so a live ML DENY IS a
            # candidate. A future tier-1 node that forgets the flag defaults to
            # advisory (fail-safe: under-block, not surprise-block).
            hard = r.should_deny and _is_hard_deny(r)
            # AUDIT/RESPONSE VERDICT CONSISTENCY (integration-sentinel FIX-B HIGH):
            # an ADVISORY (shadow / enforce-off) tier-1 DENY must NOT surface as a
            # DENY *signal* either. `run_dag` already refuses to let it decide the
            # returned verdict (it stays out of `hard_denies`), but every OFF-PATH
            # consumer — the audit dual-write (audit_logger.log_signals →
            # DenyOverrides.combine, :247), the /trail + decisions read API
            # (decisions_service, pick_top_denier), and the trail `winning_source`
            # (validation_service:390) — recomputes the verdict over the captured
            # `signals[]` via `DenyOverrides.combine()`, which keys PURELY on
            # `decision == "DENY"` and has NO notion of `metadata["enforce"]`. So a
            # raw-captured advisory DENY (e.g. D1 trajectory shadow priority 68, or
            # D2/D3 with d{2,3}_enforce_enabled=False — the shipped default) would
            # make the PERSISTED audit `decision` = DENY while the caller correctly
            # got ALLOW. Capturing the advisory DENY via `_advisory_for_trail`
            # (decision→ALLOW, opinion preserved under metadata) is the SAME lever
            # the tier0-already-decided branch uses: it keeps the deep tier in the
            # trail without ever flipping any downstream combine to DENY. An
            # enforce-deciding DENY (ML, or D2/D3 enforce-on) is captured RAW so it
            # still decides both the verdict AND the audit. Only an ADVISORY DENY is
            # rewritten — an ALLOW / abstain is captured untouched (no spurious
            # `trail_advisory` stamp on a plain ALLOW signal).
            # enforce-deciding DENY (ML, or D2/D3 enforce-on) is captured RAW so it
            # still decides both the verdict AND the audit. Only an ADVISORY DENY is
            # rewritten — an ALLOW / abstain is captured untouched (no spurious
            # `trail_advisory` stamp on a plain ALLOW signal).
            advisory_deny = r.should_deny and not hard
            capture(_advisory_for_trail(r) if advisory_deny else r)
            if hard:
                hard_denies.append(r)
        # When ≥2 tier-1 nodes hard-DENY, the deciding verdict MUST be the
        # SHARED-ranking winner — NOT the first hard-DENY in gather/iteration
        # order. `pick_top_denier` reuses `DenyOverrides.combine()`'s exact
        # `(priority, confidence, _neg_source)` ranking (deny_overrides.py:71), so
        # run_dag's returned `ValidationResult` names the SAME deciding source the
        # downstream combiner will name as `winning_source`. A first-in-order pick
        # (`first_deny or r`) diverged the moment a lower-priority denier ran first
        # (e.g. bedrock_guardrail@40 before ml_classifier@65) — a self-inconsistent
        # verdict (LLD 31 §6.4; integration-sentinel FIX-B HIGH). Only reachable
        # once WS-L adds D1–D7 tier-1 nodes (ML is the sole tier-1 node today), but
        # the invariant must hold before those nodes land.
        if first_deny is None and hard_denies:
            first_deny = _top_tier1_denier(hard_denies)

    if first_deny is not None:
        # The verdict is the denier's OWN result (no combine() on the hot path);
        # winning_source is computed downstream over the captured signals[].
        return first_deny, signals

    # All checks passed — the synthetic ALLOW, carrying policy-sourced
    # platform/cloud_region (reproduces validation_service.py:442).
    return all_allow(), signals
