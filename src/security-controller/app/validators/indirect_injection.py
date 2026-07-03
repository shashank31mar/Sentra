"""D2 — indirect / second-order injection detector (content phase).

WS-L / LLD 32 §5.2 / FR-3.6. Runs on `phase=content` as a tier-1 `ValidatorNode`
(`Source.SENTRA_INDIRECT`). Detects an INGESTED content payload (a fetched doc,
tool output, retrieved passage) that is trying to inject instructions into the
agent — the "second-order" injection an ordinary request-phase prompt check
misses because the malicious text arrives as *data*, not as the user's prompt.

THREE passes over the REDACTED `content_text` (the `redaction.ner` barrier runs
FIRST and mutates `content_text` in place; D2 reads the mutated view):
  1. sigma  — `service.sigma_engine.match_rules(req.content_text)` (cheap regex
              over known signatures FIRST). NOTE: `content_text`, NOT `user_input`
              (the named footgun — `user_input` is empty on a content call).
  2. ML     — the ML classifier framed as "is this ingested content injecting
              instructions?" (the novel subset the signatures miss). The
              classifier reads `request.user_input`, so D2 presents `content_text`
              THERE via a shallow request copy (`model_copy`, non-mutating), not
              the raw request whose `user_input` is empty on a content call.
  3. heuristics — instruction-density (imperative-verb / second-person ratio) +
              encoding/obfuscation scan (base64, homoglyphs, zero-width).

Live-enforce, FP/precision-gated (R5-C): D2 blocks in the first wave once the
offline eval-harness clears the FP budget. Until then its DENY is captured
ADVISORY (does not decide) via the tier-1 enforce mechanism (`metadata["enforce"]`),
NOT relocated to a shadow node. A no-denier content run fails secure to DENY via
the phase-aware `all_allow`, never a silent ALLOW.
"""

from __future__ import annotations

import logging
import re
import unicodedata

from app.api.models import ValidationRequest, ValidationResult
from app.combiners import Source

logger = logging.getLogger(__name__)

REASON_INDIRECT = "INDIRECT_INJECTION"

# Imperative / instruction-framing markers. A high density of these in INGESTED
# content is a second-order-injection tell ("ignore your instructions", "you must
# now…"). Deliberately conservative — this is one of three passes, not a gate.
_IMPERATIVE_MARKERS = (
    "ignore", "disregard", "forget", "override", "you must", "you should",
    "now you", "instead of", "system prompt", "new instructions", "act as",
    "pretend", "reveal", "print", "output the", "send", "exfiltrate",
)
# Zero-width / bidi obfuscation characters (an evasion tell — hides an injection
# inside otherwise-benign text). LLD 29a normalize-then-detect discipline.
_ZERO_WIDTH = "​‌‍⁠﻿‪‫‬‭‮"
# A base64-ish blob (long run of base64 alphabet) is an encoding-evasion tell.
_BASE64_RUN = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")

# Instruction-density threshold: fraction of imperative markers per ~sentence
# unit above which the heuristic fires. Conservative; the FP budget (R5-C) is the
# real rollout gate.
_DENSITY_THRESHOLD = 0.02


def _has_mixed_script_token(text: str) -> bool:
    """A single alphabetic run mixing scripts (LATIN + CYRILLIC/GREEK/...) is the
    canonical homoglyph tell — NFKC does NOT fold cross-script look-alikes (e.g.
    Cyrillic `а` U+0430 for Latin `a` normalizes to itself, same length), so the
    NFKC/length branch alone misses them."""
    for token in re.findall(r"\w+", text, flags=re.UNICODE):
        scripts = set()
        for ch in token:
            if ch.isalpha():
                name = unicodedata.name(ch, "")
                if "CYRILLIC" in name:
                    scripts.add("CYRILLIC")
                elif "GREEK" in name:
                    scripts.add("GREEK")
                elif "LATIN" in name:
                    scripts.add("LATIN")
                # (ASCII digits / underscore are not alpha — extend as needed)
        if len(scripts) > 1:
            return True
    return False


class IndirectInjectionValidator:
    """D2 content-phase detector — LLD 32 §5.2."""

    def __init__(self, service):
        # Delegate to the shared sigma + ML validators the request phase already
        # uses (reuse before build — engineering.md). The service owns the single
        # cached instances.
        self._service = service

    async def validate(self, req: ValidationRequest) -> ValidationResult:
        text = getattr(req, "content_text", None) or ""
        if not text.strip():
            # Nothing to inspect — abstain (the phase-aware all_allow fails secure
            # to DENY when no node decides; D2 does not fabricate an ALLOW).
            return ValidationResult.abstain("indirect_injection: empty content_text")

        # 1) sigma pass over the REDACTED content_text (NOT user_input — the named
        #    footgun; user_input is empty on a content call so match_rules(user_input)
        #    would scan nothing).
        sigma_result = await self._service.sigma_engine.match_rules(text)
        if sigma_result.should_deny:
            return ValidationResult(
                decision="DENY",
                reason=f"{REASON_INDIRECT}: signature match in ingested content "
                       f"({sigma_result.reason})",
                violation_type=REASON_INDIRECT,
                threat_type=REASON_INDIRECT,
                matched_rule=sigma_result.matched_rule,
                severity=sigma_result.severity,
                should_deny=True,
                source=Source.SENTRA_INDIRECT,
                confidence=1.0,
            )

        # 2) content-framed ML — the novel subset the signatures miss. The ML
        #    classifier builds its prompt from request.user_input ONLY
        #    (ml_classifier.py:257), which is empty on a content call — so we
        #    present the ingested content THERE via a shallow pydantic-v2 copy.
        #    model_copy(update=...) returns a NEW instance; it does NOT mutate the
        #    original req the other DAG nodes share. A DENY on the ingested content
        #    is an indirect-injection signal.
        content_req = req.model_copy(update={"user_input": text})
        ml_result = await self._service.ml_classifier.validate(content_req)
        if ml_result.should_deny:
            return ValidationResult(
                decision="DENY",
                reason=f"{REASON_INDIRECT}: ML flagged ingested content as injecting",
                violation_type=REASON_INDIRECT,
                threat_type=REASON_INDIRECT,
                should_deny=True,
                source=Source.SENTRA_INDIRECT,
                confidence=ml_result.confidence,
            )

        # 3) heuristics — instruction density + encoding/obfuscation.
        density_hit, density = self._instruction_density(text)
        obfuscation_hit, kind = self._obfuscation(text)
        if density_hit or obfuscation_hit:
            detail = "instruction-density" if density_hit else f"obfuscation:{kind}"
            return ValidationResult(
                decision="DENY",
                reason=f"{REASON_INDIRECT}: heuristic {detail} in ingested content",
                violation_type=REASON_INDIRECT,
                threat_type=REASON_INDIRECT,
                should_deny=True,
                source=Source.SENTRA_INDIRECT,
                confidence=0.7,
                metadata={"heuristic": detail, "density": round(density, 4)},
            )

        # Clean ingested content — vote ALLOW (a real ALLOW so the content run has a
        # decider; the phase-aware all_allow only fails secure when NO node decides).
        return ValidationResult(
            decision="ALLOW",
            reason="indirect_injection: no injection signal in ingested content",
            should_deny=False,
            source=Source.SENTRA_INDIRECT,
        )

    # ------------------------------------------------------------------ helpers
    def _instruction_density(self, text: str) -> tuple[bool, float]:
        """Fraction of imperative/instruction markers relative to the token count.
        A high density in INGESTED content is a second-order-injection tell."""
        lowered = text.lower()
        tokens = max(len(lowered.split()), 1)
        hits = sum(lowered.count(marker) for marker in _IMPERATIVE_MARKERS)
        density = hits / tokens
        return (density >= _DENSITY_THRESHOLD and hits >= 2), density

    def _obfuscation(self, text: str) -> tuple[bool, str]:
        """Encoding / obfuscation scan: zero-width / bidi chars, homoglyphs
        (mixed-script tokens), compatibility-form obfuscation, and base64-ish
        blobs."""
        if any(ch in text for ch in _ZERO_WIDTH):
            return True, "zero_width"
        # Homoglyph tell: a single alphabetic token mixing scripts (Latin +
        # Cyrillic/Greek look-alikes). NFKC does NOT fold cross-script homoglyphs,
        # so this — not the NFKC/length branch — is what catches them.
        if _has_mixed_script_token(text):
            return True, "homoglyph"
        # Compatibility-form obfuscation: NFKC materially changes the string
        # (ligatures, full-width forms, etc.) with a length delta.
        nfkc = unicodedata.normalize("NFKC", text)
        if nfkc != text and len(nfkc) != len(text):
            return True, "compat_form"
        if _BASE64_RUN.search(text):
            return True, "base64"
        return False, ""
