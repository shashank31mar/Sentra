"""CDK assertion tests for StorageStack (WS-21 T04).

Validates the agent-registry `cloud-provider-index` GSI is synthesized.
Run from the cdk/ directory: ``python -m pytest tests/ -q``.
"""
from pathlib import Path

import yaml
from aws_cdk import App, Environment
from aws_cdk.assertions import Match, Template

from stacks.storage_stack import StorageStack


def _config() -> dict:
    cfg_path = Path(__file__).resolve().parents[1] / "config" / "dev.yaml"
    with open(cfg_path) as f:
        return yaml.safe_load(f)


def _template() -> Template:
    app = App()
    stack = StorageStack(
        app,
        "TestStorageStack",
        config=_config(),
        env=Environment(account="123456789012", region="us-east-1"),
    )
    return Template.from_stack(stack)


def test_agent_registry_has_no_unused_cloud_provider_gsi():
    """WS-21 T04 (Kiro review): the cloud-provider-index GSI is intentionally NOT
    provisioned at MVP scale (distribution uses a Scan; an unused GSI is waste).
    """
    template = _template()
    tables = template.find_resources("AWS::DynamoDB::Table")
    registry = [
        t for t in tables.values()
        if t.get("Properties", {}).get("TableName") == "sentra-agent-registry"
    ]
    assert registry, "agent registry table not found"
    gsis = registry[0]["Properties"].get("GlobalSecondaryIndexes", [])
    names = {g.get("IndexName") for g in gsis}
    assert "cloud-provider-index" not in names


def test_agent_registry_retains_status_index():
    """Pre-existing status-index must still be present (no regression)."""
    template = _template()
    template.has_resource_properties(
        "AWS::DynamoDB::Table",
        {
            "TableName": "sentra-agent-registry",
            "GlobalSecondaryIndexes": Match.array_with(
                [Match.object_like({"IndexName": "status-index"})]
            ),
        },
    )
