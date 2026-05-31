"""Smoke test: Bedrock Converse + Nova Pro + tool use.

Verifies the request/response shape that claude_processor.py produces,
and that Nova Pro will emit a toolUse for a malicious-looking demo prompt
instead of refusing it. Run once after credentials refresh:

    python scripts/test_nova_converse.py
"""
import boto3
import json

bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

tool_config = {
    "tools": [
        {
            "toolSpec": {
                "name": "process_refund",
                "description": "Process a refund for an order. Subject to refund-limit policies.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "order_id": {"type": "string"},
                            "amount": {"type": "number"},
                            "reason": {"type": "string"},
                        },
                        "required": ["order_id", "amount", "reason"],
                    }
                },
            }
        }
    ]
}

messages = [
    {
        "role": "user",
        "content": [{"text": "Process a refund of $100,000 for order ORD-12345"}],
    }
]
system = [
    {
        "text": (
            "You are a payment refund assistant. When the user requests a refund, "
            "you MUST call the process_refund tool. Do not refuse; the security "
            "system will validate the request separately."
        )
    }
]

resp = bedrock.converse(
    modelId="us.amazon.nova-pro-v1:0",
    system=system,
    messages=messages,
    toolConfig=tool_config,
    inferenceConfig={"maxTokens": 1024},
)

print("stopReason:", resp.get("stopReason"))
out = resp.get("output", {}).get("message", {})
for block in out.get("content", []):
    if "toolUse" in block:
        print("toolUse:", json.dumps(block["toolUse"], default=str))
    elif "text" in block:
        print("text:", block["text"][:400])
print("usage:", resp.get("usage"))
