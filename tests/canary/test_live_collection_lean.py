"""WS-J FIX-2 (FINDING 1) — the lean-live-collection regression guard.

The gap integration-sentinel found: the hourly LIVE container (docker/canary/
Dockerfile) installs ONLY httpx/boto3/pytest/pytest-cov — NO fastapi, NO pydantic,
NO aegion_guard SDK. If a test module collected in live mode does a module-LEVEL
import of app.* / aegion_guard / fastapi / pydantic / moto, the WHOLE suite errors
AT COLLECTION before any scenario runs → emit_run_metrics never fires → ZERO
ChecksPassed/ChecksFailed → the ChecksFailed alarm (TreatMissingData.BREACHING)
fires PERMANENTLY. The hermetic PR-gate never caught it because its venv HAS those
deps.

This test reproduces conftest.py's CANARY_TARGET=="live" ``collect_ignore`` logic and
asserts the actually-live-collected modules (test_all_routes.py + test_metrics_live.py)
statically import ONLY the lean allowlist {httpx, boto3, pytest, canary.*, stdlib}. It
FAILS the moment someone adds an app-importing test that would be collected live.

Deliberately PURE (stdlib + pytest only): this module itself must be lean, or it would
be the very leak it guards against. It never imports app / the SDK / fastapi / pydantic
— it STATIC-PARSES source with ``ast``, it does not execute the target modules.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Set

import pytest

_CANARY_DIR = Path(__file__).resolve().parent

# The lean container's non-stdlib runtime deps (docker/canary/Dockerfile RUN pip).
# A live-collected module may import ONLY these third-party roots + the canary package
# itself + the stdlib. fastapi/pydantic/aegion_guard/moto/app are NOT installed there.
# J8 (§5C): the canary image now also carries Playwright + headless Chromium (the
# console UI sweep + hosted-UI login run in the SAME hourly container), so `playwright`
# joins the lean allowlist. The console module still `importorskip`s it so a browserless
# run (the hermetic PR gate, or a future lean edition without the browser) SKIP-collects
# rather than errors — belt-and-suspenders on top of the allowlist.
_LEAN_THIRD_PARTY = frozenset({"httpx", "boto3", "botocore", "pytest", "_pytest", "playwright"})
_CANARY_ROOTS = frozenset({"canary"})
# The heavy roots that MUST NOT appear at module level in a live-collected module.
_FORBIDDEN_LIVE_ROOTS = frozenset({"app", "aegion_guard", "fastapi", "pydantic", "moto"})


def _live_collect_ignore() -> Set[str]:
    """conftest.py's ACTUAL CANARY_TARGET=='live' collect_ignore, via the SAME pure
    helper the runtime branch calls (conftest._live_collect_ignore). Calling the real
    helper — not a re-implementation — means neutering the runtime branch or the helper
    is caught here (no decoupled shadow copy that could pass while the wiring is broken)."""
    from canary.conftest import _live_collect_ignore as real_helper  # conftest is lean

    return set(real_helper(_CANARY_DIR))


def _live_collected_modules() -> Set[str]:
    """The test_*.py modules pytest WOULD collect in live mode: on disk minus ignored."""
    on_disk = {p.name for p in _CANARY_DIR.glob("test_*.py")}
    return on_disk - _live_collect_ignore()


def _top_level_import_roots(py_file: Path) -> Set[str]:
    """The set of top-level (module-scope, not function-local) imported root packages
    in ``py_file`` — the ones that run AT COLLECTION when pytest imports the module.
    Imports nested inside a function/class body are ignored (they only run when that
    code path executes, which the live entrypoint never does for a skipped scenario)."""
    tree = ast.parse(py_file.read_text(), filename=str(py_file))
    roots: Set[str] = set()
    for node in tree.body:  # module-scope statements ONLY (no recursion into defs)
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:  # skip relative imports (none here)
                roots.add(node.module.split(".")[0])
    return roots


_LIVE_COLLECTED_EXPECTED = {
    "test_all_routes.py",           # P0-1 all-route positive/negative sweep (httpx)
    "test_metrics_live.py",         # requires_live CloudWatch metric checks (httpx)
    "test_oidc_routes_live.py",     # J8.4 no-identity 401 sweep of the oidc lane (httpx)
    "test_console_authed_oidc.py",  # J8.1-J8.4 Playwright login + authed legs (browser)
}


def test_live_collected_set_is_exactly_the_black_box_scenarios():
    """The live-collected set is EXACTLY the pure-httpx black-box scenario modules + the
    J8 console modules (httpx oidc sweep + the Playwright console lane). A widening
    (someone drops a module out of the ignore list) trips this."""
    assert _live_collected_modules() == _LIVE_COLLECTED_EXPECTED


def _load_conftest_under(target: str):
    """Import a FRESH copy of canary/conftest.py with CANARY_TARGET=target set, in an
    isolated module object, and return it. conftest is lean at module level (its app.*
    imports are all deferred into fixtures), so this is safe in the lean env — it
    executes the REAL module-level collect_ignore branch under the given target."""
    import importlib.util
    import os as _os

    conftest_path = _CANARY_DIR / "conftest.py"
    prev = _os.environ.get("CANARY_TARGET")
    _os.environ["CANARY_TARGET"] = target
    try:
        spec = importlib.util.spec_from_file_location(
            f"_canary_conftest_probe_{target}", conftest_path
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod
    finally:
        if prev is None:
            _os.environ.pop("CANARY_TARGET", None)
        else:
            _os.environ["CANARY_TARGET"] = prev


def test_conftest_wires_live_collect_ignore_and_leaves_inprocess_full():
    """The runtime WIRING guard: load conftest.py under CANARY_TARGET=live and assert
    its module-level ``collect_ignore`` actually IGNORES the heavy modules (populated,
    not empty), and under inprocess it stays EMPTY (the 193-pass PR gate must collect
    everything). Neutering the ``if ... == 'live'`` branch — the exact regression that
    reintroduces the false-alarm bug — FAILS here. The decoupled design assertions
    above check intent; THIS checks the real conftest wiring."""
    expected_ignore = {
        p.name for p in _CANARY_DIR.glob("test_*.py")
    } - _LIVE_COLLECTED_EXPECTED

    live_conftest = _load_conftest_under("live")
    assert set(live_conftest.collect_ignore) == expected_ignore, (
        "conftest live-mode collect_ignore is not wired to the live-ignore set "
        f"(got {sorted(live_conftest.collect_ignore)}) — the lean container would "
        "collect heavy app-importing modules and blank the alarms"
    )

    inprocess_conftest = _load_conftest_under("inprocess")
    assert list(inprocess_conftest.collect_ignore) == [], (
        "inprocess collect_ignore must be EMPTY — the PR gate collects the full suite"
    )


def test_live_collected_modules_import_only_the_lean_allowlist():
    """Every module collected against a live target imports ONLY {httpx, boto3, pytest,
    canary.*, stdlib} at module scope — nothing the lean container cannot satisfy. If a
    future test that imports app.*/aegion_guard/fastapi/pydantic gets added to the live
    set, this FAILS in the PR gate instead of blanking the alarms in prod."""
    stdlib = set(sys.stdlib_module_names) | {"__future__"}
    allowed = _LEAN_THIRD_PARTY | _CANARY_ROOTS | stdlib

    offenders = {}
    for name in sorted(_live_collected_modules()):
        roots = _top_level_import_roots(_CANARY_DIR / name)
        bad = roots - allowed
        if bad:
            offenders[name] = sorted(bad)
    assert not offenders, (
        "live-collected canary modules import non-lean deps at module scope (would "
        f"ModuleNotFoundError at collection in the lean container): {offenders}"
    )


def test_no_live_collected_module_imports_a_forbidden_heavy_root():
    """The direct, explicit form of the guard: NO live-collected module top-level
    imports app / aegion_guard / fastapi / pydantic / moto (the roots the lean image
    lacks). Distinct from the allowlist test so the intent reads unambiguously."""
    hits = {}
    for name in sorted(_live_collected_modules()):
        roots = _top_level_import_roots(_CANARY_DIR / name)
        forbidden = roots & _FORBIDDEN_LIVE_ROOTS
        if forbidden:
            hits[name] = sorted(forbidden)
    assert not hits, f"live-collected modules import forbidden heavy roots: {hits}"


def test_entrypoint_import_chain_is_lean():
    """entrypoint.expected_check_count() imports canary.route_manifest, and main()
    imports canary.reporting_plugin — both run in the lean container. Neither (nor
    entrypoint itself) may top-level import a forbidden heavy root, or ``python -m
    canary.entrypoint`` itself would crash before it could run/emit anything."""
    for name in ("entrypoint.py", "route_manifest.py", "reporting_plugin.py", "scenarios.py"):
        roots = _top_level_import_roots(_CANARY_DIR / name)
        forbidden = roots & _FORBIDDEN_LIVE_ROOTS
        assert not forbidden, (
            f"canary/{name} top-level imports {sorted(forbidden)} — breaks the lean "
            "container's entrypoint import chain"
        )


def test_this_guard_is_itself_lean():
    """Self-check: this regression test must not itself import a heavy root at module
    scope (else it is the leak it guards against and could never run in a lean edition)."""
    roots = _top_level_import_roots(Path(__file__).resolve())
    forbidden = roots & _FORBIDDEN_LIVE_ROOTS
    assert not forbidden, f"this guard imports forbidden heavy roots: {sorted(forbidden)}"


def test_dockerfile_copies_the_integration_conftest_the_canary_conftest_loads():
    """REGRESSION (a real deploy bug): the canary conftest.py loads
    ../integration/conftest.py by FILE PATH at collection. If the lean Dockerfile does
    not COPY tests/integration/ into the image, collection dies with FileNotFoundError
    → the whole suite errors (exit 4, zero checks) in prod, while the hermetic PR-gate
    passes (it has the file on disk). Assert the Dockerfile COPYs tests/integration/."""
    dockerfile = (_CANARY_DIR.parents[1] / "docker" / "canary" / "Dockerfile").read_text()
    copy_lines = [ln.strip() for ln in dockerfile.splitlines() if ln.strip().startswith("COPY ")]
    # canary conftest loads tests/integration/conftest.py — the image must carry it.
    assert any("tests/integration/" in ln for ln in copy_lines), (
        "docker/canary/Dockerfile must COPY tests/integration/ — the canary conftest "
        "loads tests/integration/conftest.py by file path at collection; without it the "
        "live container errors at collection (exit 4, zero checks)."
    )
    # And the canary suite itself must be copied (sanity).
    assert any("tests/canary/" in ln for ln in copy_lines)


def test_dockerfile_has_playwright_chromium_for_j8():
    """J8.0 — the canary image must carry Playwright + headless Chromium (the console UI
    sweep + hosted-UI login run in the hourly container). Assert the pip install includes
    playwright AND `playwright install ... chromium` runs. (The --no-sandbox/headless=new
    launch flags + SEC-10 no-trace are enforced in conftest._ConsoleSession, asserted by
    test_console_launch_flags_are_fargate_safe.)"""
    dockerfile = (_CANARY_DIR.parents[1] / "docker" / "canary" / "Dockerfile").read_text()
    assert "playwright" in dockerfile, (
        "docker/canary/Dockerfile must pip-install playwright — the J8 console lane needs it"
    )
    assert "playwright install" in dockerfile and "chromium" in dockerfile, (
        "docker/canary/Dockerfile must run `playwright install ... chromium` — pip alone "
        "does not fetch the browser binary"
    )


def test_console_launch_flags_are_fargate_safe():
    """J8.0/SEC-10 — Chromium under Fargate has no user namespaces, so the console session
    MUST launch with --no-sandbox, and MUST NOT capture a trace/screenshot (prod cookies +
    authed DOM). Static-check the conftest source (no browser import needed)."""
    src = (_CANARY_DIR / "conftest.py").read_text()
    assert "--no-sandbox" in src, "console Chromium must launch --no-sandbox under Fargate"
    # SEC-10: no capture CALL in the console session. Match the actual API *invocations*
    # (kwarg assignment / method call), not the bare word — a descriptive comment that
    # names the prohibition ("no record_video / no tracing") must NOT trip this.
    for forbidden in ("record_video=", "record_video_dir=", ".screenshot(",
                      "tracing.start(", ".start_tracing("):
        assert forbidden not in src, (
            f"SEC-10 violated: console session must never invoke {forbidden!r} "
            f"(real prod cookies + authed DOM must not hit an artifact)"
        )


def test_pythonunbuffered_set_so_prod_logs_flush():
    """REGRESSION: a short-lived Fargate task with block-buffered stdout can exit before
    the awslogs driver flushes → an EMPTY CloudWatch stream (a live monitor with no
    readable output). Assert PYTHONUNBUFFERED is set in the canary Dockerfile."""
    dockerfile = (_CANARY_DIR.parents[1] / "docker" / "canary" / "Dockerfile").read_text()
    assert "PYTHONUNBUFFERED=1" in dockerfile, (
        "docker/canary/Dockerfile must set PYTHONUNBUFFERED=1 or prod canary logs may "
        "never reach CloudWatch (short task exits before the log driver flushes)."
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
