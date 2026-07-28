"""G4 / FR-14.1 — "a new benchmark = one adapter, zero core change", enforced.

LLD 41 §4.2 · WS-A A1 (task A2).

The extensibility claim is asserted mechanically rather than in prose: no
benchmark-specific identifier may appear in **executable** source under
``benchmarks/core/`` or ``benchmarks/rigs/``.

Why it is tokenizer-scoped, not a raw text scan
------------------------------------------------
A naive text scan fails immediately. An illustrative comment such as
``# "agentdojo" | "asb" — the registry key`` is a docstring *about* the seam, not
a *dependency on* a benchmark, and banning the word from comments would push
authors toward vaguer comments — a worse outcome than the leak the test exists to
catch. So COMMENT and STRING tokens are stripped with the stdlib tokenizer before
scanning, and a real leak — an identifier, an attribute, an ``if`` on a name —
survives as a NAME token.

The known residual, stated rather than hidden
----------------------------------------------
Stripping string literals means a **hard-coded string dispatch** (a registry
literally keyed ``{"agentdojo": factory}``, an ``if benchmark == "asb"``) is *not*
caught here — the benchmark name survives only as a STRING token, which this scan
removes. That residual is deliberate and is pinned by
:func:`test_scan_has_a_known_string_literal_residual` below so it stays a known
limit rather than folklore.

**This test is the cheap early warning, not the proof.** G4's real acceptance
criterion is the M4 zero-diff ``git diff`` over ``benchmarks/core/`` and
``benchmarks/rigs/`` when the second adapter lands — something a git diff proves
and no lint can. When this test fails, the fix is to move the leak into the
adapter, not to weaken the test.
"""
from __future__ import annotations

import io
import tokenize

import pytest

from .conftest import REPO_ROOT

#: Identifiers that name a specific benchmark or its internals. Substring match,
#: lower-cased — ``asb`` is short on purpose and would fire on a careless
#: identifier, which is the intended pressure.
BANNED = ("agentdojo", "asb", "pyopenagi", "toolsexecutor", "reactagentattack")

#: The directories the FR-14.1 claim is about: the shared core and the two rigs.
#: Adapters live under ``benchmarks/adapters/`` and are exempt by construction —
#: naming their own benchmark is their entire job.
SCANNED_GLOBS = ("core/*.py", "rigs/*.py")

#: Token types carrying literal text rather than executable structure. Python 3.12
#: tokenizes f-strings per PEP 701, so the literal segments arrive as
#: ``FSTRING_MIDDLE`` rather than ``STRING``; interpolated *expressions* still
#: arrive as NAME/OP and are therefore still scanned, which is what we want.
_LITERAL_TOKENS = frozenset(
    {tokenize.COMMENT, tokenize.STRING}
    | {
        getattr(tokenize, name)
        for name in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END")
        if hasattr(tokenize, name)
    }
)


def _code_only(source: str) -> str:
    """Source with COMMENT and STRING tokens removed.

    Tokens are joined with a space so two adjacent fragments can never
    concatenate into a false positive.
    """
    kept = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in _LITERAL_TOKENS:
            continue
        if token.string.strip():
            kept.append(token.string)
    return " ".join(kept)


def _scanned_files() -> list:
    paths = []
    for pattern in SCANNED_GLOBS:
        paths.extend(sorted((REPO_ROOT / "benchmarks").glob(pattern)))
    return [p for p in paths if p.name != "__init__.py"]


def test_core_has_no_benchmark_specific_identifiers():
    """No module under ``core/`` or ``rigs/`` names a benchmark in executable code."""
    paths = _scanned_files()
    assert paths, (
        "the scan found no source files under benchmarks/core or benchmarks/rigs — "
        "the assertions below would be vacuous"
    )

    for path in paths:
        with tokenize.open(str(path)) as handle:
            code = _code_only(handle.read()).lower()
        for token in BANNED:
            assert token not in code, (
                f"{path} names a specific benchmark in CODE: {token!r}. Move the "
                "leak into the adapter — do not weaken this test."
            )


def test_scan_strips_comments_and_docstrings_but_keeps_identifiers():
    """The discrimination the whole test rests on, proven both ways.

    Without this, ``_code_only`` returning the empty string for everything would
    make the scan above pass forever.
    """
    illustrative = '''
"""The registry key, e.g. agentdojo."""
# asb lands in the second wave
LABEL = "agentdojo"
'''
    assert "agentdojo" not in _code_only(illustrative)
    assert "asb" not in _code_only(illustrative)

    leaked = "from benchmarks.adapters.agentdojo import build\n"
    assert "agentdojo" in _code_only(leaked)

    branched = "def pick(name):\n    if name is agentdojo_default:\n        return 1\n"
    assert "agentdojo" in _code_only(branched)


def test_scan_has_a_known_string_literal_residual():
    """The documented limit: a hard-coded **string** dispatch is not caught here.

    Stripping string literals is the deliberate trade that keeps illustrative
    comments legal. The cost is that ``{"agentdojo": factory}`` and
    ``if benchmark == "asb"`` slip through this scan. They are covered instead by
    G4's real acceptance criterion — the M4 zero-diff ``git diff`` over
    ``benchmarks/core/`` and ``benchmarks/rigs/`` when the second adapter lands.

    This test exists so the residual is a *recorded* limit: if someone later
    tightens the scan to keep dict-key strings, this test fails and forces the
    docstring above to be updated with it.
    """
    residual = 'ADAPTERS = {"agentdojo": build}\n'
    assert "agentdojo" not in _code_only(residual)

    equality = 'if benchmark == "asb":\n    pass\n'
    assert "asb" not in _code_only(equality)


@pytest.mark.parametrize("token", BANNED)
def test_banned_tokens_are_lowercase(token):
    """The scan lower-cases the source, so an upper-cased entry here would never
    match — a silently dead ban is worse than no ban."""
    assert token == token.lower()
