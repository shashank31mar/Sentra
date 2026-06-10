"""Real open-dataset lookups for the demo tools (IEEE-CIS fraud, IBM Telco churn).

Offline pipelines in ``data-pipelines/`` derive compact JSON snapshots committed under
``common/data/``. At runtime a tool maps a stable key (account/txn id, msisdn) into the snapshot by
hashing — so a given key always resolves to the same real-data-derived row (decisions stay
reproducible across runs and clouds) while the *values* come from the real dataset's distribution
rather than a synthetic hash.

stdlib-only (``json`` + ``hashlib``) so the Azure Function packages stay build-free (no Oryx). If a
snapshot file is absent (e.g. the pipeline was never run), the lookups return ``None`` and callers
fall back to their previous deterministic behaviour — the demo never hard-fails on missing data.

Snapshot shapes (one row per list element, no PII — only derived scores/cohorts):
  ieee_cis_scores.json : [{"fraud_score": float, "risk": "low|med|high", "is_fraud": 0|1}, ...]
  telco_subscribers.json: [{"plan": str, "tenure_months": int, "monthly_charges": float,
                            "churn_risk": float, "churn_band": "low|med|high", "churned": bool}, ...]
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any, Dict, List, Optional

_DATA_DIR = pathlib.Path(__file__).resolve().parent / "data"
_CACHE: Dict[str, Optional[List[Dict[str, Any]]]] = {}


def _load(name: str) -> Optional[List[Dict[str, Any]]]:
    """Load + cache a snapshot list. Returns None (cached) if the file is missing/empty/invalid."""
    if name in _CACHE:
        return _CACHE[name]
    path = _DATA_DIR / f"{name}.json"
    rows: Optional[List[Dict[str, Any]]] = None
    try:
        if path.is_file():
            data = json.loads(path.read_text())
            if isinstance(data, list) and data:
                rows = data
    except (ValueError, OSError):
        rows = None
    _CACHE[name] = rows
    return rows


def _index(key: str, n: int) -> int:
    """Deterministic [0, n) index from a key — stable across runs/processes/clouds."""
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:12], 16) % n


def fraud_record(key: str) -> Optional[Dict[str, Any]]:
    """Real IEEE-CIS-derived fraud row for a key, or None if the snapshot isn't bundled."""
    rows = _load("ieee_cis_scores")
    if not rows:
        return None
    return rows[_index(key, len(rows))]


def subscriber_record(msisdn: str) -> Optional[Dict[str, Any]]:
    """Real IBM-Telco-derived subscriber row for a msisdn, or None if the snapshot isn't bundled."""
    rows = _load("telco_subscribers")
    if not rows:
        return None
    return rows[_index(msisdn, len(rows))]
