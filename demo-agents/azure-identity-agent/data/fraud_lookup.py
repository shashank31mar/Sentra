#!/usr/bin/env python3
"""Fraud scoring for the identity agent (LLD 22 §8.3).

A deterministic stand-in for an IEEE-CIS-trained model: stable score in [0,1] + risk band, keyed by
``account_id`` or ``txn_id``. Deterministic so demo decisions are reproducible across runs/clouds.
The scoring function lives in ``common/store.py`` (so the in-memory and DDB paths share it); this
module exposes it for the identity tools and a small CLI for spot checks / CSV enrichment.

    python azure-identity-agent/data/fraud_lookup.py acct-1007 txn-0042
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # demo-agents/
from common.store import check_fraud_score, fraud_score  # noqa: E402,F401  (re-export)


def main() -> int:
    keys = sys.argv[1:] or ["acct-1000", "txn-001"]
    for k in keys:
        print(k, "->", fraud_score(k))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
