"""The reusable adapter-conformance suite — **the single place** the
``BenchmarkAdapter`` contract is enforced.

Shared contract: ``BenchmarkAdapter`` (LLD 41 §4.2 · FR-14.1 · WS-A A1).

:func:`assert_adapter_conforms` is the whole contract, in one callable. WS-C, WS-E
and WS-F each make their adapter appear here by **registering it** — the
parametrization below reads :func:`benchmarks.core.registry.registered_names`, so
no sibling workstream has to remember to edit a list. Conformance is enforced in
one place or it drifts into three.

Today the registry is empty (the first adapter lands with WS-C), so the
registry-driven test skips. That would make this file vacuous, which is why the
suite is *also* exercised against a deliberately-broken :class:`StubAdapter` in
both directions: once conforming, and once per rule it can violate. Those negative
tests are what prove the suite bites, and they keep working after real adapters
arrive.
"""
from __future__ import annotations

import pytest

from benchmarks.core import registry
from benchmarks.core.adapter import BenchmarkAdapter, ToolManifest
from benchmarks.core.case import BenchmarkCase

from ..conftest import StubAdapter, case_kwargs


def assert_adapter_conforms(adapter) -> None:
    """Assert ``adapter`` satisfies every load-bearing rule of the protocol.

    The rules, and why each one is here rather than left to review:

    * **``iter_cases()`` yields only ``BenchmarkCase``.** Both rigs and the ledger
      writer read named fields off it; a duck-typed near-miss fails deep inside a
      run instead of at the seam.
    * **``case_id`` is sorted and unique.** Order-dependence is a reproducibility
      defect (tie-breaker E) and it silently changes trust accumulation in Mode B.
      A duplicate ``case_id`` breaks ``diff.py``'s join — the key it uses to match
      run *N* to *N−1* — so a duplicate makes G5 quietly wrong rather than loud.
    * **``tool_manifest()`` returns a ``ToolManifest`` with non-empty, sorted,
      unique ``tool_names``.** It is the sole input to ``policy_synth``; an empty
      surface synthesizes a policy that allows nothing and scores a perfect,
      meaningless ASR reduction.
    * **``name`` is a lowercase non-empty string and ``upstream_repo`` is set.**
      Both land in the manifest; an empty one is an unpinnable run.
    """
    assert isinstance(adapter, BenchmarkAdapter), (
        f"{type(adapter).__name__} does not present the BenchmarkAdapter surface"
    )

    assert isinstance(adapter.name, str) and adapter.name, "adapter.name is empty"
    assert adapter.name == adapter.name.lower(), (
        f"adapter.name {adapter.name!r} must be lowercase — it is matched exactly "
        "against --adapter and stamped into manifest.benchmark.adapter"
    )
    assert isinstance(adapter.upstream_repo, str) and adapter.upstream_repo, (
        "adapter.upstream_repo is empty — the checkout it names is what §7.1 pins"
    )

    cases = list(adapter.iter_cases())
    assert cases, (
        f"{adapter.name}.iter_cases() yielded nothing — every assertion below "
        "would be vacuous, and so would the run"
    )

    for case in cases:
        assert isinstance(case, BenchmarkCase), (
            f"{adapter.name}.iter_cases() yielded {type(case).__name__}, "
            "not a BenchmarkCase"
        )

    case_ids = [case.case_id for case in cases]
    assert case_ids == sorted(case_ids), (
        f"{adapter.name}.iter_cases() is not sorted by case_id — order-dependence "
        "is a reproducibility defect (tie-breaker E)"
    )
    assert len(set(case_ids)) == len(case_ids), (
        f"{adapter.name}.iter_cases() repeats a case_id — diff.py joins on it, so "
        "a duplicate makes the run-over-run comparison silently wrong"
    )

    for suite in sorted({case.suite for case in cases}):
        manifest = adapter.tool_manifest(suite=suite)
        assert isinstance(manifest, ToolManifest), (
            f"{adapter.name}.tool_manifest(suite={suite!r}) returned "
            f"{type(manifest).__name__}, not a ToolManifest"
        )
        names = list(manifest.tool_names)
        assert names, (
            f"{adapter.name}.tool_manifest(suite={suite!r}).tool_names is empty — "
            "policy_synth would build a policy that allows nothing and score a "
            "meaningless ASR reduction"
        )
        assert names == sorted(names), (
            f"{adapter.name}.tool_manifest(suite={suite!r}).tool_names is unsorted"
        )
        assert len(set(names)) == len(names), (
            f"{adapter.name}.tool_manifest(suite={suite!r}).tool_names repeats a name"
        )


# --------------------------------------------------------------------------- #
# Every registered adapter. WS-C / WS-E / WS-F appear here by registering.
# --------------------------------------------------------------------------- #
_REGISTERED = registry.registered_names()


@pytest.mark.skipif(
    not _REGISTERED,
    reason=(
        "no adapter is registered yet — WS-C lands the first one. This test "
        "activates on its own the moment an adapter package registers itself; "
        "meanwhile the StubAdapter tests below keep the suite honest."
    ),
)
@pytest.mark.parametrize("name", _REGISTERED or ["<none>"])
def test_registered_adapter_conforms(name):
    """Every adapter in the registry satisfies the contract."""
    assert_adapter_conforms(registry.get_adapter(name))


# --------------------------------------------------------------------------- #
# The suite tested against itself — a conformance suite that has only ever seen
# conforming adapters is a suite nobody has tested.
# --------------------------------------------------------------------------- #
def _cases(*case_ids, suite="core"):
    return [
        BenchmarkCase(**case_kwargs(case_id=cid, episode_id=cid, suite=suite))
        for cid in case_ids
    ]


def test_conforming_stub_passes():
    """The positive control. If this fails, every negative test below is
    meaningless — they would be passing for the wrong reason."""
    assert_adapter_conforms(
        StubAdapter(cases=_cases("stub:core:1", "stub:core:2", "stub:core:3"))
    )


def test_rejects_unsorted_case_ids():
    with pytest.raises(AssertionError, match="not sorted by case_id"):
        assert_adapter_conforms(StubAdapter(cases=_cases("stub:core:3", "stub:core:1")))


def test_rejects_duplicate_case_ids():
    with pytest.raises(AssertionError, match="repeats a case_id"):
        assert_adapter_conforms(StubAdapter(cases=_cases("stub:core:1", "stub:core:1")))


def test_rejects_a_non_case_yield():
    """A duck-typed near-miss must fail at the seam, not deep inside a run."""

    class NotACase:
        case_id = "stub:core:1"
        suite = "core"
        episode_id = "stub:core:1"

    with pytest.raises(AssertionError, match="not a BenchmarkCase"):
        assert_adapter_conforms(StubAdapter(cases=[NotACase()]))


def test_rejects_an_empty_case_stream():
    with pytest.raises(AssertionError, match="yielded nothing"):
        assert_adapter_conforms(StubAdapter(cases=[]))


def test_rejects_empty_tool_names():
    with pytest.raises(AssertionError, match="tool_names is empty"):
        assert_adapter_conforms(
            StubAdapter(cases=_cases("stub:core:1"), tool_names=[], read_write={})
        )


def test_rejects_unsorted_tool_names():
    with pytest.raises(AssertionError, match="tool_names is unsorted"):
        assert_adapter_conforms(
            StubAdapter(
                cases=_cases("stub:core:1"),
                tool_names=["write_record", "read_record"],
                read_write={"read_record": "READ", "write_record": "WRITE"},
            )
        )


def test_rejects_duplicate_tool_names():
    with pytest.raises(AssertionError, match="tool_names repeats a name"):
        assert_adapter_conforms(
            StubAdapter(
                cases=_cases("stub:core:1"),
                tool_names=["read_record", "read_record"],
                read_write={"read_record": "READ"},
            )
        )


def test_rejects_a_name_the_cli_cannot_select():
    with pytest.raises(AssertionError, match="must be lowercase"):
        assert_adapter_conforms(
            StubAdapter(name="StubAdapter", cases=_cases("stub:core:1"))
        )


def test_rejects_an_unpinnable_checkout():
    with pytest.raises(AssertionError, match="upstream_repo is empty"):
        assert_adapter_conforms(
            StubAdapter(upstream_repo="", cases=_cases("stub:core:1"))
        )


def test_conformance_covers_every_suite_the_cases_name():
    """``tool_manifest()`` is checked once per suite present in the case stream,
    so a second suite with a broken manifest cannot hide behind a healthy first.
    """
    calls = []

    class SecondSuiteBroken(StubAdapter):
        def tool_manifest(self, *, suite):
            calls.append(suite)
            if suite == "beta":
                return ToolManifest(tool_names=[], read_write={}, provenance="stub")
            return super().tool_manifest(suite=suite)

    adapter = SecondSuiteBroken(
        cases=_cases("stub:alpha:1", suite="alpha") + _cases("stub:beta:1", suite="beta")
    )
    with pytest.raises(AssertionError, match="tool_names is empty"):
        assert_adapter_conforms(adapter)

    assert calls == ["alpha", "beta"]
