"""Unit tests for BenchmarkSessionStore (LLD 41 §4.4a, WS-D milestone D1)."""

import inspect
import pytest
from benchmarks.core.session_store import BenchmarkSessionStore


@pytest.mark.asyncio
async def test_returns_all_five_consumer_keys():
    store = BenchmarkSessionStore()
    sess = await store.get_or_create_session("sess-1")
    required_keys = {"trust_score", "quarantine_status", "abuse_counters", "tool_history", "session_id"}
    assert required_keys.issubset(sess.keys())


@pytest.mark.asyncio
async def test_initial_score_is_100_and_new_session_is_active():
    store = BenchmarkSessionStore()
    sess = await store.get_or_create_session("sess-1")
    assert sess["trust_score"] == 100.0
    assert sess["quarantine_status"] == "active"


@pytest.mark.asyncio
async def test_deny_applies_penalty():
    store = BenchmarkSessionStore()
    sess = await store.update_trust_score_deny("sess-1", violation_type="POLICY_NOT_FOUND")
    assert sess["trust_score"] == 85.0
    assert sess["quarantine_status"] == "active"


@pytest.mark.asyncio
async def test_four_denies_enter_quarantine_band():
    store = BenchmarkSessionStore()
    for _ in range(4):
        sess = await store.update_trust_score_deny("sess-1", violation_type="INDIRECT_INJECTION")
    # 100 - (15 * 4) = 40.0
    assert sess["trust_score"] == 40.0
    assert sess["quarantine_status"] == "quarantined"


@pytest.mark.asyncio
async def test_delegates_to_session_manager_helpers(monkeypatch):
    from unittest.mock import MagicMock
    store = BenchmarkSessionStore()

    qs_mock = MagicMock(side_effect=store._sm._get_quarantine_status)
    inc_mock = MagicMock(side_effect=store._sm._get_increment_amount)
    req_mock = MagicMock(side_effect=store._sm._get_consecutive_allows_required)

    monkeypatch.setattr(store._sm, "_get_quarantine_status", qs_mock)
    monkeypatch.setattr(store._sm, "_get_increment_amount", inc_mock)
    monkeypatch.setattr(store._sm, "_get_consecutive_allows_required", req_mock)

    await store.update_trust_score_deny("sess-1", "TEST")
    assert qs_mock.called

    # Reduce score to < 100 so allow increment logic runs
    for _ in range(10):
        await store.update_trust_score_allow("sess-1")

    assert req_mock.called
    assert inc_mock.called


@pytest.mark.asyncio
async def test_episode_boundary_discards_state():
    store = BenchmarkSessionStore()
    await store.update_trust_score_deny("ep1-sess", "DENY")
    
    # Fresh episode gets a new session_id
    sess2 = await store.get_or_create_session("ep2-sess")
    assert sess2["trust_score"] == 100.0
    assert sess2["quarantine_status"] == "active"


def test_only_three_public_async_methods():
    store = BenchmarkSessionStore()
    methods = [
        name for name, func in inspect.getmembers(store, predicate=inspect.iscoroutinefunction)
        if not name.startswith("_")
    ]
    assert set(methods) == {"get_or_create_session", "update_trust_score_deny", "update_trust_score_allow"}
