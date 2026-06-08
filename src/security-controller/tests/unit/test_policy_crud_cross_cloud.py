"""
Regression tests for cross-cloud policy round-trip (LLD 15 §4.5).

Guards the bug where `cross_cloud_dependencies` (and platform / cloud_region /
allowed_agents) were silently dropped on every POST/PUT /v1/policies because
PolicyCreate/UpdateRequest didn't declare them — routes.py persists
`request.dict()`, so undeclared fields never reached S3, and the context
validator then failed open (allowed a refund with no prior verification).

Two gates are covered:
  1. The controller request model retains the fields through `.dict()`.
  2. apply_policy.build_update_body (the S2 hook's PUT path) preserves them
     across a remove/add-tool round-trip instead of whitelisting them away.
"""
import pytest

# Importing the model also puts repo `scripts/` on sys.path (see models.py),
# which makes the apply_policy CLI importable below.
from app.api.models import PolicyUpdateRequest


CROSS_CLOUD_DEP = {
    "target_agent": "azure-verification-agent",
    "target_tool": "verify_image_authenticity",
    "required_before": ["process_refund"],
    "max_age_seconds": 300,
}


def _base_body(**overrides):
    body = {
        "schema_version": "1.1",
        "agent_id": "sentra-mvp-customer-service-agent",
        "name": "Bedrock Customer Service Agent Policy (Cross-Cloud)",
        "version": "1.0.0",
        "description": "x",
        "allowed_tools": ["query_customers", "get_order_details", "process_refund"],
        "policies": [
            {
                "policy_id": "pol-001",
                "name": "Refund Amount Limit",
                "severity": "high",
                "decision": "DENY",
                "enabled": True,
            }
        ],
        "platform": "bedrock",
        "cloud_region": "us-east-1",
        "allowed_agents": ["azure-verification-agent"],
        "cross_cloud_dependencies": [CROSS_CLOUD_DEP],
        "max_calls_per_minute": 30,
    }
    body.update(overrides)
    return body


def test_policy_update_request_round_trips_cross_cloud_fields():
    """The route persists request.dict(); the cross-cloud fields MUST survive it."""
    req = PolicyUpdateRequest(**_base_body())
    dumped = req.dict()

    assert dumped["cross_cloud_dependencies"] == [CROSS_CLOUD_DEP]
    assert dumped["platform"] == "bedrock"
    assert dumped["cloud_region"] == "us-east-1"
    assert dumped["allowed_agents"] == ["azure-verification-agent"]
    assert dumped["max_calls_per_minute"] == 30


def test_policy_update_request_cross_cloud_optional_for_single_cloud():
    """Single-cloud policies omit the fields; they default to None, not error."""
    body = _base_body()
    for k in ("platform", "cloud_region", "allowed_agents",
              "cross_cloud_dependencies", "max_calls_per_minute"):
        body.pop(k)
    req = PolicyUpdateRequest(**body)
    assert req.cross_cloud_dependencies is None
    assert req.platform is None


def test_apply_policy_build_update_body_preserves_cross_cloud():
    """S2's remove/add-tool hook must not strip the cross-cloud rule."""
    import apply_policy

    fetched = {"content": _base_body()}

    removed = apply_policy.build_update_body(
        fetched, remove_tool="query_customers", add_tool=None
    )
    assert "query_customers" not in removed["allowed_tools"]
    assert removed["cross_cloud_dependencies"] == [CROSS_CLOUD_DEP]
    assert removed["platform"] == "bedrock"
    assert removed["cloud_region"] == "us-east-1"
    assert removed["allowed_agents"] == ["azure-verification-agent"]
    assert removed["version"] == "1.0.1"  # patch bumped

    # And the restore (--add-tool) leg keeps the rule too.
    restored = apply_policy.build_update_body(
        {"content": removed}, remove_tool=None, add_tool="query_customers"
    )
    assert "query_customers" in restored["allowed_tools"]
    assert restored["cross_cloud_dependencies"] == [CROSS_CLOUD_DEP]
    assert restored["version"] == "1.0.2"
