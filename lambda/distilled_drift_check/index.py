"""Distilled fast-ALLOW drift-check — the §14 online distilled-vs-heavy disagreement monitor.

WHY: with fast-ALLOW enabled, a confident distilled ALLOW (>=0.95) SKIPS Haiku, so there
is no live Haiku verdict to compare against on those calls. This scheduled job is the
active re-check: it samples the distilled confident-ALLOW verdicts recorded in the signal
store and RE-RUNS the same inputs through the real Haiku classifier (the strong model).
If Haiku now DENYs a request the distilled model confidently ALLOWed, the models have
DISAGREED — the distilled model may be drifting stale as traffic changes (the SEC-7 risk).

It publishes `DistilledDriftDisagreement` (a rate 0..1) to CloudWatch. A CloudWatch alarm
watches it and, on breach, notifies via SNS → email (same mechanism as the canary). This
job takes NO automated action on prod — a human investigates and decides whether to flip
the DISTILLED_ALLOW_SHORTCIRCUIT_ENABLED kill-switch (founder call: email-only).

No VPC needed: reads DynamoDB (signal store) + calls Bedrock (Haiku) — both AWS APIs. It
does NOT call the distilled sidecar (the stored confidence is the distilled verdict).

Reuses the EXACT controller Haiku prompt + tool schema (vendored ml_classifier_prompts /
ml_classifier_schema) so the re-check verdict is apples-to-apples with production.
"""
from __future__ import annotations

import json
import logging
import os
import time
from decimal import Decimal

import boto3
from botocore.config import Config as BotoConfig

from ml_classifier_prompts import SYSTEM_PROMPT, build_messages
from ml_classifier_schema import TOOL_CHOICE, TOOL_NAME, TOOL_SPEC

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-east-1")
SIGNALS_TABLE = os.environ.get("SIGNALS_TABLE", "sentra-validation-signals-v2")
NAMESPACE = os.environ.get("METRIC_NAMESPACE", "Sentra/SecurityController")
TENANT = os.environ.get("DRIFT_TENANT", "acme")
# Haiku target — the inference-profile ARN if provided (matches the controller's
# workload isolation), else the raw hot model id.
HAIKU_TARGET = (
    os.environ.get("ML_CLASSIFIER_INFERENCE_PROFILE_ARN")
    or os.environ.get("ML_CLASSIFIER_HOT_MODEL_ID", "anthropic.claude-haiku-4-5-20251001-v1:0")
)
# How many recent confident-ALLOW samples to re-check per run, and the confidence
# bar that defines a "fast-ALLOW" (must match distilled_allow_shortcircuit_min_confidence).
SAMPLE_SIZE = int(os.environ.get("DRIFT_SAMPLE_SIZE", "50"))
ALLOW_CONF_BAR = float(os.environ.get("DRIFT_ALLOW_CONF_BAR", "0.95"))
LOOKBACK_MIN = int(os.environ.get("DRIFT_LOOKBACK_MIN", "180"))

_ddb = boto3.resource("dynamodb", region_name=REGION)
_cw = boto3.client("cloudwatch", region_name=REGION)
_bedrock = boto3.client(
    "bedrock-runtime", region_name=REGION,
    config=BotoConfig(read_timeout=8, connect_timeout=3, retries={"max_attempts": 1}),
)


def _today_partition() -> str:
    # UTC date, matching how the signal store keys tenant_decision_date.
    return f"{TENANT}#{time.strftime('%Y-%m-%d', time.gmtime())}"


def _sample_confident_allows() -> list[dict]:
    """Pull recent distilled confident-ALLOW verdicts (the fast-ALLOWed requests) from
    the signal store via the decision-date GSI. Returns the input fields to re-check."""
    from boto3.dynamodb.conditions import Key

    table = _ddb.Table(SIGNALS_TABLE)
    cut_ms = int((time.time() - LOOKBACK_MIN * 60) * 1000)
    out: list[dict] = []
    lek = None
    while len(out) < SAMPLE_SIZE:
        kw = dict(
            IndexName="decision-date-timestamp-index",
            KeyConditionExpression=Key("tenant_decision_date").eq(_today_partition())
            & Key("timestamp_ms").gte(cut_ms),
            ScanIndexForward=False,  # newest first
            ExpressionAttributeNames={"#s": "source", "#d": "decision"},
            ProjectionExpression="#s, #d, confidence, record_type, tool_name, "
            "operation_type, user_input",
        )
        if lek:
            kw["ExclusiveStartKey"] = lek
        resp = table.query(**kw)
        for it in resp.get("Items", []):
            if it.get("source") != "sentra.distilled":
                continue
            if it.get("record_type") == "not_run":
                continue
            conf = it.get("confidence")
            if it.get("decision") != "ALLOW" or conf is None:
                continue
            if float(conf) < ALLOW_CONF_BAR:
                continue
            out.append({
                "tool_name": it.get("tool_name", ""),
                "operation_type": it.get("operation_type", ""),
                "user_input": it.get("user_input", ""),
                "distilled_conf": float(conf),
            })
            if len(out) >= SAMPLE_SIZE:
                break
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
    return out


def _haiku_verdict(row: dict) -> str | None:
    """Re-run one input through Haiku (same prompt/schema as prod). Returns
    'ALLOW'/'DENY', or None on any Bedrock error (excluded from the rate — a
    transport failure is not a disagreement)."""
    try:
        resp = _bedrock.converse(
            modelId=HAIKU_TARGET,
            system=[{"text": SYSTEM_PROMPT}],
            messages=build_messages(
                tool_name=row["tool_name"],
                tool_params={},
                user_input=row["user_input"],
                agent_id="drift-check",
            ),
            toolConfig={"tools": [TOOL_SPEC], "toolChoice": TOOL_CHOICE},
            inferenceConfig={"maxTokens": 512, "temperature": 0.0},
        )
        for block in resp["output"]["message"]["content"]:
            tu = block.get("toolUse") if isinstance(block, dict) else None
            if tu and tu.get("name") == TOOL_NAME:
                inp = tu.get("input")
                if isinstance(inp, str):
                    inp = json.loads(inp)
                return inp.get("decision")
    except Exception as exc:  # noqa: BLE001 — a Bedrock error is not a disagreement
        logger.warning("drift re-check Haiku call failed (excluded): %s", exc)
    return None


def handler(event, context):
    samples = _sample_confident_allows()
    n = len(samples)
    if n == 0:
        logger.info("drift-check: no confident-ALLOW samples in the window; nothing to check")
        # Emit 0 disagreement + 0 sample size so the alarm sees data (not INSUFFICIENT).
        _publish(0.0, 0, 0)
        return {"checked": 0, "disagreements": 0, "rate": 0.0}

    disagreements = 0
    rechecked = 0
    conflicts = []
    for row in samples:
        v = _haiku_verdict(row)
        if v is None:
            continue  # Bedrock error — not counted either way
        rechecked += 1
        if v == "DENY":
            disagreements += 1
            conflicts.append({"tool": row["tool_name"], "conf": row["distilled_conf"],
                              "input": row["user_input"][:80]})

    rate = (disagreements / rechecked) if rechecked else 0.0
    logger.info(
        "drift-check: sampled=%d rechecked=%d disagreements=%d rate=%.4f conflicts=%s",
        n, rechecked, disagreements, rate, json.dumps(conflicts[:10]),
    )
    _publish(rate, disagreements, rechecked)
    return {"checked": rechecked, "disagreements": disagreements, "rate": rate,
            "conflicts": conflicts[:10]}


def _publish(rate: float, disagreements: int, rechecked: int) -> None:
    """Publish the drift metrics. `DistilledDriftDisagreement` (the rate) is what the
    alarm watches; the counts are for the dashboard."""
    try:
        _cw.put_metric_data(
            Namespace=NAMESPACE,
            MetricData=[
                {"MetricName": "DistilledDriftDisagreement", "Value": rate, "Unit": "None"},
                {"MetricName": "DistilledDriftDisagreementCount", "Value": disagreements, "Unit": "Count"},
                {"MetricName": "DistilledDriftRechecked", "Value": rechecked, "Unit": "Count"},
            ],
        )
    except Exception as exc:  # noqa: BLE001 — never fail the run over a metric publish
        logger.error("drift-check metric publish failed: %s", exc)
