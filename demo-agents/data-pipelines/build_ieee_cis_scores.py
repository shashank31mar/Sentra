#!/usr/bin/env python3
"""Derive a compact fraud-score snapshot from the IEEE-CIS Fraud Detection dataset.

Input : Kaggle competition file ``train_transaction.csv`` (590k rows, anonymized features + the
        real ``isFraud`` label). Download once (rules-acceptance required):
            kaggle competitions download -c ieee-fraud-detection -f train_transaction.csv
        or via the API token in ~/.kaggle/access_token (see README).
Output: demo-agents/common/data/ieee_cis_scores.json — one record per *sampled* row:
        {"fraud_score", "risk", "is_fraud"}

``fraud_score`` is the **empirical fraud rate** of the transaction's real cohort
(ProductCD x card-network x card-type x amount-bucket), computed over the whole 590k-row dataset —
i.e. the observed probability that a transaction *like this one* is fraud. No model is shipped;
the derivation is a two-pass stdlib ``csv`` job, fully reproducible. The identity tool maps an
account/txn key -> one of these rows (see common/realdata.py), so its fraud score is grounded in the
real IEEE-CIS distribution instead of a synthetic hash.

    python data-pipelines/build_ieee_cis_scores.py --csv /tmp/ieee_cis/train_transaction.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
from collections import defaultdict
from typing import Dict, List

OUT = pathlib.Path(__file__).resolve().parents[1] / "common" / "data" / "ieee_cis_scores.json"


def _amt_bucket(amt: str) -> int:
    """Log-scale amount bucket (real TransactionAmt) — stable, handles the long tail."""
    try:
        v = float(amt)
    except (TypeError, ValueError):
        return -1
    return int(math.log10(v + 1) * 2)  # ~0..8 over $0..$30k


def _cohort(row: Dict[str, str]) -> tuple:
    return (
        row.get("ProductCD", "") or "?",
        row.get("card4", "") or "?",   # visa / mastercard / amex / discover
        row.get("card6", "") or "?",   # debit / credit
        _amt_bucket(row.get("TransactionAmt", "")),
    )


def _band(p: float) -> str:
    return "high" if p >= 0.10 else "med" if p >= 0.03 else "low"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="path to IEEE-CIS train_transaction.csv")
    ap.add_argument("--sample", type=int, default=5000, help="rows to emit (systematic sample)")
    args = ap.parse_args()

    csv_path = pathlib.Path(args.csv)

    # Pass 1: empirical fraud rate per real cohort over the entire dataset.
    cohort_tot: Dict[tuple, int] = defaultdict(int)
    cohort_fraud: Dict[tuple, int] = defaultdict(int)
    total = 0
    with csv_path.open(newline="") as f:
        for row in csv.DictReader(f):
            k = _cohort(row)
            cohort_tot[k] += 1
            cohort_fraud[k] += row["isFraud"] == "1"
            total += 1
    base_rate = sum(cohort_fraud.values()) / max(total, 1)

    # Pass 2: systematic sample -> emit one record per sampled row with its cohort's fraud probability.
    step = max(total // args.sample, 1)
    out: List[Dict] = []
    with csv_path.open(newline="") as f:
        for i, row in enumerate(csv.DictReader(f)):
            if i % step:
                continue
            k = _cohort(row)
            n = cohort_tot[k]
            # smooth small cohorts toward the global base rate so a sparse cohort isn't a hard 0/1.
            score = (cohort_fraud[k] + base_rate * 20) / (n + 20)
            out.append(
                {
                    "fraud_score": round(score, 4),
                    "risk": _band(score),
                    "is_fraud": 1 if row["isFraud"] == "1" else 0,
                }
            )
            if len(out) >= args.sample:
                break

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    frauds = sum(r["is_fraud"] for r in out)
    print(f"wrote {len(out)} fraud-score rows -> {OUT}")
    print(f"  scanned={total}  cohorts={len(cohort_tot)}  base_fraud={base_rate:.4f}")
    print(f"  sampled is_fraud={frauds} ({frauds/len(out):.2%})")
    print(f"  bands: " + ", ".join(f"{b}={sum(r['risk']==b for r in out)}" for b in ("low", "med", "high")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
