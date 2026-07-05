"""WS-J J-report — the alarm-metric ↔ emitter SEAM test (the dead-seam guard).

The FIX-B finding: the prod ECS canary CMD was a bare ``pytest`` that never called
``guard_at_most_one`` / ``emit_run_metrics`` / the product-5xx escalation, so the
reporting plugin computed PASS/FAIL/INFRA counts and threw them away — every alarm
in ``canary_stack.py`` watched a metric that was NEVER produced (dead / permanent-
false-ALARM). These tests pin BOTH ends of the seam together:

  * every metric name an alarm WATCHES (``CanaryStack.ALARM_METRIC_NAMES``) is a
    metric name the entrypoint EMITS (emit_run_metrics ∪ guard_at_most_one), and
  * the emitters actually fire when driven with a fake CloudWatch client.

Reverting either end (dropping a metric from the emitter, or adding an alarm on a
metric nothing emits) breaks this test — which is exactly the guarantee the bare-CMD
regression lacked.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

from canary import entrypoint
from canary.reporting_plugin import ResultSink

# Import the stack constant WITHOUT standing up CDK (heavy): add cdk/ to the path and
# import only the module-level frozenset. If the CDK toolkit is unavailable in the
# hermetic env, fall back to reading the source so the seam is still checkable.
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _alarm_metric_names() -> frozenset:
    cdk_dir = _REPO_ROOT / "cdk"
    if str(cdk_dir) not in sys.path:
        sys.path.insert(0, str(cdk_dir))
    try:
        from stacks.canary_stack import ALARM_METRIC_NAMES  # type: ignore

        return ALARM_METRIC_NAMES
    except Exception:  # noqa: BLE001 — aws_cdk not importable in a lean env; parse source.
        src = (cdk_dir / "stacks" / "canary_stack.py").read_text()
        names = set()
        # Grab every metric_name="..." referenced by an alarm/metric in the stack.
        import re

        for m in re.finditer(r'metric_name\s*=\s*"([^"]+)"', src):
            names.add(m.group(1))
        # ChecksFailed is referenced via a local var (checks_failed) not a literal in
        # the MathExpression, so ensure it is present.
        names.add("ChecksFailed")
        return frozenset(names)


class _FakeCw:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def put_metric_data(self, **kw):
        self.calls.append(kw)

    def emitted_names(self) -> set:
        return {m["MetricName"] for c in self.calls for m in c["MetricData"]}


class _FakeEcs:
    def __init__(self, running: List[str]) -> None:
        self._running = running

    def list_tasks(self, **kw):
        return {"taskArns": self._running}


def test_every_alarm_metric_is_emitted_by_the_entrypoint():
    """The core seam: no alarm watches a metric the entrypoint never produces."""
    alarm_names = _alarm_metric_names()

    # Metrics emit_run_metrics produces on a normal end-of-run.
    cw_run = _FakeCw()
    entrypoint.emit_run_metrics(
        cw_run,
        {"PASS": 3, "FAIL": 1, "INFRA": 0, "SERVICE_5XX": 1},
        expected=4,
    )
    run_metric_names = cw_run.emitted_names()

    # Metric guard_at_most_one produces when a peer is RUNNING.
    cw_overlap = _FakeCw()
    entrypoint.guard_at_most_one(
        _FakeEcs(["arn:aws:ecs:...:task/peer"]), cw_overlap, ResultSink(mode="inprocess")
    )
    overlap_metric_names = cw_overlap.emitted_names()

    produced = run_metric_names | overlap_metric_names
    missing = alarm_names - produced
    assert not missing, (
        f"alarms watch metrics NO emitter produces (dead alarms): {sorted(missing)} "
        f"— produced={sorted(produced)}"
    )


def test_emit_run_metrics_emits_product_5xx_every_run_even_when_zero():
    """ProductFivexxFail is emitted EVERY run (0 when no product 5xx) so its
    NOT_BREACHING alarm reads a real zero, not permanent missing-data."""
    cw = _FakeCw()
    entrypoint.emit_run_metrics(cw, {"PASS": 10, "FAIL": 0, "INFRA": 0}, expected=10)
    md = {m["MetricName"]: m["Value"] for c in cw.calls for m in c["MetricData"]}
    assert md["ProductFivexxFail"] == 0.0


def test_emit_run_metrics_reports_product_5xx_count():
    """A run that saw 2 product 5xx emits ProductFivexxFail=2 (the critical escalation
    signal) — distinct from the plain ChecksFailed count."""
    cw = _FakeCw()
    entrypoint.emit_run_metrics(
        cw, {"PASS": 8, "FAIL": 2, "INFRA": 0, "SERVICE_5XX": 2}, expected=10
    )
    md = {m["MetricName"]: m["Value"] for c in cw.calls for m in c["MetricData"]}
    assert md["ProductFivexxFail"] == 2.0
    assert md["ChecksFailed"] == 2.0


def test_alarm_metric_names_is_the_documented_set():
    """The alarm-metric set is exactly the six the stack alarms depend on — a guard so
    a new alarm added without an emitter is caught by the seam test above."""
    assert _alarm_metric_names() == frozenset({
        "ChecksFailed", "ChecksPassed", "InfraErrors", "ChecksExpected",
        "CanarySkippedOverlap", "ProductFivexxFail",
    })
