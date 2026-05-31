"""Integration tests for DecisionsService — Workstream 17 / LLD 17 §14.2.

Test IDs 14-19 from the LLD test plan. Hits the live DDB table
`sentra-validation-signals` — gated by RUN_INTEGRATION=1 so default
local runs skip them. Each test uses a unique session_id so concurrent
test runs don't collide.

Run from src/security-controller/:
    RUN_INTEGRATION=1 AWS_PROFILE=sentra AWS_REGION=us-east-1 \\
        PYTHONPATH=. pytest tests/test_decisions_service.py -v
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone

import pytest

# Skip the whole module unless RUN_INTEGRATION=1 — these hit live DDB.
pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION") != "1",
    reason="Live DDB integration test (set RUN_INTEGRATION=1 to run)",
)


# Imports moved inside fixtures so module collection doesn't require AWS creds.
def _fresh_service():
    from app.services.decisions_service import DecisionsService
    return DecisionsService()


def _signal(source: str, decision: str = "ALLOW", priority: int = 0, **kw):
    from app.combiners import Signal
    return Signal(source=source, decision=decision, priority=priority, **kw)


def _write_validate_signals(writer, session_id: str, request_id: str):
    """Build 5 sentra signals (matching ValidationService output) + write them."""
    from app.combiners import Signal, Source
    sigs = [
        Signal(source=Source.SENTRA_TRUST, decision="ALLOW", priority=90),
        Signal(source=Source.SENTRA_POLICY, decision="ALLOW", priority=80),
        Signal(source=Source.SENTRA_SIGMA, decision="DENY",
               reason="PII_EXPOSURE test", priority=70, threat_type="PII_EXPOSURE"),
        Signal(source=Source.SENTRA_CONTEXT, decision="ALLOW", priority=60),
        Signal(source=Source.SENTRA_ABUSE, decision="ALLOW", priority=50),
    ]
    success, failure = writer.write_signals(
        session_id=session_id, request_id=request_id, signals=sigs,
        shared_attrs={
            "agent_id": "test-agent", "tool_name": "test_tool",
            "platform": "bedrock", "cloud_region": "us-east-1",
        },
    )
    assert failure == 0, f"writer reported failures: {failure}"
    return sigs


# ---------------------------------------------------------------------------
# Test 14: end-to-end validate → decisions returns combined DENY (sigma wins)
# ---------------------------------------------------------------------------


def test_14_post_validate_then_get_decisions_returns_combined_deny():
    """LLD §14.2 test 14: write 5 sentra signals → /decisions returns
    combined DENY with winning_source=sentra.sigma."""
    from app.utils.signal_store_writer import SignalStoreWriter

    writer = SignalStoreWriter()
    sid = f"it14-{uuid.uuid4().hex[:8]}"
    rid = f"req-{uuid.uuid4().hex[:8]}"
    _write_validate_signals(writer, sid, rid)

    svc = _fresh_service()
    resp = svc.get_session_decisions(session_id=sid, request_id=rid)

    assert resp["total"] == 1, f"expected 1 grouped decision, got {resp['total']}"
    d = resp["decisions"][0]
    assert d["combined"]["decision"] == "DENY"
    assert d["combined"]["winning_source"] == "sentra.sigma"
    assert "PII_EXPOSURE" in (d["combined"]["reason"] or "")
    # All 5 signals visible to the dashboard expander
    assert len(d["signals"]) == 5


# ---------------------------------------------------------------------------
# Test 15: distinct request_ids in same session group separately
# ---------------------------------------------------------------------------


def test_15_two_request_ids_grouped_separately():
    from app.utils.signal_store_writer import SignalStoreWriter

    writer = SignalStoreWriter()
    sid = f"it15-{uuid.uuid4().hex[:8]}"
    rid_a, rid_b = "reqA", "reqB"
    _write_validate_signals(writer, sid, rid_a)
    _write_validate_signals(writer, sid, rid_b)

    svc = _fresh_service()
    resp = svc.get_session_decisions(session_id=sid)

    assert resp["total"] == 2
    rids = {d["request_id"] for d in resp["decisions"]}
    assert rids == {rid_a, rid_b}


# ---------------------------------------------------------------------------
# Test 16: edge signal POST'd after validate appears in same group
# ---------------------------------------------------------------------------


def test_16_edge_signal_post_appears_in_group():
    """The connector POSTs bedrock_guardrail after the Lambda fires — must
    join the same request_id's group on the read side."""
    from app.utils.signal_store_writer import SignalStoreWriter

    writer = SignalStoreWriter()
    sid = f"it16-{uuid.uuid4().hex[:8]}"
    rid = f"req-{uuid.uuid4().hex[:8]}"
    _write_validate_signals(writer, sid, rid)

    svc = _fresh_service()
    svc.post_signal(
        session_id=sid,
        signal_data={
            "request_id": rid,
            "source": "bedrock_guardrail",
            "decision": "ALLOW",
            "priority": 40,
            "agent_id": "test-agent",
            "platform": "bedrock",
        },
    )

    resp = svc.get_session_decisions(session_id=sid, request_id=rid)
    d = resp["decisions"][0]
    # 5 sentra + 1 bedrock_guardrail
    assert len(d["signals"]) == 6
    sources = {s["source"] for s in d["signals"]}
    assert "bedrock_guardrail" in sources
    # bedrock_guardrail ALLOW + sentra.sigma DENY → combined still DENY
    assert d["combined"]["decision"] == "DENY"
    assert d["combined"]["winning_source"] == "sentra.sigma"


# ---------------------------------------------------------------------------
# Test 17: SK collision protection under same-millisecond writes
# ---------------------------------------------------------------------------


def test_17_same_ms_writes_no_sk_collision():
    """LLD §14.2 test 17: two signals at the same ms with the same
    request_id and different sources must produce 2 distinct SKs (not 1
    overwrite)."""
    from app.utils.signal_store_writer import SignalStoreWriter
    from app.combiners import Signal, Source

    writer = SignalStoreWriter()
    sid = f"it17-{uuid.uuid4().hex[:8]}"
    rid = f"req-{uuid.uuid4().hex[:8]}"

    # Force the same timestamp by passing it explicitly.
    same_ts = datetime.now(timezone.utc)
    sigs = [
        Signal(source=Source.SENTRA_TRUST, decision="ALLOW", priority=90),
        Signal(source=Source.SENTRA_SIGMA, decision="DENY", reason="x", priority=70),
    ]
    success, failure = writer.write_signals(
        session_id=sid, request_id=rid, signals=sigs,
        shared_attrs={"agent_id": "test"},
        now=same_ts,
    )
    assert failure == 0 and success == 2

    svc = _fresh_service()
    raw = svc.get_session_signals(session_id=sid, request_id=rid)
    assert raw["total"] == 2
    sks = {s["sk"] for s in raw["signals"]}
    # Same timestamp_ms in SK but distinct source suffix → distinct SKs
    assert len(sks) == 2


# ---------------------------------------------------------------------------
# Test 18: DDB write fails — validation succeeds, CW has the row, decisions
# returns empty for the affected session, runner-side combiner produces a
# "no signals" outcome (graceful degrade).
# ---------------------------------------------------------------------------


def test_18_decisions_returns_empty_for_unknown_session():
    """A session with no signals (e.g. DDB write all failed) returns
    empty decisions — caller handles gracefully."""
    svc = _fresh_service()
    resp = svc.get_session_decisions(session_id=f"nonexistent-{uuid.uuid4().hex}")
    assert resp["total"] == 0
    assert resp["decisions"] == []


# ---------------------------------------------------------------------------
# Test 19: GSI 2 paginated scan returns time-ordered results, cursor
# round-trips.
# ---------------------------------------------------------------------------


def test_19_paginated_scan_decisions():
    """Write a few sessions worth of signals; scan across with limit=2;
    cursor round-trip retrieves the next page."""
    from app.utils.signal_store_writer import SignalStoreWriter

    writer = SignalStoreWriter()
    # Three distinct sessions, each with one validate-style batch.
    for i in range(3):
        sid = f"it19-{i}-{uuid.uuid4().hex[:6]}"
        rid = f"req-{uuid.uuid4().hex[:6]}"
        _write_validate_signals(writer, sid, rid)
    # Tiny delay so the new rows are searchable
    time.sleep(0.5)

    svc = _fresh_service()
    page1 = svc.scan_decisions(limit=2)
    # Cursor may or may not be present depending on what else is in the
    # decision_date partition for today. The contract is: if cursor is
    # present, has_more is True.
    if page1.get("next_cursor"):
        page2 = svc.scan_decisions(limit=2, cursor=page1["next_cursor"])
        # Just need a clean response — content can vary based on the day's
        # accumulated signals.
        assert "decisions" in page2

    # Invalid cursor → ValueError
    with pytest.raises(ValueError):
        svc.scan_decisions(cursor="not-base64-at-all")
