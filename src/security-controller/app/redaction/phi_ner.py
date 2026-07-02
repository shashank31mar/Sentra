"""Tier-2 server-side free-text PHI redactor + persist-gate detector — WS-E2.

LLD 29 §4 (the NER barrier), §5.3.3 + §6.3 (the persist-gate). This is the SERVER
half of the two-tier redactor (§2.1): Tier-1 already masked *structured* PII at
the edge (typed tokens `⟦AEGR:{nonce}:CARD:6:4⟧` arriving in `tool_params`/
`user_input`); this layer redacts the surviving *free-text* PHI in the
`content_text` field of the content/output/memory phases (names, prose addresses,
conditions — the Safe-Harbor catch-all a deterministic matcher cannot bound).

Placement (§4.1): the redactor is invoked by a DAG **entry node** (registry.py) so
it runs BEFORE the phase's deep-detector nodes, the audit write, and the feedback
write — the happens-before **barrier** (F1). Every downstream consumer reads the
post-NER redacted `content_text`, never the raw.

Hermetic / stage-2 scope (task doc + LLD 29 §247):
  * NO live NER model and NO managed de-id API (AWS Comprehend Medical) is wired
    here — Comprehend even in gate-only mode pushes raw PHI to AWS = a new
    subprocessor, the exact friction the self-host default avoids. A served, warm
    ONNX/Presidio microservice + Dockerfile is **stage 3** (out of scope).
  * What ships here is the CLIENT + a `Tier2Redactor` INTERFACE and a
    deterministic, stdlib-only `ReferenceNerRedactor` STUB so the barrier, the
    NO-RAW invariant, and egress-fail-closed are all testable hermetically.

Fail-secure (§5.4, E3): a redactor outage raises :class:`NerUnavailable`; the
barrier node maps that to egress-fail-closed — the unredactable content is HELD
(dropped from `content_text`), the safe fields still process, the action is NOT
blanket-DENYed, and `EgressHeldCount`/`NerUnavailableCount` are emitted. The one
forbidden path is "skip-store but forward the raw onward" (§7.2).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol


class NerUnavailable(RuntimeError):
    """The Tier-2 redactor could not process a field (model outage / backpressure).

    Raised (NOT returned) so the barrier node distinguishes an outage — which
    triggers egress-fail-closed (E3: hold the content, do not forward raw) — from
    a clean "no PHI found" pass. Never let this bubble as a raw value.
    """


@dataclass
class RedactedView:
    """The result of a Tier-2 redaction pass over one free-text field.

    Attributes:
        text: the redacted content — free-text PHI replaced by typed tokens
            `⟦AEGR:{nonce}:NAME⟧` etc. The raw is discarded (never held here).
        redacted: provenance flag — True once a redaction pass ran over this field
            (the cheap first-line check the audit writer keys on, §5.3 point 3). A
            field WITHOUT this flag is dropped from any log/persist
            (`RawContentBlockedFromLog`).
        found_classes: the PHI classes the pass tokenized (for metrics/trail); NOT
            the raw values (I-1 — no raw retained anywhere).
    """

    text: Optional[str]
    redacted: bool = True
    found_classes: List[str] = field(default_factory=list)


class Tier2Redactor(Protocol):
    """The free-text PHI redactor contract (server side of §4.1).

    An implementation reads a free-text field, replaces PHI with typed tokens, and
    returns a :class:`RedactedView` with the raw discarded. The production form
    (stage 3) is a warm, distilled ONNX/Presidio microservice; the stage-2 form is
    :class:`ReferenceNerRedactor` (stdlib-only, deterministic).
    """

    def redact(self, text: str, *, nonce: Optional[str], tenant_id: str) -> RedactedView:
        ...


class ReferenceNerRedactor:
    """A deterministic, stdlib-only reference PHI redactor (stage-2 stub).

    NOT the production model — it is a small pattern set that proves the barrier,
    the redacted-view provenance, and the NO-RAW invariant hermetically (no AWS, no
    model download). Stage 3 swaps in the served ONNX/Presidio client behind the
    same :class:`Tier2Redactor` interface without touching the barrier node.

    It catches the *free-text* Safe-Harbor shapes Tier-1's structured matchers do
    not: a proper-name pair ("John Smith"), a prose street address, and a small
    clinical-condition lexicon. Recall is deliberately partial — the whole point of
    §5.3.3 is that the persist-gate re-scan (a STRONGER, INDEPENDENT detector)
    catches what this misses; a gate that re-ran THIS redactor would be circular
    (F3).
    """

    # A run of 2+ TitleCase tokens → a personal NAME. GREEDY over the run so
    # "John Smith" is one token, not a partial. Conservative on the trigger (needs
    # ≥2 TitleCase words); the gate re-scan is the backstop for what it misses.
    _NAME = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b")
    # Prose street address: "<number> <Street words> <suffix>".
    _ADDRESS = re.compile(
        r"\b\d{1,5}\s+([A-Z][a-z]+\s+){1,3}"
        r"(Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr)\b"
    )
    _CONDITIONS = (
        "diabetes", "hypertension", "asthma", "cancer", "hiv",
        "depression", "schizophrenia", "pregnancy",
    )

    def redact(self, text: str, *, nonce: Optional[str], tenant_id: str) -> RedactedView:
        if text is None:
            return RedactedView(text=text, redacted=True, found_classes=[])
        found: List[str] = []
        out = text

        def _tok(kind: str) -> str:
            found.append(kind)
            # Mirror the Tier-1 sentinel grammar so downstream reads it as a marker.
            return f"⟦AEGR:{nonce}:{kind}⟧" if nonce else f"⟦AEGR:{kind}⟧"

        out = self._ADDRESS.sub(lambda _m: _tok("ADDRESS"), out)
        out = self._NAME.sub(lambda _m: _tok("NAME"), out)
        for cond in self._CONDITIONS:
            pat = re.compile(rf"\b{re.escape(cond)}\b", re.IGNORECASE)
            if pat.search(out):
                out = pat.sub(lambda _m: _tok("CONDITION"), out)
        # De-dup for the trail; the raw values are NEVER retained (I-1).
        return RedactedView(text=out, redacted=True, found_classes=sorted(set(found)))


class PhiNerClient:
    """The client the DAG barrier node calls (§4.1).

    Wraps a :class:`Tier2Redactor` (the stage-2 reference stub by default; a served
    client in stage 3). Owns the free-text-field contract :meth:`redact_free_text`
    and translates a redactor failure into :class:`NerUnavailable` so the barrier
    node can fail closed on egress.
    """

    def __init__(self, redactor: Optional[Tier2Redactor] = None) -> None:
        self._redactor: Tier2Redactor = redactor or ReferenceNerRedactor()

    def redact_free_text(
        self, text: Optional[str], *, nonce: Optional[str], tenant_id: str
    ) -> RedactedView:
        """Redact the surviving free-text PHI in one field (server side of §4.1).

        Returns a :class:`RedactedView` (raw discarded). A None/empty field is a
        no-op redacted view (nothing to scrub, still flagged so it may persist).
        Any redactor exception is re-raised as :class:`NerUnavailable` so the caller
        fails closed on egress — NEVER forwards/persists the raw value.
        """
        if text is None or text == "":
            return RedactedView(text=text, redacted=True, found_classes=[])
        try:
            return self._redactor.redact(text, nonce=nonce, tenant_id=tenant_id)
        except NerUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 — any failure is an outage, fail closed
            raise NerUnavailable(f"Tier-2 NER redaction failed: {exc}") from exc


# ============================================================================
# Persist-gate detector (E4.2 / LLD 29 §5.3.3, §6.3) — the STRONGER INDEPENDENT
# detector that admits a record to ANY persisting store. It is NOT the flag and
# NOT the Tier-2 primary re-run (that would be circular — F3). Stage-2 ships an
# INTERFACE + an independent stub; a wired Comprehend-Medical-gate-only mode is a
# flagged, off-by-default deploy-stage option with counsel sign-off (§247), NOT
# wired here (a subprocessor boundary).
# ============================================================================

# Strip a genuine post-redaction sentinel token BEFORE re-scanning so the gate does
# not flag its own redaction output as a residual.
_SENTINEL = re.compile(r"⟦AEGR:[^⟧]*⟧")


class GateDetector(Protocol):
    """The persist-gate admission detector (§5.3.3, F2/F3).

    Contract: :meth:`find_residual` re-scans the WHOLE would-be-persisted record
    text (payload + reason + winning_source + detector_outcomes, joined by the
    caller) and returns the residual identifier CLASSES it still finds — empty iff
    the record is safe to persist. It MUST be independent of, and at least as
    sensitive as, the Tier-2 primary; re-running the primary redactor as the gate
    is FORBIDDEN (circular).
    """

    def find_residual(self, text: str) -> List[str]:
        ...


class IndependentGateDetector:
    """A stronger, INDEPENDENT residual-identifier detector (stage-2 stub).

    Independent of :class:`ReferenceNerRedactor` by construction: it scans by a
    DIFFERENT method (broad structured-identifier shapes + an untokenized-name
    heuristic), NOT by re-running the primary's pattern set. This is what makes the
    gate a real gate and not a rubber stamp (F3) — it can catch a residual the
    Tier-2 primary missed (a raw SSN/email/phone/card the edge somehow let through,
    or an honorific-led name the primary's bare TitleCase-pair rule did not fire
    on).

    Stage 3 replaces this with the heavy offline reclassifier (§6.6). The
    Comprehend-Medical-gate-only alternative stays a flagged, off-by-default deploy
    option (§247) — NOT wired here (subprocessor boundary).
    """

    _RESIDUAL_PATTERNS: Dict[str, "re.Pattern[str]"] = {
        "SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "EMAIL": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
        "PHONE": re.compile(r"\b\d{3}[.\-\s]\d{3}[.\-\s]\d{4}\b"),
        "CARD": re.compile(r"\b(?:\d[ -]?){13,19}\b"),
        # A residual proper-name run the primary did not tokenize (independent
        # heuristic: an honorific-led name, which the primary's bare TitleCase-pair
        # rule does not target).
        "NAME": re.compile(r"\b(?:Mr|Mrs|Ms|Dr|Miss)\.?\s+[A-Z][a-z]+\b"),
    }

    def find_residual(self, text: str) -> List[str]:
        if not text:
            return []
        scanned = _SENTINEL.sub(" ", text)
        hits = [cls for cls, pat in self._RESIDUAL_PATTERNS.items() if pat.search(scanned)]
        return sorted(set(hits))


# Process-wide singletons (mirrors the audit_logger / signal_store pattern).
_phi_ner_client: Optional[PhiNerClient] = None
_gate_detector: Optional[GateDetector] = None


def get_phi_ner_client() -> PhiNerClient:
    global _phi_ner_client
    if _phi_ner_client is None:
        _phi_ner_client = PhiNerClient()
    return _phi_ner_client


def get_gate_detector() -> GateDetector:
    global _gate_detector
    if _gate_detector is None:
        _gate_detector = IndependentGateDetector()
    return _gate_detector
