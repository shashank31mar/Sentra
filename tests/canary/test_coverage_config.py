"""WS-J J-cov — regression guard for the P0-2 coverage gate CONFIG (lld/38 §4.3).

WHY THIS FILE EXISTS
--------------------
The P0-2 "all code logic covered" gate is only meaningful if it actually MEASURES
something. Two ways it silently becomes vacuous — both are real bugs this file guards:

  1. The path form ``--cov=app/api`` (instead of the dotted ``--cov=app.api.routes``)
     resolves against repo-root cwd, misses ``PYTHONPATH=src/security-controller``,
     and coverage reports **0.00%** while every test still passes — a green gate that
     measures nothing. (This is exactly the defect independent verification caught
     2026-07-05.)
  2. Someone points ``[run] source`` at the whole ``app/api``+``app/services`` tree,
     which includes background schedulers/scanners/purge code no HTTP request reaches,
     dragging the number to a meaningless ~37% and inviting an unreachable floor.

These tests read the committed ``.coveragerc`` and assert its scope is the dotted
request-path module set with a real positive floor — so a regression to the path form
or a broadened/emptied scope FAILS here, in the fast PR-gate/inprocess suite. This
test is pure stdlib + pytest (no ``app``/SDK import) so it also runs in the lean set.
"""
from __future__ import annotations

import configparser
import os

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_COVERAGERC = os.path.join(_HERE, ".coveragerc")

# The request-path modules the black-box canary is responsible for exercising
# (lld/38 §4.3). Kept here as the contract; a drift between this and .coveragerc
# fails test_coveragerc_scope_is_exactly_the_request_path_modules.
_EXPECTED_SOURCE = {
    "app.api.routes",
    "app.api.tenancy_routes",
    "app.api.models",
    "app.combiners",
    "app.services.validation_service",
}


def _read_coveragerc() -> configparser.ConfigParser:
    assert os.path.exists(_COVERAGERC), (
        ".coveragerc is missing — the P0-2 coverage gate has no scope config"
    )
    cp = configparser.ConfigParser()
    cp.read(_COVERAGERC)
    return cp


def _source_modules(cp: configparser.ConfigParser) -> list[str]:
    raw = cp["run"]["source"]
    return [line.strip() for line in raw.splitlines() if line.strip()]


def test_coveragerc_exists_and_has_run_and_report_sections():
    cp = _read_coveragerc()
    assert cp.has_section("run"), ".coveragerc needs a [run] section with source="
    assert cp.has_section("report"), ".coveragerc needs a [report] section with fail_under="


def test_coverage_source_is_dotted_module_form_not_paths():
    """The bug that shipped 0.00%: path form instead of dotted-module form."""
    cp = _read_coveragerc()
    for mod in _source_modules(cp):
        assert "/" not in mod, (
            f"coverage source {mod!r} is a PATH — use the dotted-module form "
            f"(e.g. app.api.routes). The path form silently measures 0.00% under "
            f"PYTHONPATH=src/security-controller."
        )
        assert "." in mod, f"coverage source {mod!r} is not a dotted module"


def test_coveragerc_scope_is_exactly_the_request_path_modules():
    """Guard against broadening to the whole app/api+app/services tree (→ ~37%,
    unreachable floor) or narrowing away a request-path module."""
    cp = _read_coveragerc()
    assert set(_source_modules(cp)) == _EXPECTED_SOURCE, (
        "coverage scope drifted from the request-path module set. Broadening to the "
        "whole app/api+app/services tree pulls in scheduler/scanner/purge code no HTTP "
        "request reaches (meaningless ~37%); narrowing drops a module the canary drives."
    )


def test_coverage_floor_is_a_real_positive_number():
    cp = _read_coveragerc()
    floor = int(cp["report"]["fail_under"])
    assert floor >= 1, "fail_under must be a real positive floor, not 0/absent (a 0 floor is a non-gate)"
    # Sanity ceiling: a black-box canary over the request path cannot honestly hit ~85%
    # (auth-gated + deferred-WS branches are unreachable in Increment 1). If someone sets
    # a bar this high the gate will falsely fail; flag it so the number stays honest.
    assert floor <= 70, (
        f"fail_under={floor} is implausibly high for a black-box request-path canary "
        f"(OIDC-gated + deferred-WS branches are unreachable in Increment 1). Keep it an "
        f"honest target-to-tune (~50 today), raised as those increments land."
    )


@pytest.mark.requires_live  # excluded from the lean live container; runs in PR-gate/inprocess
def test_coverage_actually_measures_nonzero_when_run():
    """End-to-end anti-vacuous guard: run coverage over one canary test with the
    committed .coveragerc and assert it records >0 measured statements for the scoped
    modules. Catches the 0.00% regression that a static config check alone could miss
    (e.g. a PYTHONPATH/import-root mismatch). Marked so it does not run in the lean
    live container (it shells a subprocess); it runs in the inprocess/PR-gate suite."""
    import subprocess
    import sys

    repo_root = os.path.abspath(os.path.join(_HERE, "..", ".."))
    env = dict(os.environ)
    env.pop("AWS_PROFILE", None)
    env.update(
        AWS_ACCESS_KEY_ID="testing",
        AWS_SECRET_ACCESS_KEY="testing",
        AWS_DEFAULT_REGION="us-east-1",
        PYTHONPATH=os.path.join(repo_root, "src", "security-controller"),
    )
    proc = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            "tests/canary/test_j2_validate.py", "-q", "-p", "no:cacheprovider",
            "-m", "not requires_live and not pr_gate_only",
            "--cov", "--cov-config=tests/canary/.coveragerc",
            "--cov-report=term-missing",
        ],
        cwd=repo_root, env=env, capture_output=True, text=True, timeout=300,
    )
    out = proc.stdout + proc.stderr
    assert "TOTAL" in out, f"no coverage report produced:\n{out[-2000:]}"
    # The vacuous-gate signature is 'Total coverage: 0.00%' / a TOTAL row at 0%.
    assert "0.00%" not in out and "Total coverage: 0" not in out, (
        f"coverage measured 0% — the gate is vacuous (path-vs-dotted or import-root bug):\n{out[-2000:]}"
    )
