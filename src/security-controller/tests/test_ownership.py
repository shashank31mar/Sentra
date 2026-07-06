"""Anti-IDOR ownership helper tests (WS-M M0.1 / lld/39 §3.3, §13).

``assert_owns`` is the shared contract that closes BUG-1's IDOR half: RBAC proves
the operator's role, this proves the *resource* is theirs. Every test is a negative
or a fail-secure assertion — a foreign / absent / unresolvable target must never
be treated as owned.

The POLICY / CONNECTION / SESSION paths point-read moto-backed v2 tables; the
critical footgun test (``_bypasses_cache``) proves the helper does NOT reuse the
tenant-blind ``PolicyService.get_policy`` cache.
"""
from __future__ import annotations

import boto3
import pytest
from fastapi import HTTPException
from moto import mock_aws

from app.api.deps import OperatorContext
from app.api.ownership import ResourceKind, assert_owns, _tenant_of_policy
from app.config import settings
from app.utils import tenancy


def _ctx(tenant_id: str = "t_a", role: str = "editor") -> OperatorContext:
    return OperatorContext(sub="op-1", tenant_id=tenant_id, role=role, email="op@x")


# --------------------------------------------------------------------------- #
# AGENT — delimited-prefix, no read
# --------------------------------------------------------------------------- #
def test_assert_owns_agent_prefix_match_ok():
    # own-tenant agent id → no raise
    assert_owns(_ctx("t_a"), ResourceKind.AGENT, "t_a-aws-payments-01")


def test_assert_owns_agent_foreign_prefix_403():
    with pytest.raises(HTTPException) as ei:
        assert_owns(_ctx("t_a"), ResourceKind.AGENT, "t_b-aws-payments-01")
    assert ei.value.status_code == 403


def test_assert_owns_agent_short_prefix_no_false_match():
    """The delimiter guard: tenant ``t_01`` must NOT match agent ``t_01hxyz-…``
    (a bare ``startswith`` would). This is the LLD-26 §3.3 short-prefix trap."""
    with pytest.raises(HTTPException) as ei:
        assert_owns(_ctx("t_01"), ResourceKind.AGENT, "t_01hxyz-aws-x-1")
    assert ei.value.status_code == 403


# --------------------------------------------------------------------------- #
# moto v2-table fixtures (mirror test_multitenancy_isolation)
# --------------------------------------------------------------------------- #
@pytest.fixture
def own_env(monkeypatch):
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SECURITY_TOKEN", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(k, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", settings.aws_region)
    monkeypatch.setattr(settings, "tenancy_v2_enabled", True)
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name=settings.aws_region)
        # policies-metadata v2 (tenant_id, policy_id)
        ddb.create_table(
            TableName=settings.dynamodb_policies_metadata_table_v2,
            KeySchema=[{"AttributeName": "tenant_id", "KeyType": "HASH"},
                       {"AttributeName": "policy_id", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "tenant_id", "AttributeType": "S"},
                                  {"AttributeName": "policy_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        # session-context v2 (tenant_id, session_id)
        ddb.create_table(
            TableName=settings.dynamodb_session_table_v2,
            KeySchema=[{"AttributeName": "tenant_id", "KeyType": "HASH"},
                       {"AttributeName": "session_id", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "tenant_id", "AttributeType": "S"},
                                  {"AttributeName": "session_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        # connections (tenant_id, id) — born tenant-scoped, no flag split
        ddb.create_table(
            TableName=settings.dynamodb_connections_table,
            KeySchema=[{"AttributeName": "tenant_id", "KeyType": "HASH"},
                       {"AttributeName": "id", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "tenant_id", "AttributeType": "S"},
                                  {"AttributeName": "id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield ddb


# --------------------------------------------------------------------------- #
# CONNECTION
# --------------------------------------------------------------------------- #
def test_assert_owns_connection_present_ok(own_env):
    own_env.Table(settings.dynamodb_connections_table).put_item(
        Item={"tenant_id": "t_a", "id": "conn-1", "cloud_provider": "aws"})
    assert_owns(_ctx("t_a"), ResourceKind.CONNECTION, "conn-1")


def test_assert_owns_connection_absent_404(own_env):
    # tenant B owns it; tenant A's scoped read misses → 404 (existence-masked)
    own_env.Table(settings.dynamodb_connections_table).put_item(
        Item={"tenant_id": "t_b", "id": "conn-1", "cloud_provider": "aws"})
    with pytest.raises(HTTPException) as ei:
        assert_owns(_ctx("t_a"), ResourceKind.CONNECTION, "conn-1")
    assert ei.value.status_code == 404


# --------------------------------------------------------------------------- #
# SESSION
# --------------------------------------------------------------------------- #
def test_assert_owns_session_present_ok(own_env):
    own_env.Table(settings.dynamodb_session_table_v2).put_item(
        Item={"tenant_id": "t_a", "session_id": "sess-1", "trust_score": 50})
    assert_owns(_ctx("t_a"), ResourceKind.SESSION, "sess-1")


def test_assert_owns_session_absent_404(own_env):
    own_env.Table(settings.dynamodb_session_table_v2).put_item(
        Item={"tenant_id": "t_b", "session_id": "sess-1", "trust_score": 50})
    with pytest.raises(HTTPException) as ei:
        assert_owns(_ctx("t_a"), ResourceKind.SESSION, "sess-1")
    assert ei.value.status_code == 404


def test_assert_owns_session_unresolvable_denies(own_env, monkeypatch):
    """Flag-off fixture: the tenant can't be bound to a scoped key, so a bare-key
    read would be cross-tenant-readable. The helper must DENY (404), not fall
    through (Invariant 5/7)."""
    monkeypatch.setattr(settings, "tenancy_v2_enabled", False)
    with pytest.raises(HTTPException) as ei:
        assert_owns(_ctx("t_a"), ResourceKind.SESSION, "sess-1")
    assert ei.value.status_code == 404


# --------------------------------------------------------------------------- #
# POLICY
# --------------------------------------------------------------------------- #
def _put_policy(ddb, tenant_id: str, policy_id: str):
    ddb.Table(settings.dynamodb_policies_metadata_table_v2).put_item(
        Item={"tenant_id": tenant_id, "policy_id": policy_id, "status": "active"})


def test_assert_owns_policy_owner_match_ok(own_env):
    _put_policy(own_env, "t_a", "p1")
    assert_owns(_ctx("t_a"), ResourceKind.POLICY, "p1")


def test_assert_owns_policy_foreign_owner_403(own_env, monkeypatch):
    """A policy whose stored tenant_id differs from the caller's → 403. (Force the
    scoped read to surface the foreign row so we exercise the owner-compare, not
    just the partition miss.)"""
    _put_policy(own_env, "t_b", "p1")
    import app.api.ownership as own
    monkeypatch.setattr(own, "_tenant_of_policy", lambda pid, tid: "t_b")
    with pytest.raises(HTTPException) as ei:
        assert_owns(_ctx("t_a"), ResourceKind.POLICY, "p1")
    assert ei.value.status_code == 403


def test_assert_owns_policy_missing_404(own_env):
    with pytest.raises(HTTPException) as ei:
        assert_owns(_ctx("t_a"), ResourceKind.POLICY, "does-not-exist")
    assert ei.value.status_code == 404


def test_assert_owns_policy_bypasses_cache(own_env):
    """FOOTGUN regression (M0.1 / M7 c-warm): warm the tenant-BLIND
    PolicyService.get_policy cache with tenant A's row, then assert tenant B's
    ownership check STILL denies — proving assert_owns does a direct tenant-scoped
    read, not a cached (poisonable) one."""
    from app.services.policy_service import PolicyService
    from tests.mt_helpers import run

    _put_policy(own_env, "t_a", "p1")
    # Warm PolicyService's process-wide, tenant-blind cache under tenant A.
    tenancy.set_current_tenant("t_a")
    run(PolicyService().get_policy("p1"))  # caches key `policy:p1` = tenant A's row
    tenancy.set_current_tenant(tenancy.DEFAULT_TENANT)

    # Tenant B checks ownership of p1 → must NOT be served A's cached row.
    with pytest.raises(HTTPException) as ei:
        assert_owns(_ctx("t_b"), ResourceKind.POLICY, "p1")
    assert ei.value.status_code == 404  # absent from B's partition


def test_assert_owns_lookup_error_denies(own_env, monkeypatch):
    """A store error on the ownership read fails secure (deny), never allow."""
    import app.api.ownership as own

    def _boom(pid, tid):
        raise RuntimeError("ddb down")

    monkeypatch.setattr(own, "_tenant_of_policy", _boom)
    with pytest.raises(HTTPException) as ei:
        assert_owns(_ctx("t_a"), ResourceKind.POLICY, "p1")
    assert ei.value.status_code == 404
