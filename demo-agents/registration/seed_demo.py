#!/usr/bin/env python3
"""Register the demo agents and create their policies (LLD 22 §10.2–§10.4).

Two actions, both idempotent-ish and demo-local (no core seeders imported):
  * **agents**   -> write the full registry envelope to `sentra-agent-registry` (boto3 put_item).
  * **policies** -> POST each policy to `/v1/policies` (PolicyCreateRequest) with the usage-plan key.

There is no public `POST /v1/agents` yet (LLD 22 §10 fast-follow), so registration writes the registry
table directly — exactly the gap a future registration API would close.

Env:
    SENTRA_API_BASE   https://<id>.execute-api.us-east-1.amazonaws.com/prod
    SENTRA_API_KEY    usage-plan x-api-key
    AWS_PROFILE/AWS_REGION (default sentra / us-east-1)

    python registration/seed_demo.py                 # agents + policies
    python registration/seed_demo.py --dry-run
    python registration/seed_demo.py --agents-only
    python registration/seed_demo.py --policies-only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List

import yaml

HERE = pathlib.Path(__file__).resolve().parent
REGISTRY_TABLE = os.environ.get("SENTRA_AGENT_REGISTRY", "sentra-agent-registry")
PROFILE = os.environ.get("AWS_PROFILE", "sentra")
REGION = os.environ.get("AWS_REGION", "us-east-1")


def _load(name: str, key: str) -> List[Dict[str, Any]]:
    return yaml.safe_load((HERE / name).read_text())[key]


def _floats_to_decimal(obj: Any) -> Any:
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_floats_to_decimal(v) for v in obj]
    return obj


# --------------------------------------------------------------------------- agents
def register_agents(dry_run: bool) -> None:
    agents = _load("agents.demo.yaml", "agents")
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    print(f"\n== Registering {len(agents)} agents to {REGISTRY_TABLE} ==")
    if dry_run:
        for a in agents:
            print(f"  [dry-run] {a['agent_id']} ({a['platform']}/{a['cloud_provider']})")
        return

    import boto3

    table = boto3.Session(profile_name=PROFILE, region_name=REGION).resource("dynamodb").Table(REGISTRY_TABLE)
    for a in agents:
        item = dict(a)
        item.setdefault("created_at", now)
        item.setdefault("created_by", "demo-seed")
        table.put_item(Item=_floats_to_decimal(item))
        print(f"  ✓ {a['agent_id']} ({a['platform']}/{a['cloud_provider']})")


# --------------------------------------------------------------------------- tools
TOOL_REGISTRY_TABLE = os.environ.get("SENTRA_TOOL_REGISTRY", "sentra-tool-registry")

# (tool_id, display name, op, [param names]). /v1/agents/{id}/tools enriches each agent's
# policy.allowed_tools against this registry and DROPS any tool not registered here — so the demo
# tools must be registered or Agent Detail shows an empty tools list (Kiro-style gap, observed live).
DEMO_TOOLS = [
    ("lookup_account", "Lookup Account", "READ", ["account_id"]),
    ("get_transactions", "Get Transactions", "READ", ["account_id", "limit"]),
    ("process_refund", "Process Refund", "WRITE", ["account_id", "amount", "txn_id"]),
    ("transfer_funds", "Transfer Funds", "WRITE", ["from_account", "to_account", "amount"]),
    ("verify_identity", "Verify Identity", "READ", ["subject_id", "method"]),
    ("check_fraud_score", "Check Fraud Score", "READ", ["key"]),
    ("lookup_subscriber", "Lookup Subscriber", "READ", ["msisdn"]),
    ("change_plan", "Change Plan", "WRITE", ["msisdn", "new_plan"]),
    ("reset_sim", "Reset SIM", "WRITE", ["msisdn", "new_sim_id"]),
    ("port_out_number", "Port Out Number", "WRITE", ["msisdn", "target_carrier"]),
]


def register_tools(dry_run: bool) -> None:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    print(f"\n== Registering {len(DEMO_TOOLS)} tools to {TOOL_REGISTRY_TABLE} ==")
    if dry_run:
        for tid, name, op, params in DEMO_TOOLS:
            print(f"  [dry-run] {tid} ({op}) params={params}")
        return
    import boto3

    table = boto3.Session(profile_name=PROFILE, region_name=REGION).resource("dynamodb").Table(TOOL_REGISTRY_TABLE)
    for tid, name, op, params in DEMO_TOOLS:
        table.put_item(Item={
            "tool_id": tid, "name": name,
            "description": f"{name} ({op}) — Acme demo tool, validated by AegionAI/Sentra.",
            "category": "read" if op == "READ" else "write",
            "operation_type": op,
            "parameters": {p: {"type": "string", "required": True} for p in params},
            "execution_config": {"timeout_seconds": 60, "retry_attempts": 1, "idempotent": op == "READ"},
            "status": "active", "version": "1.0.0", "created_at": now, "created_by": "demo-seed",
        })
        print(f"  ✓ {tid} ({op})")


# --------------------------------------------------------------------------- policies
POLICIES_METADATA_TABLE = os.environ.get("SENTRA_POLICIES_METADATA", "sentra-policies-metadata")
POLICY_S3_BUCKET = os.environ.get("SENTRA_POLICY_BUCKET", "sentra-mvp-artifacts")


def _severity_breakdown(rules: List[Dict[str, Any]]) -> Dict[str, int]:
    out = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for r in rules:
        sev = str(r.get("severity", "low")).lower()
        if sev in out:
            out[sev] += 1
    return out


def create_policies(dry_run: bool, force: bool = False) -> None:
    """Write demo policies straight to S3 + sentra-policies-metadata (the store the validator reads).

    NOTE: ``POST /v1/policies`` is unusable for creation today — the route validates
    ``request.dict(exclude_none=True)`` (a PolicyCreateRequest, which lacks ``policy_id/status/
    created_at/created_by``) against ``AgentPolicyDocument`` (which requires them), and the service
    only generates those *after* validation. So, exactly like agent registration (no public API),
    the seeder writes the hybrid DDB+S3 record directly, mirroring ``policy_service.create_policy``.
    This is what ``policy_engine.get_agent_policy`` reads (S3 YAML via the agent-index GSI).
    """
    import yaml as _yaml

    policies = _load("policies.demo.yaml", "policies")
    print(f"\n== Writing {len(policies)} policies to {POLICIES_METADATA_TABLE} + s3://{POLICY_S3_BUCKET} ==")
    if dry_run:
        for p in policies:
            ccd = "cross-cloud" if p.get("cross_cloud_dependencies") else "—"
            print(f"  [dry-run] {p['agent_id']}: {len(p['allowed_tools'])} tools, {ccd}")
        return

    import boto3

    sess = boto3.Session(profile_name=PROFILE, region_name=REGION)
    s3 = sess.client("s3")
    table = sess.resource("dynamodb").Table(POLICIES_METADATA_TABLE)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Discover the real artifacts bucket from an existing policy item (the CDK name is stack-suffixed,
    # not the hardcoded 'sentra-mvp-artifacts' string in policy_service.py).
    bucket = os.environ.get("SENTRA_POLICY_BUCKET")
    if not bucket:
        existing = table.scan(Limit=1, ProjectionExpression="s3_bucket").get("Items", [])
        bucket = existing[0]["s3_bucket"] if existing else POLICY_S3_BUCKET
    print(f"   policy bucket: {bucket}")

    for p in policies:
        agent_id = p["agent_id"]
        version = p["version"]
        policy_id = f"agent-config-{agent_id}"
        # The full policy document the validators read from S3 (carries cross_cloud_dependencies).
        doc = dict(p)
        doc.setdefault("policy_id", policy_id)
        doc.setdefault("status", "active")
        doc.setdefault("created_at", now)
        doc.setdefault("created_by", "demo-seed")
        yaml_content = _yaml.dump(doc, sort_keys=False)
        s3_key = f"policies/agents/{agent_id}/v{version}.yaml"
        put = s3.put_object(Bucket=bucket, Key=s3_key,
                            Body=yaml_content.encode("utf-8"), ContentType="application/x-yaml")
        metadata_item = {
            "policy_id": policy_id, "agent_id": agent_id, "name": p["name"], "version": version,
            "status": "active", "s3_bucket": bucket, "s3_key": s3_key,
            "s3_version_id": put.get("VersionId", "null"),
            "allowed_tools_count": len(p["allowed_tools"]), "policies_count": len(p["policies"]),
            "severity_breakdown": _severity_breakdown(p["policies"]),
            "content_hash": f"sha256:{hashlib.sha256(yaml_content.encode()).hexdigest()}",
            "schema_version": p.get("schema_version", "v1"),
            "created_at": now, "updated_at": now, "created_by": "demo-seed", "last_updated_by": "demo-seed",
        }
        table.put_item(Item=metadata_item)
        ccd = "cross-cloud" if p.get("cross_cloud_dependencies") else "—"
        print(f"  ✓ {agent_id} -> {policy_id} v{version} ({ccd}) [{s3_key}]")


def attach_policies(dry_run: bool) -> None:
    """Attach each agent's policy via the real API (populates agent.attached_policy_ids → the
    console's Agent Detail 'Attached policies' section). policy_id is deterministic per agent."""
    agents = _load("agents.demo.yaml", "agents")
    api_base = os.environ.get("SENTRA_API_BASE")
    api_key = os.environ.get("SENTRA_API_KEY")
    print(f"\n== Attaching policies to {len(agents)} agents ==")
    if dry_run:
        for a in agents:
            print(f"  [dry-run] {a['agent_id']} <- agent-config-{a['agent_id']}")
        return
    if not (api_base and api_key):
        raise SystemExit("SENTRA_API_BASE and SENTRA_API_KEY are required to attach policies")
    import urllib.error
    import urllib.request

    base = api_base.rstrip("/")
    for a in agents:
        aid = a["agent_id"]
        pid = f"agent-config-{aid}"
        req = urllib.request.Request(
            f"{base}/v1/agents/{aid}/policies", method="POST",
            data=json.dumps({"policy_id": pid}).encode(),
            headers={"Content-Type": "application/json", "x-api-key": api_key})
        try:
            with urllib.request.urlopen(req, timeout=30):
                print(f"  ✓ {aid} <- {pid}")
        except urllib.error.HTTPError as e:
            print(f"  {'•' if e.code == 409 else '✗'} {aid}: HTTP {e.code} (409 = already attached)")


def main() -> int:
    ap = argparse.ArgumentParser(description="Register demo agents + create policies")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--agents-only", action="store_true")
    ap.add_argument("--policies-only", action="store_true")
    ap.add_argument("--tools-only", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="update existing policies (PUT) instead of skipping on 409")
    args = ap.parse_args()

    if args.tools_only:
        register_tools(args.dry_run)
    else:
        if not args.policies_only:
            register_agents(args.dry_run)
            register_tools(args.dry_run)
        if not args.agents_only:
            create_policies(args.dry_run, force=args.force)
            attach_policies(args.dry_run)
    print("\n✅ seed_demo complete." if not args.dry_run else "\n(dry run — nothing written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
