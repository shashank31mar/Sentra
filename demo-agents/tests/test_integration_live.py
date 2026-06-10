"""Gated live integration test (WS-23 / LLD 22 §12.1).

Runs the traffic generator against the **deployed** agents and asserts Scenario A / B1 / injection /
refund-limit behave correctly end to end through the real Sentra controller. This is the only test
that needs the live stack — it is the demo's counterpart to the SDK's own contract test.

    RUN_INTEGRATION=1 \
    PAYMENTS_LAMBDA_NAME=acme-payments-agent-tools \
    IDENTITY_FUNC_URL=https://<id>.azurewebsites.net/api/tool/{tool_name} \
    TELECOM_FUNC_URL=https://<tel>.azurewebsites.net/api/tool/{tool_name} \
    pytest demo-agents/tests/test_integration_live.py -q
"""
from __future__ import annotations

import os
import uuid

import pytest

from generator import LiveInvoker

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1",
    reason="live stack required; set RUN_INTEGRATION=1 and the agent endpoints",
)


@pytest.fixture
def invoke():
    return LiveInvoker()


def test_scenarioA_cross_cloud(invoke):
    sid = f"it-A-{uuid.uuid4().hex[:8]}"
    # Refund without verify -> DENY.
    s, b = invoke("aws", "process_refund", {"account_id": "acct-1000", "amount": 50}, sid + "-x", "refund", None)
    assert s != 200 and "dependency" in b.get("reason", "").lower()
    # Verify then refund (same session) -> ALLOW.
    invoke("azure", "verify_identity", {"subject_id": "acct-1000"}, sid, "verify", None)
    s, _ = invoke("aws", "process_refund", {"account_id": "acct-1000", "amount": 50}, sid, "refund", None)
    assert s == 200


def test_scenarioB1_sim_swap(invoke):
    sid = f"it-B-{uuid.uuid4().hex[:8]}"
    s, b = invoke("azure", "reset_sim", {"msisdn": "+12025550001", "new_sim_id": "SIM1"}, sid, "swap", None)
    assert s != 200 and "dependency" in b.get("reason", "").lower()


def test_injection_denied(invoke):
    sid = f"it-inj-{uuid.uuid4().hex[:8]}"
    s, _ = invoke("aws", "get_transactions", {"account_id": "acct-1000"}, sid,
                  "list; DROP TABLE accounts;--", None)
    assert s != 200
