"""Shared tenancy helpers for seed/maintenance scripts (workstream T08).

Mirrors ``src/security-controller/app/utils/tenancy.py`` so seeding/query tooling
writes and reads the SAME shape the controller expects. The flag comes from the
``TENANCY_V2_ENABLED`` env var — set it to match the controller's deployment so a
re-seed never silently re-creates flat v1 rows (workstream T6/T8).

Off (default) → flat v1 shape. On → tenant-scoped v2 shape:
    tenant_id            base PK on registry / policies / sessions
    tenant_agent_id      = "{tenant}#{agent_id}"   (agent-keyed GSIs)
    tenant_decision_date = "{tenant}#{YYYY-MM-DD}" (compliance GSI)
    tenant_session_id    = "{tenant}#{session_id}" (validation-signals base PK)
"""
import os

from boto3.dynamodb.conditions import Key

DEFAULT_TENANT = "default"


def v2_enabled() -> bool:
    return os.getenv("TENANCY_V2_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


def compose(tenant: str, value: str) -> str:
    return f"{tenant}#{value}"


def table_name(v1_name: str, v2_name: str) -> str:
    return v2_name if v2_enabled() else v1_name


def item_key(attr: str, value: str, tenant: str = DEFAULT_TENANT) -> dict:
    """get_item/delete Key, flag-aware (registry/policies/sessions)."""
    if v2_enabled():
        return {"tenant_id": tenant, attr: value}
    return {attr: value}


def stamp_registry(item: dict, tenant: str = DEFAULT_TENANT) -> dict:
    if v2_enabled():
        item["tenant_id"] = tenant
    return item


def stamp_policy(item: dict, tenant: str = DEFAULT_TENANT) -> dict:
    if v2_enabled():
        item["tenant_id"] = tenant
        if item.get("agent_id") is not None:
            item["tenant_agent_id"] = compose(tenant, item["agent_id"])
    return item


def agent_index_condition(agent_id: str, tenant: str = DEFAULT_TENANT):
    """OBJECT-form (boto3 Key) condition for the agent-index GSI."""
    if v2_enabled():
        return Key("tenant_agent_id").eq(compose(tenant, agent_id))
    return Key("agent_id").eq(agent_id)


def status_index_condition(status: str, tenant: str = DEFAULT_TENANT):
    """OBJECT-form condition for the status-index GSI (tenant_id PK + status SK)."""
    if v2_enabled():
        return Key("tenant_id").eq(tenant) & Key("status").eq(status)
    return Key("status").eq(status)


def query_or_scan(table, tenant: str = DEFAULT_TENANT, **kwargs):
    """Tenant-partition Query when v2, else the original scan (registry/policies
    base tables have PK tenant_id). Keeps unscoped enumeration from leaking
    cross-tenant rows."""
    if not v2_enabled():
        return table.scan(**kwargs)
    q = dict(kwargs)
    q["KeyConditionExpression"] = Key("tenant_id").eq(tenant)
    return table.query(**q)
