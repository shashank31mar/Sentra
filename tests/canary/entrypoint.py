"""WS-J J-report — the ECS canary entrypoint helpers (lld/38 §12.1).

The at-most-one concurrency startup guard (Jr.4) + end-of-run CloudWatch metric
emission (Jr.3). Kept import-side-effect-free so a PR-gate run can unit-test them
without an ECS runtime. The ECS container's actual entrypoint calls
``guard_at_most_one`` on start (exit 0 + SKIPPED_OVERLAP on a running peer), then
runs the suite, then ``emit_run_metrics``.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

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
    ``ChecksExpected`` (anti-false-PASS, §9.4). ``ChecksExpected`` is the manifest-
    required count for the currently-landed WS set — the ONLY independent attestation
    that a run didn't silently drop checks (a partial run overwrites (run_id,check_id)
    rows leaving no duplicate to notice), so it is emitted EVERY run."""
    md = [
        {"MetricName": "ChecksPassed", "Value": float(counts.get("PASS", 0)), "Unit": "Count"},
        {"MetricName": "ChecksFailed", "Value": float(counts.get("FAIL", 0)), "Unit": "Count"},
        {"MetricName": "InfraErrors", "Value": float(counts.get("INFRA", 0)), "Unit": "Count"},
        {"MetricName": "ChecksExpected", "Value": float(expected), "Unit": "Count"},
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


__all__ = [
    "another_canary_running",
    "guard_at_most_one",
    "emit_run_metrics",
    "expected_check_count",
    "CLUSTER",
    "FAMILY",
    "NAMESPACE",
]
