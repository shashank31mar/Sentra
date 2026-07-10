#!/usr/bin/env python3
"""Step 1 — extract the distillation TEACHER corpus from the validation signal store.

The teacher is the live Haiku/Sonnet ML classifier. Every /v1/validate call that
reached the ML node wrote a `sentra.ml_classifier` Signal row to
`sentra-validation-signals-v2` carrying the INPUT (tool_name, user_input,
tool_params, operation_type) and the teacher's LABEL (decision + confidence). We
distill THOSE (input -> label) pairs into the small local student.

We keep ONLY rows the teacher actually voted on:
  * decision in {ALLOW, DENY}                 (a concrete verdict — the label)
  * confidence present                        (the soft signal)
Abstains carry no label (decision null) and are dropped — the student cannot learn
from "the teacher declined to vote".

Output: data/teacher_raw.jsonl — one {tool_name, user_input, tool_params,
operation_type, decision, confidence, agent_id, ts} per line.

Parallel Segment scan (TOTAL_SEGMENTS workers) so 2.97M rows is minutes, not hours.
Read-only; uses the `sentra` profile.
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

import boto3
from boto3.dynamodb.conditions import Attr


def _json_default(o):
    """DynamoDB numbers deserialize to Decimal — make them JSON-safe."""
    if isinstance(o, Decimal):
        # int if whole, else float (confidence like 0.96 → float)
        return int(o) if o % 1 == 0 else float(o)
    raise TypeError(f"not serializable: {type(o)}")

TABLE = "sentra-validation-signals-v2"
ML_SOURCE = "sentra.ml_classifier"
TOTAL_SEGMENTS = 16
OUT = Path(__file__).resolve().parent.parent / "data" / "teacher_raw.jsonl"

# Cap for a first run so we don't pull all 2.97M rows before we've sanity-checked
# the pipeline. Override with EXTRACT_MAX=0 for the full pull.
MAX_ROWS = int(os.environ.get("EXTRACT_MAX", "200000"))


def _scan_segment(segment: int) -> list[dict]:
    """Scan one parallel segment, projecting only the fields we distill from."""
    ddb = boto3.session.Session(
        profile_name=os.environ.get("AWS_PROFILE", "sentra"),
        region_name="us-east-1",
    ).resource("dynamodb")
    table = ddb.Table(TABLE)
    rows: list[dict] = []
    kwargs = dict(
        Segment=segment,
        TotalSegments=TOTAL_SEGMENTS,
        # Only ml_classifier rows with a concrete decision (label) present.
        FilterExpression=Attr("source").eq(ML_SOURCE) & Attr("decision").exists(),
        ProjectionExpression="tool_name, user_input, tool_params, operation_type, "
        "decision, confidence, agent_id, timestamp_ms",
    )
    start_key = None
    while True:
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key
        resp = table.scan(**kwargs)
        for it in resp.get("Items", []):
            dec = it.get("decision")
            if dec not in ("ALLOW", "DENY"):
                continue  # abstain / malformed → no label
            rows.append(
                {
                    "tool_name": it.get("tool_name", ""),
                    "user_input": it.get("user_input", ""),
                    "tool_params": it.get("tool_params", {}),
                    "operation_type": it.get("operation_type", ""),
                    "decision": dec,
                    "confidence": float(it["confidence"]) if it.get("confidence") is not None else None,
                    "agent_id": it.get("agent_id", ""),
                    "ts": int(it["timestamp_ms"]) if it.get("timestamp_ms") else None,
                }
            )
        start_key = resp.get("LastEvaluatedKey")
        if not start_key or (MAX_ROWS and len(rows) >= MAX_ROWS // TOTAL_SEGMENTS):
            break
    return rows


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    print(f"scanning {TABLE} for {ML_SOURCE} rows across {TOTAL_SEGMENTS} segments "
          f"(cap ~{MAX_ROWS or 'ALL'})...", file=sys.stderr)
    total = 0
    with OUT.open("w") as f, concurrent.futures.ThreadPoolExecutor(TOTAL_SEGMENTS) as ex:
        for rows in ex.map(_scan_segment, range(TOTAL_SEGMENTS)):
            for r in rows:
                f.write(json.dumps(r, default=_json_default) + "\n")
            total += len(rows)
            print(f"  segment done (+{len(rows)}, total {total})", file=sys.stderr)
    # Quick label distribution so we SEE the imbalance we have to fix downstream.
    allow = deny = 0
    for line in OUT.open():
        d = json.loads(line)
        allow += d["decision"] == "ALLOW"
        deny += d["decision"] == "DENY"
    print(f"\nDONE: {total} teacher rows -> {OUT}", file=sys.stderr)
    print(f"  ALLOW={allow}  DENY={deny}  deny_frac={deny/max(total,1):.4f}", file=sys.stderr)
    if total:
        print(f"  (class imbalance is expected — fixed in step 2 by augmenting attacks)",
              file=sys.stderr)


if __name__ == "__main__":
    main()
