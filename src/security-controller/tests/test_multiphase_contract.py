"""WS-B — multi-phase /v1/validate contract (LLD 30).

Covers the server half of the additive `phase` surface:
  * B1: the `phase` / `content_text` fields + `KNOWN_PHASES` + `_CONTENT_FIELD`
    on `ValidationRequest` (additive, defaulted, enum-narrowed).
  * B2: the handler routing — unknown phase → 422 (a validation error, NOT a
    verdict, NOT metered); known-but-unbuilt phase → 200 fail-secure DENY
    (`_phase_not_implemented_deny`, audited + metered); `request` unchanged.

The routing tests drive the real app over a `TestClient` and patch the process
`validation_service` / audit / metrics seams so no AWS is touched. Identity is
OFF by default (`tenant_identity_mode == "off"`), so the request path is
byte-identical to pre-WS-B and resolves straight to `validation_service`.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.models import KNOWN_PHASES, ValidationRequest, _CONTENT_FIELD
from app.main import app


# --------------------------------------------------------------------------- helpers

def _today_payload(**overrides):
    """A today-shaped ValidationRequest kwargs dict (no phase/content_text)."""
    base = dict(
        request_id="req-1",
        session_id="sess-1",
        agent_id="payment-agent",
        tool_name="process_refund",
        tool_params={"order_id": "ORD-1", "amount": 10.0},
        user_input="refund order ORD-1",
        timestamp="2026-07-01T00:00:00Z",
        operation_type="WRITE",
    )
    base.update(overrides)
    return base


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def spy_service():
    """Replace the process-wide validation_service with a spy that returns ALLOW.

    Lets the routing tests assert whether the request pipeline was reached
    (request phase) vs bypassed (known-but-unbuilt / unknown phase) without any
    real validators / AWS.
    """
    svc = Mock()
    svc.validate_tool_call = AsyncMock(
        return_value={
            "decision": "ALLOW", "reason": "ok", "trust_score": 99.0,
            "session_id": "sess-1", "latency_ms": 1.0,
        }
    )
    prev = getattr(app.state, "validation_service", None)
    app.state.validation_service = svc
    try:
        yield svc
    finally:
        app.state.validation_service = prev


@pytest.fixture
def spy_deny_seams():
    """Patch the audit + metrics seams the phase-DENY helper fires, so we can
    assert the metering split without touching CloudWatch/DynamoDB."""
    with patch("app.utils.audit_logger.AuditLogger") as audit_cls, \
         patch("app.utils.metrics_publisher.MetricsPublisher") as metrics_cls:
        audit = Mock()
        audit.log_decision = AsyncMock(return_value=None)
        audit_cls.return_value = audit
        metrics = Mock()
        metrics.publish_validation_metrics = AsyncMock(return_value=None)
        metrics_cls.return_value = metrics
        yield {"audit": audit, "metrics": metrics}


# ===================================================================== B1.1 phase

def test_phase_defaults_to_request():
    """A ValidationRequest built with no `phase` defaults to "request" and
    carries no content_text (invariant 1 — additive + defaulted)."""
    req = ValidationRequest(**_today_payload())
    assert req.phase == "request"
    assert req.content_text is None


def test_unknown_phase_422_at_validation(client):
    """An unknown `phase` is a validation error, NOT a verdict.

    Model level: constructing raises Pydantic ValidationError. Over the app: a
    POST with a typo'd phase returns HTTP 422 and the body is NOT a DENY verdict.
    Must fail if the Literal narrowing is removed (§2.1)."""
    with pytest.raises(ValidationError):
        ValidationRequest(**_today_payload(phase="reqest"))

    resp = client.post("/v1/validate", json=_today_payload(phase="reqest"))
    assert resp.status_code == 422
    # A 422 is a framework validation error, not a decision body.
    assert resp.json().get("decision") != "DENY"


def test_existing_caller_no_phase_unchanged():
    """A today-shaped payload (no phase/content_text keys) round-trips clean and
    `model_dump(exclude_defaults=True)` carries neither key — additivity is
    byte-clean on the wire (invariant 1)."""
    req = ValidationRequest(**_today_payload())
    dumped = req.model_dump(exclude_defaults=True)
    assert "phase" not in dumped
    assert "content_text" not in dumped
    # The pre-existing required fields are unchanged.
    assert req.tool_name == "process_refund"
    assert req.operation_type == "WRITE"


# ===================================================================== B1.2 KNOWN_PHASES

def test_known_phases_is_single_source():
    """The `phase` Literal accepts EXACTLY the members of KNOWN_PHASES: each
    member constructs, and a value outside the set raises (§2.2)."""
    assert KNOWN_PHASES == frozenset({"request", "content", "output", "memory"})
    for p in KNOWN_PHASES:
        req = ValidationRequest(**_today_payload(phase=p))
        assert req.phase == p
    with pytest.raises(ValidationError):
        ValidationRequest(**_today_payload(phase="not-a-phase"))


# ===================================================================== B1.3 content_text + map

def test_content_text_defaults_none_and_additive():
    req = ValidationRequest(**_today_payload())
    assert req.content_text is None
    assert "content_text" not in req.model_dump(exclude_defaults=True)


def test_content_field_map_is_canonical():
    """_CONTENT_FIELD maps content/output/memory → "content_text" (one field, not
    per-phase *_body), has exactly those keys, and every value names a real
    ValidationRequest field (§2.3)."""
    assert _CONTENT_FIELD == {
        "content": "content_text",
        "output": "content_text",
        "memory": "content_text",
    }
    assert set(_CONTENT_FIELD) == {"content", "output", "memory"}
    fields = set(ValidationRequest.model_fields)
    for field_name in _CONTENT_FIELD.values():
        assert field_name in fields, f"_CONTENT_FIELD names a non-field: {field_name}"


# ===================================================================== B2.1 routing

def test_request_phase_pipeline_unchanged(client, spy_service):
    """phase="request" (and absent) reaches validation_service.validate_tool_call
    — the request pipeline is untouched by WS-B (§3.5 + no-op guarantee)."""
    resp = client.post("/v1/validate", json=_today_payload())  # no phase → request
    assert resp.status_code == 200
    assert resp.json()["decision"] == "ALLOW"
    spy_service.validate_tool_call.assert_awaited_once()

    spy_service.validate_tool_call.reset_mock()
    resp = client.post("/v1/validate", json=_today_payload(phase="request"))
    assert resp.status_code == 200
    spy_service.validate_tool_call.assert_awaited_once()


def test_unknown_phase_not_counted_in_deny_metrics(client, spy_service, spy_deny_seams):
    """After a phase="reqest" 422, the metric-publish path was NOT invoked and
    the service was NOT called — a 4XX is not a metered verdict (§9)."""
    resp = client.post("/v1/validate", json=_today_payload(phase="reqest"))
    assert resp.status_code == 422
    spy_service.validate_tool_call.assert_not_awaited()
    spy_deny_seams["metrics"].publish_validation_metrics.assert_not_awaited()


# ===================================================================== B2.2 known-but-unbuilt DENY

@pytest.mark.parametrize("phase", ["content", "output", "memory"])
def test_known_unbuilt_phase_denies(client, spy_service, spy_deny_seams, phase):
    """A known-but-unbuilt phase → 200 fail-secure DENY with the canonical reason
    + violation_type, routed-but-stubbed (service NOT called), never ALLOW.
    Must fail if the guard is removed or the phase is routed to request (§3.2)."""
    resp = client.post("/v1/validate", json=_today_payload(phase=phase))
    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == "DENY"
    assert body["decision"] != "ALLOW"
    assert body["reason"].startswith("phase_handler_not_implemented:")
    assert body["reason"] == f"phase_handler_not_implemented:{phase}"
    assert body["violation_type"] == "PHASE_UNHANDLED"
    # Routed-but-stubbed: the request pipeline was NEVER reached.
    spy_service.validate_tool_call.assert_not_awaited()


def test_phase_deny_body_shape(client, spy_service, spy_deny_seams):
    """The DENY dict has exactly the keys the SDK `_parse_decision` reads, so the
    SDK parses it as a clean DENY (not a default-DENY fallback)."""
    resp = client.post("/v1/validate", json=_today_payload(phase="content"))
    body = resp.json()
    assert set(body) == {
        "decision", "reason", "session_id", "trust_score",
        "latency_ms", "violation_type",
    }


def test_known_unbuilt_phase_is_metered_as_a_deny(client, spy_service, spy_deny_seams):
    """The known-but-unbuilt DENY DOES flow through the metric-publish path
    (contrast the unknown-phase 422). Pins §9's split."""
    resp = client.post("/v1/validate", json=_today_payload(phase="content"))
    assert resp.status_code == 200
    spy_deny_seams["metrics"].publish_validation_metrics.assert_awaited_once()
    spy_deny_seams["audit"].log_decision.assert_awaited_once()


def test_known_but_unbuilt_vs_unknown_are_distinct(client, spy_service, spy_deny_seams):
    """content → 200 DENY phase_handler_not_implemented:content; reqest → 422 (no
    verdict); neither ALLOWs (§3.1)."""
    r_known = client.post("/v1/validate", json=_today_payload(phase="content"))
    assert r_known.status_code == 200
    assert r_known.json()["decision"] == "DENY"
    assert r_known.json()["reason"] == "phase_handler_not_implemented:content"

    r_unknown = client.post("/v1/validate", json=_today_payload(phase="reqest"))
    assert r_unknown.status_code == 422
    assert r_unknown.json().get("decision") != "ALLOW"
    assert r_known.json()["decision"] != "ALLOW"


# ============================================================ B2.3 metering resiliency

@pytest.mark.asyncio
async def test_phase_deny_meters_even_when_audit_fails():
    """§9 metering split is resilient to an audit failure.

    `_phase_not_implemented_deny` guards audit and metrics as TWO INDEPENDENT
    (sibling) seams: if `AuditLogger.log_decision` raises, the phase-DENY must
    STILL flow through `publish_validation_metrics` so it appears in the
    `Decisions` stream as a DENY (LLD 30 §9) — a known-but-unbuilt-phase DENY on
    which audit fails must not be silently un-metered.

    This FAILS on the pre-fix nesting (metrics try nested inside the audit try):
    an audit exception jumped to the outer except and the metric publish was
    never reached. Drives the helper directly with a metrics spy + an audit that
    raises, and asserts the metric was published anyway and the DENY is intact."""
    from app.api.models import ValidationRequest
    from app.api.routes import _phase_not_implemented_deny

    req = ValidationRequest(**_today_payload(phase="content"))

    audit = Mock()
    audit.log_decision = AsyncMock(side_effect=RuntimeError("audit backend down"))
    metrics = Mock()
    metrics.publish_validation_metrics = AsyncMock(return_value=None)

    with patch("app.utils.audit_logger.AuditLogger", return_value=audit), \
         patch("app.utils.metrics_publisher.MetricsPublisher", return_value=metrics):
        body = await _phase_not_implemented_deny(
            req, reason="phase_handler_not_implemented:content"
        )

    # Audit was attempted (and raised) — the metric publish must STILL have fired.
    audit.log_decision.assert_awaited_once()
    metrics.publish_validation_metrics.assert_awaited_once()
    # And the DENY the SDK contract expects is returned unchanged despite audit failing.
    assert body["decision"] == "DENY"
    assert body["reason"] == "phase_handler_not_implemented:content"
    assert body["violation_type"] == "PHASE_UNHANDLED"


# ============================================================ B2.4 GUARD 1 defensive branch

@pytest.mark.asyncio
async def test_out_of_set_phase_bypassing_literal_422s_never_denies(spy_service, spy_deny_seams):
    """GUARD 1 (routes.py) — a phase OUTSIDE KNOWN_PHASES that bypassed the Pydantic
    Literal (a `model_construct`-style hand-built request / future internal call)
    re-raises the SAME 422 the Literal produces — it must NEVER fall into the
    known-but-unbuilt DENY path and pollute the `Decisions` metric with a typo
    (LLD 30 §3.1, §9). Normal HTTP can't reach this branch (the Literal 422s at
    deserialization), so it is exercised by constructing the request unvalidated
    and calling the handler directly.

    Must FAIL if GUARD 1 is removed: without it a bare `!= "request"` compare would
    route the out-of-set phase to `_phase_not_implemented_deny` (a phantom verdict)
    instead of raising 422 — so this asserts BOTH the 422 AND that neither the
    audit nor the metric-publish seam was touched."""
    from fastapi import HTTPException

    from app.api.models import ValidationRequest
    from app.api.routes import validate_tool_call

    # model_construct skips validation → a phase the Literal would have rejected.
    bad = ValidationRequest.model_construct(**_today_payload(phase="not-a-phase"))
    assert bad.phase == "not-a-phase"  # the Literal was genuinely bypassed

    http_request = Mock()
    http_request.headers = {}  # .get("x-forwarded-for") → None
    http_request.client = None

    with pytest.raises(HTTPException) as exc_info:
        await validate_tool_call(bad, http_request)

    assert exc_info.value.status_code == 422
    # NOT a verdict: neither the service pipeline nor the DENY audit/metric seams ran.
    spy_service.validate_tool_call.assert_not_awaited()
    spy_deny_seams["audit"].log_decision.assert_not_awaited()
    spy_deny_seams["metrics"].publish_validation_metrics.assert_not_awaited()
