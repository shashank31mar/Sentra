"""CombiningAlgorithm Protocol — LLD 17 §6.2.

Every combining algorithm is a pure function from `Sequence[Signal]` to
one combined `Signal`. The Protocol exists so future algorithms
(PermitOverrides, OrderedDenyOverrides, WeightedConfidenceCombiner) can
be swapped in without touching call sites.
"""

from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable

from app.combiners.signal import Signal


@runtime_checkable
class CombiningAlgorithm(Protocol):
    """A pure function that folds N signals into 1 combined signal.

    Implementations MUST:
    - Raise `ValueError` on empty input (no defensible default verdict).
    - Set `source="combined"` on the returned Signal so consumers can
      distinguish an aggregate from a raw producer signal.
    - Populate `metadata["winning_source"]` with the source string that
      drove the verdict (essential for the dashboard's "By" column).
    """

    name: str

    def combine(self, signals: Sequence[Signal]) -> Signal: ...
