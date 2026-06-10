#!/usr/bin/env python3
"""Derive a compact subscriber snapshot from the IBM Telco Customer Churn dataset.

Input : the public IBM Telco churn CSV (no auth, no PII — synthetic IBM sample data).
        Default source: https://raw.githubusercontent.com/IBM/telco-customer-churn-on-icp4d/master/data/Telco-Customer-Churn.csv
Output: demo-agents/common/data/telco_subscribers.json — one record per real row:
        {"plan", "tenure_months", "monthly_charges", "churn_risk", "churn_band", "churned"}

``churn_risk`` is the **empirical churn rate** of the subscriber's real cohort
(Contract x InternetService x tenure-year-bucket), computed over the whole dataset — i.e. the
observed probability that a subscriber *like this one* churns. No model, stdlib-only, reproducible.
The telecom tool maps a msisdn -> one of these rows (see common/realdata.py), so its plan / tenure /
charges / churn risk come from real data instead of a synthetic hash.

    python data-pipelines/build_telco_subscribers.py            # fetch from the public mirror
    python data-pipelines/build_telco_subscribers.py --csv /tmp/telco.csv
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import pathlib
import urllib.request
from collections import defaultdict
from typing import Dict, List

PUBLIC_CSV = (
    "https://raw.githubusercontent.com/IBM/telco-customer-churn-on-icp4d/master/"
    "data/Telco-Customer-Churn.csv"
)
OUT = pathlib.Path(__file__).resolve().parents[1] / "common" / "data" / "telco_subscribers.json"


def _plan(row: Dict[str, str]) -> str:
    """Map real (InternetService, Contract, Partner/Dependents) to a demo plan name."""
    net = row["InternetService"]
    contract = row["Contract"]
    family = row["Partner"] == "Yes" or row["Dependents"] == "Yes"
    if net == "Fiber optic":
        return "fiber-1gbps"
    if net == "No":
        return "prepaid-basic"
    # DSL
    if family and contract != "Month-to-month":
        return "family-share"
    return "postpaid-plus" if contract == "Two year" else "postpaid-standard"


def _band(p: float) -> str:
    return "high" if p >= 0.45 else "med" if p >= 0.2 else "low"


def _load_rows(csv_path: str | None) -> List[Dict[str, str]]:
    if csv_path:
        text = pathlib.Path(csv_path).read_text()
    else:
        with urllib.request.urlopen(PUBLIC_CSV, timeout=60) as r:
            text = r.read().decode("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="local Telco CSV (default: fetch public IBM mirror)")
    ap.add_argument("--limit", type=int, default=0, help="cap rows (0 = all)")
    args = ap.parse_args()

    rows = _load_rows(args.csv)

    # Pass 1: empirical churn rate per real cohort (Contract x InternetService x tenure-year bucket).
    cohort_tot: Dict[tuple, int] = defaultdict(int)
    cohort_churn: Dict[tuple, int] = defaultdict(int)

    def cohort_key(row: Dict[str, str]) -> tuple:
        return (row["Contract"], row["InternetService"], min(int(row["tenure"]), 72) // 12)

    for row in rows:
        k = cohort_key(row)
        cohort_tot[k] += 1
        cohort_churn[k] += row["Churn"] == "Yes"

    base_rate = sum(cohort_churn.values()) / max(sum(cohort_tot.values()), 1)

    # Pass 2: emit one record per row using its cohort's observed churn probability.
    out: List[Dict] = []
    for row in rows:
        k = cohort_key(row)
        n = cohort_tot[k]
        # smooth tiny cohorts toward the global base rate (Laplace-ish) so a 1-row cohort
        # isn't a hard 0/1.
        risk = (cohort_churn[k] + base_rate * 5) / (n + 5)
        try:
            charges = round(float(row["MonthlyCharges"]), 2)
        except ValueError:
            charges = 0.0
        out.append(
            {
                "plan": _plan(row),
                "tenure_months": min(int(row["tenure"]), 72),
                "monthly_charges": charges,
                "churn_risk": round(risk, 3),
                "churn_band": _band(risk),
                "churned": row["Churn"] == "Yes",
            }
        )
        if args.limit and len(out) >= args.limit:
            break

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    churned = sum(r["churned"] for r in out)
    print(f"wrote {len(out)} subscriber rows -> {OUT}")
    print(f"  cohorts={len(cohort_tot)}  base_churn={base_rate:.3f}  churned={churned} ({churned/len(out):.1%})")
    print(f"  bands: " + ", ".join(f"{b}={sum(r['churn_band']==b for r in out)}" for b in ("low", "med", "high")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
