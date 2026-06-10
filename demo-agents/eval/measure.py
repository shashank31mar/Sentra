#!/usr/bin/env python3
"""Measure how well the Sentra security controller detects prompt injection (efficiency + accuracy).

Runs a **labeled** dataset (``labeled_prompts.jsonl`` from fetch_dataset.py) through the live
``/v1/validate`` and compares Sentra's ALLOW/DENY to ground truth, producing a confusion matrix and
the standard metrics. This is the concrete answer to "how well is the controller working?".

Treating injection as the positive class:
  * TP = injection prompt -> DENY     (caught)
  * FN = injection prompt -> ALLOW    (missed — a false negative, the dangerous one)
  * FP = benign prompt    -> DENY     (over-block — annoys users)
  * TN = benign prompt    -> ALLOW    (correctly allowed)

Reports precision, recall, F1, **F2** (recall-weighted — for a security gate, a miss (FN) usually
costs more than an over-block (FP), so F-beta with beta>1 is often more honest than F1), accuracy,
and latency p50/p95 (the efficiency side).

    SENTRA_API_BASE=… SENTRA_API_KEY=… python demo-agents/eval/measure.py --limit 120
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
AGENT = os.environ.get("EVAL_AGENT_ID", "acme-payments-agent")


def validate(api: str, key: str, text: str) -> tuple[str, float]:
    body = json.dumps({
        "request_id": f"eval-{uuid.uuid4().hex[:8]}", "session_id": f"eval-{uuid.uuid4().hex[:10]}",
        "agent_id": AGENT, "tool_name": "get_transactions", "tool_params": {"account_id": "acct-1000"},
        "user_input": text, "timestamp": datetime.now(timezone.utc).isoformat(), "operation_type": "READ",
    }).encode()
    req = urllib.request.Request(api, data=body, method="POST",
                                 headers={"Content-Type": "application/json", "x-api-key": key})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.load(r)
        return d.get("decision", "?"), (time.time() - t0) * 1000
    except urllib.error.HTTPError as e:
        return ("DENY" if e.code == 403 else "ERROR"), (time.time() - t0) * 1000


def fbeta(precision: float, recall: float, beta: float) -> float:
    b2 = beta * beta
    denom = b2 * precision + recall
    return (1 + b2) * precision * recall / denom if denom else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="cap rows (0 = all)")
    ap.add_argument("--data", default=str(HERE / "labeled_prompts.jsonl"))
    args = ap.parse_args()
    api = os.environ["SENTRA_API_BASE"].rstrip("/") + "/v1/validate"
    key = os.environ["SENTRA_API_KEY"]

    rows = [json.loads(x) for x in pathlib.Path(args.data).read_text().splitlines() if x.strip()]
    if args.limit:
        # balanced-ish sample: interleave so a small --limit still has both classes
        rows = sorted(rows, key=lambda r: r["label"])
        inj = [r for r in rows if r["label"] == 1][: args.limit // 2]
        ben = [r for r in rows if r["label"] == 0][: args.limit - len(inj)]
        rows = inj + ben

    tp = fp = fn = tn = err = 0
    lat: list[float] = []
    for r in rows:
        dec, ms = validate(api, key, r["text"])
        lat.append(ms)
        if dec == "ERROR":
            err += 1
            continue
        deny, inj = dec == "DENY", r["label"] == 1
        tp += inj and deny
        fn += inj and not deny
        fp += (not inj) and deny
        tn += (not inj) and not deny

    n = tp + fp + fn + tn
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = fbeta(precision, recall, 1.0)
    f2 = fbeta(precision, recall, 2.0)
    accuracy = (tp + tn) / n if n else 0.0
    lat.sort()
    p = lambda q: lat[min(int(len(lat) * q), len(lat) - 1)] if lat else 0.0

    print(f"\n=== Sentra detection on {DATASET_LABEL} (n={n}, errors={err}) ===")
    print(f"  confusion: TP={tp}  FP={fp}  FN={fn}  TN={tn}")
    print(f"  precision = {precision:.3f}   (of blocked, how many were real attacks)")
    print(f"  recall    = {recall:.3f}   (of real attacks, how many we caught)")
    print(f"  F1        = {f1:.3f}")
    print(f"  F2        = {f2:.3f}   (recall-weighted — better for a security gate)")
    print(f"  accuracy  = {accuracy:.3f}")
    print(f"  latency   = p50 {p(0.5):.0f}ms  p95 {p(0.95):.0f}ms")
    return 0


DATASET_LABEL = "deepset/prompt-injections"

if __name__ == "__main__":
    raise SystemExit(main())
