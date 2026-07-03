"""Offline detection eval-harness + the R5-C FP-budget gate — WS-L M5.2/M5.3.

LLD 32 §14.2. The AUTHORITATIVE quality gate for D1/D2/D3: it scores a detector
against a labeled corpus and computes precision / recall / F1 + the FP-rate. No
threshold/rollout change ships without a green harness run (§14.2). Online
estimators (human-adjudicated overturns = online FP; the §8 reclassify = online FN)
COMPLEMENT it — but the reclassify/retrain loop itself is NOT built here (this is
the offline EVAL, not the retrain pipeline).

Because D2/D3 enforce (no shadow node), quality comes from THIS offline harness +
the online overturn estimators, not a shadow comparison (§14.2 footgun).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, List, Tuple

from app.api.models import ValidationRequest, ValidationResult


@dataclass(frozen=True)
class DetectorScore:
    """Precision / recall / F1 + confusion-matrix counts + FP-rate for a detector
    over a labeled corpus. FP-rate = FP / (FP + TN) — the fraction of BENIGN inputs
    the detector wrongly DENYs (the R5-C rollout budget is a ceiling on this)."""
    tp: int
    fp: int
    tn: int
    fn: int

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return (self.tp / denom) if denom else 0.0

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return (self.tp / denom) if denom else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return (2 * p * r / (p + r)) if (p + r) else 0.0

    @property
    def fp_rate(self) -> float:
        denom = self.fp + self.tn
        return (self.fp / denom) if denom else 0.0


# A labeled corpus item: (request, is_attack). `is_attack=True` means the input
# SHOULD be DENYed (a positive); False means benign (a negative).
LabeledItem = Tuple[ValidationRequest, bool]


async def score_detector(
    detect: Callable[[ValidationRequest], Awaitable[ValidationResult]],
    corpus: List[LabeledItem],
) -> DetectorScore:
    """Run `detect` over every labeled item and tally the confusion matrix.

    A DENY (`should_deny`) on a labeled-attack item is a TP; a DENY on a benign item
    is a FP; an ALLOW/ABSTAIN on an attack is a FN; an ALLOW/ABSTAIN on benign is a TN.
    An abstain is treated as "did not detect" (not a positive) — fail-secure at the
    verdict layer is a separate concern; here we measure the detector's own signal.
    """
    tp = fp = tn = fn = 0
    for req, is_attack in corpus:
        result = await detect(req)
        denied = bool(getattr(result, "should_deny", False))
        if is_attack and denied:
            tp += 1
        elif is_attack and not denied:
            fn += 1
        elif not is_attack and denied:
            fp += 1
        else:
            tn += 1
    return DetectorScore(tp=tp, fp=fp, tn=tn, fn=fn)


def fp_budget_gate(score: DetectorScore, fp_budget: float) -> bool:
    """R5-C enforce-graduation gate (WS-L M5.3, LLD 32 §5/§14).

    Returns True (the detector MAY graduate to live-enforce) ONLY when its measured
    FP-rate is at or below the budget. A detector whose FP-rate exceeds the budget
    stays ADVISORY (the gate returns False → the enforce flag is not flipped). This
    is a rollout threshold, NOT a shadow phase: a forgotten enable under-blocks (a
    missed detection, caught by §14), never a surprise FP outage.
    """
    return score.fp_rate <= fp_budget
