"""Azure Telecom agent — tool logic (LLD 22 §6.1.1, §6.4).

A telecom customer-support / account-management agent. The security relevance is **SIM-swap and
port-out** — the classic account-takeover fraud vectors. Scenario B1: `reset_sim` / `port_out_number`
are DENIED unless `verify_identity` (the Azure identity agent) ran for the same session within 300s —
i.e. an unauthenticated SIM swap is blocked by the cross-cloud precondition (core `context_validator`).

Like the identity agent, tools are **pure** so the Azure Function package stays stdlib-only — no
DDB/boto3/Faker at runtime. There is no `acme-subscribers` datastore in this cut (Kiro review #3):
the subscriber profile (plan, tenure, monthly charges, churn risk) comes from the **real IBM Telco
churn dataset** — a compact snapshot derived offline by `data-pipelines/build_telco_subscribers.py`,
bundled into the package, and looked up via the msisdn (`common.realdata.subscriber_record`; falls
back to a msisdn-hash profile if absent). The account↔subscriber bridge for the cross-cloud narrative
lives on `acme-bank-accounts.linked_msisdn` (from `datagen`).

Separate from `function_app.py` so it's unit-testable without `azure.functions`.
"""
from __future__ import annotations

import hashlib
import pathlib
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # demo-agents/

from aegion_guard import AegionGuard, ToolDenied, from_azure_request  # noqa: E402
from common.realdata import subscriber_record  # noqa: E402  (pure; stdlib json lookup)

AGENT_ID = "acme-telecom-agent"
_PLANS = ("prepaid-basic", "postpaid-standard", "postpaid-plus", "fiber-1gbps", "family-share")

guard = AegionGuard(agent_id=AGENT_ID, platform="azure_foundry", cloud_region="centralus", timeout_s=30)


def _profile(msisdn: str) -> Dict[str, Any]:
    """Subscriber profile for a msisdn.

    Plan / tenure / charges / churn risk come from the real IBM Telco churn dataset when the derived
    snapshot is bundled (see common/realdata.py + data-pipelines). Falls back to a deterministic
    msisdn-hash profile if the snapshot isn't present (keeps the Function build-free + never fails).
    The ``sim_id`` is always msisdn-derived (it's just a stable identifier, not dataset-sourced).
    """
    h = hashlib.sha256(msisdn.encode("utf-8")).hexdigest()
    sim_id = f"SIM{int(h[2:16], 16)}"
    record = subscriber_record(msisdn)
    if record is not None:
        return {
            "msisdn": msisdn,
            "plan": record["plan"],
            "sim_id": sim_id,
            "tenure_months": record["tenure_months"],
            "monthly_charges": record["monthly_charges"],
            "churn_risk": record["churn_risk"],
            "churn_band": record["churn_band"],
            "source": "ibm_telco",
        }
    return {
        "msisdn": msisdn,
        "plan": _PLANS[int(h[:2], 16) % len(_PLANS)],
        "sim_id": sim_id,
        "tenure_months": int(h[16:18], 16) % 72 + 1,
        "source": "synthetic",
    }


@guard.tool(operation_type="READ")
async def lookup_subscriber(msisdn: str) -> Dict[str, Any]:
    return _profile(msisdn)


@guard.tool(operation_type="WRITE")
async def change_plan(msisdn: str, new_plan: str) -> Dict[str, Any]:
    return {"success": True, "msisdn": msisdn, "plan": new_plan}


@guard.tool(operation_type="WRITE")
async def reset_sim(msisdn: str, new_sim_id: str) -> Dict[str, Any]:
    return {"success": True, "msisdn": msisdn, "sim_id": new_sim_id,
            "changed_at": datetime.now(timezone.utc).isoformat()}


@guard.tool(operation_type="WRITE")
async def port_out_number(msisdn: str, target_carrier: str) -> Dict[str, Any]:
    return {"success": True, "msisdn": msisdn, "target_carrier": target_carrier,
            "port_ref": f"port-{uuid.uuid4().hex[:10]}"}


TOOLS = {
    "lookup_subscriber": lookup_subscriber,
    "change_plan": change_plan,
    "reset_sim": reset_sim,
    "port_out_number": port_out_number,
}


async def dispatch(req: Any) -> Tuple[int, Dict[str, Any]]:
    ctx = from_azure_request(req)
    tool_name = ctx["tool_name"]
    if tool_name not in TOOLS:
        return 404, {"error": f"unknown tool: {tool_name}"}
    if not ctx["session_id"] or ctx["session_id"] == "unknown":
        return 400, {"error": "session_id is required"}
    try:
        with guard.session(ctx["session_id"], ctx["user_input"], request_id=ctx["request_id"]):
            result = await TOOLS[tool_name](**ctx["params"])
        return 200, {"decision": "ALLOW", "tool_name": tool_name, "result": result}
    except ToolDenied as denied:
        return 403, {"decision": "DENY", "reason": denied.reason, "threat_type": denied.threat_type}
    except (TypeError, ValueError) as bad:
        return 400, {"error": f"bad tool params: {bad}"}
