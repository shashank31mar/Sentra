"""DenyOverrides combining algorithm — LLD 17 §6.3.

Semantics:
  - Any DENY in the signal set → combined DENY.
  - Among DENYs: highest `priority` wins; ties broken by higher
    `confidence`; ties broken alphabetically on `source` for determinism.
  - All ALLOW → combined ALLOW.
  - Empty input → ValueError (no signals = no defensible verdict).

Why deterministic tie-breaks
-----------------------------
Tests assert that the same input always produces the same combined.
Non-determinism here would make test 7 in LLD 17 §14.1 flaky and would
also make production "winning_source" attribution drift between requests
that emit identical signal sets.
"""

from __future__ import annotations

from typing import Sequence

from app.combiners.signal import Signal


class DenyOverrides:
    name = "deny-overrides"

    def combine(self, signals: Sequence[Signal]) -> Signal:
        if not signals:
            raise ValueError("DenyOverrides.combine: signals must be non-empty")

        denies = [s for s in signals if s.decision == "DENY"]
        if denies:
            # Sort key inverted so max() picks the right tuple. The
            # alphabetical source tie-break is *reversed* (negated) so a
            # smaller source string wins — matches what `sorted(...)[0]`
            # would do for the same comparator.
            def rank(s: Signal):
                return (s.priority, s.confidence or 0.0, _neg_source(s.source))

            winner = max(denies, key=rank)
            return Signal(
                source="combined",
                decision="DENY",
                reason=winner.reason,
                priority=winner.priority,
                confidence=winner.confidence,
                threat_type=winner.threat_type,
                matched_rule=winner.matched_rule,
                severity=winner.severity,
                metadata={"winning_source": winner.source},
            )

        return Signal(
            source="combined",
            decision="ALLOW",
            reason=None,
            priority=0,
            metadata={"winning_source": None},
        )


def _neg_source(source: str) -> tuple:
    """Return a sort key that orders 'sentra.sigma' before 'sentra.trust'
    when used inside a max() lookup. Pure helper, kept private."""
    # max() picks the largest tuple; we want alphabetically *first* to win
    # the tie, so negate by inverting each codepoint.
    return tuple(-ord(c) for c in source)


def pick_top_denier(signals: Sequence[Signal]) -> "Signal | None":
    """Return the single highest-ranked DENY Signal, or None if there are no
    DENYs — WS-C / LLD 31 §6.4 (ADDITIVE; the ranking is NOT changed).

    This REUSES `DenyOverrides.combine()`'s exact ranking so the DAG scheduler's
    tier-1 multi-DENY pick and the downstream `combine()` share ONE ranking
    source of truth. The scheduler must return the denier's own
    `ValidationResult` (its operator-facing `reason`), so it needs the winning
    *source*, not the synthetic "combined" Signal `combine()` returns.

    The key is byte-for-byte the tuple `combine()` uses
    `(priority, confidence or 0.0, _neg_source(source))` — including the
    `confidence or 0.0` coalescing and the same `_neg_source` codepoint
    inversion — so a `None` confidence coalesces to 0.0 and the
    alphabetically-smaller source wins a tie, identically to `combine()`. A
    fresh alphabetical `sorted()` (or dropping the coalesce) would silently
    diverge from `combine()` on the source/confidence tie-break — the exact bug
    this shared helper exists to prevent. It does NOT re-implement or alter the
    algorithm; it factors out the winner-selection so there is no second copy to
    drift.
    """
    denies = [s for s in signals if s.decision == "DENY"]
    if not denies:
        return None
    return max(denies, key=lambda s: (s.priority, s.confidence or 0.0, _neg_source(s.source)))
