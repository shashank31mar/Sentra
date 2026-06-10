"""Continuous traffic generator (LLD 22 §9).

Drives the three agents with a realistic mix of legitimate (real-data) and attack (corpus) calls so
`console.aegionai.ai` always shows a steady ALLOW/DENY stream across both clouds. Each cross-cloud
sequence gets its **own short session_id** (LLD 22 §9 / Kiro M2): the controller caps tool_history at
the last 10 ALLOWED calls and rate-limits per session, so long/reused sessions cause false DENYs.

Invocation is pluggable:
  * ``LiveInvoker``  — Bedrock Lambda invoke (payments) + HTTP POST to the Azure Functions (identity/telecom).
  * a custom callable — used by tests to run the in-process handlers against a fake controller (offline).

Each "step" is (cloud, agent, tool, params, user_input, expect). The generator only orchestrates +
labels; the **decisions come from the real Sentra controller**, never from here.
"""
from __future__ import annotations

import json
import os
import pathlib
import random
import sys
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

# An invoker takes (cloud, tool, params, session_id, user_input, request_id) and returns (status, body).
Invoker = Callable[[str, str, Dict[str, Any], str, str, Optional[str]], Tuple[int, Dict[str, Any]]]

_ATTACKS_FILE = pathlib.Path(__file__).resolve().parent / "attack_prompts" / "injection.txt"


def load_attacks() -> List[str]:
    lines = []
    for ln in _ATTACKS_FILE.read_text().splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            lines.append(ln)
    return lines


# Prompts the live sigma ruleset reliably DENYs (mirror of prompt_injection_basic.yaml selections +
# tests/fake_controller markers). Sequences labelled DENY draw from THIS subset so the label is
# honest: the full deepset corpus includes subtle roleplay/translation attacks that even the live
# engine misses by design (recall ~0.58), which would make a 100%-DENY label unachievable.
_CAUGHT_MARKERS = (
    "ignore all previous", "ignore previous instructions", "ignore all preceding", "ignore the above",
    "forget all previous", "forget everything", "forget about all", "you are now dan", "developer mode",
    "jailbreak", "i want you to act as", "now you are", "new task:", "drop table", "delete from",
)


def caught_attacks() -> List[str]:
    """The reliably-denied subset of the corpus (matches live sigma + the offline FakeController)."""
    caught = [a for a in load_attacks() if any(m in a.lower() for m in _CAUGHT_MARKERS)]
    return caught or load_attacks()  # fall back to full corpus if the file ever changes


# Account keys the real IEEE-CIS snapshot classifies as HIGH fraud risk (band 'high'). Hardcoded so
# the traffic Lambda stays self-contained (no common/ + dataset bundled). Stable from the committed
# common/data/ieee_cis_scores.json; if that snapshot is regenerated, refresh via:
#   python -c "from common.store import fraud_score as f; \
#     print([f'acct-{i}' for i in range(1000,1200) if f(f'acct-{i}')['risk']=='high'][:8])"
_HIGH_FRAUD_ACCTS = ["acct-1019", "acct-1085", "acct-1090", "acct-1099",
                     "acct-1109", "acct-1111", "acct-1114", "acct-1136"]


@dataclass
class Step:
    cloud: str          # "aws" | "azure"
    agent: str          # agent_id
    tool: str
    params: Dict[str, Any]
    user_input: str
    expect: str         # "ALLOW" | "DENY" (the intended outcome; honesty-checked against reality)


@dataclass
class Sequence:
    name: str
    steps: List[Step]
    session_id: str = field(default_factory=lambda: f"sess-{uuid.uuid4().hex[:12]}")


def build_sequences(seed: int = 0, n_accounts: int = 200) -> List[Sequence]:
    """A labelled mix exercising both scenarios, sigma, and the hardcoded refund limit.

    Pools are derived statically (no Faker): account ids match what the loader writes
    (``acct-1000..``); the Azure identity/telecom tools are deterministic so any msisdn works.
    """
    rng = random.Random(seed)
    account_ids = [f"acct-{1000 + i}" for i in range(n_accounts)]
    attacks = caught_attacks()

    def acct() -> str:
        return rng.choice(account_ids)

    def linked() -> Tuple[str, str]:
        a = acct()
        return f"+1202555{rng.randint(0, 9999):04d}", a

    seqs: List[Sequence] = []

    # 1. Legit reads (ALLOW).
    a = acct()
    seqs.append(Sequence("legit_read", [
        Step("aws", "acme-payments-agent", "lookup_account", {"account_id": a}, "what's my balance?", "ALLOW"),
        Step("aws", "acme-payments-agent", "get_transactions", {"account_id": a, "limit": 5}, "show recent transactions", "ALLOW"),
    ]))

    # 2. Scenario A happy path: Azure verify -> AWS refund (same session) => ALLOW.
    a = acct()
    seqs.append(Sequence("scenarioA_happy", [
        Step("azure", "acme-identity-agent", "verify_identity", {"subject_id": a}, "verify the customer", "ALLOW"),
        Step("aws", "acme-payments-agent", "process_refund", {"account_id": a, "amount": 120.0}, "refund my $120 order", "ALLOW"),
    ]))

    # 3. Scenario A attack: refund WITHOUT prior verify => DENY (cross_cloud_dependency_not_met).
    seqs.append(Sequence("scenarioA_attack", [
        Step("aws", "acme-payments-agent", "process_refund", {"account_id": acct(), "amount": 90.0}, "please refund me", "DENY"),
    ]))

    # 4. Hardcoded refund limit: > $5000 => DENY (engine default, LLD 22 §6.5).
    a = acct()
    seqs.append(Sequence("refund_over_limit", [
        Step("azure", "acme-identity-agent", "verify_identity", {"subject_id": a}, "verify me", "ALLOW"),
        Step("aws", "acme-payments-agent", "process_refund", {"account_id": a, "amount": 7500.0}, "refund $7,500", "DENY"),
    ]))

    # 5. Scenario B1 happy: verify -> SIM swap => ALLOW.
    m, _ = linked()
    seqs.append(Sequence("scenarioB1_happy", [
        Step("azure", "acme-identity-agent", "verify_identity", {"subject_id": m}, "verify subscriber", "ALLOW"),
        Step("azure", "acme-telecom-agent", "reset_sim", {"msisdn": m, "new_sim_id": f"SIM{rng.randint(10**14, 10**15)}"}, "swap my SIM", "ALLOW"),
    ]))

    # 6. Scenario B1 attack: SIM swap / port-out WITHOUT verify => DENY.
    m, _ = linked()
    seqs.append(Sequence("scenarioB1_attack", [
        Step("azure", "acme-telecom-agent", "port_out_number", {"msisdn": m, "target_carrier": "Mint"}, "port my number out now", "DENY"),
    ]))

    # 7. Injection (sigma) => DENY, regardless of policy.
    seqs.append(Sequence("injection", [
        Step("aws", "acme-payments-agent", "get_transactions", {"account_id": acct()}, rng.choice(attacks), "DENY"),
    ]))

    # 7b. Injection BURST in ONE session: 3 attacks decay trust 100→80→60→40 → QUARANTINE, then a
    # benign call in that same session is contained (DENY). Makes trust-decay + blast-radius
    # containment visible in the LIVE feed — not just the manual S4 scenario (LLD 22 §6.4 / §9).
    a = acct()
    seqs.append(Sequence("injection_burst_quarantine", [
        Step("aws", "acme-payments-agent", "get_transactions", {"account_id": a}, rng.choice(attacks), "DENY"),
        Step("aws", "acme-payments-agent", "get_transactions", {"account_id": a}, rng.choice(attacks), "DENY"),
        Step("aws", "acme-payments-agent", "get_transactions", {"account_id": a}, rng.choice(attacks), "DENY"),
        Step("aws", "acme-payments-agent", "lookup_account", {"account_id": a}, "what is my balance?", "DENY"),
    ]))

    # 8-9. Standalone Azure traffic so identity + telecom show up in Live Activity at a healthy rate
    # (payments otherwise dominates because it has the most tool steps). These have no cross-cloud
    # precondition (check_fraud_score/verify/lookup/change_plan), so they ALLOW on their own.
    seqs.append(Sequence("identity_checks", [
        Step("azure", "acme-identity-agent", "check_fraud_score", {"key": f"txn-{rng.randint(0, 9999)}"}, "score this transaction", "ALLOW"),
        Step("azure", "acme-identity-agent", "verify_identity", {"subject_id": acct()}, "verify this customer", "ALLOW"),
    ]))
    m1, _ = linked()
    m2, _ = linked()
    seqs.append(Sequence("telecom_support", [
        Step("azure", "acme-telecom-agent", "lookup_subscriber", {"msisdn": m1}, "what's my plan?", "ALLOW"),
        Step("azure", "acme-telecom-agent", "change_plan", {"msisdn": m2, "new_plan": "postpaid-plus"}, "upgrade my plan", "ALLOW"),
    ]))

    # 10-11. Real injection attacks routed through the AZURE agents too, so the attack corpus
    # exercises all three agents/clouds (not just payments). The prompt is the `user_input`; the
    # controller's sigma/ML detects it and DENYs regardless of which agent/tool carries it.
    seqs.append(Sequence("injection_identity", [
        Step("azure", "acme-identity-agent", "check_fraud_score", {"key": f"txn-{rng.randint(0, 9999)}"}, rng.choice(attacks), "DENY"),
    ]))
    seqs.append(Sequence("injection_telecom", [
        Step("azure", "acme-telecom-agent", "lookup_subscriber", {"msisdn": linked()[0]}, rng.choice(attacks), "DENY"),
    ]))

    # 12. Real-fraud cross-cloud block: a subject the IEEE-CIS data flags HIGH fraud fails identity
    # verification at the controller (high_fraud_identity_block) — so it never enters tool_history —
    # and the refund in the SAME session is then DENIED by the cross-cloud precondition. Real data →
    # a real Sentra DENY → contained across clouds.
    hf = rng.choice(_HIGH_FRAUD_ACCTS)
    seqs.append(Sequence("high_fraud_identity_block", [
        Step("azure", "acme-identity-agent", "verify_identity", {"subject_id": hf}, "verify this customer", "DENY"),
        Step("aws", "acme-payments-agent", "process_refund", {"account_id": hf, "amount": 200.0}, "refund my order", "DENY"),
    ]))

    # 13+. Extra LEGIT volume so the live feed looks like a real SOC stream — mostly allowed traffic
    # with occasional attacks — instead of being deny-dominated (the bursts/attacks above are
    # deliberately heavy on payments). Realistic ALLOW:DENY balance across all three agents.
    # Kept at 2× so the per-tick step count stays well within the Lambda's 120s budget.
    for _ in range(2):
        a = acct()
        seqs.append(Sequence("legit_read", [
            Step("aws", "acme-payments-agent", "lookup_account", {"account_id": a}, "check my balance", "ALLOW"),
            Step("aws", "acme-payments-agent", "get_transactions", {"account_id": a, "limit": 5}, "recent activity", "ALLOW"),
        ]))
        b = acct()
        seqs.append(Sequence("legit_refund", [
            Step("azure", "acme-identity-agent", "verify_identity", {"subject_id": b}, "verify me", "ALLOW"),
            Step("aws", "acme-payments-agent", "process_refund", {"account_id": b, "amount": 75.0}, "refund my $75", "ALLOW"),
        ]))
        m1, _ = linked()
        seqs.append(Sequence("legit_telecom", [
            Step("azure", "acme-telecom-agent", "lookup_subscriber", {"msisdn": m1}, "what's my plan?", "ALLOW"),
        ]))
        seqs.append(Sequence("legit_identity", [
            Step("azure", "acme-identity-agent", "check_fraud_score", {"key": f"txn-{rng.randint(0, 9999)}"}, "score this txn", "ALLOW"),
        ]))

    rng.shuffle(seqs)
    return seqs


def run(sequences: List[Sequence], invoke: Invoker) -> Dict[str, int]:
    """Run sequences; return a tally. Honesty-checks expected vs. actual (WS-15 lesson)."""
    tally = {"ALLOW": 0, "DENY": 0, "ERROR": 0, "mismatch": 0}
    for seq in sequences:
        for i, step in enumerate(seq.steps):
            rid = f"req-{seq.session_id}-{i}"
            try:
                status, body = invoke(step.cloud, step.tool, step.params, seq.session_id, step.user_input, rid)
            except Exception as exc:  # noqa: BLE001 — a transport failure shouldn't kill the loop
                tally["ERROR"] += 1
                print(f"  [{seq.name}] {step.tool} ERROR: {exc}")
                continue
            decision = "ALLOW" if status == 200 else "DENY"
            tally[decision] += 1
            flag = "" if decision == step.expect else "  ⚠ MISMATCH"
            if flag:
                tally["mismatch"] += 1
            reason = body.get("reason", "") if isinstance(body, dict) else ""
            print(f"  [{seq.name}] {step.cloud}:{step.tool} -> {decision} {reason}{flag}")
    return tally


# --------------------------------------------------------------------------- live invoker
class LiveInvoker:
    """Drives the deployed agents: Bedrock Lambda invoke (aws) + HTTP POST (azure)."""

    def __init__(self) -> None:
        self.payments_lambda = os.environ.get("PAYMENTS_LAMBDA_NAME", "acme-payments-agent-tools")
        self.identity_url = os.environ.get("IDENTITY_FUNC_URL", "")      # …/api/tool/{tool_name}
        self.telecom_url = os.environ.get("TELECOM_FUNC_URL", "")
        self.region = os.environ.get("AWS_REGION", "us-east-1")
        self.profile = os.environ.get("AWS_PROFILE", "sentra")

    def __call__(self, cloud, tool, params, session_id, user_input, request_id):
        if cloud == "aws":
            return self._aws(tool, params, session_id, user_input, request_id)
        url = self.identity_url if "identity" in self._agent_for(tool) else self.telecom_url
        return self._azure(url, tool, params, session_id, user_input, request_id)

    @staticmethod
    def _agent_for(tool: str) -> str:
        return "identity" if tool in ("verify_identity", "check_fraud_score") else "telecom"

    def _aws(self, tool, params, session_id, user_input, request_id):
        import boto3

        event = {
            "apiPath": f"/{tool}", "httpMethod": "POST", "actionGroup": "payments_tools",
            "inputText": user_input, "sessionId": session_id,
            "sessionAttributes": {"sentra_request_id": request_id} if request_id else {},
            "requestBody": {"content": {"application/json": {"properties":
                [{"name": k, "value": str(v)} for k, v in params.items()]}}},
        }
        # Use the default credential chain: the Lambda execution role in AWS, or AWS_PROFILE locally.
        # (A hardcoded profile_name='sentra' fails inside Lambda, which has no named profiles.)
        if self.profile and os.environ.get("AWS_PROFILE"):
            session = boto3.Session(profile_name=self.profile, region_name=self.region)
        else:
            session = boto3.Session(region_name=self.region)
        client = session.client("lambda")
        resp = client.invoke(FunctionName=self.payments_lambda, Payload=json.dumps(event).encode())
        out = json.loads(resp["Payload"].read())
        status = out.get("response", {}).get("httpStatusCode", 500)
        body = json.loads(out["response"]["responseBody"]["application/json"]["body"])
        return status, body

    def _azure(self, url, tool, params, session_id, user_input, request_id):
        import urllib.error
        import urllib.request

        target = url.replace("{tool_name}", tool)
        payload = json.dumps({"params": params, "session_id": session_id,
                              "user_input": user_input, "request_id": request_id}).encode()
        req = urllib.request.Request(target, data=payload, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=35) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:  # 403 DENY comes back as HTTPError
            try:
                return e.code, json.loads(e.read())
            except Exception:
                return e.code, {"reason": f"HTTP {e.code}"}


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Demo traffic generator")
    ap.add_argument("--live", action="store_true", help="Invoke the deployed agents (needs endpoints)")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    seqs = build_sequences(args.seed)
    print(f"Built {len(seqs)} sequences ({sum(len(s.steps) for s in seqs)} steps).")
    if not args.live:
        for s in seqs:
            print(f"  {s.name}: " + " -> ".join(f"{st.cloud}:{st.tool}[{st.expect}]" for st in s.steps))
        print("\n(dry plan — pass --live with PAYMENTS_LAMBDA_NAME / IDENTITY_FUNC_URL / TELECOM_FUNC_URL set)")
        return 0
    tally = run(seqs, LiveInvoker())
    print(f"\nTally: {tally}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
