#!/usr/bin/env python3
"""MEAS-D2-RECALL / R5-C FP-budget measurement runner (WS-L M2.4/M3.3/M5.2-5.3).

Feeds a LABELED corpus (attack + benign) through the REAL D2 (IndirectInjection)
and D3 (MemoryWrite) detectors via the M5.2 offline harness
(`app.services.detection_eval.score_detector` + `fp_budget_gate`), and reports
precision / recall / F1 / FP-rate per detector so the R5-C enforce-graduation
decision is made on a MEASURED number, not asserted.

This is the runner the ws-l M2.4 acceptance item (MEAS-D2-RECALL) calls for; the
M5.2 harness shipped the scoring LIBRARY, this wires it to a corpus.

Corpus: demo-agents/eval/labeled_prompts.jsonl  ({"text","label"}, label 1=attack,
0=benign) — the only labeled set with BENIGN negatives (FP-rate needs negatives).

Run hermetically (project memory):
  cd src/security-controller && env -u AWS_PROFILE AWS_ACCESS_KEY_ID=test \
    AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=us-east-1 \
    venv/bin/python ../../scripts/meas_d2_d3_fp_budget.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Make the security-controller app importable regardless of CWD.
_CTRL = Path(__file__).resolve().parent.parent / "src" / "security-controller"
sys.path.insert(0, str(_CTRL))

from app.api.models import ValidationRequest  # noqa: E402
from app.services.detection_eval import score_detector, fp_budget_gate  # noqa: E402

CORPUS = Path(__file__).resolve().parent.parent / "demo-agents" / "eval" / "labeled_prompts.jsonl"

# R5-C FP budget: the ceiling on the fraction of BENIGN inputs a detector may wrongly
# DENY before its enforce flag is flipped. 0.01 (1%) is a conservative default for an
# inline blocker; adjust per founder call. The gate is advisory output — the human flips.
FP_BUDGET = float(os.environ.get("FP_BUDGET", "0.01"))


_LIMIT = int(os.environ.get("MEAS_LIMIT", "0"))  # 0 = full corpus; N = first N items (smoke)


def _load_corpus() -> list[tuple[ValidationRequest, bool]]:
    items: list[tuple[ValidationRequest, bool]] = []
    with open(CORPUS) as fh:
        for i, line in enumerate(fh):
            if _LIMIT and len(items) >= _LIMIT:
                break
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            text = d.get("text", "")
            is_attack = int(d.get("label", 0)) == 1
            # A content-phase request carrying the corpus text as ingested content.
            req = ValidationRequest(
                request_id=f"meas-{i}",
                session_id="meas-session",
                agent_id="acme-payments-agent",
                tool_name="ingest_content",
                tool_params={},
                user_input="",                 # content phase → payload is in content_text
                timestamp="2026-07-03T00:00:00.000Z",
                operation_type="READ",
                phase="content",
                content_text=text,
            )
            items.append((req, is_attack))
    return items


async def _main() -> int:
    corpus = _load_corpus()
    n_attack = sum(1 for _, a in corpus if a)
    n_benign = len(corpus) - n_attack
    print(f"Corpus: {len(corpus)} items ({n_attack} attack / {n_benign} benign)")
    print(f"FP budget (R5-C ceiling): {FP_BUDGET:.4f}\n")

    # Build the real detectors against a real service (the harness scores the detector's
    # own signal, pre-enforce-wrapper — score_detector reads should_deny directly).
    from app.services.validation_service import ValidationService
    service = ValidationService()

    from app.validators.indirect_injection import IndirectInjectionValidator
    from app.validators.memory_write import MemoryWriteValidator
    d2 = IndirectInjectionValidator(service)
    d3 = MemoryWriteValidator(service)

    async def detect_d2(req):
        return await d2.validate(req)

    async def detect_d3(req):
        # D3 scores the same text as a memory-write candidate (phase=memory semantics).
        mreq = req.model_copy(update={"phase": "memory"})
        return await d3.validate(mreq)

    results = {}
    for name, detect in (("D2 indirect_injection", detect_d2), ("D3 memory_write", detect_d3)):
        score = await score_detector(detect, corpus)
        may_enforce = fp_budget_gate(score, FP_BUDGET)
        results[name] = (score, may_enforce)
        print(f"=== {name} ===")
        print(f"  TP={score.tp} FP={score.fp} TN={score.tn} FN={score.fn}")
        print(f"  precision={score.precision:.4f}  recall={score.recall:.4f}  F1={score.f1:.4f}")
        print(f"  FP-rate={score.fp_rate:.4f}  (budget {FP_BUDGET:.4f})")
        print(f"  R5-C gate → MAY ENFORCE: {'YES' if may_enforce else 'NO (FP-rate over budget → stay advisory)'}\n")

    print("=== R5-C decision summary ===")
    for name, (score, ok) in results.items():
        print(f"  {name}: FP-rate {score.fp_rate:.4f} {'<=' if ok else '>'} {FP_BUDGET:.4f} → {'ENFORCE OK' if ok else 'HOLD ADVISORY'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
