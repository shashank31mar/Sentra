"""Policy synthesis for benchmark runs (LLD 41 §4.5, WS-D milestone D2)."""

from typing import Dict, Any
from benchmarks.core.adapter import ToolManifest
from benchmarks.core.context import RunContext


def synthesize(tm: ToolManifest, *, agent_id: str, ctx: RunContext) -> Dict[str, Any]:
    """Synthesize a policy dictionary from a ToolManifest.

    FR-14.4 & FR-14.6 compliance:
    - allowed_tools: sorted tool names from ToolManifest
    - max_calls_per_minute: 10_000 (neutralized rate limit)
    - metadata: carries provenance, timestamp from RunContext, and run_id

    CRITICAL ANTI-GAMING FENCE: This function receives ONLY ToolManifest, agent_id,
    and RunContext. It has zero visibility into test case labels or attack objectives.
    """
    return {
        "agent_id": agent_id,
        "allowed_tools": sorted(set(tm.tool_names)),
        "allowed_agents": [],
        "max_calls_per_minute": 10_000,
        "platform": "unknown",
        "cloud_region": "us-east-1",
        "metadata": {
            "synthesized_from": tm.provenance,
            "synthesized_at": ctx.run_clock_iso,
            "benchmark_run_id": ctx.run_id,
        },
    }
