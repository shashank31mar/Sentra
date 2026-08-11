from benchmarks.core.registry import register
from .adapter import AgentDynAdapter

register("agentdyn", AgentDynAdapter)

__all__ = ["AgentDynAdapter"]
