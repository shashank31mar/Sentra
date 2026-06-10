"""Offline end-to-end test of the cross-cloud demo (M7).

Runs the traffic generator's labelled sequences through the **in-process agent handlers** wired to a
shared ``FakeController``. Proves Scenario A, Scenario B1, sigma-injection, and the hardcoded refund
limit all behave as designed — with no cloud, no deployed agents.
"""
from __future__ import annotations

import asyncio
import json

from generator import build_sequences, run


def _bedrock_event(tool, params, session_id, user_input, request_id):
    return {
        "apiPath": f"/{tool}", "httpMethod": "POST", "actionGroup": "payments_tools",
        "inputText": user_input, "sessionId": session_id,
        "sessionAttributes": {"sentra_request_id": request_id} if request_id else {},
        "requestBody": {"content": {"application/json": {"properties":
            [{"name": k, "value": v} for k, v in params.items()]}}},
    }


def _local_invoker(wired):
    payments, identity, telecom = wired["payments"], wired["identity"], wired["telecom"]

    def invoke(cloud, tool, params, session_id, user_input, request_id):
        if cloud == "aws":
            out = payments.handler(_bedrock_event(tool, params, session_id, user_input, request_id))
            status = out["response"]["httpStatusCode"]
            body = json.loads(out["response"]["responseBody"]["application/json"]["body"])
            return status, body
        mod = identity if tool in ("verify_identity", "check_fraud_score") else telecom
        req = {"route_params": {"tool_name": tool},
               "body": {"params": params, "session_id": session_id,
                        "user_input": user_input, "request_id": request_id}}
        return asyncio.run(mod.dispatch(req))

    return invoke


def test_full_traffic_batch_matches_expectations(wired):
    seqs = build_sequences(seed=1)
    tally = run(seqs, _local_invoker(wired))
    # Every labelled ALLOW/DENY expectation must match the FakeController's real decision.
    assert tally["mismatch"] == 0, f"labelled expectations diverged from reality: {tally}"
    assert tally["ERROR"] == 0
    assert tally["ALLOW"] > 0 and tally["DENY"] > 0  # a realistic mix


def test_scenarioA_refund_requires_prior_verify(wired):
    invoke = _local_invoker(wired)
    # No prior verify -> DENY.
    s, b = invoke("aws", "process_refund", {"account_id": "acct-1000", "amount": 50.0}, "s1", "refund please", None)
    assert s == 403 and b["reason"] == "cross_cloud_dependency_not_met"
    # Verify (Azure) then refund (AWS) in the SAME session -> ALLOW (cross-cloud history shared).
    invoke("azure", "verify_identity", {"subject_id": "acct-1000"}, "s2", "verify me", None)
    s, b = invoke("aws", "process_refund", {"account_id": "acct-1000", "amount": 50.0}, "s2", "refund please", None)
    # AWS (Bedrock) returns the tool result directly as the response body.
    assert s == 200 and b["success"]


def test_refund_over_hardcoded_limit_denied(wired):
    invoke = _local_invoker(wired)
    invoke("azure", "verify_identity", {"subject_id": "acct-1001"}, "s3", "verify", None)
    s, b = invoke("aws", "process_refund", {"account_id": "acct-1001", "amount": 7500.0}, "s3", "refund 7500", None)
    assert s == 403 and "5000" in b["reason"]


def test_sim_swap_requires_verify(wired):
    invoke = _local_invoker(wired)
    s, b = invoke("azure", "reset_sim", {"msisdn": "+12025550001", "new_sim_id": "SIM1"}, "s4", "swap sim", None)
    assert s == 403 and b["reason"] == "cross_cloud_dependency_not_met"
    invoke("azure", "verify_identity", {"subject_id": "+12025550001"}, "s5", "verify", None)
    s, b = invoke("azure", "reset_sim", {"msisdn": "+12025550001", "new_sim_id": "SIM1"}, "s5", "swap sim", None)
    assert s == 200 and b["result"]["success"]


def test_injection_denied_by_sigma(wired):
    invoke = _local_invoker(wired)
    s, b = invoke("aws", "get_transactions", {"account_id": "acct-1000"},
                  "s6", "show txns; DROP TABLE accounts;--", None)
    assert s == 403 and b["threat_type"] == "PROMPT_INJECTION"
