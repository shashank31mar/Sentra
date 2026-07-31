"""Deterministic send-queue reader — no LLM, no network.

Reads the curated send_queue.yaml (Layer 0, founder-approved) and the append-only
sent_log.jsonl, and returns the next N eligible funds not yet sent. This is the only
place the daily loop touches the fund list — it NEVER re-parses the messy shortlist.

Ordering: prestige tier (T1 > T2 > T3 > Emerging) then confidence (high > med > low),
matching the order the curating pass wrote. We re-sort defensively so the contract holds
even if the YAML is hand-edited out of order.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

_TIER_RANK = {"T1": 0, "T2": 1, "T3": 2, "Emerging": 3}
_CONF_RANK = {"high": 0, "med": 1, "medium": 1, "low": 2}


def _norm(name: str) -> str:
    """Normalize a fund name for matching against the sent log (case/space/punct-insensitive)."""
    return "".join(ch for ch in name.lower() if ch.isalnum())


def load_eligible(queue_path: Path) -> list[dict]:
    with queue_path.open() as fh:
        data = yaml.safe_load(fh) or {}
    eligible = data.get("eligible") or []
    if not isinstance(eligible, list):
        raise ValueError(f"'eligible' in {queue_path} is not a list")
    return eligible


def _load_norm_names(log_path: Path) -> set[str]:
    """Return normalized fund names from a jsonl log ({fund: ...} per line)."""
    names: set[str] = set()
    if not log_path.exists():
        return names
    with log_path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # skip a corrupt line rather than crash the morning job
            fund = rec.get("fund")
            if fund:
                names.add(_norm(fund))
    return names


def load_sent_names(sent_log_path: Path) -> set[str]:
    """Normalized fund names already sent (idempotency key)."""
    return _load_norm_names(sent_log_path)


def load_dropped_names(dropped_log_path: Path) -> set[str]:
    """Normalized fund names dropped by a prior day's fresh conflict re-check.

    A fund newly found to back a competitor is excluded from future dequeues until
    the founder clears its entry — so it isn't re-picked and re-dropped every morning.
    """
    return _load_norm_names(dropped_log_path)


def _sort_key(fund: dict) -> tuple[int, int, str]:
    tier = _TIER_RANK.get(str(fund.get("prestige", "")).strip(), 9)
    conf = _CONF_RANK.get(str(fund.get("confidence", "")).strip().lower(), 9)
    return (tier, conf, str(fund.get("fund", "")))


def next_batch(
    queue_path: Path,
    sent_log_path: Path,
    n: int,
    dropped_log_path: Path | None = None,
) -> list[dict]:
    """Next N eligible funds, in send order, excluding funds already sent OR previously
    dropped by a fresh conflict re-check.

    N is typically the *working set* (> daily cap) so the prep's Stage-0 re-check can drop
    newly-conflicted funds and still reach the cap from the remainder.
    """
    eligible = load_eligible(queue_path)
    sent = load_sent_names(sent_log_path)
    dropped = load_dropped_names(dropped_log_path) if dropped_log_path else set()
    skip = sent | dropped
    fresh = [f for f in eligible if _norm(str(f.get("fund", ""))) not in skip]
    fresh.sort(key=_sort_key)
    return fresh[:n]
