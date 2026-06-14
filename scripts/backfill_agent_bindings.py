#!/usr/bin/env python3
"""Backfill the agent→policy *binding* (and per-agent cloud_region).

agent-policy-management M0 / T10 (+ T11 data migration). **Run this BEFORE the
engine starts reading the binding** (agent-policy-management feature §2.6). The
engine ships with a legacy-GSI fallback so the order is safe either way, but
running this first means the binding path is authoritative from the first
request and there is no window where any agent resolves `null`.

What it does (idempotent, re-runnable):
  1. For every agent in `sentra-agent-registry`, resolve its CURRENT governing
     policy exactly as the engine resolves it *today* — the `agent-index` GSI on
     `sentra-policies-metadata` (`agent_id` + `status=active`, latest first).
     That policy's STORED `policy_id` is written to the agent as the scalar
     `attached_policy_id`. The id is NEVER reconstructed as `agent-config-{id}`
     (feature §2.7 / K2 — legacy ids carry varied suffixes).
  2. Backfill `cloud_region` on any agent missing it (T11), derived from the
     agent's hosting cloud (`resolve_cloud_region`). Real seeded agents already
     carry it after seed_agents.py; this covers records seeded by other paths.

Non-1:1 reality (feature §2.6 / N2 / K8) — handled explicitly, NOT as errors:
  - Agent with NO active policy  -> left UNBOUND (expected). It will fail-secure
    DENY post-cutover, which is intended (e.g. the *-unsecured demo agent).
    Reported in the "unbound (expected)" list for sign-off.
  - Policy with NO agent (orphan) -> nothing to bind; ignored. Still available
    in the attach picker for future binding.

Verify semantics: we assert every agent that HAD a resolvable active policy now
has a matching `attached_policy_id`. We do NOT assert "every agent is bound".

Usage:
    export AWS_PROFILE=sentra
    export AWS_REGION=us-east-1

    python scripts/backfill_agent_bindings.py --dry-run     # preview, no writes
    python scripts/backfill_agent_bindings.py               # apply
    python scripts/backfill_agent_bindings.py --verify-only  # check state only

Exits non-zero if the verify step fails (so CI can gate on it).
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Optional

import boto3
from boto3.dynamodb.conditions import Key

import _tenancy  # shared tenancy helpers (workstream T08) — flag-gated, no-op when off

# Region defaults live with the controller's resolver so the script and the
# engine agree on the fallback. Import is best-effort: the script can run from a
# checkout without the controller package on PYTHONPATH.
try:  # pragma: no cover - import shim
    sys.path.insert(
        0, os.path.join(os.path.dirname(__file__), "..", "src", "security-controller")
    )
    from app.utils.cloud import resolve_cloud_region  # type: ignore
except Exception:  # fallback so the script is self-contained
    _CLOUD_TO_REGION = {"aws": "us-east-1", "azure": "centralus", "gcp": "us-central1"}
    _PLATFORM_TO_CLOUD = {
        "bedrock": "aws",
        "azure_foundry": "azure",
        "vertex_ai": "gcp",
        "sentra": "aws",
    }

    def resolve_cloud_region(agent, policy=None):  # type: ignore
        if agent and agent.get("cloud_region"):
            return agent["cloud_region"]
        if policy and policy.get("cloud_region"):
            return policy["cloud_region"]
        provider = (agent or {}).get("cloud_provider") or _PLATFORM_TO_CLOUD.get(
            (agent or {}).get("platform"), "unknown"
        )
        return _CLOUD_TO_REGION.get(provider)


AWS_PROFILE = os.environ.get("AWS_PROFILE", "sentra")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
AGENT_TABLE = "sentra-agent-registry"
POLICY_TABLE = "sentra-policies-metadata"
AGENT_TABLE_V2 = "sentra-agent-registry-v2"
POLICY_TABLE_V2 = "sentra-policies-metadata-v2"
AGENT_INDEX = "agent-index"


def _session() -> boto3.Session:
    # Honor an already-exported AWS_PROFILE; fall back to the project default.
    return boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)


def _scan_all(table) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    kwargs: Dict[str, Any] = {}
    while True:
        # Tenant-scoped Query when TENANCY_V2_ENABLED, else full scan (no-op off).
        resp = _tenancy.query_or_scan(table, **kwargs)
        items.extend(resp.get("Items", []))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            return items
        kwargs["ExclusiveStartKey"] = lek


def resolve_active_policy_id(policy_table, agent_id: str) -> Optional[str]:
    """The STORED policy_id of the agent's active policy via the agent-index GSI
    (exactly how the engine resolves today). None if the agent has no active
    policy. Never reconstructs the id (K2). The agent-index PK is the composite
    `tenant_agent_id` when v2 is on (matches the runtime engine)."""
    resp = policy_table.query(
        IndexName=AGENT_INDEX,
        KeyConditionExpression=_tenancy.agent_index_condition(agent_id),
        FilterExpression=Key("status").eq("active"),
        ScanIndexForward=False,  # latest version first
        Limit=1,
    )
    items = resp.get("Items", [])
    return items[0]["policy_id"] if items else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="preview, no writes")
    ap.add_argument("--verify-only", action="store_true", help="check state, no writes")
    args = ap.parse_args()

    ddb = _session().resource("dynamodb")
    agents_table = ddb.Table(_tenancy.table_name(AGENT_TABLE, AGENT_TABLE_V2))
    policy_table = ddb.Table(_tenancy.table_name(POLICY_TABLE, POLICY_TABLE_V2))

    agents = _scan_all(agents_table)
    policies = _scan_all(policy_table)
    bound_policy_ids = {
        rid
        for a in agents
        if (rid := a.get("attached_policy_id"))
    }

    print(f"Loaded {len(agents)} agents, {len(policies)} policies "
          f"(profile={AWS_PROFILE}, region={AWS_REGION})\n")

    to_bind: List[Dict[str, str]] = []        # agents that need a binding written
    already_bound: List[str] = []             # already correct (idempotent no-op)
    unbound_expected: List[str] = []          # no active policy -> intentionally unbound
    region_backfill: List[Dict[str, str]] = []  # agents missing cloud_region

    for agent in agents:
        agent_id = agent["agent_id"]
        resolved = resolve_active_policy_id(policy_table, agent_id)
        current = agent.get("attached_policy_id")

        if resolved is None:
            unbound_expected.append(agent_id)
        elif current == resolved:
            already_bound.append(agent_id)
        else:
            to_bind.append({"agent_id": agent_id, "policy_id": resolved,
                            "was": current or "<none>"})

        if not agent.get("cloud_region"):
            region = resolve_cloud_region(agent)
            if region:
                region_backfill.append({"agent_id": agent_id, "region": region})

    # Orphan policies (active policy whose agent_id is not a registered agent).
    agent_ids = {a["agent_id"] for a in agents}
    orphan_policies = sorted({
        p["policy_id"] for p in policies
        if p.get("status") == "active" and p.get("agent_id") not in agent_ids
    })

    # ---- Report ----
    print("== Plan ==")
    print(f"  bind (write attached_policy_id) : {len(to_bind)}")
    for r in to_bind:
        print(f"      {r['agent_id']:<45} {r['was']} -> {r['policy_id']}")
    print(f"  already bound (no-op)           : {len(already_bound)}")
    print(f"  cloud_region backfill           : {len(region_backfill)}")
    for r in region_backfill:
        print(f"      {r['agent_id']:<45} cloud_region = {r['region']}")
    print(f"  unbound (expected, will DENY)   : {len(unbound_expected)}")
    for aid in sorted(unbound_expected):
        print(f"      {aid}")
    print(f"  orphan active policies (ignored): {len(orphan_policies)}")
    for pid in orphan_policies:
        print(f"      {pid}")
    print()

    # ---- Apply ----
    if not args.dry_run and not args.verify_only:
        for r in to_bind:
            agents_table.update_item(
                Key=_tenancy.item_key("agent_id", r["agent_id"]),
                UpdateExpression="SET attached_policy_id = :p",
                ExpressionAttributeValues={":p": r["policy_id"]},
            )
        for r in region_backfill:
            agents_table.update_item(
                Key=_tenancy.item_key("agent_id", r["agent_id"]),
                UpdateExpression="SET cloud_region = :r",
                ExpressionAttributeValues={":r": r["region"]},
            )
        print(f"Applied: {len(to_bind)} bindings, {len(region_backfill)} regions.\n")
    elif args.dry_run:
        print("Dry-run: no writes.\n")

    # ---- Verify ----
    # Re-read so verification reflects what's actually persisted (not our plan).
    if not args.dry_run:
        fresh = {a["agent_id"]: a for a in _scan_all(agents_table)}
        failures = []
        for agent in agents:
            agent_id = agent["agent_id"]
            resolved = resolve_active_policy_id(policy_table, agent_id)
            if resolved is None:
                continue  # expected-unbound; not a failure (N2/K8)
            got = fresh.get(agent_id, {}).get("attached_policy_id")
            if got != resolved:
                failures.append(f"{agent_id}: expected {resolved}, got {got!r}")
        if failures:
            print("VERIFY FAILED:")
            for f in failures:
                print(f"  {f}")
            return 1
        print("VERIFY OK: every agent with a resolvable active policy is bound to it.")
        print(f"  ({len(unbound_expected)} expected-unbound, {len(orphan_policies)} "
              f"orphan policies — both accepted.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
