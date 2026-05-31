#!/usr/bin/env python3
"""ML Threat Classifier eval harness — WS19 Task 2.3 / LLD 19 §10.

Reads a labeled JSONL dataset (output of extract_ml_eval_dataset.py and/or
human-reviewed generate_adversarial_dataset.py), runs each row through the
MLClassifierValidator against a specified Bedrock model, and reports:

  - precision / recall / F1 per threat_type
  - macro-averaged metrics across categories
  - confusion matrix
  - latency p50/p99
  - per-call Bedrock cost (configurable per model)
  - per-row predictions for failure analysis

Output:
  - {output-dir}/{run_id}.json — structured metrics + per-row predictions
  - {output-dir}/{run_id}.md — human-readable summary

CI gate (M2 Task 2.4):
  Pass `--ci-gate --thresholds-yaml eval_thresholds.yaml` to fail the process
  if metrics fall below the configured thresholds. The workflow YAML wires
  this on PRs touching ML classifier code.

Usage (local):
    AWS_PROFILE=sentra python scripts/eval_ml_classifier.py \\
        --dataset /tmp/ml-eval-dataset.holdout.jsonl \\
        --model anthropic.claude-haiku-4-5-20251001-v1:0 \\
        --output-dir ./eval_results/

Usage (with adversarial set + thresholds):
    python scripts/eval_ml_classifier.py \\
        --dataset /tmp/ml-adversarial/adversarial-v1-20260530.labeled.jsonl \\
        --model anthropic.claude-haiku-4-5-20251001-v1:0 \\
        --thresholds-yaml scripts/eval_thresholds.yaml \\
        --ci-gate
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import statistics
import sys
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("eval_ml_classifier")


# Allow importing app.* when run from the repo root (so the script doesn't have
# to live inside src/security-controller).
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_CONTROLLER_APP = os.path.join(_REPO_ROOT, "src", "security-controller")
if _CONTROLLER_APP not in sys.path:
    sys.path.insert(0, _CONTROLLER_APP)


# Cost per 1M tokens (input, output) — keep in sync with LLD 19 §13.1.
MODEL_COSTS = {
    "anthropic.claude-haiku-4-5-20251001-v1:0": (1.00, 5.00),
    "anthropic.claude-sonnet-4-6-v1:0": (3.00, 15.00),
    "us.anthropic.claude-opus-4-1-20250805-v1:0": (15.00, 75.00),
}


@dataclass
class RowPrediction:
    row_id: int
    label_decision: str
    label_threat_type: str
    pred_decision: Optional[str]
    pred_threat_type: Optional[str]
    pred_confidence: Optional[float]
    model_used: Optional[str]
    latency_ms: float
    abstained: bool = False
    error: Optional[str] = None


@dataclass
class CategoryMetrics:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return (2 * p * r / (p + r)) if (p + r) else 0.0


@dataclass
class EvalReport:
    run_id: str
    model_id: str
    dataset_path: str
    row_count: int = 0
    abstain_count: int = 0
    error_count: int = 0
    per_category: dict[str, CategoryMetrics] = field(default_factory=dict)
    overall_precision: float = 0.0
    overall_recall: float = 0.0
    overall_f1: float = 0.0
    latency_p50_ms: float = 0.0
    latency_p99_ms: float = 0.0
    est_cost_usd: float = 0.0
    predictions: list[RowPrediction] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {**self.__dict__}
        d["per_category"] = {
            k: {"tp": m.tp, "fp": m.fp, "fn": m.fn,
                "precision": m.precision, "recall": m.recall, "f1": m.f1}
            for k, m in self.per_category.items()
        }
        d["predictions"] = [p.__dict__ for p in self.predictions]
        return d


def _load_dataset(path: str) -> list[dict]:
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    log.info("loaded %d rows from %s", len(rows), path)
    return rows


def _estimate_cost(model_id: str, n_calls: int) -> float:
    """Rough cost estimate: ~500 input tokens (system + few-shots + payload),
    ~50 output tokens. Per-1M rates from LLD 19 §13.1."""
    if model_id not in MODEL_COSTS:
        return 0.0
    in_per_m, out_per_m = MODEL_COSTS[model_id]
    return n_calls * (500 / 1_000_000 * in_per_m + 50 / 1_000_000 * out_per_m)


async def _eval_one_row(validator, row: dict, row_id: int) -> RowPrediction:
    # Lazy import to avoid pulling app.* before sys.path is set.
    from app.api.models import ValidationRequest

    req = ValidationRequest(
        request_id=f"eval-{row_id}",
        session_id=f"eval-session-{row_id}",
        agent_id=row.get("agent_id", "eval-agent"),
        tool_name=row.get("tool_name", ""),
        tool_params=row.get("tool_params", {}) or {},
        user_input=row.get("user_input", ""),
        timestamp="2026-05-30T00:00:00Z",
        operation_type="READ",
    )
    start = time.monotonic()
    try:
        result = await validator.validate(req)
    except Exception as exc:
        log.warning("row %d validation raised: %s", row_id, exc)
        return RowPrediction(
            row_id=row_id,
            label_decision=row.get("label_decision", row.get("human_label", "?")),
            label_threat_type=row.get("label_threat_type", row.get("proposed_threat_type", "?")),
            pred_decision=None, pred_threat_type=None, pred_confidence=None,
            model_used=None,
            latency_ms=(time.monotonic() - start) * 1000,
            error=str(exc),
        )
    latency_ms = (time.monotonic() - start) * 1000
    if result.is_abstain:
        return RowPrediction(
            row_id=row_id,
            label_decision=row.get("label_decision", "?"),
            label_threat_type=row.get("label_threat_type", "?"),
            pred_decision=None, pred_threat_type=None, pred_confidence=None,
            model_used=(result.metadata or {}).get("model_used"),
            latency_ms=latency_ms,
            abstained=True,
        )
    return RowPrediction(
        row_id=row_id,
        label_decision=row.get("label_decision", "?"),
        label_threat_type=row.get("label_threat_type", "?"),
        pred_decision=result.decision,
        pred_threat_type=result.threat_type or "NONE",
        pred_confidence=result.confidence,
        model_used=(result.metadata or {}).get("model_used"),
        latency_ms=latency_ms,
    )


def _aggregate(predictions: list[RowPrediction], model_id: str) -> EvalReport:
    """Compute per-category precision/recall/F1 + overall stats."""
    per_cat: dict[str, CategoryMetrics] = defaultdict(CategoryMetrics)
    latencies: list[float] = []
    for p in predictions:
        latencies.append(p.latency_ms)
        if p.abstained or p.error or p.pred_threat_type is None:
            # ABSTAINs don't contribute to precision/recall — they're scored
            # separately via abstain_count. This matches LLD 17 §4 absence
            # semantics (no signal = no contribution to the verdict).
            continue

        true_t = p.label_threat_type
        pred_t = p.pred_threat_type
        if true_t == pred_t:
            per_cat[true_t].tp += 1
        else:
            per_cat[pred_t].fp += 1
            per_cat[true_t].fn += 1

    # Macro-averaged precision/recall over categories with any signal.
    active = [m for m in per_cat.values() if (m.tp + m.fp + m.fn) > 0]
    overall_p = statistics.mean(m.precision for m in active) if active else 0.0
    overall_r = statistics.mean(m.recall for m in active) if active else 0.0
    overall_f1 = (2 * overall_p * overall_r / (overall_p + overall_r)) if (overall_p + overall_r) else 0.0

    latencies.sort()
    p50 = latencies[len(latencies) // 2] if latencies else 0.0
    p99 = latencies[int(len(latencies) * 0.99)] if latencies else 0.0

    return EvalReport(
        run_id=uuid.uuid4().hex[:8],
        model_id=model_id,
        dataset_path="",  # filled by caller
        row_count=len(predictions),
        abstain_count=sum(1 for p in predictions if p.abstained),
        error_count=sum(1 for p in predictions if p.error),
        per_category=dict(per_cat),
        overall_precision=overall_p,
        overall_recall=overall_r,
        overall_f1=overall_f1,
        latency_p50_ms=p50,
        latency_p99_ms=p99,
        est_cost_usd=_estimate_cost(model_id, len([p for p in predictions if not p.abstained and not p.error])),
        predictions=predictions,
    )


def _write_markdown(path: str, report: EvalReport) -> None:
    lines = [
        f"# ML Classifier Eval Report — {report.run_id}",
        "",
        f"- Model: `{report.model_id}`",
        f"- Dataset: `{report.dataset_path}`",
        f"- Rows: **{report.row_count}** ({report.abstain_count} abstain, {report.error_count} error)",
        f"- Overall macro-precision: **{report.overall_precision:.3f}**",
        f"- Overall macro-recall: **{report.overall_recall:.3f}**",
        f"- Overall macro-F1: **{report.overall_f1:.3f}**",
        f"- Latency p50: {report.latency_p50_ms:.0f} ms / p99: {report.latency_p99_ms:.0f} ms",
        f"- Est. Bedrock cost (this run): ${report.est_cost_usd:.4f}",
        "",
        "## Per-category metrics",
        "",
        "| Threat type | TP | FP | FN | Precision | Recall | F1 |",
        "|---|---|---|---|---|---|---|",
    ]
    for cat in sorted(report.per_category.keys()):
        m = report.per_category[cat]
        lines.append(
            f"| {cat} | {m.tp} | {m.fp} | {m.fn} | "
            f"{m.precision:.3f} | {m.recall:.3f} | {m.f1:.3f} |"
        )
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    log.info("wrote markdown summary to %s", path)


def _load_thresholds(path: str) -> dict:
    """Trivial YAML loader (key: value only) so we don't pull pyyaml as a hard
    dep for CI gate — keep this script importable from any controller env."""
    out = {}
    with open(path) as f:
        for raw in f:
            line = raw.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            k, v = line.split(":", 1)
            try:
                out[k.strip()] = float(v.strip())
            except ValueError:
                out[k.strip()] = v.strip()
    return out


def _check_gate(report: EvalReport, thresholds: dict) -> tuple[bool, list[str]]:
    failures: list[str] = []

    def check(name: str, value: float, op: str = "ge"):
        if name not in thresholds:
            return
        thr = float(thresholds[name])
        ok = value >= thr if op == "ge" else value <= thr
        if not ok:
            failures.append(f"{name}={value:.3f} fails threshold {op} {thr}")

    check("overall_precision", report.overall_precision)
    check("overall_recall", report.overall_recall)
    check("overall_f1", report.overall_f1)
    check("latency_p99_ms", report.latency_p99_ms, op="le")

    # Per-category recall thresholds (e.g. recall_PII_EXPOSURE).
    for cat, m in report.per_category.items():
        check(f"recall_{cat}", m.recall)

    return (len(failures) == 0, failures)


async def _amain(args) -> int:
    rows = _load_dataset(args.dataset)
    if not rows:
        log.error("empty dataset")
        return 2

    # Configure validator to use the target model directly (bypass profile).
    os.environ["ML_CLASSIFIER_ENABLED"] = "true"
    os.environ["ML_CLASSIFIER_HOT_MODEL_ID"] = args.model
    os.environ["ML_CLASSIFIER_INFERENCE_PROFILE_ARN"] = ""
    # Force re-read of settings before importing validator.
    from app.config import Settings
    from app import config as _config_mod
    _config_mod.settings = Settings()

    from app.validators.ml_classifier import MLClassifierValidator
    validator = MLClassifierValidator()

    sem = asyncio.Semaphore(args.concurrency)

    async def _bounded(row, i):
        async with sem:
            return await _eval_one_row(validator, row, i)

    log.info("running eval on %d rows (concurrency=%d)…", len(rows), args.concurrency)
    predictions = await asyncio.gather(*[_bounded(r, i) for i, r in enumerate(rows)])

    report = _aggregate(predictions, args.model)
    report.dataset_path = args.dataset

    os.makedirs(args.output_dir, exist_ok=True)
    json_path = os.path.join(args.output_dir, f"{report.run_id}.json")
    md_path = os.path.join(args.output_dir, f"{report.run_id}.md")
    with open(json_path, "w") as f:
        json.dump(report.to_dict(), f, indent=2, default=str)
    log.info("wrote JSON report to %s", json_path)
    _write_markdown(md_path, report)

    if args.thresholds_yaml:
        thresholds = _load_thresholds(args.thresholds_yaml)
        ok, failures = _check_gate(report, thresholds)
        if not ok:
            log.error("CI gate FAILED:")
            for fail in failures:
                log.error("  %s", fail)
            if args.ci_gate:
                return 1
        else:
            log.info("CI gate passed.")

    log.info("summary: precision=%.3f recall=%.3f F1=%.3f p99=%.0fms abstain=%d/%d cost=$%.4f",
             report.overall_precision, report.overall_recall, report.overall_f1,
             report.latency_p99_ms, report.abstain_count, report.row_count, report.est_cost_usd)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dataset", required=True, help="JSONL with label_decision + label_threat_type per row")
    p.add_argument("--model", required=True, help="Bedrock model ID to evaluate")
    p.add_argument("--output-dir", default="./eval_results/")
    p.add_argument("--concurrency", type=int, default=4, help="parallel Bedrock calls (mind your quota)")
    p.add_argument("--thresholds-yaml", help="path to eval_thresholds.yaml for CI gate")
    p.add_argument("--ci-gate", action="store_true", help="exit nonzero when thresholds fail")
    args = p.parse_args()
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    sys.exit(main())
