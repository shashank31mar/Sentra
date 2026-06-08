"""Unit tests for DiscoveryService (WS-21 T31/T32) — static policy-derived read-model."""
from unittest.mock import Mock, patch

import pytest

from app.services.discovery_service import DiscoveryService, _risk_from_severity


@pytest.fixture
def svc_tables():
    policy_table = Mock()
    registry_table = Mock()

    def table_factory(name):
        return registry_table if "registry" in name else policy_table

    with patch("app.services.discovery_service.boto3.resource") as res:
        res.return_value.Table.side_effect = table_factory
        svc = DiscoveryService()
        yield svc, policy_table, registry_table


def test_risk_heuristic():
    assert _risk_from_severity({"high": 1}) == "high"
    assert _risk_from_severity({"critical": 2}) == "high"
    assert _risk_from_severity({"medium": 1}) == "med"
    assert _risk_from_severity({"low": 5}) == "low"
    assert _risk_from_severity(None) == "low"


@pytest.mark.asyncio
async def test_list_discovered_managed_vs_unmanaged(svc_tables):
    svc, policy_table, registry_table = svc_tables
    policy_table.scan.return_value = {"Items": [
        {"agent_id": "agA", "name": "Agent A", "created_at": "2026-06-06T00:00:00Z",
         "severity_breakdown": {"high": 1}},
        {"agent_id": "agB", "name": "Agent B", "created_at": "2026-06-05T00:00:00Z",
         "severity_breakdown": {"low": 1}},
    ]}
    registry_table.scan.return_value = {"Items": [
        {"agent_id": "agA", "cloud_provider": "aws"},
    ]}

    out = await svc.list_discovered()
    by_id = {r["id"]: r for r in out["agents"]}
    assert out["total"] == 2
    assert by_id["agA"]["status"] == "managed"
    assert by_id["agA"]["cloud_provider"] == "aws"
    assert by_id["agA"]["risk"] == "high"
    assert by_id["agB"]["status"] == "unmanaged"
    assert by_id["agB"]["cloud_provider"] == "unknown"
    assert out["next_token"] is None


@pytest.mark.asyncio
async def test_list_discovered_status_filter(svc_tables):
    svc, policy_table, registry_table = svc_tables
    policy_table.scan.return_value = {"Items": [
        {"agent_id": "agA", "name": "A"}, {"agent_id": "agB", "name": "B"},
    ]}
    registry_table.scan.return_value = {"Items": [{"agent_id": "agA"}]}
    out = await svc.list_discovered(status="unmanaged")
    assert [r["id"] for r in out["agents"]] == ["agB"]


@pytest.mark.asyncio
async def test_list_discovered_honors_limit_and_cursor(svc_tables):
    """Kiro review: limit/cursor are honored (offset pagination over the read-model)."""
    svc, policy_table, registry_table = svc_tables
    policy_table.scan.return_value = {"Items": [
        {"agent_id": f"ag{i}", "name": f"A{i}"} for i in range(5)
    ]}
    registry_table.scan.return_value = {"Items": []}

    page1 = await svc.list_discovered(limit=2)
    assert page1["total"] == 5
    assert len(page1["agents"]) == 2
    assert page1["next_token"] is not None

    page2 = await svc.list_discovered(limit=2, cursor=page1["next_token"])
    assert len(page2["agents"]) == 2
    # page 2 ids differ from page 1
    assert {a["id"] for a in page2["agents"]}.isdisjoint({a["id"] for a in page1["agents"]})

    # last page → no next_token
    page3 = await svc.list_discovered(limit=2, cursor=page2["next_token"])
    assert len(page3["agents"]) == 1
    assert page3["next_token"] is None


@pytest.mark.asyncio
async def test_list_discovered_bad_cursor_raises_value_error(svc_tables):
    svc, policy_table, registry_table = svc_tables
    policy_table.scan.return_value = {"Items": [{"agent_id": "a", "name": "A"}]}
    registry_table.scan.return_value = {"Items": []}
    with pytest.raises(ValueError):
        await svc.list_discovered(cursor="!!!not-base64!!!")


@pytest.mark.asyncio
async def test_summary_counts(svc_tables):
    svc, policy_table, registry_table = svc_tables
    policy_table.scan.return_value = {"Items": [
        {"agent_id": "agA", "name": "A", "created_at": "2026-06-05T00:00:00Z"},
        {"agent_id": "agB", "name": "B", "created_at": "2026-06-05T00:00:00Z"},
    ]}
    registry_table.scan.return_value = {"Items": [{"agent_id": "agA", "cloud_provider": "aws"}]}
    summary = await svc.summary()
    assert summary["detected"] == 2
    assert summary["unmanaged"] == 1
    assert summary["providers_total"] == 3


@pytest.mark.asyncio
async def test_import_creates_managed_skips_existing(svc_tables):
    svc, policy_table, registry_table = svc_tables
    policy_table.scan.return_value = {"Items": [
        {"agent_id": "agA", "name": "A", "policy_id": "pol-A"},
        {"agent_id": "agB", "name": "B", "policy_id": "pol-B"},
    ]}
    registry_table.scan.return_value = {"Items": [{"agent_id": "agA"}]}  # agA already managed

    out = await svc.import_agents(["agA", "agB"], enforcement_mode="monitor")
    statuses = {r["discovery_id"]: r["status"] for r in out["agents"]}
    assert statuses["agA"] == "skipped"      # already managed
    assert statuses["agB"] == "managed"
    assert out["imported"] == 1
    # only agB written to registry
    registry_table.put_item.assert_called_once()
    written = registry_table.put_item.call_args.kwargs["Item"]
    assert written["agent_id"] == "agB"
    assert written["enforcement_mode"] == "monitor"
    assert written["status"] == "active"


@pytest.mark.asyncio
async def test_import_empty_raises_value_error(svc_tables):
    svc, _, _ = svc_tables
    with pytest.raises(ValueError):
        await svc.import_agents([])


@pytest.mark.asyncio
async def test_import_all_unknown_raises_lookup_error(svc_tables):
    svc, policy_table, registry_table = svc_tables
    policy_table.scan.return_value = {"Items": [{"agent_id": "agA", "name": "A", "policy_id": "p"}]}
    registry_table.scan.return_value = {"Items": []}
    with pytest.raises(LookupError):
        await svc.import_agents(["does-not-exist"])
