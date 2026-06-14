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

# hosting cloud → default region. Used only as the LAST fallback when an agent
# record predates `cloud_region` (T11 migration) AND its bound policy carries no
# region either (agent-policy-management §2.3 / R7). A real region on the agent
# always wins; this just guarantees cross-cloud resolution never errors on a
# missing field.
CLOUD_TO_DEFAULT_REGION = {
    "aws": "us-east-1",
    "azure": "centralus",
    "gcp": "us-central1",
}


def resolve_cloud_provider(agent: Optional[Dict[str, Any]]) -> str:
    """cloud_provider as stored, else derived from platform, else 'unknown'."""
    if not agent:
        return UNKNOWN
    cp = agent.get("cloud_provider")
    if cp:
        return cp
    return PLATFORM_TO_CLOUD.get(agent.get("platform"), UNKNOWN)


def resolve_cloud_region(
    agent: Optional[Dict[str, Any]],
    policy: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Authoritative cloud_region for an agent (agent-policy-management §2.3, R7).

    Fallback chain, never raises on a missing field:
      1. the AGENT's own `cloud_region` (authoritative once T11 migration lands)
      2. the bound policy's `cloud_region` (back-compat for unmigrated agents)
      3. a hosting-cloud default (`CLOUD_TO_DEFAULT_REGION`)
      4. None (genuinely undetermined — caller treats as "no region")

    Cloud identity is a PER-AGENT attribute; a shared policy must NOT dictate it,
    so the agent's value always wins. The policy is consulted only as a bridge
    for records that predate the field.
    """
    if agent and agent.get("cloud_region"):
        return agent["cloud_region"]
    if policy and policy.get("cloud_region"):
        return policy["cloud_region"]
    provider = resolve_cloud_provider(agent)
    return CLOUD_TO_DEFAULT_REGION.get(provider)
