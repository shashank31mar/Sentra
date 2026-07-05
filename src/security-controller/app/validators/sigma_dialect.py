"""Prompt-signature-rule dialect: matchers, condition AST, and the load-time
parser/validator — WS-F (lld/35 §4, Appendix A).

This is the stdlib-only (LLD 23 §1.2) closed dialect the SigmaEngine compiles at
LOAD and evaluates on the HOT PATH. It replaces the old flat-substring matcher
with an additive data model:

    Selection  — one `detection:` selection (a set of CompiledMatchers + require_all)
    Condition  — the parsed boolean AST over selection names (never eval())
    CompiledMatcher — one compiled `re.Pattern` + its raw string + modifier

Closed dialect (lld/35 §4.2/§4.3, Appendix A EBNF):
  * matchers:    {contains, re, all}
  * conditions:  {<sel>, 1 of them, all of them, and, or, not, (…)}  (precedence not > and > or)

Fail-secure invariants owned here (lld/35 §6d):
  * `re.escape` on every `|contains` / `|all` value  — so a metachar-bearing literal
    (`[SYSTEM]`, `<|im_end|>`, `\\x`) stays a literal instead of becoming a char class
    or an uncompilable escape (silent fail-OPEN).
  * `|re` is the ONLY untrusted-regex surface — validated as external data:
    compile-fail -> skip; ReDoS structural heuristic -> skip; length cap -> skip.
  * matcher-count caps (per rule / per ruleset) — a fat-corpus DoS is a HARD reject.
  * NO `eval()` on condition text — the condition parses to a pure boolean AST and
    evaluation is a fold over the per-selection bool map.
  * An undefined-selection reference FAILS the rule load (never silently False — a
    typo'd selection that "passes" is a disabled rule nobody notices = fail-open).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ---- §6d load-time caps / bounds (defaults; overridable via config) --------- #
DEFAULT_RE_MAX_LEN = 512          # |re source length cap
DEFAULT_MATCHERS_PER_RULE = 200   # HARD cap per rule
DEFAULT_MATCHERS_PER_RULESET = 5000  # HARD cap per ruleset

# The closed modifier set (lld/35 §4.2). A field ending in one of these is a
# supported matcher; any other |modifier (e.g. |lt, |gte, |startswith) is NOT part
# of the prompt-signature dialect — those are param/session predicates that belong
# to the Cedar/abuse surface (§8) and are IGNORED here (they produce zero matchers,
# which is exactly why the 4 param-rules are inert — bug-for-bug preserved).
_CONTAINS = "contains"
_RE = "re"
_ALL = "all"
CLOSED_MODIFIERS = frozenset({_CONTAINS, _RE, _ALL})


class DialectError(ValueError):
    """A rule violates the closed dialect and must be skipped at LOAD.

    Fail-secure: one bad rule is skipped (log + continue); it never silently
    evaluates, and it never fails the whole ruleset.
    """


class MatcherCapExceeded(DialectError):
    """A rule/ruleset exceeds the matcher-count cap — a fat-corpus DoS guard."""


# ============================================================
# Compiled matcher + selection
# ============================================================

@dataclass
class CompiledMatcher:
    """One compiled matcher. `raw` is retained for logging/console/trail; `pattern`
    is the compiled re.Pattern actually matched on the hot path via `.search()`."""
    raw: str
    pattern: "re.Pattern[str]"
    modifier: str  # one of CLOSED_MODIFIERS


@dataclass
class Selection:
    """A `detection:` selection: a set of matchers + the require_all flag.

    `require_all` is True for a `|all` matcher (every value must hit -> selection
    true); False (the default, `|contains`/`|re`) means ANY value hitting makes the
    selection true — the old any-hit semantics.
    """
    name: str
    matchers: List[CompiledMatcher] = field(default_factory=list)
    require_all: bool = False

    def matches(self, text: str) -> bool:
        if not self.matchers:
            return False
        if self.require_all:
            return all(m.pattern.search(text) is not None for m in self.matchers)
        return any(m.pattern.search(text) is not None for m in self.matchers)


# ============================================================
# Condition boolean AST (no eval())
# ============================================================

class Node:
    """Base boolean-AST node. `eval` folds over the per-selection bool map."""
    def eval(self, sel_bools: Dict[str, bool]) -> bool:  # pragma: no cover - abstract
        raise NotImplementedError

    def refs(self) -> Set[str]:
        """Selection names this node references (for undefined-selection check)."""
        return set()


@dataclass
class Ref(Node):
    name: str

    def eval(self, sel_bools: Dict[str, bool]) -> bool:
        # A referenced-but-absent selection is a load-time error (checked in
        # `validate_refs`); here it defaults False, but load rejects it first.
        return sel_bools.get(self.name, False)

    def refs(self) -> Set[str]:
        return {self.name}


@dataclass
class OneOfThem(Node):
    """`1 of them` — any defined selection is true."""
    def eval(self, sel_bools: Dict[str, bool]) -> bool:
        return any(sel_bools.values())


@dataclass
class AllOfThem(Node):
    """`all of them` — every defined selection is true."""
    def eval(self, sel_bools: Dict[str, bool]) -> bool:
        return bool(sel_bools) and all(sel_bools.values())


@dataclass
class Not(Node):
    child: Node

    def eval(self, sel_bools: Dict[str, bool]) -> bool:
        return not self.child.eval(sel_bools)

    def refs(self) -> Set[str]:
        return self.child.refs()


@dataclass
class And(Node):
    left: Node
    right: Node

    def eval(self, sel_bools: Dict[str, bool]) -> bool:
        return self.left.eval(sel_bools) and self.right.eval(sel_bools)

    def refs(self) -> Set[str]:
        return self.left.refs() | self.right.refs()


@dataclass
class Or(Node):
    left: Node
    right: Node

    def eval(self, sel_bools: Dict[str, bool]) -> bool:
        return self.left.eval(sel_bools) or self.right.eval(sel_bools)

    def refs(self) -> Set[str]:
        return self.left.refs() | self.right.refs()


@dataclass
class Condition:
    """The parsed, LOAD-time boolean AST + the raw string for logging."""
    raw: str
    ast: Node

    def evaluate(self, sel_bools: Dict[str, bool]) -> bool:
        return self.ast.eval(sel_bools)

    def refs(self) -> Set[str]:
        return self.ast.refs()


# ============================================================
# Condition parser (recursive-descent, no eval())
#   condition := or_expr
#   or_expr   := and_expr ("or" and_expr)*
#   and_expr  := not_expr ("and" not_expr)*
#   not_expr  := "not" not_expr | primary
#   primary   := "(" or_expr ")" | "1 of them" | "all of them" | <selection-name>
# Precedence: not > and > or  (lld/35 Appendix A EBNF).
# ============================================================

_TOKEN_RE = re.compile(r"\(|\)|[A-Za-z_][A-Za-z0-9_.*]*|\d+")


def _tokenize(condition: str) -> List[str]:
    """Split a condition into words / parens. Rejects any char outside the closed
    grammar so a Python-code smuggle (`__import__('os')`) is a PARSE ERROR, never
    executed. Multi-word terminals (`1 of them`, `all of them`) are folded here."""
    # Reject characters that are not part of the closed grammar. Only letters,
    # digits, underscore, dot, star, parens and whitespace are legal. Anything else
    # (quotes, brackets, operators like +/(), commas) is a smuggle attempt.
    if re.search(r"[^A-Za-z0-9_.*()\s]", condition):
        raise DialectError(
            f"condition contains illegal characters (closed grammar only): {condition!r}"
        )
    words = _TOKEN_RE.findall(condition)
    # Fold the two multi-word terminals into single sentinel tokens.
    folded: List[str] = []
    i = 0
    lowered = [w.lower() for w in words]
    while i < len(words):
        if lowered[i] == "1" and lowered[i + 1: i + 3] == ["of", "them"]:
            folded.append("__ONE_OF_THEM__")
            i += 3
        elif lowered[i] == "all" and lowered[i + 1: i + 3] == ["of", "them"]:
            folded.append("__ALL_OF_THEM__")
            i += 3
        else:
            folded.append(words[i])
            i += 1
    return folded


class _Parser:
    def __init__(self, tokens: List[str]):
        self._tokens = tokens
        self._pos = 0

    def _peek(self) -> Optional[str]:
        return self._tokens[self._pos] if self._pos < len(self._tokens) else None

    def _next(self) -> str:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def parse(self) -> Node:
        if not self._tokens:
            raise DialectError("empty condition")
        node = self._or_expr()
        if self._pos != len(self._tokens):
            raise DialectError(f"trailing tokens in condition near {self._peek()!r}")
        return node

    def _or_expr(self) -> Node:
        node = self._and_expr()
        while (self._peek() or "").lower() == "or":
            self._next()
            node = Or(node, self._and_expr())
        return node

    def _and_expr(self) -> Node:
        node = self._not_expr()
        while (self._peek() or "").lower() == "and":
            self._next()
            node = And(node, self._not_expr())
        return node

    def _not_expr(self) -> Node:
        if (self._peek() or "").lower() == "not":
            self._next()
            return Not(self._not_expr())
        return self._primary()

    def _primary(self) -> Node:
        tok = self._peek()
        if tok is None:
            raise DialectError("unexpected end of condition")
        if tok == "(":
            self._next()
            node = self._or_expr()
            if self._peek() != ")":
                raise DialectError("unbalanced parenthesis in condition")
            self._next()
            return node
        if tok == "__ONE_OF_THEM__":
            self._next()
            return OneOfThem()
        if tok == "__ALL_OF_THEM__":
            self._next()
            return AllOfThem()
        low = tok.lower()
        if low in ("and", "or", "not"):
            raise DialectError(f"unexpected operator {tok!r} in condition")
        # A bare selection-name reference.
        self._next()
        return Ref(tok)


def parse_condition(condition: Optional[str]) -> Condition:
    """Parse a condition string to a boolean AST.

    A missing/empty condition defaults to `1 of them` (the old any-hit default) so
    a rule without an explicit condition keeps the substring engine's semantics.
    Raises DialectError (-> the rule is skipped at LOAD) on any grammar violation or
    a code-smuggle attempt. NEVER eval()s.
    """
    raw = (condition or "").strip()
    if not raw:
        return Condition(raw="1 of them", ast=OneOfThem())
    ast = _Parser(_tokenize(raw)).parse()
    return Condition(raw=raw, ast=ast)


# ============================================================
# ReDoS structural heuristic (stdlib-only; no runtime step budget)
# ============================================================

# Catastrophic-backtracking shapes: a quantified group that is itself quantified
# ((a+)+, (a*)*, (a+)*, (.*)+ …) or an alternation-in-repetition ((a|a)+). stdlib
# `re` has no step budget (LLD 23 forecloses RE2), so we reject the structure at
# LOAD rather than let a pathological pattern hang every request behind it.
_NESTED_QUANTIFIER = re.compile(r"\([^)]*[+*][^)]*\)\s*[+*]")
_ALT_IN_REPETITION = re.compile(r"\([^)]*\|[^)]*\)\s*[+*]")


def looks_catastrophic(pattern_src: str) -> bool:
    """Best-effort structural heuristic for catastrophic backtracking.

    Deliberately conservative: it can only ever REJECT (skip a rule), never admit —
    so a false positive costs one dropped `|re` rule (flagged via the gap list),
    while a missed catastrophic pattern is still bounded by the F4 ReDoS smoke-test
    + the empty-`|re`-surface-at-launch fact (lld/35 §6d/§11)."""
    return bool(
        _NESTED_QUANTIFIER.search(pattern_src)
        or _ALT_IN_REPETITION.search(pattern_src)
    )


# ============================================================
# Selection parsing (the load-time matcher compiler)
# ============================================================

def compile_selections(
    detection: Dict,
    *,
    re_max_len: int = DEFAULT_RE_MAX_LEN,
    matchers_per_rule: int = DEFAULT_MATCHERS_PER_RULE,
) -> Tuple[Dict[str, Selection], int]:
    """Compile a rule's `detection:` block into {selection_name: Selection}.

    Returns (selections, matcher_count). Raises MatcherCapExceeded if the rule's
    matcher count exceeds `matchers_per_rule` (a HARD reject — the fat-corpus DoS
    guard, lld/35 §6d). A single uncompilable / ReDoS-suspect / over-long `|re` is
    SKIPPED (log + continue), not fatal — one bad matcher never fails the rest.

    Non-dialect predicates (`parameters.*`, `session.*`, `tool_name`, `|lt`, `|gte`
    …) produce ZERO matchers — that is exactly why the 4 param-rules are inert, and
    the migration preserves that bug-for-bug (§5.4). Such a selection is still
    REGISTERED (defined-but-always-False) so a condition Ref to it is legal.
    """
    selections: Dict[str, Selection] = {}
    matcher_count = 0

    for sel_name, sel_data in detection.items():
        if sel_name == "condition":
            continue
        if not isinstance(sel_data, dict):
            continue

        selection = Selection(name=sel_name)
        for field_key, values in sel_data.items():
            modifier = _modifier_of(field_key)
            if modifier not in CLOSED_MODIFIERS:
                # Not a dialect matcher (param/session/equality predicate) — inert.
                continue
            if not isinstance(values, list):
                values = [values]

            if modifier == _ALL:
                selection.require_all = True

            for value in values:
                if value is None:
                    continue
                value = str(value)
                compiled = _compile_matcher(value, modifier, re_max_len=re_max_len)
                if compiled is None:
                    continue  # bad |re — skipped + logged
                selection.matchers.append(compiled)
                matcher_count += 1
                if matcher_count > matchers_per_rule:
                    raise MatcherCapExceeded(
                        f"rule exceeds per-rule matcher cap "
                        f"({matchers_per_rule}); rejected (fat-corpus DoS guard)"
                    )

        # Register EVERY declared selection (even a zero-matcher param/session-only
        # one) so a condition Ref to it resolves to defined-but-False, not undefined.
        # A zero-matcher selection can never make its Ref true -> inert (which is why
        # the 4 param-rules are inert), but a condition that legitimately names it
        # (e.g. `exfiltration_patterns or large_query_limit`, the F8.4 split rule) is
        # NOT a load failure. A truly UNDEFINED name (a typo not in `detection`) is
        # what the caller's undefined-ref check rejects.
        selections[sel_name] = selection

    return selections, matcher_count


def _modifier_of(field_key: str) -> str:
    """Return the trailing `|modifier` of a detection field, or "" if none."""
    if "|" in field_key:
        return field_key.rsplit("|", 1)[1].strip().lower()
    return ""


def _compile_matcher(
    value: str, modifier: str, *, re_max_len: int
) -> Optional[CompiledMatcher]:
    """Compile one matcher value. Returns None (skip + log) on an invalid `|re`.

    `|contains` / `|all`: the value is a LITERAL — `re.escape`d so a metachar-bearing
    string survives (M2 fail-secure). `|re`: the value is UNTRUSTED external regex —
    length-capped, ReDoS-heuristic'd, compile-guarded (§6d)."""
    if modifier in (_CONTAINS, _ALL):
        # MANDATORY re.escape — the whole M2 fail-secure guard.
        return CompiledMatcher(
            raw=value,
            pattern=re.compile(re.escape(value), re.IGNORECASE),
            modifier=modifier,
        )

    # modifier == _RE — untrusted external data (lld/35 §6d).
    if len(value) > re_max_len:
        logger.warning(
            "prompt-signature |re skipped: exceeds %d-char cap (len=%d)",
            re_max_len, len(value),
        )
        return None
    if looks_catastrophic(value):
        logger.warning(
            "prompt-signature |re skipped: ReDoS structural heuristic tripped: %r",
            value,
        )
        return None
    try:
        pattern = re.compile(value, re.IGNORECASE)
    except re.error as e:
        logger.warning("prompt-signature |re skipped: uncompilable %r: %s", value, e)
        return None
    return CompiledMatcher(raw=value, pattern=pattern, modifier=_RE)
