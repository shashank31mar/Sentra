"""WS-L M2.1/M2.2 — phase routing (content/memory INTO the pipeline, AFTER
identity; output stays stubbed) + the phase-aware `all_allow` (FIX-H/FIX-J).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.models import ValidationRequest, ValidationResult
from app.main import app


def _payload(**over):
    base = dict(
        request_id="req-1", session_id="sess-1", agent_id="payment-agent",
        tool_name="ingest_doc", tool_params={}, user_input="",
        timestamp="2026-07-03T00:00:00Z", operation_type="READ",
    )
    base.update(over)
    return base


@pytest.fixture
def client():
    return TestClient(app)


# ------------------------------------------------------------------ M2.1
def test_output_phase_still_stubbed(client):
    """output still returns phase_handler_not_implemented:output (D5 not built)."""
    spy = Mock()
    spy.validate_tool_call = AsyncMock(return_value={"decision": "ALLOW"})
    prev = getattr(app.state, "validation_service", None)
    app.state.validation_service = spy
    try:
        resp = client.post("/v1/validate", json=_payload(phase="output"))
        assert resp.status_code == 200
        assert resp.json()["reason"] == "phase_handler_not_implemented:output"
        spy.validate_tool_call.assert_not_awaited()
    finally:
        app.state.validation_service = prev


def test_content_memory_phase_requires_identity_gate():
    """FIX-I / SEC-13: with identity ENFORCE + a spoofed/unverified caller, a
    content-phase call returns the IDENTITY DENY and the pipeline (the D2 node) is
    NEVER reached. Pins that D-nodes never run before identity resolves."""
    from app.api import routes as routes_mod
    from app.api import deps as deps_mod

    spy = Mock()
    spy.validate_tool_call = AsyncMock(return_value={"decision": "ALLOW"})

    # identity resolves to a should_deny state (enforce + unverified/spoofed).
    ctx = Mock(state="tampered", should_deny=True, should_route=False,
               is_verified=False, claimed_tenant_id="t1", agent_id="payment-agent",
               tenant_id=None, reason="IDENTITY_TAMPERED")

    client = TestClient(app)
    prev = getattr(app.state, "validation_service", None)
    app.state.validation_service = spy
    try:
        # resolve_tenant_from_jwt is imported INSIDE the handler from app.api.deps —
        # patch it at its source module. _identity_deny is a routes-module function.
        with patch.object(deps_mod, "resolve_tenant_from_jwt", AsyncMock(return_value=ctx)), \
             patch.object(routes_mod, "_identity_deny",
                          AsyncMock(return_value={"decision": "DENY", "reason": "IDENTITY_TAMPERED",
                                                  "violation_type": "IDENTITY_TAMPERED",
                                                  "session_id": "sess-1", "trust_score": 0.0,
                                                  "latency_ms": 0.0})):
            resp = client.post("/v1/validate", json=_payload(phase="content", content_text="doc"))
        assert resp.status_code == 200
        body = resp.json()
        assert body["decision"] == "DENY"
        assert body["reason"] == "IDENTITY_TAMPERED"
        # The pipeline (and therefore the D2 node) was never reached.
        spy.validate_tool_call.assert_not_awaited()
    finally:
        app.state.validation_service = prev


# ------------------------------------------------------------------ M2.2 (phase-aware all_allow / FIX-H, FIX-J)
def _pipeline_svc(session):
    """A ValidationService whose validators ALLOW, for driving _run_validation_pipeline
    directly (offline). The NER barrier is patched to a no-op in the content tests."""
    from app.services.validation_service import ValidationService
    from app.validators.distilled_classifier import DistilledClassifier

    with patch.object(ValidationService, "__init__", lambda self: None):
        svc = ValidationService()
    svc.cedar_engine = None
    allow = ValidationResult(decision="ALLOW", reason="ok", should_deny=False)
    svc.trust_checker = Mock(); svc.trust_checker.check = AsyncMock(return_value=allow)
    svc.policy_engine = Mock()
    svc.policy_engine.validate = AsyncMock(return_value=allow)
    svc.policy_engine.get_agent_policy = AsyncMock(return_value={"rate_limit": 100})
    svc.policy_engine.get_agent_cloud_identity = Mock(return_value=(None, None))
    svc.cross_agent_validator = Mock()
    svc.cross_agent_validator.validate = AsyncMock(return_value=allow)
    svc.sigma_engine = Mock()
    svc.sigma_engine.match_rules = AsyncMock(return_value=allow)
    svc.context_validator = Mock()
    svc.context_validator.validate_sequence = AsyncMock(return_value=allow)
    svc.abuse_detector = Mock()
    svc.abuse_detector.check_rate_limit = AsyncMock(return_value=allow)
    svc.ml_classifier = Mock()
    svc.ml_classifier.validate = AsyncMock(return_value=ValidationResult.abstain("off"))
    svc.distilled_classifier = DistilledClassifier()
    svc.metrics_publisher = Mock()
    svc.metrics_publisher.publish_node_metrics = AsyncMock()
    return svc


_SESSION = {"session_id": "s", "agent_id": "a", "trust_score": 80.0, "action_count": 1}


def _req(**over):
    base = dict(
        request_id="r", session_id="s", agent_id="a", tool_name="ingest",
        tool_params={}, user_input="", timestamp="2026-07-03T00:00:00Z",
        operation_type="READ",
    )
    base.update(over)
    return ValidationRequest(**base)


@pytest.mark.asyncio
async def test_content_no_denier_fails_secure():
    """FIX-H / invariant 5: a content run where the D2 node ABSTAINs (empty
    content_text → D2 abstain) terminates in DENY phase_handler_abstain:content, NOT
    a synthetic ALLOW."""
    svc = _pipeline_svc(_SESSION)
    # empty content_text → NER barrier abstains, D2 abstains (nothing to inspect).
    req = _req(phase="content", content_text="")
    result, _ = await svc._run_validation_pipeline(req, dict(_SESSION))
    assert result.should_deny
    assert result.reason == "phase_handler_abstain:content"


@pytest.mark.asyncio
async def test_request_all_allow_unchanged():
    """A request run with no denier still returns the synthetic ALLOW (T-EQUIV)."""
    svc = _pipeline_svc(_SESSION)
    result, _ = await svc._run_validation_pipeline(_req(phase="request"), dict(_SESSION))
    assert result.decision == "ALLOW"
    assert result.should_deny is False
    assert result.reason == "All validation checks passed"


@pytest.mark.asyncio
async def test_phase_resolution_hoisted_no_unbound():
    """FIX-J regression pin: a content run does NOT raise UnboundLocalError (the
    `phase` binding is hoisted above the `_all_allow` closure)."""
    svc = _pipeline_svc(_SESSION)
    # Just running the content pipeline without an UnboundLocalError is the assertion.
    result, _ = await svc._run_validation_pipeline(_req(phase="content", content_text=""), dict(_SESSION))
    assert result is not None
