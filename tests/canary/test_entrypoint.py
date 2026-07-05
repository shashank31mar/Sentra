"""WS-J J-report Jr.4/Jr.3 — at-most-one startup guard + CW metric emission."""
from __future__ import annotations

from typing import Any, Dict, List

from canary.entrypoint import (
    emit_run_metrics,
    expected_check_count,
    guard_at_most_one,
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
