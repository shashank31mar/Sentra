"""Unit tests for CedarPolicyEngine (CT04).

Proves the engine reproduces `policy_engine`'s full signal contract — decision,
violation_type, violated_policy AND penalty — plus the invoke_agent two-call
semantics and the cross-cloud superset. The loader is stubbed so this is a pure
engine test (no DynamoDB/S3): it returns the real baseline Cedar policy set and a
structured policy dict, exactly what the live loader yields post-migration.
"""
import pytest

from app.api.models import ValidationRequest
from app.validators.cedar.engine import CedarPolicyEngine
from app.validators.cedar.policy_loader import LoadedCedarPolicy, PolicyNotMigratedError
from app.validators.cedar.schema import get_baseline_policies
from app.validators.policy_engine import PolicyDisabledError, PolicyNotFoundError


def _request(tool_name, tool_params=None, agent_id="agent-1"):
    return ValidationRequest(
        request_id="req-1", session_id="sess-1", agent_id=agent_id,
        tool_name=tool_name, tool_params=tool_params or {},
        user_input="x", timestamp="2026-06-12T00:00:00Z", operation_type="WRITE")


class _FakeLoader:
    """Stub CedarPolicyLoader: serves the baseline policy set + a fixed structured
    policy, or raises a resolution error to exercise the error paths."""

    def __init__(self, policy=None, raises=None):
        self._policy = policy
        self._raises = raises

    async def load(self, agent_id):
        if self._raises is not None:
            raise self._raises
        policy = dict(self._policy or {})
        policy.setdefault("platform", "bedrock")
        policy.setdefault("cloud_region", "us-east-1")
        return LoadedCedarPolicy(
            policy=policy, metadata={"policy_format": "cedar"},
            agent={"platform": "bedrock"}, compiled_cedar=get_baseline_policies())


def _engine(policy=None, raises=None):
    eng = CedarPolicyEngine()
    eng._loader = _FakeLoader(policy=policy, raises=raises)
    eng._policy_engine.get_agent_cloud_identity = lambda agent_id: ("bedrock", "us-east-1")
    return eng


BASE_POLICY = {
    "allowed_tools": ["get_balance", "process_refund", "verify_identity", "invoke_agent"],
    "allowed_agents": ["helper-agent"],
    "max_refund_amount": 5000,  # dollars (structured source); engine converts to cents
}


# --- tool allow-list -------------------------------------------------------

@pytest.mark.asyncio
async def test_allowed_tool_allows():
    res = await _engine(BASE_POLICY).validate(_request("get_balance"))
    assert res.decision == "ALLOW"
    assert res.penalty == 0
    assert res.platform == "bedrock" and res.cloud_region == "us-east-1"


@pytest.mark.asyncio
async def test_unauthorized_tool():
    res = await _engine(BASE_POLICY).validate(_request("secretsmanager.get"))
    assert res.decision == "DENY"
    assert res.violation_type == "UNAUTHORIZED_TOOL"
    assert res.violated_policy is None
    assert res.penalty == -15


# --- refund cap (the only -10 tier) ----------------------------------------

@pytest.mark.asyncio
async def test_refund_within_cap_allows():
    res = await _engine(BASE_POLICY).validate(_request("process_refund", {"amount": 3000}))
    assert res.decision == "ALLOW"


@pytest.mark.asyncio
async def test_refund_over_cap():
    res = await _engine(BASE_POLICY).validate(_request("process_refund", {"amount": 9000}))
    assert res.decision == "DENY"
    assert res.violation_type == "POLICY_VIOLATION"
    assert res.violated_policy == "max_refund_amount"
    assert res.penalty == -10


@pytest.mark.asyncio
async def test_refund_missing_amount_fails_secure():
    # policy_engine would default to $0 and ALLOW; Cedar denies-on-missing.
    res = await _engine(BASE_POLICY).validate(_request("process_refund", {}))
    assert res.decision == "DENY"
    assert res.violated_policy == "max_refund_amount"
    assert res.penalty == -10


@pytest.mark.asyncio
async def test_refund_string_currency_coerced():
    res = await _engine(BASE_POLICY).validate(_request("process_refund", {"amount": "$3,000"}))
    assert res.decision == "ALLOW"
    res2 = await _engine(BASE_POLICY).validate(_request("process_refund", {"amount": "$9,000"}))
    assert res2.decision == "DENY" and res2.penalty == -10


@pytest.mark.asyncio
async def test_refund_default_cap_when_absent():
    # No max_refund_amount in policy → $5,000 default → $9,000 denied.
    policy = {"allowed_tools": ["process_refund"], "allowed_agents": []}
    res = await _engine(policy).validate(_request("process_refund", {"amount": 9000}))
    assert res.decision == "DENY" and res.violated_policy == "max_refund_amount"


# --- high-fraud identity gate ----------------------------------------------

@pytest.mark.asyncio
async def test_high_fraud_identity_block():
    res = await _engine(BASE_POLICY).validate(
        _request("verify_identity", {"fraud_risk": "high", "fraud_score": 0.97}))
    assert res.decision == "DENY"
    assert res.violation_type == "POLICY_VIOLATION"
    assert res.violated_policy == "high_fraud_identity_block"
    assert res.penalty == -15


@pytest.mark.asyncio
async def test_verify_identity_low_fraud_allows():
    res = await _engine(BASE_POLICY).validate(_request("verify_identity", {"fraud_risk": "low"}))
    assert res.decision == "ALLOW"


# --- invoke_agent (two AND-ed authorizations + structural pre-check) -------

@pytest.mark.asyncio
async def test_invoke_agent_allowed():
    res = await _engine(BASE_POLICY).validate(_request("invoke_agent", {"agent_id": "helper-agent"}))
    assert res.decision == "ALLOW"


@pytest.mark.asyncio
async def test_invoke_agent_missing_target():
    res = await _engine(BASE_POLICY).validate(_request("invoke_agent", {}))
    assert res.decision == "DENY"
    assert res.violation_type == "INVALID_AGENT_INVOCATION"
    assert res.penalty == -15


@pytest.mark.asyncio
async def test_invoke_agent_disallowed_target():
    res = await _engine(BASE_POLICY).validate(_request("invoke_agent", {"agent_id": "evil-agent"}))
    assert res.decision == "DENY"
    assert res.violation_type == "UNAUTHORIZED_AGENT_INVOCATION"
    assert res.penalty == -15


@pytest.mark.asyncio
async def test_invoke_agent_not_in_allowed_tools_call1_wins():
    # invoke_agent NOT in allowed_tools → call-1 (tool-auth) denies → UNAUTHORIZED_TOOL,
    # even when a target is supplied (call-1 wins, matching legacy check order).
    policy = {"allowed_tools": ["get_balance"], "allowed_agents": ["helper-agent"]}
    res = await _engine(policy).validate(_request("invoke_agent", {"agent_id": "helper-agent"}))
    assert res.decision == "DENY"
    assert res.violation_type == "UNAUTHORIZED_TOOL"


# --- cross-cloud is NOT enforced by Cedar (deferred, stays in context_validator) -

@pytest.mark.asyncio
async def test_cross_cloud_not_enforced_by_cedar():
    # Real cross_cloud_dependencies shape (required_before/target_agent/target_tool —
    # NOT a `tool` key). Cedar does NOT enforce the precondition; an allowed tool is
    # ALLOWed at the policy step (context_validator enforces the sequence downstream,
    # exactly as with the legacy engine — parity preserved).
    policy = {
        "allowed_tools": ["sim_swap"],
        "allowed_agents": [],
        "cross_cloud_dependencies": [
            {"target_agent": "acme-identity-agent", "target_tool": "verify_identity",
             "required_before": ["sim_swap"], "max_age_seconds": 300},
        ],
    }
    res = await _engine(policy).validate(_request("sim_swap", {}))
    assert res.decision == "ALLOW"


# --- allow-list-first semantics (review finding #3) ------------------------

@pytest.mark.asyncio
async def test_dangerous_tool_not_in_allowlist_is_unauthorized_tool():
    # process_refund NOT in allow-list, with an over-cap amount: a resource-scoped
    # forbid (refund cap) also matches, but legacy checks the allow-list FIRST →
    # UNAUTHORIZED_TOOL/-15, NOT POLICY_VIOLATION/max_refund_amount/-10. Cedar must
    # reproduce that ordering (else penalty -10 vs -15 drifts trust scoring).
    policy = {"allowed_tools": ["get_balance"], "allowed_agents": []}
    res = await _engine(policy).validate(_request("process_refund", {"amount": 9999999}))
    assert res.decision == "DENY"
    assert res.violation_type == "UNAUTHORIZED_TOOL"
    assert res.violated_policy is None
    assert res.penalty == -15


@pytest.mark.asyncio
async def test_verify_identity_not_in_allowlist_high_fraud_is_unauthorized_tool():
    # Same ordering trap on the fraud gate: verify_identity not allowed + fraud=high
    # → UNAUTHORIZED_TOOL (allow-list first), not high_fraud_identity_block.
    policy = {"allowed_tools": ["get_balance"], "allowed_agents": []}
    res = await _engine(policy).validate(_request("verify_identity", {"fraud_risk": "high"}))
    assert res.decision == "DENY"
    assert res.violation_type == "UNAUTHORIZED_TOOL"
    assert res.violated_policy is None


# --- policy resolution errors ----------------------------------------------

@pytest.mark.asyncio
async def test_policy_disabled():
    res = await _engine(raises=PolicyDisabledError("disabled")).validate(_request("get_balance"))
    assert res.decision == "DENY"
    assert res.violation_type == "POLICY_DISABLED"
    assert res.penalty == -15
    assert res.cloud_region == "us-east-1"  # cloud carried on pre-load DENY


@pytest.mark.asyncio
async def test_policy_not_found():
    res = await _engine(raises=PolicyNotFoundError("none")).validate(_request("get_balance"))
    assert res.decision == "DENY"
    assert res.violation_type == "POLICY_NOT_FOUND"
    assert res.penalty == -15


@pytest.mark.asyncio
async def test_not_migrated_abstains():
    res = await _engine(raises=PolicyNotMigratedError("not yet")).validate(_request("get_balance"))
    assert res.is_abstain
    assert res.decision is None


# --- source stamping (combiner integration) --------------------------------

@pytest.mark.asyncio
async def test_result_stamped_with_sentra_policy_source():
    res = await _engine(BASE_POLICY).validate(_request("get_balance"))
    assert res.source == "sentra.policy"
