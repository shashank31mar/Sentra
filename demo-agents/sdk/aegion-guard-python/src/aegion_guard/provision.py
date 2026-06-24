"""Operator provisioning helper — generate an agent keypair and register its public key.

Run as ``python -m aegion_guard.provision``. This is an **operator** tool (the
agent never self-registers — that is the asymmetric trust model, LLD-26 §3): an
operator generates a P-256 keypair, keeps the private key with the agent, and
registers only the **public** key with the controller, which returns a ``kid``.

Two modes:

* default — generate the keypair, write ``<agent_id>.private.pem`` (mode 600) and
  ``<agent_id>.public.pem``, and print the exact registration request body + curl.
  The operator registers via the console/API, then sets ``SENTRA_AGENT_KID``.

* ``--register`` — additionally POST the public key to
  ``{api_base}/v1/agents/{agent_id}/credentials`` (operator-authed; pass the
  required auth via ``--header "x-amzn-oidc-data: ..."`` or whatever your
  deployment needs), parse the returned ``kid``, and write a ready-to-source
  ``<agent_id>.identity.env``.

The private key is written locally and never transmitted; only the public key is
sent. Requires the ``identity`` extra (``pip install 'aegion-guard[identity]'``).
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

from .identity import ALG, generate_keypair


def _parse_headers(raw: List[str]) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    for item in raw or []:
        if ":" not in item:
            raise SystemExit(f"--header must be 'Name: value' (got {item!r})")
        name, _, value = item.partition(":")
        headers[name.strip()] = value.strip()
    return headers


def _write_private_key(path: Path, pem: str) -> None:
    """Write the private key with owner-only permissions (0600)."""
    # Create with restrictive perms from the start (don't widen-then-narrow).
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, pem.encode("utf-8"))
    finally:
        os.close(fd)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def _register(api_base: str, agent_id: str, public_pem: str,
              headers: Dict[str, str], timeout_s: float = 10.0) -> str:
    """POST the public key; return the ``kid`` the controller assigns."""
    url = f"{api_base.rstrip('/')}/v1/agents/{agent_id}/credentials"
    body = json.dumps({"public_key": public_pem, "alg": ALG}).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise SystemExit(f"registration failed: HTTP {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"could not reach controller at {url}: {exc.reason}") from exc
    kid = data.get("kid")
    if not kid:
        raise SystemExit(f"controller did not return a kid (got {data!r})")
    return kid


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m aegion_guard.provision",
        description="Generate an agent ES256 keypair and (optionally) register its public key.",
    )
    ap.add_argument("--agent-id", required=True,
                    help="Canonical agent_id (must start with '<tenant_id>-').")
    ap.add_argument("--tenant-id", required=True, help="Owning tenant_id.")
    ap.add_argument("--out-dir", default=".", help="Where to write key/env files (default: cwd).")
    ap.add_argument("--ttl", type=float, default=None,
                    help="Token lifetime seconds for the agent (≤900; default 600).")
    ap.add_argument("--register", action="store_true",
                    help="Also POST the public key to the controller and capture the kid.")
    ap.add_argument("--api-base", default=os.environ.get("SENTRA_API_BASE"),
                    help="Controller/API base URL (required with --register).")
    ap.add_argument("--header", action="append", default=[], metavar="'Name: value'",
                    help="Extra request header for --register (operator auth). Repeatable.")
    args = ap.parse_args(argv)

    if not args.agent_id.startswith(args.tenant_id + "-"):
        print(
            f"error: agent_id {args.agent_id!r} must be tenant-scoped — it must start "
            f"with {args.tenant_id + '-'!r}. The controller's isolation check rejects "
            f"any other shape.",
            file=sys.stderr,
        )
        return 2

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    private_pem, public_pem = generate_keypair()
    priv_path = out / f"{args.agent_id}.private.pem"
    pub_path = out / f"{args.agent_id}.public.pem"
    _write_private_key(priv_path, private_pem)
    pub_path.write_text(public_pem, encoding="utf-8")

    print(f"✓ wrote private key (keep secret, on the agent): {priv_path}  [mode 600]")
    print(f"✓ wrote public key (register with Sentra):       {pub_path}")
    print()

    reg_body = {"public_key": public_pem, "alg": ALG}
    kid: Optional[str] = None
    if args.register:
        if not args.api_base:
            print("error: --register requires --api-base (or SENTRA_API_BASE).", file=sys.stderr)
            return 2
        kid = _register(args.api_base, args.agent_id, public_pem, _parse_headers(args.header))
        print(f"✓ registered public key — kid = {kid}")
    else:
        print("Register the public key (operator-authed), then note the returned kid:")
        print(f"  POST {{api_base}}/v1/agents/{args.agent_id}/credentials")
        print("  body:")
        print("    " + json.dumps(reg_body))
        print()

    # Emit the env scaffold the agent process sources to enable signing.
    env_path = out / f"{args.agent_id}.identity.env"
    ttl_line = f"\nSENTRA_TOKEN_TTL_S={args.ttl}" if args.ttl else ""
    env_path.write_text(
        f"# Source this in the agent's environment to enable WS-A request signing.\n"
        f"SENTRA_TENANT_ID={args.tenant_id}\n"
        f"SENTRA_AGENT_KID={kid or '<kid-from-registration>'}\n"
        f"SENTRA_AGENT_PRIVATE_KEY_FILE={priv_path.resolve()}{ttl_line}\n",
        encoding="utf-8",
    )
    print(f"✓ wrote env scaffold: {env_path}")
    if kid is None:
        print("  (fill in SENTRA_AGENT_KID once registration returns the kid)")
    print()
    print("Then in the agent:  AegionGuard(agent_id=..., ...) auto-signs from these env vars,")
    print("or pass tenant_id=/kid=/private_key_file= explicitly.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
