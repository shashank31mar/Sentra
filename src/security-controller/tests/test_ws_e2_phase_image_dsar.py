"""WS-E2 — E1.0 phase-contract VERIFY + image-mode router (E6) + DSAR route + the
additive redaction fields on ValidationRequest.

E1.0 is VERIFY-ONLY (WS-B owns `phase`/`content_text`/`KNOWN_PHASES`/`_CONTENT_FIELD`
on main): assert `content_text` is the field the NER node redacts for content/
output/memory and that `phase` narrows to KNOWN_PHASES — WITHOUT re-adding the field.
"""
from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from pydantic import ValidationError

from app.api.models import (
    KNOWN_PHASES,
    ValidationRequest,
    _CONTENT_FIELD,
)
from app.redaction.image_mode import (
    DEFAULT_IMAGE_MODE,
    REDACT_ENGINE_GAPS,
    ImageMode,
    resolve_image_mode,
    route_image_field,
)


def _payload(**over):
    base = dict(
        request_id="r", session_id="s", agent_id="a", tool_name="t",
        tool_params={}, user_input="hi", timestamp="2026-07-02T00:00:00Z",
        operation_type="READ",
    )
    base.update(over)
    return base


# ============================================================ E1.0 phase VERIFY-ONLY

def test_content_field_map_targets_content_text():
    """_CONTENT_FIELD maps content/output/memory → the `content_text` field the
    NER node redacts (VERIFY WS-B's contract; do not re-add)."""
    assert _CONTENT_FIELD == {"content": "content_text", "output": "content_text", "memory": "content_text"}
    fields = set(ValidationRequest.model_fields)
    for phase, field_name in _CONTENT_FIELD.items():
        assert field_name in fields
        req = ValidationRequest(**_payload(phase=phase, content_text="doc body"))
        # The field the barrier reads/redacts is exactly this one.
        assert getattr(req, field_name) == "doc body"


def test_phase_narrows_to_known_phases():
    assert KNOWN_PHASES == frozenset({"request", "content", "output", "memory"})
    for p in KNOWN_PHASES:
        assert ValidationRequest(**_payload(phase=p)).phase == p
    with pytest.raises(ValidationError):
        ValidationRequest(**_payload(phase="typo"))


# =========================================== additive redaction fields (WS-E, §3.3/§5.3)

def test_redaction_fields_additive_and_defaulted():
    """`redaction_nonce`/`redacted` are additive + defaulted so a pre-redaction
    caller is byte-identical on the wire (neither key appears in exclude_defaults)."""
    req = ValidationRequest(**_payload())
    assert req.redaction_nonce is None
    assert req.redacted is False
    dumped = req.model_dump(exclude_defaults=True)
    assert "redaction_nonce" not in dumped
    assert "redacted" not in dumped


def test_redaction_fields_round_trip():
    req = ValidationRequest(**_payload(redaction_nonce="abcd", redacted=True))
    assert req.redaction_nonce == "abcd"
    assert req.redacted is True


# ==================================================================== E6 image mode

def test_image_mode_defaults_block():
    """A tool with no explicit mode → BLOCK (fail-secure). NEVER EVALUATE (§3.6
    FOOTGUN — a default-evaluate would pass raw pixels)."""
    assert resolve_image_mode(None) is ImageMode.BLOCK
    assert DEFAULT_IMAGE_MODE is ImageMode.BLOCK


def test_image_mode_resolves_each_mode():
    assert resolve_image_mode("evaluate") is ImageMode.EVALUATE
    assert resolve_image_mode("redact") is ImageMode.REDACT
    assert resolve_image_mode("block") is ImageMode.BLOCK
    # Case / whitespace tolerant.
    assert resolve_image_mode(" EVALUATE ") is ImageMode.EVALUATE


def test_image_mode_unresolvable_fails_to_block():
    """An unknown/malformed mode fails toward BLOCK (tenet 1). Must FAIL if the
    default were EVALUATE."""
    assert resolve_image_mode("passthru-raw") is ImageMode.BLOCK
    assert resolve_image_mode("") is ImageMode.BLOCK
    assert route_image_field("nonsense") is ImageMode.BLOCK


def test_redact_engine_named_gaps():
    """The two steps the later `redact`-engine does NOT cover are named, not assumed
    done (§3.6 / E6.3): faces + DICOM metadata."""
    assert set(REDACT_ENGINE_GAPS) == {"faces", "dicom_metadata"}


# ==================================================================== DSAR route (E5.4)

@pytest.mark.asyncio
async def test_dsar_no_tenant_is_403():
    """A caller with no resolvable tenant (identity off → `default`, no X-Tenant-Id)
    is a 403 — never a silent fleet-wide delete."""
    from fastapi import HTTPException
    from app.api.routes import delete_feedback_subject

    with pytest.raises(HTTPException) as exc:
        await delete_feedback_subject("loc-abc", x_tenant_id=None, operator_email="op@x")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_dsar_scopes_delete_to_caller_tenant():
    """The DSAR route binds the delete to the caller's tenant — it never passes a
    cross-tenant id to the store. Assert the store is called with the header
    tenant."""
    from app.api.routes import delete_feedback_subject

    fake_store = Mock()
    fake_store.delete_subject = Mock(return_value=3)
    with patch("app.redaction.feedback_store.get_feedback_store", return_value=fake_store):
        result = await delete_feedback_subject(
            "loc-abc", x_tenant_id="t_caller", operator_email="op@x"
        )
    assert result["deleted"] == 3
    assert result["tenant_id"] == "t_caller"
    # The store was scoped to the caller's tenant — never a different one.
    _args, kwargs = fake_store.delete_subject.call_args
    assert kwargs["tenant_id"] == "t_caller"
