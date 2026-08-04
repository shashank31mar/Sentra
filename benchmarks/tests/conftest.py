"""Shared fixtures for the benchmark-harness test suite.

Deliberately imports **nothing** from ``app.*`` at module scope: several tests
here turn on whether the I4 substitution landed before the app modules that
construct AWS clients were imported, and a conftest that pulled them in first
would quietly make those tests vacuous. It only puts the PDP package root on
``sys.path`` — the same thing ``enforce()`` does — so the tests that legitimately
need ``app.utils.tenancy`` can import it themselves.

That discipline extends transitively: ``benchmarks.core.case`` imports
``app.api.models`` (it derives ``PHASES`` from LLD 30's ``KNOWN_PHASES``), so the
WS-A helpers below import ``benchmarks.core.*`` **inside** their bodies rather
than at module scope.
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


# --------------------------------------------------------------------------- #
# WS-A milestone A1 — case-model and adapter-protocol helpers
# --------------------------------------------------------------------------- #
def case_kwargs(**overrides) -> dict:
    """Keyword arguments for one valid ``BenchmarkCase``, with overrides applied.

    Returns a **dict**, never a ``BenchmarkCase`` — deliberately. LLD 41 §4.1
    (SEC-4) rejects a ``make_case()`` factory because a public frozen dataclass
    can always be constructed around it; the ``__post_init__`` tests must
    therefore call ``BenchmarkCase(...)`` *directly*. Supplying kwargs keeps those
    call sites direct while staying readable, and this helper adds no validation
    of its own — so a test that overrides a field into an invalid value still
    reaches the real guard.
    """
    kwargs = {
        "benchmark": "stub",
        "suite": "core",
        "case_id": "stub:core:task_1",
        "episode_id": "stub:core:task_1",
        "phase": "request",
        "agent_id": "bench-stub-core",
        "tool_name": "read_record",
        "tool_params": {"record_id": "1"},
        "user_input": "read record 1",
        "content_text": None,
        "operation_type": "READ",
        "label": False,
        "attack_type": None,
        "injection_goal": None,
        "expected_outcome": "allow",
    }
    kwargs.update(overrides)
    return kwargs


class StubAdapter:
    """A structurally-typed ``BenchmarkAdapter`` whose every output is injectable.

    It exists so the conformance suite can be proven to *bite*: a suite that has
    only ever seen conforming adapters is a suite nobody has tested. Each
    constructor argument is handed back verbatim — unsorted ``cases``, a duplicate
    ``case_id``, a non-``BenchmarkCase`` yield and an unsorted ``tool_names`` are
    all reachable, which is what the negative conformance tests need.

    Imports live inside the methods; see the module docstring.
    """

    def __init__(
        self,
        *,
        name: str = "stub",
        cases=(),
        tool_names=("read_record", "write_record"),
        read_write=None,
        upstream_repo: str = "/nonexistent/stub-upstream",
        provenance: str = "stub-adapter@0000000",
    ):
        self.name = name
        self.upstream_repo = upstream_repo
        self._cases = list(cases)
        self._tool_names = list(tool_names)
        self._read_write = (
            dict(read_write)
            if read_write is not None
            else {n: ("READ" if n.startswith("read") else "WRITE") for n in tool_names}
        )
        self._provenance = provenance

    def iter_cases(self, *, suite=None):
        for case in self._cases:
            if suite is None or getattr(case, "suite", None) == suite:
                yield case

    def tool_manifest(self, *, suite: str):
        from benchmarks.core.adapter import ToolManifest

        return ToolManifest(
            tool_names=list(self._tool_names),
            read_write=dict(self._read_write),
            provenance=f"{self._provenance}:{suite}",
        )

    def run_arm(self, *, arm, ctx=None):
        from benchmarks.core.adapter import ArmResult

        return ArmResult(
            arm=arm,
            episode_ids=tuple(sorted({c.episode_id for c in self._cases})),
            native={"scored_by": "the benchmark's own scorer, not ours"},
        )

    def score_run(self, *, with_arm, without_arm):
        from benchmarks.core.adapter import RunScore

        # A real adapter delegates to the benchmark's scorer here; the stub just
        # returns a fixed pair, because what is under test is the seam, not ASR.
        return RunScore(asr_with=0.11, asr_without=0.43)


@pytest.fixture
def clean_registry():
    """Yield :mod:`benchmarks.core.registry` emptied for the test, then restored.

    The registry is process-global and adapter packages populate it at import, so
    a test that registers a name would otherwise either collide with a real
    adapter or leak into the next test. Reaching into ``_REGISTRY`` is deliberate:
    a public ``clear()`` on a production registry is an API nobody should have.
    """
    from benchmarks.core import registry

    saved = dict(registry._REGISTRY)
    registry._REGISTRY.clear()
    try:
        yield registry
    finally:
        registry._REGISTRY.clear()
        registry._REGISTRY.update(saved)


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
