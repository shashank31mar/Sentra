#!/usr/bin/env python3
"""Re-key policy S3 objects to the explicit per-tenant layout (LLD-26 §4.3 / WS-B B3).

Moves every policy artifact from the legacy IMPLICIT layout

    policies/agents/{agent_id}/v{n}.{yaml|cedar}

to the explicit, IAM-scopable layout

    tenants/{tenant_id}/policies/agents/{agent_id}/v{n}.{yaml|cedar}

and updates the ``s3_key`` on the matching ``sentra-policies-metadata-v2`` row so
the controller's reads follow. This is a real re-key (copy + metadata update), not
just a new-write convention — existing objects don't move on their own.

Safety / sequencing (matches the controller's dual-read, s3_policy_store.get_policy_object):
* **Copy-then-update**: each object is copied to the new key, THEN the metadata
  ``s3_key`` is flipped. The controller dual-reads both layouts throughout, so the
  object is reachable at every instant of the migration (and after a flag rollback).
* **Idempotent**: a row whose ``s3_key`` already points at ``tenants/`` is skipped;
  S3 copy is overwrite. Re-running is a no-op.
* **Old objects are retained** by default (rollback-safe). Pass ``--delete-old`` only
  after you've flipped ``S3_EXPLICIT_TENANT_PREFIX=true`` on the controller and
  confirmed reads are clean — deletion is the irreversible final step.

The ``.cedar`` co-artifact (when ``policy_format=cedar``) is carried alongside its
``.yaml`` source — same key, extension swapped (policy_artifact.cedar_key_for).

Usage
-----
    python scripts/migrate_s3_policy_prefix.py --dry-run          # plan, all tenants
    python scripts/migrate_s3_policy_prefix.py --tenant acme      # one tenant
    python scripts/migrate_s3_policy_prefix.py                    # copy + re-point
    python scripts/migrate_s3_policy_prefix.py --delete-old       # then drop legacy objects
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

AWS_PROFILE = os.environ.get("AWS_PROFILE", "sentra")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
METADATA_TABLE = os.environ.get("POLICIES_METADATA_TABLE_V2", "sentra-policies-metadata-v2")

LEGACY_PREFIX = "policies/agents/"


def _cedar_key_for(yaml_key: str) -> str:
    root, ext = os.path.splitext(yaml_key)
    return root + ".cedar" if ext else yaml_key + ".cedar"


def _explicit_key(tenant_id: str, legacy_key: str) -> str:
    return f"tenants/{tenant_id}/{legacy_key}"


def _object_exists(s3, bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def _copy(s3, bucket: str, src: str, dst: str, *, dry_run: bool) -> bool:
    """Copy src→dst if src exists and dst doesn't already. Returns True if copied."""
    if not _object_exists(s3, bucket, src):
        return False
    if _object_exists(s3, bucket, dst):
        return False  # idempotent — already there
    if dry_run:
        print(f"    [dry-run] copy {src} -> {dst}")
        return True
    s3.copy_object(Bucket=bucket, CopySource={"Bucket": bucket, "Key": src}, Key=dst)
    print(f"    ✓ copied {src} -> {dst}")
    return True


def migrate(tenant_filter: Optional[str], *, dry_run: bool, delete_old: bool) -> Dict[str, int]:
    session = boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)
    ddb = session.resource("dynamodb")
    s3 = session.client("s3")
    table = ddb.Table(METADATA_TABLE)

    stats = {"rows": 0, "copied": 0, "repointed": 0, "skipped": 0, "deleted": 0, "missing": 0}

    start_key = None
    while True:
        scan_kwargs: Dict = {}
        if start_key:
            scan_kwargs["ExclusiveStartKey"] = start_key
        resp = table.scan(**scan_kwargs)
        for item in resp.get("Items", []):
            tenant_id = item.get("tenant_id")
            s3_key = item.get("s3_key")
            s3_bucket = item.get("s3_bucket")
            policy_id = item.get("policy_id")
            if not (tenant_id and s3_key and s3_bucket):
                continue
            if tenant_filter and tenant_id != tenant_filter:
                continue
            stats["rows"] += 1

            if s3_key.startswith("tenants/"):
                stats["skipped"] += 1
                continue
            if not s3_key.startswith(LEGACY_PREFIX):
                print(f"  ⚠ {policy_id}: unexpected s3_key layout {s3_key!r}; skipping")
                stats["skipped"] += 1
                continue

            new_yaml = _explicit_key(tenant_id, s3_key)
            print(f"  • {policy_id} [{tenant_id}] {s3_key} -> {new_yaml}")

            copied_yaml = _copy(s3, s3_bucket, s3_key, new_yaml, dry_run=dry_run)
            if copied_yaml:
                stats["copied"] += 1
            elif not _object_exists(s3, s3_bucket, new_yaml) and not _object_exists(s3, s3_bucket, s3_key):
                # Neither layout has the object — metadata points at nothing.
                print(f"    ⚠ source object missing for {policy_id} ({s3_key})")
                stats["missing"] += 1

            # .cedar co-artifact follows the source (when present).
            old_cedar, new_cedar = _cedar_key_for(s3_key), _cedar_key_for(new_yaml)
            if _copy(s3, s3_bucket, old_cedar, new_cedar, dry_run=dry_run):
                stats["copied"] += 1

            # Re-point metadata (copy-then-update keeps the object reachable throughout).
            if not dry_run:
                table.update_item(
                    Key={"tenant_id": tenant_id, "policy_id": policy_id},
                    UpdateExpression="SET s3_key = :k",
                    ExpressionAttributeValues={":k": new_yaml},
                )
                print(f"    ✓ re-pointed metadata s3_key -> {new_yaml}")
            else:
                print(f"    [dry-run] set metadata s3_key -> {new_yaml}")
            stats["repointed"] += 1

            if delete_old and not dry_run:
                for k in (s3_key, old_cedar):
                    if _object_exists(s3, s3_bucket, k):
                        s3.delete_object(Bucket=s3_bucket, Key=k)
                        print(f"    ✓ deleted legacy {k}")
                        stats["deleted"] += 1

        start_key = resp.get("LastEvaluatedKey")
        if not start_key:
            break

    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description="Re-key policy S3 objects to tenants/{tenant_id}/… (WS-B B3)")
    ap.add_argument("--tenant", help="Only migrate this tenant_id (default: all)")
    ap.add_argument("--dry-run", action="store_true", help="Print the plan; write nothing")
    ap.add_argument("--delete-old", action="store_true",
                    help="Delete legacy objects after re-pointing (irreversible; run only after the "
                         "controller is on S3_EXPLICIT_TENANT_PREFIX=true and reads are confirmed)")
    args = ap.parse_args()

    if args.delete_old and args.dry_run:
        print("note: --delete-old is ignored under --dry-run")

    print(f"== S3 policy-prefix migration (table={METADATA_TABLE}, tenant={args.tenant or 'ALL'}, "
          f"{'DRY-RUN' if args.dry_run else 'LIVE'}{', DELETE-OLD' if args.delete_old else ''}) ==")
    stats = migrate(args.tenant, dry_run=args.dry_run, delete_old=args.delete_old)
    print(f"\nDone: {stats}")
    if stats["missing"]:
        print("⚠ some metadata rows point at a missing object — investigate before --delete-old")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
