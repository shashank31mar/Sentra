"""WS-L M1.4 INTEG — the boot-time registration-completeness assertion (SEC-5).

Proves the assertion (a) does NOT raise with the current registration, and (b) DOES
raise (fail-fast) when a node carries an unregistered source — not a silent
priority-0 fall-through.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.combiners import Source
from app.services.scheduler import assert_registration_complete, build_dag
from app.services.scheduler.node import CostTier, ValidatorNode


def _svc():
    from app.services.validation_service import ValidationService
    from app.validators.distilled_classifier import DistilledClassifier

    with patch.object(ValidationService, "__init__", lambda self: None):
        svc = ValidationService()
    svc.distilled_classifier = DistilledClassifier()
    return svc


def test_boot_assertion_passes_with_current_registration():
    """The current registration is complete — the boot assertion does not raise."""
    assert_registration_complete(_svc())  # must not raise


def test_boot_assertion_raises_on_unregistered_source():
    """SEC-5 fail-fast: a request-phase node whose source is NOT in DEFAULT_PRIORITIES
    makes the boot assertion RAISE — proving it is a hard boot failure, not a silent
    priority-0 fall-through."""
    real_build_dag = build_dag

    async def _noop(req, sess):
        from app.api.models import ValidationResult
        return ValidationResult(decision="ALLOW", reason="x", should_deny=False)

    def _patched(service, phase, stamp_ctx):
        nodes = real_build_dag(service, phase, stamp_ctx)
        if phase == "request":
            nodes.append(ValidatorNode(
                source="sentra.totally_unregistered",
                cost_tier=CostTier.EXPENSIVE_MODEL,
                run=_noop,
                depends_on=(Source.SENTRA_POLICY,),
                order_key=99,
            ))
        return nodes

    with patch("app.services.scheduler.registry.build_dag", _patched):
        with pytest.raises(RuntimeError, match="registration-incomplete"):
            assert_registration_complete(_svc())
