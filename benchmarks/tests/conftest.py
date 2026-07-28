"""Shared fixtures for the benchmark-harness test suite.

Deliberately imports **nothing** from ``app.*`` at module scope: several tests
here turn on whether the I4 substitution landed before the app modules that
construct AWS clients were imported, and a conftest that pulled them in first
would quietly make those tests vacuous. It only puts the PDP package root on
``sys.path`` — the same thing ``enforce()`` does — so the tests that legitimately
need ``app.utils.tenancy`` can import it themselves.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTROLLER_ROOT = REPO_ROOT / "src" / "security-controller"

for _path in (str(REPO_ROOT), str(CONTROLLER_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)


#: An environment in which ``enforce()`` reaches I2 cleanly: badged, no ambient
#: credential provider of any kind. ``AWS_CONFIG_FILE`` /
#: ``AWS_SHARED_CREDENTIALS_FILE`` are pointed at a path that does not exist and
#: IMDS is disabled, so I3's snapshot is hermetic on a developer laptop that has
#: a live ``sentra`` profile sitting in ``~/.aws/credentials``.
HERMETIC_ENV = {
    "AEGION_BENCHMARK": "1",
    "AWS_CONFIG_FILE": "/nonexistent/aegion-benchmark/config",
    "AWS_SHARED_CREDENTIALS_FILE": "/nonexistent/aegion-benchmark/credentials",
    "AWS_EC2_METADATA_DISABLED": "true",
    "AWS_DEFAULT_REGION": "us-east-1",
}

#: Variables that must not survive into a hermetic subprocess/test env.
AWS_CREDENTIAL_VARS = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_PROFILE",
    "AWS_ROLE_ARN",
    "AWS_WEB_IDENTITY_TOKEN_FILE",
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
    "AWS_CONTAINER_CREDENTIALS_FULL_URI",
)


def hermetic_subprocess_env(**overrides: str) -> dict:
    """A copy of the current environment scrubbed of every credential provider,
    plus :data:`HERMETIC_ENV`, plus the caller's overrides."""
    env = {k: v for k, v in os.environ.items() if k not in AWS_CREDENTIAL_VARS}
    env.update(HERMETIC_ENV)
    env.update(overrides)
    return env


@pytest.fixture
def hermetic_env(monkeypatch):
    """In-process equivalent of :func:`hermetic_subprocess_env`. ``monkeypatch``
    restores every variable at teardown."""
    for var in AWS_CREDENTIAL_VARS:
        monkeypatch.delenv(var, raising=False)
    for key, value in HERMETIC_ENV.items():
        monkeypatch.setenv(key, value)
    return monkeypatch


@pytest.fixture(autouse=True)
def _undo_process_wide_effects():
    """``enforce()`` mutates process-global state — the ``app.*`` class symbols
    and the tenant contextvar. ``monkeypatch`` cannot see either, so unwind them
    after every test; otherwise the first test to call ``enforce()`` leaves the
    whole session bound to ``_benchmark`` with the real publishers gone, and the
    tests that introspect the *real* classes silently introspect the null ones.
    """
    yield

    from benchmarks.core import isolation

    isolation.restore_substitutions()

    if "app.utils.tenancy" in sys.modules:
        tenancy = sys.modules["app.utils.tenancy"]
        if tenancy.current_tenant() != tenancy.DEFAULT_TENANT:
            tenancy.set_current_tenant(tenancy.DEFAULT_TENANT)
