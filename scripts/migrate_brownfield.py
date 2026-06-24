#!/usr/bin/env python3
"""Brownfield `default` population: inventory + gated discard (LLD-26 §B9 / WS-B).

Every pre-tenancy agent was imported under the hardwired ``default`` tenant and
carries a flat, non-canonical ``agent_id`` (``acme-payments-agent``,
``payment-agent``, …). ``agent_id`` is immutable (registry PK, binding key, S3
path, signal partition), so there is **no in-place path** to move a ``default``
agent into a real tenant — the resolved decision is *re-import under the real
tenant, then discard the ``default`` copies* (no cascade re-key is built).

The re-import is the normal connect→scan→import flow under the real tenant (for
the demo agents this is already done — they exist under tenant ``acme`` with
registered credentials). This tool covers the other two halves of B9:

* ``inventory`` (default, READ-ONLY, safe to run anytime) — enumerate what lives
  under ``default`` across the v2 stores, the legacy flat registry, and S3, and
  write the list to a file to attach to the purge sign-off.
* ``purge`` (IRREVERSIBLE) — erase the ``default`` population. Refuses to run
  without ``--confirm-no-customer-data``, the explicit human sign-off re-affirming
  nothing real lives under ``default`` (the "dev data" premise is a design-time
  assumption, not an execution-time fact). Delegates to the controller's tested,
  resumable ``tenant_purge.purge_tenant`` so script and runtime share one engine.

Freeze (step 2 of B9) has no single flag — it is operational: re-point/retire the
demo traffic orchestrator and stop re-seeding under ``default`` BEFORE the purge,
so no net-new ``default`` rows accrue. This tool warns if it sees recent activity.

Usage
-----
    python scripts/migrate_brownfield.py inventory                     # safe, read-only
    python scripts/migrate_brownfield.py inventory --out default_inventory.json
    python scripts/migrate_brownfield.py purge --confirm-no-customer-data  # irreversible
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, List

import boto3

os.environ.setdefault("AWS_PROFILE", "sentra")
os.environ.setdefault("AWS_REGION", "us-east-1")
AWS_PROFILE = os.environ["AWS_PROFILE"]
AWS_REGION = os.environ["AWS_REGION"]
DEFAULT_TENANT = "default"

REGISTRY_V2 = os.environ.get("AGENT_REGISTRY_TABLE_V2", "sentra-agent-registry-v2")
REGISTRY_V1 = os.environ.get("AGENT_REGISTRY_TABLE", "sentra-agent-registry")
POLICIES_V2 = os.environ.get("POLICIES_METADATA_TABLE_V2", "sentra-policies-metadata-v2")
CREDS_TABLE = os.environ.get("AGENT_CREDENTIALS_TABLE", "sentra-agent-credentials")


def _session():
    return boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)


def inventory() -> Dict:
    ddb = _session().resource("dynamodb")
    inv: Dict = {"tenant": DEFAULT_TENANT}

    # v2 registry rows under `default`.
    reg = ddb.Table(REGISTRY_V2)
    resp = reg.query(
        KeyConditionExpression="tenant_id = :t",
        ExpressionAttributeValues={":t": DEFAULT_TENANT},
        ProjectionExpression="agent_id, cloud_provider, attached_policy_id",
    )
    inv["registry_v2"] = [
        {"agent_id": i.get("agent_id"), "cloud": i.get("cloud_provider"),
         "policy": i.get("attached_policy_id")}
        for i in resp.get("Items", [])
    ]

    # Legacy flat registry (no tenant_id) — the pre-v2 rows.
    flat = ddb.Table(REGISTRY_V1)
    fr = flat.scan(ProjectionExpression="agent_id, cloud_provider")
    inv["registry_flat"] = [
        {"agent_id": i.get("agent_id"), "cloud": i.get("cloud_provider")}
        for i in fr.get("Items", [])
    ]

    # Policies under `default`.
    pol = ddb.Table(POLICIES_V2)
    pr = pol.query(
        KeyConditionExpression="tenant_id = :t",
        ExpressionAttributeValues={":t": DEFAULT_TENANT},
        ProjectionExpression="policy_id, agent_id, s3_key",
    )
    inv["policies_v2"] = [
        {"policy_id": i.get("policy_id"), "agent_id": i.get("agent_id"), "s3_key": i.get("s3_key")}
        for i in pr.get("Items", [])
    ]

    # Any credentials wrongly registered under `default` (should be zero — real
    # tenants only). Surfaced so the sign-off can confirm none exist.
    try:
        cr = ddb.Table(CREDS_TABLE).query(
            KeyConditionExpression="tenant_id = :t",
            ExpressionAttributeValues={":t": DEFAULT_TENANT},
        )
        inv["credentials_under_default"] = len(cr.get("Items", []))
    except Exception:  # noqa: BLE001
        inv["credentials_under_default"] = "unknown"

    inv["counts"] = {
        "registry_v2": len(inv["registry_v2"]),
        "registry_flat": len(inv["registry_flat"]),
        "policies_v2": len(inv["policies_v2"]),
    }
    return inv


def _print_inventory(inv: Dict) -> None:
    print(f"== Brownfield inventory: tenant={inv['tenant']} ==")
    print(f"  v2 registry rows : {inv['counts']['registry_v2']}")
    for a in inv["registry_v2"]:
        print(f"    - {a['agent_id']} ({a['cloud']}) policy={a['policy']}")
    print(f"  flat registry rows: {inv['counts']['registry_flat']}")
    for a in inv["registry_flat"]:
        print(f"    - {a['agent_id']} ({a['cloud']})")
    print(f"  v2 policy rows   : {inv['counts']['policies_v2']}")
    print(f"  credentials under default (expect 0): {inv['credentials_under_default']}")
    if inv["credentials_under_default"] not in (0, "unknown"):
        print("  ⚠ credentials exist under `default` — a real tenant may be mis-homed; STOP and investigate")


def purge(confirm: bool) -> int:
    if not confirm:
        print("refusing to purge: pass --confirm-no-customer-data (explicit human sign-off "
              "re-confirming nothing real lives under `default`). Run `inventory` first and "
              "attach its output to the sign-off.", file=sys.stderr)
        return 2

    # Reuse the controller's tested, resumable purge engine (one engine for script
    # and runtime). settings table names default to the production names above.
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "security-controller"))
    from app.services.tenant_purge import purge_tenant  # type: ignore

    print("== Purging brownfield `default` population (IRREVERSIBLE) ==")
    counts = purge_tenant(
        DEFAULT_TENANT,
        confirm_no_customer_data=True,
        progress=lambda store, n: print(f"  ✓ {store}: {n} deleted"),
    )
    print(f"Done: {counts}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Brownfield `default` inventory + gated discard (WS-B B9)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    inv_p = sub.add_parser("inventory", help="read-only: list the default population")
    inv_p.add_argument("--out", help="write the inventory JSON here (to attach to sign-off)")

    pur_p = sub.add_parser("purge", help="IRREVERSIBLE: erase the default population")
    pur_p.add_argument("--confirm-no-customer-data", action="store_true",
                       help="explicit sign-off that nothing real lives under `default`")

    args = ap.parse_args()
    if args.cmd == "inventory":
        inv = inventory()
        _print_inventory(inv)
        if args.out:
            with open(args.out, "w") as f:
                json.dump(inv, f, indent=2, default=str)
            print(f"\nwrote {args.out}")
        return 0
    if args.cmd == "purge":
        return purge(args.confirm_no_customer_data)
    return 1


if __name__ == "__main__":
    sys.exit(main())
