"""WS-L M3.2/M3.3 — D3 memory-integrity validator (memory phase)."""
from __future__ import annotations

import pytest

from app.api.models import ValidationRequest, ValidationResult
from app.combiners import Source
from app.validators.memory_write import (
    MemoryWriteValidator,
    compute_mac,
    verify_mac,
)


def _req(memory=None, content_text="a memory candidate"):
    params = {"memory": memory} if memory is not None else {}
    return ValidationRequest(
        request_id="r", session_id="s", agent_id="a", tool_name="write_memory",
        tool_params=params, user_input="", timestamp="2026-07-03T00:00:00Z",
        operation_type="WRITE", phase="memory", content_text=content_text,
    )


def _good_memory(**over):
    mem = {
        "provenance": {"source": "operator_directive", "actor": "admin"},
        "kind": "OPERATOR_DIRECTIVE",
        "trust_weight": 0.9,
        "effects": {},
    }
    mem.update(over)
    return mem


@pytest.mark.asyncio
async def test_d3_missing_provenance_denies():
    result = await MemoryWriteValidator().validate(_req(memory={"kind": "AGENT_INFERENCE"}))
    assert result.should_deny
    assert result.violation_type == "MEMORY_POISONING"


@pytest.mark.asyncio
async def test_d3_untrusted_cannot_self_promote():
    """An untrusted-sourced memory claiming trust_weight > 0.3 → DENY."""
    mem = _good_memory(provenance={"source": "tool_output"}, trust_weight=0.8,
                       kind="TOOL_OUTPUT")
    result = await MemoryWriteValidator().validate(_req(memory=mem))
    assert result.should_deny
    assert result.violation_type == "MEMORY_POISONING"


@pytest.mark.asyncio
async def test_d3_memory_cannot_loosen_security():
    """A memory write expanding allowed_tools / raising a limit / skipping a check
    → MEMORY_POISONING."""
    for effect in ("expand_allowed_tools", "raise_limit", "skip_check"):
        mem = _good_memory(effects={effect: True})
        result = await MemoryWriteValidator().validate(_req(memory=mem))
        assert result.should_deny, f"{effect} should DENY"
        assert result.violation_type == "MEMORY_POISONING"


@pytest.mark.asyncio
async def test_d3_canonicalize_before_hash():
    """The named footgun: two byte-different-but-logically-identical birth facts MAC
    the SAME (canonicalize-before-MAC); a genuinely tampered candidate fails verify."""
    birth_a = {"kind": "OPERATOR_DIRECTIVE", "text": "café  policy\nupdate",
               "actor": "admin"}
    # different Unicode form (NFC vs decomposed), whitespace, and key order — same logical fact.
    birth_b = {"actor": "admin", "text": "café policy update",  # decomposed é + collapsed ws
               "kind": "OPERATOR_DIRECTIVE"}
    mac_a = compute_mac(birth_a)
    assert verify_mac(birth_b, mac_a), "canonicalization must make logically-equal facts MAC equal"

    tampered = {"kind": "OPERATOR_DIRECTIVE", "text": "café policy DELETE", "actor": "admin"}
    assert not verify_mac(tampered, mac_a), "a tampered candidate must fail VerifyMac"


@pytest.mark.asyncio
async def test_d3_tampered_mac_denies():
    """A memory candidate carrying a MAC that does not verify → MEMORY_POISONING."""
    birth = {"kind": "OPERATOR_DIRECTIVE", "text": "grant read"}
    mem = _good_memory(birth_facts=birth, mac="deadbeef" * 8)  # wrong MAC
    result = await MemoryWriteValidator().validate(_req(memory=mem))
    assert result.should_deny
    assert result.violation_type == "MEMORY_POISONING"


@pytest.mark.asyncio
async def test_d3_clean_memory_allows():
    """A well-formed provenance-bearing memory write with a valid MAC → ALLOW."""
    birth = {"kind": "OPERATOR_DIRECTIVE", "text": "allow reporting"}
    mem = _good_memory(birth_facts=birth, mac=compute_mac(birth))
    result = await MemoryWriteValidator().validate(_req(memory=mem))
    assert result.decision == "ALLOW"
    assert result.should_deny is False
    assert result.source == Source.SENTRA_MEMORY


@pytest.mark.asyncio
async def test_d3_source_and_reason():
    result = await MemoryWriteValidator().validate(_req(memory={"kind": "AGENT_INFERENCE"}))
    assert result.source == Source.SENTRA_MEMORY
    assert result.violation_type == "MEMORY_POISONING"


@pytest.mark.asyncio
async def test_d3_advisory_until_enforce():
    """R5-C mirror of D2: advisory until enforce ON."""
    from app.services.scheduler.run import _is_hard_deny
    from app.services.scheduler.registry import _apply_enforce_if

    d3_deny = ValidationResult(
        decision="DENY", reason="MEMORY_POISONING: x", violation_type="MEMORY_POISONING",
        should_deny=True, source=Source.SENTRA_MEMORY,
    )
    assert _is_hard_deny(_apply_enforce_if(d3_deny, enforce=False)) is False
    assert _is_hard_deny(_apply_enforce_if(d3_deny, enforce=True)) is True
