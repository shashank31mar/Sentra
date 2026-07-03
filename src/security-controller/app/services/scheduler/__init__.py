"""Cost-annotated DAG scheduler — WS-C / LLD 31 (FR-2.8, ADR-030, realizes AD-4).

Productionizes the WS20.0 DAG design (LLD 20 §3.4) into the real validation
pipeline: a tier-0 cheap-deterministic frontier that short-circuits before any
model, then a tier-1 parallel-gather of the expensive models (respecting
dependency chains). The scheduler is a REFACTOR with a verdict-equivalence
guarantee — it reproduces the sequential pipeline's final
`(decision, should_deny, winning_source)` tuple (LLD 31 §3).

Public surface (the contract WS-L populates with D1–D7 nodes):
- `CostTier`         — tier-0 / tier-1 cost annotation.
- `ValidatorNode`    — the node descriptor (source, cost_tier, run, depends_on).
- `build_dag(phase)` — the node registry / registration point.
- `run_dag(...)`     — the scheduler entry (same return contract as the
                       sequential `_run_validation_pipeline`).
"""

from __future__ import annotations

from app.services.scheduler.node import CostTier, ValidatorNode
from app.services.scheduler.registry import assert_registration_complete, build_dag
from app.services.scheduler.run import run_dag

__all__ = [
    "CostTier",
    "ValidatorNode",
    "build_dag",
    "run_dag",
    "assert_registration_complete",
]
