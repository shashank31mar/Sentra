"""Tests for the deterministic queue logic — ordering, sent-log exclusion, name normalization.

Run:  cd scripts/outreach && python -m pytest tests/ -v
(No AWS, no network, no Gmail — pure logic.)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `lib` importable

from lib import queue  # noqa: E402


def _write_queue(tmp_path: Path, eligible: list[dict]) -> Path:
    p = tmp_path / "send_queue.yaml"
    p.write_text(yaml.safe_dump({"eligible": eligible, "excluded": []}))
    return p


def _write_sent(tmp_path: Path, funds: list[str]) -> Path:
    p = tmp_path / "sent_log.jsonl"
    p.write_text("".join(json.dumps({"fund": f, "date": "2026-07-28"}) + "\n" for f in funds))
    return p


def test_orders_by_tier_then_confidence(tmp_path):
    q = _write_queue(tmp_path, [
        {"fund": "Zeta", "prestige": "T3", "confidence": "high"},
        {"fund": "Alpha", "prestige": "T1", "confidence": "med"},
        {"fund": "Beta", "prestige": "T1", "confidence": "high"},
        {"fund": "Gamma", "prestige": "Emerging", "confidence": "high"},
    ])
    sent = _write_sent(tmp_path, [])
    batch = queue.next_batch(q, sent, n=10)
    assert [f["fund"] for f in batch] == ["Beta", "Alpha", "Zeta", "Gamma"]


def test_excludes_already_sent(tmp_path):
    q = _write_queue(tmp_path, [
        {"fund": "Alpha", "prestige": "T1", "confidence": "high"},
        {"fund": "Beta", "prestige": "T2", "confidence": "high"},
    ])
    sent = _write_sent(tmp_path, ["Alpha"])
    batch = queue.next_batch(q, sent, n=10)
    assert [f["fund"] for f in batch] == ["Beta"]


def test_sent_match_is_normalized(tmp_path):
    # Sent log recorded a differently-spelled variant; must still be excluded.
    q = _write_queue(tmp_path, [
        {"fund": "Basis Set Ventures", "prestige": "T2", "confidence": "high"},
    ])
    sent = _write_sent(tmp_path, ["basis set  ventures"])  # case + double space
    batch = queue.next_batch(q, sent, n=10)
    assert batch == []


def test_respects_batch_size(tmp_path):
    q = _write_queue(tmp_path, [
        {"fund": f"F{i}", "prestige": "T1", "confidence": "high"} for i in range(20)
    ])
    sent = _write_sent(tmp_path, [])
    assert len(queue.next_batch(q, sent, n=10)) == 10


def test_missing_sent_log_is_empty_not_error(tmp_path):
    q = _write_queue(tmp_path, [{"fund": "Alpha", "prestige": "T1", "confidence": "high"}])
    missing = tmp_path / "does_not_exist.jsonl"
    batch = queue.next_batch(q, missing, n=10)
    assert [f["fund"] for f in batch] == ["Alpha"]


def test_corrupt_sent_line_is_skipped(tmp_path):
    q = _write_queue(tmp_path, [
        {"fund": "Alpha", "prestige": "T1", "confidence": "high"},
        {"fund": "Beta", "prestige": "T2", "confidence": "high"},
    ])
    p = tmp_path / "sent_log.jsonl"
    p.write_text('{"fund": "Alpha"}\nNOT JSON\n')
    batch = queue.next_batch(q, p, n=10)
    assert [f["fund"] for f in batch] == ["Beta"]  # Alpha excluded, corrupt line ignored


def test_excludes_dropped_funds(tmp_path):
    # A fund dropped by a prior conflict re-check must not be re-picked.
    q = _write_queue(tmp_path, [
        {"fund": "Alpha", "prestige": "T1", "confidence": "high"},
        {"fund": "Beta", "prestige": "T2", "confidence": "high"},
        {"fund": "Gamma", "prestige": "T3", "confidence": "high"},
    ])
    sent = _write_sent(tmp_path, [])
    dropped = tmp_path / "dropped.jsonl"
    dropped.write_text(json.dumps({"fund": "Beta", "competitor": "Runlayer"}) + "\n")
    batch = queue.next_batch(q, sent, n=10, dropped_log_path=dropped)
    assert [f["fund"] for f in batch] == ["Alpha", "Gamma"]  # Beta dropped


def test_working_set_refill_headroom(tmp_path):
    # Requesting n*multiplier returns more than the cap so Stage-0 drops can refill.
    q = _write_queue(tmp_path, [
        {"fund": f"F{i:02d}", "prestige": "T2", "confidence": "high"} for i in range(30)
    ])
    sent = _write_sent(tmp_path, [])
    working = queue.next_batch(q, sent, n=20)  # cap 10 x mult 2
    assert len(working) == 20  # headroom to drop up to 10 and still reach 10 clean
