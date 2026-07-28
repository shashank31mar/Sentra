"""The ``BenchmarkAdapter`` protocol and the value types every adapter shares.

LLD 41 §4.2 (D3) · FR-14.1 · WS-A milestone A1 (task A2).

An adapter is a class with exactly **four** methods. ``iter_cases()`` yields
:class:`~benchmarks.core.case.BenchmarkCase` objects for Mode A; ``tool_manifest()``
returns the suite's tool surface so ``policy_synth`` can build a policy;
``run_arm()`` executes the benchmark's own loop for one Mode B arm; ``score_run()``
takes the completed pair of arms and returns ASR/utility using the *benchmark's
own* scoring code.

Adding a third benchmark means writing one class implementing these four methods
and registering it (:mod:`benchmarks.core.registry`) — the rigs, the case model,
the manifest, the report and the scorers are untouched. That claim is not left as
prose: ``benchmarks/tests/test_extensibility.py`` enforces it as a code scan, and
G4's real proof is a zero-diff ``git diff`` over ``benchmarks/core/`` and
``benchmarks/rigs/`` when the second adapter lands.

(An earlier LLD draft said "three" in prose while listing four. **Four is
correct** — ``run_arm`` is per-arm and ``score_run`` needs *both* arms.)

Two contract rules are load-bearing rather than stylistic
----------------------------------------------------------
* ``iter_cases()`` **MUST be deterministic in order — sorted by ``case_id``.**
  Order-dependence is a reproducibility defect (tie-breaker E) and it silently
  changes trust accumulation in Mode B. Enforced by the conformance suite,
  ``benchmarks/tests/integration/test_adapter_conformance.py``.
* ``score_run()`` **delegates to the benchmark's own scorer; it never re-derives
  "did the attack succeed."** Reimplementing that silently diverges from the
  published baseline and destroys the one property that makes a public benchmark
  worth using. :class:`ArmResult` therefore carries the benchmark's native
  results object opaquely, exactly as ``BenchmarkCase.raw`` does — core never
  reads it.

:class:`ToolManifest` deliberately carries **no case labels** (LLD 41 §4.5). It is
the only input ``policy_synth.synthesize()`` reads, so a synthesizer reaching for
``injection_goal`` would have to import the case model — a visible import the
extensibility scan covers. That structural fence is pinned by
``test_tool_manifest_carries_no_case_labels``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Iterator,
    List,
    Literal,
    Optional,
    Protocol,
    Tuple,
    runtime_checkable,
)

from .case import BenchmarkCase

if TYPE_CHECKING:  # pragma: no cover
    # WS-A task A3 (milestone A2) lands ``benchmarks/core/context.py``. Under
    # ``from __future__ import annotations`` the reference below is a string that
    # is never evaluated at runtime, so this module imports standalone today and
    # needs no edit when A3 arrives.
    from .context import RunContext

#: Which arm of the Mode B pair is running. ``"with"`` inserts the checkpoint;
#: ``"without"`` is the stock pipeline the published baseline corresponds to.
Arm = Literal["with", "without"]

#: The runtime dual of :data:`Arm` — a ``Literal`` is not enforced at runtime, so
#: the checks below read from this.
ARMS: Tuple[str, str] = ("with", "without")

#: The read/write classification an adapter derives per tool. Matches
#: ``ValidationRequest.operation_type`` (``app/api/models.py:70``).
OPERATION_TYPES = frozenset({"READ", "WRITE"})


# --------------------------------------------------------------------------- #
# Value types every adapter and rig shares
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ToolManifest:
    """A suite's tool surface — FR-14.4. The sole input to ``policy_synth``.

    Args:
        tool_names: every tool the suite exposes. The conformance suite requires
            this to be non-empty, sorted and unique.
        read_write: tool name → ``"READ"`` | ``"WRITE"``. Feeds
            ``BenchmarkCase.operation_type``.
        provenance: where the surface was read from (adapter + suite + upstream
            SHA), recorded into ``manifest.policy.synthesized_from`` so a run whose
            policy suddenly grew conditions is legible in the diff.
        param_bounds: optional per-tool parameter bounds. ``None`` when the
            benchmark exposes no schema to derive them from.

    Carries no ``label``, ``attack_type`` or ``injection_goal`` — see the module
    docstring's anti-gaming note.
    """

    tool_names: List[str]
    read_write: Dict[str, str]
    provenance: str
    param_bounds: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        """Internal-consistency only.

        The *adapter-facing* contract (non-empty, sorted, unique ``tool_names``)
        is enforced in one place — the conformance suite — so it stays testable
        against a deliberately-broken adapter. What is checked here is the pair of
        invariants a caller would otherwise trip over silently: an unclassified
        tool, and a classification for a tool that does not exist.
        """
        unknown = sorted(set(self.read_write.values()) - OPERATION_TYPES)
        if unknown:
            raise ValueError(
                f"read_write carries operation types {unknown} outside "
                f"{sorted(OPERATION_TYPES)} — operation_type is what reaches "
                "ValidationRequest.operation_type on the wire"
            )
        orphans = sorted(set(self.read_write) - set(self.tool_names))
        if orphans:
            raise ValueError(
                f"read_write classifies tools absent from tool_names: {orphans}"
            )


@dataclass(frozen=True)
class ArmResult:
    """The raw outcome of one Mode B arm.

    ``native`` is the benchmark's **own** results object (AgentDojo's
    ``SuiteResults``, an ASB result row set, …), carried opaquely. Core never
    reads it — ``score_run()`` hands it back to the benchmark's own scorer. This
    is the same escape-valve discipline as ``BenchmarkCase.raw``, and it is what
    keeps "a new benchmark = one adapter, zero core change" true for Mode B.

    ``episode_ids`` is a *tuple*, in execution order, because the ledger and the
    resume filter key on it and both need a stable sequence.
    """

    arm: str
    episode_ids: Tuple[str, ...]
    native: Any = None

    def __post_init__(self) -> None:
        if self.arm not in ARMS:
            raise ValueError(
                f"arm must be one of {list(ARMS)}, got {self.arm!r} — the pair is "
                "what score_run() compares, so a third value has no meaning"
            )

    @property
    def n_episodes(self) -> int:
        """Derived, so the count can never disagree with the ids."""
        return len(self.episode_ids)


@dataclass(frozen=True)
class RunScore:
    """The Mode B headline, mapped from the benchmark's own scorer.

    Every rate is a **fraction in [0, 1]**, not a percentage. An adapter that hands
    back ``11`` for "11%" would otherwise produce an ``asr_reduction_pp`` of
    thousands, so the bound is checked rather than assumed.

    ``asr_reduction_pp`` and ``utility_retention`` are **properties, not stored
    fields** — a stored copy is a second source of truth that can disagree with
    its own inputs.
    """

    asr_with: float
    asr_without: float
    utility_with: Optional[float] = None
    utility_without: Optional[float] = None
    refuse_rate: Optional[float] = None

    def __post_init__(self) -> None:
        for name in (
            "asr_with",
            "asr_without",
            "utility_with",
            "utility_without",
            "refuse_rate",
        ):
            value = getattr(self, name)
            if value is None:
                continue
            if not 0.0 <= value <= 1.0:
                raise ValueError(
                    f"{name}={value!r} is outside [0, 1] — RunScore rates are "
                    "fractions, not percentages (asr_reduction_pp is what carries "
                    "percentage points)"
                )

    @property
    def asr_reduction_pp(self) -> float:
        """``asr_without − asr_with``, in **percentage points**.

        Never a relative percentage: a relative "70% reduction" off a 3% base is a
        rounding error dressed as a result (LLD 41 §5.2). Report it only with
        ``noise_floor_pp`` beside it — a tenth of a point without the floor is a
        precision claim the rig cannot support.
        """
        return (self.asr_without - self.asr_with) * 100.0

    @property
    def utility_retention(self) -> Optional[float]:
        """``utility_with / utility_without``.

        ``None`` when either arm's utility is unknown, or when the baseline is
        zero — a ratio off a collapsed denominator is worse than no ratio. The
        report prints both raw numbers alongside it for the same reason.
        """
        if self.utility_with is None or not self.utility_without:
            return None
        return self.utility_with / self.utility_without


# --------------------------------------------------------------------------- #
# The protocol — exactly four methods and two attributes
# --------------------------------------------------------------------------- #
@runtime_checkable
class BenchmarkAdapter(Protocol):
    """Everything a benchmark must provide, and nothing more.

    ``@runtime_checkable`` buys an ``isinstance`` shape check (attribute presence
    only — signatures are not verified, and ``issubclass`` is unsupported on a
    protocol with data members). The behavioural contract lives in the conformance
    suite.

    A fifth method added here to serve one benchmark is the failure FR-14.1 exists
    to prevent; ``test_protocol_has_exactly_four_methods`` fails on it.
    """

    #: The registry key AND the ``benchmark.adapter`` manifest field — the
    #: adapter's own lowercase package name. NO benchmark literal appears in core.
    name: str

    #: Absolute path to the pinned local checkout, recorded as
    #: ``benchmark.checkout`` alongside its git SHA (§7.1).
    upstream_repo: str

    def iter_cases(self, *, suite: Optional[str] = None) -> Iterator[BenchmarkCase]:
        """Mode A. Yield normalized labeled cases.

        MUST be deterministic in order — **sorted by ``case_id``**, and unique.
        ``suite=None`` means every suite.
        """
        ...

    def tool_manifest(self, *, suite: str) -> ToolManifest:
        """FR-14.4. The suite's tool surface, feeding ``policy_synth.synthesize()``."""
        ...

    def run_arm(self, *, arm: Arm, ctx: "RunContext") -> ArmResult:
        """Mode B. Execute the benchmark's OWN loop for one arm, with the
        checkpoint inserted iff ``arm == "with"``."""
        ...

    def score_run(self, *, with_arm: ArmResult, without_arm: ArmResult) -> RunScore:
        """Mode B scoring, using the **benchmark's own** scorer — never a
        reimplementation. Maps its output onto :class:`RunScore`."""
        ...
