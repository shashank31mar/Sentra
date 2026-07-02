#!/usr/bin/env python3
"""WS-0 Test-3 (M0-4 / metric 6c): masked-vs-unmasked deep-tier recall delta.

Throwaway rig. For each attack row, run the REAL deep tier on (1) unmasked content
and (2) content masked by the REAL production WS-E Tier-1 redactor (SDK redact()),
and report per-class recall(unmasked), recall(masked), delta, with a Wilson 95% CI.

Deep tier (lld/34 §6c) = the two live detectors:
  - Sigma / prompt-signature : sigma_engine.match_rules(text)   [S3/DDB rules]
  - ML classifier            : ml_classifier.validate(request)  [real Bedrock, ENABLED]
A row counts as DETECTED if EITHER detector returns decision=DENY (deny-overrides:
the deep tier's job is to catch it; either signal firing = caught).

Classes measured + reported SEPARATELY, never averaged (§7.3 HARD RULE).
CI read against ~semantic-unit N, not row count (corpus MANIFEST honesty).

Env: run with ML_CLASSIFIER_ENABLED=true + AWS creds (profile sentra) + us-east-1.
Never mocks Bedrock (§6c invalidator). Writes results/recall_<ts>.json.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "corpus"
RESULTS = HERE / "results"
RESULTS.mkdir(exist_ok=True)

# --- import the REAL production code (SDK redactor + controller detectors) ---- #
REPO = HERE.parents[1]
SDK_SRC = REPO / "demo-agents" / "sdk" / "aegion-guard-python" / "src"
CTRL = REPO / "src" / "security-controller"
sys.path.insert(0, str(SDK_SRC))
sys.path.insert(0, str(CTRL))

from aegion_guard.redaction import redact  # noqa: E402  the real WS-E Tier-1 masker


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score 95% CI for a proportion k/n (§6c / §7.6)."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


async def _detect(text: str, sigma_engine, ml_validator, ValidationRequest,
                  idx: int) -> dict:
    """Run BOTH detectors on one text. DETECTED = either returns DENY."""
    # Sigma (local regex over S3-loaded rules)
    sig_deny = False
    sig_err = None
    try:
        sig = await sigma_engine.match_rules(text)
        sig_deny = getattr(sig, "should_deny", False) or getattr(sig, "decision", "") == "DENY"
    except Exception as e:  # a detector error is NOT a detection (honest)
        sig_err = f"{type(e).__name__}: {e}"

    # ML classifier (real Bedrock)
    ml_deny = False
    ml_abstain = False
    ml_err = None
    try:
        req = ValidationRequest(
            request_id=f"ws0-recall-{idx}",
            session_id=f"ws0-recall-sess-{idx % 8}",
            agent_id="acme-payments-agent",
            tool_name="process_refund",
            tool_params={},
            user_input=text,
            timestamp="2026-07-02T00:00:00.000Z",
            operation_type="WRITE",
        )
        res = await ml_validator.validate(req)
        dec = getattr(res, "decision", None)
        ml_deny = (dec == "DENY") or getattr(res, "should_deny", False)
        ml_abstain = dec is None
    except Exception as e:
        ml_err = f"{type(e).__name__}: {e}"

    return {"detected": bool(sig_deny or ml_deny),
            "sigma_deny": sig_deny, "ml_deny": ml_deny, "ml_abstain": ml_abstain,
            "sigma_err": sig_err, "ml_err": ml_err}


async def score_class(cls: str, rows: list[dict], sigma_engine, ml_validator,
                      ValidationRequest, concurrency: int) -> dict:
    sem = asyncio.Semaphore(concurrency)

    async def one(row: dict, i: int) -> dict:
        async with sem:
            text = row["text"]
            masked = redact(text)  # REAL WS-E Tier-1 production redactor
            unmasked_res, masked_res = await asyncio.gather(
                _detect(text, sigma_engine, ml_validator, ValidationRequest, i * 2),
                _detect(masked, sigma_engine, ml_validator, ValidationRequest, i * 2 + 1),
            )
            return {
                "variant": row["variant"],
                "source": row["source_corpus"],
                "text_changed_by_redaction": masked != text,
                "unmasked_detected": unmasked_res["detected"],
                "masked_detected": masked_res["detected"],
                "unmasked": unmasked_res,
                "masked": masked_res,
            }

    per_row = await asyncio.gather(*[one(r, i) for i, r in enumerate(rows)])

    n = len(per_row)
    u_hits = sum(1 for r in per_row if r["unmasked_detected"])
    m_hits = sum(1 for r in per_row if r["masked_detected"])
    u_recall = u_hits / n if n else 0.0
    m_recall = m_hits / n if n else 0.0
    # rows where redaction actually changed the text (the ones masking COULD affect)
    changed = [r for r in per_row if r["text_changed_by_redaction"]]
    changed_lost = sum(1 for r in changed
                       if r["unmasked_detected"] and not r["masked_detected"])
    return {
        "class": cls,
        "n_rows": n,
        "unmasked_recall": round(u_recall, 4),
        "masked_recall": round(m_recall, 4),
        "delta": round(u_recall - m_recall, 4),
        "unmasked_ci95": [round(x, 4) for x in wilson_ci(u_hits, n)],
        "masked_ci95": [round(x, 4) for x in wilson_ci(m_hits, n)],
        "rows_redaction_changed": len(changed),
        "detections_lost_to_masking_on_changed_rows": changed_lost,
        "per_row": per_row,
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="cap rows/class (0=all); for a cheap smoke run")
    ap.add_argument("--concurrency", type=int, default=8)
    args = ap.parse_args()

    if os.environ.get("ML_CLASSIFIER_ENABLED", "").lower() != "true":
        sys.exit("Refusing to run: set ML_CLASSIFIER_ENABLED=true (real Bedrock deep tier, §6c).")

    # import controller detectors AFTER env is set so settings pick up the flag
    from app.validators.sigma_engine import get_sigma_engine  # noqa: E402
    from app.validators.ml_classifier import MLClassifierValidator  # noqa: E402
    from app.api.models import ValidationRequest  # noqa: E402

    sigma_engine = get_sigma_engine()
    ml_validator = MLClassifierValidator(bedrock_client=None)

    # detector-version stamp (§6c MANDATORY)
    stamp = {
        "ml_hot_target": getattr(ml_validator, "hot_target", "?"),
        "ml_escalation": getattr(ml_validator, "escalation_model_id", "?"),
        "ml_enabled": os.environ.get("ML_CLASSIFIER_ENABLED"),
        "run_started": None,  # filled below (no Date.now in scripts; use time here — real script, not workflow)
    }
    stamp["run_started"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    out = {"detector_version": stamp, "classes": {}}
    for cls in ("exfiltration", "indirect_injection"):
        path = CORPUS / f"{cls}.jsonl"
        rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        if args.limit:
            rows = rows[:args.limit]
        print(f"[{cls}] scoring {len(rows)} rows (concurrency={args.concurrency})...", flush=True)
        res = await score_class(cls, rows, sigma_engine, ml_validator,
                                ValidationRequest, args.concurrency)
        # print summary, keep per_row only in the file
        summary = {k: v for k, v in res.items() if k != "per_row"}
        print(json.dumps(summary, indent=2), flush=True)
        out["classes"][cls] = res

    ts = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    outpath = RESULTS / f"recall_{ts}.json"
    outpath.write_text(json.dumps(out, indent=2))
    print(f"\nFull results (with per-row) → {outpath.relative_to(REPO)}")


if __name__ == "__main__":
    asyncio.run(main())
