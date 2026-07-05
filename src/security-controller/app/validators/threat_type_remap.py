"""Threat-type vocabulary remap — WS-F Milestone F7 (lld/35 §7, Appendix B).

The old `_extract_threat_type` uppercased the FIRST `llm.<x>` tag by YAML order.
That was:
  * YAML-order-fragile — a rule with TWO `llm.` tags derives a `threat_type` a
    reformat/sort silently flips (zero test coverage historically);
  * off-enum — `llm.sql_injection` -> `SQL_INJECTION`, `llm.authorization_bypass`
    -> `AUTHORIZATION_BYPASS`, `llm.prompt_leakage` -> `PROMPT_LEAKAGE` are NOT in
    the canonical 8-value enum the ML classifier / console / trail key on.

This module derives a STABLE, in-enum `threat_type`:
  1. collect the rule's `llm.<x>` tags (order-independent);
  2. pick the single primary tag deterministically (by _TAG_PRIORITY, not YAML
     order) so a tag reorder can never flip the derived value;
  3. remap that tag's uppercased form to the 8-value enum via _REMAP.

This is a LABELED change (it alters the DENY reason + console grouping), so it is
applied AFTER the §5 equivalence-frozen migration — never folded into F1.

The canonical enum is `ml_classifier_schema.THREAT_TYPES` (the join key the whole
pipeline shares). We import it rather than restate it — a drift there is a single
source of truth, not a copy.
"""
from __future__ import annotations

import logging
from typing import Dict, List

from app.validators.ml_classifier_schema import THREAT_TYPES

logger = logging.getLogger(__name__)

VALID_THREAT_TYPES = frozenset(THREAT_TYPES)

# Off-enum llm.<x> tag (uppercased) -> canonical 8-value enum (lld/35 §7 table).
# A tag whose uppercased form is ALREADY in the enum needs no entry here.
_REMAP: Dict[str, str] = {
    "PROMPT_LEAKAGE": "SYSTEM_EXTRACTION",       # sigma-llm-008 system_prompt_extraction
    "AUTHORIZATION_BYPASS": "PRIVILEGE_ESCALATION",  # sigma-llm-007 privilege_escalation
    "SQL_INJECTION": "OTHER",                     # sigma-llm-005 sql_injection (no dedicated enum slot)
    # already-valid tags map to themselves via the enum check below:
    #   PROMPT_INJECTION, PII_EXPOSURE, DATA_THEFT, JAILBREAK_ATTEMPT
    # Non-enumerated attack-intent tags on relocated/inert rules (F8) still resolve
    # to OTHER via the fall-through so no rule ever derives UNKNOWN_THREAT.
    "JAILBREAK": "JAILBREAK_ATTEMPT",            # bare `llm.jailbreak` -> canonical form
    "BYPASS": "JAILBREAK_ATTEMPT",               # secondary jailbreak intent
    "FINANCIAL_FRAUD": "OTHER",                  # sigma-llm-006 (relocated F8)
    "DOS": "OTHER",                              # sigma-llm-009 (relocated F8)
    "PARAMETER_TAMPERING": "OTHER",              # sigma-llm-011 (relocated F8)
    "UNAUTHORIZED_ACCESS": "PRIVILEGE_ESCALATION",  # sigma-llm-010 (inert)
}

# Deterministic primary-tag priority — the tie-break when a rule carries >1 `llm.`
# tag, so the derived type is stable regardless of YAML order (F7.2). Lower rank =
# higher priority. A tag not listed falls to the end, ordered lexically, so the
# result is still deterministic.
_TAG_PRIORITY: List[str] = [
    "prompt_injection",
    "jailbreak",
    "authorization_bypass",
    "prompt_leakage",
    "sql_injection",
    "data_theft",
    "pii_exposure",
    "bypass",
]


def _llm_tags(tags: List[str]) -> List[str]:
    return [t[len("llm."):] for t in tags if isinstance(t, str) and t.startswith("llm.")]


def primary_llm_tag(tags: List[str]) -> str:
    """Pick the single primary `llm.<x>` tag deterministically (order-independent).

    Returns the tag suffix (without the `llm.` prefix), or "" if the rule has no
    `llm.` tag. Determinism is the whole point: a tag reorder must not flip it."""
    llm = _llm_tags(tags)
    if not llm:
        return ""

    def rank(tag: str) -> tuple:
        try:
            return (0, _TAG_PRIORITY.index(tag))
        except ValueError:
            return (1, 0)

    # Primary priority, then lexical for anything unlisted — fully deterministic.
    return sorted(llm, key=lambda t: (rank(t), t))[0]


def derive_threat_type(tags: List[str]) -> str:
    """Derive the canonical 8-value `threat_type` for a rule's tags (F7).

    Stable under tag reorder; always in the 8-value enum (never UNKNOWN_THREAT — an
    off-enum tag falls through to OTHER). A rule with NO `llm.` tag also resolves to
    OTHER (a corpus-lint gap F4 flags separately, but the runtime value stays
    in-enum so downstream consumers never see a stray string)."""
    primary = primary_llm_tag(tags)
    if not primary:
        # No llm.* tag — F4 corpus-lint flags this; runtime stays in-enum.
        return "OTHER"
    upper = primary.upper()
    if upper in _REMAP:
        return _REMAP[upper]
    if upper in VALID_THREAT_TYPES:
        return upper
    # Any unknown off-enum tag -> OTHER (never UNKNOWN_THREAT).
    logger.info("prompt-signature threat-type: unmapped tag %r -> OTHER", primary)
    return "OTHER"


def llm_tag_count(tags: List[str]) -> int:
    """Count of distinct `llm.<x>` tags (F4/F7 lint: exactly one primary tag)."""
    return len(_llm_tags(tags))
