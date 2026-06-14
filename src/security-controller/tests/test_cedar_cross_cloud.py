"""Cross-cloud uniformity (CT14, feature §8 — the payoff).

One Cedar policy bound to a Bedrock agent AND an Azure agent must yield the
IDENTICAL authorization outcome while each agent resolves its OWN cloud
(platform/cloud_region come from the agent record, §2.3; authz is entity-borne
from the shared policy). This validates policy uniformity across clouds.

Scope note (C5): this validates uniformity, NOT identity hardening — the
principal is still self-asserted until multicloud-import §14. CT14 passing does
NOT mean cross-cloud identity is secured.
"""
import pytest

from app.api.models import ValidationRequest
from app.validators.cedar.engine import CedarPolicyEngine
from app.validators.cedar.policy_loader import LoadedCedarPolicy
from app.validators.cedar.schema import get_baseline_policies

# One shared authz policy — the SAME allowed_tools / cap for every bound agent.
SHARED_AUTHZ = {
    "allowed_tools": ["get_balance", "process_refund"],
    "allowed_agents": [],
    "max_refund_amount": 5000,
}

CLOUDS = {
    "bedrock-agent": ("bedrock", "us-east-1"),
    "azure-agent": ("azure_foundry", "centralus"),
}


def _request(agent_id, tool_name, tool_params=None):
    return ValidationRequest(
        request_id="r", session_id="s", agent_id=agent_id, tool_name=tool_name,
        tool_params=tool_params or {}, user_input="x",
        timestamp="2026-06-12T00:00:00Z", operation_type="WRITE")


class _PerAgentCloudLoader:
    """Returns the SAME shared authz policy for every agent, but stamps the
    agent's OWN cloud onto the policy dict (exactly what resolve_policy_bundle
    does via cloud-from-agent, §2.3)."""

    async def load(self, agent_id):
        platform, region = CLOUDS[agent_id]
        policy = dict(SHARED_AUTHZ, platform=platform, cloud_region=region)
        return LoadedCedarPolicy(policy=policy, metadata={"policy_format": "cedar"},
                                 agent={"platform": platform}, compiled_cedar=get_baseline_policies())


def _engine():
    eng = CedarPolicyEngine()
    eng._loader = _PerAgentCloudLoader()
    eng._policy_engine.get_agent_cloud_identity = lambda agent_id: CLOUDS[agent_id]
    return eng


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,params", [
    ("get_balance", {}),                       # allowed → ALLOW on both clouds
    ("secretsmanager.get", {}),                # not allowed → DENY on both clouds
    ("process_refund", {"amount": 9000}),      # over cap → DENY on both clouds
    ("process_refund", {"amount": 3000}),      # within cap → ALLOW on both clouds
])
async def test_identical_authz_across_clouds(tool, params):
    eng = _engine()
    bedrock = await eng.validate(_request("bedrock-agent", tool, params))
    azure = await eng.validate(_request("azure-agent", tool, params))

    # Same authorization outcome — the §8 uniformity payoff.
    assert bedrock.decision == azure.decision
    assert bedrock.violation_type == azure.violation_type
    assert bedrock.violated_policy == azure.violated_policy
    assert bedrock.penalty == azure.penalty

    # …but each resolves its OWN cloud (agent-sourced, §2.3).
    assert (bedrock.platform, bedrock.cloud_region) == ("bedrock", "us-east-1")
    assert (azure.platform, azure.cloud_region) == ("azure_foundry", "centralus")
