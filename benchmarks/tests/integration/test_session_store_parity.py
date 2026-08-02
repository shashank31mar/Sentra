"""Integration test for BenchmarkSessionStore parity against SessionManager (LLD 41 §4.4a, WS-D milestone D1)."""

import pytest
from benchmarks.core.session_store import BenchmarkSessionStore
from app.utils.session_manager import SessionManager


@pytest.mark.asyncio
async def test_session_store_trust_score_and_quarantine_parity():
    """Drive DENY/ALLOW sequences and verify exact trust_score and quarantine_status parity."""
    store = BenchmarkSessionStore()
    sm = SessionManager()

    session_id = "parity-sess-1"
    sess = await store.get_or_create_session(session_id)

    assert sess["trust_score"] == 100.0
    assert sess["quarantine_status"] == sm._get_quarantine_status(100.0)

    # 1. First DENY
    sess = await store.update_trust_score_deny(session_id, "TEST_VIOLATION")
    assert sess["trust_score"] == 85.0
    assert sess["quarantine_status"] == sm._get_quarantine_status(85.0)

    # 2. Three more DENYs (total 4 DENYs -> score = 40.0, entering quarantine)
    for _ in range(3):
        sess = await store.update_trust_score_deny(session_id, "TEST_VIOLATION")

    assert sess["trust_score"] == 40.0
    assert sess["quarantine_status"] == sm._get_quarantine_status(40.0)
    assert sess["quarantine_status"] == "quarantined"

    # 3. Recovery via ALLOWs
    # At score 40.0, _get_consecutive_allows_required returns 12, increment 3
    req_allows = sm._get_consecutive_allows_required(40.0)
    inc = sm._get_increment_amount(40.0)
    assert req_allows == 12
    assert inc == 3

    for _ in range(req_allows - 1):
        sess = await store.update_trust_score_allow(session_id)
        assert sess["trust_score"] == 40.0  # Threshold not reached yet

    # Final allow triggers increment
    sess = await store.update_trust_score_allow(session_id)
    assert sess["trust_score"] == 43.0
    assert sess["quarantine_status"] == sm._get_quarantine_status(43.0)
    assert sess["quarantine_status"] == "warning"
