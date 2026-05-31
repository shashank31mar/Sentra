"""Unit tests for the cross-cloud AgentCallerFactory — Workstream 15 M4 Task 4.1.

Loads the factory module directly via importlib to avoid importing
src/dashboard/services/__init__.py, which pulls in streamlit (a heavyweight
dependency not needed for routing logic). Connector instantiation is faked so
boto3 + Azure config aren't required to run these tests.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
FACTORY_PATH = REPO_ROOT / "src" / "dashboard" / "services" / "agent_caller_factory.py"


def _load_factory_module():
    """Import the factory module standalone (bypasses dashboard.services.__init__)."""
    spec = importlib.util.spec_from_file_location("acf_under_test", FACTORY_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def acf():
    return _load_factory_module()


@pytest.fixture
def tmp_policies(tmp_path):
    """Minimal cross-cloud policy file written to a temp path."""
    policies = {
        "bedrock-agent-a": {
            "platform": "bedrock",
            "cloud_region": "us-east-1",
            "allowed_tools": ["foo"],
        },
        "bedrock-agent-b": {
            "platform": "bedrock",
            "cloud_region": "us-east-1",
            "allowed_tools": ["bar"],
        },
        "azure-agent": {
            "platform": "azure_foundry",
            "cloud_region": "centralus",
            "allowed_tools": ["verify"],
        },
        "no-platform-agent": {
            # missing platform — should resolve to "unknown"
            "allowed_tools": ["baz"],
        },
    }
    path = tmp_path / "agent_policies.yaml"
    path.write_text(yaml.dump(policies))
    return path


class _FakeConnector:
    def __init__(self, platform: str, region: str) -> None:
        self.platform = platform
        self.cloud_region = region


def _build_count_decorator():
    """Returns (builder, call_log) — builder forwards to FakeConnector."""
    calls: list[tuple[str, str]] = []

    def builder(platform: str, region: str):
        calls.append((platform, region))
        return _FakeConnector(platform, region)

    return builder, calls


def test_get_platform_returns_record(acf, tmp_policies):
    factory = acf.AgentCallerFactory(policy_path=tmp_policies)
    assert factory.get_platform("bedrock-agent-a") == {
        "platform": "bedrock",
        "cloud_region": "us-east-1",
    }
    assert factory.get_platform("azure-agent") == {
        "platform": "azure_foundry",
        "cloud_region": "centralus",
    }


def test_get_platform_missing_returns_none(acf, tmp_policies):
    factory = acf.AgentCallerFactory(policy_path=tmp_policies)
    assert factory.get_platform("does-not-exist") is None


def test_missing_platform_field_defaults_to_unknown(acf, tmp_policies):
    factory = acf.AgentCallerFactory(policy_path=tmp_policies)
    record = factory.get_platform("no-platform-agent")
    assert record == {"platform": "unknown", "cloud_region": ""}


def test_get_connector_caches_by_platform_region(acf, tmp_policies):
    builder, calls = _build_count_decorator()
    factory = acf.AgentCallerFactory(policy_path=tmp_policies, connector_builder=builder)

    c1 = factory.get_connector("bedrock-agent-a")
    c2 = factory.get_connector("bedrock-agent-b")  # same platform+region
    c3 = factory.get_connector("azure-agent")

    assert c1 is c2, "same (platform, region) should reuse the cached connector"
    assert c1 is not c3, "different platforms must produce different connectors"
    assert calls == [("bedrock", "us-east-1"), ("azure_foundry", "centralus")], (
        "builder must be invoked exactly once per unique (platform, region)"
    )


def test_get_connector_raises_for_unknown_agent(acf, tmp_policies):
    factory = acf.AgentCallerFactory(policy_path=tmp_policies)
    with pytest.raises(acf.UnknownPlatformError, match="not found"):
        factory.get_connector("does-not-exist")


def test_get_connector_raises_for_unsupported_platform(acf, tmp_policies):
    """Vertex AI is Phase 2; the factory should fail-loud rather than silently
    return a Bedrock connector."""
    # Patch the YAML to include a vertex agent
    policies = yaml.safe_load(tmp_policies.read_text())
    policies["vertex-agent"] = {"platform": "vertex_ai", "cloud_region": "us-central1"}
    tmp_policies.write_text(yaml.dump(policies))

    factory = acf.AgentCallerFactory(policy_path=tmp_policies)
    with pytest.raises(acf.UnknownPlatformError, match="Phase 2"):
        factory.get_connector("vertex-agent")


def test_missing_policy_file_returns_empty_map_and_raises_on_lookup(acf, tmp_path):
    """A missing policy file is logged but doesn't crash on import — only the
    first get_connector call raises (with a useful message)."""
    missing = tmp_path / "does_not_exist.yaml"
    factory = acf.AgentCallerFactory(policy_path=missing)
    assert factory.list_platforms() == {}
    with pytest.raises(acf.UnknownPlatformError):
        factory.get_connector("any-agent")


def test_invalidate_drops_caches(acf, tmp_policies):
    builder, calls = _build_count_decorator()
    factory = acf.AgentCallerFactory(policy_path=tmp_policies, connector_builder=builder)

    factory.get_connector("bedrock-agent-a")
    assert len(calls) == 1
    factory.invalidate()
    factory.get_connector("bedrock-agent-a")
    assert len(calls) == 2, "invalidate must force builder to run again"


def test_default_region_fallback_when_policy_omits_region(acf, tmp_path, monkeypatch):
    """If cloud_region is absent in YAML, the factory falls back to env defaults."""
    policies = {"bedrock-agent": {"platform": "bedrock"}}  # no cloud_region
    path = tmp_path / "policies.yaml"
    path.write_text(yaml.dump(policies))

    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    builder, calls = _build_count_decorator()
    factory = acf.AgentCallerFactory(policy_path=path, connector_builder=builder)
    factory.get_connector("bedrock-agent")
    assert calls == [("bedrock", "eu-west-1")]


def test_list_platforms_includes_every_agent_from_yaml(acf, tmp_policies):
    factory = acf.AgentCallerFactory(policy_path=tmp_policies)
    platforms = factory.list_platforms()
    assert set(platforms.keys()) == {
        "bedrock-agent-a",
        "bedrock-agent-b",
        "azure-agent",
        "no-platform-agent",
    }


def test_list_platforms_returns_a_defensive_copy(acf, tmp_policies):
    """Mutating the returned map should not corrupt the factory's internal cache."""
    factory = acf.AgentCallerFactory(policy_path=tmp_policies)
    snapshot = factory.list_platforms()
    snapshot["azure-agent"]["platform"] = "tampered"
    assert factory.get_platform("azure-agent")["platform"] == "azure_foundry"
