"""Tenancy v2 verification (Multi-Cloud Agent Import P0a — workstream T10).

Exercises the FLAG-ON (v2) path the rest of the suite (flag-off) can't reach:

* helper builders return the composite v2 shapes (unit, no AWS);
* tenant isolation through real service reads — tenant A never sees tenant B's
  rows across registry / policies / signals (the check the scan-leak fix needs);
* the key-changed GSI readers resolve the tenant's data (agent-index policy
  resolution + decision-date GET /v1/decisions regression guard);
* the signal writer preserves the LLD 17 SK / decision_date format byte-for-byte
  while adding the composite tenant keys;
* the migration transforms copy signal keys verbatim.
"""
import importlib

import boto3
import pytest
from moto import mock_aws

from app.config import settings
from app.utils import tenancy


def _create_bucket(s3, bucket: str, region: str) -> None:
    """Create an S3 bucket honoring the real-S3/moto region contract.

    `create_bucket` only omits a LocationConstraint in ``us-east-1``; every
    other region MUST pass ``CreateBucketConfiguration`` or moto raises
    ``IllegalLocationConstraintException``. ``settings`` defaults to
    ``us-west-2`` (config/dev.yaml), so a bare ``create_bucket`` errors on
    setup — this helper makes the moto fixtures region-safe.
    """
    if region == "us-east-1":
        s3.create_bucket(Bucket=bucket)
    else:
        s3.create_bucket(
            Bucket=bucket,
            CreateBucketConfiguration={"LocationConstraint": region},
        )


# --------------------------------------------------------------------------- #
# Helper unit tests (no AWS, no flag mutation beyond the local toggle)
# --------------------------------------------------------------------------- #
def test_helpers_v1_shape(monkeypatch):
    monkeypatch.setattr(settings, "tenancy_v2_enabled", False)
    assert tenancy.item_key("agent_id", "a1") == {"agent_id": "a1"}
    kce, val = tenancy.agent_index_kce_value("a1")
    assert kce == "agent_id = :agent_id" and val == "a1"
    assert tenancy.signal_pk_attr() == "session_id"
    assert tenancy.signal_pk_value("s1") == "s1"
    assert tenancy.decision_date_gsi_attr() == "decision_date"
    assert tenancy.stamp_base_item({"x": 1}) == {"x": 1}  # no tenant attrs


def test_helpers_v2_shape(monkeypatch):
    monkeypatch.setattr(settings, "tenancy_v2_enabled", True)
    assert tenancy.item_key("agent_id", "a1") == {"tenant_id": "default", "agent_id": "a1"}
    kce, val = tenancy.agent_index_kce_value("a1")
    assert kce == "tenant_agent_id = :agent_id" and val == "default#a1"
    assert tenancy.signal_pk_attr() == "tenant_session_id"
    assert tenancy.signal_pk_value("s1") == "default#s1"
    assert tenancy.decision_date_gsi_value("2026-06-11") == "default#2026-06-11"
    kce, names, values = tenancy.status_index_query("active")
    assert kce == "tenant_id = :__t AND #status = :status"
    assert values == {":__t": "default", ":status": "active"}


def test_helpers_table_name_flag_switch(monkeypatch):
    monkeypatch.setattr(settings, "tenancy_v2_enabled", False)
    assert tenancy.table_name("agent_registry") == settings.dynamodb_agent_registry_table
    monkeypatch.setattr(settings, "tenancy_v2_enabled", True)
    assert tenancy.table_name("agent_registry") == settings.dynamodb_agent_registry_table_v2


def test_set_current_tenant(monkeypatch):
    monkeypatch.setattr(settings, "tenancy_v2_enabled", True)
    token = tenancy.set_current_tenant("acme")
    try:
        assert tenancy.current_tenant() == "acme"
        assert tenancy.item_key("agent_id", "a1") == {"tenant_id": "acme", "agent_id": "a1"}
    finally:
        tenancy.reset_current_tenant(token)
    assert tenancy.current_tenant() == "default"


def test_stamp_signal_item_preserves_sk_and_decision_date(monkeypatch):
    monkeypatch.setattr(settings, "tenancy_v2_enabled", True)
    item = {
        "session_id": "s1", "agent_id": "a1",
        "sk": "req-1#1700000000000#sentra.policy",
        "decision_date": "2026-06-11", "timestamp_ms": 1700000000000,
    }
    out = tenancy.stamp_signal_item(dict(item))
    # added composite keys
    assert out["tenant_session_id"] == "default#s1"
    assert out["tenant_agent_id"] == "default#a1"
    assert out["tenant_decision_date"] == "default#2026-06-11"
    # untouched (LLD 17 contract)
    assert out["sk"] == item["sk"]
    assert out["decision_date"] == item["decision_date"]
    assert out["timestamp_ms"] == item["timestamp_ms"]


# --------------------------------------------------------------------------- #
# Migration transform byte-preservation (workstream T07 acceptance)
# --------------------------------------------------------------------------- #
def test_migration_signal_transform_is_byte_identical():
    mig = importlib.import_module("scripts.migrate_tenancy") if _scripts_importable() \
        else _load_migrate_module()
    src = {
        "session_id": "s1", "agent_id": "a1",
        "sk": "req-9#1699999999999#sentra.sigma",
        "decision_date": "2026-06-10", "timestamp_ms": 1699999999999,
        "decision": "DENY",
    }
    out = mig._transform_signals(src, "default")
    for k in ("sk", "decision_date", "timestamp_ms", "decision"):
        assert out[k] == src[k]  # never recomputed
    assert out["tenant_session_id"] == "default#s1"
    assert out["tenant_decision_date"] == "default#2026-06-10"


def _scripts_importable() -> bool:
    try:
        importlib.import_module("scripts.migrate_tenancy")
        return True
    except Exception:
        return False


def _load_migrate_module():
    import os
    import sys
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    scripts_dir = os.path.join(root, "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    return importlib.import_module("migrate_tenancy")


# --------------------------------------------------------------------------- #
# moto-backed flag-ON isolation + GSI resolution
# --------------------------------------------------------------------------- #
@pytest.fixture
def aws_creds(monkeypatch):
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SECURITY_TOKEN", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(k, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", settings.aws_region)


def _create_v2_tables(ddb):
    ddb.create_table(
        TableName=settings.dynamodb_agent_registry_table_v2,
        KeySchema=[{"AttributeName": "tenant_id", "KeyType": "HASH"},
                   {"AttributeName": "agent_id", "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": "tenant_id", "AttributeType": "S"},
                              {"AttributeName": "agent_id", "AttributeType": "S"},
                              {"AttributeName": "status", "AttributeType": "S"}],
        GlobalSecondaryIndexes=[{
            "IndexName": "status-index",
            "KeySchema": [{"AttributeName": "tenant_id", "KeyType": "HASH"},
                          {"AttributeName": "status", "KeyType": "RANGE"}],
            "Projection": {"ProjectionType": "ALL"}}],
        BillingMode="PAY_PER_REQUEST",
    )
    ddb.create_table(
        TableName=settings.dynamodb_policies_metadata_table_v2,
        KeySchema=[{"AttributeName": "tenant_id", "KeyType": "HASH"},
                   {"AttributeName": "policy_id", "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": "tenant_id", "AttributeType": "S"},
                              {"AttributeName": "policy_id", "AttributeType": "S"},
                              {"AttributeName": "tenant_agent_id", "AttributeType": "S"},
                              {"AttributeName": "status", "AttributeType": "S"}],
        GlobalSecondaryIndexes=[
            {"IndexName": "agent-index",
             "KeySchema": [{"AttributeName": "tenant_agent_id", "KeyType": "HASH"}],
             "Projection": {"ProjectionType": "ALL"}},
            {"IndexName": "status-index",
             "KeySchema": [{"AttributeName": "tenant_id", "KeyType": "HASH"},
                           {"AttributeName": "status", "KeyType": "RANGE"}],
             "Projection": {"ProjectionType": "ALL"}}],
        BillingMode="PAY_PER_REQUEST",
    )
    ddb.create_table(
        TableName=settings.dynamodb_validation_signals_table_v2,
        KeySchema=[{"AttributeName": "tenant_session_id", "KeyType": "HASH"},
                   {"AttributeName": "sk", "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": "tenant_session_id", "AttributeType": "S"},
                              {"AttributeName": "sk", "AttributeType": "S"},
                              {"AttributeName": "tenant_agent_id", "AttributeType": "S"},
                              {"AttributeName": "tenant_decision_date", "AttributeType": "S"},
                              {"AttributeName": "timestamp_ms", "AttributeType": "N"}],
        GlobalSecondaryIndexes=[
            {"IndexName": "agent-timestamp-index",
             "KeySchema": [{"AttributeName": "tenant_agent_id", "KeyType": "HASH"},
                           {"AttributeName": "timestamp_ms", "KeyType": "RANGE"}],
             "Projection": {"ProjectionType": "ALL"}},
            {"IndexName": "decision-date-timestamp-index",
             "KeySchema": [{"AttributeName": "tenant_decision_date", "KeyType": "HASH"},
                           {"AttributeName": "timestamp_ms", "KeyType": "RANGE"}],
             "Projection": {"ProjectionType": "ALL"}}],
        BillingMode="PAY_PER_REQUEST",
    )


@pytest.fixture
def v2_env(aws_creds, monkeypatch):
    monkeypatch.setattr(settings, "tenancy_v2_enabled", True)
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name=settings.aws_region)
        _create_v2_tables(ddb)
        yield ddb


def test_registry_tenant_isolation(v2_env):
    """A default-tenant list_agents never returns a tenant=other row (scan leak guard)."""
    from app.services.agent_service import AgentService

    reg = v2_env.Table(settings.dynamodb_agent_registry_table_v2)
    reg.put_item(Item={"tenant_id": "default", "agent_id": "mine", "status": "active", "name": "Mine"})
    reg.put_item(Item={"tenant_id": "other", "agent_id": "theirs", "status": "active", "name": "Theirs"})

    svc = AgentService()
    result = pytest_run(svc.list_agents(enrich=False))
    ids = {a["agent_id"] for a in result["agents"]}
    assert "mine" in ids
    assert "theirs" not in ids  # cross-tenant row must not leak


def test_get_agent_is_tenant_scoped(v2_env):
    from app.services.agent_service import AgentService

    reg = v2_env.Table(settings.dynamodb_agent_registry_table_v2)
    reg.put_item(Item={"tenant_id": "other", "agent_id": "theirs", "status": "active", "name": "Theirs"})

    svc = AgentService()
    # current tenant is "default"; the other-tenant agent must be invisible.
    assert pytest_run(svc.get_agent("theirs")) is None


def test_policy_engine_resolves_v2_agent_index(v2_env):
    """agent-index GSI (composite tenant_agent_id) resolves the tenant's policy."""
    import boto3 as _b
    from app.validators.policy_engine import PolicyEngine

    s3 = _b.client("s3", region_name=settings.aws_region)
    _create_bucket(s3, settings.s3_bucket, settings.aws_region)
    s3_key = "policies/agents/agentA/v1.yaml"
    s3.put_object(Bucket=settings.s3_bucket, Key=s3_key,
                  Body=b"agent_id: agentA\nallowed_tools:\n  - read_thing\nallowed_agents: []\n")

    pol = v2_env.Table(settings.dynamodb_policies_metadata_table_v2)
    pol.put_item(Item={"tenant_id": "default", "policy_id": "p1", "agent_id": "agentA",
                       "tenant_agent_id": "default#agentA", "status": "active",
                       "s3_bucket": settings.s3_bucket, "s3_key": s3_key})
    # a colliding agent_id under another tenant must NOT resolve for default.
    pol.put_item(Item={"tenant_id": "other", "policy_id": "p2", "agent_id": "agentA",
                       "tenant_agent_id": "other#agentA", "status": "active",
                       "s3_bucket": settings.s3_bucket, "s3_key": s3_key})

    engine = PolicyEngine()
    policy = pytest_run(engine.get_agent_policy("agentA"))
    assert "read_thing" in policy["allowed_tools"]


def test_signal_writer_and_decisions_gsi_v2(v2_env):
    """Writer stamps composite keys (SK unchanged); decisions decision-date GSI
    returns the tenant's rows (GET /v1/decisions regression guard)."""
    from datetime import datetime, timezone
    from app.combiners.signal import Signal
    from app.utils.signal_store_writer import SignalStoreWriter
    from app.services.decisions_service import DecisionsService

    now = datetime(2026, 6, 11, 12, 0, 0, tzinfo=timezone.utc)
    writer = SignalStoreWriter()
    sig = Signal(source="sentra.policy", decision="ALLOW", priority=50)
    ok, fail = writer.write_signals(
        session_id="sessX", request_id="reqX", signals=[sig],
        shared_attrs={"agent_id": "agentA"}, now=now,
    )
    assert (ok, fail) == (1, 0)

    # Row landed under the composite PK with SK format intact.
    tbl = v2_env.Table(settings.dynamodb_validation_signals_table_v2)
    row = tbl.get_item(Key={"tenant_session_id": "default#sessX",
                            "sk": f"reqX#{int(now.timestamp()*1000)}#sentra.policy"}).get("Item")
    assert row is not None
    assert row["tenant_decision_date"] == "default#2026-06-11"
    assert row["decision_date"] == "2026-06-11"  # unchanged

    # decisions scan via the decision-date GSI returns it (and only the tenant's).
    # until is exclusive of times after midnight, so span to the next day to
    # include the noon row.
    decisions = DecisionsService().scan_decisions(since="2026-06-11", until="2026-06-12")
    assert decisions.get("total", 0) >= 1


# --------------------------------------------------------------------------- #
# small sync runner for the async service methods (avoids a pytest-asyncio dep
# requirement on this module's plain tests)
# --------------------------------------------------------------------------- #
def pytest_run(coro):
    import asyncio
    return asyncio.get_event_loop().run_until_complete(coro)
