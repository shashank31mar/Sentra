from benchmarks.core.registry import register
from .adapter import InjecAgentAdapter

register("injecagent", InjecAgentAdapter)

__all__ = ["InjecAgentAdapter"]
