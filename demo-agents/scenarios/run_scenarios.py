#!/usr/bin/env python3
"""Live cross-cloud demo scenarios against the DEPLOYED agents (the S2 / S4 analogues).

Run one at a time for an investor/CISO walkthrough — each prints a narration and hits real endpoints.

  S2  Cross-cloud policy propagation:
        a control-plane policy change instantly governs the Azure agent across the cloud boundary.
        (Now possible because PUT /v1/policies is fixed.)
  S4  Cross-cloud blast-radius containment:
        repeated injection attacks degrade a session's trust until it's QUARANTINED, after which every
        operation in that session is blocked — across both clouds — even a benign one.

Env: SENTRA_API_BASE, SENTRA_API_KEY, IDENTITY_FUNC_URL, TELECOM_FUNC_URL (with {tool_name}).

    python demo-agents/scenarios/run_scenarios.py s2
    python demo-agents/scenarios/run_scenarios.py s4
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

import yaml

HERE = pathlib.Path(__file__).resolve().parent
DEMO = HERE.parent
BASE = os.environ["SENTRA_API_BASE"].rstrip("/")
KEY = os.environ["SENTRA_API_KEY"]
TELECOM_URL = os.environ.get("TELECOM_FUNC_URL", "https://acme-telecom-func.azurewebsites.net/api/tool/{tool_name}")


def _api(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json", "x-api-key": KEY})
    try:
        with urllib.request.urlopen(req, timeout=35) as r:
            return r.status, json.loads(r.read() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or "{}")
        except Exception:
            return e.code, {}


def azure_tool(tool: str, params: dict, session_id: str, user_input: str) -> tuple[int, dict]:
    url = TELECOM_URL.replace("{tool_name}", tool)
    data = json.dumps({"params": params, "session_id": session_id, "user_input": user_input}).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=35) as r:
            return r.status, json.loads(r.read() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or "{}")
        except Exception:
            return e.code, {"reason": f"HTTP {e.code}"}


def validate(agent_id: str, tool: str, params: dict, session_id: str, user_input: str, op="READ") -> dict:
    _, body = _api("POST", "/v1/validate", {
        "request_id": f"sc-{uuid.uuid4().hex[:8]}", "session_id": session_id, "agent_id": agent_id,
        "tool_name": tool, "tool_params": params, "user_input": user_input,
        "timestamp": datetime.now(timezone.utc).isoformat(), "operation_type": op})
    return body


def _telecom_policy(remove_tool: str | None) -> dict:
    """The telecom PolicyUpdateRequest body, optionally with a tool removed from allowed_tools."""
    pol = next(p for p in yaml.safe_load((DEMO / "registration" / "policies.demo.yaml").read_text())["policies"]
               if p["agent_id"] == "acme-telecom-agent")
    body = dict(pol)
    if remove_tool:
        body["allowed_tools"] = [t for t in body["allowed_tools"] if t != remove_tool]
    return body


def banner(t: str) -> None:
    print(f"\n{'='*70}\n{t}\n{'='*70}")


def s2() -> None:
    banner("S2 — Cross-cloud policy propagation (control plane → Azure agent)")
    sid = f"s2-{uuid.uuid4().hex[:8]}"
    msisdn = "+12025550001"
    print("1. Customer asks the AZURE telecom agent to change their plan — currently ALLOWED:")
    s, b = azure_tool("change_plan", {"msisdn": msisdn, "new_plan": "postpaid-plus"}, sid, "upgrade my plan")
    print(f"   -> HTTP {s}  decision={b.get('decision', 'ALLOW')}")

    print("\n2. Security team removes `change_plan` from the telecom policy in Sentra (one API call):")
    s, b = _api("PUT", "/v1/policies/agent-config-acme-telecom-agent", _telecom_policy(remove_tool="change_plan"))
    print(f"   -> PUT /v1/policies  HTTP {s}  version={b.get('version')}")

    print("\n3. Wait for propagation, then the SAME Azure call is now BLOCKED by Sentra:")
    for i in range(12):
        time.sleep(5)
        s, b = azure_tool("change_plan", {"msisdn": msisdn, "new_plan": "postpaid-plus"}, f"{sid}-{i}", "upgrade my plan")
        dec = b.get("decision", "ALLOW")
        print(f"   t+{(i+1)*5:>3}s  HTTP {s}  decision={dec}  {b.get('reason','')[:50]}")
        if dec == "DENY":
            print("   ✓ policy change propagated across the cloud boundary.")
            break

    print("\n4. Restore the policy (re-add change_plan):")
    s, _ = _api("PUT", "/v1/policies/agent-config-acme-telecom-agent", _telecom_policy(remove_tool=None))
    print(f"   -> restored  HTTP {s}")


def s4() -> None:
    banner("S4 — Cross-cloud blast-radius containment (trust decay → quarantine)")
    sid = f"s4-{uuid.uuid4().hex[:8]}"
    attacks = [ln for ln in (DEMO / "traffic" / "attack_prompts" / "injection.txt").read_text().splitlines()
               if ln.strip() and not ln.startswith("#") and ("ignore" in ln.lower() or "forget" in ln.lower())][:5]
    print(f"Session {sid}: firing injection attacks; trust degrades on each DENY.\n")
    for i, atk in enumerate(attacks, 1):
        b = validate("acme-payments-agent", "get_transactions", {"account_id": "acct-1000"}, sid, atk)
        print(f"  attack {i}: decision={b.get('decision'):4}  trust_score={b.get('trust_score')}  {b.get('reason','')[:40]}")
        if (b.get("trust_score") or 100) <= 40:
            print("  ⚠ session trust <= 40 → QUARANTINED.")
            break
        time.sleep(1)

    print("\nNow a BENIGN, cross-cloud-relevant call in the SAME session — contained by quarantine:")
    b = validate("acme-payments-agent", "lookup_account", {"account_id": "acct-1000"}, sid, "what is my balance?")
    print(f"  benign lookup: decision={b.get('decision')}  trust={b.get('trust_score')}  {b.get('reason','')[:60]}")
    if b.get("decision") == "DENY":
        print("  ✓ the compromised session is isolated — even a harmless request is blocked.")


def main() -> int:
    which = (sys.argv[1].lower() if len(sys.argv) > 1 else "")
    if which == "s2":
        s2()
    elif which == "s4":
        s4()
    else:
        print("usage: run_scenarios.py [s2|s4]")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
