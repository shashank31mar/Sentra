"""WS-E2 / LLD 29 §5.4 (E4.4, F7) — the NO-RAW-PHI invariant must hold even on a
CRASH. An uncaught exception (or a frame-local-capturing APM like Sentry/Datadog)
would otherwise expose the raw `ValidationRequest` (tool_params/user_input/
content_text) sitting in the outer `validate_tool_call` frame's locals.

This pins the strip-early control (E4.4 option 1 + the option-2 assertion): after
`validate_tool_call` runs — on BOTH the normal-return and the mid-pipeline-exception
paths — the raw content fields are scrubbed off the request object, so nothing raw
lingers in this frame for a traceback / APM to capture.

Non-vacuous: with the `finally: _scrub_raw_content(request)` removed, the raw PAN/SSN
survive on the request object and these asserts FAIL.
"""
import asyncio
import json
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.api.models import ValidationRequest, ValidationResult
from app.services.validation_service import ValidationService, _scrub_raw_content

_RAW_PAN = "4111111111111111"
_RAW_SSN = "123-45-6789"


def _raw_request() -> ValidationRequest:
    return ValidationRequest(
        request_id="req-f7", session_id="sess-f7", agent_id="acme-payments-agent",
        tool_name="process_refund",
        tool_params={"card": _RAW_PAN, "note": f"ssn {_RAW_SSN}"},
        user_input=f"refund to card {_RAW_PAN}",
        timestamp="2026-07-02T10:00:00Z", operation_type="WRITE",
    )


def test_scrub_removes_raw_content_leaves_structure():
    """Unit: _scrub_raw_content zeroes the content fields, keeps structural ones."""
    req = _raw_request()
    _scrub_raw_content(req)
    blob = json.dumps({"tp": req.tool_params, "ui": req.user_input})
    assert _RAW_PAN not in blob and _RAW_SSN not in blob
    assert req.tool_params == {}
    assert req.user_input == "⟦scrubbed⟧"
    # structural identity preserved (still auditable / traceable)
    assert req.agent_id == "acme-payments-agent"
    assert req.tool_name == "process_refund"
    assert req.request_id == "req-f7"


@pytest.mark.asyncio
async def test_request_scrubbed_after_normal_return():
    """After a normal validate_tool_call return, the request object carries NO raw
    content (the finally scrubbed it), so it can't leak from this frame later."""
    svc = ValidationService()
    req = _raw_request()
    svc.session_manager = Mock()
    svc.session_manager.get_or_create_session = AsyncMock(return_value={"trust_score": 90.0})
    allow = ValidationResult(decision="ALLOW", reason="OK", should_deny=False)
    with patch.object(svc, "_run_validation_pipeline", AsyncMock(return_value=(allow, []))), \
         patch.object(svc, "_handle_allow", AsyncMock(return_value={"decision": "ALLOW", "latency_ms": 1.0})):
        await svc.validate_tool_call(req)
    blob = json.dumps({"tp": req.tool_params, "ui": req.user_input})
    assert _RAW_PAN not in blob and _RAW_SSN not in blob
    assert req.tool_params == {}


@pytest.mark.asyncio
async def test_request_scrubbed_after_midpipeline_crash():
    """THE F7 case: the pipeline raises mid-flight. UPDATED for WS-F F6.6 (§6f 1+2):
    `validate_tool_call` no longer returns a fabricated 200-DENY on a crash — it RAISES
    `PipelineError` (mapped to an honest 5XX at the HTTP boundary). The scrub-on-crash
    invariant this test protects STILL holds: the `finally: _scrub_raw_content(request)`
    runs on the raise path too, so the raw PAN/SSN are absent from the frame's `request`
    locals a traceback/APM would capture — even though the exception propagates."""
    from app.services.validation_service import PipelineError

    svc = ValidationService()
    req = _raw_request()
    svc.session_manager = Mock()
    svc.session_manager.get_or_create_session = AsyncMock(return_value={"trust_score": 90.0})
    boom = RuntimeError("simulated mid-pipeline crash")
    with patch.object(svc, "_run_validation_pipeline", AsyncMock(side_effect=boom)):
        # honest 5XX contract: the crash PROPAGATES (no fake 200-DENY)
        with pytest.raises(PipelineError):
            await svc.validate_tool_call(req)
    # and the raw content is STILL GONE from the request object the frame held (the
    # finally scrubbed it before the raise unwound the frame) — the actual invariant.
    blob = json.dumps({"tp": req.tool_params, "ui": req.user_input})
    assert _RAW_PAN not in blob, "raw PAN survived on the request frame-local after a crash (F7 leak)"
    assert _RAW_SSN not in blob, "raw SSN survived on the request frame-local after a crash (F7 leak)"
