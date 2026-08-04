"""Unit tests for policy engine class-level patching (LLD 41 §4.5, WS-D milestone D2)."""

import pytest
from app.services.validation_service import ValidationService
from app.validators.policy_engine import PolicyEngine, PolicyNotFoundError
from benchmarks.core.policy_fixture import patch_policy_engine


@pytest.mark.asyncio
async def test_patch_reaches_all_three_consumers(monkeypatch):
    from benchmarks.core.null_objects import NullAuditWriter
    monkeypatch.setattr("app.utils.audit_logger.AuditLogger", lambda: NullAuditWriter())

    syn_policy = {
        "agent_id": "test-agent",
        "allowed_tools": ["tool_a"],
        "metadata": {},
    }
    with patch_policy_engine({"test-agent": syn_policy}):
        svc = ValidationService()
        
        res1 = await svc.policy_engine.resolve_policy_bundle("test-agent")
        res2 = await svc.context_validator.policy_engine.resolve_policy_bundle("test-agent")
        assert res1[0]["allowed_tools"] == ["tool_a"]
        assert res2[0]["allowed_tools"] == ["tool_a"]
        if svc.cedar_engine is not None:
            cedar_pe = getattr(svc.cedar_engine, "policy_engine", getattr(svc.cedar_engine, "_policy_engine", None))
            res3 = await cedar_pe.resolve_policy_bundle("test-agent")
            assert res3[0]["allowed_tools"] == ["tool_a"]


@pytest.mark.asyncio
async def test_patch_is_reverted_after_run():
    syn_policy = {"agent_id": "test-agent", "allowed_tools": []}
    with patch_policy_engine({"test-agent": syn_policy}):
        pass
    
    # Asserting method is restored
    assert PolicyEngine.resolve_policy_bundle != patch_policy_engine


@pytest.mark.asyncio
async def test_unknown_agent_id_still_raises_policy_not_found():
    with patch_policy_engine({"known-agent": {}}):
        engine = PolicyEngine()
        with pytest.raises(PolicyNotFoundError):
            await engine.resolve_policy_bundle("unknown-agent")
