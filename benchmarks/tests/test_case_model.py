"""Unit tests for ``BenchmarkCase`` — LLD 41 §4.1 (D2) · FR-14.1 · WS-A A1.

Every construction test calls ``BenchmarkCase(...)`` **directly**, never through a
helper that could be doing the validating. That is the entire point of SEC-4: an
earlier draft put these guards in a ``make_case(**kw)`` factory, which a public
frozen dataclass makes bypassable — ``BenchmarkCase(phase="output", …)``
constructs cleanly around it. :func:`benchmarks.tests.conftest.case_kwargs` only
supplies keyword defaults and adds no validation, so a test that overrides a field
into an invalid value still reaches the real ``__post_init__``.
"""
from __future__ import annotations

import dataclasses

import pytest

from benchmarks.core.case import (
    CONTENT_PHASES,
    MAX_CONTENT_TEXT_LEN,
    PHASES,
    BenchmarkCase,
    ContentFieldMismatch,
    ContentTooLong,
    ExcludedPhase,
    LabelMismatch,
    UnknownPhase,
    _EXCLUDED_PHASES,
)

from .conftest import case_kwargs


def test_output_phase_raises_excluded_phase():
    """``phase="output"`` is refused *on construction*, carrying both ids.

    ``routes.py:221`` fail-secure DENYs the output phase because D5 is not built,
    so an output-scored case would be recorded as "blocked" by a stub. The adapter
    catches this specific type, counts it into ``excluded_by_phase`` and the
    manifest reports it — which is why it is distinct from :class:`UnknownPhase`.
    """
    with pytest.raises(ExcludedPhase) as excinfo:
        BenchmarkCase(**case_kwargs(phase="output", content_text="ingested output"))

    assert excinfo.value.case_id == "stub:core:task_1"
    assert excinfo.value.phase == "output"
    # The refusal has to be self-explaining: an operator reading it should not
    # have to open routes.py to learn why the phase is not measurable.
    assert "output" in str(excinfo.value)


def test_unknown_phase_raises():
    """A phase LLD 30 does not know at all is a *different* error from exclusion.

    Collapsing the two would make an adapter bug (a typo'd phase) look like an
    expected, counted omission in the manifest.
    """
    with pytest.raises(UnknownPhase) as excinfo:
        BenchmarkCase(**case_kwargs(phase="telemetry"))

    assert excinfo.value.phase == "telemetry"
    assert not isinstance(excinfo.value, ExcludedPhase)


def test_label_outcome_mismatch_raises():
    """``label`` is TRUE iff ``expected_outcome == "deny"`` — asserted, not hoped.

    The redundancy is intentional (one feeds ``score_detector``, the other is what
    a human reads in ``cases.jsonl``); this invariant is the only thing keeping
    the two from drifting into a silently mis-scored corpus.
    """
    with pytest.raises(LabelMismatch):
        BenchmarkCase(**case_kwargs(label=True, expected_outcome="allow"))
    with pytest.raises(LabelMismatch):
        BenchmarkCase(**case_kwargs(label=False, expected_outcome="deny"))

    # Both consistent pairings construct.
    benign = BenchmarkCase(**case_kwargs(label=False, expected_outcome="allow"))
    attack = BenchmarkCase(**case_kwargs(label=True, expected_outcome="deny"))
    assert benign.label is False
    assert attack.label is True


@pytest.mark.parametrize(
    "phase,content_text,expected",
    [
        ("content", "an injected passage", None),
        ("content", None, ContentFieldMismatch),
        ("memory", "a poisoned memory write", None),
        ("memory", None, ContentFieldMismatch),
        ("request", None, None),
        ("request", "a payload with nowhere to ride", ContentFieldMismatch),
    ],
)
def test_content_text_required_iff_content_or_memory(phase, content_text, expected):
    """``content_text`` is present **iff** the phase is content-bearing.

    On ``request`` the payload rides ``user_input``; a request-phase case also
    carrying ``content_text`` has one of the two going unmeasured, which is a
    silently wrong number rather than an error — hence the guard.
    """
    kwargs = case_kwargs(phase=phase, content_text=content_text)
    if expected is None:
        case = BenchmarkCase(**kwargs)
        assert case.content_text == content_text
    else:
        with pytest.raises(expected):
            BenchmarkCase(**kwargs)


def test_phases_derived_from_known_phases():
    """``PHASES`` is computed from LLD 30's set, not re-typed beside it.

    This test **imports** ``KNOWN_PHASES`` rather than restating a literal, so the
    day LLD 30 registers a fifth phase the assertion carries it automatically —
    which is the property a hand-written ``Literal[...]`` in ``case.py`` would
    have destroyed.
    """
    from app.api.models import KNOWN_PHASES

    assert PHASES == KNOWN_PHASES - {"output"}
    assert _EXCLUDED_PHASES == frozenset({"output"})

    # Guard the guard: if "output" ever leaves KNOWN_PHASES the subtraction above
    # becomes a no-op and this file would stop testing anything.
    assert "output" in KNOWN_PHASES
    assert "output" not in PHASES
    assert PHASES, "an empty measurable phase set would make every case test vacuous"


def test_content_phases_derived_from_content_field_map():
    """``CONTENT_PHASES`` is derived from LLD 30's phase → content-field map.

    Writing ``("content", "memory")`` by hand in ``case.py`` is the same defect as
    a hand-written phase list, one level down: the set of phases whose payload
    rides ``content_text`` is a fact ``app/api/models.py:34`` already owns.
    """
    from app.api.models import _CONTENT_FIELD

    assert CONTENT_PHASES == frozenset(_CONTENT_FIELD) & PHASES
    assert CONTENT_PHASES == {"content", "memory"}
    # The excluded phase is content-bearing upstream but must not appear here —
    # the intersection with PHASES is what removes it, and when D5 ships and
    # "output" leaves _EXCLUDED_PHASES it will reappear with no further edit.
    assert "output" in _CONTENT_FIELD
    assert "output" not in CONTENT_PHASES
    assert "request" not in CONTENT_PHASES


def test_content_text_max_len_boundary():
    """The bound mirrors ``ValidationRequest.content_text`` exactly.

    The constant is **imported**, not spelled ``1048576`` here: the harness-side
    check exists so an over-cap payload is a corpus defect caught before case one
    rather than a 422 forty minutes into a run, and a hardcoded copy would drift
    from the edge it is supposed to mirror.
    """
    from app.api.models import CONTENT_TEXT_MAX_LEN

    assert MAX_CONTENT_TEXT_LEN == CONTENT_TEXT_MAX_LEN

    at_bound = BenchmarkCase(
        **case_kwargs(phase="content", content_text="x" * CONTENT_TEXT_MAX_LEN)
    )
    assert len(at_bound.content_text) == CONTENT_TEXT_MAX_LEN

    with pytest.raises(ContentTooLong) as excinfo:
        BenchmarkCase(
            **case_kwargs(phase="content", content_text="x" * (CONTENT_TEXT_MAX_LEN + 1))
        )
    assert excinfo.value.length == CONTENT_TEXT_MAX_LEN + 1


def test_frozen_dataclass_rejects_mutation():
    """Frozen is load-bearing, not stylistic.

    A case is read by both rigs, the ledger writer and the scorer; a mutation
    anywhere downstream would mean the label that was *scored* is not the label
    that was *recorded*.
    """
    case = BenchmarkCase(**case_kwargs())

    with pytest.raises(dataclasses.FrozenInstanceError):
        case.label = True  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        case.case_id = "reassigned"  # type: ignore[misc]

    assert case.label is False


def test_raw_defaults_to_empty_and_is_the_only_defaulted_field():
    """``raw`` is the adapter-private escape valve; everything else is explicit.

    Requiring every other field is deliberate: a forgotten ``content_text`` should
    be a ``TypeError`` at construction, not a ``None`` that quietly satisfies the
    request-phase branch of a rule it was never meant to take.
    """
    case = BenchmarkCase(**case_kwargs())
    assert case.raw == {}

    defaulted = [
        f.name
        for f in dataclasses.fields(BenchmarkCase)
        if f.default is not dataclasses.MISSING
        or f.default_factory is not dataclasses.MISSING  # type: ignore[misc]
    ]
    assert defaulted == ["raw"]

    with pytest.raises(TypeError):
        BenchmarkCase(benchmark="stub", suite="core")  # type: ignore[call-arg]
