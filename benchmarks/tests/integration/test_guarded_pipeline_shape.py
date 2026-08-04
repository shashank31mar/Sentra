"""Integration test for AgentDojo guarded pipeline shape (LLD 41 §4.4, WS-E milestone E1)."""

import sys
from pathlib import Path

agentdojo_src = "/Users/ruchikkachaudhary/closed-source/agentdojo/src"
if agentdojo_src not in sys.path and Path(agentdojo_src).exists():
    sys.path.insert(0, agentdojo_src)

import pytest
from unittest.mock import MagicMock
from agentdojo.agent_pipeline.agent_pipeline import AgentPipeline, PipelineConfig, ToolsExecutionLoop
from agentdojo.agent_pipeline.tool_execution import ToolsExecutor
from benchmarks.adapters.agentdojo.guards import SentraContentGuard, SentraRequestGuard
from benchmarks.core.guard_client import GuardClient
from benchmarks.core.null_objects import NullAuditWriter, NullMetricsPublisher


def test_guarded_pipeline_shape(monkeypatch):
    monkeypatch.setattr("app.utils.audit_logger.AuditLogger", lambda: NullAuditWriter())
    monkeypatch.setattr("app.utils.metrics_publisher.MetricsPublisher", lambda: NullMetricsPublisher())

    gc = GuardClient()
    req_guard = SentraRequestGuard(client=gc)
    content_guard = SentraContentGuard(client=gc)

    # Construct execution loop
    executor = ToolsExecutor()
    llm_stub = MagicMock()
    loop = ToolsExecutionLoop([req_guard, executor, content_guard, llm_stub], max_iters=15)

    assert loop.max_iters == 15
    assert len(loop.elements) == 4
    assert isinstance(loop.elements[0], SentraRequestGuard)
    assert isinstance(loop.elements[1], ToolsExecutor)
    assert isinstance(loop.elements[2], SentraContentGuard)
