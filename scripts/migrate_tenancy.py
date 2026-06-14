#!/usr/bin/env python3
"""Tenancy v1 → v2 migration (Multi-Cloud Agent Import, P0a / workstream T07).

Copies every row from the four flat runtime tables into their tenant-scoped
``*-v2`` counterparts, stamping ``tenant_id = "default"`` plus the composite GSI
attributes the v2 schema queries on. Existing demo agents/policies/sessions are
grandfathered under ``tenant=default`` (workstream §1.1).

What it does NOT do
-------------------
* It does not flip ``TENANCY_V2_ENABLED`` — that is the T09 write-freeze cutover.
* It does not delete or mutate the v1 tables (they stay ``RETAIN`` for rollback).
* It does not propagate DELETES — a ``put_item`` delta re-copies new/changed rows
  but never removes a row deleted in v1 after the bulk copy. The T09 write-freeze
  keeps that window closed; T10's parity check (v2 ⊋ v1) is the backstop.

Idempotent: every row is written with ``put_item`` (overwrite), so re-running is a
no-op the second time. ``--dry-run`` prints the per-table plan without writing.
``--table`` migrates one table at a time.

Composite-key formats MUST match ``app/utils/tenancy.py`` (the runtime reader):
    tenant_agent_id      = "{tenant}#{agent_id}"
    tenant_decision_date = "{tenant}#{YYYY-MM-DD}"
    tenant_session_id    = "{tenant}#{session_id}"   (validation-signals base PK)

Usage
-----
    python scripts/migrate_tenancy.py --dry-run            # plan for all tables
    python scripts/migrate_tenancy.py --table policies     # migrate one table
    python scripts/migrate_tenancy.py                      # migrate all tables
"""
from __future__ import annotations

import argparse
import sys
from typing import Any, Callable, Dict, List

import boto3

AWS_PROFILE = "sentra"
AWS_REGION = "us-east-1"
DEFAULT_TENANT = "default"


def _compose(tenant: str, value: str) -> str:
    return f"{tenant}#{value}"


# --------------------------------------------------------------------------- #
# Per-table row transforms (v1 item -> v2 item). Each ADDS attributes; it never
# drops or recomputes existing ones (the signal store's sk / decision_date /
# timestamp_ms are preserved byte-for-byte — LLD 17 §5.2, best-practices §12).
# --------------------------------------------------------------------------- #
def _transform_registry(item: Dict[str, Any], tenant: str) -> Dict[str, Any]:
    # Base PK tenant_id, SK agent_id. No agent-keyed GSI on registry-v2.
    out = dict(item)
    out["tenant_id"] = tenant
    return out


def _transform_policies(item: Dict[str, Any], tenant: str) -> Dict[str, Any]:
    # Base PK tenant_id, SK policy_id; agent-index keys on tenant_agent_id.
    out = dict(item)
    out["tenant_id"] = tenant
    if item.get("agent_id") is not None:
        out["tenant_agent_id"] = _compose(tenant, item["agent_id"])
    return out


def _transform_sessions(item: Dict[str, Any], tenant: str) -> Dict[str, Any]:
    # Base PK tenant_id, SK session_id; agent-updated-index keys on tenant_agent_id.
    out = dict(item)
    out["tenant_id"] = tenant
    if item.get("agent_id") is not None:
        out["tenant_agent_id"] = _compose(tenant, item["agent_id"])
    return out


def _transform_signals(item: Dict[str, Any], tenant: str) -> Dict[str, Any]:
    # Composite base PK tenant_session_id (SK `sk` unchanged); GSIs key on
    # tenant_agent_id / tenant_decision_date. sk / decision_date / timestamp_ms
    # are copied verbatim — NEVER recomputed (guards SK lexical-sort drift).
    out = dict(item)
    out["tenant_id"] = tenant
    if item.get("session_id") is not None:
        out["tenant_session_id"] = _compose(tenant, item["session_id"])
    if item.get("agent_id") is not None:
        out["tenant_agent_id"] = _compose(tenant, item["agent_id"])
    if item.get("decision_date") is not None:
        out["tenant_decision_date"] = _compose(tenant, item["decision_date"])
    return out


# logical -> (v1 name, v2 name, transform)
TABLES: Dict[str, tuple] = {
    "registry": ("sentra-agent-registry", "sentra-agent-registry-v2", _transform_registry),
    "policies": ("sentra-policies-metadata", "sentra-policies-metadata-v2", _transform_policies),
    "sessions": ("sentra-session-context", "sentra-session-context-v2", _transform_sessions),
    "signals": ("sentra-validation-signals", "sentra-validation-signals-v2", _transform_signals),
}


def _scan_all(table) -> List[Dict[str, Any]]:
    """Intentionally UNSCOPED full scan — the source predates tenants and we must
    copy EVERY row. Do not 'consistency-fix' this to a tenant query (workstream T07)."""
    items: List[Dict[str, Any]] = []
    kwargs: Dict[str, Any] = {}
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek
    return items


def migrate_table(dynamodb, logical: str, tenant: str, dry_run: bool) -> Dict[str, int]:
    v1_name, v2_name, transform = TABLES[logical]
    src = dynamodb.Table(v1_name)
    rows = _scan_all(src)
    print(f"\n[{logical}] {v1_name} -> {v2_name}")
    print(f"  rows in v1: {len(rows)}")

    if dry_run:
        sample = rows[0] if rows else {}
        if sample:
            preview = transform(sample, tenant)
            added = sorted(set(preview) - set(sample))
            print(f"  would write: {len(rows)} rows under tenant={tenant!r}")
            print(f"  attrs added per row: {added}")
        else:
            print("  (table empty — nothing to migrate)")
        return {"scanned": len(rows), "written": 0}

    dst = dynamodb.Table(v2_name)
    written = 0
    with dst.batch_writer() as batch:
        for item in rows:
            batch.put_item(Item=transform(item, tenant))
            written += 1

    # Self-verify: re-count v2 so a silently-short batch surfaces HERE, not only
    # at the T10b parity check. batch_writer auto-retries UnprocessedItems and
    # raises on hard errors, but a row-count mismatch is the loud backstop.
    v2_count = _count(dst)
    ok = v2_count >= len(rows)
    flag = "✅" if ok else "❌"
    print(f"  {flag} wrote {written} rows to {v2_name} (v2 now holds {v2_count}; v1 had {len(rows)})")
    return {"scanned": len(rows), "written": written, "v2_count": v2_count, "ok": ok}


def _count(table) -> int:
    """Total item count via paginated Select=COUNT scan (idempotent re-runs make
    v2_count >= v1 count the success condition, never an exact-equality trap)."""
    total = 0
    kwargs: Dict[str, Any] = {"Select": "COUNT"}
    while True:
        resp = table.scan(**kwargs)
        total += resp.get("Count", 0)
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            return total
        kwargs["ExclusiveStartKey"] = lek


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate v1 runtime tables to tenant-scoped v2 tables.")
    parser.add_argument("--table", choices=sorted(TABLES), help="migrate a single table (default: all)")
    parser.add_argument("--tenant", default=DEFAULT_TENANT, help="tenant to stamp (default: 'default')")
    parser.add_argument("--dry-run", action="store_true", help="print the plan; write nothing")
    parser.add_argument("--profile", default=AWS_PROFILE)
    parser.add_argument("--region", default=AWS_REGION)
    args = parser.parse_args()

    print(f"Connecting to AWS (profile: {args.profile}, region: {args.region})...")
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    dynamodb = session.resource("dynamodb")

    targets = [args.table] if args.table else list(TABLES)
    mode = "DRY-RUN" if args.dry_run else "LIVE"
    print(f"Mode: {mode} | tenant={args.tenant!r} | tables={targets}")

    totals = {"scanned": 0, "written": 0}
    short_copies = []
    for logical in targets:
        try:
            r = migrate_table(dynamodb, logical, args.tenant, args.dry_run)
        except Exception as exc:  # noqa: BLE001 — surface per-table failure, keep going
            print(f"  ❌ [{logical}] failed: {exc}")
            return 1
        totals["scanned"] += r["scanned"]
        totals["written"] += r["written"]
        if not args.dry_run and not r.get("ok", True):
            short_copies.append(logical)

    print(f"\nDone. scanned={totals['scanned']} written={totals['written']} ({mode})")
    if short_copies:
        print(f"❌ short copy detected in: {short_copies} — v2 holds fewer rows than v1. "
              f"Re-run before cutover; do NOT flip TENANCY_V2_ENABLED.")
        return 1
    if not args.dry_run:
        print("Reminder: v1 tables are retained. Run T10 parity check before any v1 deletion.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
