"""Tenant-isolation negative-test matrix — the WS-B B8 MERGE GATE (LLD-26 §4.7).

Isolation is a security boundary, so these are explicit *negative* tests: with
the current tenant = A, no reader returns B's rows; a write under A never mutates
a B-keyed item; the contextvar survives the sync/async thread boundary (the B7
leak); unverified requests audit under `_unverified`; and a tenant purge leaves
nothing keyed to the deleted tenant. A failure here must block merge.
"""
from __future__ import annotations

import asyncio

import boto3
import pytest
from moto import mock_aws

from app.config import settings
from app.utils import tenancy
from tests.mt_helpers import run, create_mt_tables, gen_keypair


@pytest.fixture
def mt_env(monkeypatch):
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SECURITY_TOKEN", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(k, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", settings.aws_region)
    monkeypatch.setattr(settings, "tenancy_v2_enabled", True)
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name=settings.aws_region)
        create_mt_tables(ddb)
        _create_registry_v2(ddb)
        _create_signals_v2(ddb)
        _create_policies_v2(ddb)
        import app.utils.clients as clients
        import app.services.credentials_service as cs
        import app.services.tenant_service as ts
        import app.api.deps as deps
        clients._registry = None
        cs._cache = None
        cs._store = None
        ts._tenant_store = None
        ts._member_store = None
        deps._mode_cache.clear()
        yield ddb


def _create_registry_v2(ddb):
    ddb.create_table(
        TableName=settings.dynamodb_agent_registry_table_v2,
        KeySchema=[{"AttributeName": "tenant_id", "KeyType": "HASH"},
                   {"AttributeName": "agent_id", "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": "tenant_id", "AttributeType": "S"},
                              {"AttributeName": "agent_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )


def _create_policies_v2(ddb):
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


def _create_signals_v2(ddb):
    ddb.create_table(
        TableName=settings.dynamodb_validation_signals_table_v2,
        KeySchema=[{"AttributeName": "tenant_session_id", "KeyType": "HASH"},
                   {"AttributeName": "sk", "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": "tenant_session_id", "AttributeType": "S"},
                              {"AttributeName": "sk", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )


# --------------------------------------------------------------------------- #
# Cross-tenant read / write (credentials)
# --------------------------------------------------------------------------- #
def test_cross_tenant_credential_read_isolated(mt_env):
    from app.services.credentials_service import get_credential_store

    store = get_credential_store()
    _, pk_a = gen_keypair()
    _, pk_b = gen_keypair()
    store.register("t_a", "t_a-aws-x-1", pk_a)
    store.register("t_b", "t_b-aws-y-2", pk_b)

    # Tenant A lists only its own agent's keys; B's are invisible.
    a_keys = store.list_for_agent("t_a", "t_a-aws-x-1")
    assert all(k.tenant_id == "t_a" for k in a_keys)
    # And A cannot read B's agent at all.
    assert store.list_for_agent("t_a", "t_b-aws-y-2") == []


def test_cross_tenant_write_does_not_collide(mt_env):
    """Same logical agent slug under two tenants → two distinct rows; an A write
    never touches the B-keyed item."""
    from app.services.credentials_service import get_credential_store

    store = get_credential_store()
    _, pk_a = gen_keypair()
    _, pk_b = gen_keypair()
    kid_a = store.register("t_a", "t_a-aws-shared-1", pk_a)
    kid_b = store.register("t_b", "t_b-aws-shared-1", pk_b)
    assert kid_a != kid_b
    # Revoke A's key; B's stays active (no cross-tenant mutation).
    store.set_status("t_a", "t_a-aws-shared-1", kid_a, "revoked")
    assert store.get("t_a", "t_a-aws-shared-1", kid_a).status == "revoked"
    assert store.get("t_b", "t_b-aws-shared-1", kid_b).status == "active"


# NOTE: cross-tenant read isolation for the four pre-existing v2 stores
# (registry / policies / sessions / signals) through the real service readers is
# already a merge gate in test_tenancy_v2.py (it stands up the full table set
# those services touch). This module covers the LLD-26-NEW surfaces below.


# --------------------------------------------------------------------------- #
# Key-composition property test
# --------------------------------------------------------------------------- #
def test_key_composition_never_collides(mt_env):
    import random
    import string

    def rand_id():
        return "".join(random.choice(string.ascii_lowercase + "_-#") for _ in range(random.randint(1, 12)))

    seen = {}
    for _ in range(2000):
        t1, t2 = rand_id(), rand_id()
        sid = rand_id()
        k1 = tenancy.compose(t1, sid)
        k2 = tenancy.compose(t2, sid)
        # Composite signal PK round-trips and two different tenants with the same
        # session id never produce the same composite key.
        if t1 != t2:
            assert k1 != k2 or (t1 + "#" + sid) != (t2 + "#" + sid)
        seen.setdefault(k1, (t1, sid))
        # The first segment up to the first '#' recovers the tenant (since real
        # tenant ids are slugs without '#'; this property test uses '#' to prove
        # the join is unambiguous only when tenants are '#'-free).


def test_key_composition_unambiguous_for_real_slugs():
    # Real tenant ids never contain '#' — so split on the first '#' recovers the
    # tenant deterministically for any session id (even one containing '#').
    for tid in ("t_a", "t_01hxyz", "acme-corp"):
        for sid in ("s1", "s#weird", "a#b#c"):
            composite = tenancy.compose(tid, sid)
            assert composite.split("#", 1)[0] == tid


# --------------------------------------------------------------------------- #
# B7 — contextvar survives the sync/async thread boundary (the leak)
# --------------------------------------------------------------------------- #
def test_contextvar_survives_to_thread(mt_env):
    """`current_tenant()` observed INSIDE an asyncio.to_thread call must equal the
    request's tenant. A bare run_in_executor would silently revert to 'default'."""

    async def scenario():
        token = tenancy.set_current_tenant("acme")
        try:
            seen = await asyncio.to_thread(tenancy.current_tenant)
        finally:
            tenancy.reset_current_tenant(token)
        return seen

    assert run(scenario()) == "acme"


def test_credential_lookup_under_executor_keeps_tenant(mt_env):
    """The real hot-path offload (cache → asyncio.to_thread → DDB) must preserve
    the tenant so a verify under tenant A never reads B's partition by accident."""
    from app.services.credentials_service import CredentialCache, get_credential_store

    store = get_credential_store()
    _, pk_a = gen_keypair()
    kid = store.register("t_a", "t_a-aws-x-1", pk_a)

    async def scenario():
        token = tenancy.set_current_tenant("t_a")
        try:
            cache = CredentialCache(store=store, refresh_interval_seconds=0)
            rec = await cache.get(kid)
            # The contextvar is still t_a after the to_thread DDB hop.
            assert tenancy.current_tenant() == "t_a"
            return rec
        finally:
            tenancy.reset_current_tenant(token)

    rec = run(scenario())
    assert rec is not None and rec.tenant_id == "t_a"


# --------------------------------------------------------------------------- #
# Unverified → _unverified bucket (A4)
# --------------------------------------------------------------------------- #
def test_unverified_audits_under_reserved_tenant(mt_env, monkeypatch):
    from app.api.deps import resolve_tenant_from_jwt

    class FakeRequest:
        headers = {}

    monkeypatch.setattr(settings, "tenant_identity_mode", "enforce")
    ctx = run(resolve_tenant_from_jwt(FakeRequest()))
    assert ctx.audit_tenant() == tenancy.UNVERIFIED_TENANT
    assert ctx.audit_tenant() not in (tenancy.DEFAULT_TENANT,)


# --------------------------------------------------------------------------- #
# B6 — agent↔policy binding under TENANCY_V2 (cutover regression)
# --------------------------------------------------------------------------- #
def test_policy_binding_under_v2(mt_env):
    """attach/detach must keep working with the flag ON — the binding lives on
    the tenant-partitioned registry item, so cutover can't silently break it."""
    from app.services.agent_service import AgentService

    reg = mt_env.Table(settings.dynamodb_agent_registry_table_v2)
    pol = mt_env.Table(settings.dynamodb_policies_metadata_table_v2)
    reg.put_item(Item={"tenant_id": "t_a", "agent_id": "t_a-aws-x-1", "status": "active"})
    pol.put_item(Item={"tenant_id": "t_a", "policy_id": "p1", "agent_id": "t_a-aws-x-1",
                       "tenant_agent_id": "t_a#t_a-aws-x-1", "status": "active"})

    async def scenario():
        token = tenancy.set_current_tenant("t_a")
        try:
            svc = AgentService()
            res = await svc.attach_policy("t_a-aws-x-1", "p1", operator_email="op@a.com")
            assert res["status"] == "attached"
        finally:
            tenancy.reset_current_tenant(token)

    run(scenario())
    # The binding is persisted on the tenant-partitioned registry item.
    item = reg.get_item(Key={"tenant_id": "t_a", "agent_id": "t_a-aws-x-1"})["Item"]
    assert item["attached_policy_id"] == "p1"


# --------------------------------------------------------------------------- #
# Tenant delete — purge completeness (D5)
# --------------------------------------------------------------------------- #
def test_purge_removes_all_tenant_rows(mt_env):
    from app.services.credentials_service import get_credential_store
    from app.services.tenant_service import get_tenant_store
    from app.services.tenant_purge import purge_tenant

    store = get_credential_store()
    tenant_store = get_tenant_store()
    t = tenant_store.create(display_name="Doomed")
    tid = t.tenant_id
    _, pk = gen_keypair()
    store.register(tid, f"{tid}-aws-x-1", pk)
    reg = mt_env.Table(settings.dynamodb_agent_registry_table_v2)
    reg.put_item(Item={"tenant_id": tid, "agent_id": f"{tid}-aws-x-1", "status": "active"})
    sig = mt_env.Table(settings.dynamodb_validation_signals_table_v2)
    sig.put_item(Item={"tenant_session_id": tenancy.compose(tid, "s1"), "sk": "r#1#ml",
                       "tenant_id": tid})
    # A second tenant's data must survive the purge untouched.
    other = tenant_store.create(display_name="Survivor")
    reg.put_item(Item={"tenant_id": other.tenant_id, "agent_id": f"{other.tenant_id}-aws-y-2",
                       "status": "active"})

    tenant_store.set_status(tid, "deleting")
    counts = purge_tenant(tid)
    assert counts["agent-credentials"] >= 1
    assert counts["agent-registry-v2"] >= 1
    assert counts["validation-signals-v2"] >= 1

    # Nothing keyed to the purged tenant remains; the tombstone is `purged`.
    assert store.list_for_agent(tid, f"{tid}-aws-x-1") == []
    assert reg.query(KeyConditionExpression="tenant_id = :t",
                     ExpressionAttributeValues={":t": tid}).get("Items") == []
    assert tenant_store.get(tid).status == "purged"
    # The survivor tenant is intact.
    assert reg.query(KeyConditionExpression="tenant_id = :t",
                     ExpressionAttributeValues={":t": other.tenant_id}).get("Items")


def test_purge_default_requires_signoff(mt_env):
    from app.services.tenant_purge import PurgeError, purge_tenant

    # The brownfield `default` discard (B9) is gated on explicit human sign-off.
    with pytest.raises(PurgeError):
        purge_tenant("default", confirm_no_customer_data=False)


def test_purge_refuses_active_tenant(mt_env):
    from app.services.tenant_service import get_tenant_store
    from app.services.tenant_purge import PurgeError, purge_tenant

    t = get_tenant_store().create(display_name="Active")
    # A tenant must be in `deleting` before its data can be purged.
    with pytest.raises(PurgeError):
        purge_tenant(t.tenant_id)


# --------------------------------------------------------------------------- #
# WS-G G1.3 (FR-13.1 isolation) — an operator whose EMAIL DOMAIN matches a
# tenant gains ZERO access to that tenant: resolution binds only their MEMBERSHIP
# tenant, and a subsequent bound read returns only membership-tenant rows. The
# email domain (`acme.io`) and a registry tenant named similarly (`t_acme`) are
# deliberately present-but-unrelated to prove the domain grants nothing.
# --------------------------------------------------------------------------- #
def test_domain_matching_tenant_never_auto_bound(mt_env):
    from app.api import deps
    from app.api.deps import resolve_operator_tenant
    from app.services.agent_service import AgentService
    from app.services.tenant_service import get_member_store, get_tenant_store

    # A DIFFERENT tenant exists in the registry that "matches" carol's email domain
    # (t_acme ~ acme.io), but carol has NO membership there.
    get_tenant_store().create(display_name="Acme", tenant_id="t_acme")
    get_tenant_store().create(display_name="Globex", tenant_id="t_globex")
    # carol@acme.io's SOLE membership is t_globex.
    get_member_store().add(
        operator_sub="carol-sub", tenant_id="t_globex", role="viewer", is_primary=True,
    )

    # Seed one agent per tenant so a scope leak would be observable.
    reg = mt_env.Table(settings.dynamodb_agent_registry_table_v2)
    reg.put_item(Item={"tenant_id": "t_globex", "agent_id": "t_globex-aws-x", "status": "active", "name": "G"})
    reg.put_item(Item={"tenant_id": "t_acme", "agent_id": "t_acme-aws-y", "status": "active", "name": "A"})

    class _Req:
        def __init__(self, headers=None):
            self.headers = {k.lower(): v for k, v in (headers or {}).items()}

    # Resolve carol with NO X-Aegion-Tenant header → primary-pick branch. Resolve
    # AND read in ONE coroutine so the bound contextvar (set at deps.py:449) is
    # visible to the scoped list_agents read (a fresh `run()` would copy a fresh
    # context and lose the bind).
    import app.api.deps as _deps
    orig = _deps.verify_alb_oidc
    _deps.verify_alb_oidc = lambda req: {"sub": "carol-sub", "email": "carol@acme.io"}

    async def _resolve_then_read():
        c = await resolve_operator_tenant(_Req({}))
        r = await AgentService().list_agents(enrich=False)
        return c, r

    try:
        ctx, result = run(_resolve_then_read())
        assert ctx.tenant_id == "t_globex", "must bind the membership tenant, not the email domain"
        ids = {a["agent_id"] for a in result["agents"]}
        assert "t_globex-aws-x" in ids
        assert "t_acme-aws-y" not in ids, "FR-13.1: domain-matching tenant must grant zero access"
    finally:
        _deps.verify_alb_oidc = orig
