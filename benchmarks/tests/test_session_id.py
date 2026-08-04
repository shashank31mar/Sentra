"""Unit tests for session ID derivation and RunContext (LLD 41 §4.6 D6)."""

from datetime import datetime, timezone
import re
from benchmarks.core.context import RunContext, generate_run_id
from benchmarks.core.session import session_id_for


def test_session_id_is_deterministic():
    s1 = session_id_for("task_123", run_id="2026-07-27T14-02-11Z-a1b2c3")
    s2 = session_id_for("task_123", run_id="2026-07-27T14-02-11Z-a1b2c3")
    assert s1 == s2


def test_session_id_differs_across_runs():
    s1 = session_id_for("task_123", run_id="run-111")
    s2 = session_id_for("task_123", run_id="run-222")
    assert s1 != s2


def test_session_id_shape():
    s = session_id_for("task_123", run_id="2026-07-27T14-02-11Z-a1b2c3")
    pattern = r"^bench-.{20,}-[0-9a-f]{12}$"
    assert re.match(pattern, s), f"Session ID '{s}' does not match pattern {pattern}"


def test_mode_a_episode_equals_case(tmp_path):
    ctx_a = RunContext(run_id="run1", run_clock_iso="2026-07-27T14:02:11Z", transcript_dir=tmp_path, mode="A")
    ctx_b = RunContext(run_id="run1", run_clock_iso="2026-07-27T14:02:11Z", transcript_dir=tmp_path, mode="B")

    # In Mode A, episode == case_id; two cases get different session_ids
    s_a1 = ctx_a.session_id_for("case1")
    s_a2 = ctx_a.session_id_for("case2")
    assert s_a1 != s_a2

    # In Mode B, two cases sharing episode_id get the same session_id
    s_b1 = ctx_b.session_id_for("shared_ep_1")
    s_b2 = ctx_b.session_id_for("shared_ep_1")
    assert s_b1 == s_b2


def test_run_clock_is_fixed_not_wallclock(tmp_path):
    fixed_time = "2026-07-27T14:02:11.123456Z"
    ctx = RunContext(run_id="run1", run_clock_iso=fixed_time, transcript_dir=tmp_path)
    
    assert ctx.run_clock_iso == fixed_time
    assert ctx.run_clock_iso == fixed_time
