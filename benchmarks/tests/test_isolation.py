"""The three refusal paths, proven from a subprocess — the M1 exit gate.

LLD 41 §4.7 · WS-B B4.

Each case launches a real ``benchmarks/`` entry point and asserts **exit code 2**
plus the reason on stderr. In-process monkeypatching cannot prove "the first
executable statement" and cannot observe a ``SystemExit`` that fires before
argparse, so these are subprocess tests by construction — pinned by
:func:`test_all_three_use_subprocess_not_monkeypatch`.

**The footgun that makes or breaks this gate:** the live-credential case is only
passable because I3 asserts *before* I2 mutates. If someone "simplifies"
``enforce()`` by sentinelizing first, this test becomes unpassable. If you find
yourself relaxing it, the bug is in ``enforce()``'s ordering, not here.
"""
from __future__ import annotations

import inspect
import json
import subprocess
import sys

import pytest

from .conftest import REPO_ROOT, hermetic_subprocess_env

#: The entry point under test. WS-B owns a minimal one of its own rather than
#: depending on WS-A's ``run.py``; the contract asserted here — enforce() first,
#: exit 2 on refusal — is identical for every entry point under ``benchmarks/``.
ENTRY_POINT = [sys.executable, "-m", "benchmarks.core.isolation"]

PROD_BASE_URL = "https://iw3limi4k7.execute-api.us-east-1.amazonaws.com/prod"


def _run(args=(), env=None):
    return subprocess.run(
        ENTRY_POINT + list(args),
        cwd=str(REPO_ROOT),
        env=env if env is not None else hermetic_subprocess_env(),
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_unbadged_entrypoint_exits_2():
    """``AEGION_BENCHMARK`` unset in the subprocess env → exit 2, stderr names the
    badge."""
    env = hermetic_subprocess_env()
    env.pop("AEGION_BENCHMARK", None)

    result = _run(env=env)

    assert result.returncode == 2, result.stderr
    assert "unbadged" in result.stderr
    assert "AEGION_BENCHMARK" in result.stderr


def test_live_credentials_exit_2():
    """A fabricated live-looking credential injected into the environment the
    subprocess **starts with**, so I3's pre-mutation snapshot sees it."""
    env = hermetic_subprocess_env(
        AWS_ACCESS_KEY_ID="AKIAIOSFODNN7EXAMPLE",
        AWS_SECRET_ACCESS_KEY="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    )

    result = _run(env=env)

    assert result.returncode == 2, result.stderr
    assert "live AWS credentials present" in result.stderr


def test_prod_base_url_exits_2():
    """Badged, no credentials, ``--transport hosted --base-url <PROD_HOSTS
    entry>`` → exit 2."""
    result = _run(["--transport", "hosted", "--base-url", PROD_BASE_URL])

    assert result.returncode == 2, result.stderr
    assert "refusing to target production" in result.stderr


def test_badged_clean_run_exits_0():
    """The positive control. Without it, an ``enforce()`` that unconditionally
    exited 2 would satisfy all three refusal cases above — the gate has to prove
    that a clean shell gets through, and that the manifest block it prints is the
    six-field one."""
    result = _run()

    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    block = json.loads(result.stdout)
    assert block["tenant"] == "_benchmark"
    assert block["badge"] is True
    assert block["aws_credentials"] == "sentinel"
    assert block["metrics_publisher"] == "NullMetricsPublisher"
    assert block["audit_writer"] == "NullAuditWriter"


def test_non_prod_hosted_base_url_is_allowed():
    """I5 is a denylist, not a ban on hosted runs — a non-production endpoint
    passes, which is what makes the three refusals above meaningful."""
    result = _run(
        ["--transport", "hosted", "--base-url", "https://benchmark-engine.internal.test/v1"]
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["prod_target_check"] == "passed"


def test_all_three_use_subprocess_not_monkeypatch():
    """A lint-shaped assertion: the three refusal cases must launch a real
    process. An in-process test of the same three conditions would be a weaker
    claim wearing the same name."""
    source = inspect.getsource(sys.modules[__name__])
    for name in (
        "test_unbadged_entrypoint_exits_2",
        "test_live_credentials_exit_2",
        "test_prod_base_url_exits_2",
    ):
        body = inspect.getsource(globals()[name])
        assert "_run(" in body, f"{name} must launch the entry point in a subprocess"
        assert "monkeypatch" not in body, f"{name} must not monkeypatch in-process"
    assert "subprocess.run(" in source
