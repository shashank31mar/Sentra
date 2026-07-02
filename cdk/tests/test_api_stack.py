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
        "signals",          # LLD 17 §8.2 GET+POST /v1/sessions/{session_id}/signals
        "conversation",     # T16
        "{conversation_id}",
        "quarantine",       # T17
        "feedback",         # WS-E2 DSAR delete parent /v1/feedback
        "subjects",         # WS-E2 /v1/feedback/subjects
        "{subject_locator}",  # WS-E2 DELETE /v1/feedback/subjects/{subject_locator}
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


def _integration_path(uri):
    """Extract the backend PATH from a synthesized Integration.Uri. The URI is
    `{nlb_base_url}{path}` built via a CFN Fn::Join: ["", ["http://", <NLB DNS
    token>, "/v1/..."]] — so the path is the LAST join element (a plain string).
    Falls back to a plain-string URI (no token) for robustness.
    """
    if isinstance(uri, dict) and "Fn::Join" in uri:
        parts = uri["Fn::Join"][1]
        tail = parts[-1] if parts else ""
        return tail if isinstance(tail, str) else ""
    return uri if isinstance(uri, str) else ""


def _method_by_integration_path(api_template, http_method, path, *, exact=False):
    """Return the synthesized Method resource whose HTTP-integration backend path
    matches `path` for `http_method`, or None. Pins the method to its BACKEND PATH
    (not just that *a* method exists). exact=True requires an equal path (needed for
    /v1/metrics, a prefix of /v1/metrics/overview); else a suffix/contains match.
    """
    for props in api_template.find_resources("AWS::ApiGateway::Method").values():
        p = props.get("Properties", {})
        if p.get("HttpMethod") != http_method:
            continue
        ipath = _integration_path((p.get("Integration", {}) or {}).get("Uri"))
        if (ipath == path) if exact else (path in ipath):
            return p
    return None


# Back-compat alias used by the read-method test below.
def _method_by_integration_suffix(api_template, http_method, path_suffix):
    return _method_by_integration_path(api_template, http_method, path_suffix)


@pytest.mark.parametrize(
    "http_method,path_suffix,required_query_param",
    [
        # The method-level gate the resource-presence test can't give: each read
        # route's METHOD is wired to the CORRECT backend path with its query param
        # passed through — catches a method wired to the wrong path / dropped param.
        ("GET", "/v1/sessions/{session_id}/trail", "request_id"),
        ("GET", "/v1/sessions/{session_id}/decisions", "request_id"),
        ("GET", "/v1/sessions/{session_id}/signals", "request_id"),
    ],
)
def test_session_read_methods_wired_to_correct_backend_path(
    api_template, http_method, path_suffix, required_query_param
):
    """Method exists, targets the right integration URI, requires the session_id
    path param, api-key-gated, and passes its query param through."""
    method = _method_by_integration_suffix(api_template, http_method, path_suffix)
    assert method is not None, f"no {http_method} method wired to {path_suffix}"
    assert method.get("ApiKeyRequired") is True, f"{path_suffix} must be api-key-gated"
    rp = method.get("RequestParameters", {}) or {}
    assert rp.get("method.request.path.session_id") is True, (
        f"{path_suffix} must declare the session_id path param"
    )
    assert f"method.request.querystring.{required_query_param}" in rp, (
        f"{path_suffix} must pass {required_query_param} through the gateway"
    )
    integ_params = (method.get("Integration", {}) or {}).get("RequestParameters", {}) or {}
    assert (
        f"integration.request.querystring.{required_query_param}" in integ_params
    ), f"{path_suffix} integration must forward {required_query_param} to the backend"


def test_bare_metrics_get_method_wired(api_template):
    """GET /v1/metrics (bare) is wired distinct from /metrics/{overview,...}."""
    # /v1/metrics is a prefix of /v1/metrics/overview → require an EXACT path match.
    method = _method_by_integration_path(api_template, "GET", "/v1/metrics", exact=True)
    assert method is not None, "GET /v1/metrics (bare) not wired to its backend path"
    assert method.get("ApiKeyRequired") is True


def test_rollback_conversation_post_method_wired(api_template):
    """POST /v1/rollback/conversation/{conversation_id} is wired with its path param."""
    method = _method_by_integration_suffix(
        api_template, "POST", "/v1/rollback/conversation/{conversation_id}"
    )
    assert method is not None, "POST /v1/rollback/conversation/{conversation_id} not wired"
    assert method.get("ApiKeyRequired") is True
    assert (method.get("RequestParameters", {}) or {}).get(
        "method.request.path.conversation_id"
    ) is True


def test_feedback_subject_delete_method_wired(api_template):
    """DELETE /v1/feedback/subjects/{subject_locator} (DSAR) is wired + api-key-gated."""
    method = _method_by_integration_suffix(
        api_template, "DELETE", "/v1/feedback/subjects/{subject_locator}"
    )
    assert method is not None, "DELETE /v1/feedback/subjects/{subject_locator} not wired"
    assert method.get("ApiKeyRequired") is True
    assert (method.get("RequestParameters", {}) or {}).get(
        "method.request.path.subject_locator"
    ) is True


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
