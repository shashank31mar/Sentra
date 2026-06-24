#!/usr/bin/env python3
"""Provision data-plane identity for the three Acme demo agents (LLD-26 WS-A/acme migration).

The Acme agents already live under tenant ``acme`` with bound policies; this is the
last mile that makes them actually *sign* their ``/v1/validate`` calls under that
tenant (so the tenant can run in ``enforce``). For each agent it:

  1. generates a fresh ES256 keypair (rotation-safe: the controller keeps old keys
     valid until ``not_after``, so re-running never bricks a live agent),
  2. registers the **public** key under tenant ``acme`` → a ``kid``
     (asymmetric trust: the private key never leaves this host — LLD-26 §3),
  3. writes the private key (mode 600) + an ``<agent>.identity.env`` scaffold,
  4. prints the exact deploy env to export before re-deploying that agent.

This is a thin loop over the tested SDK CLI (``aegion_guard.provision``) — it adds
the per-agent fan-out and the deploy-env emission, nothing security-relevant.

Registration is operator-authed (control-plane RBAC ≥ admin, or `editor` to
rotate). Supply the operator token the same way the SDK CLI does, via ``--header``.

Usage
-----
    python provision_acme_identity.py \\
        --api-base "$SENTRA_API_BASE" \\
        --header "x-amzn-oidc-data: <operator OIDC token>"

    # then, per the printed output, export the env and redeploy each agent:
    #   AWS  : SENTRA_TENANT_ID/KID/PRIVATE_KEY -> deploy_payments_agent.py
    #   Azure: same three -> azd up (wired through infra/main.bicep)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Make the canonical SDK importable (src layout).
_SDK_SRC = Path(__file__).resolve().parents[1] / "sdk" / "aegion-guard-python" / "src"
sys.path.insert(0, str(_SDK_SRC))

from aegion_guard import provision  # noqa: E402  (after sys.path tweak)

TENANT = "acme"
# (agent_id, kind) — agent_id is the existing flat id, which is a delimited prefix
# of tenant `acme` (`acme-` == tenant + "-"), so it passes the controller's
# canonical-id check without a re-key.
ACME_AGENTS = [
    ("acme-payments-agent", "aws"),
    ("acme-identity-agent", "azure"),
    ("acme-telecom-agent", "azure"),
]


def main() -> int:
    ap = argparse.ArgumentParser(description="Provision identity for the Acme demo agents (tenant=acme)")
    ap.add_argument("--api-base", default=os.environ.get("SENTRA_API_BASE"),
                    help="Controller/API base URL (or set SENTRA_API_BASE).")
    ap.add_argument("--header", action="append", default=[], metavar="'Name: value'",
                    help="Operator auth header for registration (e.g. x-amzn-oidc-data). Repeatable.")
    ap.add_argument("--out-dir", default="./.identity", help="Where to write keys/env (default: ./.identity).")
    ap.add_argument("--no-register", action="store_true",
                    help="Generate keys only; skip the controller registration POST.")
    args = ap.parse_args()

    if not args.api_base and not args.no_register:
        print("error: --api-base (or SENTRA_API_BASE) required unless --no-register", file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(out_dir, 0o700)

    print(f"== Provisioning identity for {len(ACME_AGENTS)} Acme agents (tenant={TENANT}) ==\n")
    for agent_id, cloud in ACME_AGENTS:
        print(f"--- {agent_id} [{cloud}] ---")
        argv = ["--agent-id", agent_id, "--tenant-id", TENANT, "--out-dir", str(out_dir)]
        if not args.no_register:
            argv += ["--register", "--api-base", args.api_base]
            for h in args.header:
                argv += ["--header", h]
        rc = provision.main(argv)
        if rc != 0:
            print(f"  ✗ provisioning failed for {agent_id} (rc={rc})", file=sys.stderr)
            return rc
        key_path = out_dir / f"{agent_id}.key"
        print(f"\n  To enable signing on redeploy, export (kid printed above):")
        print(f"    export SENTRA_TENANT_ID={TENANT}")
        print(f"    export SENTRA_AGENT_KID=<kid-from-above>")
        if cloud == "aws":
            print(f"    export SENTRA_AGENT_PRIVATE_KEY=\"$(cat {key_path})\"   # Lambda env (PEM literal)")
            print(f"    python demo-agents/aws-payments-agent/deploy/deploy_payments_agent.py --create")
        else:
            print(f"    export SENTRA_AGENT_PRIVATE_KEY=\"$(cat {key_path})\"   # azd → infra/main.bicep")
            print(f"    (cd demo-agents/azure-{ 'identity' if 'identity' in agent_id else 'telecom' }-agent && azd up)")
        print()

    print("All Acme agents provisioned. After redeploy, verify in shadow (controller logs "
          "identity_state=verified), then flip tenant `acme` to enforce + raise the dev ceiling.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
