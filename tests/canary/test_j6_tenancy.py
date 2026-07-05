"""WS-J J6 — multi-tenant isolation (landed-today, REQUIRED now).

Exercises the EXISTING, DONE tenancy mechanism (LLD 26 — do NOT rebuild): the
``tenancy`` switchboard's tenant-scoped keys + ``query_or_scan`` partition. Under
``TENANCY_V2_ENABLED`` (the enforcing isolation cutover), a write under tenant A is
never readable under tenant B — a cross-tenant read is the failure (Invariant 4 /
NFR-6). Two ephemeral ``canary-<uuid4hex>`` tenants; a cross-tenant read is asserted
against the real tenant-partition Query, not rebuilt.
"""
from __future__ import annotations

import uuid

import boto3
import pytest
from moto import mock_aws

from app.config import settings
from app.utils import tenancy


def _v2_signals_table(ddb):
    """Create the TENANCY_V2 signals table (PK tenant_session_id / SK sk), mirroring
    signal_store_table_construct.py v2."""
    return ddb.create_table(
        TableName=settings.dynamodb_validation_signals_table_v2,
        KeySchema=[
            {"AttributeName": "tenant_session_id", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "tenant_session_id", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )


def test_j6_1_no_cross_tenant_read(monkeypatch):
    """J6.1 — a signal row written under tenant A is NOT returned when the current
    tenant is B (and vice-versa), through the real tenant-partition read."""
    monkeypatch.setattr(settings, "tenancy_v2_enabled", True)
    assert tenancy.v2_enabled()

    tenant_a = f"canary-{uuid.uuid4().hex}"
    tenant_b = f"canary-{uuid.uuid4().hex}"

    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name=settings.aws_region)
        table = _v2_signals_table(ddb)

        # Write one row per tenant for the SAME logical session id (proving it is
        # TENANT isolation, not session isolation — the session id collides).
        session = "shared-session-1"
        for tenant in (tenant_a, tenant_b):
            key = tenancy.signal_item_key(session, "r-1#sentra.policy", tenant=tenant)
            table.put_item(Item={**key, "agent_id": f"agent-{tenant}", "marker": tenant})

        # Read under tenant A: only A's row is in A's partition.
        token = tenancy.set_current_tenant(tenant_a)
        try:
            key_a = tenancy.signal_item_key(session, "r-1#sentra.policy")
            got_a = table.get_item(Key=key_a).get("Item")
        finally:
            tenancy.set_current_tenant(None)
            # contextvars token reset is best-effort; set back to None above.
            del token

        assert got_a is not None and got_a["marker"] == tenant_a
        # B's key is a DIFFERENT partition — A can never address it.
        key_b_from_a = tenancy.signal_item_key(session, "r-1#sentra.policy", tenant=tenant_b)
        assert key_a["tenant_session_id"] != key_b_from_a["tenant_session_id"]

        # Read under tenant B: only B's row.
        tenancy.set_current_tenant(tenant_b)
        try:
            key_b = tenancy.signal_item_key(session, "r-1#sentra.policy")
            got_b = table.get_item(Key=key_b).get("Item")
        finally:
            tenancy.set_current_tenant(None)
        assert got_b is not None and got_b["marker"] == tenant_b


def test_j6_1_partition_scan_excludes_other_tenant(monkeypatch):
    """J6.1 — ``query_or_scan`` (the isolation-leak fix) returns ONLY the current
    tenant's rows, never a cross-tenant row."""
    monkeypatch.setattr(settings, "tenancy_v2_enabled", True)
    tenant_a = f"canary-{uuid.uuid4().hex}"
    tenant_b = f"canary-{uuid.uuid4().hex}"

    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name=settings.aws_region)
        # A generic tenant-partitioned table (PK tenant_id) to exercise query_or_scan.
        table = ddb.create_table(
            TableName="canary-tenant-scan-probe",
            KeySchema=[
                {"AttributeName": "tenant_id", "KeyType": "HASH"},
                {"AttributeName": "id", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "tenant_id", "AttributeType": "S"},
                {"AttributeName": "id", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table.put_item(Item={"tenant_id": tenant_a, "id": "row-a", "marker": tenant_a})
        table.put_item(Item={"tenant_id": tenant_b, "id": "row-b", "marker": tenant_b})

        tenancy.set_current_tenant(tenant_a)
        try:
            resp = tenancy.query_or_scan(table)
        finally:
            tenancy.set_current_tenant(None)
        markers = {it["marker"] for it in resp.get("Items", [])}
        assert markers == {tenant_a}, f"cross-tenant leak: {markers}"


def test_j6_2_no_decision_bleed(monkeypatch):
    """J6.2 — a trust/label row under tenant A does not change a decision key under
    tenant B: the tenant-scoped key space keeps them in disjoint partitions (distinct
    session-id collision proves TENANT, not session, isolation)."""
    monkeypatch.setattr(settings, "tenancy_v2_enabled", True)
    tenant_a = f"canary-{uuid.uuid4().hex}"
    tenant_b = f"canary-{uuid.uuid4().hex}"
    session = "collision-session"

    key_a = tenancy.signal_item_key(session, "trust#1", tenant=tenant_a)
    key_b = tenancy.signal_item_key(session, "trust#1", tenant=tenant_b)
    # Same session id, DIFFERENT partitions → A's trust state cannot key B's read.
    assert key_a["tenant_session_id"].startswith(tenant_a + "#")
    assert key_b["tenant_session_id"].startswith(tenant_b + "#")
    assert key_a["tenant_session_id"] != key_b["tenant_session_id"]
