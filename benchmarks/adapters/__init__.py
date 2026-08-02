"""Benchmark adapters package."""

from .agentdojo.adapter import AgentDojoAdapter
from .local_prompts.adapter import LocalPromptsAdapter

__all__ = ["AgentDojoAdapter", "LocalPromptsAdapter"]
