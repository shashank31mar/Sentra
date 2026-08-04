"""Tenancy switchboard — the single place the ``TENANCY_V2_ENABLED`` cutover lives.

Multi-Cloud Agent Import, P0a (workstream §1, feature §14.2).

Why this module exists
----------------------
The migration flips four runtime tables from a flat key to a tenant-scoped key.
Doing that inline at every call site would scatter ``if v2`` branches across six
services and make a flag-rollback un-reviewable. Instead every flag-conditional
lives here, behind small builders. Call sites read like:

    table = ddb.Table(tenancy.table_name("agent_registry"))
    item = table.get_item(Key=tenancy.item_key("agent_id", agent_id)).get("Item")

The contract that makes rollback safe:

* **Flag OFF** → every builder returns the *v1* shape (no ``tenant_id``, bare
  GSI keys, plain ``scan``). Behaviour is byte-identical to pre-migration code.
* **Flag ON** → builders return the *v2* shape (``tenant_id`` partition key,
  composite GSI keys, tenant-scoped ``query``).

Key design (workstream §1.1, with one correction)
--------------------------------------------------
* ``agent-registry`` / ``policies-metadata`` / ``session-context`` v2:
  base PK ``tenant_id``, SK = the old PK attribute. A tenant ``Query`` is the
  natural isolation boundary; ``get_item`` is an exact ``(tenant_id, id)`` lookup.
* ``validation-signals`` v2: base PK is the **composite** ``tenant_session_id``
  (``{tenant}#{session_id}``), SK = ``sk`` (unchanged). ``sk`` already occupies
  the sort key, so ``session_id`` cannot be the SK — folding it into the PK keeps
  the hot ``Query(PK, sk begins_with <rid>)`` pattern and avoids a tenant-wide
  hot partition. (Resolves the §1.3-vs-§0.1 contradiction in the workstream.)
* Agent-keyed GSIs (``agent-index``, ``agent-updated-index``,
  ``agent-timestamp-index``) key off a dedicated composite attribute
  ``tenant_agent_id`` = ``{tenant}#{agent_id}`` so the plain ``agent_id`` is never
  clobbered. The compliance GSI keys off ``tenant_decision_date``.
* ``status-index`` reuses the base PK ``tenant_id`` + SK ``status`` (no new attr).

Tenant resolution
-----------------
P0a: :func:`current_tenant` always returns ``"default"`` (all migrated rows live
under that tenant). P1 (feature §14) sets it from the verified JWT ``tid`` claim
via :func:`set_current_tenant`; everything below then becomes per-tenant with no
further changes here.
"""
from __future__ import annotations

import contextvars
from typing import Any, Optional, Tuple

from boto3.dynamodb.conditions import Key

from app.config import settings

# Reserved tenant every grandfathered/demo row migrates under (workstream §1.1).
DEFAULT_TENANT = "default"

# Reserved system tenants (LLD-26 §3.7, §6.2). None of these may be minted as a
# customer tenant_id — tenant creation rejects them (WS-D D4).
#   _unverified — audit bucket for requests with no proven tenant (WS-A A4).
#   _platform   — Sentra-staff cross-tenant support capability (WS-D §6.3).
UNVERIFIED_TENANT = "_unverified"
PLATFORM_TENANT = "_platform"
# `_revocation` is the PK of the revoked-since epoch row in the credentials table
# (credentials_service). Reserve it too so a tenant can never collide with it
# (already unreachable via the slug rules, but defense-in-depth).
REVOCATION_PSEUDO_TENANT = "_revocation"
# `_benchmark` is the tenant the security-efficacy benchmark harness binds for the
# whole of a run (LLD 41 §4.7 I5 / FR-14.9). Reserving it is what makes every row
# the rig can cause separable by partition key — `compose()` prefixes it, so a row
# that leaks past the null objects is identifiable after the fact and deletable as
# a unit, and no customer can ever mint the id and collide with it.
BENCHMARK_PSEUDO_TENANT = "_benchmark"
RESERVED_TENANT_IDS = frozenset(
    {DEFAULT_TENANT, UNVERIFIED_TENANT, PLATFORM_TENANT, REVOCATION_PSEUDO_TENANT,
     BENCHMARK_PSEUDO_TENANT}
)

# Runtime-identity rollout ladder (LLD-26 §7.2). Ordered so `min()` over the
# index gives the more-conservative of two modes.
IDENTITY_MODES = ("off", "shadow", "enforce")


def effective_identity_mode(tenant_mode: Optional[str]) -> str:
    """The mode actually in force for a tenant = the *more conservative* of the
    fleet-wide env ceiling (``TENANT_IDENTITY_MODE``) and the tenant row's
    ``identity_mode`` (LLD-26 §7.2). A tenant can never rise above the ceiling;
    the ceiling can cap every tenant at ``shadow`` (incident) or ``off`` (kill).
    Unknown values fail closed to ``off``."""
    ceiling = (settings.tenant_identity_mode or "off").lower()
    tenant = (tenant_mode or "off").lower()
    ci = IDENTITY_MODES.index(ceiling) if ceiling in IDENTITY_MODES else 0
    ti = IDENTITY_MODES.index(tenant) if tenant in IDENTITY_MODES else 0
    return IDENTITY_MODES[min(ci, ti)]


def effective_local_floor_enabled(tenant_override: Optional[bool]) -> bool:
    """Whether the deterministic local floor is active for a tenant (WS-I I5.3 /
    LLD 28 §5.6). The floor evaluates locally ONLY when the fleet flag AND the
    tenant override both permit it — either set to False routes that tenant to the
    hosted ``/v1/validate`` path (the incident escape hatch). ``tenant_override``
    None means "inherit the fleet flag". This is a kill-switch over the EVAL
    LOCATION, never over enforcement (ADR-034): off ⇒ validate on the server, it
    must NEVER be read as "skip validation"."""
    fleet = bool(getattr(settings, "local_floor_enabled", True))
    if tenant_override is None:
        return fleet
    return fleet and bool(tenant_override)


def is_reserved_tenant(tenant_id: str) -> bool:
    """True if ``tenant_id`` is a reserved system id that no customer may hold."""
    return tenant_id in RESERVED_TENANT_IDS

# Composite GSI / base partition attribute names (v2 only).
AGENT_GSI_PK = "tenant_agent_id"          # {tenant}#{agent_id}
DECISION_DATE_GSI_PK = "tenant_decision_date"  # {tenant}#{YYYY-MM-DD}
SIGNAL_BASE_PK = "tenant_session_id"      # {tenant}#{session_id}

_current_tenant: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_tenant", default=DEFAULT_TENANT
)

# Logical name → settings attribute, per flag state.
_V1_TABLE_ATTR = {
    "agent_registry": "dynamodb_agent_registry_table",
    "policies_metadata": "dynamodb_policies_metadata_table",
    "session_context": "dynamodb_session_table",
    "validation_signals": "dynamodb_validation_signals_table",
}
_V2_TABLE_ATTR = {
    "agent_registry": "dynamodb_agent_registry_table_v2",
    "policies_metadata": "dynamodb_policies_metadata_table_v2",
    "session_context": "dynamodb_session_table_v2",
    "validation_signals": "dynamodb_validation_signals_table_v2",
}


# --------------------------------------------------------------------------- #
# Flag + tenant context
# --------------------------------------------------------------------------- #
def v2_enabled() -> bool:
    """Read the cutover flag LIVE — never latch it at ``__init__`` (workstream
    T7: a rolling deploy runs old+new tasks together, and tests flip it)."""
    return bool(settings.tenancy_v2_enabled)


def current_tenant() -> str:
    """The tenant for the current request. P0a: always ``"default"``."""
    return _current_tenant.get()


def set_current_tenant(tenant: Optional[str]) -> contextvars.Token:
    """Bind the request tenant (P1: from the verified JWT ``tid``). Returns a
    token for :func:`reset_current_tenant`."""
    return _current_tenant.set(tenant or DEFAULT_TENANT)


def reset_current_tenant(token: contextvars.Token) -> None:
    _current_tenant.reset(token)


def compose(tenant: str, value: str) -> str:
    """The canonical composite-key join used by every v2 GSI key."""
    return f"{tenant}#{value}"


# --------------------------------------------------------------------------- #
# S3 policy-object layout (LLD-26 §4.3 / WS-B B3)
# --------------------------------------------------------------------------- #
# Legacy (implicit): policies/agents/{agent_id}/v{n}.{ext} — isolation holds
#   ONLY because the canonical agent_id carries the tenant prefix.
# Explicit per-tenant: tenants/{tenant_id}/policies/agents/{agent_id}/v{n}.{ext}
#   — moves isolation from implicit to explicit and makes the future IAM
#   session-tag scoping (s3:prefix = tenants/${tenant_id}/*) a config change,
#   not a re-key. Gated on `s3_explicit_tenant_prefix` AND v2 (tenant must be
#   real). Reads dual-read across both layouts (see policy_s3_read_candidates).
_POLICY_LEAF_PREFIX = "policies/agents"


def _explicit_policy_prefix_enabled() -> bool:
    """Explicit prefixing only means something once tenancy is on — under v1 the
    only tenant is the implicit one, so there is no real tenant_id to key by."""
    return v2_enabled() and bool(settings.s3_explicit_tenant_prefix)


def _tenant_s3_prefix(tenant: str) -> str:
    return f"tenants/{tenant}/"


def policy_s3_object_key(agent_id: str, version: str, *, ext: str = "yaml",
                         tenant: Optional[str] = None) -> str:
    """Compose the S3 object key for a policy artifact (the structured ``.yaml``
    source or, with ``ext='cedar'``, its co-artifact). Explicit per-tenant layout
    when enabled, else the legacy implicit layout (byte-identical to today)."""
    leaf = f"{_POLICY_LEAF_PREFIX}/{agent_id}/v{version}.{ext}"
    if _explicit_policy_prefix_enabled():
        return _tenant_s3_prefix(tenant or current_tenant()) + leaf
    return leaf


def policy_s3_read_candidates(stored_key: str, *, tenant: Optional[str] = None) -> list:
    """Ordered keys to try when reading a policy object during the B3 migration
    window. The metadata ``s3_key`` is authoritative, so it is tried first; the
    alternate-prefix variant is the fallback so a read succeeds whether the object
    has been re-keyed yet or not (and after a flag rollback). Order preserved, no
    duplicates."""
    t = tenant or current_tenant()
    candidates = [stored_key]
    explicit = _tenant_s3_prefix(t)
    if stored_key.startswith(explicit):
        candidates.append(stored_key[len(explicit):])           # explicit → legacy
    elif stored_key.startswith(_POLICY_LEAF_PREFIX + "/"):
        candidates.append(explicit + stored_key)                # legacy → explicit
    # de-dup while preserving order
    seen, out = set(), []
    for k in candidates:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


# --------------------------------------------------------------------------- #
# Table-name resolution
# --------------------------------------------------------------------------- #
def table_name(logical: str) -> str:
    """Resolve a logical table name to its physical v1/v2 name (flag-aware)."""
    mapping = _V2_TABLE_ATTR if v2_enabled() else _V1_TABLE_ATTR
    try:
        return getattr(settings, mapping[logical])
    except KeyError:
        raise ValueError(f"unknown logical table {logical!r}")


# --------------------------------------------------------------------------- #
# Base-table keys (boto3 resource API)
# --------------------------------------------------------------------------- #
def item_key(entity_attr: str, entity_id: str, tenant: Optional[str] = None) -> dict:
    """``Key=`` for get_item / update_item / delete_item on registry / policies /
    session tables. v2 → ``{tenant_id, entity_attr}``; v1 → ``{entity_attr}``."""
    if v2_enabled():
        return {"tenant_id": tenant or current_tenant(), entity_attr: entity_id}
    return {entity_attr: entity_id}


def signal_item_key(session_id: str, sk: str, tenant: Optional[str] = None) -> dict:
    """``Key=`` for the validation-signals base table (resource API).
    v2 → ``{tenant_session_id, sk}``; v1 → ``{session_id, sk}``."""
    if v2_enabled():
        return {SIGNAL_BASE_PK: compose(tenant or current_tenant(), session_id), "sk": sk}
    return {"session_id": session_id, "sk": sk}


# --------------------------------------------------------------------------- #
# put_item stamping — add v2 attributes to an item before writing (no-op on v1)
# --------------------------------------------------------------------------- #
def stamp_base_item(item: dict, tenant: Optional[str] = None) -> dict:
    """Set the ``tenant_id`` base PK on a registry / policy / session item.
    Mutates and returns ``item``. No-op when the flag is off."""
    if v2_enabled():
        item["tenant_id"] = tenant or current_tenant()
    return item


def stamp_agent_gsi(item: dict, agent_attr: str = "agent_id", tenant: Optional[str] = None) -> dict:
    """Set the composite ``tenant_agent_id`` GSI attr from ``item[agent_attr]``.
    Used by policy + session items (their agent-keyed GSIs). No-op on v1 or when
    the source attribute is absent."""
    if v2_enabled():
        aid = item.get(agent_attr)
        if aid is not None:
            item[AGENT_GSI_PK] = compose(tenant or current_tenant(), aid)
    return item


# --------------------------------------------------------------------------- #
# GSI query builders
# --------------------------------------------------------------------------- #
def agent_index_kce_value(agent_id: str, placeholder: str = ":agent_id",
                          tenant: Optional[str] = None) -> Tuple[str, str]:
    """For STRING-form agent-index queries (``policy_engine``, ``policy_service``,
    ``agent_service``). Returns ``(key_condition_expression, value)`` — the value
    goes under ``placeholder`` in ExpressionAttributeValues.

    v2 → (``"tenant_agent_id = :agent_id"``, ``"{tenant}#{agent_id}"``)
    v1 → (``"agent_id = :agent_id"``, ``agent_id``)
    """
    if v2_enabled():
        return f"{AGENT_GSI_PK} = {placeholder}", compose(tenant or current_tenant(), agent_id)
    return f"agent_id = {placeholder}", agent_id


def agent_index_key_condition(agent_id: str, tenant: Optional[str] = None):
    """OBJECT-form (boto3 ``Key``) agent-index / agent-updated-index condition
    (``session_manager.get_agent_session_stats``)."""
    if v2_enabled():
        return Key(AGENT_GSI_PK).eq(compose(tenant or current_tenant(), agent_id))
    return Key("agent_id").eq(agent_id)


def status_index_query(status_value: str, tenant: Optional[str] = None) -> Tuple[str, dict, dict]:
    """status-index GSI query parts, flag-aware (``policy_service.list_policies``).
    Returns ``(KeyConditionExpression, ExpressionAttributeNames, ExpressionAttributeValues)``.

    v2 keys on the base PK ``tenant_id`` + SK ``status``; v1 on ``status`` alone.
    """
    if v2_enabled():
        return (
            "tenant_id = :__t AND #status = :status",
            {"#status": "status"},
            {":__t": tenant or current_tenant(), ":status": status_value},
        )
    return ("#status = :status", {"#status": "status"}, {":status": status_value})


# --------------------------------------------------------------------------- #
# scan() → tenant-scoped Query (boto3 resource API) — closes the isolation leak
# --------------------------------------------------------------------------- #
def query_or_scan(table, **scan_kwargs):
    """Run a tenant-partition ``Query`` when v2 is on, else the original ``scan``.

    Folds the caller's existing ``FilterExpression`` / ``ProjectionExpression`` /
    ``Limit`` / ``ExclusiveStartKey`` / ``Select`` through unchanged. Handles both
    expression forms used in the codebase:

    * STRING ``FilterExpression`` (with manual ExpressionAttributeValues) → uses a
      string ``KeyConditionExpression`` and merges ``:__t`` into the values, so we
      never mix a condition object with manually-supplied values (boto3 forbids).
    * OBJECT ``FilterExpression`` (``Attr(...)``) or none → uses a ``Key`` object
      condition; boto3 builds and merges the placeholders.
    """
    if not v2_enabled():
        return table.scan(**scan_kwargs)

    q = dict(scan_kwargs)
    fe = q.get("FilterExpression")
    if isinstance(fe, str):
        eav = dict(q.get("ExpressionAttributeValues") or {})
        eav[":__t"] = current_tenant()
        q["ExpressionAttributeValues"] = eav
        q["KeyConditionExpression"] = "tenant_id = :__t"
    else:
        q["KeyConditionExpression"] = Key("tenant_id").eq(current_tenant())
    return table.query(**q)


# --------------------------------------------------------------------------- #
# fleet_scan — a DELIBERATELY cross-tenant scan for platform / SOC fleet views
# --------------------------------------------------------------------------- #
def fleet_scan(table, **scan_kwargs):
    """A genuine cross-tenant ``table.scan`` for **fleet-wide platform/SOC KPIs**
    — the opposite of :func:`query_or_scan`.

    ``query_or_scan`` scopes every read to ``current_tenant()`` (the tenant-
    isolation guarantee for per-tenant data). But a handful of reads are *platform*
    views that must span EVERY tenant: the SOC console's fleet quarantine count +
    session list + agents-below-trust. Routed through ``query_or_scan`` those
    silently see only the caller's partition (``default`` for an API-key console
    read) and miss every other tenant's sessions.

    This helper runs a plain ``scan`` (no ``KeyConditionExpression``) so it reads
    ALL tenant partitions, folding the caller's ``FilterExpression`` /
    ``ProjectionExpression`` / ``Limit`` / ``ExclusiveStartKey`` / ``Select``
    through unchanged. Byte-identical to the pre-v2 behaviour.

    USE ONLY for platform/SOC aggregates that are meant to be fleet-wide. NEVER use
    it for per-tenant data reads — that would leak one tenant's rows to another.
    (Auth-hardening — scoping the console to an operator's tenants — is a separate
    follow-up; today the console is a single-operator platform view.)
    """
    return table.scan(**scan_kwargs)


# --------------------------------------------------------------------------- #
# Low-level client helpers (decisions_service / signal_store_writer)
# --------------------------------------------------------------------------- #
def signal_pk_attr() -> str:
    """Base partition-key attribute name for the validation-signals table."""
    return SIGNAL_BASE_PK if v2_enabled() else "session_id"


def signal_pk_value(session_id: str, tenant: Optional[str] = None) -> str:
    """Base partition-key VALUE for a signal row (composite when v2)."""
    if v2_enabled():
        return compose(tenant or current_tenant(), session_id)
    return session_id


def decision_date_gsi_attr() -> str:
    return DECISION_DATE_GSI_PK if v2_enabled() else "decision_date"


def decision_date_gsi_value(decision_date: str, tenant: Optional[str] = None) -> str:
    if v2_enabled():
        return compose(tenant or current_tenant(), decision_date)
    return decision_date


def stamp_signal_item(item: dict, tenant: Optional[str] = None) -> dict:
    """Add v2 tenant attributes to a signal item (plain python dict, pre-serialize).

    Sets the composite base PK ``tenant_session_id`` (from ``item['session_id']``),
    the agent GSI key ``tenant_agent_id`` (from ``item['agent_id']`` when present),
    and the compliance GSI key ``tenant_decision_date`` (from
    ``item['decision_date']``). Also stores a plain ``tenant_id`` for observability.
    No-op when the flag is off (SK / decision_date / timestamp untouched in both
    modes — LLD 17 §5.2 contract). Mutates and returns ``item``.
    """
    if not v2_enabled():
        return item
    t = tenant or current_tenant()
    item["tenant_id"] = t
    sid = item.get("session_id")
    if sid is not None:
        item[SIGNAL_BASE_PK] = compose(t, sid)
    aid = item.get("agent_id")
    if aid is not None:
        item[AGENT_GSI_PK] = compose(t, aid)
    dd = item.get("decision_date")
    if dd is not None:
        item[DECISION_DATE_GSI_PK] = compose(t, dd)
    return item
