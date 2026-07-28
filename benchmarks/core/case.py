"""``BenchmarkCase`` — the central shared contract every adapter emits.

LLD 41 §4.1 (D2) · FR-14.1 · WS-A milestone A1 (task A1).

``BenchmarkCase`` is the one dataclass every adapter emits and both rigs consume.
It is the join key that makes FR-14.1's "a new benchmark costs one adapter and no
core change" true rather than aspirational: Mode A reads
``phase``/``tool_name``/``tool_params``/``user_input``/``content_text``/``label``
to build a ``ValidationRequest``; Mode B reads ``case_id``/``episode_id``/
``expected_outcome`` to key the paired arms and score them.

The shape is deliberately a **superset of what** ``ValidationRequest``
(``app/api/models.py:54``) **needs, plus the labels a scorer needs, and nothing
else.** Every field maps to either a wire field or a report column; a field that
maps to neither does not belong.

Nothing here is re-typed from the owner
---------------------------------------
Two sets are *derived*, never restated:

* :data:`PHASES` = ``KNOWN_PHASES - _EXCLUDED_PHASES``. LLD 30 owns the phase
  universe as ``KNOWN_PHASES`` (``app/api/models.py:27``), whose own comment calls
  itself "the SINGLE SOURCE OF TRUTH". A hand-written ``Literal[...]`` here would
  silently fall behind the day LLD 30 registers a fifth phase — and a frozen
  dataclass does not enforce a ``Literal`` at runtime anyway, so the alias would
  be decoration while the runtime check did the work. **Subtract, don't re-list.**
* :data:`CONTENT_PHASES` = the keys of LLD 30's canonical phase → content-field
  map (``app/api/models.py:34``) intersected with :data:`PHASES`. The set of
  phases whose payload rides ``content_text`` is the same fact on both sides of
  the seam; writing ``("content", "memory")`` by hand here is the same defect as
  a hand-written phase list, one level down.

``phase == "output"`` is excluded in code, not in prose
-------------------------------------------------------
``routes.py:221`` returns ``_phase_not_implemented_deny(...)`` (defined ``:401``)
for the output phase because D5 is not built. A case scored on agent output would
therefore be recorded as *blocked by a stub* — a number that means nothing.
The adapter catches :class:`ExcludedPhase`, increments
``excluded_by_phase[phase]``, and the manifest reports the count.

**When D5 ships the fix is exactly one edit** — remove ``"output"`` from
:data:`_EXCLUDED_PHASES` — because both sets above are derived. The manifest diff
will then show the excluded count drop to zero: the visible proof the exclusion
was real and is now gone.

Why the guards are in ``__post_init__`` and not in a factory (SEC-4)
--------------------------------------------------------------------
An earlier LLD draft put them inside a ``make_case(**kw)`` helper. That is
bypassable and therefore not a guarantee: ``BenchmarkCase`` is a public frozen
dataclass, so ``BenchmarkCase(phase="output", label=True,
expected_outcome="allow", …)`` constructs cleanly and skips *every* check. SEC-4
claims validation happens "on construction"; only ``__post_init__`` makes that
true. No factory is provided here — one that adds no validation adds no value,
and one that adds validation re-opens the hole.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from app.api.models import (  # LLD 30 owns all three
    CONTENT_TEXT_MAX_LEN,
    KNOWN_PHASES,
    _CONTENT_FIELD,
)

#: Phases LLD 30 knows but the harness cannot measure. In ``KNOWN_PHASES``, no
#: live handler (``routes.py:221``). Removing an entry here is the *whole* change
#: needed to start measuring it.
_EXCLUDED_PHASES = frozenset({"output"})

#: The harness's measurable surface. Derived — see the module docstring.
PHASES = KNOWN_PHASES - _EXCLUDED_PHASES

#: The measurable phases whose payload rides ``content_text`` rather than
#: ``user_input``. Derived from LLD 30's canonical phase → content-field map so a
#: newly content-bearing phase carries this rule with it.
CONTENT_PHASES = frozenset(_CONTENT_FIELD) & PHASES

#: Re-exported so a scorer or a report column reads the bound from one place.
#: The **adapter** truncates to this and flags, rather than letting the edge 422
#: mid-run (LLD 41 §4.1).
MAX_CONTENT_TEXT_LEN = CONTENT_TEXT_MAX_LEN


# --------------------------------------------------------------------------- #
# Refusals. Each is distinct because the adapter loop treats them differently:
# ExcludedPhase is *counted and reported* (an expected, measured omission), while
# the rest are corpus defects that should stop the run.
# --------------------------------------------------------------------------- #
class CaseValidationError(ValueError):
    """Base for every :class:`BenchmarkCase` construction refusal.

    Carries ``case_id`` so an adapter that catches one can report *which* case,
    which is the difference between a usable error and a stack trace.
    """

    def __init__(self, case_id: str, message: str) -> None:
        super().__init__(f"{case_id}: {message}")
        self.case_id = case_id


class ExcludedPhase(CaseValidationError):
    """A phase LLD 30 knows but the harness deliberately does not measure.

    The one refusal an adapter is *expected* to catch: it increments
    ``excluded_by_phase[phase]`` and the manifest reports the count.
    """

    def __init__(self, case_id: str, phase: str) -> None:
        super().__init__(
            case_id,
            f"phase {phase!r} is excluded from measurement — it has no live "
            "handler (routes.py:221 fail-secure DENYs it), so a case scored on it "
            "would be recorded as blocked by a stub. Excluded phases: "
            f"{sorted(_EXCLUDED_PHASES)}",
        )
        self.phase = phase


class UnknownPhase(CaseValidationError):
    """A phase LLD 30 does not know at all — an adapter bug, not an omission."""

    def __init__(self, case_id: str, phase: str) -> None:
        super().__init__(
            case_id,
            f"phase {phase!r} is not a known validation phase; "
            f"measurable phases are {sorted(PHASES)}",
        )
        self.phase = phase


class LabelMismatch(CaseValidationError):
    """``label`` and ``expected_outcome`` disagree.

    The redundancy between them is intentional and cheap (one is what
    ``score_detector`` consumes, the other is what a human reads in
    ``cases.jsonl``); this invariant is what keeps them honest.
    """

    def __init__(self, case_id: str, label: bool, expected_outcome: str) -> None:
        super().__init__(
            case_id,
            f"label={label!r} contradicts expected_outcome={expected_outcome!r} — "
            'label is TRUE iff expected_outcome == "deny"',
        )
        self.label = label
        self.expected_outcome = expected_outcome


class ContentFieldMismatch(CaseValidationError):
    """``content_text`` is present on a non-content phase, or absent on one.

    Present **iff** the phase is content-bearing: on ``request`` the payload rides
    ``user_input``, and a case carrying both has one of them going unmeasured.
    """

    def __init__(self, case_id: str, phase: str, present: bool) -> None:
        expected = "required" if phase in CONTENT_PHASES else "must be None"
        super().__init__(
            case_id,
            f"content_text is {'present' if present else 'None'} on phase "
            f"{phase!r}, where it {expected} — content_text is present iff the "
            f"phase is one of {sorted(CONTENT_PHASES)}",
        )
        self.phase = phase


class ContentTooLong(CaseValidationError):
    """``content_text`` exceeds the bound ``ValidationRequest`` enforces.

    The harness-side dual of the edge's 422: the adapter is required to truncate
    and flag, so an over-cap payload is a corpus defect caught before case one
    rather than a 422 forty minutes into a run.
    """

    def __init__(self, case_id: str, length: int) -> None:
        super().__init__(
            case_id,
            f"content_text is {length} chars, over the {MAX_CONTENT_TEXT_LEN} "
            "bound ValidationRequest.content_text enforces (models.py:51) — the "
            "adapter must truncate and flag, not let the edge 422 mid-run",
        )
        self.length = length


# --------------------------------------------------------------------------- #
# The contract
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class BenchmarkCase:
    """One normalized, labeled case. Frozen; validated on construction.

    Field-by-field rationale for the non-obvious ones:

    ``case_id`` is **stable across runs** — ``diff.py`` joins run *N* to *N−1* on
    it, so a uuid here would make every diff a full add/remove and destroy G5.
    Adapters build it as ``{benchmark}:{suite}:{task_id}[:{injection_task_id}]``
    from the benchmark's own stable ids.

    ``episode_id`` is separate from ``case_id`` on purpose: the trust boundary is
    *coarser* than the case in Mode B (one user-task/injection pair) and *equal*
    to it in Mode A. Collapsing them hard-codes Mode A's semantics into the
    contract.

    ``injection_goal`` is the attacker's objective verbatim. It is **report
    grouping only — never scoring, and never reachable from ``policy_synth``**
    (LLD 41 §4.5's anti-gaming fence: a parameter condition narrow enough to
    encode the goal would raise ASR reduction without improving anything).

    ``raw`` is adapter-private passthrough and **core NEVER reads it**. It is the
    escape valve that keeps FR-14.1 true when the third benchmark arrives with odd
    metadata; the moment core reads it, WS-F's zero-diff proof fails.
    """

    # --- identity / provenance (manifest + join key) ---
    benchmark: str
    suite: str
    case_id: str
    episode_id: str

    # --- the action under test (mirrors ValidationRequest) ---
    phase: str
    agent_id: str
    tool_name: str
    tool_params: Dict[str, Any]
    user_input: str
    content_text: Optional[str]
    operation_type: str

    # --- labels (what the scorers need) ---
    label: bool
    attack_type: Optional[str]
    injection_goal: Optional[str]
    expected_outcome: str

    # --- carried, never interpreted by core ---
    raw: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate on construction — the only place that can be a guarantee.

        Ordered most-specific first: ``ExcludedPhase`` before ``UnknownPhase``
        (both are "not in PHASES", but only the former is an expected, counted
        omission), and the structural ``content_text`` presence rule before its
        length bound.
        """
        if self.phase in _EXCLUDED_PHASES:
            raise ExcludedPhase(self.case_id, self.phase)
        if self.phase not in PHASES:
            raise UnknownPhase(self.case_id, self.phase)
        if self.label != (self.expected_outcome == "deny"):
            raise LabelMismatch(self.case_id, self.label, self.expected_outcome)
        if (self.content_text is None) == (self.phase in CONTENT_PHASES):
            raise ContentFieldMismatch(
                self.case_id, self.phase, self.content_text is not None
            )
        if self.content_text is not None and len(self.content_text) > MAX_CONTENT_TEXT_LEN:
            raise ContentTooLong(self.case_id, len(self.content_text))
