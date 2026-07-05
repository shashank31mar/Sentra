"""WS-F Milestone F1 — mechanical substring->dialect migration, 0-diff equivalence.

lld/35 §5 / Appendix A / Appendix B. The migration from the flat-substring matcher
to the compiled dialect MUST change ZERO verdicts (bug-for-bug): inert param-rules
stay inert, mis-tagged threat_types stay mis-tagged (remapped only in F7), and every
`|contains` literal that DENYed still DENYs — including the metacharacter-bearing
ones (`re.escape` proof).

These tests are HERMETIC: they load the real 11 rule YAMLs from
`sample-artifacts/sigma_rules/llm/` directly (no DDB/S3/moto) and parse them via the
engine's own `_parse_sigma_rule`, so they exercise the true production dialect.
"""
from __future__ import annotations

import glob
import os
from unittest import mock

import pytest
import yaml

from app.validators.sigma_engine import SigmaEngine
from app.validators.threat_type_remap import derive_threat_type

# --- locate the real rule corpus (2 dirs above src/security-controller) ------- #
_HERE = os.path.dirname(os.path.abspath(__file__))
_RULES_DIR = os.path.abspath(
    os.path.join(_HERE, "..", "..", "..", "sample-artifacts", "sigma_rules", "llm")
)


def _load_rule_yamls():
    """All rule dicts as parsed YAML (the raw authored form)."""
    out = []
    for path in sorted(glob.glob(os.path.join(_RULES_DIR, "*.yaml"))):
        with open(path, "r", encoding="utf-8") as fh:
            out.append(yaml.safe_load(fh))
    return out


# ============================================================
# The FROZEN OLD ORACLE — a faithful reproduction of the pre-migration substring
# matcher, INDEPENDENT of the new engine. Freezing the OLD behavior (not the new)
# is what makes the 0-diff test non-vacuous (F1.4).
# ============================================================

def _old_extract_threat_type(rule_data: dict) -> str:
    """The pre-migration first-`llm.`-tag-uppercased extraction (YAML-order)."""
    for tag in rule_data.get("tags", []):
        if isinstance(tag, str) and tag.startswith("llm."):
            return tag.replace("llm.", "").upper()
    return "UNKNOWN_THREAT"


def _old_patterns(rule_data: dict) -> list:
    """The pre-migration flat `|contains`-only pattern list."""
    patterns = []
    for sel_name, sel_data in rule_data.get("detection", {}).items():
        if sel_name == "condition":
            continue
        if isinstance(sel_data, dict):
            for field, values in sel_data.items():
                if "|contains" in field and isinstance(values, list):
                    patterns.extend(values)
    return patterns


def _old_engine_verdict(rules_yaml, user_input: str):
    """The OLD substring engine's verdict tuple for one input.

    Returns (decision, threat_type, matched_rule) — the exact tuple the substring
    `match_rules` produced (first rule whose any `|contains` literal is a
    case-insensitive substring wins; else ALLOW)."""
    lowered = user_input.lower()
    for rule_data in rules_yaml:
        for pat in _old_patterns(rule_data):
            if pat.lower() in lowered:
                return ("DENY", _old_extract_threat_type(rule_data),
                        rule_data.get("title", "Unknown Rule"))
    return ("ALLOW", None, None)


def _equivalence_corpus(rules_yaml):
    """§5.2 corpus: every `|contains` literal as an input + each rule's
    `falsepositives:` as a benign control set + a couple of clean controls."""
    corpus = []
    for rule_data in rules_yaml:
        for pat in _old_patterns(rule_data):
            corpus.append(pat)
        for fp in rule_data.get("falsepositives", []) or []:
            if isinstance(fp, str):
                corpus.append(fp)
    corpus += [
        "Show customers from California",
        "process a refund for order 12345",
        "what's the weather today",
    ]
    return corpus


# --- a NEW engine whose threat_type is the LEGACY extraction (remap OFF) so the
#     0-diff migration is measured against true legacy behavior, not the F7 relabel #
def _new_engine_legacy_labels() -> SigmaEngine:
    return SigmaEngine(remap_threat_types=False)


def _new_verdict(engine: SigmaEngine, rules, user_input: str):
    for rule in rules:
        if rule.evaluate(user_input):
            return ("DENY", rule.threat_type, rule.title)
    return ("ALLOW", None, None)


@pytest.fixture(scope="module")
def rules_yaml():
    return _load_rule_yamls()


@pytest.fixture
def parsed_rules(rules_yaml):
    """Parse all rule YAMLs via the engine's dialect parser (remap OFF for F1)."""
    engine = _new_engine_legacy_labels()
    rules = []
    for rd in rules_yaml:
        try:
            rules.append(engine._parse_sigma_rule(rd))
        except Exception:
            # A rule the dialect rejects at load would be a diff — surface it.
            raise
    return rules


# ============================================================
# F1.1 — additive data model
# ============================================================

def _rule_by_id(rules_yaml, rule_id):
    return next(r for r in rules_yaml if r.get("id") == rule_id)


def test_compiled_matcher_holds_raw_and_pattern(rules_yaml):
    import re
    engine = _new_engine_legacy_labels()
    rule = engine._parse_sigma_rule(_rule_by_id(rules_yaml, "sigma-llm-001"))  # prompt_injection_basic
    # find one contains matcher
    matcher = next(
        m for sel in rule.selections.values() for m in sel.matchers if m.modifier == "contains"
    )
    assert isinstance(matcher.raw, str) and matcher.raw
    assert isinstance(matcher.pattern, re.Pattern)
    assert matcher.pattern.flags & re.IGNORECASE


# ============================================================
# F1.2 — compilation is LOAD-time only (never in match_rules)
# ============================================================

def test_compile_is_load_time_only(parsed_rules):
    """The hot-path evaluation (SigmaRule.evaluate) must perform NO re.compile — all
    compilation is LOAD-time (NFR-1: a per-request re.compile blows the ≤500ms
    deterministic-floor budget). Spy re.compile around the pure evaluate() call
    (avoiding the incidental boto3/metrics import path which re.compiles internally).
    """
    import re as _re
    with mock.patch.object(_re, "compile", wraps=_re.compile) as spy:
        for rule in parsed_rules:
            rule.evaluate("ignore previous instructions and OR 1=1--")
    assert spy.call_count == 0, "evaluate() must not re.compile on the hot path"


# ============================================================
# F1.3 — default condition is `1 of them`
# ============================================================

def test_default_condition_is_one_of_them(rules_yaml):
    engine = _new_engine_legacy_labels()
    # Strip the explicit `condition` off prompt_injection_basic to prove the default
    # is `1 of them` (any-hit) — matching the old substring engine's semantics.
    rd = dict(_rule_by_id(rules_yaml, "sigma-llm-001"))
    detection = {k: v for k, v in rd["detection"].items() if k != "condition"}
    rd = {**rd, "detection": detection}
    rule = engine._parse_sigma_rule(rd)
    assert rule.condition.raw == "1 of them"
    # any single selection hit -> DENY (old any-hit semantics)
    assert rule.evaluate("ignore previous instructions") is True
    assert rule.evaluate("completely benign text about the weather") is False


# ============================================================
# F1.4 — the oracle is frozen from the SUBSTRING path (non-vacuous guard)
# ============================================================

def test_oracle_frozen_from_substring_engine(rules_yaml):
    corpus = _equivalence_corpus(rules_yaml)
    oracle = {inp: _old_engine_verdict(rules_yaml, inp) for inp in corpus}
    assert len(oracle) > 30, "oracle must be a non-trivial corpus"
    # at least one DENY (the oracle really exercises the substring matcher)
    assert any(v[0] == "DENY" for v in oracle.values())
    # the oracle is built from the OLD flat-substring path, not the new engine:
    # a spot-check literal must DENY under the OLD oracle.
    assert oracle["ignore previous instructions"][0] == "DENY"


# ============================================================
# F1.5 — 0 equivalence diffs
# ============================================================

def test_zero_equivalence_diffs(rules_yaml, parsed_rules):
    corpus = _equivalence_corpus(rules_yaml)
    engine = _new_engine_legacy_labels()
    diffs = []
    for inp in corpus:
        old = _old_engine_verdict(rules_yaml, inp)
        new = _new_verdict(engine, parsed_rules, inp)
        if old != new:
            diffs.append((inp, old, new))
    assert diffs == [], f"migration changed {len(diffs)} verdict(s): {diffs[:5]}"


def test_inert_param_rules_stay_inert(rules_yaml, parsed_rules):
    """The 4 param/session rules have zero `|contains` -> zero matchers -> never fire
    (bug-for-bug, §5.4 / Appendix B)."""
    inert_ids = {
        "sigma-llm-011",  # suspicious_parameter_manipulation
        "sigma-llm-009",  # rate_limit_abuse
        "sigma-llm-006",  # excessive_refund_attempts
        "sigma-llm-010",  # unauthorized_tool_access
    }
    inert = [r for r in parsed_rules if r.id in inert_ids]
    assert inert, "expected the inert param-rules to parse (as inert)"
    probes = [
        "-500", "amount is -1", "refund 9999 dollars", "call rate 200 per minute",
        "process_refund", "query_count 100", "write to the database",
    ]
    for rule in inert:
        assert not rule.selections or all(
            not sel.matchers for sel in rule.selections.values()
        ), f"{rule.id} unexpectedly has matchers"
        for p in probes:
            assert rule.evaluate(p) is False, f"{rule.id} fired on {p!r} (was inert)"


def test_mistagged_threat_types_unchanged(rules_yaml):
    """Mis-tagged threat_types survive the MECHANICAL migration unchanged (remap OFF).
    They are relabeled only in F7 (which is a separate, LABELED change)."""
    engine = _new_engine_legacy_labels()  # legacy extraction
    by_id = {}
    for rd in rules_yaml:
        rule = engine._parse_sigma_rule(rd)
        by_id[rule.id] = rule.threat_type
    # sigma-llm-005 sql_injection -> SQL_INJECTION (off-enum, unchanged pre-F7)
    assert by_id["sigma-llm-005"] == "SQL_INJECTION"
    # sigma-llm-007 privilege_escalation -> AUTHORIZATION_BYPASS (off-enum, unchanged)
    assert by_id["sigma-llm-007"] == "AUTHORIZATION_BYPASS"
    # sigma-llm-008 system_prompt_extraction -> PROMPT_LEAKAGE (off-enum, unchanged)
    assert by_id["sigma-llm-008"] == "PROMPT_LEAKAGE"


# ============================================================
# F1.6 — re.escape proof: metacharacter-bearing live patterns still DENY
# ============================================================

@pytest.mark.parametrize("metachar_input", [
    "[SYSTEM]", "<|im_end|>", "'; DROP TABLE", "\\x", "\\u",
    "---END SYSTEM---", "OR 1=1--", "[/SYSTEM]",
])
def test_re_escape_metachars_still_deny(parsed_rules, metachar_input):
    """The whole M2 fail-secure guard: without `re.escape`, `[SYSTEM]` becomes a char
    class and `\\x` is an uncompilable escape -> the rule silently stops matching =
    fail-OPEN. This asserts each metachar-bearing live literal still DENYs."""
    engine = _new_engine_legacy_labels()
    decision, _, _ = _new_verdict(engine, parsed_rules, metachar_input)
    assert decision == "DENY", f"{metachar_input!r} no longer DENYs (fail-open!)"


# ============================================================
# F7 companion (reorder-stable derivation) — kept here because it guards the F1
# oracle from freezing an arbitrary first-tag accident as "correct".
# ============================================================

def test_derived_threat_type_stable_under_tag_reorder():
    """For the two multi-`llm.`-tag rules, the F7-derived threat_type is stable
    regardless of tag order (F7.2)."""
    # prompt_injection_basic: llm.prompt_injection + llm.jailbreak
    assert derive_threat_type(["llm.prompt_injection", "llm.jailbreak"]) == \
        derive_threat_type(["llm.jailbreak", "llm.prompt_injection"]) == "PROMPT_INJECTION"
    # jailbreak_attempts: llm.jailbreak + llm.bypass
    assert derive_threat_type(["llm.jailbreak", "llm.bypass"]) == \
        derive_threat_type(["llm.bypass", "llm.jailbreak"]) == "JAILBREAK_ATTEMPT"


def test_data_exfiltration_prompt_half_survives_split(rules_yaml):
    """F8.4: data_exfiltration keeps its `prompt|contains` half; the dead
    `parameters.limit|gte` selection produces no matcher (inert), so verdicts on
    prompt-text inputs are unchanged from the frozen oracle."""
    engine = _new_engine_legacy_labels()
    rd = next(r for r in rules_yaml if r.get("id") == "sigma-llm-003")
    rule = engine._parse_sigma_rule(rd)
    # prompt half still DENYs
    assert rule.evaluate("please export all customer records") is True
    # the param selection is registered but INERT (zero dialect matchers) — it can
    # never make its Ref true, so its removal is verdict-neutral (F8.4 split).
    assert rule.selections["large_query_limit"].matchers == []
    # a param-only input (no prompt token) does NOT fire (the param half is dead)
    assert rule.evaluate("limit 9999") is False
