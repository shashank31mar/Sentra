"""In-process attribution extraction and decision signal combined analysis (LLD 41 §4.6, WS-D milestone D3)."""

from typing import Any, Dict, Optional, Tuple
from app.combiners import DenyOverrides, Signal


def extract_attribution(
    pipeline_tuple: Tuple[Any, Any],
    *,
    session: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Extract exact attribution from ValidationService._run_validation_pipeline return tuple.

    FR-14.8 & Tenet 3 compliance:
    - winning_source is derived from DenyOverrides().combine(signals) or validation_result.source.
    - NEVER infers source from violation_type.
    - Captures trust_score_after and quarantined status from session dict.
    """
    val_result, signals = pipeline_tuple

    deciding_source = "unattributed"
    if signals:
        top_signal = DenyOverrides().combine(signals)
        if top_signal and hasattr(top_signal, "metadata") and isinstance(top_signal.metadata, dict) and top_signal.metadata.get("winning_source"):
            src = top_signal.metadata["winning_source"]
            deciding_source = getattr(src, "value", str(src))
        elif top_signal and hasattr(top_signal, "source") and top_signal.source:
            src = top_signal.source
            deciding_source = getattr(src, "value", str(src))
        elif top_signal and isinstance(top_signal, dict) and top_signal.get("source"):
            src = top_signal["source"]
            deciding_source = getattr(src, "value", str(src))
    
    if deciding_source == "unattributed" and hasattr(val_result, "source") and val_result.source:
        src = val_result.source
        deciding_source = getattr(src, "value", str(src))

    trust_score_after = session.get("trust_score", 100.0) if session else 100.0
    quarantined = session.get("quarantine_status") in ("quarantined", "suspended") if session else False

    return {
        "deciding_source": deciding_source,
        "trust_score_after": trust_score_after,
        "quarantined": quarantined,
    }
