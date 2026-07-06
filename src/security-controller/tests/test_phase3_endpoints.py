"""Route-level tests for WS-21 Phase 3: discovery, attach/detach, verdict (T32-T34).

WS-M M1.1 note: ``POST/DELETE /v1/agents/{id}/policies`` are now RBAC-gated
(``require_role("editor")``) + anti-IDOR (``assert_owns``). These route-behaviour
tests inject a verified operator via a FastAPI dependency override on
``resolve_operator_tenant`` and neutralize the ownership point-read (its own
coverage lives in ``test_ownership.py`` / ``test_policy_routes_authz.py``), so they
keep exercising the handler's business logic — attach/detach mapping — under auth.
"""
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.deps import OperatorContext, resolve_operator_tenant
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def as_editor():
    """Inject a verified editor operator (tenant ``t_ph``) and make ``assert_owns``
    a no-op for these business-logic tests (ownership is covered elsewhere)."""
    app.dependency_overrides[resolve_operator_tenant] = lambda: OperatorContext(
        sub="op-ph", tenant_id="t_ph", role="editor", email="ph@x")
    with patch("app.api.routes.assert_owns", return_value=None):
        yield
    app.dependency_overrides.pop(resolve_operator_tenant, None)


# --------------------------------------------------------------------- discovery

@pytest.fixture
def mock_discovery():
    with patch('app.services.discovery_service.DiscoveryService') as mock:
        svc = Mock()
        svc.list_discovered = AsyncMock(return_value={
            "total": 1, "agents": [{"id": "a", "status": "unmanaged"}], "next_token": None})
        svc.summary = AsyncMock(return_value={
            "detected": 1, "unmanaged": 1, "new_24h": 0,
            "providers_connected": 1, "providers_total": 3, "last_scan": "2026-06-06T00:00:00Z"})
        svc.platforms = AsyncMock(return_value={"providers": []})
        svc.import_agents = AsyncMock(return_value={
            "imported": 1, "agents": [{"discovery_id": "a", "agent_id": "a", "status": "managed"}]})
        mock.return_value = svc
        yield svc


def test_discovery_agents(client, mock_discovery):
    r = client.get("/v1/discovery/agents?status=unmanaged")
    assert r.status_code == 200
    assert r.json()["total"] == 1


def test_discovery_summary_and_platforms(client, mock_discovery):
    assert client.get("/v1/discovery/summary").status_code == 200
    assert client.get("/v1/discovery/platforms").status_code == 200


def test_discovery_import_ok(client, mock_discovery, as_editor):
    # WS-M M2.6: now editor-gated; the raw id is prefix-stamped to ctx.tenant_id.
    r = client.post("/v1/discovery/import", json={"agent_ids": ["a"]})
    assert r.status_code == 201
    assert r.json()["imported"] == 1


def test_discovery_import_empty_400(client, mock_discovery, as_editor):
    mock_discovery.import_agents.side_effect = ValueError("required")
    r = client.post("/v1/discovery/import", json={"agent_ids": []})
    assert r.status_code == 400


def test_discovery_import_all_unknown_422(client, mock_discovery, as_editor):
    mock_discovery.import_agents.side_effect = LookupError("none in policy")
    r = client.post("/v1/discovery/import", json={"agent_ids": ["x"]})
    assert r.status_code == 422


def test_discovery_import_prefix_stamps_ctx_tenant(client, mock_discovery, as_editor):
    """M2.6: an unprefixed id is stamped to ctx.tenant_id before the write."""
    client.post("/v1/discovery/import", json={"agent_ids": ["a", "t_ph-b"]})
    stamped = mock_discovery.import_agents.call_args.args[0]
    # "a" gets the tenant prefix; an already-correct prefix is left unchanged.
    assert stamped == ["t_ph-a", "t_ph-b"]


# WS-M FIX-B: edge-validation of agent_ids — a malformed element must be an honest
# 400, NOT a bare 500 (a non-string element would raise AttributeError on
# .startswith and leak a non-customer-safe failure mode).
def test_discovery_import_non_string_element_400(client, mock_discovery, as_editor):
    r = client.post("/v1/discovery/import", json={"agent_ids": [123]})
    assert r.status_code == 400
    assert "non-empty strings" in r.json()["detail"]
    mock_discovery.import_agents.assert_not_called()


def test_discovery_import_empty_string_element_400(client, mock_discovery, as_editor):
    r = client.post("/v1/discovery/import", json={"agent_ids": ["ok", ""]})
    assert r.status_code == 400
    mock_discovery.import_agents.assert_not_called()


def test_discovery_import_non_list_agent_ids_400(client, mock_discovery, as_editor):
    r = client.post("/v1/discovery/import", json={"agent_ids": {"a": 1}})
    assert r.status_code == 400
    mock_discovery.import_agents.assert_not_called()


# ----------------------------------------------------------------- attach/detach

@pytest.fixture
def mock_agent_attach():
    with patch('app.services.agent_service.AgentService') as mock:
        svc = Mock()
        svc.attach_policy = AsyncMock(return_value={
            "agent_id": "a", "policy_id": "p", "status": "attached", "attached_at": "x"})
        svc.detach_policy = AsyncMock(return_value={
            "agent_id": "a", "policy_id": "p", "status": "detached"})
        mock.return_value = svc
        yield svc


def test_attach_ok(client, mock_agent_attach, as_editor):
    r = client.post("/v1/agents/a/policies", json={"policy_id": "p"})
    assert r.status_code == 200
    assert r.json()["status"] == "attached"


def test_attach_missing_policy_id_400(client, mock_agent_attach, as_editor):
    assert client.post("/v1/agents/a/policies", json={}).status_code == 400


def test_attach_unknown_404(client, mock_agent_attach, as_editor):
    mock_agent_attach.attach_policy.side_effect = KeyError("agent a not found")
    r = client.post("/v1/agents/a/policies", json={"policy_id": "p"})
    assert r.status_code == 404


def test_attach_when_bound_replaces_no_409(client, mock_agent_attach, as_editor):
    """agent-policy-management T21: rebind-as-replace. Attaching to an
    already-bound agent is an atomic swap → 200, NOT a 409. The service no longer
    raises ValueError on rebind, and the route no longer maps one to 409."""
    r = client.post("/v1/agents/a/policies", json={"policy_id": "p"})
    assert r.status_code == 200
    assert r.json()["status"] == "attached"


def test_detach_ok(client, mock_agent_attach, as_editor):
    r = client.delete("/v1/agents/a/policies/p")
    assert r.status_code == 200
    assert r.json()["status"] == "detached"


def test_detach_not_attached_404(client, mock_agent_attach, as_editor):
    mock_agent_attach.detach_policy.side_effect = KeyError("not attached")
    assert client.delete("/v1/agents/a/policies/p").status_code == 404


# ----------------------------------------------------------------------- verdict

@pytest.fixture
def mock_verdict():
    with patch('app.api.routes._decisions_service') as mock:
        svc = Mock()
        svc.record_verdict = Mock(return_value={
            "decision_id": "s:r", "verdict": "false_positive", "verdict_at": "x"})
        mock.return_value = svc
        yield svc


def test_verdict_ok(client, mock_verdict, as_editor):
    # WS-M M2.7: now editor-gated + session-owned; operator derives from ctx.sub, so
    # a body operator_id is ignored (still accepted in the payload, just not used).
    r = client.post("/v1/decisions/s:r/verdict",
                    json={"verdict": "false_positive", "reason": "benign", "operator_id": "op1"})
    assert r.status_code == 200
    assert r.json()["verdict"] == "false_positive"
    # attribution is the verified ctx.sub ("op-ph"), never the body operator_id.
    assert mock_verdict.record_verdict.call_args.args[3] == "op-ph"


def test_verdict_bad_value_400(client, mock_verdict, as_editor):
    r = client.post("/v1/decisions/s:r/verdict",
                    json={"verdict": "nonsense", "reason": "x", "operator_id": "o"})
    assert r.status_code == 400


def test_verdict_missing_fields_400(client, mock_verdict, as_editor):
    # reason is still required (operator_id is no longer a required body field — it
    # is derived from the verified identity).
    r = client.post("/v1/decisions/s:r/verdict", json={"verdict": "false_positive"})
    assert r.status_code == 400


def test_verdict_not_found_404(client, mock_verdict, as_editor):
    mock_verdict.record_verdict.side_effect = LookupError("no decision")
    r = client.post("/v1/decisions/s:r/verdict",
                    json={"verdict": "false_positive", "reason": "x", "operator_id": "o"})
    assert r.status_code == 404


def test_verdict_already_verdicted_409(client, mock_verdict, as_editor):
    mock_verdict.record_verdict.side_effect = RuntimeError("already verdicted")
    r = client.post("/v1/decisions/s:r/verdict",
                    json={"verdict": "false_positive", "reason": "x", "operator_id": "o"})
    assert r.status_code == 409
