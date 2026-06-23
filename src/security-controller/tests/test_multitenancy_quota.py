"""Quota enforcement + platform-admin gating (LLD-26 WS-E E2/E3)."""
from __future__ import annotations

import boto3
import pytest
from fastapi import HTTPException
from moto import mock_aws

from app.config import settings
from tests.mt_helpers import create_mt_tables, run


@pytest.fixture
def mt_env(monkeypatch):
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SECURITY_TOKEN", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(k, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", settings.aws_region)
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name=settings.aws_region)
        create_mt_tables(ddb)
        _create_quota_table(ddb)
        import app.utils.clients as clients
        import app.services.tenant_service as ts
        import app.services.quota_service as qs
        clients._registry = None
        ts._tenant_store = None
        ts._member_store = None
        qs._counter = None
        yield ddb


def _create_quota_table(ddb):
    ddb.create_table(
        TableName=settings.dynamodb_quota_counters_table,
        KeySchema=[{"AttributeName": "tenant_id", "KeyType": "HASH"},
                   {"AttributeName": "counter_key", "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": "tenant_id", "AttributeType": "S"},
                              {"AttributeName": "counter_key", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )


# --------------------------------------------------------------------------- #
# E2a — max_agents at import
# --------------------------------------------------------------------------- #
def test_max_agents_enforced(mt_env):
    from app.services.quota_service import QuotaExceeded, check_agent_quota
    from app.services.tenant_service import get_tenant_store

    get_tenant_store().create(display_name="Capped", tenant_id="t_cap",
                              quota={"max_agents": 3, "max_validate_rps": 50})
    # Under cap: fine.
    check_agent_quota(current_count=2, adding=1, tenant_id="t_cap")
    # Over cap: rejected.
    with pytest.raises(QuotaExceeded) as exc:
        check_agent_quota(current_count=3, adding=1, tenant_id="t_cap")
    assert exc.value.kind == "max_agents" and exc.value.limit == 3


def test_max_agents_noop_without_tenant_row(mt_env):
    from app.services.quota_service import check_agent_quota

    # No registry row (e.g. `default` pre-identity) → no quota applies (no regression).
    check_agent_quota(current_count=9999, adding=1, tenant_id="default")


# --------------------------------------------------------------------------- #
# E2b — RPS counter: off by default, fail-open
# --------------------------------------------------------------------------- #
def test_rps_disabled_by_default(mt_env, monkeypatch):
    from app.services.quota_service import check_validate_rps

    monkeypatch.setattr(settings, "quota_enforcement_enabled", False)
    # Flag off → always allow, zero hot-path cost.
    assert check_validate_rps("t_cap") is True


def test_rps_counter_allows_under_limit_and_blocks_over(mt_env, monkeypatch):
    from app.services.quota_service import get_quota_counter

    counter = get_quota_counter()
    # Two hits under a limit of 5 → allowed.
    assert counter.allow("t_cap", max_rps=5) is True
    assert counter.allow("t_cap", max_rps=5) is True
    # Exhaust the window: many hits over a limit of 1 → eventually blocks.
    blocked = any(not counter.allow("t_burst", max_rps=1) for _ in range(5))
    assert blocked


def test_rps_fails_open_on_counter_error(monkeypatch):
    # No moto table at all → counter writes raise → fail OPEN (allow).
    import app.services.quota_service as qs
    qs._counter = None
    monkeypatch.setenv("AWS_DEFAULT_REGION", settings.aws_region)
    with mock_aws():
        import app.utils.clients as clients
        clients._registry = None
        # Table intentionally absent → ClientError → allow.
        assert qs.get_quota_counter().allow("t_x", max_rps=1) is True


# --------------------------------------------------------------------------- #
# E3 — platform gating
# --------------------------------------------------------------------------- #
def test_require_platform_blocks_non_platform(mt_env):
    import app.api.deps as deps

    async def scenario():
        deps._alb_claims_override = lambda req: {"sub": "op_cust", "email": "c@acme.io"}
        from app.services.tenant_service import get_member_store
        get_member_store().add("op_cust", "t_cap", role="owner", is_primary=True)

        class Req:
            headers = {}
        # A normal tenant operator (no _platform membership) → 403.
        with pytest.raises(HTTPException) as exc:
            await deps.require_platform(Req())
        assert exc.value.status_code == 403
        deps._alb_claims_override = None

    run(scenario())


def test_require_platform_allows_platform_member(mt_env):
    import app.api.deps as deps
    from app.utils import tenancy

    async def scenario():
        deps._alb_claims_override = lambda req: {"sub": "op_staff", "email": "s@sentra.io"}
        from app.services.tenant_service import get_member_store
        members = get_member_store()
        members.add("op_staff", tenancy.PLATFORM_TENANT, role="admin", is_primary=False)
        members.add("op_staff", "t_cap", role="admin", is_primary=True)

        class Req:
            headers = {}
        ctx = await deps.require_platform(Req())
        assert ctx.is_platform is True
        deps._alb_claims_override = None

    run(scenario())
