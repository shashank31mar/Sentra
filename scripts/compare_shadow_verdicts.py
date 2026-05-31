#!/usr/bin/env python3
"""Compare shadow-mode ML verdicts vs. the live combined verdict — WS19 M3
Task 3.3 / LLD 19 §11.1 Phase 2.

While shadow mode is on (ML_CLASSIFIER_SHADOW_MODE=true), the ML signal is
written to the signal store but does NOT influence the customer-facing
verdict. This script reads the signal store for the last N days and reports:

  - ML-DENY count where the live verdict was ALLOW (potential incremental catches)
  - ML-ALLOW count where the live verdict was DENY (potential ML misses)
  - Sigma-and-ML agreement rate
  - Novel-input count: requests where ML emitted a verdict AND no sigma rule
    fired (drives the M3 exit gate — need ≥50 to call shadow mode adequate
    per workstream-19 Task 3.2 v0.2)

Output: human-readable summary + JSON with per-disagreement detail for
manual review.

Usage:
    python scripts/compare_shadow_verdicts.py --days 7 --out /tmp/shadow-report.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Iterator

import boto3
from boto3.dynamodb.conditions import Key

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("compare_shadow_verdicts")


SIGNALS_TABLE_DEFAULT = "sentra-validation-signals"
GSI_NAME = "decision-date-timestamp-index"


def _iter_signals(table, target_date_iso: str) -> Iterator[dict]:
    last_eval_key = None
    while True:
        kwargs = {
            "IndexName": GSI_NAME,
            "KeyConditionExpression": Key("decision_date").eq(target_date_iso),
        }
        if last_eval_key:
            kwargs["ExclusiveStartKey"] = last_eval_key
        resp = table.query(**kwargs)
        for item in resp.get("Items", []):
            yield item
        last_eval_key = resp.get("LastEvaluatedKey")
        if not last_eval_key:
            break


def _group_by_request(items: list[dict]) -> dict[str, list[dict]]:
    by_rid: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        rid = it.get("request_id")
        if rid:
            by_rid[rid].append(it)
    return by_rid


def _combined_verdict(signals: list[dict]) -> str:
    """Live verdict per deny-overrides, EXCLUDING ML (since in shadow mode ML
    is not allowed to influence the verdict — that's the whole point)."""
    for s in signals:
        if s.get("source") == "sentra.ml_classifier":
            continue
        if s.get("decision") == "DENY":
            return "DENY"
    return "ALLOW"


def _has_sigma_hit(signals: list[dict]) -> bool:
    for s in signals:
        if s.get("source") == "sentra.sigma" and s.get("decision") == "DENY":
            return True
    return False


def _ml_signal(signals: list[dict]) -> dict | None:
    for s in signals:
        if s.get("source") == "sentra.ml_classifier":
            return s
    return None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--table", default=os.environ.get("VALIDATION_SIGNALS_TABLE", SIGNALS_TABLE_DEFAULT))
    p.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    p.add_argument("--out", default="/tmp/shadow-report.json")
    p.add_argument("--top-disagreements", type=int, default=20,
                   help="how many disagreement examples to include in the report for manual review")
    args = p.parse_args()

    dynamodb = boto3.resource("dynamodb", region_name=args.region)
    table = dynamodb.Table(args.table)
    today = datetime.now(timezone.utc).date()

    all_items: list[dict] = []
    for offset in range(args.days):
        date_iso = (today - timedelta(days=offset)).isoformat()
        items = list(_iter_signals(table, date_iso))
        log.info("date %s — %d signal rows", date_iso, len(items))
        all_items.extend(items)

    by_request = _group_by_request(all_items)
    log.info("examined %d requests across %d signal rows", len(by_request), len(all_items))

    counts = {
        "total_requests": 0,
        "ml_emitted_signal": 0,
        "ml_abstained_or_missing": 0,
        "ml_deny_combined_allow": 0,  # potential incremental ML catches
        "ml_allow_combined_deny": 0,  # potential ML misses
        "ml_and_sigma_both_deny": 0,
        "ml_deny_no_sigma_hit": 0,    # novel coverage (the M3 exit-gate metric)
        "ml_allow_no_sigma_hit_no_other_deny": 0,
    }
    disagreements_ml_caught_extra: list[dict] = []
    disagreements_ml_missed: list[dict] = []

    for rid, signals in by_request.items():
        counts["total_requests"] += 1
        ml = _ml_signal(signals)
        if ml is None:
            counts["ml_abstained_or_missing"] += 1
            continue
        counts["ml_emitted_signal"] += 1

        combined = _combined_verdict(signals)
        ml_decision = ml.get("decision")
        sigma_hit = _has_sigma_hit(signals)

        if ml_decision == "DENY" and not sigma_hit:
            counts["ml_deny_no_sigma_hit"] += 1
        if ml_decision == "ALLOW" and combined == "ALLOW" and not sigma_hit:
            counts["ml_allow_no_sigma_hit_no_other_deny"] += 1
        if ml_decision == "DENY" and sigma_hit:
            counts["ml_and_sigma_both_deny"] += 1
        if ml_decision == "DENY" and combined == "ALLOW":
            counts["ml_deny_combined_allow"] += 1
            if len(disagreements_ml_caught_extra) < args.top_disagreements:
                disagreements_ml_caught_extra.append({
                    "request_id": rid,
                    "ml_reason": ml.get("reason"),
                    "ml_threat_type": ml.get("threat_type"),
                    "ml_confidence": ml.get("confidence"),
                    "other_sources": [s.get("source") for s in signals if s.get("source") != "sentra.ml_classifier"],
                })
        if ml_decision == "ALLOW" and combined == "DENY":
            counts["ml_allow_combined_deny"] += 1
            if len(disagreements_ml_missed) < args.top_disagreements:
                disagreements_ml_missed.append({
                    "request_id": rid,
                    "ml_reason": ml.get("reason"),
                    "ml_confidence": ml.get("confidence"),
                    "denying_sources": [
                        {"source": s.get("source"), "reason": s.get("reason"), "threat_type": s.get("threat_type")}
                        for s in signals if s.get("decision") == "DENY" and s.get("source") != "sentra.ml_classifier"
                    ],
                })

    report = {
        "window_days": args.days,
        "as_of_utc": today.isoformat(),
        "counts": counts,
        "m3_exit_gate": {
            "novel_inputs_required": 50,
            "novel_inputs_observed": counts["ml_deny_no_sigma_hit"] + counts["ml_allow_no_sigma_hit_no_other_deny"],
            "passes": (counts["ml_deny_no_sigma_hit"] + counts["ml_allow_no_sigma_hit_no_other_deny"]) >= 50,
        },
        "disagreements_ml_caught_extra": disagreements_ml_caught_extra,
        "disagreements_ml_missed": disagreements_ml_missed,
    }

    with open(args.out, "w") as f:
        json.dump(report, f, indent=2, default=str)
    log.info("wrote shadow report to %s", args.out)

    # Human summary
    print()
    print(f"Shadow-mode comparison (last {args.days} days, as of {today.isoformat()})")
    print("=" * 70)
    print(f"  total requests:                 {counts['total_requests']}")
    print(f"  ML emitted a signal:            {counts['ml_emitted_signal']}")
    print(f"  ML abstained / missing:         {counts['ml_abstained_or_missing']}")
    print(f"  ML+sigma both DENY:             {counts['ml_and_sigma_both_deny']}")
    print(f"  ML caught extra (DENY/ALLOW):   {counts['ml_deny_combined_allow']}   ← incremental value")
    print(f"  ML missed (ALLOW/DENY):         {counts['ml_allow_combined_deny']}")
    print(f"  ML novel coverage (no sigma):   {counts['ml_deny_no_sigma_hit']}")
    print()
    print(f"M3 exit gate: novel inputs observed = "
          f"{report['m3_exit_gate']['novel_inputs_observed']} / {report['m3_exit_gate']['novel_inputs_required']} required")
    print(f"  → shadow mode adequate to exit: {report['m3_exit_gate']['passes']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
