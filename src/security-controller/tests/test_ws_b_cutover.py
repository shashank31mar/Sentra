"""WS-B cutover tests — explicit S3 prefix (B3) and the residual fallback window (B1).

These complement the B8 isolation matrix (test_multitenancy_isolation.py) with the
two net-new WS-B behaviours: the explicit per-tenant policy-object layout with
dual-read migration, and the time-boxed legacy-fallback window that lets an
enforce-flipped tenant tolerate a not-yet-credentialed agent before expiring it to
a hard DENY.
"""
from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from app.config import settings
from app.utils import tenancy
from tests.mt_helpers import run, create_mt_tables


# =========================================================================== #
# B3 — explicit per-tenant S3 policy prefix
# =========================================================================== #
def test_policy_key_legacy_when_flag_off(monkeypatch):
    monkeypatch.setattr(settings, "tenancy_v2_enabled", True)
    monkeypatch.setattr(settings, "s3_explicit_tenant_prefix", False)
    key = tenancy.policy_s3_object_key("acme-payments-agent", "1.0.0")
    assert key == "policies/agents/acme-payments-agent/v1.0.0.yaml"


def test_policy_key_explicit_when_flag_on(monkeypatch):
    monkeypatch.setattr(settings, "tenancy_v2_enabled", True)
    monkeypatch.setattr(settings, "s3_explicit_tenant_prefix", True)
    token = tenancy.set_current_tenant("acme")
    try:
        key = tenancy.policy_s3_object_key("acme-payments-agent", "1.0.0")
        cedar = tenancy.policy_s3_object_key("acme-payments-agent", "1.0.0", ext="cedar")
    finally:
        tenancy.reset_current_tenant(token)
    assert key == "tenants/acme/policies/agents/acme-payments-agent/v1.0.0.yaml"
    assert cedar == "tenants/acme/policies/agents/acme-payments-agent/v1.0.0.cedar"


def test_explicit_prefix_inert_without_v2(monkeypatch):
    # tenant_id isn't real under v1, so the explicit prefix must NOT engage.
    monkeypatch.setattr(settings, "tenancy_v2_enabled", False)
    monkeypatch.setattr(settings, "s3_explicit_tenant_prefix", True)
    assert tenancy.policy_s3_object_key("a", "1").startswith("policies/agents/")


def test_read_candidates_cover_both_layouts(monkeypatch):
    monkeypatch.setattr(settings, "tenancy_v2_enabled", True)
    # legacy stored key → also try the explicit variant
    legacy = "policies/agents/acme-payments-agent/v1.0.0.yaml"
    cands = tenancy.policy_s3_read_candidates(legacy, tenant="acme")
    assert cands == [legacy, "tenants/acme/" + legacy]
    # explicit stored key → also try the legacy variant
    explicit = "tenants/acme/" + legacy
    assert tenancy.policy_s3_read_candidates(explicit, tenant="acme") == [explicit, legacy]


def test_get_policy_object_dual_read(monkeypatch):
    """The object lives at the LEGACY key but metadata already points at the
    EXPLICIT key (the mid-migration window): dual-read must still find it."""
    monkeypatch.setattr(settings, "tenancy_v2_enabled", True)
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(k, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", settings.aws_region)
    with mock_aws():
        s3 = boto3.client("s3", region_name=settings.aws_region)
        s3.create_bucket(Bucket="test-policy-bucket")
        legacy = "policies/agents/acme-payments-agent/v1.0.0.yaml"
        s3.put_object(Bucket="test-policy-bucket", Key=legacy, Body=b"name: acme")
        from app.utils.s3_policy_store import get_policy_object
        explicit = "tenants/acme/" + legacy
        obj = get_policy_object(s3, "test-policy-bucket", explicit, tenant="acme")
        assert obj["Body"].read() == b"name: acme"
        # And a genuinely-absent object raises (no silent allow).
        with pytest.raises(Exception):
            get_policy_object(s3, "test-policy-bucket", "tenants/acme/policies/agents/ghost/v1.yaml", tenant="acme")


# =========================================================================== #
# B1 — residual uncredentialed-agent legacy-fallback window
# =========================================================================== #
@pytest.fixture
def fb_env(monkeypatch):
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(k, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", settings.aws_region)
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name=settings.aws_region)
        create_mt_tables(ddb)
        import app.utils.clients as clients
        import app.services.fallback_service as fb
        clients._registry = None
        fb._store = None
        yield ddb
        fb._store = None


def test_fallback_disabled_by_default(fb_env, monkeypatch):
    monkeypatch.setattr(settings, "identity_fallback_window_seconds", 0)
    from app.services.fallback_service import get_fallback_store
    d = run(get_fallback_store().consider("acme-payments-agent", "acme"))
    assert d.allow is False and d.state == "disabled"


def test_fallback_opens_then_active(fb_env, monkeypatch):
    monkeypatch.setattr(settings, "identity_fallback_window_seconds", 3600)
    from app.services.fallback_service import get_fallback_store
    store = get_fallback_store()
    first = run(store.consider("acme-telecom-agent", "acme"))
    assert first.allow is True and first.state == "opened"
    # Second sight (now cached) → active, same deadline, still allowed.
    again = run(store.consider("acme-telecom-agent", "acme"))
    assert again.allow is True and again.state == "active"
    assert again.deadline_ms == first.deadline_ms


def test_fallback_expires_to_deny(fb_env, monkeypatch):
    """A row whose deadline is already in the past denies on next sight (the
    persisted deadline is what makes 'expires to DENY' survive restarts)."""
    monkeypatch.setattr(settings, "identity_fallback_window_seconds", 3600)
    from app.services.fallback_service import get_fallback_store, _now_ms
    store = get_fallback_store()
    # Seed an already-expired row directly, bypassing the cache.
    ddb = boto3.resource("dynamodb", region_name=settings.aws_region)
    ddb.Table(settings.dynamodb_identity_fallback_table).put_item(Item={
        "agent_id": "stale-agent", "tenant_id": "acme",
        "first_seen_ms": _now_ms() - 10_000_000, "deadline_ms": _now_ms() - 5_000_000,
        "last_seen_ms": _now_ms() - 6_000_000, "ttl": 1,
    })
    d = run(store.consider("stale-agent", "acme"))
    assert d.allow is False and d.state == "expired"


def test_residual_list(fb_env, monkeypatch):
    monkeypatch.setattr(settings, "identity_fallback_window_seconds", 3600)
    from app.services.fallback_service import get_fallback_store
    store = get_fallback_store()
    run(store.consider("acme-payments-agent", "acme"))
    run(store.consider("globex-agent", "t_globex"))
    acme_only = store.list_residual("acme")
    assert {r["agent_id"] for r in acme_only} == {"acme-payments-agent"}
    assert all(r["expired"] is False for r in acme_only)


def test_fallback_in_tenant_purge_store_list():
    """Tenant deletion must erase fallback rows too (D5 / B8 'tenant delete')."""
    from app.services.tenant_purge import _DDB_STORES
    logicals = {s[0] for s in _DDB_STORES}
    assert "identity-fallback" in logicals
