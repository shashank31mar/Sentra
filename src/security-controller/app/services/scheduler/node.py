"""DAG node descriptor + cost tiers — WS-C / LLD 31 §5.1 (the DAG data model).

Each validator becomes a `ValidatorNode`: a canonical `Source.SENTRA_*` name, a
cost tier, an awaitable `run` callable, and `depends_on` edges. This is the
WS20.0 "node with dependencies and a cost tier" (LLD 20 §4.5) made concrete.

The descriptor is `frozen=True` so the static graph cannot be mutated per
request — the registry builds it once and the scheduler only reads it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, Dict, Tuple

from app.api.models import ValidationRequest, ValidationResult


class CostTier(str, Enum):
    """Cost tiers — LLD 20 §3.4 / LLD 31 §5.1.

    tier-0 = the cheap deterministic frontier (short-circuit); tier-1 = the
    expensive models, parallel-gathered only for tier-0 survivors.
    """

    DETERMINISTIC = "tier-0"    # ~1-5ms: trust, policy, cross_agent, sigma, context, abuse
    EXPENSIVE_MODEL = "tier-1"  # ~600ms ML; D1-D7 (added by WS-L)


@dataclass(frozen=True)
class ValidatorNode:
    """A single validator in the DAG (LLD 31 §5.1).

    Attributes:
        source: the canonical `Source.SENTRA_*` string from combiners/sources.py
            (e.g. ``sentra.sigma``). This is the join key the combiner's
            ``_neg_source`` tie-break and the WS-D trail both key on — a new /
            invented name breaks the audit join and silently loses tie-breaks
            (``default_priority`` returns 0 for an unknown source). NEVER spell a
            literal; pass ``Source.SENTRA_*``.
        cost_tier: DETERMINISTIC (tier-0, short-circuit) or EXPENSIVE_MODEL
            (tier-1, parallel-gather).
        run: the awaitable the sequential step makes today, wrapping ONLY the
            validator call (the Cedar cutover/shadow/legacy selection is
            encapsulated inside the policy node's ``run`` — the scheduler stays
            policy-engine-agnostic; LLD 31 §5.3). Signature
            ``(request, session) -> Awaitable[ValidationResult]``.
        depends_on: source names that must complete before this node runs. A
            tier-0 edge orders the topological run; a tier-1→tier-1 edge declares
            a sequential chain (D2→D4→D5); a tier-1→tier-0 edge is documentary
            (tier-1 only runs for frontier survivors anyway).
        order_key: the legacy step index — the DETERMINISTIC tie-break for
            topologically-independent tier-0 nodes so the short-circuit returns
            the SAME denier's result object (and its operator-facing ``reason``)
            the sequential chain returns (LLD 31 §6.2). Pinned to the legacy step
            order, NOT alphabetical.
    """

    source: str
    cost_tier: CostTier
    run: Callable[[ValidationRequest, Dict], Awaitable[ValidationResult]]
    depends_on: Tuple[str, ...] = ()
    order_key: int = field(default=0)
