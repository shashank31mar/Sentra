"""CDK assertion tests for ApiStack (WS-21 Phase 1 Tier B wiring + T03 logs fix).

Builds the full stack graph (network → storage → cognito → compute → api) the
same way app.py does, then asserts the new API Gateway resources/params are
synthesized. Run from cdk/: ``python -m pytest tests/ -q``.
"""
import os
from pathlib import Path

import pytest
import yaml
from aws_cdk import App, Environment
from aws_cdk.assertions import Match, Template

from stacks import ApiStack, ComputeStack, NetworkStack, StorageStack
from stacks.cognito_stack import CognitoStack


def _config() -> dict:
    with open(Path(__file__).resolve().parents[1] / "config" / "dev.yaml") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def api_template() -> Template:
    os.environ.setdefault("AWS_ACCOUNT_ID", "123456789012")
    os.environ.setdefault("ENV", "dev")
    config = _config()
    env = Environment(account="123456789012", region="us-east-1")
    app = App()
    network = NetworkStack(app, "Net", config=config, env=env)
    storage = StorageStack(app, "Stor", config=config, env=env)
    cognito = CognitoStack(app, "Cog", config=config, env=env)
    compute = ComputeStack(
        app, "Comp", config=config, network_stack=network,
        storage_stack=storage, cognito_stack=cognito, env=env,
    )
    api = ApiStack(
        app, "Api", config=config, network_stack=network, compute_stack=compute, env=env,
    )
    return Template.from_stack(api)


@pytest.mark.parametrize(
    "path_part",
    [
        "{agent_id}",       # T11 GET /v1/agents/{agent_id}
        "tools",            # T12 /tools
        "sessions",         # T13
        "{session_id}",     # T14 + T17
        "decisions",        # T14/T15
        "trail",            # WS-D LLD 33 §9A GET /v1/sessions/{session_id}/trail (per-resource GW: unwired route = 403)
        "conversation",     # T16
        "{conversation_id}",
        "quarantine",       # T17
        "metrics",                 # T20-T22 parent
        "overview",                # T20
        "platform-distribution",   # T21
        "decisions-timeseries",    # T22
        "discovery",               # T32 parent
        "summary",                 # T32
        "platforms",               # T32
        "import",                  # T32
        "policies",                # T33 (also Tier A; present either way)
        "{policy_id}",             # T33 detach
        "status",                  # agent-policy-management T24: /policies/{policy_id}/status
        "{decision_id}",           # T34
        "verdict",                 # T34
    ],
)
def test_tier_b_resources_synthesized(api_template, path_part):
    """Each Tier B path segment is present in the synthesized API (Phase 1)."""
    api_template.has_resource_properties(
        "AWS::ApiGateway::Resource", {"PathPart": path_part}
    )


def test_policy_status_patch_method_synthesized(api_template):
    """agent-policy-management T24: PATCH /policies/{policy_id}/status is wired
    with the policy_id path param (the one new method in this feature)."""
    api_template.has_resource_properties(
        "AWS::ApiGateway::Method",
        {
            "HttpMethod": "PATCH",
            "RequestParameters": Match.object_like(
                {"method.request.path.policy_id": True}
            ),
        },
    )


def test_logs_endpoint_passes_real_query_params(api_template):
    """WS-21 T03: /v1/logs method maps since/until/decision/threat_type/agent_id."""
    api_template.has_resource_properties(
        "AWS::ApiGateway::Method",
        {
            "HttpMethod": "GET",
            "RequestParameters": Match.object_like(
                {
                    "method.request.querystring.since": False,
                    "method.request.querystring.until": False,
                    "method.request.querystring.decision": False,
                    "method.request.querystring.threat_type": False,
                    "method.request.querystring.agent_id": False,
                }
            ),
        },
    )


def test_logs_endpoint_no_longer_uses_start_time(api_template):
    """The buggy start_time/end_time params (C3) are gone."""
    methods = api_template.find_resources("AWS::ApiGateway::Method")
    for props in methods.values():
        params = props.get("Properties", {}).get("RequestParameters", {}) or {}
        assert "method.request.querystring.start_time" not in params
        assert "method.request.querystring.end_time" not in params
