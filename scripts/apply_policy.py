#!/usr/bin/env python3
"""Control-plane policy CLI — Workstream 15 M5 Task 5.2.

Lets us mutate an agent's policy via the controller's /v1/policies API from
either the dashboard's S2 scenario runner OR a human at the keyboard.

S2 uses two operations:
  - `remove-tool`: drop a tool from the agent's allowed_tools so the next
    request to that tool DENIes with "tool not authorized for agent".
  - `add-tool`: add it back to restore baseline behavior.

Both prints the controller's reported propagation timestamps so the demo can
show "policy applied at T+0, both clouds enforcing at T+Δ".

Usage:
    python scripts/apply_policy.py \\
        --agent-id sentra-mvp-customer-service-agent \\
        --remove-tool query_customers \\
        --reason "S2 demo: tighten policy"

    python scripts/apply_policy.py \\
        --agent-id sentra-mvp-customer-service-agent \\
        --add-tool query_customers \\
        --reason "S2 demo: restore baseline"

Resolves the controller URL in this order:
  1. --controller-url CLI arg
  2. SENTRA_API_ENDPOINT env var (must end at /prod, /v1 is appended)
  3. fallback: http://localhost:8080 (local dev)

API key resolved from:
  1. --api-key CLI arg
  2. SENTRA_API_KEY env var
  3. AWS Secrets Manager 'sentra-api-key' (if boto3 importable + creds set)

Exits non-zero on any error so CI / pytest can assert.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional


logger = logging.getLogger("apply_policy")


def _resolve_controller_url(cli_value: Optional[str]) -> str:
    if cli_value:
        return cli_value.rstrip("/")
    # Check both env-var names the project uses. The dashboard ECS task sets
    # SECURITY_CONTROLLER_URL (internal ALB); scripts run outside the cluster
    # typically set SENTRA_API_ENDPOINT (public API Gateway). When apply_policy
    # is invoked in-process by the dashboard runner (S2 hook), it inherits the
    # dashboard's env — so SECURITY_CONTROLLER_URL must be honored, otherwise
    # the fallback to localhost:8080 hangs the runner (W17 deploy bug, fixed
    # 2026-05-26).
    for env_name in ("SECURITY_CONTROLLER_URL", "SENTRA_API_ENDPOINT"):
        env = os.environ.get(env_name, "").rstrip("/")
        if not env:
            continue
        # Trim known suffixes so callers can pass the validate URL directly.
        for suffix in ("/v1/validate", "/v1"):
            if env.endswith(suffix):
                env = env[: -len(suffix)]
                break
        return env
    return "http://localhost:8080"


def _resolve_api_key(cli_value: Optional[str]) -> Optional[str]:
    if cli_value:
        return cli_value
    if os.environ.get("SENTRA_API_KEY"):
        return os.environ["SENTRA_API_KEY"]
    # Last resort: try AWS Secrets Manager
    try:
        import boto3  # type: ignore

        client = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        secret = client.get_secret_value(SecretId="sentra-api-key")
        return json.loads(secret["SecretString"])["key"]
    except Exception as exc:  # pragma: no cover — exercised in prod only
        logger.debug("AWS Secrets Manager fallback failed: %s", exc)
        return None


def _http(method: str, url: str, *, api_key: Optional[str], body: Optional[dict] = None, timeout: float = 15.0) -> dict:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
    headers["X-Operator-Email"] = os.environ.get("SENTRA_OPERATOR_EMAIL", "apply-policy@cli")

    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else str(exc)
        raise SystemExit(f"HTTP {exc.code} {method} {url} :: {detail[:300]}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Network error {method} {url} :: {exc}") from exc


def resolve_policy_id(base_url: str, agent_id: str, api_key: Optional[str]) -> str:
    """Resolve an agent's active policy_id via GET /v1/policies?agent_id=...

    Why: the stored policy_id format is not deterministic from agent_id alone
    (it includes a version suffix like '-policy-v1'). An earlier version of
    this script hardcoded 'agent-config-<agent_id>' which matched a legacy
    naming convention that the active metadata store has long since moved on
    from — see the dashboard `sentra-policies-metadata` table. Hardcoding
    bites every time someone bumps the version suffix or refactors the policy
    seeder; resolving by agent_id keeps us decoupled from that detail.
    """
    qs = urllib.parse.urlencode({"agent_id": agent_id, "status": "active", "limit": 10})
    url = f"{base_url}/v1/policies?{qs}"
    resp = _http("GET", url, api_key=api_key)
    policies = resp.get("policies", [])
    if not policies:
        raise SystemExit(
            f"No active policy found for agent_id={agent_id!r}. "
            f"Check that {agent_id} is registered + has a policy in the "
            "sentra-policies-metadata table."
        )
    # If multiple policies match, prefer the highest 'version' suffix. The
    # active controller already filters by status=active, so this is just
    # defensive for the edge case of two concurrently-active policy versions.
    policies.sort(key=lambda p: p.get("version") or "", reverse=True)
    return policies[0]["policy_id"]


def fetch_policy(base_url: str, policy_id: str, api_key: Optional[str]) -> dict:
    url = f"{base_url}/v1/policies/{policy_id}?include_content=true"
    resp = _http("GET", url, api_key=api_key)
    policy = resp.get("policy")
    if not policy:
        raise SystemExit(f"Policy {policy_id} not found in response: {resp}")
    return policy


def push_policy(base_url: str, policy_id: str, body: dict, api_key: Optional[str]) -> dict:
    url = f"{base_url}/v1/policies/{policy_id}"
    return _http("PUT", url, api_key=api_key, body=body)


def _increment_patch(version: str) -> str:
    parts = version.split(".")
    if len(parts) != 3:
        raise SystemExit(f"unparsable semver: {version}")
    parts[2] = str(int(parts[2]) + 1)
    return ".".join(parts)


def _content_or_fail(policy: dict) -> dict:
    content = policy.get("content")
    if not content:
        raise SystemExit("Policy returned without content — pass include_content=true.")
    return content


def build_update_body(current: dict, *, remove_tool: Optional[str], add_tool: Optional[str]) -> dict:
    """Return a fresh policy body with one tool removed/added; bump patch version."""
    content = _content_or_fail(current)
    allowed = list(content.get("allowed_tools") or [])
    if remove_tool:
        if remove_tool not in allowed:
            raise SystemExit(f"Tool {remove_tool!r} is not in allowed_tools — nothing to remove.")
        allowed = [t for t in allowed if t != remove_tool]
    if add_tool:
        if add_tool in allowed:
            raise SystemExit(f"Tool {add_tool!r} is already in allowed_tools — nothing to add.")
        allowed.append(add_tool)
    if not allowed:
        raise SystemExit("Refusing to push a policy with empty allowed_tools.")

    return {
        "schema_version": content.get("schema_version", "v1"),
        "agent_id": content["agent_id"],
        "name": content["name"],
        "version": _increment_patch(content["version"]),
        "description": content.get("description"),
        "allowed_tools": allowed,
        "policies": content["policies"],
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Apply a policy update via the Sentra control plane.")
    parser.add_argument("--agent-id", required=True, help="Agent ID — policy_id is resolved via GET /v1/policies?agent_id=...")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--remove-tool", help="Tool name to remove from allowed_tools.")
    grp.add_argument("--add-tool", help="Tool name to add to allowed_tools.")
    parser.add_argument("--reason", default="", help="Free-text reason recorded in the audit log.")
    parser.add_argument("--controller-url", default=None, help="Override the controller base URL.")
    parser.add_argument("--api-key", default=None, help="Override the Sentra API key.")
    parser.add_argument("--dry-run", action="store_true", help="Print the patched policy body but don't PUT it.")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s")

    base_url = _resolve_controller_url(args.controller_url)
    api_key = _resolve_api_key(args.api_key)
    if not api_key and base_url.startswith("https://"):
        logger.warning("No API key resolved; controller will likely 401 on the public endpoint.")

    # Resolve policy_id from agent_id rather than hardcoding a naming convention.
    policy_id = resolve_policy_id(base_url, args.agent_id, api_key)
    logger.info("Resolved policy_id=%s for agent_id=%s", policy_id, args.agent_id)
    logger.info("Fetching current policy %s from %s", policy_id, base_url)
    current = fetch_policy(base_url, policy_id, api_key)
    current_version = (current.get("metadata") or {}).get("version") or _content_or_fail(current).get("version")
    logger.info("Current version: %s · current allowed_tools: %s", current_version, _content_or_fail(current).get("allowed_tools"))

    new_body = build_update_body(current, remove_tool=args.remove_tool, add_tool=args.add_tool)

    if args.dry_run:
        print(json.dumps(new_body, indent=2))
        return 0

    t0 = time.perf_counter()
    t0_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    logger.info("Pushing policy update (reason=%r)", args.reason or "—")
    result = push_policy(base_url, policy_id, new_body, api_key)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    summary = {
        "policy_id": policy_id,
        "previous_version": current_version,
        "new_version": result.get("version"),
        "applied_at": t0_iso,
        "controller_round_trip_ms": elapsed_ms,
        "controller_reported_updated_at": result.get("updated_at"),
        "removed_tool": args.remove_tool,
        "added_tool": args.add_tool,
        "reason": args.reason,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
