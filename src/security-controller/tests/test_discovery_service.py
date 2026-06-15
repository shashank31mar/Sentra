"""DiscoveryService — detected-agents union + NotImported/Imported/Managed (feature §8.1)."""
import boto3
import pytest
from moto import mock_aws

from app.config import settings
from app.services.discovery_service import DiscoveryService, _risk_from_severity


def test_risk_heuristic():
    assert _risk_from_severity({"high": 1}) == "high"
    assert _risk_from_severity({"critical": 2}) == "high"
    assert _risk_from_severity({"medium": 1}) == "med"
    assert _risk_from_severity({"low": 5}) == "low"
    assert _risk_from_severity(None) == "low"


@pytest.fixture
def aws_creds(monkeypatch):
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SECURITY_TOKEN", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(k, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", settings.aws_region)


@pytest.fixture
def tables(aws_creds, monkeypatch):
    monkeypatch.setattr(settings, "tenancy_v2_enabled", False)  # v1 keys
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name=settings.aws_region)
        ddb.create_table(
            TableName=settings.dynamodb_agent_registry_table,
            KeySchema=[{"AttributeName": "agent_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "agent_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        ddb.create_table(
            TableName=settings.dynamodb_policies_metadata_table,
            KeySchema=[{"AttributeName": "policy_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "policy_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        ddb.create_table(
            TableName=settings.dynamodb_discovery_cache_table,
            KeySchema=[{"AttributeName": "tenant_id", "KeyType": "HASH"},
                       {"AttributeName": "native_resource_id", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "tenant_id", "AttributeType": "S"},
                                  {"AttributeName": "native_resource_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        ddb.create_table(
            TableName=settings.dynamodb_validation_signals_table,
            KeySchema=[{"AttributeName": "session_id", "KeyType": "HASH"},
                       {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "session_id", "AttributeType": "S"},
                                  {"AttributeName": "sk", "AttributeType": "S"},
                                  {"AttributeName": "agent_id", "AttributeType": "S"},
                                  {"AttributeName": "timestamp_ms", "AttributeType": "N"}],
            GlobalSecondaryIndexes=[{
                "IndexName": "agent-timestamp-index",
                "KeySchema": [{"AttributeName": "agent_id", "KeyType": "HASH"},
                              {"AttributeName": "timestamp_ms", "KeyType": "RANGE"}],
                "Projection": {"ProjectionType": "ALL"}}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield {
            "registry": ddb.Table(settings.dynamodb_agent_registry_table),
            "policies": ddb.Table(settings.dynamodb_policies_metadata_table),
            "cache": ddb.Table(settings.dynamodb_discovery_cache_table),
            "signals": ddb.Table(settings.dynamodb_validation_signals_table),
        }


def _signal(agent_id, ts_ms=1700000000000):
    return {"session_id": f"s-{agent_id}", "sk": f"r-{agent_id}#{ts_ms}#sentra.policy",
            "agent_id": agent_id, "timestamp_ms": ts_ms, "timestamp_iso": "2026-06-11T12:00:00.000Z"}


@pytest.mark.asyncio
async def test_union_three_states(tables):
    # imported + traffic → managed; imported, no traffic → imported; scanned-only → not_imported
    tables["registry"].put_item(Item={"agent_id": "agent-managed", "name": "Managed", "cloud_provider": "aws",
                                       "native_resource_id": "arn-managed"})
    tables["registry"].put_item(Item={"agent_id": "agent-quiet", "name": "Quiet", "cloud_provider": "aws",
                                       "native_resource_id": "arn-quiet"})
    tables["signals"].put_item(Item=_signal("agent-managed"))
    tables["cache"].put_item(Item={"tenant_id": "default", "native_resource_id": "arn-new",
                                    "name": "scanned-new", "cloud_provider": "aws", "connection_id": "conn-1"})

    out = await DiscoveryService().list_discovered()
    by_id = {r["name"]: r for r in out["agents"]}
    assert by_id["Managed"]["status"] == "managed"
    assert by_id["Managed"]["last_active"] is not None
    assert by_id["Quiet"]["status"] == "imported"
    assert by_id["scanned-new"]["status"] == "not_imported"
    assert by_id["scanned-new"]["agent_id"] is None
    assert out["total"] == 3


@pytest.mark.asyncio
async def test_dedupe_scanned_against_imported(tables):
    # A scanned agent whose name matches an imported agent must NOT duplicate.
    tables["registry"].put_item(Item={"agent_id": "acme-payments-agent", "name": "acme-payments-agent",
                                       "cloud_provider": "aws"})  # no native_resource_id (pre-backfill)
    tables["cache"].put_item(Item={"tenant_id": "default", "native_resource_id": "JGECQEHF9N",
                                    "name": "acme-payments-agent", "cloud_provider": "aws"})
    out = await DiscoveryService().list_discovered()
    names = [r["name"] for r in out["agents"]]
    assert names.count("acme-payments-agent") == 1  # deduped by normalized-name fallback
    assert out["total"] == 1


@pytest.mark.asyncio
async def test_status_filter_and_connection_scope(tables):
    tables["registry"].put_item(Item={"agent_id": "imp", "name": "imp", "cloud_provider": "aws"})
    tables["cache"].put_item(Item={"tenant_id": "default", "native_resource_id": "n1", "name": "scan1",
                                    "cloud_provider": "aws", "connection_id": "conn-A"})
    tables["cache"].put_item(Item={"tenant_id": "default", "native_resource_id": "n2", "name": "scan2",
                                    "cloud_provider": "aws", "connection_id": "conn-B"})
    svc = DiscoveryService()
    not_imp = await svc.list_discovered(status="not_imported")
    assert {r["name"] for r in not_imp["agents"]} == {"scan1", "scan2"}
    scoped = await svc.list_discovered(connection_id="conn-A")
    names = {r["name"] for r in scoped["agents"]}
    assert "scan1" in names and "scan2" not in names  # connection_id filters scanned rows


@pytest.mark.asyncio
async def test_import_scanned_uses_canonical_id_from_native(tables):
    from app.services.discovery_service import canonical_agent_id
    tables["cache"].put_item(Item={"tenant_id": "default", "native_resource_id": "arn-x",
                                    "name": "new-agent", "cloud_provider": "aws"})
    out = await DiscoveryService().import_agents(["arn-x"], enforcement_mode="enforce")
    assert out["imported"] == 1
    assert out["agents"][0]["status"] == "managed"
    # agent_id is canonical (native-derived), NOT the display name (feature §10.1)
    expected = canonical_agent_id("default", "aws", "arn-x")
    assert out["agents"][0]["agent_id"] == expected
    row = tables["registry"].get_item(Key={"agent_id": expected}).get("Item")
    assert row is not None
    assert row["native_resource_id"] == "arn-x"        # native id stored (DA1)
    assert row["name"] == "new-agent"                   # display name preserved
    assert row["enforcement_mode"] == "enforce"
    # re-import is idempotent (deduped by native id, not name)
    again = await DiscoveryService().import_agents(["arn-x"])
    assert again["agents"][0]["status"] == "skipped"


@pytest.mark.asyncio
async def test_import_same_name_different_native_no_collision(tables):
    """Two Azure deployments both named 'gpt-4o-mini' in different accounts must
    import as DISTINCT agents — the canonical id is native-derived (feature §10.1)."""
    base = "/subscriptions/{s}/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/{a}/deployments/gpt-4o-mini"
    n1 = base.format(s="sub-A", a="acct1")
    n2 = base.format(s="sub-B", a="acct2")
    for n in (n1, n2):
        tables["cache"].put_item(Item={"tenant_id": "default", "native_resource_id": n,
                                        "name": "gpt-4o-mini", "cloud_provider": "azure",
                                        "platform": "azure_foundry"})
    out = await DiscoveryService().import_agents([n1, n2])
    assert out["imported"] == 2                         # no false "skipped" collision
    ids = {a["agent_id"] for a in out["agents"]}
    assert len(ids) == 2


@pytest.mark.asyncio
async def test_import_azure_scanned_sets_platform_and_placement(tables):
    """An Azure-scanned agent imports as an active azure_foundry registry row,
    carrying the placement/capability fields the scanner supplied (feature §7)."""
    from app.services.discovery_service import canonical_agent_id
    native = ("/subscriptions/sub/resourceGroups/rg/providers/"
              "Microsoft.CognitiveServices/accounts/acct/deployments/identity")
    tables["cache"].put_item(Item={
        "tenant_id": "default", "native_resource_id": native, "name": "acme-identity-agent",
        "cloud_provider": "azure", "platform": "azure_foundry", "framework": "azure_openai",
        "region": "centralus", "model": "gpt-4o-mini", "tools": ["verify_identity"],
    })
    out = await DiscoveryService().import_agents([native], enforcement_mode="monitor")
    assert out["imported"] == 1 and out["agents"][0]["status"] == "managed"
    agent_id = canonical_agent_id("default", "azure", native)
    row = tables["registry"].get_item(Key={"agent_id": agent_id}).get("Item")
    assert row["status"] == "active"
    assert row["name"] == "acme-identity-agent"          # display name preserved
    assert row["cloud_provider"] == "azure"
    assert row["platform"] == "azure_foundry"            # derived from the scanned record
    assert row["cloud_region"] == "centralus"
    assert row["foundation_model"] == "gpt-4o-mini"
    assert row["allowed_tools"] == ["verify_identity"]


@pytest.mark.asyncio
async def test_import_empty_and_unknown(tables):
    with pytest.raises(ValueError):
        await DiscoveryService().import_agents([])
    with pytest.raises(LookupError):
        await DiscoveryService().import_agents(["nope-does-not-exist"])


@pytest.mark.asyncio
async def test_pagination_and_bad_cursor(tables):
    for i in range(5):
        tables["cache"].put_item(Item={"tenant_id": "default", "native_resource_id": f"n{i}",
                                        "name": f"a{i}", "cloud_provider": "aws"})
    svc = DiscoveryService()
    p1 = await svc.list_discovered(limit=2)
    assert p1["total"] == 5 and len(p1["agents"]) == 2 and p1["next_token"]
    p2 = await svc.list_discovered(limit=2, cursor=p1["next_token"])
    assert {a["id"] for a in p2["agents"]}.isdisjoint({a["id"] for a in p1["agents"]})
    with pytest.raises(ValueError):
        await svc.list_discovered(cursor="!!!not-base64!!!")


@pytest.mark.asyncio
async def test_summary_counts(tables):
    tables["registry"].put_item(Item={"agent_id": "imp", "name": "imp", "cloud_provider": "aws"})
    tables["cache"].put_item(Item={"tenant_id": "default", "native_resource_id": "n1", "name": "scan1",
                                    "cloud_provider": "aws"})
    summary = await DiscoveryService().summary()
    assert summary["detected"] == 2
    assert summary["unmanaged"] == 1   # not_imported count
    assert summary["providers_total"] == 3
