"""Fleet-wide session KPIs must span ALL tenants (SOC/platform console views).

Regression guard for the tenant-scoping bug: `count_sessions_by_status`,
`query_sessions`, and `count_agents_below_trust` back the SOC console's fleet KPIs.
Routed through `tenancy.query_or_scan` they scoped to `current_tenant()` — so an
API-key console read (current_tenant()=`default`) counted 0 quarantined sessions
even though they all lived under the `acme` partition. These now use
`tenancy.fleet_scan` (a genuine cross-tenant scan).

Each test sets the caller context to `default` and puts the session under `acme`,
so it FAILS on the old per-tenant path and PASSES with the fleet-wide scan.
"""
import boto3
import pytest
from moto import mock_aws

from app.config import settings
from app.utils import tenancy


SESSION_TABLE = "sentra-session-context-v2"


@pytest.fixture
def fleet_env(monkeypatch):
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(k, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", settings.aws_region)
    monkeypatch.setattr(settings, "tenancy_v2_enabled", True)
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name=settings.aws_region)
        ddb.create_table(
            TableName=SESSION_TABLE,
            KeySchema=[
                {"AttributeName": "tenant_id", "KeyType": "HASH"},
                {"AttributeName": "session_id", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "tenant_id", "AttributeType": "S"},
                {"AttributeName": "session_id", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield ddb


def _put_session(ddb, *, tenant, session_id, quarantine_status, trust_score, agent_id):
    ddb.Table(SESSION_TABLE).put_item(Item={
        "tenant_id": tenant,
        "session_id": session_id,
        "quarantine_status": quarantine_status,
        "trust_score": trust_score,
        "agent_id": agent_id,
    })


@pytest.mark.asyncio
async def test_count_quarantined_spans_all_tenants(fleet_env):
    """A caller in the `default` context must still count a quarantined `acme`
    session — the fleet KPI is not tenant-scoped."""
    from app.utils.session_manager import SessionManager

    _put_session(fleet_env, tenant="acme", session_id="s-a1",
                 quarantine_status="quarantined", trust_score=30, agent_id="acme-payments-agent")
    _put_session(fleet_env, tenant="acme", session_id="s-a2",
                 quarantine_status="quarantined", trust_score=20, agent_id="acme-telecom-agent")
    _put_session(fleet_env, tenant="default", session_id="s-d1",
                 quarantine_status="active", trust_score=95, agent_id="demo-agent")

    token = tenancy.set_current_tenant("default")  # the API-key console context
    try:
        count = await SessionManager().count_sessions_by_status("quarantined")
    finally:
        tenancy.reset_current_tenant(token)

    # 2 acme quarantined — counted despite the caller being in `default`.
    assert count == 2


@pytest.mark.asyncio
async def test_list_quarantined_spans_all_tenants(fleet_env):
    """GET /v1/sessions?status=quarantined must LIST the acme sessions from a
    default-context console call."""
    from app.utils.session_manager import SessionManager

    _put_session(fleet_env, tenant="acme", session_id="s-a1",
                 quarantine_status="quarantined", trust_score=30, agent_id="acme-payments-agent")
    _put_session(fleet_env, tenant="default", session_id="s-d1",
                 quarantine_status="active", trust_score=95, agent_id="demo-agent")

    token = tenancy.set_current_tenant("default")
    try:
        result = await SessionManager().query_sessions(status="quarantined")
    finally:
        tenancy.reset_current_tenant(token)

    ids = {s["session_id"] for s in result["sessions"]}
    assert "s-a1" in ids          # the acme quarantined session is visible
    assert "s-d1" not in ids       # the active default session is filtered by status
    assert result["total"] == 1


@pytest.mark.asyncio
async def test_agents_below_trust_spans_all_tenants(fleet_env):
    """agents-below-trust aggregates across tenants too."""
    from app.utils.session_manager import SessionManager

    _put_session(fleet_env, tenant="acme", session_id="s-a1",
                 quarantine_status="quarantined", trust_score=20, agent_id="acme-payments-agent")
    _put_session(fleet_env, tenant="default", session_id="s-d1",
                 quarantine_status="active", trust_score=95, agent_id="demo-agent")

    token = tenancy.set_current_tenant("default")
    try:
        n = await SessionManager().count_agents_below_trust(70.0)
    finally:
        tenancy.reset_current_tenant(token)

    # only the acme agent (avg 20) is below 70; the default agent (95) is not.
    assert n == 1
