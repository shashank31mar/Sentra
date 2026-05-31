"""
Azure Function tool_interceptor — Workstream 15 M3, Task 3.2.

Mirrors lambda/bedrock_agent_actions/index.py:validate_with_sentra().

Architecture (LLD 15 §2.2):
    Azure AI Foundry Agent
              | (tool call: verify_image_authenticity, check_fraud_score)
              v
    THIS Function — POST /api/tool/{tool_name}
              |
              | 1. Translate to Sentra ValidationRequest
              | 2. POST /v1/validate via AWS API Gateway (WS16 fix)
              | 3. On DENY -> return 403 to Foundry
              | 4. On ALLOW -> execute the mock tool, return result
              v
    Sentra Security Controller (AWS)

App settings consumed (set by Bicep, see infrastructure/azure/infra/modules/function_app.bicep):
    SENTRA_API_ENDPOINT  - https://iw3limi4k7.execute-api.us-east-1.amazonaws.com/prod/v1/validate
    SENTRA_API_KEY       - resolved via @Microsoft.KeyVault(...) at cold start
    SENTRA_PLATFORM      - "azure_foundry"
    SENTRA_CLOUD_REGION  - "centralus"
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone

import urllib.error
import urllib.request

import azure.functions as func

# -----------------------------------------------------------------------------
# Module-level cache for cold-start cost (mirrors _api_key_cache in Bedrock Lambda)
# -----------------------------------------------------------------------------
_sentra_endpoint = os.environ.get("SENTRA_API_ENDPOINT", "")
_sentra_api_key = os.environ.get("SENTRA_API_KEY", "")
_sentra_platform = os.environ.get("SENTRA_PLATFORM", "azure_foundry")
_sentra_cloud_region = os.environ.get("SENTRA_CLOUD_REGION", "centralus")

# Fail loudly at import time if config is missing — the Function will return 500
# on every request rather than appear healthy and silently DENY.
if not _sentra_endpoint or not _sentra_api_key:
    logging.error(
        "Missing SENTRA_API_ENDPOINT or SENTRA_API_KEY app settings. "
        "Check Bicep wiring + Key Vault secret seeding."
    )

# -----------------------------------------------------------------------------
# Sentra agent identity for the Foundry side of the cross-cloud demo.
# Matches the policy entry in config/agent_policies.yaml (LLD 15 §4.1).
# -----------------------------------------------------------------------------
AGENT_ID = "azure-verification-agent"

# -----------------------------------------------------------------------------
# Mock tool implementations — real verification is out of scope for the demo.
# What we're demonstrating is the SECURITY interception, not the verification
# logic itself. These deterministic responses are enough to drive S3 + S4
# scenarios end-to-end (LLD 15 §9).
# -----------------------------------------------------------------------------
def execute_verify_image_authenticity(params: dict) -> dict:
    image_url = params.get("image_url", "")
    expected = params.get("expected_subject", "")
    # Deterministic: URL containing "fake" returns inauthentic.
    is_authentic = "fake" not in image_url.lower()
    return {
        "authentic": is_authentic,
        "confidence": 0.94 if is_authentic else 0.12,
        "expected_subject": expected,
        "image_url": image_url,
    }


def execute_check_fraud_score(params: dict) -> dict:
    tx_id = params.get("transaction_id", "")
    # Deterministic: tx_id containing "high" returns high fraud score.
    high_risk = "high" in tx_id.lower()
    return {
        "transaction_id": tx_id,
        "score": 87 if high_risk else 12,
        "factors": ["velocity_high", "location_anomaly"] if high_risk else [],
    }


TOOL_DISPATCH = {
    "verify_image_authenticity": execute_verify_image_authenticity,
    "check_fraud_score": execute_check_fraud_score,
}


# -----------------------------------------------------------------------------
# Sentra validation (parallel to validate_with_sentra in the Bedrock Lambda)
# -----------------------------------------------------------------------------
def validate_with_sentra(
    tool_name: str,
    tool_params: dict,
    user_input: str,
    session_id: str,
    supplied_request_id: str = None,
) -> dict:
    """POST a ValidationRequest to the Sentra controller via AWS API Gateway.

    Returns the controller's JSON response on 200, fail-secure DENY otherwise.
    Mirrors the WRITE-vs-READ operation_type heuristic from the Bedrock Lambda.

    Workstream 17 / LLD 17 §9.1.5 — when the AzureConnector supplies a
    `request_id` in the HTTP body, forward it to /v1/validate so every signal
    Sentra emits correlates to one logical agent invocation. Falls back to a
    Function-generated UUID for callers that don't thread it.
    """
    request_id = supplied_request_id or f"azure-{uuid.uuid4().hex[:12]}"
    payload = {
        "request_id": request_id,
        "session_id": session_id,
        "agent_id": AGENT_ID,
        "tool_name": tool_name,
        "tool_params": tool_params,
        "user_input": user_input,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "operation_type": "WRITE" if any(w in tool_name for w in ("refund", "modify", "delete")) else "READ",
        "platform": _sentra_platform,
        "cloud_region": _sentra_cloud_region,
    }
    # Use urllib (stdlib) instead of requests — avoids a pip dependency that
    # B1 Linux Oryx Remote Build wasn't picking up during Workstream 15 M3
    # debug session (lesson learned 2026-05-23).
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        _sentra_endpoint,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "x-api-key": _sentra_api_key},
    )
    # Timeout sized for the worst-case cross-cloud path: Azure → AWS API Gateway
    # → VPC Link → NLB → Private ALB → ECS controller. Sigma engine compute is
    # sub-second, but Lambda + ALB cold-starts and Hyperplane connection setup
    # have been observed at 10-15s end-to-end (see Workstream 15 M5 diagnosis
    # 2026-05-25: Sentra logged DENY 9s after Function's 5s timeout fired).
    # 30s is a comfortable margin; honors the upstream ALB idle timeout (60s).
    try:
        with urllib.request.urlopen(req, timeout=30.0) as resp:
            status = resp.status
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        # Server returned a non-2xx (e.g., 403 from Sentra DENY at the API Gateway layer).
        # Treat all of these as DENY-by-controller — the validator already decided.
        raw = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
        logging.error("Sentra validation HTTP %s: %s", e.code, raw[:200])
        return {"decision": "DENY", "reason": f"Validation service HTTP {e.code}"}
    except urllib.error.URLError as e:
        logging.error("Sentra validation network error: %s", e)
        return {"decision": "DENY", "reason": f"Validation service unreachable: {e}"}

    if status == 200:
        try:
            result = json.loads(raw)
        except ValueError:
            logging.error("Sentra returned 200 with non-JSON body: %s", raw[:200])
            return {"decision": "DENY", "reason": "Validation service returned invalid JSON"}
        logging.info("Sentra validation: decision=%s session=%s", result.get("decision"), session_id)
        return result

    logging.error("Sentra validation HTTP %s: %s", status, raw[:200])
    return {"decision": "DENY", "reason": f"Validation service HTTP {status}"}


# -----------------------------------------------------------------------------
# Function App entry point (v2 programming model)
# -----------------------------------------------------------------------------
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


@app.route(route="tool/{tool_name}", methods=["POST"])
def tool_call(req: func.HttpRequest) -> func.HttpResponse:
    """Route: POST /api/tool/{tool_name}

    Body (JSON):
        {
            "params": {...},          # tool-specific arguments
            "session_id": "...",      # session this call belongs to
            "user_input": "..."       # original user prompt (for audit)
        }

    Response on ALLOW (200):
        {"decision": "ALLOW", "tool_name": "...", "result": {...}, "validation": {...}}

    Response on DENY (403):
        {"decision": "DENY", "reason": "...", "validation": {...}}
    """
    tool_name = req.route_params.get("tool_name", "")

    if tool_name not in TOOL_DISPATCH:
        return _json_response(404, {"error": f"unknown tool: {tool_name}"})

    try:
        body = req.get_json()
    except ValueError:
        return _json_response(400, {"error": "request body is not valid JSON"})

    tool_params = body.get("params", {})
    session_id = body.get("session_id", "")
    user_input = body.get("user_input", "")
    # Workstream 17 / LLD 17 §9.1.5 — accept caller-supplied request_id so
    # every signal correlates to one logical agent invocation. Falls back to
    # Function-generated UUID inside validate_with_sentra() when omitted
    # (preserves behavior for older callers).
    supplied_request_id = body.get("request_id")

    if not session_id:
        return _json_response(400, {"error": "session_id is required"})

    # 1. Validate with Sentra
    validation = validate_with_sentra(
        tool_name, tool_params, user_input, session_id, supplied_request_id
    )

    if validation.get("decision") != "ALLOW":
        return _json_response(403, {
            "decision": "DENY",
            "reason": validation.get("reason", "denied by Sentra"),
            "validation": validation,
        })

    # 2. ALLOW -> execute the tool
    try:
        result = TOOL_DISPATCH[tool_name](tool_params)
    except Exception as e:
        logging.exception("Tool execution failed for %s", tool_name)
        return _json_response(500, {"error": f"tool execution failed: {e}"})

    return _json_response(200, {
        "decision": "ALLOW",
        "tool_name": tool_name,
        "result": result,
        "validation": validation,
    })


@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    """Liveness probe — does NOT touch Sentra; just confirms the Function is up
    and the SENTRA_* config is non-empty. Used by `azd up` smoke step + Foundry agent debugging."""
    return _json_response(200, {
        "status": "healthy",
        "platform": _sentra_platform,
        "cloud_region": _sentra_cloud_region,
        "tools_registered": list(TOOL_DISPATCH.keys()),
        "config_present": {
            "SENTRA_API_ENDPOINT": bool(_sentra_endpoint),
            "SENTRA_API_KEY": bool(_sentra_api_key),
        },
    })


def _json_response(status: int, body: dict) -> func.HttpResponse:
    return func.HttpResponse(
        body=json.dumps(body),
        status_code=status,
        mimetype="application/json",
    )
