#!/usr/bin/env python3
"""WS-0 Test-2 provisioning — mint a THROWAWAY probe-agent identity (tenant=acme).

The live prod controller runs TENANT_IDENTITY_MODE=enforce: a request without a
valid ES256 agent JWT fail-closes at IDENTITY_UNVERIFIED before Sigma/Bedrock. To
measure the ESCALATED path (WAN → pipeline → real Bedrock) we need a verified
session. This registers a fresh throwaway agent using the SAME production code the
operator endpoint calls (CredentialStore.register → DDB) — it does NOT touch the 3
real acme keys, and the private key never leaves this host (asymmetric trust).

Writes harness/ws0/.probe_identity.json (gitignored) with agent_id/tenant/kid/priv.
Idempotent-ish: re-running registers a NEW kid (rotation-safe) — fine for a spike.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "demo-agents" / "sdk" / "aegion-guard-python" / "src"))
sys.path.insert(0, str(REPO / "src" / "security-controller"))

from aegion_guard.identity import generate_keypair  # noqa: E402

TENANT = "acme"
# sub MUST start with tenant + "-" (controller deps.py check). Throwaway probe id.
AGENT_ID = "acme-aws-ws0probe-000000"
OUT = HERE / ".probe_identity.json"


def main() -> None:
    if os.environ.get("AWS_PROFILE") != "sentra":
        print("warn: AWS_PROFILE!=sentra; register writes to the sentra DDB", file=sys.stderr)

    from app.services.credentials_service import get_credential_store  # noqa: E402

    priv_pem, pub_pem = generate_keypair()
    store = get_credential_store()
    kid = store.register(
        tenant_id=TENANT,
        agent_id=AGENT_ID,
        public_key=pub_pem,
        created_by="ws0-spike-throwaway",
    )
    OUT.write_text(json.dumps({
        "agent_id": AGENT_ID,
        "tenant_id": TENANT,
        "kid": kid,
        "private_key": priv_pem,
    }))
    OUT.chmod(0o600)
    print(f"✓ registered throwaway probe kid={kid} agent={AGENT_ID} tenant={TENANT}")
    print(f"✓ wrote {OUT.relative_to(REPO)} (mode 600, gitignored)")
    print("  → this is a NEW kid; the 3 real acme agent keys are untouched.")
    print("  → to clean up after the spike: delete this DDB row "
          f"(tenant_id={TENANT}, key_id={AGENT_ID}#{kid}) + rm {OUT.name}")


if __name__ == "__main__":
    main()
