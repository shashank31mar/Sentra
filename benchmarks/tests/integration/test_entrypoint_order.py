"""Integration test for entrypoint ordering and isolation badge check (WS-A, WS-B)."""

import os
import subprocess
import sys


def test_entrypoint_order_unbadged():
    env = os.environ.copy()
    env.pop("AEGION_BENCHMARK", None)
    
    cmd = [sys.executable, "-m", "benchmarks.run", "--help"]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    
    # Isolation chain (I1) enforces AEGION_BENCHMARK is set and exits with 2 when unbadged
    assert proc.returncode == 2, f"Expected return code 2 when unbadged, got {proc.returncode}"


def test_entrypoint_order_badged():
    env = os.environ.copy()
    env["AEGION_BENCHMARK"] = "1"
    
    cmd = [sys.executable, "-m", "benchmarks.run", "--help"]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    
    assert proc.returncode == 0, f"Expected return code 0 when badged, got {proc.returncode}. Stderr: {proc.stderr}"
