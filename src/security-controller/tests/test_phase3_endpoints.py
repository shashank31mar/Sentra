"""Route-level tests for WS-21 Phase 3: discovery, attach/detach, verdict (T32-T34)."""
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


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


def test_discovery_import_ok(client, mock_discovery):
    r = client.post("/v1/discovery/import", json={"agent_ids": ["a"]})
    assert r.status_code == 201
    assert r.json()["imported"] == 1


def test_discovery_import_empty_400(client, mock_discovery):
    mock_discovery.import_agents.side_effect = ValueError("required")
    r = client.post("/v1/discovery/import", json={"agent_ids": []})
    assert r.status_code == 400


def test_discovery_import_all_unknown_422(client, mock_discovery):
    mock_discovery.import_agents.side_effect = LookupError("none in policy")
    r = client.post("/v1/discovery/import", json={"agent_ids": ["x"]})
    assert r.status_code == 422


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


def test_attach_ok(client, mock_agent_attach):
    r = client.post("/v1/agents/a/policies", json={"policy_id": "p"})
    assert r.status_code == 200
    assert r.json()["status"] == "attached"


def test_attach_missing_policy_id_400(client, mock_agent_attach):
    assert client.post("/v1/agents/a/policies", json={}).status_code == 400


def test_attach_unknown_404(client, mock_agent_attach):
    mock_agent_attach.attach_policy.side_effect = KeyError("agent a not found")
    r = client.post("/v1/agents/a/policies", json={"policy_id": "p"})
    assert r.status_code == 404


def test_attach_when_bound_replaces_no_409(client, mock_agent_attach):
    """agent-policy-management T21: rebind-as-replace. Attaching to an
    already-bound agent is an atomic swap → 200, NOT a 409. The service no longer
    raises ValueError on rebind, and the route no longer maps one to 409."""
    r = client.post("/v1/agents/a/policies", json={"policy_id": "p"})
    assert r.status_code == 200
    assert r.json()["status"] == "attached"


def test_detach_ok(client, mock_agent_attach):
    r = client.delete("/v1/agents/a/policies/p")
    assert r.status_code == 200
    assert r.json()["status"] == "detached"


def test_detach_not_attached_404(client, mock_agent_attach):
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


def test_verdict_ok(client, mock_verdict):
    r = client.post("/v1/decisions/s:r/verdict",
                    json={"verdict": "false_positive", "reason": "benign", "operator_id": "op1"})
    assert r.status_code == 200
    assert r.json()["verdict"] == "false_positive"


def test_verdict_bad_value_400(client, mock_verdict):
    r = client.post("/v1/decisions/s:r/verdict",
                    json={"verdict": "nonsense", "reason": "x", "operator_id": "o"})
    assert r.status_code == 400


def test_verdict_missing_fields_400(client, mock_verdict):
    r = client.post("/v1/decisions/s:r/verdict", json={"verdict": "false_positive"})
    assert r.status_code == 400


def test_verdict_not_found_404(client, mock_verdict):
    mock_verdict.record_verdict.side_effect = LookupError("no decision")
    r = client.post("/v1/decisions/s:r/verdict",
                    json={"verdict": "false_positive", "reason": "x", "operator_id": "o"})
    assert r.status_code == 404


def test_verdict_already_verdicted_409(client, mock_verdict):
    mock_verdict.record_verdict.side_effect = RuntimeError("already verdicted")
    r = client.post("/v1/decisions/s:r/verdict",
                    json={"verdict": "false_positive", "reason": "x", "operator_id": "o"})
    assert r.status_code == 409
