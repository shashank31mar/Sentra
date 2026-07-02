"""Record-what-ran decision trail — WS-D / LLD 33 (FR-6.8, NFR-10, ADR-031).

`build_trail` is a **pure post-pipeline consumer** of the stable
`(signals[], _step_timings, verdict)` seam the WS-C DAG scheduler already
produces (LLD 33 §7.1). It runs NO validator, changes NO pipeline return point,
and never touches `DenyOverrides.combine()`'s code. It classifies the phase's
coverage set into the four disjoint buckets:

    ran         — a real Signal was emitted (the layer voted).
    ran-ABSTAIN — the layer ran but declined to vote (no Signal).
    ran-ERROR   — the layer ran + a verdict was decided but it emitted no usable
                  Signal (a fail-secure / unstamped denying result — a belt-and-
                  suspenders backstop after the §7.1.1 producer stamp).
    not-run     — the layer was never invoked at all → a `NotRunMarker`.

Invariant (ii) (LLD 33 §3): a `NotRunMarker` is a SEPARATE frozen type, not a
`Signal` — it has no `decision` field, so it structurally cannot be passed to
`DenyOverrides.combine()`. The absence of `decision` is the whole guarantee.

Not-run / abstain / error markers are persisted alongside the ran `Signal` rows
on the SAME `sentra-validation-signals` partition (via
`SignalStoreWriter.write_not_run_markers`), so the console reads ran + not-run in
ONE Query. Aggregate counts + `winning_source` / `block_point` are DERIVED on
read (LLD 33 §2.3 / §6.3) — never stored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal


@dataclass(frozen=True)
class NotRunMarker:
    """A coverage-set layer that was NEVER invoked (``not_run``), ran-but-abstained
    (``abstain``), or ran-and-errored (``error``). Deliberately NOT a Signal: no
    ``decision`` field, so it structurally cannot be passed to
    ``DenyOverrides.combine()`` — that is invariant (ii) (LLD 33 §3) enforced by
    the type system, not a runtime check.

    Do NOT add a ``decision`` field "for symmetry" — its absence is the whole
    invariant-(ii) guarantee, and it is asserted again at persistence
    (``_build_marker_item``).
    """

    source: str                                                     # coverage-set source
    record_type: Literal["not_run", "abstain", "error"] = "not_run"  # row-type discriminator — NOT a decision
    reason: str = "gated by earlier DENY"                           # DERIVED (§7.1.3) — never a blanket lie
    phase: str = "request"
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class TrailResult:
    """The output of :func:`build_trail`: the not-run/abstain/error markers to
    persist alongside the ran signals, plus a small summary. The ran signals
    themselves are the caller-owned ``signals[]`` list — the trail builder never
    copies or re-orders them."""

    markers: List[NotRunMarker]
    summary: Dict = field(default_factory=dict)


def coverage_set(phase: str) -> List[str]:
    """Sources that COULD run for this phase, in stable coverage order (§5.1, KD-3).

    TODAY this returns ``STATIC_FALLBACK_ORDER`` (combiners/sources.py) — the LIVE
    coverage source, since WS-C's pure ``coverage_sources(phase)`` accessor is NOT
    YET BUILT (§5.1 / §13 gap #4): ``scheduler`` exports only
    ``CostTier``/``ValidatorNode``/``build_dag``/``run_dag``, and the landed
    ``build_dag(service, phase, stamp_ctx)`` is service-coupled, not a pure lookup.

    A missing/unknown phase degrades to the request graph, never crashes (SEC-4):
    the ``coverage_sources("request")`` fallback inside the ``try`` and
    ``STATIC_FALLBACK_ORDER`` outside it both cover this. When WS-C lands the pure
    accessor the ``try`` starts succeeding with NO change here (KD-3).
    """
    try:
        from app.services.scheduler import coverage_sources  # WS-C seam — NOT YET BUILT
        return coverage_sources(phase) or coverage_sources("request")
    except (ImportError, AttributeError, KeyError):
        from app.combiners.sources import STATIC_FALLBACK_ORDER
        return STATIC_FALLBACK_ORDER  # the live path today


def build_trail(
    *,
    signals,
    step_timings,
    coverage,
    winning_source,
    phase,
    is_deny,
) -> TrailResult:
    """Classify ``coverage`` into ran / ran-ABSTAIN / ran-ERROR / not-run (§7.1/§7.2).

    Pure function; runs no validator; changes no return point; never touches
    ``DenyOverrides.combine()``'s code. The four sets are disjoint by construction
    (each coverage source lands in exactly one bucket), which is what makes a
    same-SK collision impossible (§11.2).

    Args:
        signals: the caller-owned ``signals[]`` list the pipeline captured. Each
            has a ``.source`` and a ``.decision`` ("ALLOW"/"DENY").
        step_timings: a BY-VALUE snapshot of ``_step_timings`` (KD-4). Its keyset
            is the short step labels (``"trust"``, ``"ml"``, …); the non-validator
            plumbing labels are excluded via ``STEP_LABEL_TO_SOURCE``.
        coverage: the coverage-set list (``coverage_set(phase)``) in coverage order.
        winning_source: the deny-overrides deciding source when the verdict is a
            DENY (used only to NAME the ran DENIER); may be None (read-time
            recompute fills the durable copy — §6.3).
        phase: the validation phase (``"request"`` today), stamped on every marker.
        is_deny: the verdict's ``should_deny``.
    """
    from app.combiners.sources import STEP_LABEL_TO_SOURCE

    cov_order = list(coverage)
    cov = set(cov_order)
    invoked = {
        STEP_LABEL_TO_SOURCE[k]
        for k in (step_timings or {})
        if k in STEP_LABEL_TO_SOURCE
    } & cov
    ran = {s.source for s in signals}
    deny_sources = {s.source for s in signals if s.decision == "DENY"}
    denier = {winning_source} if (is_deny and winning_source) else set()
    ran_error = (invoked & denier) - ran            # decided verdict, no Signal → ERROR (backstop after §7.1.1)
    ran_abstain = invoked - ran - ran_error          # ran, genuinely abstained
    not_run = cov - invoked                           # never invoked

    def _not_run_reason(src: str) -> str:
        # §7.1.3 — PURELY POSITIONAL, no is_deny disjunct. A DENY *elsewhere* on the
        # request must not make a cost-skipped node that sits BEFORE the denier read
        # "gated" — that would overstate the gate (invariant i). Gate ONLY if a
        # DENY-voting ran source PRECEDES `src` in cov_order.
        i = cov_order.index(src)
        return (
            "gated by earlier DENY"
            if any(d in cov_order[:i] for d in deny_sources)
            else "skipped for cost/tier"
        )

    # Emit markers in a stable coverage order per bucket so the persisted rows and
    # the read-time classification see the same shape.
    markers: List[NotRunMarker] = []
    markers += [
        NotRunMarker(
            source=s,
            record_type="error",
            reason="ran; decided verdict but emitted no signal (fail-secure/unstamped)",
            phase=phase,
        )
        for s in cov_order
        if s in ran_error
    ]
    markers += [
        NotRunMarker(
            source=s,
            record_type="abstain",
            reason="ran; abstained (no vote)",
            phase=phase,
        )
        for s in cov_order
        if s in ran_abstain
    ]
    markers += [
        NotRunMarker(
            source=s,
            record_type="not_run",
            reason=_not_run_reason(s),
            phase=phase,
        )
        for s in cov_order
        if s in not_run
    ]
    return TrailResult(markers=markers, summary={"phase": phase})


def resolve_high_assurance(tenant_setting, session_override) -> bool:
    """Escalate-only high-assurance resolution (§8.1, D3.1).

    ``effective_high_assurance = tenant_setting OR session_override`` — the session
    override can only ESCALATE, never downgrade. ``request.context`` is
    agent-supplied and untrusted, so a caller must not be able to thin its own
    audit by sending ``override=off`` when the tenant enabled the mode:
      * tenant-ON + session-off → ON
      * tenant-OFF + session-on → ON
    High-assurance is a verdict-neutral recording knob (invariant vi), so
    escalate-only can never affect a decision — it only prevents a self-serving
    reduction of a regulated tenant's record.
    """
    return bool(tenant_setting) or bool(session_override)
