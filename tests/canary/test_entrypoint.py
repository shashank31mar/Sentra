"""WS-J J-report Jr.4/Jr.3 — at-most-one startup guard + CW metric emission +
the ECS entrypoint main() wrapper (the seam that turns plugin counts into metrics)."""
from __future__ import annotations

from typing import Any, Dict, List

import canary.entrypoint as entrypoint
import canary.reporting_plugin as reporting_plugin
from canary.entrypoint import (
    emit_run_metrics,
    expected_check_count,
    guard_at_most_one,
    main,
)
from canary.reporting_plugin import ResultSink


class _FakeEcs:
    def __init__(self, running_arns: List[str]):
        self._arns = running_arns

    def list_tasks(self, **kw):
        assert kw["cluster"] == "sentra-mvp-cluster"
        assert kw["family"] == "sentra-canary"
        assert kw["desiredStatus"] == "RUNNING"
        return {"taskArns": self._arns}


class _FakeCw:
    def __init__(self):
        self.calls: List[Dict[str, Any]] = []

    def put_metric_data(self, **kw):
        self.calls.append(kw)


def test_startup_guard_skips_on_running_peer(capsys):
    """Another RUNNING canary → guard returns False, emits CanarySkippedOverlap metric
    + a SKIPPED_OVERLAP results row (never indistinguishable from green, Jr.4)."""
    ecs = _FakeEcs(["arn:aws:ecs:...:task/other-running"])
    cw = _FakeCw()
    sink = ResultSink(mode="inprocess")
    proceed = guard_at_most_one(ecs, cw, sink)
    assert proceed is False
    metric_names = {
        m["MetricName"] for call in cw.calls for m in call["MetricData"]
    }
    assert "CanarySkippedOverlap" in metric_names
    assert "SKIPPED_OVERLAP" in capsys.readouterr().out


def test_startup_guard_proceeds_when_alone():
    ecs = _FakeEcs([])
    cw = _FakeCw()
    sink = ResultSink(mode="inprocess")
    assert guard_at_most_one(ecs, cw, sink) is True
    assert cw.calls == []  # no overlap metric when alone


def test_startup_guard_excludes_self():
    """The current task's own ARN is excluded from the running-peer check."""
    self_arn = "arn:aws:ecs:...:task/self"
    ecs = _FakeEcs([self_arn])
    cw = _FakeCw()
    sink = ResultSink(mode="inprocess")
    assert guard_at_most_one(ecs, cw, sink, exclude_task_arn=self_arn) is True


def test_emit_run_metrics_includes_checks_expected():
    """End-of-run emits ChecksPassed/Failed/Infra + ChecksExpected (anti-false-PASS)."""
    cw = _FakeCw()
    emit_run_metrics(cw, {"PASS": 100, "FAIL": 2, "INFRA": 1}, expected=113)
    md = {m["MetricName"]: m["Value"] for call in cw.calls for m in call["MetricData"]}
    assert md["ChecksPassed"] == 100.0
    assert md["ChecksFailed"] == 2.0
    assert md["InfraErrors"] == 1.0
    assert md["ChecksExpected"] == 113.0


def test_expected_check_count_matches_landed_manifest():
    """ChecksExpected equals the landed-set manifest count (positive + each axis)."""
    n = expected_check_count()
    # Sanity: it must equal what the all-route generator emits (see test_all_routes).
    from canary.route_manifest import ROUTE_MANIFEST

    hand = sum(
        1 + len(s.failure_axis)
        for s in ROUTE_MANIFEST
        if s.auth_class in ("public", "key") and s.landed_flag
    )
    assert n == hand and n > 0


# --------------------------------------------------------------------------- main()
def test_main_inprocess_runs_suite_and_returns_pytest_exit(monkeypatch):
    """main() runs the suite via _run_suite; in inprocess mode it does NOT touch
    ECS/CloudWatch (no live emission) and returns the pytest exit code (the seam that
    the bare CMD lacked: it now actually invokes the runner)."""
    seen: Dict[str, Any] = {}

    def _fake_run_suite(argv=None):
        seen["ran"] = True
        seen["argv"] = argv
        return 0  # pytest ExitCode.OK

    monkeypatch.setattr(entrypoint, "_run_suite", _fake_run_suite)
    monkeypatch.setenv("CANARY_TARGET", "inprocess")
    rc = main(["tests/canary/test_reporting_plugin.py"])
    assert seen["ran"] is True
    assert rc == 0


def test_main_live_emits_metrics_after_run(monkeypatch):
    """The load-bearing FIX: in live mode main() runs the guard, runs the suite, then
    calls emit_run_metrics with the plugin's counts → the CloudWatch metrics the alarms
    watch are actually produced (they were computed-then-discarded before)."""
    emitted: Dict[str, Any] = {}

    class _FakeCw:
        def put_metric_data(self, **kw):
            emitted.setdefault("md", []).extend(kw["MetricData"])

    class _FakeEcs:
        def list_tasks(self, **kw):
            return {"taskArns": []}  # no peer → proceed

    def _fake_boto3_client(name):
        return {"ecs": _FakeEcs(), "cloudwatch": _FakeCw()}[name]

    import boto3

    monkeypatch.setattr(boto3, "client", _fake_boto3_client)
    monkeypatch.setenv("CANARY_TARGET", "live")

    # Simulate the plugin having counted a run (as pytest_runtest_makereport would).
    monkeypatch.setattr(reporting_plugin, "run_counts",
                        lambda: {"PASS": 5, "FAIL": 1, "INFRA": 0, "SERVICE_5XX": 1})
    monkeypatch.setattr(entrypoint, "_run_suite", lambda argv=None: 1)  # a FAIL

    rc = main([])

    names = {m["MetricName"]: m["Value"] for m in emitted["md"]}
    assert names["ChecksPassed"] == 5.0
    assert names["ChecksFailed"] == 1.0
    assert names["ProductFivexxFail"] == 1.0
    assert "ChecksExpected" in names
    assert rc == 1  # a failing run exits non-zero (pages via the alarm too)


def test_main_live_skips_run_and_emit_when_peer_running(monkeypatch):
    """If a peer canary is already RUNNING, main() exits 0 WITHOUT running the suite or
    the end-of-run emit — the overlap guard already emitted its distinct metric+row."""
    ran = {"suite": False, "emit": False}

    class _FakeCw:
        def put_metric_data(self, **kw):
            pass

    class _FakeEcs:
        def list_tasks(self, **kw):
            return {"taskArns": ["arn:aws:ecs:...:task/peer"]}  # a peer is running

    def _fake_boto3_client(name):
        return {"ecs": _FakeEcs(), "cloudwatch": _FakeCw()}[name]

    class _FakeSink:
        def write(self, result):  # the SKIPPED_OVERLAP row — capture, don't touch AWS.
            ran["overlap_row"] = result.status
            return True

    import boto3

    monkeypatch.setattr(boto3, "client", _fake_boto3_client)
    monkeypatch.setattr(reporting_plugin, "ResultSink", lambda *a, **k: _FakeSink())
    monkeypatch.setenv("CANARY_TARGET", "live")
    monkeypatch.setattr(entrypoint, "_run_suite",
                        lambda argv=None: ran.__setitem__("suite", True))
    monkeypatch.setattr(entrypoint, "emit_run_metrics",
                        lambda *a, **k: ran.__setitem__("emit", True))

    rc = main([])
    assert rc == 0
    assert ran["suite"] is False and ran["emit"] is False
    assert ran.get("overlap_row") == "SKIPPED_OVERLAP"  # the guard did emit its row
