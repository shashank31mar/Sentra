"""Tests for the Cloud Connections service (connections-api-spec.md).

Covers the Connect-Account wizard backend: create + external_id mint, provider
gating, role attach + ARN validation, the AssumeRole test status-flip, scan
gating, delete, and tenant isolation. STS/bedrock are stubbed for the connected
path (the live AWS calls are integration-only).
"""
import boto3
import pytest
from moto import mock_aws

from app.config import settings
from app.utils import tenancy


@pytest.fixture
def aws_creds(monkeypatch):
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SECURITY_TOKEN", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(k, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", settings.aws_region)


@pytest.fixture
def svc(aws_creds):
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name=settings.aws_region)
        ddb.create_table(
            TableName=settings.dynamodb_connections_table,
            KeySchema=[{"AttributeName": "tenant_id", "KeyType": "HASH"},
                       {"AttributeName": "id", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "tenant_id", "AttributeType": "S"},
                                  {"AttributeName": "id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        # scan_connection persists discovered agents here (feature §8.1).
        ddb.create_table(
            TableName=settings.dynamodb_discovery_cache_table,
            KeySchema=[{"AttributeName": "tenant_id", "KeyType": "HASH"},
                       {"AttributeName": "native_resource_id", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "tenant_id", "AttributeType": "S"},
                                  {"AttributeName": "native_resource_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        from app.services.connections_service import ConnectionsService
        yield ConnectionsService()


def test_create_mints_external_id_and_scopes(svc):
    conn = svc.create_connection("aws")
    assert conn["cloud_provider"] == "aws"
    assert conn["status"] == "connecting"
    assert conn["external_id"].startswith("ext-default-")
    assert conn["aegion_principal_arn"].startswith("arn:aws:iam::")
    assert "bedrock:ListAgents" in conn["scopes"]
    assert conn["role_arn"] is None
    assert conn["id"].startswith("conn-aws-")


def test_create_gcp_not_available(svc):
    from app.services.connections_service import ProviderNotAvailable
    with pytest.raises(ProviderNotAvailable):
        svc.create_connection("gcp")


def test_list_and_get(svc):
    a = svc.create_connection("aws")
    listing = svc.list_connections()["connections"]
    assert any(c["id"] == a["id"] for c in listing)
    got = svc.get_connection(a["id"])
    assert got["id"] == a["id"]


def test_get_unknown_404(svc):
    from app.services.connections_service import ConnectionNotFound
    with pytest.raises(ConnectionNotFound):
        svc.get_connection("conn-nope")


def test_set_role_arn_valid_and_invalid(svc):
    from app.services.connections_service import InvalidRoleArn
    conn = svc.create_connection("aws")
    good = "arn:aws:iam::531109575379:role/AegionDiscoveryRole"
    updated = svc.set_role_arn(conn["id"], good)
    assert updated["role_arn"] == good
    with pytest.raises(InvalidRoleArn):
        svc.set_role_arn(conn["id"], "not-an-arn")


def test_test_connection_without_role_returns_ok_false(svc):
    conn = svc.create_connection("aws")
    result = svc.test_connection(conn["id"])
    assert result["ok"] is False
    assert "role_arn" in result["message"].lower()


def test_test_connection_flips_connected(svc, monkeypatch):
    conn = svc.create_connection("aws")
    svc.set_role_arn(conn["id"], "arn:aws:iam::531109575379:role/AegionDiscoveryRole")
    # Stub the live AssumeRole + probe (integration-only in CI). Returns the
    # agent list now (count is derived from it).
    fake_agents = [{"native_resource_id": f"arn{i}", "name": f"n{i}"} for i in range(7)]
    monkeypatch.setattr(svc, "_assume_and_probe", lambda r, e: (True, fake_agents, "AssumeRole OK · 7 agents visible"))
    result = svc.test_connection(conn["id"])
    assert result["ok"] is True and result["agents_visible"] == 7
    refreshed = svc.get_connection(conn["id"])
    assert refreshed["status"] == "connected"
    assert refreshed["agents_visible"] == 7
    assert refreshed["connected_at"] is not None


def test_scan_requires_connected(svc, monkeypatch):
    from app.services.connections_service import NotConnected
    conn = svc.create_connection("aws")
    with pytest.raises(NotConnected):
        svc.scan_connection(conn["id"])
    # connect, then scan persists what it lists and returns the real count
    svc.set_role_arn(conn["id"], "arn:aws:iam::531109575379:role/AegionDiscoveryRole")
    fake_agents = [{"native_resource_id": "arn-a", "name": "a"},
                   {"native_resource_id": "arn-b", "name": "b"}]
    monkeypatch.setattr(svc, "_assume_and_probe", lambda r, e: (True, fake_agents, "ok"))
    svc.test_connection(conn["id"])
    scan = svc.scan_connection(conn["id"])
    assert scan["status"] == "scanning"
    assert scan["scan_id"].startswith("scan-")
    assert scan["discovered_count"] == 2


def test_delete(svc):
    from app.services.connections_service import ConnectionNotFound
    conn = svc.create_connection("aws")
    svc.delete_connection(conn["id"])
    with pytest.raises(ConnectionNotFound):
        svc.get_connection(conn["id"])


def test_tenant_isolation(svc):
    """A connection created under tenant 'other' must not appear for 'default'."""
    token = tenancy.set_current_tenant("other")
    try:
        theirs = svc.create_connection("aws")
    finally:
        tenancy.reset_current_tenant(token)
    # back to default
    default_ids = {c["id"] for c in svc.list_connections()["connections"]}
    assert theirs["id"] not in default_ids
    from app.services.connections_service import ConnectionNotFound
    with pytest.raises(ConnectionNotFound):
        svc.get_connection(theirs["id"])


# ===========================================================================
# Azure provider (service principal + Cognitive Services discovery — feature §7)
# ===========================================================================

# Valid-looking GUIDs for the SP triple (subscription / tenant / client id).
_SUB = "11111111-1111-1111-1111-111111111111"
_TEN = "22222222-2222-2222-2222-222222222222"
_CLI = "33333333-3333-3333-3333-333333333333"


class _FakeAzureScanner:
    """Stands in for AzureScanner.discover so tests don't need the Azure SDK or a
    live subscription. Mirrors the (ok, agents|None, message) contract."""

    def __init__(self, ok=True, agents=None, message="ok"):
        self._ok, self._agents, self._message = ok, agents, message
        self.calls = []

    def discover(self, creds):
        self.calls.append(creds)
        return self._ok, self._agents, self._message


def _azure_agents(n):
    return [{
        "native_resource_id": f"/subscriptions/{_SUB}/resourceGroups/rg/providers/"
                              f"Microsoft.CognitiveServices/accounts/acct/deployments/dep{i}",
        "name": f"dep{i}", "status": "Succeeded", "cloud_provider": "azure",
        "platform": "azure_foundry", "framework": "azure_openai",
        "region": "centralus", "model": "gpt-4o-mini", "tools": [],
    } for i in range(n)]


def test_create_azure_mints_connecting(svc):
    conn = svc.create_connection("azure")
    assert conn["cloud_provider"] == "azure"
    assert conn["status"] == "connecting"
    assert conn["id"].startswith("conn-azure-")
    assert conn["role_arn"] is None
    assert conn["external_id"] is None              # AWS confused-deputy guard only
    assert conn["aegion_principal_arn"] is None
    assert any("CognitiveServices" in s for s in conn["scopes"])


def test_set_azure_credentials_valid_and_invalid(svc):
    from app.services.connections_service import InvalidRoleArn
    conn = svc.create_connection("azure")
    updated = svc.set_azure_credentials(
        conn["id"], subscription_id=_SUB, tenant_id=_TEN, client_id=_CLI,
        secret_ref="aegion/azure/acme-sp",
    )
    assert updated["azure_subscription_id"] == _SUB
    assert updated["azure_client_id"] == _CLI
    assert updated["account_ref"] == _SUB
    # the secret reference itself is never projected to the API
    assert "azure_secret_ref" not in updated

    with pytest.raises(InvalidRoleArn):                      # malformed GUID
        svc.set_azure_credentials(conn["id"], subscription_id="nope",
                                  tenant_id=_TEN, client_id=_CLI, secret_ref="r")
    with pytest.raises(InvalidRoleArn):                      # missing secret_ref
        svc.set_azure_credentials(conn["id"], subscription_id=_SUB,
                                  tenant_id=_TEN, client_id=_CLI, secret_ref="")


def test_set_azure_credentials_rejected_on_aws_connection(svc):
    from app.services.connections_service import InvalidRoleArn
    aws = svc.create_connection("aws")
    with pytest.raises(InvalidRoleArn):
        svc.set_azure_credentials(aws["id"], subscription_id=_SUB, tenant_id=_TEN,
                                  client_id=_CLI, secret_ref="r")


def test_azure_test_without_credentials_ok_false(svc):
    conn = svc.create_connection("azure")
    result = svc.test_connection(conn["id"])
    assert result["ok"] is False
    assert "service principal" in result["message"].lower()


def test_azure_test_flips_connected(svc):
    conn = svc.create_connection("azure")
    svc.set_azure_credentials(conn["id"], subscription_id=_SUB, tenant_id=_TEN,
                              client_id=_CLI, secret_ref="aegion/azure/acme-sp")
    svc._azure_scanner = _FakeAzureScanner(ok=True, agents=_azure_agents(3),
                                           message="Service principal OK · 3 agents visible")
    result = svc.test_connection(conn["id"])
    assert result["ok"] is True and result["agents_visible"] == 3
    refreshed = svc.get_connection(conn["id"])
    assert refreshed["status"] == "connected"
    assert refreshed["connected_at"] is not None


def test_azure_scan_persists_with_placement(svc):
    conn = svc.create_connection("azure")
    svc.set_azure_credentials(conn["id"], subscription_id=_SUB, tenant_id=_TEN,
                              client_id=_CLI, secret_ref="aegion/azure/acme-sp")
    svc._azure_scanner = _FakeAzureScanner(ok=True, agents=_azure_agents(2))
    svc.test_connection(conn["id"])
    scan = svc.scan_connection(conn["id"])
    assert scan["status"] == "scanning" and scan["discovered_count"] == 2
    # cache rows carry the azure placement fields the importer relies on
    cache = svc.discovery_cache_table.scan()["Items"]
    assert len(cache) == 2
    row = cache[0]
    assert row["cloud_provider"] == "azure"
    assert row["platform"] == "azure_foundry"
    assert row["region"] == "centralus"


def test_azure_test_failure_marks_error(svc):
    conn = svc.create_connection("azure")
    svc.set_azure_credentials(conn["id"], subscription_id=_SUB, tenant_id=_TEN,
                              client_id=_CLI, secret_ref="aegion/azure/acme-sp")
    svc._azure_scanner = _FakeAzureScanner(ok=False, agents=None,
                                           message="AuthorizationFailed: SP lacks Reader")
    result = svc.test_connection(conn["id"])
    assert result["ok"] is False
    refreshed = svc.get_connection(conn["id"])
    assert refreshed["status"] == "error"
    assert "Reader" in (refreshed["error"] or "")
