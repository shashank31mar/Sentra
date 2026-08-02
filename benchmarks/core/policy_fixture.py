"""Policy Engine class-level patching for in-process benchmark execution (LLD 41 §4.5, WS-D milestone D2)."""

from contextlib import contextmanager
from typing import Any, Dict, Tuple
from app.validators.policy_engine import PolicyEngine, PolicyNotFoundError


class BenchmarkPolicyEngine(PolicyEngine):
    """Class-level override for PolicyEngine.resolve_policy_bundle.
    
    Replaces DynamoDB / S3 calls with in-memory policy dictionaries.
    """

    def __init__(self, synthesized_policies: Dict[str, Dict[str, Any]] | None = None) -> None:
        super().__init__()
        self._synthesized_policies = synthesized_policies or {}

    def register_policy(self, agent_id: str, policy_dict: Dict[str, Any]) -> None:
        self._synthesized_policies[agent_id] = policy_dict

    async def resolve_policy_bundle(self, agent_id: str) -> Tuple[Dict, Dict, Dict]:
        if agent_id not in self._synthesized_policies:
            raise PolicyNotFoundError(f"No synthesized policy found for agent {agent_id}")

        policy = self._synthesized_policies[agent_id]
        metadata = policy.get("metadata", {})
        agent = {
            "agent_id": agent_id,
            "platform": policy.get("platform", "unknown"),
            "cloud_region": policy.get("cloud_region", "us-east-1"),
        }
        return (policy, metadata, agent)


@contextmanager
def patch_policy_engine(synthesized_policies: Dict[str, Dict[str, Any]]):
    """Context manager performing class-level patching of PolicyEngine.resolve_policy_bundle.

    Class-level patching ensures all 3 consumers instantiated inside ValidationService
    (self.policy_engine, self.context_validator.policy_engine, self.cedar_engine.policy_engine)
    share the in-memory policy lookup without modifying app/ source code.
    """
    from app.config import settings
    from app.validators.cedar.policy_loader import CedarPolicyLoader

    original_cedar_enabled = getattr(settings, "cedar_enabled", False)
    settings.cedar_enabled = True

    original_resolve = PolicyEngine.resolve_policy_bundle
    original_get_identity = PolicyEngine.get_agent_cloud_identity
    original_load_compiled = CedarPolicyLoader._load_compiled_cached

    async def _mock_resolve(self_instance, agent_id: str) -> Tuple[Dict, Dict, Dict]:
        if agent_id not in synthesized_policies:
            raise PolicyNotFoundError(f"No synthesized policy found for agent {agent_id}")

        policy = synthesized_policies[agent_id]
        metadata = policy.get("metadata", {})
        metadata.setdefault("policy_format", "cedar")
        agent = {
            "agent_id": agent_id,
            "platform": policy.get("platform", "unknown"),
            "cloud_region": policy.get("cloud_region", "us-east-1"),
        }
        return (policy, metadata, agent)

    def _mock_get_identity(self_instance, agent_id: str) -> Tuple[str, str]:
        policy = synthesized_policies.get(agent_id, {})
        return (policy.get("platform", "unknown"), policy.get("cloud_region", "us-east-1"))

    def _mock_load_compiled(self_instance, metadata: dict) -> Tuple[str, bool]:
        return ('@id("permit_use_tool") permit(principal, action == Action::"UseTool", resource) when { resource in principal.allowed_tools };', True)

    try:
        PolicyEngine.resolve_policy_bundle = _mock_resolve
        PolicyEngine.get_agent_cloud_identity = _mock_get_identity
        CedarPolicyLoader._load_compiled_cached = _mock_load_compiled
        yield
    finally:
        PolicyEngine.resolve_policy_bundle = original_resolve
        PolicyEngine.get_agent_cloud_identity = original_get_identity
        CedarPolicyLoader._load_compiled_cached = original_load_compiled
        settings.cedar_enabled = original_cedar_enabled
