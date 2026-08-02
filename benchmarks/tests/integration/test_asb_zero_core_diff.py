"""Integration test asserting zero core diff for ASB adapter (LLD 41 §4.2, §6, WS-F milestone F3)."""

import subprocess
from pathlib import Path

from benchmarks.adapters.asb import ASBAdapter
from benchmarks.core.adapter import ArmResult

REPO_ROOT = Path("/Users/ruchikkachaudhary/closed-source/Sentra")


def test_asb_zero_core_diff():
    """Assert git diff over benchmarks/core/ and benchmarks/rigs/ is empty relative to baseline commit 4aa1aeb."""
    cmd = ["git", "diff", "--stat", "4aa1aeb", "HEAD", "--", "benchmarks/core/", "benchmarks/rigs/"]
    res = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=True)
    
    assert res.stdout.strip() == "", f"Core diff found against pre-WS-F baseline: {res.stdout}"


def test_asb_runs_through_unmodified_core_rig():
    """Prove ASB adapter operates through core abstractions without core modifications."""
    adapter = ASBAdapter()
    cases = list(adapter.iter_cases())
    assert len(cases) > 0

    manifest = adapter.tool_manifest(suite="default")
    assert manifest.provenance.startswith("asb:")

    with_arm = adapter.run_arm(arm="with", ctx=None)
    without_arm = adapter.run_arm(arm="without", ctx=None)

    assert isinstance(with_arm, ArmResult)
    score = adapter.score_run(with_arm=with_arm, without_arm=without_arm)
    assert score.asr_reduction_pp > 0.0
