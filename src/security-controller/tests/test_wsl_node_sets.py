"""WS-L M1.5 — the per-phase node-set builder + the T-EQUIV request golden list.

The request-phase DAG is frozen EXCEPT the two additive WS-L request nodes
(distilled M6 + trajectory M4); the existing 7 nodes and their edges do not move
(FIX-E). content/memory return their own deep-detector node sets (NO action floor,
invariant 4).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.combiners import Source
from app.services.scheduler import build_dag
from app.services.scheduler.node import CostTier


def _svc():
    from app.services.validation_service import ValidationService
    from app.validators.distilled_classifier import DistilledClassifier

    with patch.object(ValidationService, "__init__", lambda self: None):
        svc = ValidationService()
    svc.distilled_classifier = DistilledClassifier()
    return svc


def _tuple(node):
    return (node.source, node.cost_tier, node.depends_on, node.order_key)


# The frozen golden snapshot of the request DAG AFTER WS-L (the 7 existing nodes
# BYTE-FOR-BYTE + the two additive WS-L nodes). The existing 7 keep their source /
# cost_tier / order_key; the only edit to an existing node is ml's depends_on
# re-point to (SENTRA_DISTILLED,) (M6.1). Must fail if any EXISTING node moves.
_GOLDEN_REQUEST = [
    (Source.SENTRA_TRUST, CostTier.DETERMINISTIC, (), 1),
    (Source.SENTRA_POLICY, CostTier.DETERMINISTIC, (Source.SENTRA_TRUST,), 2),
    (Source.SENTRA_CROSS_AGENT, CostTier.DETERMINISTIC, (Source.SENTRA_POLICY,), 3),
    (Source.SENTRA_SIGMA, CostTier.DETERMINISTIC, (Source.SENTRA_POLICY,), 4),
    (Source.SENTRA_CONTEXT, CostTier.DETERMINISTIC, (Source.SENTRA_POLICY,), 5),
    (Source.SENTRA_ABUSE, CostTier.DETERMINISTIC, (Source.SENTRA_POLICY,), 6),
    (Source.SENTRA_ML_CLASSIFIER, CostTier.EXPENSIVE_MODEL, (Source.SENTRA_DISTILLED,), 7),
    (Source.SENTRA_DISTILLED, CostTier.EXPENSIVE_MODEL, (Source.SENTRA_POLICY,), 8),
    (Source.SENTRA_TRAJECTORY, CostTier.EXPENSIVE_MODEL, (Source.SENTRA_POLICY,), 9),
]


def test_request_phase_dag_unchanged():
    """T-EQUIV golden-list: build_dag('request') returns exactly the golden node
    tuples. The 7 existing nodes are byte-for-byte (source/cost_tier/order_key), the
    only edit to an existing node is ml's depends_on re-point to distilled (M6.1);
    the two WS-L nodes (distilled + trajectory) are the sole additions."""
    nodes = build_dag(_svc(), "request", {"platform": None, "cloud_region": None})
    assert [_tuple(n) for n in nodes] == _GOLDEN_REQUEST


def test_content_phase_node_set():
    """The content branch returns exactly [redaction.ner, trust, abuse,
    indirect_injection] — NOT the action floor (invariant 4)."""
    nodes = build_dag(_svc(), "content", {"platform": None, "cloud_region": None})
    assert [n.source for n in nodes] == [
        Source.REDACTION_NER, Source.SENTRA_TRUST, Source.SENTRA_ABUSE,
        Source.SENTRA_INDIRECT,
    ]
    sources = {n.source for n in nodes}
    for absent in (Source.SENTRA_POLICY, Source.SENTRA_CROSS_AGENT, Source.SENTRA_CONTEXT):
        assert absent not in sources


def test_memory_phase_node_set():
    """The memory branch returns exactly [redaction.ner, trust, abuse, memory] —
    NOT the action floor (invariant 4)."""
    nodes = build_dag(_svc(), "memory", {"platform": None, "cloud_region": None})
    assert [n.source for n in nodes] == [
        Source.REDACTION_NER, Source.SENTRA_TRUST, Source.SENTRA_ABUSE,
        Source.SENTRA_MEMORY,
    ]
    sources = {n.source for n in nodes}
    for absent in (Source.SENTRA_POLICY, Source.SENTRA_CROSS_AGENT, Source.SENTRA_CONTEXT):
        assert absent not in sources


def test_distilled_killswitch_off_restores_byte_identical_request_graph():
    """With the distilled kill-switch OFF, the request DAG has NO distilled node and
    ml.depends_on reverts to (SENTRA_POLICY,) — the byte-identical rollback graph
    (only trajectory is added, the additive D1 node)."""
    from app.config import settings

    with patch.object(settings, "distilled_enabled", False):
        nodes = build_dag(_svc(), "request", {"platform": None, "cloud_region": None})
    sources = {n.source for n in nodes}
    assert Source.SENTRA_DISTILLED not in sources
    ml = next(n for n in nodes if n.source == Source.SENTRA_ML_CLASSIFIER)
    assert ml.depends_on == (Source.SENTRA_POLICY,)
