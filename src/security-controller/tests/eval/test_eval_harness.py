"""WS-L M5.2 — the offline detection eval-harness (the authoritative quality gate).

Scores a detector against a labeled corpus → precision/recall/F1 + the FP-rate the
R5-C enforce-graduation gate reads (LLD 32 §14.2).
"""
from __future__ import annotations

import pytest

from app.api.models import ValidationRequest, ValidationResult
from app.services.detection_eval import (
    DetectorScore,
    fp_budget_gate,
    score_detector,
)


def _req(content_text: str) -> ValidationRequest:
    return ValidationRequest(
        request_id="r", session_id="s", agent_id="a", tool_name="ingest",
        tool_params={}, user_input="", timestamp="2026-07-03T00:00:00Z",
        operation_type="READ", phase="content", content_text=content_text,
    )


def test_eval_harness_computes_prf1():
    """The metric math is correct: a DetectorScore with tp=8, fp=2, tn=88, fn=2
    yields precision 0.8, recall 0.8, f1 0.8, fp_rate 2/90."""
    s = DetectorScore(tp=8, fp=2, tn=88, fn=2)
    assert s.precision == pytest.approx(8 / 10)
    assert s.recall == pytest.approx(8 / 10)
    assert s.f1 == pytest.approx(0.8)
    assert s.fp_rate == pytest.approx(2 / 90)


@pytest.mark.asyncio
async def test_harness_scores_detector_over_corpus_and_gate_reads_fp():
    """The harness runs a detector over a small labeled corpus and returns FP-rate +
    recall the gate reads; assert the gate blocks enforce-graduation when FP-rate
    exceeds the budget (INTEG seam)."""
    # A toy detector that DENYs when the content contains "attack".
    async def detect(req: ValidationRequest) -> ValidationResult:
        deny = "attack" in (req.content_text or "")
        return ValidationResult(
            decision="DENY" if deny else "ALLOW",
            reason="x", should_deny=deny, source="sentra.indirect_injection",
        )

    corpus = [
        (_req("attack payload one"), True),    # TP
        (_req("attack payload two"), True),    # TP
        (_req("benign report"), False),        # TN
        (_req("attack in a benign-looking doc"), False),  # FP (contains 'attack' but labeled benign)
        (_req("quarterly numbers"), False),    # TN
    ]
    score = await score_detector(detect, corpus)
    assert score.tp == 2 and score.fp == 1 and score.fn == 0
    # FP-rate = 1 / (1 + 2 TN) = 1/3.
    assert score.fp_rate == pytest.approx(1 / 3)
    # the gate blocks enforce when the FP-rate exceeds the budget; allows below.
    assert fp_budget_gate(score, fp_budget=0.05) is False
    assert fp_budget_gate(score, fp_budget=0.5) is True
