"""Cloud-provider resolution (WS-21 — Kombai crash fix).

`cloud_provider` is the agent's hosting cloud (aws/gcp/azure). Not every agent
record carries it (other workstreams' seeds/demos, discovery imports), so we
derive it from the governing connector/runtime (`platform`) when missing. The
API must never emit a value outside the documented enum, or the dashboard's
enum→style maps get an undefined key and white-screen.
"""
from typing import Any, Dict, Optional

# governing connector/runtime → hosting cloud
PLATFORM_TO_CLOUD = {
    "bedrock": "aws",         # AWS Bedrock
    "azure_foundry": "azure",
    "vertex_ai": "gcp",
    "sentra": "aws",          # self-hosted on AWS ECS
}

# 'unknown' is a documented enum value (LLD 21 §2) for genuinely-undetermined
# cloud — the UI maps it to a neutral badge rather than crashing.
UNKNOWN = "unknown"


def resolve_cloud_provider(agent: Optional[Dict[str, Any]]) -> str:
    """cloud_provider as stored, else derived from platform, else 'unknown'."""
    if not agent:
        return UNKNOWN
    cp = agent.get("cloud_provider")
    if cp:
        return cp
    return PLATFORM_TO_CLOUD.get(agent.get("platform"), UNKNOWN)
