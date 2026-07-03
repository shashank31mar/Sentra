"""WS-L M1 — shared scaffold: the 8+1 Source taxonomy + priorities + display
labels + boot-time registration-completeness (LLD 32 §9). Plus the FIX-K triple-
equality for the LIVE request-phase D-nodes (M4.4 / M6.1).
"""
from __future__ import annotations

import pytest

from app.combiners import Source
from app.combiners.sources import (
    DEFAULT_PRIORITIES,
    SOURCE_DISPLAY_NAMES,
    STATIC_FALLBACK_ORDER,
    STEP_LABEL_TO_SOURCE,
)


_NEW_SOURCES = {
    "SENTRA_TRAJECTORY": "sentra.trajectory",
    "SENTRA_INDIRECT": "sentra.indirect_injection",
    "SENTRA_MEMORY": "sentra.memory",
    "SENTRA_TAINT": "sentra.taint",
    "SENTRA_OUTPUT_DLP": "sentra.output_dlp",
    "SENTRA_NETWORK": "sentra.network",
    "SENTRA_EGRESS": "sentra.egress",
    "SENTRA_PROVENANCE": "sentra.provenance",
    "SENTRA_ANOMALY": "sentra.anomaly",
    "SENTRA_DISTILLED": "sentra.distilled",
}


# ------------------------------------------------------------------ M1.1
def test_new_source_constants_present():
    """All ten new constants exist with the exact dotted string; distilled is a
    DISTINCT producer (not a reuse of SENTRA_ML_CLASSIFIER)."""
    for attr, value in _NEW_SOURCES.items():
        assert getattr(Source, attr) == value, f"{attr} != {value}"
    assert Source.SENTRA_DISTILLED != Source.SENTRA_ML_CLASSIFIER


# ------------------------------------------------------------------ M1.2
def test_existing_priorities_unchanged():
    """T-COMBINER-CLEAN: the 8 pre-WS-L priority entries are byte-for-byte unchanged
    after the additive WS-L edit. Must fail if any existing value moves."""
    pre_wsl = {
        Source.SENTRA_TRUST: 90,
        Source.SENTRA_POLICY: 80,
        Source.SENTRA_SIGMA: 70,
        Source.SENTRA_ML_CLASSIFIER: 65,
        Source.SENTRA_CONTEXT: 60,
        Source.SENTRA_ABUSE: 50,
        Source.SENTRA_CROSS_AGENT: 50,
        Source.REDACTION_NER: 0,
    }
    for src, prio in pre_wsl.items():
        assert DEFAULT_PRIORITIES[src] == prio, f"existing priority moved: {src}"


def test_new_priorities_values():
    """Each new source maps to its exact LLD 32 §9.2 value + the ordering
    constraints WS-L relies on."""
    expected = {
        Source.SENTRA_NETWORK: 85, Source.SENTRA_TAINT: 78, Source.SENTRA_EGRESS: 77,
        Source.SENTRA_PROVENANCE: 75, Source.SENTRA_TRAJECTORY: 68,
        Source.SENTRA_DISTILLED: 66, Source.SENTRA_OUTPUT_DLP: 63,
        Source.SENTRA_INDIRECT: 62, Source.SENTRA_MEMORY: 58, Source.SENTRA_ANOMALY: 55,
    }
    for src, prio in expected.items():
        assert DEFAULT_PRIORITIES[src] == prio
    # sigma 70 > distilled 66 > ml 65 ; sigma 70 > trajectory 68 > ml 65
    assert 70 > DEFAULT_PRIORITIES[Source.SENTRA_DISTILLED] > 65
    assert 70 > DEFAULT_PRIORITIES[Source.SENTRA_TRAJECTORY] > 65


# ------------------------------------------------------------------ M1.3
def test_display_names_cover_new_sources():
    """Every one of the ten new sources has a non-empty display label."""
    for value in _NEW_SOURCES.values():
        assert SOURCE_DISPLAY_NAMES.get(value), f"missing/empty label for {value}"


# ------------------------------------------------------------------ M1.4
def _svc():
    """A ValidationService with the distilled classifier wired (the only attribute
    build_dag's node factories reference at graph-BUILD time)."""
    from app.services.validation_service import ValidationService
    from app.validators.distilled_classifier import DistilledClassifier
    from unittest.mock import patch

    with patch.object(ValidationService, "__init__", lambda self: None):
        svc = ValidationService()
    svc.distilled_classifier = DistilledClassifier()
    return svc


def test_all_registered_sources_have_priority_and_labels():
    """SEC-5: every registered node source (across request/content/memory) is in
    DEFAULT_PRIORITIES + SOURCE_DISPLAY_NAMES; each REQUEST-phase emitted source is
    in STATIC_FALLBACK_ORDER; each content/memory-only source is NOT (FIX-K)."""
    from app.services.scheduler import build_dag

    svc = _svc()
    fallback = set(STATIC_FALLBACK_ORDER)
    for phase in ("request", "content", "memory"):
        for node in build_dag(svc, phase, {"platform": None, "cloud_region": None}):
            assert node.source in DEFAULT_PRIORITIES, f"{node.source} missing priority"
            assert node.source in SOURCE_DISPLAY_NAMES, f"{node.source} missing label"
            if phase == "request":
                assert node.source in fallback, f"request source {node.source} not in fallback"

    # content/memory-specific sources must NOT be in the request-phase fallback order.
    assert Source.SENTRA_INDIRECT not in fallback
    assert Source.SENTRA_MEMORY not in fallback


# ------------------------------------------------------------------ M4.4 / M6.1 (FIX-K triple-equality)
def test_trajectory_in_request_fallback_order():
    """sentra.trajectory + sentra.distilled are in STATIC_FALLBACK_ORDER, _ORDER, and
    STEP_LABEL_TO_SOURCE.values(); the three sets are co-equal (the trail drift-guard
    triple-equality, invariant #8a); D2/D3 sources are absent from all three."""
    from app.services.scheduler.registry import _ORDER

    fallback = set(STATIC_FALLBACK_ORDER)
    order = set(_ORDER)
    step_vals = set(STEP_LABEL_TO_SOURCE.values())

    assert Source.SENTRA_TRAJECTORY in fallback
    assert Source.SENTRA_DISTILLED in fallback
    assert Source.SENTRA_TRAJECTORY in order and Source.SENTRA_DISTILLED in order
    assert Source.SENTRA_TRAJECTORY in step_vals and Source.SENTRA_DISTILLED in step_vals

    # the triple-equality the live trail drift-guard asserts.
    assert fallback == order == step_vals

    # D2/D3 (content/memory sources) are NEVER in the request-phase surfaces.
    for absent in (Source.SENTRA_INDIRECT, Source.SENTRA_MEMORY):
        assert absent not in fallback
        assert absent not in order
        assert absent not in step_vals


def test_request_emitted_set_equals_fallback_order():
    """FIX-K / T-TRAIL-14(a): the set of sources build_dag('request') emits equals
    STATIC_FALLBACK_ORDER (the emitted request-phase source set)."""
    from app.services.scheduler import build_dag

    svc = _svc()
    emitted = {n.source for n in build_dag(svc, "request", {"platform": None, "cloud_region": None})}
    assert emitted == set(STATIC_FALLBACK_ORDER)
