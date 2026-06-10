"""Azure Identity agent — tool logic (LLD 22 §6.1.1).

Kept separate from ``function_app.py`` so it is unit-testable **without** the ``azure.functions``
package. The Azure wrapper just adapts the HTTP request and calls :func:`dispatch`.

Tools are **pure** (no DynamoDB, no Faker): `verify_identity` always "passes" — the point of
Scenario A/B1 is that the verification *happened* in-session, which the cross-cloud precondition
checks — and `check_fraud_score`/`verify_identity` return scores grounded in the **real IEEE-CIS
fraud dataset** (a compact snapshot derived offline by `data-pipelines/build_ieee_cis_scores.py` and
bundled into the package; `common.store.fraud_score` → `common.realdata`). The lookup is stdlib-only
JSON, so no Oryx build is needed; it falls back to a deterministic hash if the snapshot is absent.

Cross-cloud: this is the Azure half. Its `timeout_s=30` accounts for the Azure->AWS cold path
(LLD 23 §7 / WS-15).
"""
from __future__ import annotations

import pathlib
import sys
from typing import Any, Dict, Optional, Tuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # demo-agents/

from aegion_guard import AegionGuard, ToolDenied, from_azure_request  # noqa: E402
from common.store import fraud_score as lookup_fraud  # noqa: E402  (real IEEE-CIS lookup; stdlib)

AGENT_ID = "acme-identity-agent"

guard = AegionGuard(agent_id=AGENT_ID, platform="azure_foundry", cloud_region="centralus", timeout_s=30)


@guard.tool(operation_type="READ")
async def verify_identity(
    subject_id: str,
    method: Optional[str] = None,
    fraud_risk: Optional[str] = None,
    fraud_score: Optional[float] = None,
) -> Dict[str, Any]:
    # `fraud_risk`/`fraud_score` are forwarded into /v1/validate (injected by dispatch from the real
    # IEEE-CIS data) so the controller can refuse verification for high-risk subjects BEFORE this
    # body runs. If we got here, Sentra ALLOWED it (risk != high) → verified is True. The high-risk
    # path is denied upstream (policy_engine high_fraud_identity_block) and never reaches here.
    score = fraud_score if fraud_score is not None else lookup_fraud(subject_id)["fraud_score"]
    return {
        "verified": fraud_risk != "high",
        "subject_id": subject_id,
        "method": method or "knowledge_based",
        "identity_score": int(round((1.0 - score) * 100)),
        "fraud_risk": fraud_risk,
    }


@guard.tool(operation_type="READ")
async def check_fraud_score(key: str) -> Dict[str, Any]:
    return {"key": key, **lookup_fraud(key)}


TOOLS = {"verify_identity": verify_identity, "check_fraud_score": check_fraud_score}


async def dispatch(req: Any) -> Tuple[int, Dict[str, Any]]:
    """Validate + run a tool from an Azure request shape. Returns (http_status, body)."""
    ctx = from_azure_request(req)
    tool_name = ctx["tool_name"]
    if tool_name not in TOOLS:
        return 404, {"error": f"unknown tool: {tool_name}"}
    if not ctx["session_id"] or ctx["session_id"] == "unknown":
        return 400, {"error": "session_id is required"}
    # Enrich verify_identity with the subject's REAL IEEE-CIS risk so the controller sees it in
    # tool_params and can refuse verification for high-risk subjects (high_fraud_identity_block).
    if tool_name == "verify_identity" and "fraud_risk" not in ctx["params"]:
        subject = ctx["params"].get("subject_id")
        if subject:
            fs = lookup_fraud(subject)
            ctx["params"]["fraud_risk"] = fs["risk"]
            ctx["params"]["fraud_score"] = fs["fraud_score"]
    try:
        with guard.session(ctx["session_id"], ctx["user_input"], request_id=ctx["request_id"]):
            result = await TOOLS[tool_name](**ctx["params"])
        return 200, {"decision": "ALLOW", "tool_name": tool_name, "result": result}
    except ToolDenied as denied:
        return 403, {"decision": "DENY", "reason": denied.reason, "threat_type": denied.threat_type}
    except (TypeError, ValueError) as bad:
        return 400, {"error": f"bad tool params: {bad}"}
