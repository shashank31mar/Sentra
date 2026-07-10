"""Distilled classifier CLIENT — the request-phase tier-1 front-runner (FR-3.12).

The distilled student model runs as a SEPARATE Fargate service
(app/distilled/server.py, CloudMap `distilled-classifier.sentra.internal`) because
its serving stack (torch + a ~465MB multilingual embedder) is too heavy for the
stdlib-lean controller — same sidecar pattern as phi-ner. This module is the thin
CLIENT the tier-1 chain-head calls: it POSTs {tool_name, operation_type, user_input}
to the model service and maps the response into a ValidationResult that drives the
`_run_ml` short-circuit.

THE ASYMMETRIC SHORT-CIRCUIT (measured-safe, 2026-07-10 eval + founder call):
  * confident DENY  (P(DENY)  >= distilled_deny_shortcircuit_min_confidence, 0.95)
      → short-circuit: BLOCK, skip Haiku. Measured precision 1.0 / 0 false-blocks —
        always safe (worst case is a fail-SECURE over-block, caught by drift metrics).
  * confident ALLOW (P(ALLOW) >= distilled_allow_shortcircuit_min_confidence, 0.95)
      → short-circuit: skip Haiku — BUT ONLY when distilled_allow_shortcircuit_enabled
        is True. Default OFF: a false-ALLOW skips the strong tier (fail-OPEN), so it is
        gated until a live SHADOW soak proves floor∪model leaves no hole (a confident-
        wrong ALLOW would let an attack through). The multilingual model scores the
        German/role injections it used to miss at LOW confidence (~0.53), so they fall
        through to Haiku — but shadow verifies this on real traffic before we trust it.
  * anything else (low confidence, service error/timeout, unset URL, interim)
      → escalate to Haiku (fail-secure). NEVER an abstain (an abstain aborts the chain
        and skips Haiku — the exact fail-open to avoid); always a concrete escalate.

The gate itself lives in registry._is_confident_distilled — this module returns the
raw {decision, confidence} and an `escalate` marker; the gate applies the thresholds.
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request

from app.api.models import ValidationRequest, ValidationResult
from app.combiners import Source
from app.config import settings

logger = logging.getLogger(__name__)

# The metadata flag the tier-1 chain-tail (`_run_ml`) reads to detect the
# non-confident/escalate path. A truthy `escalate` means "distilled had nothing
# confident to say (or could not be reached) — run Haiku".
ESCALATE_KEY = "escalate"


def _escalate(reason: str, **meta) -> ValidationResult:
    """A CONCRETE escalate verdict → Haiku runs. NEVER an abstain (would abort the
    chain and skip Haiku). Fail-secure: any inability to get a confident verdict
    lands here, so the strong tier always runs."""
    return ValidationResult(
        decision="ALLOW",
        reason=f"distilled: {reason}",
        should_deny=False,
        confidence=0.0,
        source=Source.SENTRA_DISTILLED,
        metadata={ESCALATE_KEY: True, "model": "distilled_v1", **meta},
    )


class DistilledClassifier:
    """Thin fail-secure HTTP client to the distilled model service. Same interface
    the interim stub had (`async def classify(req) -> ValidationResult`), so the
    scheduler wiring is unchanged."""

    def _post_sync(self, url: str, payload: dict, timeout: float) -> dict:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — fixed in-VPC host
            if resp.status != 200:
                raise urllib.error.HTTPError(url, resp.status, "non-200", resp.headers, None)
            return json.loads(resp.read().decode("utf-8"))

    async def classify(self, req: ValidationRequest) -> ValidationResult:
        """Call the model service; map its verdict to a ValidationResult. Every
        failure path returns a concrete escalate (→ Haiku), never an abstain."""
        base = settings.distilled_service_url
        if not base:
            # No service wired → escalate to Haiku (the pre-deploy steady state).
            return _escalate("service url unset → escalate to Haiku", model="unset")

        url = base.rstrip("/") + "/classify"
        payload = {
            "tool_name": req.tool_name or "",
            "operation_type": req.operation_type or "",
            "user_input": req.user_input or "",
        }
        timeout = settings.distilled_timeout_ms / 1000.0
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(self._post_sync, url, payload, timeout),
                timeout=timeout,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — timeout/HTTP/transport → escalate (fail-secure)
            logger.warning("distilled service call failed; escalating to Haiku: %s", exc)
            return _escalate("service error/timeout → escalate to Haiku", distilled_error=True)

        # Map the service verdict. The service returns confidence = P(the returned
        # decision). We carry decision + confidence; the gate in registry applies the
        # asymmetric thresholds. `escalate` is NOT set here for a concrete verdict —
        # the gate decides whether the confidence clears the bar; if it doesn't, the
        # gate itself falls through to Haiku.
        decision = result.get("decision")
        confidence = result.get("confidence")
        model_tag = result.get("model", "distilled_v1")
        if decision not in ("ALLOW", "DENY") or not isinstance(confidence, (int, float)):
            return _escalate("malformed service response → escalate to Haiku", model=model_tag)

        return ValidationResult(
            decision=decision,
            reason=f"distilled_v1: {decision} (confidence {confidence:.3f})",
            should_deny=(decision == "DENY"),
            confidence=float(confidence),
            source=Source.SENTRA_DISTILLED,
            metadata={"model": model_tag},  # NO escalate key — a concrete verdict
        )
