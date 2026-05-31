#!/usr/bin/env python3
"""Extract a labeled eval dataset for the ML threat classifier from the
validation signal store — WS19 Task 2.1 / LLD 19 §10.2.

Labels are inferred from existing signals (per LLD 19 §10.2):
  - sigma DENY with a threat_type        → positive (label = that threat_type)
  - trusted-agent ALLOW with no sigma hit → negative (label = NONE)
  - policy UNAUTHORIZED_TOOL DENY        → OUT OF DISTRIBUTION (excluded)
  - any ALLOW that had a sigma hit       → ambiguous (excluded; needs manual label)

Output: JSONL on local disk and (optionally) S3 at
`s3://<eval-bucket>/ml-classifier/dataset-v1-YYYYMMDD.jsonl`.

Held-out split: 20% by session_id (NOT by row — same-session leakage would
inflate apparent precision).

Usage:
    python scripts/extract_ml_eval_dataset.py \\
        --days 90 \\
        --bucket sentra-eval \\
        --local-out /tmp/ml-eval-dataset.jsonl

Dry-run (no S3 upload, just print stats):
    python scripts/extract_ml_eval_dataset.py --dry-run --days 30

Reads from DDB table `sentra-validation-signals` (LLD 17 §5.1) — uses the
decision-date-timestamp-index GSI for date-range scans. Requires read access
to the table; the controller task role + dashboard task role both already
have it (compute_stack.py).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import random
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterator, Optional

import boto3
from boto3.dynamodb.conditions import Key

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("extract_ml_eval_dataset")


SIGNALS_TABLE_DEFAULT = "sentra-validation-signals"
GSI_NAME = "decision-date-timestamp-index"

# Threat types we treat as positives. Aligned with LLD 19 §7.1's enum.
POSITIVE_THREAT_TYPES = {
    "PROMPT_INJECTION",
    "PII_EXPOSURE",
    "DATA_THEFT",
    "PRIVILEGE_ESCALATION",
    "JAILBREAK_ATTEMPT",
    "SYSTEM_EXTRACTION",
    "OTHER",
}

# Policy violation types that are out-of-distribution for a threat classifier
# (LLD 19 §10.2). Threat classification is "is this a threat?" — policy
# enforcement is "is this authorized?" — different tasks, different labels.
EXCLUDED_VIOLATION_TYPES = {
    "UNAUTHORIZED_TOOL",
    "MISSING_REQUIRED_FIELD",
    "RATE_LIMIT_EXCEEDED",
    "LOW_TRUST",
}


@dataclass
class LabeledExample:
    request_id: str
    session_id: str
    agent_id: str
    tool_name: str
    tool_params: dict
    user_input: str
    label_decision: str       # "ALLOW" | "DENY"
    label_threat_type: str    # NONE | one of POSITIVE_THREAT_TYPES
    source_signal: str        # which signal we inferred the label from
    timestamp_iso: str

    def to_dict(self) -> dict:
        return self.__dict__


def _iter_signals_by_date(table, target_date_iso: str) -> Iterator[dict]:
    """Yield every signal row for the given UTC YYYY-MM-DD via GSI 2."""
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


def _signals_for_request(items: list[dict]) -> dict[str, list[dict]]:
    """Group signal rows by request_id so we can reason about the per-request
    combined verdict + which validators fired."""
    by_request: dict[str, list[dict]] = {}
    for it in items:
        rid = it.get("request_id")
        if rid:
            by_request.setdefault(rid, []).append(it)
    return by_request


def _label_from_signals(signals: list[dict]) -> Optional[tuple[str, str, str]]:
    """Apply LLD 19 §10.2 labeling rules to a request's signals.

    Returns (decision, threat_type, source_signal) or None to skip the row.
    Callers can use _label_skip_reason() on a None return to attribute the skip.
    """
    sigma = next((s for s in signals if s.get("source") == "sentra.sigma"), None)
    policy = next((s for s in signals if s.get("source") == "sentra.policy"), None)

    # Rule 1: sigma DENY with a known threat_type → positive
    if sigma and sigma.get("decision") == "DENY":
        tt = sigma.get("threat_type") or ""
        if tt in POSITIVE_THREAT_TYPES:
            return ("DENY", tt, "sentra.sigma")
        return None  # sigma_deny_unknown_threat_type

    # Rule 2: policy-engine DENY → exclude (authorization ≠ threat)
    if policy and policy.get("decision") == "DENY":
        return None  # policy_deny_ood

    # Rule 3: ALL-ALLOW + no sigma hit → negative
    all_allow = all(s.get("decision") == "ALLOW" for s in signals if s.get("decision") in ("ALLOW", "DENY"))
    sigma_clean = sigma is None or (sigma.get("decision") == "ALLOW" and not sigma.get("threat_type"))
    if all_allow and sigma_clean:
        return ("ALLOW", "NONE", "all_allow_no_sigma")

    # Rule 4: ALLOW combined but sigma did hit — ambiguous, manual label needed
    return None  # ambiguous_allow_with_sigma_hit


def _label_skip_reason(signals: list[dict]) -> str:
    """Mirror of _label_from_signals's None-return branches, exposed for
    operator visibility in the skip-reason counter."""
    sigma = next((s for s in signals if s.get("source") == "sentra.sigma"), None)
    policy = next((s for s in signals if s.get("source") == "sentra.policy"), None)
    if sigma and sigma.get("decision") == "DENY":
        tt = sigma.get("threat_type") or ""
        if tt not in POSITIVE_THREAT_TYPES:
            return f"sigma_deny_unknown_threat_type:{tt or 'EMPTY'}"
    if policy and policy.get("decision") == "DENY":
        viol = (policy.get("metadata") or {}).get("violation_type", "") or "UNKNOWN"
        return f"policy_deny_ood:{viol}"
    # Fallthrough: ALLOW-combined but sigma hit, OR something else unaccounted for
    if sigma and sigma.get("decision") == "ALLOW" and sigma.get("threat_type"):
        return "ambiguous_allow_with_sigma_hit"
    return "other"


def _example_from_signals(signals: list[dict]) -> Optional[LabeledExample]:
    label = _label_from_signals(signals)
    if label is None:
        return None
    decision, threat_type, source_signal = label
    # Pull request fields from any signal — audit_logger.py flattens these as
    # top-level shared_attrs on each signal row (NOT nested under a
    # `request_payload` key; an earlier draft of this script assumed otherwise
    # and silently produced empty datasets). Note: user_input is truncated to
    # 200 chars by the audit logger — acceptable for eval, but worth knowing
    # when comparing eval-time predictions against production live behavior.
    first = signals[0]
    return LabeledExample(
        request_id=first.get("request_id", ""),
        session_id=first.get("session_id", ""),
        agent_id=first.get("agent_id", ""),
        tool_name=first.get("tool_name") or "",
        tool_params=first.get("tool_params") or {},
        user_input=first.get("user_input") or "",
        label_decision=decision,
        label_threat_type=threat_type,
        source_signal=source_signal,
        timestamp_iso=first.get("timestamp_iso", ""),
    )


def _holdout_split(examples: list[LabeledExample], holdout_pct: int, seed: int = 17) -> tuple[list, list]:
    """Split by session_id, not by row — same-session leakage would inflate
    precision under cross-validation. Deterministic via the seeded hash."""
    rng = random.Random(seed)
    sessions = sorted({e.session_id for e in examples if e.session_id})
    rng.shuffle(sessions)
    holdout_count = max(1, len(sessions) * holdout_pct // 100)
    holdout_sessions = set(sessions[:holdout_count])
    train = [e for e in examples if e.session_id not in holdout_sessions]
    holdout = [e for e in examples if e.session_id in holdout_sessions]
    return train, holdout


def _write_jsonl(path: str, examples: list[LabeledExample], split_name: str) -> None:
    with open(path, "w") as f:
        for ex in examples:
            row = ex.to_dict()
            row["split"] = split_name
            f.write(json.dumps(row, default=str) + "\n")
    log.info("wrote %d rows to %s", len(examples), path)


def _upload_to_s3(local_path: str, bucket: str, key: str, dry_run: bool) -> None:
    if dry_run:
        log.info("[dry-run] would upload %s to s3://%s/%s", local_path, bucket, key)
        return
    s3 = boto3.client("s3")
    s3.upload_file(local_path, bucket, key)
    log.info("uploaded to s3://%s/%s", bucket, key)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--days", type=int, default=90, help="how many days back to scan")
    p.add_argument("--table", default=os.environ.get("VALIDATION_SIGNALS_TABLE", SIGNALS_TABLE_DEFAULT))
    p.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    p.add_argument("--bucket", default="sentra-eval", help="S3 bucket for dataset upload")
    p.add_argument("--local-out", default="/tmp/ml-eval-dataset.jsonl")
    p.add_argument("--holdout-pct", type=int, default=20)
    p.add_argument("--dry-run", action="store_true", help="skip S3 upload; print stats only")
    args = p.parse_args()

    dynamodb = boto3.resource("dynamodb", region_name=args.region)
    table = dynamodb.Table(args.table)

    today = datetime.now(timezone.utc).date()
    all_items: list[dict] = []
    for offset in range(args.days):
        date_iso = (today - timedelta(days=offset)).isoformat()
        try:
            day_items = list(_iter_signals_by_date(table, date_iso))
            log.info("date %s — %d signal rows", date_iso, len(day_items))
            all_items.extend(day_items)
        except Exception as exc:
            log.warning("failed to scan %s: %s", date_iso, exc)

    by_request = _signals_for_request(all_items)
    log.info("grouped into %d requests from %d signal rows", len(by_request), len(all_items))

    examples: list[LabeledExample] = []
    skip_reasons: Counter = Counter()
    for rid, sigs in by_request.items():
        ex = _example_from_signals(sigs)
        if ex is None:
            skip_reasons[_label_skip_reason(sigs)] += 1
            continue
        if not ex.user_input and not ex.tool_params:
            skip_reasons["empty_payload"] += 1
            continue
        examples.append(ex)

    log.info("labeled %d examples; skipped %s", len(examples), dict(skip_reasons))
    if not examples:
        log.error("no labelable examples found — nothing to write. Common causes: (a) no qualifying signals in the scan window (try --days 90); (b) signal rows missing tool_name / user_input top-level fields — confirm audit_logger.py:_shared_attrs_from_request is still flattening them; (c) only policy/trust DENYs in the window (those are excluded as out-of-distribution per LLD 19 §10.2).")
        return 1

    label_dist = Counter(f"{e.label_decision}/{e.label_threat_type}" for e in examples)
    session_count = len({e.session_id for e in examples})
    log.info("label distribution: %s", dict(label_dist))
    log.info("distinct sessions: %d", session_count)

    train, holdout = _holdout_split(examples, args.holdout_pct)
    log.info("split: %d train / %d holdout", len(train), len(holdout))

    # Versioned filename so future eval runs reuse the same dataset
    # (apples-to-apples comparison across prompt/model changes).
    stamp = today.strftime("%Y%m%d")
    train_path = args.local_out
    holdout_path = args.local_out.replace(".jsonl", ".holdout.jsonl")
    _write_jsonl(train_path, train, "train")
    _write_jsonl(holdout_path, holdout, "holdout")

    dataset_hash = hashlib.sha256()
    for p_ in (train_path, holdout_path):
        with open(p_, "rb") as f:
            dataset_hash.update(f.read())
    digest = dataset_hash.hexdigest()[:12]
    log.info("dataset hash (train+holdout): %s", digest)

    if args.bucket and not args.dry_run:
        _upload_to_s3(train_path, args.bucket, f"ml-classifier/dataset-v1-{stamp}-{digest}.train.jsonl", args.dry_run)
        _upload_to_s3(holdout_path, args.bucket, f"ml-classifier/dataset-v1-{stamp}-{digest}.holdout.jsonl", args.dry_run)
    else:
        log.info("[dry-run or no bucket] skipping S3 upload")

    return 0


if __name__ == "__main__":
    sys.exit(main())
