"""WS-J J-report — the ECS canary entrypoint (lld/38 §12.1).

The at-most-one concurrency startup guard (Jr.4) + end-of-run CloudWatch metric
emission (Jr.3), AND the ``main()`` the container actually runs — the wrapper that
turns the reporting-plugin's per-check counts into the CloudWatch metrics every
``canary_stack`` alarm reads. Without this wrapper the plugin computes PASS/FAIL/
INFRA counts and throws them away, so every alarm watches a metric that is never
produced (the dead-seam bug). ``main()``:

  1. ``guard_at_most_one`` — exit 0 (+ SKIPPED_OVERLAP row/metric) if a peer is RUNNING.
  2. run the suite in-process with the reporting plugin loaded (durable rows written).
  3. ``emit_run_metrics`` — ChecksPassed/Failed/Infra + ChecksExpected + ProductFivexxFail.
  4. exit non-zero iff any check FAILed (a red hourly run pages via the alarm).

The helper functions stay import-side-effect-free so a PR-gate run can unit-test
them without an ECS runtime.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional

CLUSTER = "sentra-mvp-cluster"
FAMILY = "sentra-canary"
NAMESPACE = "Sentra/Canary"


def another_canary_running(ecs_client, *, exclude_task_arn: Optional[str] = None) -> bool:
    """True iff another ``sentra-canary`` task is already RUNNING (§12.1). EventBridge
    Scheduler has NO overlap control — at-most-one is enforced HERE."""
    resp = ecs_client.list_tasks(
        cluster=CLUSTER, family=FAMILY, desiredStatus="RUNNING"
    )
    arns = [a for a in resp.get("taskArns", []) if a != exclude_task_arn]
    return len(arns) > 0


def guard_at_most_one(ecs_client, cloudwatch_client, sink, *,
                      exclude_task_arn: Optional[str] = None) -> bool:
    """If another canary is RUNNING: emit a DISTINCT ``CanarySkippedOverlap`` metric
    AND a ``status=SKIPPED_OVERLAP`` results row (so a persistent skip is NOT
    indistinguishable from a healthy run), then return False (caller exits 0 without
    running any scenario). Else return True.

    A bare ``exit 0`` skip emits ZERO PASS/FAIL rows, which reads as "nothing
    failed" — the SKIPPED_OVERLAP row + metric are MANDATORY (Jr.4 footgun)."""
    if not another_canary_running(ecs_client, exclude_task_arn=exclude_task_arn):
        return True

    cloudwatch_client.put_metric_data(
        Namespace=NAMESPACE,
        MetricData=[{"MetricName": "CanarySkippedOverlap", "Value": 1.0, "Unit": "Count"}],
    )
    from canary.reporting_plugin import CanaryResult, new_run_id

    sink.write(
        CanaryResult(
            run_id=new_run_id(),
            check_id="startup.overlap-guard",
            status="SKIPPED_OVERLAP",
            failure_reason="another sentra-canary task already RUNNING",
        )
    )
    return False


def emit_run_metrics(cloudwatch_client, counts: Dict[str, int], *, expected: int) -> None:
    """End-of-run CW emission (Jr.3): ChecksPassed / ChecksFailed / InfraErrors +
    ``ChecksExpected`` (anti-false-PASS, §9.4) + ``ProductFivexxFail`` (§9.1 critical
    escalation). ``ChecksExpected`` is the manifest-required count for the currently-
    landed WS set — the ONLY independent attestation that a run didn't silently drop
    checks (a partial run overwrites (run_id,check_id) rows leaving no duplicate to
    notice). ``ProductFivexxFail`` is emitted EVERY run (0 when no product 5xx) so its
    NOT_BREACHING alarm reads a real zero, not permanent missing-data — it fires ONLY
    on a genuine ≥1 count. All four families are emitted every run: an alarm on a
    never-produced metric is a dead alarm (the seam this wrapper closes)."""
    md = [
        {"MetricName": "ChecksPassed", "Value": float(counts.get("PASS", 0)), "Unit": "Count"},
        {"MetricName": "ChecksFailed", "Value": float(counts.get("FAIL", 0)), "Unit": "Count"},
        {"MetricName": "InfraErrors", "Value": float(counts.get("INFRA", 0)), "Unit": "Count"},
        {"MetricName": "ChecksExpected", "Value": float(expected), "Unit": "Count"},
        {"MetricName": "ProductFivexxFail", "Value": float(counts.get("SERVICE_5XX", 0)), "Unit": "Count"},
    ]
    cloudwatch_client.put_metric_data(Namespace=NAMESPACE, MetricData=md)


def expected_check_count() -> int:
    """The manifest-required check count for the currently-landed WS set: every landed
    public/key route's positive + each failure_axis (mirrors the coverage-guard
    covered-set), the anchor for the ChecksExpected attestation."""
    from canary.route_manifest import ROUTE_MANIFEST

    total = 0
    for spec in ROUTE_MANIFEST:
        if spec.auth_class in ("public", "key") and spec.landed_flag:
            total += 1  # positive
            total += len(spec.failure_axis)
    return total


_SUITE_DIR = "tests/canary/"
# Only live-safe scenarios run in prod: pr_gate_only (billing-hygiene J5) never runs
# against real prod; requires_live-marked scenarios DO (they need the live target).
# NOTE the collection narrowing is enforced in conftest.py's CANARY_TARGET-driven
# ``collect_ignore`` (NOT this marker): in the lean live container ONLY the two
# black-box httpx scenario modules (test_all_routes.py + test_metrics_live.py) are
# collected — every app-standing-up / meta / harness-unit module is ignored so a
# module-level app.*/aegion_guard/fastapi/pydantic import cannot error collection and
# blank out the metrics. This marker only additionally deselects pr_gate_only rows.
_SUITE_MARKERS = "not pr_gate_only"


def _run_suite(pytest_args: Optional[List[str]] = None) -> "Any":
    """Run the canary suite in-process with the reporting plugin loaded (so every
    check writes its durable row and the run-counts accumulate). Returns the pytest
    ``ExitCode``. Kept a thin wrapper so ``main`` stays testable."""
    import pytest

    args = pytest_args if pytest_args is not None else [
        _SUITE_DIR, "-v", "-m", _SUITE_MARKERS,
    ]
    # Load the reporting plugin explicitly (mirrors the -p canary.reporting_plugin the
    # bare CMD used) so pytest_configure builds the run-state before collection.
    return pytest.main(args, plugins=["canary.reporting_plugin"])


def resolve_self_task_arn() -> Optional[str]:
    """The running task's own ARN, for the overlap guard's self-exclusion. ECS does
    NOT inject a static ``ECS_TASK_ARN`` env var — it injects ``ECS_CONTAINER_METADATA_URI_V4``,
    whose ``/task`` document carries ``TaskARN``. Without this the guard sees ITSELF in
    the RUNNING list, counts itself as a "peer", and EVERY run false-skips with
    SKIPPED_OVERLAP (the canary never runs a single check). Prefer an explicit
    ``ECS_TASK_ARN`` if present (tests/local), else read the metadata endpoint; return
    None only if neither is available (guard then treats any RUNNING task as a peer —
    fail-safe toward skipping, not toward double-running)."""
    explicit = os.environ.get("ECS_TASK_ARN")
    if explicit:
        return explicit
    meta_uri = os.environ.get("ECS_CONTAINER_METADATA_URI_V4") or os.environ.get("ECS_CONTAINER_METADATA_URI")
    if not meta_uri:
        return None
    try:
        import json
        import urllib.request

        with urllib.request.urlopen(f"{meta_uri}/task", timeout=2) as resp:
            doc = json.loads(resp.read().decode("utf-8"))
        return doc.get("TaskARN")
    except Exception:  # pragma: no cover - metadata endpoint unavailable
        return None


def main(argv: Optional[List[str]] = None) -> int:
    """The ECS container entrypoint (the CMD). Overlap-guard → run suite → emit the
    end-of-run CloudWatch metrics from the plugin's counts → exit non-zero on any FAIL.

    A SKIPPED_OVERLAP (a peer is already running) exits 0 — the guard already emitted
    its distinct CanarySkippedOverlap metric + row. Any transport/import failure that
    prevents metric emission is surfaced as a non-zero exit (fail-secure: a run that
    could not attest its own metrics is a red run, never a silent green)."""
    import boto3

    from canary import reporting_plugin

    mode = os.environ.get("CANARY_TARGET", "inprocess")

    # 1) at-most-one overlap guard (only meaningful against the live ECS runtime).
    if mode == "live":
        ecs = boto3.client("ecs")
        cw = boto3.client("cloudwatch")
        sink = reporting_plugin.ResultSink(mode="live")
        self_arn = resolve_self_task_arn()
        if not guard_at_most_one(ecs, cw, sink, exclude_task_arn=self_arn):
            return 0  # a peer is running; the guard emitted overlap metric + row.

    # 2) run the suite (durable rows written by the plugin; counts accumulate).
    exit_code = _run_suite(argv)

    # 3) emit the end-of-run metrics the alarms watch — EVERY run (this is the seam
    #    that was missing: the plugin counted, but nothing emitted).
    if mode == "live":
        cw = boto3.client("cloudwatch")
        emit_run_metrics(cw, reporting_plugin.run_counts(),
                         expected=expected_check_count())

    # 4) exit non-zero on any FAIL so the container run itself reflects red (belt on
    #    top of the ChecksFailed alarm). pytest.main returns ExitCode (int-like).
    return int(exit_code)


__all__ = [
    "another_canary_running",
    "resolve_self_task_arn",
    "guard_at_most_one",
    "emit_run_metrics",
    "expected_check_count",
    "main",
    "CLUSTER",
    "FAMILY",
    "NAMESPACE",
]


if __name__ == "__main__":  # pragma: no cover - container entry
    sys.exit(main())
