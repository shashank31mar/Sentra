#!/usr/bin/env python3
"""Mint a valid agent JWT from the throwaway probe identity (prints token)."""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "demo-agents" / "sdk" / "aegion-guard-python" / "src"))

import jwt as _jwt  # PyJWT[crypto]

ident = json.loads((HERE / ".probe_identity.json").read_text())
now = int(time.time())
tok = _jwt.encode(
    {"iss": "aegion-guard", "aud": "sentra-controller",
     "sub": ident["agent_id"], "tid": ident["tenant_id"],
     "iat": now, "exp": now + 600},
    ident["private_key"], algorithm="ES256", headers={"kid": ident["kid"]},
)
print(tok if isinstance(tok, str) else tok.decode())
