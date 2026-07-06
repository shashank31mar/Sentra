"""Anti-IDOR ownership assertions for control-plane mutations (WS-M M0 / lld/39 §3.3).

``verify_alb_oidc`` + ``require_role`` prove *who* the operator is and that they
hold a sufficient role. They do **not** prove that the specific resource the
request names belongs to the operator's tenant — that is OWASP API1:2023 BOLA
(a.k.a. IDOR). :func:`assert_owns` closes that gap: after the RBAC gate, a handler
asserts the target resource is owned by ``ctx.tenant_id`` before mutating it.

Why a separate module (NOT in ``deps.py``)
------------------------------------------
``deps.py`` holds only the auth *primitives* (JWT/OIDC verify, role ladder). The
ownership dispatch needs to point-read the resource stores (policy/connection/
session), and pulling those service imports into the auth module would create an
import cycle and blur the layering. So this lives beside the routes that use it.

Fail-secure is the contract (Invariant 5, lld/39 §2.2)
------------------------------------------------------
Every path denies on mismatch **or** lookup failure — never "allow because we
couldn't check". The tenant an ownership check resolves against is ``ctx.tenant_id``
(the server-verified operator tenant), never the ambient ``tenancy.current_tenant()``
contextvar (which can be the ``"default"`` sentinel on a non-operator path).

403 vs 404 (lld/39 §3 error model)
----------------------------------
Default **403** ("not allowed"). **Except** where mere existence is sensitive —
policy / connection / session lookups by an opaque id: a cross-tenant target is
masked as **404** (a 403 would confirm the id is a live record in another tenant).
Agent ids are tenant-prefixed, so a foreign agent is an obvious **403**.
"""
from __future__ import annotations

import logging
from enum import Enum

from fastapi import HTTPException

from app.api.deps import OperatorContext
from app.utils import tenancy

logger = logging.getLogger(__name__)


class ResourceKind(str, Enum):
    """The resource families an ownership check dispatches on (lld/39 §3.3)."""

    AGENT = "agent"
    POLICY = "policy"
    CONNECTION = "connection"
    SESSION = "session"
    ACTION = "action"
    CONVERSATION = "conversation"


def assert_owns(ctx: OperatorContext, kind: ResourceKind, resource_id: str) -> None:
    """Assert ``ctx.tenant_id`` owns ``resource_id`` of the given ``kind``.

    Raises :class:`fastapi.HTTPException` (403 or 404 per the error model) on any
    mismatch, absence, or lookup failure. Returns ``None`` when ownership holds.
    """
    if kind == ResourceKind.AGENT:
        _assert_owns_agent(ctx, resource_id)
    elif kind == ResourceKind.POLICY:
        _assert_owns_policy(ctx, resource_id)
    elif kind == ResourceKind.CONNECTION:
        _assert_owns_connection(ctx, resource_id)
    elif kind in (ResourceKind.SESSION, ResourceKind.CONVERSATION):
        _assert_owns_session(ctx, resource_id)
    elif kind == ResourceKind.ACTION:
        _assert_owns_action(ctx, resource_id)
    else:  # pragma: no cover — Enum is exhaustive; defensive fail-secure.
        raise HTTPException(status_code=403, detail="unknown resource kind")


# --------------------------------------------------------------------------- #
# AGENT — delimited-prefix, no read (agent ids carry the tenant prefix)
# --------------------------------------------------------------------------- #
def _assert_owns_agent(ctx: OperatorContext, agent_id: str) -> None:
    """The operator's tenant must own ``agent_id``. Delimited prefix — never a
    bare ``startswith`` (so a short tenant id ``t_01`` can't match ``t_01hxyz-…``).
    Mismatch → 403 (agent ids are tenant-prefixed, existence is not sensitive)."""
    if not agent_id.startswith(ctx.tenant_id + "-"):
        raise HTTPException(status_code=403, detail="agent not owned by tenant")


# --------------------------------------------------------------------------- #
# POLICY — stored-attribute compare via a DIRECT tenant-scoped point-read.
# MUST NOT go through PolicyService.get_policy: that caches by a tenant-BLIND key
# (`policy:{id}`) in a process-wide singleton, so a warm cache would serve tenant
# A's row to tenant B → re-open the IDOR (lld/39 §M0 FOOTGUN). This reads the
# metadata table on the (tenant_id, policy_id) key directly.
# --------------------------------------------------------------------------- #
def _tenant_of_policy(policy_id: str, tenant_id: str):
    """Return the owning tenant of ``policy_id`` via a direct, cache-bypassing,
    tenant-scoped DynamoDB point-read, or ``None`` if no such row exists under
    ``tenant_id``. Any store error propagates (caught by the caller → deny)."""
    import boto3

    from app.config import settings

    ddb = boto3.resource("dynamodb", region_name=settings.aws_region)
    table = ddb.Table(tenancy.table_name("policies_metadata"))
    # Explicit tenant= — never the ambient contextvar. Under v2 this is an exact
    # (tenant_id, policy_id) composite-key read; a row keyed to another tenant is
    # simply absent from this partition.
    resp = table.get_item(Key=tenancy.item_key("policy_id", policy_id, tenant=tenant_id))
    item = resp.get("Item")
    if not item:
        return None
    return item.get("tenant_id")


def _assert_owns_policy(ctx: OperatorContext, policy_id: str) -> None:
    if not _tenancy_resolvable(ctx):
        raise HTTPException(status_code=404, detail="policy not found")
    try:
        owner = _tenant_of_policy(policy_id, ctx.tenant_id)
    except Exception as exc:  # noqa: BLE001 — fail secure on any store error.
        logger.warning("policy ownership lookup failed for %s: %s", policy_id, exc)
        raise HTTPException(status_code=404, detail="policy not found") from exc
    if owner is None:
        # Absent from the operator's tenant partition → existence-masked 404.
        raise HTTPException(status_code=404, detail="policy not found")
    if owner != ctx.tenant_id:
        raise HTTPException(status_code=403, detail="policy not owned by tenant")


# --------------------------------------------------------------------------- #
# CONNECTION — flag-independent structural: the connections table PK IS the
# tenant_id (connections_service._load keys on (tenant_id, id)). A tenant-scoped
# point-read that misses ⇒ 404 (existence-masked).
# --------------------------------------------------------------------------- #
def _assert_owns_connection(ctx: OperatorContext, connection_id: str) -> None:
    import boto3

    from app.config import settings

    try:
        ddb = boto3.resource("dynamodb", region_name=settings.aws_region)
        table = ddb.Table(settings.dynamodb_connections_table)
        resp = table.get_item(Key={"tenant_id": ctx.tenant_id, "id": connection_id})
    except Exception as exc:  # noqa: BLE001 — fail secure.
        logger.warning("connection ownership lookup failed for %s: %s", connection_id, exc)
        raise HTTPException(status_code=404, detail="connection not found") from exc
    if not resp.get("Item"):
        raise HTTPException(status_code=404, detail="connection not found")


# --------------------------------------------------------------------------- #
# SESSION / CONVERSATION — structural but v2-gated (effective because
# TENANCY_V2 is on). Tenant-scoped read via the session-context table keyed on
# tenancy.item_key('session_id', id, tenant=ctx.tenant_id). If the record can't
# be tenant-resolved (flag-off / stray), DENY — never fall through to a bare-key
# read that would leak another tenant's session.
# NOTE: the store is the SESSION-CONTEXT table (SessionManager), NOT the
# validation-signals store (that governs /trail; do not conflate — lld/39 §M0).
# --------------------------------------------------------------------------- #
def _assert_owns_session(ctx: OperatorContext, session_id: str) -> None:
    if not _tenancy_resolvable(ctx):
        # Flag-off / unresolvable tenant: we cannot bind the read to a tenant, so a
        # bare-key read would be cross-tenant-readable. Deny rather than fall through.
        raise HTTPException(status_code=404, detail="session not found")
    import boto3

    from app.config import settings

    try:
        ddb = boto3.resource("dynamodb", region_name=settings.aws_region)
        table = ddb.Table(tenancy.table_name("session_context"))
        resp = table.get_item(
            Key=tenancy.item_key("session_id", session_id, tenant=ctx.tenant_id)
        )
    except Exception as exc:  # noqa: BLE001 — fail secure.
        logger.warning("session ownership lookup failed for %s: %s", session_id, exc)
        raise HTTPException(status_code=404, detail="session not found") from exc
    if not resp.get("Item"):
        raise HTTPException(status_code=404, detail="session not found")


# --------------------------------------------------------------------------- #
# ACTION — the net-new Logs Insights resolution path (M2.3). The reversible-action
# audit record must carry a stamped tenant_id (audit_logger._build_log_event).
# Until the M2.3 query path lands here, this fails secure (deny) so a rollback can
# never be authorized against an unresolved action.
# --------------------------------------------------------------------------- #
def _assert_owns_action(ctx: OperatorContext, action_id: str) -> None:  # pragma: no cover
    # M2.3 wires the injection-safe Logs-Insights exact-match resolution here;
    # deferred to a later round. Fail secure until then.
    raise HTTPException(status_code=404, detail="action ownership resolution unavailable")


def _tenancy_resolvable(ctx: OperatorContext) -> bool:
    """True only when we can bind an ownership read to a concrete tenant. Requires
    TENANCY_V2 on (so ``item_key`` produces a tenant-scoped composite key) AND a
    non-empty, non-``default`` operator tenant. When false, structural-but-v2-gated
    reads (POLICY/SESSION) DENY rather than fall through to a bare-key read that
    would be cross-tenant-readable (Invariant 5 / 7, lld/39 §2.2)."""
    if not tenancy.v2_enabled():
        return False
    tid = ctx.tenant_id
    return bool(tid) and tid != tenancy.DEFAULT_TENANT


# --------------------------------------------------------------------------- #
# Back-compat alias — tenancy_routes.py had a local `_assert_owns_agent`; it is
# now re-exported from here so there is one ownership authority. Behaviour is
# byte-identical (delimited-prefix, 403 on mismatch), so repointing the existing
# 10-gate call sites is a no-op refactor (M0.1).
# --------------------------------------------------------------------------- #
def _assert_owns_agent_compat(ctx: OperatorContext, agent_id: str) -> None:
    """Thin alias: ``assert_owns(ctx, AGENT, agent_id)`` under the old name."""
    assert_owns(ctx, ResourceKind.AGENT, agent_id)
