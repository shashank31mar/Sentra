"""Mode A Detection Replay Rig (LLD 41 §4.3, §5.1, WS-C milestone C1)."""

import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from app.api.models import ValidationRequest
from app.services.detection_eval import score_detector
from benchmarks.core.case import BenchmarkCase
from benchmarks.core.context import RunContext


class CorpusIntegrityError(Exception):
    """Raised when error rate exceeds 2% of total cases (RES-1)."""


@dataclass
class ErrorRow:
    case_id: str
    detector: str
    exc: str


@dataclass
class ReplayResult:
    detector_scores: Dict[str, Any]
    errors: List[ErrorRow]
    scored_count: int
    total_cases: int


def case_to_request(case: BenchmarkCase, *, ctx: RunContext) -> ValidationRequest:
    """Convert a BenchmarkCase to a real ValidationRequest for Mode A replay.
    
    user_input is empty string for content/memory phases so payload rides content_text.
    """
    user_input = "" if case.phase in ("content", "memory") else case.user_input
    return ValidationRequest(
        request_id=f"bench-{case.case_id}",
        session_id=ctx.session_id_for(case.episode_id),
        agent_id=case.agent_id,
        tool_name=case.tool_name,
        tool_params=case.tool_params,
        user_input=user_input,
        timestamp=ctx.run_clock_iso,
        operation_type=case.operation_type,
        phase=case.phase,
        content_text=case.content_text,
    )


async def _immediate(val: Any) -> Any:
    return val


async def run_replay(
    detector: Any,
    detector_name: str,
    cases: Sequence[BenchmarkCase],
    ctx: RunContext,
) -> ReplayResult:
    """Run two-pass replay over a case corpus for a specific detector.
    
    PASS 1: Execute detector.validate(req) for every case. Memoize request_id -> ValidationResult.
            Catch exceptions into ErrorRow (dropped, never scored as ALLOW/TN).
    PASS 2: Execute score_detector over memoized closure (no duplicate detector calls).
    """
    if not cases:
        return ReplayResult(
            detector_scores={},
            errors=[],
            scored_count=0,
            total_cases=0,
        )

    corpus_items: List[Tuple[ValidationRequest, bool]] = [
        (case_to_request(c, ctx=ctx), c.label) for c in cases
    ]

    # PASS 1: The ONLY place the detector is invoked
    memo: Dict[str, Any] = {}
    errors: List[ErrorRow] = []

    for req, _label in corpus_items:
        try:
            res = await detector.validate(req)
            memo[req.request_id] = res
        except Exception as exc:
            errors.append(ErrorRow(case_id=req.request_id, detector=detector_name, exc=repr(exc)))

    total_cases = len(corpus_items)
    error_rate = len(errors) / total_cases if total_cases > 0 else 0.0
    if error_rate > 0.02:
        raise CorpusIntegrityError(
            f"Error rate {error_rate:.1%} exceeds maximum allowable threshold of 2% ({len(errors)}/{total_cases} cases failed)."
        )

    # PASS 2: score_detector consumed UNCHANGED over the memoized closure
    scored_items = [(req, label) for req, label in corpus_items if req.request_id in memo]
    
    async def memoized_detect(req: ValidationRequest) -> Any:
        return memo[req.request_id]

    score = await score_detector(memoized_detect, scored_items)

    # Invariant: len(scored) + len(errors) == total_cases
    assert len(scored_items) + len(errors) == total_cases

    detector_scores = {
        "score_obj": score,
        "tp": score.tp,
        "fp": score.fp,
        "tn": score.tn,
        "fn": score.fn,
        "precision": score.precision,
        "recall": score.recall,
        "f1": score.f1,
        "fp_rate": score.fp_rate,
    }

    return ReplayResult(
        detector_scores=detector_scores,
        errors=errors,
        scored_count=len(scored_items),
        total_cases=total_cases,
    )
