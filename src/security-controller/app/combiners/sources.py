"""Signal-source taxonomy + default priorities — LLD 17 §4.

Single source of truth for the names every validator emits and the
priority each carries in the deny-overrides algorithm.

Validators reference `Source.SENTRA_SIGMA` (the constant) when constructing
ValidationResult so a future taxonomy rename touches one file.
"""

from __future__ import annotations

from typing import Final


class Source:
    """Frozen string constants for signal-source taxonomy.

    See LLD 17 §4 for the canonical list and naming rules.
    """

    # Sentra-internal validators
    SENTRA_TRUST: Final[str] = "sentra.trust"
    SENTRA_POLICY: Final[str] = "sentra.policy"
    SENTRA_SIGMA: Final[str] = "sentra.sigma"
    SENTRA_ML_CLASSIFIER: Final[str] = "sentra.ml_classifier"  # future
    SENTRA_CONTEXT: Final[str] = "sentra.context"
    SENTRA_ABUSE: Final[str] = "sentra.abuse"
    SENTRA_CROSS_AGENT: Final[str] = "sentra.cross_agent"
    SENTRA_COMBINED: Final[str] = "sentra.combined"

    # Tier-2 free-text PHI redaction barrier node (WS-E2 / LLD 29 §4.1, F1).
    # DELIBERATELY a NON-`sentra` name (LLD 31 line-185 standing rule: zero new
    # `sentra`-prefixed identifiers). The node redacts `content_text` in place and
    # returns ALLOW/ABSTAIN — it is NOT a verdict producer and never competes in
    # the deny-overrides combiner — but it MUST be a real registered source so the
    # WS-D decision trail can join on it (an unregistered source → default_priority
    # 0 → silently loses tie-breaks; register it explicitly below).
    REDACTION_NER: Final[str] = "redaction.ner"

    # Edge (cloud-native) — emitted by connectors, not the controller
    BEDROCK_GUARDRAIL: Final[str] = "bedrock_guardrail"
    AZURE_CONTENT_FILTER: Final[str] = "azure_content_filter"

    # Aggregates
    DASHBOARD_COMBINED: Final[str] = "dashboard.combined"


# Default priority table per LLD 17 §10.1. Centralized so the combiner
# can fall back to these when a Signal arrives without an explicit priority
# (e.g. an external POST that omits the field).
DEFAULT_PRIORITIES: dict[str, int] = {
    Source.SENTRA_TRUST: 90,
    Source.SENTRA_POLICY: 80,
    Source.SENTRA_SIGMA: 70,
    # ML strictly below sigma per LLD 19 §6.1: "sigma's reason is more
    # explainable than ml_classifier's. Compliance teams prefer the
    # deterministic match. When both fire, sigma's the headline reason."
    # With both at 70 the combiner tiebreak (priority → confidence) would
    # pick ML over sigma since sigma's confidence is typically None (==0.0)
    # and ML's is a real float. 65 keeps ML strictly between sigma (70) and
    # context (60) so winning_source is unambiguous when both fire.
    Source.SENTRA_ML_CLASSIFIER: 65,
    Source.SENTRA_CONTEXT: 60,
    Source.SENTRA_ABUSE: 50,
    Source.SENTRA_CROSS_AGENT: 50,
    Source.BEDROCK_GUARDRAIL: 40,
    Source.AZURE_CONTENT_FILTER: 40,
    # The redaction barrier never votes on the verdict (ALLOW/ABSTAIN only), so its
    # priority is not used to rank a DENY. Registered at 0 explicitly so the source
    # is a KNOWN taxonomy entry for the WS-D trail join (LLD 29 §4.1 FOOTGUN 2) —
    # not an unknown that falls through default_priority's 0.
    Source.REDACTION_NER: 0,
}


def default_priority(source: str) -> int:
    """Return the default priority for a source, or 0 for unknowns.

    Combiner uses priority=0 for unknown sources (LLD 17 §11) so a typo
    or new validator doesn't crash the pipeline — it just loses tie-breaks.
    """
    return DEFAULT_PRIORITIES.get(source, 0)


# ============================================================
# WS-D / LLD 33 — decision-trail coverage + display tables (§5.2, additive).
# All four live in this ONE existing file — one source of truth shared by the
# trail builder (build_trail / coverage_set), the scheduler-absent fallback, and
# the read API's display derivation. `trail_builder.py` never spells a `sentra.*`
# literal — it references the `Source.SENTRA_*` constants through these tables.
# ============================================================

# `_step_timings` label → coverage-set validator Source. Bridges the SHORT step
# labels (`"ml"`) to the DOTTED Source constants (`sentra.ml_classifier`).
STEP_LABEL_TO_SOURCE: dict[str, str] = {
    "trust": Source.SENTRA_TRUST,
    "policy": Source.SENTRA_POLICY,        # cedar OR legacy — SAME source
    "cross_agent": Source.SENTRA_CROSS_AGENT,
    "sigma": Source.SENTRA_SIGMA,
    "context": Source.SENTRA_CONTEXT,
    "abuse": Source.SENTRA_ABUSE,
    "ml": Source.SENTRA_ML_CLASSIFIER,
}
# DELIBERATELY UNMAPPED (plumbing, NOT detectors): session, pipeline, handle,
# abuse_policy_load, policy_fallback. `policy_fallback` is the legacy re-run after
# a Cedar abstain (validation_service.py:424) — the SAME logical policy layer, so
# mapping it would DOUBLE-COUNT policy as two invoked sources (§11.2). The
# rollout-era double-fire (`policy` + `policy_fallback` both in _step_timings)
# MUST collapse to a single `sentra.policy` invoked source (T-TRAIL-06).

# Request-phase coverage, in pipeline order — the WS-D coverage source TODAY, since
# WS-C's pure `coverage_sources(phase)` accessor is NOT YET BUILT (§5.1 / §13 gap #4).
STATIC_FALLBACK_ORDER: list[str] = [
    Source.SENTRA_TRUST,
    Source.SENTRA_POLICY,
    Source.SENTRA_CROSS_AGENT,
    Source.SENTRA_SIGMA,
    Source.SENTRA_CONTEXT,
    Source.SENTRA_ABUSE,
    Source.SENTRA_ML_CLASSIFIER,
]

# Raw source → human label (§9A.2.2). The raw source string stays the join key
# (DDB SK component + DenyOverrides tie-break); the API ADDS `display_name` on
# read, never stores it. `sentra.sigma → "Prompt-signature rules"` is the
# serverless narrative rename of "Sigma" — the RAW string stays `sentra.sigma` (a
# code rename would break the SK + the combiner join key). An unknown source falls
# through to its raw string via `.get(source, source)`, never crashes — so a
# future WS-L D-layer renders as its raw name until its label is added here.
SOURCE_DISPLAY_NAMES: dict[str, str] = {
    Source.SENTRA_TRUST: "Trust score",
    Source.SENTRA_POLICY: "Policy (Cedar)",
    Source.SENTRA_SIGMA: "Prompt-signature rules",
    Source.SENTRA_ML_CLASSIFIER: "ML classifier",
    Source.SENTRA_CONTEXT: "Context integrity",
    Source.SENTRA_ABUSE: "Abuse / rate",
    Source.SENTRA_CROSS_AGENT: "Cross-agent",
}

# Raw state → human label (§9A.2.2). The raw `state` stays the four-bucket
# discriminator; the API ADDS `state_label` on read.
STATE_DISPLAY_NAMES: dict[str, str] = {
    "ran": "Ran",
    "ran_abstain": "Ran — abstained",
    "ran_error": "Ran — error (fail-secure)",
    "not_run": "Not run",
}
