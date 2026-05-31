"""Translation helpers for AWS Bedrock event format <-> cross-cloud normalized models."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


def parse_guardrail_trace(guardrail_trace: dict) -> Optional[dict[str, Any]]:
    """Extract a Sentra validation result from a Bedrock guardrail trace.

    Bedrock guardrail trace shape:
        {
          "action": "INTERVENED" | "NONE",
          "inputAssessments": [...],
          "outputAssessments": [...],
          "customApiTrace": {"request": {...}, "response": {...}}
        }
    """
    if not guardrail_trace:
        return None

    try:
        action = guardrail_trace.get("action")

        custom_api_trace = guardrail_trace.get("customApiTrace")
        if custom_api_trace and "response" in custom_api_trace:
            sentra_response = custom_api_trace["response"]
            if isinstance(sentra_response, str):
                try:
                    sentra_response = json.loads(sentra_response)
                except json.JSONDecodeError:
                    # Issue #4 (WS15 M1 review): previously returned None, which
                    # downstream consumers (audit_logger, dashboard) treated as
                    # "no validation occurred" — strictly worse than fail-secure.
                    # A guardrail trace whose Sentra response failed to parse is
                    # ambiguous; surface that explicitly so callers can decide
                    # (most will choose DENY-on-UNKNOWN at the policy layer).
                    logger.warning(
                        "Could not parse Sentra response as JSON: %s", sentra_response
                    )
                    return {
                        "decision": "UNKNOWN",
                        "reason": "Sentra response present but unparseable",
                        "guardrail_action": action,
                        "raw_response": sentra_response,
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                    }

            return {
                "decision": sentra_response.get("decision", "UNKNOWN"),
                "reason": sentra_response.get("reason", "No reason provided"),
                "request_id": sentra_response.get("request_id"),
                "trust_score": sentra_response.get("trust_score"),
                "threat_type": sentra_response.get("threat_type"),
                "violation_type": sentra_response.get("violation_type"),
                "violated_policy": sentra_response.get("violated_policy"),
                "guardrail_action": action,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }

        for assessment in guardrail_trace.get("inputAssessments", []):
            if assessment.get("action") == "BLOCKED":
                return {
                    "decision": "DENY",
                    "reason": "Blocked by Bedrock guardrail content filter",
                    "guardrail_action": action,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                }

        return {
            "decision": "ALLOW",
            "reason": "No guardrail intervention",
            "guardrail_action": action,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Error parsing guardrail trace: %s", exc)
        return None
