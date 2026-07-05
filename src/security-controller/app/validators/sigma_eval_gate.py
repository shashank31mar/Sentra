"""Offline, hermetic prompt-signature eval / CI gate — WS-F Milestone F4 (lld/35 §10).

Runs the ENGINE (the compiled dialect, NOT the substring oracle) over two committed
JSONL corpora and computes per-rule + overall recall & FP-rate, then applies the
LOCKED thresholds (§10.3). Hermetic by construction: it loads fixture `.jsonl` and
rule YAML directly from disk — NO live DDB/S3 (non-hermetic is flaky), never touches
the runtime request path, runs per-PR.

Gate (§10.3):
  (a) migration-equivalence diffs   == 0        (enforced by the F1 test suite)
  (b) FP-rate                        <= 0.5%     valid ONLY at |benign| >= 200,
                                                  else INSUFFICIENT (not pass)
  (c) recall                         >= 85%      (secondary; never traded vs FP)
  (d) corpus-lint                    clean       (UNKNOWN_THREAT == 0, exactly one
                                                  primary llm.<x> tag/rule,
                                                  threat_type stable under tag reorder)
  (e) |re ReDoS smoke                ok          (every |re under a wall-clock budget)

The runner never imports boto3 — it builds SigmaRule objects straight from YAML via a
lightweight parser reused from the engine, so it is safe to run in a bare CI process.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from app.validators.sigma_dialect import compile_selections, looks_catastrophic, parse_condition
from app.validators.threat_type_remap import derive_threat_type, llm_tag_count

BENIGN_FLOOR = 200
FP_RATE_MAX = 0.005      # 0.5%
RECALL_MIN = 0.85        # 85%
REDOS_BUDGET_SECONDS = 0.5  # per-|re wall-clock ceiling for the smoke test


@dataclass
class Rule:
    """A minimal loaded rule for the offline gate (no boto3)."""
    id: str
    title: str
    threat_type: str
    tags: List[str]
    selections: dict
    condition: object

    def evaluate(self, text: str) -> bool:
        sel_bools = {n: s.matches(text) for n, s in self.selections.items()}
        return self.condition.evaluate(sel_bools)


def load_rule(rule_data: dict) -> Rule:
    """Build a Rule from parsed YAML (the same compile path the engine uses)."""
    detection = rule_data.get("detection", {})
    selections, _ = compile_selections(detection)
    condition = parse_condition(detection.get("condition"))
    tags = rule_data.get("tags", []) or []
    return Rule(
        id=rule_data.get("id", "unknown"),
        title=rule_data.get("title", "Unknown Rule"),
        threat_type=derive_threat_type(tags),
        tags=tags,
        selections=selections,
        condition=condition,
    )


def read_jsonl(path: str) -> List[dict]:
    out = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


@dataclass
class EvalReport:
    recall: float
    fp_rate: float
    benign_count: int
    attack_count: int
    misclassified: List[str] = field(default_factory=list)
    per_rule_recall: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    # Attacks caught (DENYed) but by a rule whose derived threat_type differs from the
    # corpus line's `expected_threat_type`. These still count toward recall (the gate's
    # contract is DENY-vs-ALLOW, §10.3(c)), but a mislabel is surfaced here so it never
    # hides silently behind a passing recall number — see run_eval's docstring.
    threat_type_mismatch: List[str] = field(default_factory=list)


def run_eval(rules: List[Rule], attacks: List[dict], benign: List[dict]) -> EvalReport:
    """Run the engine over both corpora. `attacks` MUST DENY, `benign` MUST ALLOW.

    Each attack line: {"text": ..., "label": "attack", "expected_threat_type": ...}
    Each benign line: {"text": ..., "label": "benign"}.

    Recall is intentionally DENY-vs-ALLOW: an attack is "caught" if ANY rule's
    condition matches it (§10.3(c) — the gate proves we BLOCK the attack, not that we
    label it perfectly). But an attack matched by a rule whose derived `threat_type`
    disagrees with the line's declared `expected_threat_type` is recorded in
    `report.threat_type_mismatch`, so a mislabel (the exact class the F7 remap fixes)
    is observable in the report instead of being masked by a green recall. A caller
    that wants to gate on labeling can inspect that list; the recall gate does not.
    """
    caught = 0
    misclassified: List[str] = []
    mismatch: List[str] = []
    per_rule: Dict[str, Tuple[int, int]] = {}

    def _first_match(text: str) -> Optional[Rule]:
        for r in rules:
            if r.evaluate(text):
                return r
        return None

    for item in attacks:
        text = item["text"]
        hit = _first_match(text)
        if hit is not None:
            caught += 1
            expected = item.get("expected_threat_type")
            # Only compare when the corpus line declares an expectation.
            if expected is not None and hit.threat_type != expected:
                mismatch.append(
                    f"threat_type mismatch: {text!r} caught by rule {hit.id} "
                    f"(derived {hit.threat_type}) but expected {expected}"
                )
        else:
            misclassified.append(f"FN(attack not caught): {text!r}")

    false_positives = 0
    for item in benign:
        text = item["text"]
        hit = _first_match(text)
        if hit is not None:
            false_positives += 1
            per_rule[hit.id] = (per_rule.get(hit.id, (0, 0))[0], per_rule.get(hit.id, (0, 0))[1] + 1)
            misclassified.append(f"FP(benign DENYed): {text!r} -> rule {hit.id}")

    recall = caught / len(attacks) if attacks else 0.0
    fp_rate = false_positives / len(benign) if benign else 0.0
    return EvalReport(
        recall=recall,
        fp_rate=fp_rate,
        benign_count=len(benign),
        attack_count=len(attacks),
        misclassified=misclassified,
        per_rule_recall=per_rule,
        threat_type_mismatch=mismatch,
    )


@dataclass
class GateResult:
    passed: bool
    insufficient: bool
    reasons: List[str] = field(default_factory=list)
    report: Optional[EvalReport] = None


def corpus_lint(rules: List[Rule]) -> List[str]:
    """Corpus-lint (§10.3 d): every rule carries EXACTLY ONE primary llm.<x> tag,
    and every derived threat_type is in the 8-value enum. Returns the list of lint
    failures (empty == clean).

    Note on the "UNKNOWN_THREAT == 0" wording in §10.3/§7: the runtime deliberately
    keeps the derived `threat_type` in-enum — a tagless rule falls through to OTHER
    in `derive_threat_type`, it NEVER emits the stray string "UNKNOWN_THREAT" (so
    downstream consoles/trail never see one). Linting `threat_type == "UNKNOWN_THREAT"`
    would therefore be a DEAD branch that can never fire. The corpus defect the gate
    must actually catch — "a rule with no primary llm.<x> tag" — is detected at its
    SOURCE (zero `llm.` tags) via `llm_tag_count(...) == 0`, which is exactly the
    condition that would have produced UNKNOWN_THREAT before the F7 in-enum fallthrough.
    A tagless rule silently deriving OTHER instead of being flagged is the fail-open
    the §10.3(d) lint exists to close.
    """
    from app.validators.threat_type_remap import VALID_THREAT_TYPES

    failures: List[str] = []
    for r in rules:
        tag_count = llm_tag_count(r.tags)
        if tag_count == 0:
            # The tagless-rule defect (the intent behind "UNKNOWN_THREAT == 0"):
            # no primary llm.<x> tag → threat_type is an untyped OTHER guess.
            failures.append(
                f"{r.id}: no primary llm.<x> tag — threat_type is an untyped OTHER guess"
            )
        elif tag_count > 1:
            failures.append(f"{r.id}: >1 llm.<x> tag ({r.tags}) — de-dup to one primary")
        if r.threat_type not in VALID_THREAT_TYPES:
            failures.append(f"{r.id}: threat_type {r.threat_type} not in 8-value enum")
    return failures


# Adversarial probes are LENGTH-BOUNDED so a catastrophic-backtracking pattern's
# blow-up is finite-but-measurable. stdlib `re` holds the GIL for the whole C-level
# search (so a worker-thread + join timeout cannot interrupt it), and SIGALRM is
# main-thread-only / non-portable — so instead we bound the WORK: a length-24
# non-matching run of the catastrophic character makes `(a+)+$` take well over a
# 0.5s budget yet still terminate in a couple of seconds, which the inline timer
# then flags. A linear pattern finishes these probes in microseconds.
_REDOS_PROBES = [
    "a" * 24 + "!",     # catastrophic blow-up on nested-quantifier `(a+)+$`
    "a" * 30,
    "!@#" * 40,
]


def redos_smoke(rules: List[Rule], budget_seconds: float = REDOS_BUDGET_SECONDS) -> List[str]:
    """Run every `|re` matcher against LENGTH-BOUNDED worst-case adversarial inputs
    under a per-pattern wall-clock budget. Returns the patterns that blew the budget.
    Offline/CI only — never the hot path. (The load-time ReDoS heuristic already
    skips these structurally; this smoke test is the belt to that suspenders.)"""
    over_budget: List[str] = []
    for r in rules:
        for sel in r.selections.values():
            for m in sel.matchers:
                if m.modifier != "re":
                    continue
                for probe in _REDOS_PROBES:
                    t = time.perf_counter()
                    m.pattern.search(probe)
                    if (time.perf_counter() - t) > budget_seconds:
                        over_budget.append(f"{r.id}: |re {m.raw!r} > {budget_seconds}s")
                        break
    return over_budget


def run_gate(
    rules: List[Rule],
    attacks: List[dict],
    benign: List[dict],
    *,
    equivalence_diffs: int = 0,
) -> GateResult:
    """Apply the LOCKED thresholds (§10.3). Returns a GateResult; `insufficient` is
    True (NOT pass) when |benign| < 200 (the FP gate is meaningless below the floor).
    """
    reasons: List[str] = []
    report = run_eval(rules, attacks, benign)

    # (a) equivalence diffs must be zero.
    if equivalence_diffs != 0:
        reasons.append(f"equivalence diffs = {equivalence_diffs} (must be 0)")

    # (d) corpus-lint.
    lint = corpus_lint(rules)
    reasons.extend(lint)

    # (e) ReDoS smoke.
    over = redos_smoke(rules)
    reasons.extend(over)

    # (c) recall (secondary).
    if report.recall < RECALL_MIN:
        reasons.append(
            f"recall {report.recall:.2%} < {RECALL_MIN:.0%}"
        )

    # (b) FP gate — ONLY valid at |benign| >= 200, else INSUFFICIENT.
    if report.benign_count < BENIGN_FLOOR:
        return GateResult(
            passed=False,
            insufficient=True,
            reasons=[
                f"INSUFFICIENT: |benign|={report.benign_count} < {BENIGN_FLOOR} "
                f"(FP gate not evaluable)"
            ] + reasons,
            report=report,
        )
    if report.fp_rate > FP_RATE_MAX:
        reasons.append(f"FP-rate {report.fp_rate:.2%} > {FP_RATE_MAX:.1%}")

    return GateResult(
        passed=(len(reasons) == 0),
        insufficient=False,
        reasons=reasons,
        report=report,
    )
