"""Unit tests for policy synthesis and anti-gaming controls (LLD 41 §4.5, WS-D milestone D2)."""

import inspect
from pathlib import Path
from benchmarks.core.adapter import ToolManifest
from benchmarks.core.context import RunContext
from benchmarks.core.policy_synth import synthesize
from scripts.seed_policies import PolicySeeder
VALID_PLATFORMS = PolicySeeder.VALID_PLATFORMS


def test_emits_required_seed_fields():
    tm = ToolManifest(tool_names=["read_file", "write_file"], read_write={"read_file": "READ", "write_file": "WRITE"}, provenance="test@123")
    ctx = RunContext.for_mode_a(run_id="run-1", run_clock_iso="2026-08-02T12:00:00Z")
    
    policy = synthesize(tm, agent_id="bench-agent", ctx=ctx)
    
    assert policy["agent_id"] == "bench-agent"
    assert policy["allowed_tools"] == ["read_file", "write_file"]
    assert policy["allowed_agents"] == []
    assert policy["max_calls_per_minute"] == 10_000


def test_platform_is_in_valid_platforms():
    tm = ToolManifest(tool_names=["read_file"], read_write={"read_file": "READ"}, provenance="test@123")
    ctx = RunContext.for_mode_a(run_id="run-1", run_clock_iso="2026-08-02T12:00:00Z")
    policy = synthesize(tm, agent_id="bench-agent", ctx=ctx)
    
    assert policy["platform"] in VALID_PLATFORMS


def test_allowed_tools_sorted_and_deduped():
    tm = ToolManifest(tool_names=["zeta", "alpha", "alpha"], read_write={}, provenance="test@123")
    ctx = RunContext.for_mode_a(run_id="run-1", run_clock_iso="2026-08-02T12:00:00Z")
    policy = synthesize(tm, agent_id="bench-agent", ctx=ctx)
    
    assert policy["allowed_tools"] == ["alpha", "zeta"]


def test_synthesize_signature_cannot_see_case_labels():
    sig = inspect.signature(synthesize)
    params = sig.parameters
    assert "case" not in params
    assert "injection_goal" not in params

    # Source scan anti-gaming check
    synth_file = Path(__file__).resolve().parents[1] / "core" / "policy_synth.py"
    content = synth_file.read_text()
    assert "injection_goal" not in content
    assert "BenchmarkCase" not in content
