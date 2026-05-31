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
