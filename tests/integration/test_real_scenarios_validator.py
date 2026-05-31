"""Integration test — every real cross_cloud scenario YAML loads cleanly
through the ScenarioValidator with fake fetchers.

The whole point of Workstream 18 M3 was "broken scenarios never serve traffic."
That guarantee held when strict mode is on AND every real scenario passes
validation. Without this test, a missing-intent-field regression on a future
scenario would only surface at orchestrator startup in dev — exactly the cascade
we hit on 2026-05-30.

This test runs against the REAL scenario YAMLs in src/demo-orchestrator/scenarios/
with deterministic fake fetchers (no AWS or Azure required), so it's safe in CI.
A live integration test against the actual deployed cloud schemas is a separate
concern (would need RUN_INTEGRATION=1 + AWS creds).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIOS_DIR = REPO_ROOT / "src" / "demo-orchestrator" / "scenarios"
VALIDATOR_PATH = REPO_ROOT / "src" / "demo-orchestrator" / "app" / "services" / "scenario_validator.py"


def _load_validator_module():
    spec = importlib.util.spec_from_file_location("sv_int", VALIDATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["sv_int"] = module
    spec.loader.exec_module(module)
    return module


# Schemas reflecting the actual deployed Bedrock agents' OpenAPI. Mirrors the
# real `customer_tools` action group exposed by the Action Group Lambda. If a
# scenario references a tool not in here, validation correctly fails — same
# behaviour as the live orchestrator with proper IAM perms.
_CUSTOMER_SERVICE_SCHEMA = {
    "query_customers": {
        "parameters": {
            "state": {"type": "string", "openapi_type": "string", "required": True},
        }
    },
    "get_order_details": {
        "parameters": {
            "order_id": {"type": "string", "openapi_type": "string", "required": True},
        }
    },
    "process_refund": {
        "parameters": {
            "order_id": {"type": "string", "openapi_type": "string", "required": True},
            "amount": {"type": "number", "openapi_type": "number", "required": True},
        }
    },
}


# Azure Function tool registry mirrors function_app.py:TOOL_DISPATCH.
_AZURE_TOOLS = {"check_fraud_score", "verify_image_authenticity"}


class _FakeBedrockSchemaFetcher:
    """Returns the same schema for every agent_id — matches our setup where
    all three Bedrock agents share the same customer_tools action group."""

    def get(self, agent_id):
        return _CUSTOMER_SERVICE_SCHEMA


class _FakeAzureToolFetcher:
    def get_tools(self):
        return _AZURE_TOOLS


def _list_cross_cloud_scenarios():
    """Return paths to scenario YAMLs that have a cross_cloud block — these
    are the WS18 runner's target. Non-cross-cloud scenarios (single-cloud
    prompts) are out of scope for the validator."""
    out = []
    for yaml_path in sorted(SCENARIOS_DIR.glob("*.yaml")):
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        if (data or {}).get("cross_cloud"):
            out.append((yaml_path.stem, yaml_path, data))
    return out


@pytest.fixture(scope="module")
def sv():
    return _load_validator_module()


@pytest.fixture(scope="module")
def validator(sv):
    discovered = {
        # Real Bedrock-discovered agents — both symbolic and full names
        "bedrock-secured",
        "sentra-mvp-customer-service-agent",
        "bedrock-unsecured",
        "sentra-mvp-customer-service-agent-unsecured",
        "sentra-mvp-customer-service-agent-naive",
    }
    return sv.ScenarioValidator(
        bedrock_schema_fetcher=_FakeBedrockSchemaFetcher(),
        azure_tool_fetcher=_FakeAzureToolFetcher(),
        discovered_bedrock_agents=discovered,
        # Trust all Azure agent_ids in tests — production validator would
        # check against an Azure agent registry (out of v0.1 scope).
        azure_agent_exists_fn=lambda _: True,
    )


@pytest.mark.parametrize("scenario_id,_path,_data", _list_cross_cloud_scenarios())
def test_real_scenario_validates_clean(validator, scenario_id, _path, _data):
    """Every real cross_cloud scenario YAML in src/demo-orchestrator/scenarios/
    must pass validator cleanly. If this fails, fix the YAML — don't relax the
    validator."""
    errors = validator.validate_scenario(_data)
    if errors:
        formatted = "\n  ".join(e.format() for e in errors)
        pytest.fail(f"{scenario_id} has {len(errors)} validation errors:\n  {formatted}")


def test_at_least_four_scenarios_present():
    """Sanity check — if scenarios disappear, the parametrize above silently
    runs zero tests. Pin the expected lower bound."""
    scenarios = _list_cross_cloud_scenarios()
    scenario_ids = {s[0] for s in scenarios}
    expected_minimum = {
        "s1_unified_governance_pane",
        "s2_cross_cloud_policy_propagation",
        "s3_cross_cloud_sequence_validation",
        "s4_cross_cloud_blast_radius",
    }
    missing = expected_minimum - scenario_ids
    assert not missing, f"Expected scenarios missing: {missing}"
