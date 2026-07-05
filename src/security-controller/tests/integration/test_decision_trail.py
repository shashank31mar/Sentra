"""Integration test for the WS-D decision trail — LLD 33 §12 (unnumbered integration).

End-to-end over the `sentra-validation-signals` partition: a PII-bearing
`/v1/validate` that short-circuits on a sigma DENY writes the ran prefix (Signal
rows) + the not-run complement (record_type="not_run" rows) onto ONE partition,
all carrying phase=request; the read-time recompute over the ran DENY rows yields
winning_source == sentra.sigma, block_point == sentra.sigma.

Hermetic by default: the test stands up a moto-backed `sentra-validation-signals`
table (v1 schema — PK `session_id`, SK `sk`, GSI-2 `decision-date-timestamp-index`
on `decision_date` — mirroring cdk/cdk_constructs/signal_store_table_construct.py)
so `SignalStoreWriter.write_signals` / `write_not_run_markers` and
`DecisionsService.get_session_trail` run end-to-end WITHOUT live AWS. This makes
it satisfiable under the CI's hermetic creds (AWS_ACCESS_KEY_ID=testing/...),
where a BatchWriteItem against a real table would fail (no such table) and turn
every ran row into a counted failure.

FIX-B (integration-sentinel): the original version hit the LIVE dev table and so
could only pass with real `sentra` creds — under fake creds `batch_write_item`
raised a ClientError and `assert fail_sig == 0` was unreachable (4 items lost).
Backing it with moto per the sentinel's prescribed direction (a) closes that.

Run from src/security-controller/ (default — hermetic, no AWS needed):
    pytest tests/integration/test_decision_trail.py -v

Optional LIVE-DDB variant (real dev table, real creds — NOT the CI path):
    RUN_INTEGRATION_LIVE=1 AWS_PROFILE=sentra AWS_REGION=us-east-1 \\
        PYTHONPATH=. pytest tests/integration/test_decision_trail.py -v
"""

from __future__ import annotations

import os
import uuid

import boto3
import pytest
from moto import mock_aws

# Physical schema mirrors cdk/cdk_constructs/signal_store_table_construct.py
# (v1, tenancy_v2 OFF — the default). Kept in one place so a schema change is
# a single edit and the drift is caught by the read-path Query below.
_SIGNALS_TABLE = "sentra-validation-signals"
_DECISION_DATE_INDEX = "decision-date-timestamp-index"
_AGENT_INDEX = "agent-timestamp-index"


def _create_signals_table(ddb) -> None:
    """Create the v1 `sentra-validation-signals` table + both GSIs on a
    moto-backed DynamoDB resource — PK `session_id`, SK `sk`, GSI-2 keyed on
    `decision_date` (LLD 17 §5.2 / signal_store_table_construct.py)."""
    ddb.create_table(
        TableName=_SIGNALS_TABLE,
        KeySchema=[
            {"AttributeName": "session_id", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "session_id", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
            {"AttributeName": "agent_id", "AttributeType": "S"},
            {"AttributeName": "decision_date", "AttributeType": "S"},
            {"AttributeName": "timestamp_ms", "AttributeType": "N"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": _AGENT_INDEX,
                "KeySchema": [
                    {"AttributeName": "agent_id", "KeyType": "HASH"},
                    {"AttributeName": "timestamp_ms", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": _DECISION_DATE_INDEX,
                "KeySchema": [
                    {"AttributeName": "decision_date", "KeyType": "HASH"},
                    {"AttributeName": "timestamp_ms", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        BillingMode="PAY_PER_REQUEST",
    )


def test_pii_short_circuit_sigma_deny_one_query():
    """A short-circuit sigma DENY persists ran prefix (Signal rows) + not-run
    complement (record_type='not_run' rows) in ONE partition Query, all phase=request;
    the read-time recompute yields winning_source == block_point == sentra.sigma.

    Runs end-to-end against a moto-backed table so it is hermetic under the CI's
    fake creds. Set RUN_INTEGRATION_LIVE=1 to instead exercise the real dev table.
    """
    live = os.getenv("RUN_INTEGRATION_LIVE") == "1"
    if live:
        _run_body()
    else:
        # Create the moto table in the SAME region SignalStoreWriter /
        # DecisionsService use (settings.aws_region). Those consumers build
        # their boto3 clients from settings.aws_region (signal_store_writer.py:218,
        # decisions_service.py:50), which resolves to us-west-2 (config), NOT the
        # AWS_DEFAULT_REGION=us-east-1 the hermetic run exports. A hardcoded
        # us-east-1 here put the table in a region the writer never queries →
        # ResourceNotFoundException ("4 items lost") before any assertion. moto
        # keeps per-region state, so the create-region MUST match the client region.
        from app.config import settings

        with mock_aws():
            ddb = boto3.resource("dynamodb", region_name=settings.aws_region)
            _create_signals_table(ddb)
            _run_body()


def _run_body():
    from app.combiners import Source
    from app.services.decisions_service import DecisionsService
    from app.services.trail_builder import build_trail, coverage_set
    from app.combiners import Signal
    from app.utils.signal_store_writer import SignalStoreWriter

    sid = f"ittrail-{uuid.uuid4().hex[:8]}"
    rid = f"req-{uuid.uuid4().hex[:8]}"

    # Ran prefix: trust/policy/cross_agent ALLOW, sigma DENY (the denier).
    signals = [
        Signal(source=Source.SENTRA_TRUST, decision="ALLOW", priority=90),
        Signal(source=Source.SENTRA_POLICY, decision="ALLOW", priority=80),
        Signal(source=Source.SENTRA_CROSS_AGENT, decision="ALLOW", priority=50),
        Signal(source=Source.SENTRA_SIGMA, decision="DENY", reason="PII injection",
               priority=70, threat_type="PII_EXPOSURE"),
    ]
    step_timings = {"trust": 1, "policy": 1, "cross_agent": 1, "sigma": 1}
    trail = build_trail(
        signals=signals, step_timings=step_timings, coverage=coverage_set("request"),
        winning_source=Source.SENTRA_SIGMA, phase="request", is_deny=True,
    )
    # The complement past sigma must be persisted as not-run markers, else the
    # read below could never reconcile ran+not_run to coverage_total.
    assert trail.markers, "expected a non-empty not-run complement past sigma"

    writer = SignalStoreWriter()
    ok_sig, fail_sig = writer.write_signals(
        session_id=sid, request_id=rid, signals=signals,
        shared_attrs={"agent_id": "test-agent", "tool_name": "wire", "phase": "request"},
    )
    assert fail_sig == 0
    assert ok_sig == len(signals)
    ok_m, fail_m = writer.write_not_run_markers(
        session_id=sid, request_id=rid, markers=trail.markers,
    )
    assert fail_m == 0
    assert ok_m == len(trail.markers)

    svc = DecisionsService()
    resp = svc.get_session_trail(session_id=sid, request_id=rid)

    assert resp["decision"] == "DENY"
    assert resp["winning_source"] == Source.SENTRA_SIGMA
    assert resp["block_point"] == Source.SENTRA_SIGMA
    # ran prefix + not-run complement, all phase=request, one Query.
    assert resp["phase"] == "request"
    total = (resp["ran_count"] + resp["abstain_count"] + resp["ran_error_count"]
             + resp["not_run_count"])
    assert total == resp["coverage_total"]
    assert resp["not_run_count"] >= 1  # the complement past sigma
