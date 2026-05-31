"""Cloud-routing factory for agent connectors — Workstream 15 M4, Task 4.1.

Given an agent_id, resolves which cloud governs that agent and returns the
matching AgentConnector instance. The dashboard and demo orchestrator use this
to invoke agents uniformly across Bedrock / Azure Foundry / Vertex AI without
hard-coding cloud routing per call site.

Resolution path for an agent's platform:
1. In-memory cache populated by previous lookups.
2. config/agent_policies.yaml — the YAML that scripts/seed_policies.py mirrors
   into the sentra-policies-metadata DDB table + S3. Packaged with the
   dashboard image so resolution works without AWS credentials.
3. Returns None if absent. Callers should treat None as "unknown platform"
   and fail-secure DENY rather than fall back to a default connector.

Connectors are cached per (platform, region). No reason to instantiate two
BedrockConnectors for the same us-east-1 just because two agents live there.

LLD ref: 15-cross-cloud-connectors.md §3 (AgentConnector contract).
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

import yaml

def _find_ancestor_containing(*relative_paths: str) -> Optional[Path]:
    """Walk up from this file until an ancestor contains every named path.

    Lets the same module run from two layouts without per-env conditionals:
      - local dev:   <repo>/src/dashboard/services/agent_caller_factory.py
                     -> connectors at <repo>/src/connectors
                     -> policy at    <repo>/config/agent_policies.yaml
      - container:   /app/services/agent_caller_factory.py
                     -> connectors at /app/connectors (Dockerfile COPY)
                     -> policy at    /app/config/agent_policies.yaml
    """
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        if all((ancestor / rel).exists() for rel in relative_paths):
            return ancestor
    return None


_CONNECTORS_ROOT = _find_ancestor_containing("connectors")
if _CONNECTORS_ROOT and str(_CONNECTORS_ROOT) not in sys.path:
    sys.path.insert(0, str(_CONNECTORS_ROOT))

from connectors.azure_foundry import AzureConnector  # noqa: E402
from connectors.base import AgentConnector, Platform  # noqa: E402
from connectors.bedrock import BedrockConnector  # noqa: E402

logger = logging.getLogger(__name__)


_POLICY_HOST = _find_ancestor_containing("config/agent_policies.yaml")
_DEFAULT_POLICY_PATH = (
    (_POLICY_HOST / "config" / "agent_policies.yaml")
    if _POLICY_HOST
    # Fall back to the local-dev layout assumption — get_platform() will log a
    # warning and return None if the file genuinely doesn't exist.
    else Path(__file__).resolve().parents[3] / "config" / "agent_policies.yaml"
)


class UnknownPlatformError(Exception):
    """Agent missing from policy config, or its platform has no connector."""


PlatformRecord = dict[str, str]  # {"platform": ..., "cloud_region": ...}
ConnectorBuilder = Callable[[str, str], AgentConnector]


class AgentCallerFactory:
    """Maps agent_id to AgentConnector based on policy.

    Thread-safe: a single lock guards both the platform-resolution cache and
    the connector cache so concurrent first-time lookups don't all reload
    the YAML or instantiate duplicate connectors.
    """

    def __init__(
        self,
        policy_path: Optional[Path] = None,
        connector_builder: Optional[ConnectorBuilder] = None,
    ) -> None:
        self._policy_path = policy_path or _DEFAULT_POLICY_PATH
        self._builder = connector_builder or _build_connector
        self._lock = threading.Lock()
        self._platform_cache: dict[str, PlatformRecord] = {}
        self._connector_cache: dict[tuple[str, str], AgentConnector] = {}
        self._policies_loaded = False

    def _load_policies(self) -> None:
        if self._policies_loaded:
            return
        if not self._policy_path.exists():
            logger.warning(
                "agent_caller_factory: policy file not found at %s — every "
                "get_connector() call will raise UnknownPlatformError until "
                "this is fixed.",
                self._policy_path,
            )
            self._policies_loaded = True
            return
        with self._policy_path.open() as f:
            policies = yaml.safe_load(f) or {}
        for agent_id, policy in policies.items():
            if not isinstance(policy, dict):
                continue
            self._platform_cache[agent_id] = {
                "platform": policy.get("platform", "unknown"),
                "cloud_region": policy.get("cloud_region", ""),
            }
        self._policies_loaded = True
        logger.info(
            "agent_caller_factory: loaded %d agent platforms from %s",
            len(self._platform_cache),
            self._policy_path,
        )

    def get_platform(self, agent_id: str) -> Optional[PlatformRecord]:
        """Return {platform, cloud_region} for an agent, or None if unknown."""
        with self._lock:
            self._load_policies()
            record = self._platform_cache.get(agent_id)
        return dict(record) if record else None

    def list_platforms(self) -> dict[str, PlatformRecord]:
        """Return a copy of the full agent_id to platform mapping (for the dashboard table)."""
        with self._lock:
            self._load_policies()
            return {aid: dict(rec) for aid, rec in self._platform_cache.items()}

    def get_connector(self, agent_id: str) -> AgentConnector:
        """Return the cached connector for the agent's platform.

        Fail-loud on unknown agents: silently returning a Bedrock connector
        for an Azure agent would mask deployment bugs.
        """
        record = self.get_platform(agent_id)
        if not record:
            raise UnknownPlatformError(
                f"Agent {agent_id!r} not found in {self._policy_path}. "
                "Add a policy entry with platform + cloud_region fields."
            )
        platform = record["platform"]
        region = record["cloud_region"] or _default_region_for(platform)
        return self._get_or_build(platform, region)

    def _get_or_build(self, platform: str, region: str) -> AgentConnector:
        key = (platform, region)
        with self._lock:
            cached = self._connector_cache.get(key)
            if cached is not None:
                return cached
            connector = self._builder(platform, region)
            self._connector_cache[key] = connector
            return connector

    def invalidate(self) -> None:
        """Drop both caches. Use after the policy file changes on disk."""
        with self._lock:
            self._platform_cache.clear()
            self._connector_cache.clear()
            self._policies_loaded = False


def _default_region_for(platform: str) -> str:
    if platform == Platform.BEDROCK.value:
        return os.environ.get("AWS_REGION", "us-east-1")
    if platform == Platform.AZURE_FOUNDRY.value:
        return os.environ.get("AZURE_OPENAI_REGION", "centralus")
    if platform == Platform.VERTEX_AI.value:
        return os.environ.get("GCP_REGION", "us-central1")
    return ""


def _build_connector(platform: str, region: str) -> AgentConnector:
    if platform == Platform.BEDROCK.value:
        return BedrockConnector(region_name=region)
    if platform == Platform.AZURE_FOUNDRY.value:
        # Pass the YAML-resolved region so a future eastus2 agent doesn't get
        # silently routed through the centralus Azure OpenAI deployment
        # (Issue #9, Kiro M4 review). Env var stays as the fallback inside
        # AzureConnector.__init__ for direct-construction callers.
        return AzureConnector(region=region)
    if platform == Platform.VERTEX_AI.value:
        raise UnknownPlatformError(
            "vertex_ai connector is a Phase 2 follow-up (WS15 Phase 2). "
            "See lld/15-cross-cloud-connectors.md §8."
        )
    raise UnknownPlatformError(
        f"No connector registered for platform {platform!r}. "
        "Valid platforms: bedrock, azure_foundry, vertex_ai."
    )


_factory: Optional[AgentCallerFactory] = None
_factory_lock = threading.Lock()


def _get_default_factory() -> AgentCallerFactory:
    """Lazy module-level singleton so importing this module doesn't touch disk."""
    global _factory
    if _factory is None:
        with _factory_lock:
            if _factory is None:
                _factory = AgentCallerFactory()
    return _factory


def get_connector(agent_id: str) -> AgentConnector:
    """Convenience: resolve connector via the process-singleton factory."""
    return _get_default_factory().get_connector(agent_id)


def get_platform(agent_id: str) -> Optional[PlatformRecord]:
    """Convenience: look up just platform/cloud_region for an agent."""
    return _get_default_factory().get_platform(agent_id)


def list_platforms() -> dict[str, PlatformRecord]:
    """Convenience: full agent_id to platform map for the Cross-Cloud table."""
    return _get_default_factory().list_platforms()
