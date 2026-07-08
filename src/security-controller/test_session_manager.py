"""WS-G G0.11 (lld/40 §7.1d) — session read surfaces the quarantine WHY-TRACE.

`_format_session_for_api` must surface (1) the quarantine ORIGIN (operator vs
auto), distinguished by whether an operator sub was recorded, and (2) an ordered
trigger-signal list — from the fields already stored on the session item. When
those fields are absent it degrades to `quarantine_status` alone (never a
fabricated trace). Pure formatter test — no AWS.
"""
from __future__ import annotations

from app.utils.session_manager import SessionManager


def _fmt(item):
    # _format_session_for_api is a pure item→dict transform; a bare instance is
    # fine (no boto3 call is made by the formatter itself).
    return SessionManager.__new__(SessionManager)._format_session_for_api(item)


def test_format_session_surfaces_quarantine_origin_and_signals():
    # Operator-initiated quarantine: an operator sub WAS recorded → origin=operator.
    operator_item = {
        "session_id": "s-op", "agent_id": "t_a-x", "trust_score": 20.0,
        "quarantine_status": "quarantined",
        "quarantine_reason": "manual hold: suspicious egress",
        "quarantine_operator": "op-sub-123",
        "trigger_signals": ["sentra.sigma:rule-7", "sentra.trust:below-threshold"],
    }
    out = _fmt(operator_item)
    assert out["quarantine_origin"] == "operator"
    assert out["quarantine_operator"] == "op-sub-123"
    assert out["quarantine_reason"] == "manual hold: suspicious egress"
    # Ordered trigger-signal list preserved from the stored attribute.
    assert out["trigger_signals"] == ["sentra.sigma:rule-7", "sentra.trust:below-threshold"]

    # Auto (trust-driven) quarantine: NO operator recorded → origin=auto, and the
    # reason folds into a one-element trigger list when no explicit list is stored.
    auto_item = {
        "session_id": "s-auto", "agent_id": "t_a-y", "trust_score": 15.0,
        "quarantine_status": "quarantined",
        "quarantine_reason": "trust below 40",
    }
    out_auto = _fmt(auto_item)
    assert out_auto["quarantine_origin"] == "auto", "no operator sub → auto origin, not operator"
    assert out_auto["quarantine_operator"] is None
    assert out_auto["trigger_signals"] == ["trust below 40"]


def test_format_session_degrades_when_no_quarantine_fields():
    # An active session with none of the why-trace fields degrades to status-only:
    # origin None, empty trigger list, never a fabricated trace.
    active_item = {
        "session_id": "s-active", "agent_id": "t_a-z", "trust_score": 100.0,
        "quarantine_status": "active",
    }
    out = _fmt(active_item)
    assert out["quarantine_status"] == "active"
    assert out["quarantine_origin"] is None
    assert out["quarantine_operator"] is None
    assert out["trigger_signals"] == []
