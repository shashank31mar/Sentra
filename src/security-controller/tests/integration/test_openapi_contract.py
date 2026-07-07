"""WS-N N8.2 OpenAPI-contract drift guard — the operator read routes MUST declare
`OperatorSession` security, not silently inherit the global `ApiKeyAuth`.

Context (the drift this closes): the 21 WS-N read routes were converted in the
controller to operator-OIDC + tenant-scoped access (bind via resolve_operator_tenant;
_dataplane_tenant_bind removed — see ADR-038 / lld/39 §4-§5, lld/40). The published
OpenAPI spec, however, still documented every GET as inheriting the top-level
`security: [ApiKeyAuth]`, so the spec claimed agent-key auth on control-plane reads
that the CODE now gates behind an operator session. That is a spec-vs-code contract
drift a customer/integrator reads off the wrong auth model from.

This test is the machine check that pins the fixed contract:
  - each operator READ operation (path + GET) declares a per-operation `security`
    block containing an `OperatorSession` scheme (so it does NOT fall through to the
    global ApiKeyAuth), and
  - the two AGENT-lane writes (POST /v1/validate, POST /v1/sessions/{id}/signals)
    do NOT carry an OperatorSession override — they intentionally stay on the global
    ApiKeyAuth (agent data-plane), so we assert the negative too.

If a security block is dropped from any listed read op (re-drift), the corresponding
assertion fails with the operationId named. Verified to fail against the pre-fix spec
(reads inheriting ApiKeyAuth) and pass post-fix.

Run from src/security-controller/:
    pytest tests/integration/test_openapi_contract.py -q
"""

from pathlib import Path

import pytest

yaml = pytest.importorskip(
    "yaml",
    reason="PyYAML (runtime dep, requirements.txt) is required to parse the OpenAPI spec.",
)


# ---------------------------------------------------------------------------
# Spec location — walk up from this test file to the repo root and into docs/.
# tests/integration -> tests -> security-controller -> src -> <repo root>
# ---------------------------------------------------------------------------
def _find_spec(filename: str) -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "docs" / "integration" / filename
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"Could not locate docs/integration/{filename} above {here}"
    )


MAIN_SPEC = "aegion-guard-api.openapi.yaml"
CUSTOMER_SPEC = "aegion-guard-api.customer.openapi.yaml"


# ---------------------------------------------------------------------------
# The contract: operator READ routes that MUST declare OperatorSession security.
# (path, http_method, operationId). These are the 21 WS-N operator read routes;
# discoverySummary/discoveryPlatforms are the two inline single-line GET maps.
# ---------------------------------------------------------------------------
OPERATOR_READ_OPS = [
    ("/v1/sessions/{session_id}/signals", "get", "getSessionSignals"),
    ("/v1/decisions", "get", "scanDecisions"),
    ("/v1/sessions", "get", "getSessions"),
    ("/v1/sessions/{session_id}/decisions", "get", "getSessionDecisions"),
    ("/v1/sessions/{session_id}/trail", "get", "getSessionTrail"),
    ("/v1/logs", "get", "getLogs"),
    ("/v1/logs/conversation/{conversation_id}", "get", "getConversationTimeline"),
    ("/v1/metrics", "get", "getMetrics"),
    ("/v1/metrics/overview", "get", "getMetricsOverview"),
    ("/v1/metrics/platform-distribution", "get", "getPlatformDistribution"),
    ("/v1/metrics/decisions-timeseries", "get", "getDecisionsTimeseries"),
    ("/v1/agents", "get", "getAgents"),
    ("/v1/agents/{agent_id}", "get", "getAgent"),
    ("/v1/agents/{agent_id}/tools", "get", "getAgentTools"),
    ("/v1/policies", "get", "getPolicies"),
    ("/v1/policies/{policy_id}", "get", "getPolicyById"),
    ("/v1/sigma-rules", "get", "getSigmaRules"),
    ("/v1/sigma-rules/{rule_id}/content", "get", "getSigmaRuleContent"),
    ("/v1/discovery/agents", "get", "discoveryAgents"),
    ("/v1/discovery/summary", "get", "discoverySummary"),
    ("/v1/discovery/platforms", "get", "discoveryPlatforms"),
    ("/v1/connections", "get", "listConnections"),
    ("/v1/connections/{connection_id}", "get", "getConnection"),
]

# The AGENT data-plane writes that MUST NOT carry an OperatorSession override —
# they intentionally stay on the global ApiKeyAuth (agent x-api-key).
AGENT_KEY_OPS = [
    ("/v1/validate", "post", "validateToolCall"),
    ("/v1/sessions/{session_id}/signals", "post", "postSessionSignal"),
]


def _load(filename: str) -> dict:
    with open(_find_spec(filename), "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _operation(spec: dict, path: str, method: str) -> dict | None:
    path_item = spec.get("paths", {}).get(path)
    if not isinstance(path_item, dict):
        return None
    op = path_item.get(method)
    return op if isinstance(op, dict) else None


def _declares_operator_session(op: dict) -> bool:
    """True iff the operation has its OWN security list naming OperatorSession
    (i.e. it overrides the global ApiKeyAuth), not an inherited/global scheme."""
    security = op.get("security")
    if not isinstance(security, list):
        return False
    return any(
        isinstance(req, dict) and "OperatorSession" in req for req in security
    )


def _global_security_is_apikey(spec: dict) -> bool:
    security = spec.get("security")
    return (
        isinstance(security, list)
        and any(isinstance(r, dict) and "ApiKeyAuth" in r for r in security)
    )


def test_global_default_is_apikey_auth():
    """Guard the premise: the spec's global default IS ApiKeyAuth, so an operator
    read op that omits its own security block would silently be key-auth."""
    spec = _load(MAIN_SPEC)
    assert _global_security_is_apikey(spec), (
        "Expected top-level `security: [ApiKeyAuth]` — the whole point of the "
        "per-operation OperatorSession override is that reads must NOT inherit it."
    )


def test_read_routes_declare_operator_session():
    """Every operator read route declares its own OperatorSession security block
    (does not inherit the global ApiKeyAuth). Fails, naming the operationId, if a
    security block re-drifts off any listed read op."""
    spec = _load(MAIN_SPEC)
    missing = []
    for path, method, op_id in OPERATOR_READ_OPS:
        op = _operation(spec, path, method)
        assert op is not None, f"{method.upper()} {path} ({op_id}) missing from spec"
        assert op.get("operationId") == op_id, (
            f"{method.upper()} {path}: operationId is {op.get('operationId')!r}, "
            f"expected {op_id!r}"
        )
        if not _declares_operator_session(op):
            missing.append(op_id)
    assert not missing, (
        "These operator READ routes do NOT declare OperatorSession security and so "
        f"silently inherit the global ApiKeyAuth (spec/code drift): {missing}"
    )


def test_agent_lane_writes_stay_apikey_auth():
    """The agent data-plane writes must NOT carry an OperatorSession override —
    they stay on the global ApiKeyAuth (agent x-api-key lane)."""
    spec = _load(MAIN_SPEC)
    wrongly_gated = []
    for path, method, op_id in AGENT_KEY_OPS:
        op = _operation(spec, path, method)
        assert op is not None, f"{method.upper()} {path} ({op_id}) missing from spec"
        if _declares_operator_session(op):
            wrongly_gated.append(op_id)
    assert not wrongly_gated, (
        "These agent data-plane writes wrongly declare OperatorSession — they must "
        f"stay on the global ApiKeyAuth (agent lane): {wrongly_gated}"
    )


def test_customer_spec_read_routes_present_are_gated():
    """The customer-facing spec exposes a subset of the read routes (internal-only
    ones like discovery/connections/getSessionSignals/getConversationTimeline are
    absent). Every listed read route that IS present in the customer spec must also
    declare OperatorSession; absent ones are skipped (not a drift)."""
    spec = _load(CUSTOMER_SPEC)
    assert _global_security_is_apikey(spec), "customer spec global default should be ApiKeyAuth"
    missing = []
    present = 0
    for path, method, op_id in OPERATOR_READ_OPS:
        op = _operation(spec, path, method)
        if op is None:
            continue  # internal route not exposed in the customer spec
        present += 1
        if not _declares_operator_session(op):
            missing.append(op_id)
    assert present > 0, "expected the customer spec to expose at least some read routes"
    assert not missing, (
        "Customer-spec read routes inheriting global ApiKeyAuth (drift): " f"{missing}"
    )
    # Agent-lane writes present in the customer spec must stay key-auth too.
    for path, method, op_id in AGENT_KEY_OPS:
        op = _operation(spec, path, method)
        if op is None:
            continue
        assert not _declares_operator_session(op), (
            f"customer spec: agent-lane {op_id} must stay ApiKeyAuth, not OperatorSession"
        )
