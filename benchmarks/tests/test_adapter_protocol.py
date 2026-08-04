"""Unit tests for the adapter protocol, its value types and the registry.

LLD 41 §4.2 (D3) · §4.5 (the anti-gaming fence) · FR-14.1 · WS-A A1 (task A2).

These pin the *shape* of the seam: four methods and two attributes, a registry
that dispatches by name with no benchmark literal, and value types that refuse the
two unit errors most likely to reach a headline — an arm that is neither arm, and
a rate handed over as a percentage.
"""
from __future__ import annotations

import dataclasses

import pytest

from benchmarks.core.adapter import (
    ARMS,
    ArmResult,
    BenchmarkAdapter,
    RunScore,
    ToolManifest,
)
from benchmarks.core.registry import DuplicateAdapter, UnknownAdapter

from .conftest import StubAdapter, case_kwargs

#: The contract, spelled once. A fifth method bolted on to serve one benchmark is
#: the failure FR-14.1 exists to prevent.
EXPECTED_METHODS = {"iter_cases", "tool_manifest", "run_arm", "score_run"}
EXPECTED_ATTRIBUTES = {"name", "upstream_repo"}


def _protocol_members(protocol) -> set:
    """Every member the protocol declares — methods and data attributes alike.

    ``__protocol_attrs__`` is the authoritative set on Python 3.12+; the fallback
    keeps the test meaningful rather than silently green on an older runtime.
    """
    members = getattr(protocol, "__protocol_attrs__", None)
    if members is not None:
        return set(members)
    return {n for n in vars(protocol) if not n.startswith("_")} | set(
        getattr(protocol, "__annotations__", {})
    )


def test_protocol_has_exactly_four_methods():
    """Exactly four methods and exactly two attributes — no more, no fewer.

    An earlier LLD draft said "three" in prose while listing four. Four is
    correct: ``run_arm`` is per-arm and ``score_run`` needs *both* arms, so they
    cannot be merged. This test is what makes "a new benchmark = one adapter"
    mechanically true rather than aspirational.
    """
    members = _protocol_members(BenchmarkAdapter)
    methods = {n for n in members if callable(getattr(BenchmarkAdapter, n, None))}
    attributes = members - methods

    assert methods == EXPECTED_METHODS
    assert attributes == EXPECTED_ATTRIBUTES
    assert len(members) == 6


def test_conforming_adapter_satisfies_the_runtime_check():
    """``@runtime_checkable`` gives the rigs a cheap shape gate.

    It verifies attribute *presence* only — signatures are not checked, and
    ``issubclass`` is unsupported on a protocol with data members — so the
    behavioural contract stays with the conformance suite. Without this test the
    decorator could be dropped and nothing would notice.
    """
    assert isinstance(StubAdapter(), BenchmarkAdapter)
    assert not isinstance(object(), BenchmarkAdapter)


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
def test_registry_rejects_duplicate_name(clean_registry):
    """Two claimants for one name would make ``manifest.benchmark.adapter``
    depend on import order — i.e. make the manifest lie about which benchmark ran.
    """
    clean_registry.register("agentdojo", StubAdapter)

    with pytest.raises(DuplicateAdapter) as excinfo:
        clean_registry.register("agentdojo", StubAdapter)

    assert excinfo.value.name == "agentdojo"
    assert clean_registry.registered_names() == ("agentdojo",)


def test_registry_unknown_name_lists_available(clean_registry):
    """A run that dies on a typo should say what *was* available.

    ``RegistryError`` is deliberately not a ``KeyError``: ``KeyError.__str__``
    reprs its argument, which would bury this list in quotes.
    """
    clean_registry.register("alpha", StubAdapter)
    clean_registry.register("beta", StubAdapter)

    with pytest.raises(UnknownAdapter) as excinfo:
        clean_registry.get_adapter("nope")

    message = str(excinfo.value)
    assert "nope" in message
    assert "alpha" in message and "beta" in message
    assert excinfo.value.available == ("alpha", "beta")


def test_registry_stores_factories_not_instances(clean_registry):
    """Registration must cost nothing.

    An adapter package registers itself at import; if that constructed the adapter
    it would open a benchmark checkout (and potentially reach the network) merely
    to make the name selectable from ``--adapter``.
    """
    built = []

    def factory(**kwargs):
        built.append(kwargs)
        return StubAdapter(**kwargs)

    clean_registry.register("lazy", factory)
    assert built == [], "registration constructed the adapter"

    adapter = clean_registry.get_adapter("lazy", name="lazy")
    assert built == [{"name": "lazy"}], "get_adapter did not forward its kwargs"
    assert adapter.name == "lazy"


def test_registry_rejects_a_name_no_one_could_select(clean_registry):
    """``--adapter`` matches exactly, so a padded or capitalized key is a name the
    CLI can never resolve — caught at registration, not at 2am on the run."""
    for bad in ("AgentDojo", " spaced", "trailing ", ""):
        with pytest.raises(ValueError):
            clean_registry.register(bad, StubAdapter)
    assert clean_registry.registered_names() == ()


# --------------------------------------------------------------------------- #
# Value types
# --------------------------------------------------------------------------- #
def test_run_score_reduction_is_percentage_points():
    """``asr_reduction_pp`` is a difference in **percentage points**, never a
    relative percentage.

    A relative "70% reduction" off a 3% base is a rounding error dressed as a
    result. The second assertion is the load-bearing one: it fails if someone
    "improves" the property into the relative form, which the first assertion
    alone would not catch on every input.
    """
    score = RunScore(asr_with=0.11, asr_without=0.43)
    assert score.asr_reduction_pp == pytest.approx(32.0)

    relative = (0.43 - 0.11) / 0.43 * 100.0
    assert score.asr_reduction_pp != pytest.approx(relative, abs=0.5)

    # The low-base case the pp/relative distinction exists for: 2 points, which a
    # relative reading would announce as a 66% win.
    low_base = RunScore(asr_with=0.01, asr_without=0.03)
    assert low_base.asr_reduction_pp == pytest.approx(2.0)

    # It is a signed difference — a with-arm that scores *worse* reads negative
    # rather than collapsing to zero.
    assert RunScore(asr_with=0.4, asr_without=0.1).asr_reduction_pp == pytest.approx(-30.0)


def test_run_score_rejects_a_rate_handed_over_as_a_percentage():
    """Every rate is a fraction in [0, 1].

    An adapter returning ``11`` for "11%" would otherwise produce an
    ``asr_reduction_pp`` in the thousands and a headline nobody would question
    until it was already in a deck.
    """
    with pytest.raises(ValueError):
        RunScore(asr_with=11.0, asr_without=43.0)
    with pytest.raises(ValueError):
        RunScore(asr_with=0.1, asr_without=0.4, refuse_rate=24.0)
    with pytest.raises(ValueError):
        RunScore(asr_with=-0.1, asr_without=0.4)


def test_run_score_utility_retention_needs_its_denominator():
    """A ratio off a collapsed baseline hides exactly the failure it should show."""
    score = RunScore(asr_with=0.1, asr_without=0.4, utility_with=0.6, utility_without=0.8)
    assert score.utility_retention == pytest.approx(0.75)

    assert RunScore(asr_with=0.1, asr_without=0.4).utility_retention is None
    assert (
        RunScore(
            asr_with=0.1, asr_without=0.4, utility_with=0.6, utility_without=0.0
        ).utility_retention
        is None
    )


def test_arm_result_rejects_an_arm_that_is_neither_arm():
    """``Arm`` is a ``Literal``, which a dataclass does not enforce at runtime —
    so the runtime check is the load-bearing one. ``score_run`` compares a *pair*;
    a third value has no meaning in it."""
    result = ArmResult(arm="with", episode_ids=("e1", "e2"))
    assert result.n_episodes == 2
    assert set(ARMS) == {"with", "without"}

    with pytest.raises(ValueError):
        ArmResult(arm="both", episode_ids=())


def test_arm_result_carries_the_benchmark_scorer_output_opaquely():
    """``native`` is the benchmark's own results object, carried and not read.

    ``score_run()`` hands it back to the benchmark's scorer rather than
    re-deriving "did the attack succeed" — reimplementing that would silently
    diverge from the published baseline. Core reading ``native`` is the same
    defect as core reading ``BenchmarkCase.raw``.
    """
    native = object()
    result = ArmResult(arm="without", episode_ids=("e1",), native=native)
    assert result.native is native

    # n_episodes is derived, so the count can never disagree with the ids.
    assert "n_episodes" not in {f.name for f in dataclasses.fields(ArmResult)}


def test_tool_manifest_carries_no_case_labels():
    """LLD §4.5's anti-gaming fence, made structural.

    ``policy_synth.synthesize()`` reads a ``ToolManifest`` and nothing else. If the
    type carried ``injection_goal`` — the attacker's objective verbatim — a
    parameter condition narrow enough to encode it would raise ASR reduction
    without improving anything, and the leak would be invisible. Keeping the
    labels off this type means a synthesizer reaching for them has to import the
    case model, which is a visible import the extensibility scan covers.
    """
    fields = {f.name for f in dataclasses.fields(ToolManifest)}
    assert fields == {"tool_names", "read_write", "provenance", "param_bounds"}
    for label_field in ("injection_goal", "label", "attack_type", "expected_outcome"):
        assert label_field not in fields


def test_tool_manifest_rejects_an_inconsistent_classification():
    """The two invariants a caller would otherwise trip over silently: an
    operation type that never reaches the wire, and a classification for a tool
    that does not exist."""
    with pytest.raises(ValueError):
        ToolManifest(
            tool_names=["read_record"],
            read_write={"read_record": "read"},  # lowercase never reaches the wire
            provenance="stub",
        )
    with pytest.raises(ValueError):
        ToolManifest(
            tool_names=["read_record"],
            read_write={"delete_record": "WRITE"},
            provenance="stub",
        )

    manifest = ToolManifest(
        tool_names=["read_record", "write_record"],
        read_write={"read_record": "READ", "write_record": "WRITE"},
        provenance="stub",
    )
    assert manifest.param_bounds is None


def test_stub_adapter_round_trips_the_four_methods():
    """The seam works end to end at least once, so the negative tests above are
    not the only thing exercising it."""
    from benchmarks.core.case import BenchmarkCase

    case = BenchmarkCase(**case_kwargs())
    adapter = StubAdapter(cases=[case])

    assert list(adapter.iter_cases()) == [case]
    assert list(adapter.iter_cases(suite="nonexistent")) == []
    assert adapter.tool_manifest(suite="core").tool_names == [
        "read_record",
        "write_record",
    ]

    with_arm = adapter.run_arm(arm="with", ctx=None)
    without_arm = adapter.run_arm(arm="without", ctx=None)
    assert with_arm.episode_ids == (case.episode_id,)
    assert adapter.score_run(
        with_arm=with_arm, without_arm=without_arm
    ).asr_reduction_pp == pytest.approx(32.0)
