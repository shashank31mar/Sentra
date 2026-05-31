"""Signal dataclass + JSON codec — LLD 17 §5.1.

A Signal is one validator's contribution to a /v1/validate decision.
It is the atomic row stored in DDB (sentra-validation-signals) and the
input/output of the combiner.

Design notes
------------
- frozen=True: signals are facts, not commands. Never mutated after construct.
- metadata defaults via field(default_factory=dict) so the mutable-default
  trap is avoided (Kiro P3).
- to_dict/from_dict are the round-trip codec used by both the writer
  (Python → DDB attrs) and the reader (DDB attrs → Python).
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Literal, Optional


Decision = Literal["ALLOW", "DENY"]


@dataclass(frozen=True)
class Signal:
    """One validator's verdict for a single /v1/validate call.

    Attributes:
        source: taxonomy string from LLD 17 §4 (e.g. "sentra.sigma",
            "bedrock_guardrail"). Lowercase, dot-separated.
        decision: "ALLOW" or "DENY". "ERROR" is not a Signal — it's a
            controller-level failure handled by ValidationService.
        reason: human-readable rationale. None for ALLOW signals that
            have nothing interesting to say.
        priority: combiner tie-breaker (LLD 17 §10.1). Higher wins among
            DENYs of equal confidence.
        confidence: 0.0-1.0 score. ML signals populate; regex leaves None.
            Used as the secondary tie-breaker after priority.
        threat_type / matched_rule / severity: optional categorical fields
            propagated to the audit row and the dashboard expander.
        metadata: source-specific extras. Dict by default — never None,
            to keep call sites from having to None-check.
    """

    source: str
    decision: Decision
    reason: Optional[str] = None
    priority: int = 0
    confidence: Optional[float] = None
    threat_type: Optional[str] = None
    matched_rule: Optional[str] = None
    severity: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to plain dict (HTTP responses, DDB attrs, JSON logs).

        None-valued fields are kept (the consumer can drop them if it
        cares about wire size). This matches the audit log's behavior
        and makes round-trips identity-equal.
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Signal":
        """Inverse of to_dict. Tolerates extra keys (forward-compat) and
        missing optional keys (backward-compat with older serializations)."""
        # Filter to known fields only so future schema additions in the
        # writer don't break older readers.
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        # metadata may serialize as None in some paths (e.g. old CW events);
        # normalize to {} so the dataclass invariant holds.
        if filtered.get("metadata") is None:
            filtered["metadata"] = {}
        return cls(**filtered)
