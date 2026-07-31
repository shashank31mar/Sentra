#!/usr/bin/env python3
"""One-time Gmail OAuth setup — run once to authorize and cache token.json.

Prereqs (founder does these in Google Cloud Console — see docs/outreach-automation.md §6):
  1. Create a project, enable the Gmail API.
  2. Create an OAuth client ID (type: Desktop app), Testing mode, your address as a test user.
  3. Download it as scripts/outreach/credentials.json.

Then:
  python scripts/outreach/setup_gmail_oauth.py
A browser opens; approve the requested scopes; token.json is written. Done.
"""
from __future__ import annotations

import os
import sys

# Google may return a slightly narrowed/reordered scope set (e.g. it drops a redundant scope);
# without this, oauthlib raises "Scope has changed" and aborts before the token is written.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

from lib.config import load_config, resolve
from lib.gmail import GmailClient


def main() -> int:
    cfg = load_config()
    gcfg = cfg["gmail"]
    client = GmailClient(
        credentials_path=resolve(gcfg["credentials"]),
        token_path=resolve(gcfg["token"]),
        scopes=gcfg["scopes"],
    )
    # Touching the service forces the consent flow if no valid token exists.
    profile = client.service().users().getProfile(userId="me").execute()
    print(f"✓ Authorized as {profile.get('emailAddress')}")
    print(f"✓ Token cached at {resolve(gcfg['token'])}")
    print("  Scopes:", ", ".join(s.rsplit('/', 1)[-1] for s in gcfg["scopes"]))
    return 0


if __name__ == "__main__":
    # Allow `python scripts/outreach/setup_gmail_oauth.py` from repo root.
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
    raise SystemExit(main())
