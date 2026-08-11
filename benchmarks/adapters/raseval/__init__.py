from benchmarks.core.registry import register
from .adapter import RASEvalAdapter

register("raseval", RASEvalAdapter)

__all__ = ["RASEvalAdapter"]
