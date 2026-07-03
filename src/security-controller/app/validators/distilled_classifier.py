"""Distilled classifier — WS-L / LLD 32 §4.1, §4.3, FR-3.12.

The distilled model is the LIVE cheap tier-1 chain-HEAD in front of the Haiku ML
classifier. Its confident verdict DECIDES and short-circuits Haiku (confident-DENY
→ block; confident-ALLOW → allow; low-conf/error/timeout → Haiku, fail-secure).
The short-circuit is INTRINSIC — there is no OFF gate and no shadow window (LLD 32
§4.1, R5-B; founder 2026-07-03).

The MECHANISM (node + chain + short-circuit) is built and LIVE now (M6.0–M6.2).
Only the real distilled ARTIFACT is deferred: it comes from the §8 offline distill
loop → WS-E feedback store (not built). Until it ships, `classify` returns an
INTERIM escalate verdict (concrete ALLOW, `confidence=0.0`, `metadata['escalate']
= True`) so the short-circuit — though LIVE — never fires (nothing confident to
say) and Haiku always runs → verdict-equivalent to today (T-EQUIV). When the real
artifact swaps in behind this SAME interface, confident verdicts begin
short-circuiting Haiku live with zero wiring/config change (M6.3).
"""

from __future__ import annotations

import logging

from app.api.models import ValidationRequest, ValidationResult
from app.combiners import Source

logger = logging.getLogger(__name__)

# The metadata flag the tier-1 chain-tail (`_run_ml`) reads to detect the
# non-confident/escalate path (LLD 32 §4.1). A truthy `escalate` means "distilled
# had nothing confident to say — run Haiku". Kept as a module constant so the node
# and the classifier name the same string.
ESCALATE_KEY = "escalate"


class DistilledClassifier:
    """LIVE cheap tier-1 chain-HEAD. The short-circuit is intrinsic (M6.2):
    a confident verdict decides + skips Haiku. Until the real §8-distilled
    artifact swaps in, `classify` returns an INTERIM escalate verdict (no
    confident short-circuit fires — Haiku runs). Same interface either way.
    """

    async def classify(self, req: ValidationRequest) -> ValidationResult:
        """Return the distilled verdict driving the M6.2 short-circuit.

        INTERIM (until the §8 artifact, M6.3): a CONCRETE non-confident escalate
        verdict — `decision="ALLOW"`, `should_deny=False`, `confidence=0.0`,
        `metadata={"escalate": True, ...}`. `confidence 0.0 < threshold` ⇒ NOT
        confident ⇒ `_run_ml` takes the escalate branch ⇒ Haiku runs ⇒
        verdict-equivalent to today (T-EQUIV). The short-circuit is LIVE but never
        fires because the interim never returns a confident verdict.

        This is NOT `ValidationResult.abstain(...)`: an abstain would abort the
        chain and SKIP Haiku (`run_chain`, run.py) — the exact fail-open the
        interim must avoid. A concrete ALLOW keeps the chain alive so Haiku runs.

        REAL (§8 artifact, M6.3): load the distilled model and return a real
        `{decision, should_deny, confidence}`; a confident verdict then
        short-circuits Haiku live. SAME return contract — no wiring/config change.
        """
        # INTERIM — the real artifact is deferred (WS-L §8 / M6.3). A concrete,
        # non-confident escalate verdict so the LIVE short-circuit never fires and
        # Haiku decides (T-EQUIV). NEVER an abstain (would abort the chain).
        return ValidationResult(
            decision="ALLOW",
            reason="distilled_interim: escalate to Haiku (real artifact not yet loaded)",
            should_deny=False,
            confidence=0.0,
            source=Source.SENTRA_DISTILLED,
            metadata={ESCALATE_KEY: True, "model": "distilled_interim"},
        )
