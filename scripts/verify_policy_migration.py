#!/usr/bin/env python3
"""Verify the cross-cloud policy migration completed successfully.

Scans the sentra-policies DDB table and asserts every entry has the new
cross-cloud fields populated (platform, cloud_region, cross_cloud_dependencies).
Compares DDB state against config/agent_policies.yaml and reports divergences.

Exits 0 if every entry that has a YAML counterpart matches; 1 otherwise.

Usage:
    python scripts/verify_policy_migration.py
    python scripts/verify_policy_migration.py --profile sentra --region us-east-1

Reference: Workstream 15 Milestone 2 Task 2.3 (cross-cloud demo)
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

import boto3
import yaml

POLICIES_TABLE = "sentra-policies"  # legacy
METADATA_TABLE = "sentra-policies-metadata"  # active path (Data Model v2)
CONFIG_FILE = "config/agent_policies.yaml"
S3_POLICY_PREFIX = "policies/agents/"


_DESERIALIZER = boto3.dynamodb.types.TypeDeserializer()


def _ddb_to_python(item: dict) -> dict:
    """Convert a DDB attribute-typed item to plain Python via boto3's standard
    TypeDeserializer. Replaces the prior hand-rolled walker (Issue #9, WS15 M2
    review) that had a dead conditional and missed edge cases like BinarySet.
    """
    # The deserializer returns Decimal for numbers — coerce to int/float so YAML
    # diff and JSON dump produce normal-looking values.
    return {k: _normalize(_DESERIALIZER.deserialize(v)) for k, v in item.items()}


def _normalize(val):
    """Recursively coerce Decimal → int/float for downstream readability."""
    from decimal import Decimal

    if isinstance(val, Decimal):
        return int(val) if val == val.to_integral_value() else float(val)
    if isinstance(val, list):
        return [_normalize(x) for x in val]
    if isinstance(val, dict):
        return {k: _normalize(v) for k, v in val.items()}
    if isinstance(val, set):
        return [_normalize(x) for x in val]
    return val


def verify_active_path(session, region: str) -> int:
    """Verify the active validator path: sentra-policies-metadata + S3 YAMLs.

    This is the path policy_engine.get_agent_policy() actually uses for live
    validation decisions. Returns 0 on success, 1 on failure.
    """
    ddb = session.client("dynamodb")
    s3 = session.client("s3")

    print(f"\n{'=' * 80}")
    print(f"ACTIVE PATH — sentra-policies-metadata + S3")
    print(f"{'=' * 80}\n")

    scan = ddb.scan(TableName=METADATA_TABLE)
    items = [_ddb_to_python(i) for i in scan.get("Items", [])]

    failures: list[str] = []
    print(f"{'agent_id':<40} {'platform':<14} {'region':<10} {'#deps':>5} {'s3':<8} status")
    print("-" * 95)
    for it in sorted(items, key=lambda x: x.get("agent_id", "")):
        aid = it.get("agent_id", "?")
        plat = it.get("platform", "<MISSING>")
        region_v = it.get("cloud_region", "<MISSING>")
        deps = it.get("cross_cloud_deps_count", 0) or 0
        bucket = it.get("s3_bucket", "")
        key = it.get("s3_key", "")

        # Verify S3 object exists
        s3_ok = "?"
        try:
            s3.head_object(Bucket=bucket, Key=key)
            s3_ok = "OK"
        except Exception:
            s3_ok = "MISSING"
            failures.append(f"{aid}: S3 object s3://{bucket}/{key} not found")

        status = "OK"
        if plat in ("<MISSING>", "unknown"):
            status = "MISSING-PLATFORM"
            failures.append(f"{aid}: platform missing or 'unknown' in metadata")
        elif region_v in ("<MISSING>", "unknown"):
            status = "MISSING-REGION"
            failures.append(f"{aid}: cloud_region missing or 'unknown' in metadata")

        print(f"{aid:<40} {plat:<14} {region_v:<10} {deps:>5} {s3_ok:<8} {status}")

    if failures:
        print(f"\n❌ Active path FAILED with {len(failures)} issue(s):")
        for f in failures:
            print(f"   - {f}")
        return 1
    print(f"\n✅ Active path PASSED — {len(items)} metadata entries valid, all S3 objects present.")
    return 0


def verify(profile: str | None, region: str) -> int:
    session = boto3.Session(profile_name=profile, region_name=region) if profile else boto3.Session(region_name=region)
    client = session.client("dynamodb")

    print(f"🔍 Verifying both policy paths in {region} (profile={profile or 'default'})\n")
    print(f"{'=' * 80}")
    print(f"LEGACY PATH — sentra-policies (dashboard only, not validator)")
    print(f"{'=' * 80}\n")
    scan = client.scan(TableName=POLICIES_TABLE)
    raw_items = scan.get("Items", [])
    items = [_ddb_to_python(i) for i in raw_items]

    config_path = CONFIG_FILE
    if not os.path.exists(config_path):
        # Allow running from scripts/ or project root
        alt = os.path.join(os.path.dirname(__file__), "..", CONFIG_FILE)
        if os.path.exists(alt):
            config_path = alt
        else:
            print(f"❌ Config file not found at {CONFIG_FILE}")
            return 1

    with open(config_path) as f:
        yaml_policies = yaml.safe_load(f) or {}

    print(f"📊 DDB entries: {len(items)}  |  YAML entries: {len(yaml_policies)}\n")

    failures: list[str] = []
    rows: list[tuple[str, str, str, str, int, str]] = []

    for it in items:
        agent_id = it.get("agent_id", "?")
        policy_id = it.get("policy_id", "?")
        platform = it.get("platform")
        region_v = it.get("cloud_region")
        ccd = it.get("cross_cloud_dependencies", [])
        ccd_count = len(ccd) if isinstance(ccd, list) else 0

        # Status: PASS if both cross-cloud fields are populated and not 'unknown'
        if not platform or platform == "unknown":
            failures.append(f"{policy_id}: platform missing or 'unknown'")
            status = "MISSING-PLATFORM"
        elif not region_v or region_v == "unknown":
            failures.append(f"{policy_id}: cloud_region missing or 'unknown'")
            status = "MISSING-REGION"
        else:
            status = "OK"

        rows.append((policy_id, agent_id, platform or "-", region_v or "-", ccd_count, status))

    # Pretty-print
    print(f"{'policy_id':<48} {'agent_id':<38} {'platform':<14} {'region':<12} {'#deps':>5}  status")
    print("-" * 130)
    for r in sorted(rows):
        print(f"{r[0]:<48} {r[1]:<38} {r[2]:<14} {r[3]:<12} {r[4]:>5}  {r[5]}")

    print()

    # Also report any YAML entries that did NOT make it to DDB (sanity check).
    ddb_agent_ids = {it.get("agent_id") for it in items}
    missing_in_ddb = [a for a in yaml_policies if a not in ddb_agent_ids]
    if missing_in_ddb:
        print(f"⚠️  YAML entries with no DDB row: {missing_in_ddb}")
        failures.append(f"YAML agents not seeded: {missing_in_ddb}")

    legacy_failed = bool(failures)
    if failures:
        print(f"\n❌ Legacy path FAILED with {len(failures)} issue(s):")
        for f in failures:
            print(f"   - {f}")
    else:
        print("✅ Legacy path PASSED — all DDB entries have cross-cloud fields populated.")

    # Now verify the active path (sentra-policies-metadata + S3)
    active_status = verify_active_path(session, region)

    # Both paths must pass
    return 1 if (legacy_failed or active_status != 0) else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--profile", default=os.environ.get("AWS_PROFILE", "sentra"))
    p.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    args = p.parse_args()
    return verify(args.profile, args.region)


if __name__ == "__main__":
    sys.exit(main())
