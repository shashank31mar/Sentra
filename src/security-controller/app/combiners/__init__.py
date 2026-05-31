"""Multi-signal combiner module — Workstream 17 / LLD 17.

Public API:
    Signal               — frozen dataclass for one validator's contribution
    CombiningAlgorithm   — Protocol all algorithms implement
    DenyOverrides        — default algorithm: any DENY wins, highest-priority
                            denier's reason drives the displayed verdict

The combiner is used in two layers (per LLD 17 §6.1):
  1. ValidationService folds Sentra sub-validator signals into the
     `/v1/validate` HTTP response.
  2. decisions_service folds all signals (Sentra + edge guardrails) at
     read time for `/v1/sessions/{id}/decisions`.

Source-string taxonomy is the contract — see LLD 17 §4.
"""

from app.combiners.signal import Signal
from app.combiners.protocol import CombiningAlgorithm
from app.combiners.deny_overrides import DenyOverrides
from app.combiners.sources import Source, DEFAULT_PRIORITIES, default_priority

__all__ = [
    "Signal",
    "CombiningAlgorithm",
    "DenyOverrides",
    "Source",
    "DEFAULT_PRIORITIES",
    "default_priority",
]
