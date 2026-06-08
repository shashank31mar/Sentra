"""Unit tests for DecisionsService.record_verdict (WS-21 T34).

Standalone (not gated by RUN_INTEGRATION) — fully mocked, no AWS.
"""
from unittest.mock import Mock

import pytest

from app.services.decisions_service import DecisionsService


def _verdict_service():
    """DecisionsService with the DDB client + signal lookup stubbed (no AWS)."""
    svc = DecisionsService()
    svc._client = Mock()          # _ddb() returns this
    svc._emit_verdict_metric = Mock()
    return svc


def test_record_verdict_writes_attrs_and_emits():
    svc = _verdict_service()
    svc.get_session_signals = Mock(return_value={"signals": [
        {"sk": "req-1#100#sigma", "agent_id": "agA", "operator_verdict": None},
        {"sk": "req-1#100#trust", "agent_id": "agA"},
    ]})
    out = svc.record_verdict("sess-1:req-1", "false_positive", "benign", "op1")
    assert out["decision_id"] == "sess-1:req-1"
    assert out["verdict"] == "false_positive"
    assert "verdict_at" in out
    assert svc._client.update_item.call_count == 2  # one per signal row
    svc._emit_verdict_metric.assert_called_once_with("false_positive", "agA")


def test_record_verdict_malformed_id_raises_value_error():
    svc = _verdict_service()
    with pytest.raises(ValueError):
        svc.record_verdict("no-colon-here", "false_positive", "r", "o")


def test_record_verdict_not_found_raises_lookup_error():
    svc = _verdict_service()
    svc.get_session_signals = Mock(return_value={"signals": []})
    with pytest.raises(LookupError):
        svc.record_verdict("sess:req", "false_positive", "r", "o")


def test_record_verdict_already_verdicted_raises_runtime_error():
    svc = _verdict_service()
    svc.get_session_signals = Mock(return_value={"signals": [
        {"sk": "x", "operator_verdict": "confirmed_threat"},
    ]})
    with pytest.raises(RuntimeError):
        svc.record_verdict("sess:req", "false_positive", "r", "o")
