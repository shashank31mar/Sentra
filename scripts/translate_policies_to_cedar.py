#!/usr/bin/env python3
"""Translate stored agent policies to Cedar co-artifacts (feature: cedar-policy CT08).

Writes a compiled `.cedar` co-artifact **beside** each policy's retained
structured source (`…/v{version}.yaml`) — never instead of it (CT06c) — and
stamps the metadata row so the runtime can find + cache the compiled Cedar.

The model (feature §6 / §6.1): the **authorization rules are universal** (the
bundled `baseline-v{N}.cedar`, derived from `policy_engine`'s real hardcoded
checks — refund cap, fraud gate, invoke_agent two-list, cross-cloud), and **all
per-agent variance is entity-borne** — `allowed_tools` / `allowed_agents` /
`max_refund_amount` (cents) / `requires_precondition` are synthesized into the
Cedar entity store at evaluation time (CedarPolicyEngine CT05b), NOT baked into
the `.cedar` text. So each migrated policy's `.cedar` IS the validated baseline
rule set (schema-validated once, not per-policy — per-agent variance is
entity-borne, not in the `.cedar` text); the translator's per-policy job is to:
  1. write the validated `.cedar` co-artifact,
  2. stamp `policy_format=cedar` + `generator_version` (so the compiled-Cedar
     cache key works and a generator bump forces regeneration), and preserve
     `allowed_tools_count` (else the Tools tab count goes to 0),
  3. emit a one-time inert-rule inventory (the decorative `policies[].rule`
     strings enforce nothing today and are explicitly NOT translated — C2).

Defaults reproduced (CT08 / Kiro #4): `max_refund_amount` absent still enforces
$5,000 — handled by CedarPolicyEngine's entity default (500000 cents), so the
principal attribute is always present (no fail-open). `max_calls_per_minute`
stays a pipeline counter (§5) — preserved on the structured dict, no Cedar rule.
`allowed_callers` is cross_agent_validator's, outside the authz subset — never
translated; stays a structured field.

🚦 GATE (CT06b): do NOT run the live backfill until CT06b (display-path fix) is
deployed — otherwise migrated agents show a broken Tools tab. Live runs require
`--confirm-ct06b-deployed`; `--dry-run` is always safe.

Usage:
    export AWS_PROFILE=sentra
    export AWS_REGION=us-east-1

    python scripts/translate_policies_to_cedar.py --dry-run        # preview, no writes
    python scripts/translate_policies_to_cedar.py --confirm-ct06b-deployed   # apply

Idempotent: re-running writes byte-identical `.cedar` and re-stamps the same
metadata. Exits non-zero if any policy fails schema validation.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List

import boto3
import yaml

import _tenancy  # shared tenancy helpers — flag-gated, no-op when off

# Cedar package (schema loader, validator, storage convention) from the controller.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "security-controller"))
from app.validators.cedar import policy_artifact  # noqa: E402
from app.validators.cedar.evaluator import validate_policy_set  # noqa: E402
from app.validators.cedar.generator import GENERATOR_VERSION, generate_cedar  # noqa: E402

AWS_PROFILE = os.environ.get("AWS_PROFILE", "sentra")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
POLICY_TABLE = "sentra-policies-metadata"
POLICY_TABLE_V2 = "sentra-policies-metadata-v2"


def _session() -> boto3.Session:
    return boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)


def _scan_all(table) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    kwargs: Dict[str, Any] = {}
    while True:
        resp = _tenancy.query_or_scan(table, **kwargs)
        items.extend(resp.get("Items", []))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            return items
        kwargs["ExclusiveStartKey"] = lek


def translate(dry_run: bool) -> int:
    session = _session()
    dynamodb = session.resource("dynamodb")
    s3 = session.client("s3")
    table = dynamodb.Table(_tenancy.table_name(POLICY_TABLE, POLICY_TABLE_V2))

    policies = _scan_all(table)
    print(f"Scanned {len(policies)} policy metadata rows from {table.name}\n")

    # Validate the baseline once — every policy emits the same rule set.
    errors = validate_policy_set(generate_cedar("__validation__"))
    if errors:
        print("FATAL: baseline Cedar fails schema validation:")
        for e in errors:
            print("   ", e)
        return 2

    migrated = 0
    skipped: List[str] = []
    inert_rule_total = 0
    inert_by_policy: Dict[str, int] = {}

    for meta in policies:
        policy_id = meta.get("policy_id", "<unknown>")
        s3_bucket = meta.get("s3_bucket")
        s3_key = meta.get("s3_key")
        if not s3_bucket or not s3_key:
            skipped.append(f"{policy_id} (no S3 reference)")
            continue

        # Load structured source for the inert-rule inventory + tool count.
        try:
            obj = s3.get_object(Bucket=s3_bucket, Key=s3_key)
            source = yaml.safe_load(obj["Body"].read().decode("utf-8")) or {}
        except Exception as exc:  # noqa: BLE001
            skipped.append(f"{policy_id} (source read failed: {exc})")
            continue

        n_inert = len(source.get("policies", []) or [])
        inert_rule_total += n_inert
        if n_inert:
            inert_by_policy[policy_id] = n_inert

        cedar_key = policy_artifact.cedar_key_for(s3_key)
        allowed_tools_count = meta.get("allowed_tools_count")
        if allowed_tools_count is None:
            allowed_tools_count = len(source.get("allowed_tools", []) or [])

        action = "DRY-RUN" if dry_run else "WRITE"
        print(f"[{action}] {policy_id}: {s3_key} → {cedar_key} "
              f"(policy_format=cedar, generator_version={GENERATOR_VERSION}, "
              f"allowed_tools_count={allowed_tools_count}, inert_rules={n_inert})")

        if not dry_run:
            cedar_text = generate_cedar(policy_id)
            policy_artifact.put_compiled_policies(
                s3, s3_bucket, s3_key, cedar_text,
                metadata={"policy_id": policy_id, "generator_version": GENERATOR_VERSION})
            table.update_item(
                Key=_tenancy.item_key("policy_id", policy_id),
                UpdateExpression=(
                    "SET policy_format = :fmt, generator_version = :gv, "
                    "allowed_tools_count = :atc"
                ),
                ExpressionAttributeValues={
                    ":fmt": policy_artifact.FORMAT_CEDAR,
                    ":gv": GENERATOR_VERSION,
                    ":atc": allowed_tools_count,
                },
            )
        migrated += 1

    print()
    print("=" * 70)
    print(f"{'Would migrate' if dry_run else 'Migrated'}: {migrated} policies")
    if skipped:
        print(f"Skipped: {len(skipped)}")
        for s in skipped:
            print("   ", s)
    # Inert-rule inventory (Kiro #6) — operator sign-off.
    print()
    print("INERT-RULE INVENTORY (decorative `policies[].rule` — never enforced today,"
          " NOT translated to Cedar):")
    print(f"   total inert rule strings across all policies: {inert_rule_total}")
    for pid, n in sorted(inert_by_policy.items()):
        print(f"   {pid}: {n} rule string(s) dropped")
    print("=" * 70)
    return 0


def verify() -> int:
    """WS-I I3.2 — the hard gate before flipping `legacy_retired: true` (LLD 28
    §4.4 steps 2–3). Read-only. Asserts BOTH conditions:

      1. zero policies with `policy_format != cedar` (residual-abstain count == 0), and
      2. every co-artifact's `generator_version` == the current GENERATOR_VERSION
         (a version bump without re-running the backfill leaves stale `.cedar` whose
         policy_format is still `cedar` — condition 1 alone would miss it, §3.3/E11).

    Exit 0 = safe to retire legacy. Exit 1 = NOT safe (residual or stale rows listed).
    """
    session = _session()
    dynamodb = session.resource("dynamodb")
    table = dynamodb.Table(_tenancy.table_name(POLICY_TABLE, POLICY_TABLE_V2))
    policies = _scan_all(table)

    non_cedar: List[str] = []
    stale_gv: List[str] = []
    for meta in policies:
        pid = meta.get("policy_id", "<unknown>")
        if meta.get(policy_artifact.POLICY_FORMAT_FIELD) != policy_artifact.FORMAT_CEDAR:
            non_cedar.append(f"{pid} (policy_format={meta.get(policy_artifact.POLICY_FORMAT_FIELD)!r})")
        elif meta.get("generator_version") != GENERATOR_VERSION:
            stale_gv.append(f"{pid} (generator_version={meta.get('generator_version')!r}, "
                            f"expected {GENERATOR_VERSION!r})")

    print(f"Verified {len(policies)} policy rows in {table.name} "
          f"(current GENERATOR_VERSION={GENERATOR_VERSION})")
    print(f"  residual non-cedar (would ABSTAIN): {len(non_cedar)}")
    print(f"  stale generator_version (cedar but out-of-date): {len(stale_gv)}")
    if non_cedar:
        print("  NON-CEDAR rows:")
        for s in non_cedar:
            print("    ", s)
    if stale_gv:
        print("  STALE generator_version rows:")
        for s in stale_gv:
            print("    ", s)

    if non_cedar or stale_gv:
        print("\nGATE FAILED — backfill incomplete. Do NOT flip legacy_retired:true.",
              file=sys.stderr)
        return 1
    print("\nGATE PASSED — every policy carries a current .cedar co-artifact. "
          "Flipping legacy_retired:true is safe (founder-gated, I3.3).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Translate agent policies to Cedar co-artifacts (CT08).")
    parser.add_argument("--dry-run", action="store_true", help="Preview only; write nothing.")
    parser.add_argument(
        "--verify", action="store_true",
        help="WS-I I3.2 read-only gate: assert 0 residual non-cedar policies AND "
             "generator-version parity. Exit 1 if not safe to retire legacy.")
    parser.add_argument(
        "--confirm-ct06b-deployed", action="store_true",
        help="Required for live runs: confirms the CT06b display-path fix is deployed "
             "(else migrated agents show a broken Tools tab).")
    args = parser.parse_args()

    if args.verify:
        return verify()

    if not args.dry_run and not args.confirm_ct06b_deployed:
        print("Refusing live backfill: pass --confirm-ct06b-deployed (CT06b gate) "
              "or use --dry-run.", file=sys.stderr)
        return 3

    return translate(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
