"""JSON Schema for the ML classifier's structured-output tool.

LLD 19 §7.1. Bedrock Converse with tool-use enforcement guarantees the
model's response is a schema-conforming call to `emit_security_verdict`;
free-text parsing of the model output is structurally impossible.

The threat-type enum is the stable contract that scenario assertions
match against (LLD 19 §2.3) — adding/removing entries here is a
breaking change for downstream tests and dashboard rendering.
"""

from __future__ import annotations

from typing import Final


TOOL_NAME: Final[str] = "emit_security_verdict"


# Threat taxonomy — aligned with sigma rules' threat_type strings.
# MALFORMED_REQUEST is intentionally NOT in this enum (LLD 19 v0.2 §7.2);
# operational failures should ABSTAIN, not classify as a threat.
THREAT_TYPES: Final[tuple[str, ...]] = (
    "NONE",
    "PROMPT_INJECTION",
    "PII_EXPOSURE",
    "DATA_THEFT",
    "PRIVILEGE_ESCALATION",
    "JAILBREAK_ATTEMPT",
    "SYSTEM_EXTRACTION",
    "OTHER",
)


# Bedrock Converse toolConfig expects `inputSchema.json` (a JSON Schema dict).
TOOL_INPUT_SCHEMA: Final[dict] = {
    "type": "object",
    "required": ["decision", "threat_type", "confidence", "reason"],
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["ALLOW", "DENY"],
            "description": "ALLOW if threat_type is NONE; DENY otherwise.",
        },
        "threat_type": {
            "type": "string",
            "enum": list(THREAT_TYPES),
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "1.0=certain, 0.5=ambiguous, <0.5=do-not-trust.",
        },
        "reason": {
            "type": "string",
            "maxLength": 500,
            "description": (
                "One-to-two-sentence rationale citing the specific threat "
                "indicator. Avoid quoting the prompt verbatim — the audit log "
                "must not become an attack-pattern dictionary."
            ),
        },
    },
}


TOOL_SPEC: Final[dict] = {
    "toolSpec": {
        "name": TOOL_NAME,
        "description": (
            "Emit a security classification for the agent's tool-invocation "
            "request. Always call this tool; do not respond in free text."
        ),
        "inputSchema": {"json": TOOL_INPUT_SCHEMA},
    },
}


# toolChoice forces the model to call emit_security_verdict — eliminates
# parse-failure as a failure mode (LLD 19 §7.1).
TOOL_CHOICE: Final[dict] = {"tool": {"name": TOOL_NAME}}
