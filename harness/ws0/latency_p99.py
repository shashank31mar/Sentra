#!/usr/bin/env python3
"""WS-0 Test-2 (M0-3 / metric 6b): escalated-path p99 over the REAL WAN + real Bedrock.

Drives the DEPLOYED prod controller (sentra-mvp-api, us-east-1) over the public
internet from this host — the customer-representative WAN position (§3.3: never
co-located). Requests carry a valid ES256 agent JWT (identity=enforce) so they pass
the identity gate and reach the ML classifier (real Bedrock, never mocked — §6b).

For each request: time the full WAN POST→response, record server-reported latency_ms,
and classify whether it reached the deep (ML) tier — an ALLOW with server latency in
the ~Bedrock band is escalated; a fast deterministic DENY (identity/policy/sigma) is
not. Report p50/p95/p99 of the ESCALATED subset at ≥2 concurrency bands (§6b).

Env: AWS_PROFILE=sentra (to read the api key + mint JWT); .probe_identity.json present.
NEVER mocks Bedrock. Writes results/latency_<ts>.json.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

import urllib.request
import urllib.error

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
RESULTS = HERE / "results"
RESULTS.mkdir(exist_ok=True)
sys.path.insert(0, str(REPO / "demo-agents" / "sdk" / "aegion-guard-python" / "src"))

import jwt as _jwt  # noqa: E402  PyJWT[crypto]

URL = "https://iw3limi4k7.execute-api.us-east-1.amazonaws.com/prod/v1/validate"
IDENT = json.loads((HERE / ".probe_identity.json").read_text())

# Escalate-class request templates: benign-looking inputs on tools NOT gated by the
# cross-cloud precondition (get_transactions/lookup_account) so they pass the
# deterministic frontier and REACH the ML classifier (the escalated Bedrock leg).
# Varied user_input so the model actually runs (not a trivial cache hit).
_INPUTS = [
    "show recent transactions for my account",
    "list the last five transactions on this account",
    "what were my purchases this month",
    "summarize account activity for the quarter",
    "pull the transaction history for reconciliation",
    "review recent account movements for anomalies",
    "fetch statement lines for the past 30 days",
    "display pending and posted transactions",
]


def _mint_jwt() -> str:
    now = int(time.time())
    tok = _jwt.encode(
        {"iss": "aegion-guard", "aud": "sentra-controller",
         "sub": IDENT["agent_id"], "tid": IDENT["tenant_id"],
         "iat": now, "exp": now + 900},
        IDENT["private_key"], algorithm="ES256", headers={"kid": IDENT["kid"]})
    return tok if isinstance(tok, str) else tok.decode()


def _one_call(api_key: str, jwt_token: str, i: int) -> dict:
    """One blocking WAN POST (run in a thread). Returns timing + tier classification."""
    body = json.dumps({
        "request_id": f"ws0-lat-{i}",
        "session_id": f"ws0-lat-s{i % 16}",
        "agent_id": IDENT["agent_id"],
        "tool_name": "get_transactions",
        "tool_params": {"account_id": f"a{i % 50}"},
        "user_input": _INPUTS[i % len(_INPUTS)] + f" (req {i})",
        "timestamp": "2026-07-02T00:00:00.000Z",
        "operation_type": "READ",
    }).encode()
    req = urllib.request.Request(URL, data=body, method="POST", headers={
        "content-type": "application/json", "x-api-key": api_key,
        "authorization": f"Bearer {jwt_token}"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode())
            http = resp.status
    except urllib.error.HTTPError as e:
        payload = {"decision": "HTTP_ERR", "reason": str(e.code)}
        http = e.code
    except Exception as e:  # noqa: BLE001
        payload = {"decision": "ERR", "reason": f"{type(e).__name__}"}
        http = 0
    e2e_ms = (time.monotonic() - t0) * 1000.0
    server_ms = float(payload.get("latency_ms", 0.0) or 0.0)
    decision = payload.get("decision", "?")
    reason = payload.get("reason", "")
    # Escalated = reached the ML tier. Heuristic: an ALLOW (passed all deterministic
    # gates → ML ran) OR a DENY whose server latency is in the Bedrock band (>300ms).
    # Fast deterministic denies (identity/policy/sigma) have server_ms well under that.
    reached_ml = (decision == "ALLOW") or (server_ms >= 300.0)
    return {"i": i, "http": http, "decision": decision, "reason": reason,
            "e2e_ms": round(e2e_ms, 1), "server_ms": round(server_ms, 1),
            "reached_ml": reached_ml}


async def run_band(api_key: str, jwt_token: str, n: int, concurrency: int) -> dict:
    sem = asyncio.Semaphore(concurrency)

    async def one(i: int):
        async with sem:
            return await asyncio.to_thread(_one_call, api_key, jwt_token, i)

    rows = await asyncio.gather(*[one(i) for i in range(n)])
    esc = [r for r in rows if r["reached_ml"]]
    e2e = sorted(r["e2e_ms"] for r in esc)
    srv = sorted(r["server_ms"] for r in esc)

    def pct(data, p):
        if not data:
            return None
        k = max(0, min(len(data) - 1, int(round((p / 100) * (len(data) - 1)))))
        return data[k]

    return {
        "concurrency": concurrency,
        "requests_sent": n,
        "reached_ml_count": len(esc),
        "non_escalated_count": len(rows) - len(esc),
        "e2e_wan_ms": {"p50": pct(e2e, 50), "p95": pct(e2e, 95), "p99": pct(e2e, 99),
                       "max": e2e[-1] if e2e else None},
        "server_ms": {"p50": pct(srv, 50), "p95": pct(srv, 95), "p99": pct(srv, 99)},
        "decisions": {d: sum(1 for r in rows if r["decision"] == d)
                      for d in set(r["decision"] for r in rows)},
        "rows": rows,
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-band", type=int, default=150, help="requests per concurrency band (≥100 escalate floor, §6b)")
    args = ap.parse_args()

    import boto3
    api_key = boto3.Session(profile_name="sentra", region_name="us-east-1").client(
        "apigateway").get_api_keys(nameQuery="sentra-demo-key", includeValues=True)["items"][0]["value"]
    jwt_token = _mint_jwt()

    # Pre-registered bands (PRE_REGISTERED_THRESHOLDS.md): steady=5, burst=20.
    out = {
        "wan_position": "local dev host → public internet → dev/prod PDP us-east-1 (NOT co-located, §3.3)",
        "bedrock": "real aegionai-ml-classifier AIP (Haiku 4.5 → Sonnet 4.6), never mocked",
        "agent": IDENT["agent_id"],
        "run_started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "bands": [],
    }
    for concurrency in (5, 20):
        print(f"[band c={concurrency}] sending {args.per_band} requests over WAN...", flush=True)
        band = await run_band(api_key, jwt_token, args.per_band, concurrency)
        summary = {k: v for k, v in band.items() if k != "rows"}
        print(json.dumps(summary, indent=2), flush=True)
        out["bands"].append(band)

    ts = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    outpath = RESULTS / f"latency_{ts}.json"
    outpath.write_text(json.dumps(out, indent=2))
    print(f"\nFull results → {outpath.relative_to(REPO)}")
    # load-sensitivity slope (§6b: report the slope, not one point)
    if len(out["bands"]) == 2:
        b1, b2 = out["bands"]
        p99_1 = b1["e2e_wan_ms"]["p99"]
        p99_2 = b2["e2e_wan_ms"]["p99"]
        if p99_1 and p99_2:
            print(f"LOAD-SENSITIVITY: e2e p99 {p99_1}ms @c5 → {p99_2}ms @c20 "
                  f"(slope {round((p99_2-p99_1)/15, 1)} ms/concurrent)")


if __name__ == "__main__":
    asyncio.run(main())
