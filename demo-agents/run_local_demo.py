#!/usr/bin/env python3
"""Run the whole cross-cloud demo **offline** (no AWS/Azure, no deployed controller).

Wires the three in-process agent handlers to a single ``FakeController`` (which emulates the real
Sentra decision path: sigma, refund>$5000, cross-cloud preconditions) and fires the traffic
generator's labelled sequences through them — so you can watch Scenario A, Scenario B1, injection,
and the refund limit produce a realistic ALLOW/DENY stream without any cloud.

    python demo-agents/run_local_demo.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import pathlib
import sys

DEMO = pathlib.Path(__file__).resolve().parent
os.environ.setdefault("SENTRA_API_BASE", "https://example.execute-api.us-east-1.amazonaws.com/prod")
os.environ.setdefault("SENTRA_API_KEY", "local")
os.environ.setdefault("AEGION_DEMO_BACKEND", "memory")
for _p in (DEMO, DEMO / "aws-payments-agent" / "tools", DEMO / "azure-identity-agent" / "tools",
           DEMO / "azure-telecom-agent" / "tools", DEMO / "traffic", DEMO / "tests"):
    sys.path.insert(0, str(_p))

from fake_controller import FakeController  # noqa: E402
from generator import build_sequences, run  # noqa: E402


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, DEMO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    payments = _load("aws-payments-agent/tools/lambda_handler.py", "payments_handler")
    identity = _load("azure-identity-agent/tools/identity_core.py", "identity_core_mod")
    telecom = _load("azure-telecom-agent/tools/telecom_core.py", "telecom_core_mod")
    fc = FakeController()
    for mod in (payments, identity, telecom):
        mod.guard._client.post = fc.post

    def invoke(cloud, tool, params, session_id, user_input, request_id):
        if cloud == "aws":
            event = {"apiPath": f"/{tool}", "httpMethod": "POST", "actionGroup": "payments_tools",
                     "inputText": user_input, "sessionId": session_id, "sessionAttributes": {},
                     "requestBody": {"content": {"application/json": {"properties":
                         [{"name": k, "value": v} for k, v in params.items()]}}}}
            out = payments.handler(event)
            status = out["response"]["httpStatusCode"]
            return status, json.loads(out["response"]["responseBody"]["application/json"]["body"])
        mod = identity if tool in ("verify_identity", "check_fraud_score") else telecom
        req = {"route_params": {"tool_name": tool}, "body": {"params": params,
               "session_id": session_id, "user_input": user_input, "request_id": request_id}}
        return asyncio.run(mod.dispatch(req))

    print("=== AegionAI cross-cloud demo (OFFLINE — FakeController) ===\n")
    tally = run(build_sequences(seed=1), invoke)
    print(f"\nTally: {tally}")
    print("✅ end-to-end: Scenario A + B1 + injection + refund-limit all enforced offline."
          if tally["mismatch"] == 0 else "⚠ mismatch — see above")
    return 0 if tally["mismatch"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
