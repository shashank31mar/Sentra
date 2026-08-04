"""Unit tests for in-process attribution extraction (LLD 41 §4.6, WS-D milestone D3)."""

from app.api.models import ValidationResult
from app.combiners.signal import Signal
from benchmarks.core.attribution import extract_attribution


def test_reads_winning_source_from_pipeline_tuple():
    val_result = ValidationResult(decision="DENY", should_deny=True, reason="policy_violation", violation_type="POLICY_VIOLATION")
    
    signal = Signal(source="sentra.policy", decision="DENY", priority=10)
    
    attr = extract_attribution((val_result, [signal]))
    assert attr["deciding_source"] == "sentra.policy"


def test_never_infers_source_from_violation_type():
    val_result = ValidationResult(decision="DENY", should_deny=True, reason="policy_violation", violation_type="POLICY_VIOLATION")
    attr = extract_attribution((val_result, []))
    assert attr["deciding_source"] == "unattributed"


def test_trust_score_after_and_quarantined_recorded():
    val_result = ValidationResult(decision="DENY", should_deny=True, reason="test")
    session = {"trust_score": 40.0, "quarantine_status": "quarantined"}
    attr = extract_attribution((val_result, []), session=session)
    
    assert attr["trust_score_after"] == 40.0
    assert attr["quarantined"] is True
