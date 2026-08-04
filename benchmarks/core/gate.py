"""CI Evaluation Gate for Mode A (LLD 41 §15, FR-14.2, G3)."""

from typing import Any, Dict, Optional
import sys
from pathlib import Path

# Add repo root to path to ensure scripts can be imported
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Import _load_thresholds verbatim from scripts/eval_ml_classifier.py:284
from scripts.eval_ml_classifier import _load_thresholds


def check_benchmark_gate(
    metrics: Dict[str, Any],
    thresholds_path: str,
) -> Optional[bool]:
    """Check Mode A benchmark CI gate.
    
    Returns:
        True: Gate passed.
        False: Gate failed.
        None: No verdict (when detector readiness is 'inert' or 'partial').
    """
    thresholds = _load_thresholds(thresholds_path)
    fp_budget = thresholds.get("fp_budget", 0.01)
    recall_floor = thresholds.get("recall_floor", 0.70)

    readiness = metrics.get("readiness", "scored")
    if readiness in ("inert", "partial") or readiness.startswith("partial"):
        # Inert or partial readiness produces no gate verdict (prevents vacuous pass)
        return None

    fp_rate = metrics.get("fp_rate", 0.0)
    recall = metrics.get("recall", 0.0)

    # Two-sided gate: fp_rate <= budget AND recall >= floor
    passed = (fp_rate <= fp_budget) and (recall >= recall_floor)
    return passed
