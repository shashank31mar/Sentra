"""Staged, resumable per-tenant data erasure (LLD-26 §6.4 / WS-D D5, WS-B B9).

This is the irreversible live-store purge. It is **never** run automatically:

* Tenant deletion (D5) calls it only after the tenant is in ``status=deleting``.
* Brownfield ``default`` discard (B9) calls it only behind an explicit human
  sign-off (``confirm_no_customer_data=True``) re-confirming no real customer
  data sits under ``default`` — the "dev data" premise is a design-time
  assumption, not an execution-time fact.

Idempotent + resumable: progress is checkpointed at store granularity in the
``deletion_cursor`` map on the ``sentra-tenants`` row, and deleting an
already-deleted item is a no-op, so a killed purge simply resumes on re-run.

The audit archive (LLD-17) is intentionally **NOT** purged here — it is retained
under legal-hold and released by a separate lifecycle job (§6.4 step 4).
"""
from __future__ import annotations

import logging
from typing import Callable, Dict, List, Optional

from app.config import settings
from app.utils import tenancy
from app.utils.clients import get_clients
from app.services.credentials_service import get_credential_store
from app.services.tenant_service import get_tenant_store

logger = logging.getLogger(__name__)


class PurgeError(RuntimeError):
    pass


# (logical-store name, table-name, partition-key attr, sort-key attr, composite?)
# `composite` stores key their PK as `{tenant}#{...}` (validation-signals-v2),
# so they can't be queried by tenant — we scan-and-filter on the plain
# `tenant_id` attribute the writer stamps alongside.
_DDB_STORES = [
    ("agent-registry-v2", "dynamodb_agent_registry_table_v2", "tenant_id", "agent_id", False),
    ("policies-metadata-v2", "dynamodb_policies_metadata_table_v2", "tenant_id", "policy_id", False),
    ("session-context-v2", "dynamodb_session_table_v2", "tenant_id", "session_id", False),
    ("validation-signals-v2", "dynamodb_validation_signals_table_v2", "tenant_session_id", "sk", True),
    ("cloud-connections", "dynamodb_connections_table", "tenant_id", "id", False),
    ("discovery-cache", "dynamodb_discovery_cache_table", "tenant_id", "native_resource_id", False),
    ("agent-credentials", "dynamodb_agent_credentials_table", "tenant_id", "key_id", False),
    # identity-fallback (WS-B B1): PK is `agent_id` (self-asserted) with `tenant_id`
    # stored as a plain attribute, so it can't be queried by tenant → scan+filter
    # (composite=True) and delete by the single PK (sk=None).
    ("identity-fallback", "dynamodb_identity_fallback_table", "agent_id", None, True),
]


def purge_tenant(
    tenant_id: str,
    *,
    confirm_no_customer_data: bool = False,
    progress: Optional[Callable[[str, int], None]] = None,
) -> Dict[str, int]:
    """Erase every live-store row + S3 object keyed to ``tenant_id``.

    Refuses to run unless the tenant is in ``deleting`` (real tenants) OR it is
    the brownfield ``default`` discard with an explicit sign-off. Returns a
    per-store deleted-count map and flips the tenant row to ``purged`` on
    completion.
    """
    if tenancy.is_reserved_tenant(tenant_id) and tenant_id != tenancy.DEFAULT_TENANT:
        raise PurgeError(f"refusing to purge reserved tenant {tenant_id!r}")

    store = get_tenant_store()
    tenant = store.get(tenant_id)

    if tenant_id == tenancy.DEFAULT_TENANT:
        # Brownfield discard — the hard gate (B9). The premise must be re-confirmed.
        if not confirm_no_customer_data:
            raise PurgeError(
                "default purge requires explicit sign-off "
                "(confirm_no_customer_data=True) — see WS-B B9 / index brownfield gate"
            )
    else:
        if tenant is None:
            raise PurgeError(f"tenant {tenant_id!r} not found")
        if tenant.status not in ("deleting", "purged"):
            raise PurgeError(
                f"tenant {tenant_id!r} must be in status=deleting before purge "
                f"(is {tenant.status!r})"
            )
        # Belt-and-braces: revoke any straggler credentials first (D5 step 2).
        get_credential_store().revoke_all_for_tenant(tenant_id)

    cursor = dict(tenant.deletion_cursor) if tenant else {}
    counts: Dict[str, int] = {}

    for logical, attr_name, pk, sk, composite in _DDB_STORES:
        if cursor.get(logical) == "done":
            counts[logical] = 0
            continue
        table_name = getattr(settings, attr_name)
        deleted = _purge_ddb_store(table_name, tenant_id, pk, sk, composite)
        counts[logical] = deleted
        cursor[logical] = "done"
        if tenant is not None:
            store.set_deletion_cursor(tenant_id, cursor)
        if progress:
            progress(logical, deleted)

    # S3 policy objects under the explicit per-tenant prefix + the legacy implicit
    # `policies/agents/{tenant}-*` layout (brownfield objects live there).
    if cursor.get("s3") != "done":
        s3_deleted = _purge_s3(tenant_id)
        counts["s3"] = s3_deleted
        cursor["s3"] = "done"
        if tenant is not None:
            store.set_deletion_cursor(tenant_id, cursor)
        if progress:
            progress("s3", s3_deleted)

    if tenant is not None:
        store.mark_purged(tenant_id)
    logger.info("tenant purge complete tenant=%s counts=%s", tenant_id, counts)
    return counts


def _purge_ddb_store(table_name: str, tenant_id: str, pk: str, sk: str, composite: bool) -> int:
    from botocore.exceptions import ClientError

    table = get_clients().dynamodb_resource().Table(table_name)
    try:
        return _purge_ddb_store_inner(table, tenant_id, pk, sk, composite)
    except ClientError as exc:
        # A store that doesn't exist in this environment is simply nothing to
        # purge — don't fail the whole tenant erasure on it.
        if exc.response["Error"]["Code"] == "ResourceNotFoundException":
            logger.info("purge skip absent table %s", table_name)
            return 0
        raise


def _purge_ddb_store_inner(table, tenant_id, pk, sk, composite) -> int:
    deleted = 0
    start_key = None
    while True:
        if composite:
            # Can't query by tenant on a `{tenant}#...` PK — scan on the plain
            # `tenant_id` attribute the writer stamps. Deletion is rare, so the
            # scan cost is acceptable.
            kwargs = {
                "FilterExpression": "tenant_id = :t",
                "ExpressionAttributeValues": {":t": tenant_id},
            }
        else:
            kwargs = {
                "KeyConditionExpression": "#pk = :t",
                "ExpressionAttributeNames": {"#pk": pk},
                "ExpressionAttributeValues": {":t": tenant_id},
            }
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key
        resp = table.scan(**kwargs) if composite else table.query(**kwargs)
        items = resp.get("Items", [])
        with table.batch_writer() as batch:
            for item in items:
                key = {pk: item[pk]} if sk is None else {pk: item[pk], sk: item[sk]}
                batch.delete_item(Key=key)
                deleted += 1
        start_key = resp.get("LastEvaluatedKey")
        if not start_key:
            break
    return deleted


def _purge_s3(tenant_id: str) -> int:
    from botocore.exceptions import ClientError

    s3 = get_clients().s3()
    bucket = settings.s3_bucket
    deleted = 0
    prefixes: List[str] = [f"tenants/{tenant_id}/"]
    # Brownfield: pre-explicit-prefix objects live at policies/agents/{tenant}-*.
    prefixes.append(f"policies/agents/{tenant_id}-")
    paginator = s3.get_paginator("list_objects_v2")
    try:
        for prefix in prefixes:
            for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                objects = [{"Key": o["Key"]} for o in page.get("Contents", [])]
                if not objects:
                    continue
                for i in range(0, len(objects), 1000):
                    s3.delete_objects(Bucket=bucket, Delete={"Objects": objects[i:i + 1000]})
                deleted += len(objects)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("NoSuchBucket", "404"):
            logger.info("purge skip absent bucket %s", bucket)
            return 0
        raise
    return deleted
