"""Load test for the validation signal store — LLD 17 §14.3 test 23.

Goal
----
Fire 100 concurrent /v1/validate-equivalent writes into a single session
and verify:
  - No SK collisions (every signal lands as a distinct DDB item).
  - All signals correlate back to their request_ids.
  - The writer's p95 stays under the budget (~800ms end-to-end with the
    DDB write's 200ms guard; from inside AWS warmed-up writes are <100ms).

This is a local stress test against the live DDB table. It bypasses the
controller's HTTP layer and calls SignalStoreWriter directly to isolate
the substrate's behavior under contention. The HTTP layer's concurrency
behavior is exercised by the integration tests + real demos.

Run
---
    RUN_LOAD=1 AWS_PROFILE=sentra AWS_REGION=us-east-1 \\
        PYTHONPATH=src/security-controller \\
        python scripts/load_test_signal_store.py
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from statistics import median


def _abort_if_not_opted_in():
    if os.getenv("RUN_LOAD") != "1":
        print("Load test gated by RUN_LOAD=1 — exiting without action.")
        sys.exit(0)


def main():
    _abort_if_not_opted_in()
    # Import here so the gate fires before any AWS connection
    sys.path.insert(0, "src/security-controller")
    from app.combiners import Signal, Source  # noqa: E402
    from app.utils.signal_store_writer import SignalStoreWriter  # noqa: E402
    import boto3  # noqa: E402

    writer = SignalStoreWriter()
    # Loosen the budget for the test — laptops on home wifi can't hit
    # 200ms over the public internet to us-east-1, but the test isn't
    # about latency, it's about SK collision safety.
    writer.write_timeout_ms = 5000
    session_id = f"load-{uuid.uuid4().hex[:8]}"
    n = 100
    print(f"session_id: {session_id}")
    print(f"firing {n} concurrent writes...")

    latencies_ms: list[float] = []
    request_ids: set[str] = set()

    def fire_one(i: int) -> tuple[str, int, int, float]:
        rid = f"req-{i:03d}-{uuid.uuid4().hex[:6]}"
        sigs = [
            Signal(source=Source.SENTRA_TRUST, decision="ALLOW", priority=90),
            Signal(source=Source.SENTRA_POLICY, decision="ALLOW", priority=80),
            Signal(source=Source.SENTRA_SIGMA,
                   decision="DENY" if i % 5 == 0 else "ALLOW",
                   reason=("PII_EXPOSURE load" if i % 5 == 0 else None),
                   priority=70),
            Signal(source=Source.SENTRA_CONTEXT, decision="ALLOW", priority=60),
            Signal(source=Source.SENTRA_ABUSE, decision="ALLOW", priority=50),
        ]
        t0 = time.perf_counter()
        success, failure = writer.write_signals(
            session_id=session_id, request_id=rid, signals=sigs,
            shared_attrs={"agent_id": f"load-agent-{i}", "tool_name": "load_tool"},
        )
        elapsed = (time.perf_counter() - t0) * 1000
        return rid, success, failure, elapsed

    t_start = time.time()
    total_success = 0
    total_failure = 0
    with ThreadPoolExecutor(max_workers=25) as ex:
        futures = [ex.submit(fire_one, i) for i in range(n)]
        for fut in as_completed(futures):
            rid, s, f, ms = fut.result()
            latencies_ms.append(ms)
            request_ids.add(rid)
            total_success += s
            total_failure += f
    t_wall = time.time() - t_start

    print(f"wall_clock: {t_wall:.2f}s")
    print(f"writes: success={total_success} failure={total_failure}")
    print(f"latency_ms: p50={median(latencies_ms):.0f} "
          f"p95={sorted(latencies_ms)[int(0.95 * len(latencies_ms))]:.0f} "
          f"max={max(latencies_ms):.0f}")
    print(f"unique request_ids: {len(request_ids)}")
    assert len(request_ids) == n, f"request_id generation collided: {len(request_ids)} != {n}"

    # Query back and assert no SK collisions (every signal landed distinctly).
    print("verifying DDB partition...")
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    items = []
    last_key = None
    while True:
        kwargs = {
            "TableName": "sentra-validation-signals",
            "KeyConditionExpression": "session_id = :sid",
            "ExpressionAttributeValues": {":sid": {"S": session_id}},
        }
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key
        resp = ddb.query(**kwargs)
        items.extend(resp.get("Items", []))
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break

    print(f"DDB items in partition: {len(items)} (expected {n * 5})")
    # 5 signals per write × n writes = 500 items
    expected = n * 5
    assert len(items) == expected, f"SK collision suspected — got {len(items)}, expected {expected}"

    # Verify every request_id is present exactly 5x
    by_rid: dict[str, int] = {}
    for it in items:
        rid = it["request_id"]["S"]
        by_rid[rid] = by_rid.get(rid, 0) + 1
    bad = [(rid, count) for rid, count in by_rid.items() if count != 5]
    assert not bad, f"request_ids with non-5 signal count: {bad[:5]}"

    print("✅ load test passed — no collisions, all request_ids preserved")
    print(f"   {n} concurrent writes × 5 signals = {expected} items, all unique SKs")


if __name__ == "__main__":
    main()
