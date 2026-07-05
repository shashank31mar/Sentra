"""WS-J J-report — reporting plugin: live-write, three-state model, metric emission."""
from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from canary.reporting_plugin import (
    CanaryResult,
    InfraError,
    ResultSink,
    classify_outcome,
    new_run_id,
    retry_transport,
)
from app.config import settings


def _mk_results_table(ddb, name="sentra-canary-results"):
    ddb.create_table(
        TableName=name,
        KeySchema=[
            {"AttributeName": "run_id", "KeyType": "HASH"},
            {"AttributeName": "check_id", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "run_id", "AttributeType": "S"},
            {"AttributeName": "check_id", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    return ddb.Table(name)


# ---- three-state model (Jr.2) ---------------------------------------------------
def test_three_state_pass():
    assert classify_outcome(passed=True, infra=False, service_5xx=False) == "PASS"


def test_three_state_assertion_failure_is_fail_no_retry():
    assert classify_outcome(passed=False, infra=False, service_5xx=False) == "FAIL"


def test_three_state_service_5xx_is_fail_not_infra():
    """A service-returned 5xx is a FAIL that pages, NOT an INFRA blip (Jr.2 footgun)."""
    assert classify_outcome(passed=True, infra=False, service_5xx=True) == "FAIL"


def test_three_state_transport_no_response_is_infra():
    assert classify_outcome(passed=False, infra=True, service_5xx=False) == "INFRA"


def test_retry_transport_retries_then_infra():
    """A no-HTTP-response transport error retries N=2 then → INFRA (never green)."""
    calls = {"n": 0}

    def _always_conn_error():
        calls["n"] += 1
        raise ConnectionError("conn refused")

    with pytest.raises(InfraError):
        retry_transport(_always_conn_error, retries=2, backoff=0.0)
    assert calls["n"] == 3  # initial + 2 retries


def test_retry_transport_succeeds_without_retry():
    calls = {"n": 0}

    def _ok():
        calls["n"] += 1
        return "ok"

    assert retry_transport(_ok, retries=2, backoff=0.0) == "ok"
    assert calls["n"] == 1


# ---- live-write vs stdout-only (Jr.1) -------------------------------------------
def test_inprocess_writes_zero_rows(capsys):
    """inprocess mode → stdout only, NEVER writes prod (Jr.1)."""
    sink = ResultSink(mode="inprocess")
    wrote = sink.write(CanaryResult(run_id="r", check_id="c", status="PASS"))
    assert wrote is False
    assert sink.written == []
    assert "PASS c" in capsys.readouterr().out


def test_live_writes_one_row_per_check_with_all_fields():
    """live mode → exactly one row per check with the full schema populated. The
    sink uses boto3's default region (the ECS task's AWS_DEFAULT_REGION), so create
    the table in the same default region the sink writes to."""
    with mock_aws():
        ddb = boto3.resource("dynamodb")  # default region (matches ResultSink.write)
        _mk_results_table(ddb)
        sink = ResultSink(mode="live", table_name="sentra-canary-results")
        run_id = new_run_id()
        res = CanaryResult(
            run_id=run_id, check_id="j2.allow", status="FAIL", scenario="J2",
            route="POST /v1/validate", failure_reason="decision != ALLOW",
            expected="ALLOW", actual="DENY", http_status=200, latency_ms=12.3,
            correlation_id="cid-abc",
        )
        assert sink.write(res) is True
        item = boto3.resource("dynamodb").Table("sentra-canary-results").get_item(
            Key={"run_id": run_id, "check_id": "j2.allow"}
        )["Item"]
        for f in ("status", "failure_reason", "expected", "actual", "http_status",
                  "latency_ms", "correlation_id", "scenario", "route", "ttl"):
            assert f in item, f"missing result field {f}"
        assert item["status"] == "FAIL"
        assert int(item["ttl"]) > 0


def test_sts_guard_blocks_non_canary_publish():
    """The sts:GetCallerIdentity guard blocks a publish from a non-canary role (§9.3)."""

    class _FakeSts:
        def get_caller_identity(self):
            return {"Arn": "arn:aws:sts::531109575379:assumed-role/some-developer/x"}

    sink = ResultSink(mode="live", table_name="sentra-canary-results")
    published = sink.publish_critical(
        "arn:aws:sns:us-east-1:531109575379:sentra-mvp-critical-alerts",
        "boom",
        sts_client=_FakeSts(),
    )
    assert published is False  # fail-closed: a non-canary caller cannot page.
