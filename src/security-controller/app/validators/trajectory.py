"""D1 — conversation-trajectory detector (request phase, LLM-judge v1).

WS-L / LLD 32 §5.1 / FR-3.5. An ADDITIVE request-phase tier-1 `ValidatorNode`
(`Source.SENTRA_TRAJECTORY`, priority 68): an LLM-judge over the running transcript
(JAILJUDGE-style — "is this conversation escalating toward harm?"). It feeds the
deny-overrides combiner as ONE probabilistic signal (shadow→enforce), and is
NEVER a standalone gate.

Load-bearing invariants:
  * SIGNAL, never a gate (LLD 32 §5.1). [FACT] Safety-aligned models represent
    Crescendo-style responses as MORE benign the longer the conversation runs
    (arXiv 2507.02956, 2025); no published method reliably detects multi-turn
    attacks at low FP. So D1 votes (priority 68, below sigma 70) — it never decides
    alone. Even a "high risk" verdict is ADVISORY until the shadow→enforce
    graduation clears its benign-FP budget (M4.3).
  * v1 = LLM-judge, NO training corpus. The trained GRU is v2, explicitly deferred
    (do NOT build a titan-embed / trajectory_state DDB sequence-classifier here).
  * `trajectory_state` is SERVER-SIDE-WRITE-ONLY (SEC-3): D1 derives risk only from
    server-observed transcript + its own prior state — it NEVER trusts a
    client-asserted trajectory/risk field (an attacker lowering their own
    `trajectory_risk` to evade a crescendo DENY).
  * ABSTAIN on guard-model outage or when `D1_ENABLED` is off (no signal, not a DENY).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from app.api.models import ValidationRequest, ValidationResult
from app.combiners import Source

logger = logging.getLogger(__name__)

REASON_TRAJECTORY = "TRAJECTORY_ESCALATION"

# High-risk transcript markers the v1 LLM-judge keys on. In v1 this is the judge
# prompt's rubric made concrete; the real guard-model call swaps in behind the same
# interface (like the distilled artifact). Deliberately about ESCALATION across
# turns, not a single-turn signature (that is sigma's job).
_ESCALATION_MARKERS = (
    "step by step", "now that you", "continue from", "as we discussed",
    "you already agreed", "just this once", "hypothetically", "for a story",
    "ignore the previous refusal", "let's go further", "the next step",
)


def _d1_enabled() -> bool:
    """D1_ENABLED gate (default off → ABSTAIN). Read at call time (not latched) so a
    rolling deploy stays consistent within each task's env."""
    return os.environ.get("D1_ENABLED", "false").lower() in ("1", "true", "yes")


class TrajectoryValidator:
    """D1 LLM-judge-over-transcript (v1). A SIGNAL, never a gate."""

    def __init__(self, service=None):
        self._service = service

    async def validate(self, req: ValidationRequest,
                        session: Optional[Dict[str, Any]] = None) -> ValidationResult:
        if not _d1_enabled():
            return ValidationResult.abstain("trajectory: D1_ENABLED off")

        try:
            # SEC-3: derive trajectory risk ONLY from the server-side transcript +
            # this node's own prior state — NEVER from a client-asserted field. The
            # transcript comes from the server-observed session, not request.context.
            transcript = self._server_side_transcript(req, session)
            risk = await self._judge(transcript)
        except Exception as exc:  # noqa: BLE001 — a guard-model outage is an ABSTAIN, not a DENY
            logger.warning("trajectory judge unavailable; abstaining: %s", exc)
            return ValidationResult.abstain("trajectory: guard-model outage")

        if risk >= 0.5:
            # A trajectory-escalation SIGNAL. It votes into the combiner (priority
            # 68); it does NOT enforce until graduation (M4.3 wires enforce). Do not
            # let this alone decide — the wrapper leaves enforce unset by default.
            return ValidationResult(
                decision="DENY",
                reason=f"{REASON_TRAJECTORY}: transcript escalating toward harm "
                       f"(risk={risk:.2f})",
                violation_type=REASON_TRAJECTORY,
                threat_type=REASON_TRAJECTORY,
                should_deny=True,
                source=Source.SENTRA_TRAJECTORY,
                confidence=risk,
            )
        return ValidationResult(
            decision="ALLOW",
            reason="trajectory: no escalation detected",
            should_deny=False,
            source=Source.SENTRA_TRAJECTORY,
            confidence=1.0 - risk,
        )

    # ------------------------------------------------------------------ helpers
    def _server_side_transcript(self, req: ValidationRequest,
                                session: Optional[Dict[str, Any]]) -> str:
        """Assemble the transcript from SERVER-OBSERVED state only (SEC-3).

        Uses the session's server-side turn history plus THIS turn's user_input.
        Deliberately IGNORES any client-asserted `trajectory_risk` / `risk` field in
        request.context — the server never trusts a client-lowered risk level.
        """
        turns = []
        if session:
            history = session.get("transcript") or session.get("turns") or []
            if isinstance(history, (list, tuple)):
                turns.extend(str(t) for t in history)
        turns.append(getattr(req, "user_input", "") or "")
        return "\n".join(turns)

    async def _judge(self, transcript: str) -> float:
        """v1 LLM-judge over the transcript → a 0.0–1.0 escalation-risk score.

        v1 is a rubric-driven scan (no training corpus); the real guard-model call
        swaps in behind this same signature. Returns a risk score, never a hard
        verdict — the caller turns it into an advisory signal.
        """
        lowered = transcript.lower()
        hits = sum(1 for marker in _ESCALATION_MARKERS if marker in lowered)
        # Escalation risk grows with the count of escalation markers AND transcript
        # length (a longer coaxing conversation is riskier) — capped at 1.0.
        turn_count = transcript.count("\n") + 1
        risk = min(1.0, 0.34 * hits + (0.05 if turn_count >= 4 else 0.0))
        return risk
