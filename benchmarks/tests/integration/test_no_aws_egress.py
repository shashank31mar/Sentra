"""Discharge the "Rig → AWS: none, never" claim — store by store.

LLD 41 §11 (the seven-store enumeration) · WS-B B6.

That row in the networking table is a *claim*, and a claim about a tree this size
has to be discharged rather than asserted: hand-waving it is how §4.4a's CRITICAL
survived a full LLD draft, and the Bedrock store (#7) was missed by a draft *and*
a first re-gate. So this module installs a socket-level guard that records every
attempted outbound connection and then exercises the stores WS-B owns.

Two of the seven are live here — **#4 audit/signal store** and **#5 CloudWatch
metrics**, the ones I4 neutralizes. The other five are neutralized by seams WS-C
and WS-D own; they are enumerated and skipped **with the owner named**, not
quietly omitted.
"""
from __future__ import annotations

import asyncio
import socket
from pathlib import Path

import pytest

from benchmarks.core import isolation
from benchmarks.core.null_objects import NullAuditWriter, NullMetricsPublisher

REPO_ROOT = Path(__file__).resolve().parents[3]

#: §11's table, as data: store → (reached-by, neutralized-by, owning workstream).
#: Kept here so a store that gains a new AWS client cannot be added to the engine
#: without something in the rig noticing it is unaccounted for.
SEVEN_STORES = {
    1: ("Sessions (DynamoDB)", "BenchmarkSessionStore", "WS-D"),
    2: ("Policies (DynamoDB + S3)", "BenchmarkPolicyEngine", "WS-D"),
    3: ("Sigma rules (DynamoDB + S3)", "get_clients() registry primed with fakes", "WS-C"),
    4: ("Audit + signal store (CloudWatch Logs / DynamoDB)", "NullAuditWriter (I4)", "WS-B"),
    5: ("CloudWatch metrics", "NullMetricsPublisher (I4)", "WS-B"),
    6: ("RPS quota (DynamoDB)", "not reached in-process (route handler only)", "n/a"),
    7: ("Bedrock, via D2's ML leg", "injected client via MLClassifier.__init__", "WS-C"),
}

OWNED_HERE = (4, 5)


class _EgressBlocked(RuntimeError):
    """Raised in place of an actual outbound connection."""


@pytest.fixture
def egress_recorder(monkeypatch):
    """Record — and block — every outbound connection attempt.

    Both ends of the path are covered: ``socket.getaddrinfo`` (what
    ``socket.create_connection``, and therefore urllib3 and botocore, call first)
    and ``socket.socket.connect``. An attempt is evidence whether or not it would
    have succeeded, which is the point: the assertion is *zero attempts*, not
    *zero successes*.

    Loopback is recorded too, deliberately. In a proxied environment (CI runners,
    a sandboxed shell) botocore's connection goes to a local forward proxy, so
    exempting loopback would make the guard blind to exactly the egress it exists
    to catch — and would make the negative control below pass while seeing
    nothing.
    """
    attempts: list = []

    def _getaddrinfo(host, port, *args, **kwargs):
        attempts.append(f"getaddrinfo:{host}:{port}")
        raise _EgressBlocked(f"blocked DNS resolution of {host}:{port}")

    def _connect(_self, address):
        attempts.append(f"connect:{address}")
        raise _EgressBlocked(f"blocked connect to {address}")

    def _connect_ex(_self, address):
        attempts.append(f"connect_ex:{address}")
        return 1

    monkeypatch.setattr(socket, "getaddrinfo", _getaddrinfo)
    monkeypatch.setattr(socket.socket, "connect", _connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _connect_ex)
    return attempts


@pytest.fixture
def isolated(hermetic_env):
    """A run under ``enforce()``, unwound afterwards."""
    import botocore.session

    hermetic_env.setattr(botocore.session.Session, "get_credentials", lambda _s: None)
    record = isolation.enforce()
    yield record
    record.release()


# --------------------------------------------------------------------------- #
# The recorder itself — without this control, "zero attempts" could just mean
# the guard is asleep.
# --------------------------------------------------------------------------- #
def test_egress_recorder_actually_sees_an_attempt(isolated, egress_recorder):
    """An UN-neutralized AWS client does attempt egress, and the recorder catches
    it. This is the negative control that makes every ``== []`` below load
    bearing."""
    import boto3
    from botocore.config import Config

    # Credentials passed explicitly rather than resolved from the chain: the
    # `isolated` fixture stubs the provider chain to None, and botocore raises
    # NoCredentialsError at signing time — before it ever opens a socket. That
    # would make this control silently observe nothing, which is the exact
    # failure mode it exists to rule out.
    client = boto3.client(
        "cloudwatch",
        region_name="us-east-1",
        aws_access_key_id=isolation.SENTINEL_CREDENTIAL,
        aws_secret_access_key=isolation.SENTINEL_CREDENTIAL,
        config=Config(connect_timeout=1, read_timeout=1, retries={"max_attempts": 0}),
    )
    with pytest.raises(Exception):
        client.put_metric_data(
            Namespace="Sentra/Benchmark", MetricData=[{"MetricName": "X", "Value": 1}]
        )

    # Not asserted against an AWS hostname: behind a forward proxy the recorded
    # peer is the proxy, not `monitoring.us-east-1.amazonaws.com`. The claim
    # being discharged is "no connection attempted at all", so the control is
    # "an un-neutralized client attempts one".
    assert egress_recorder, (
        "the egress recorder observed nothing — the guard is not installed, and "
        "every `== []` assertion in this module would be vacuous"
    )


# --------------------------------------------------------------------------- #
# Store #5 — CloudWatch metrics. The observed live contamination path.
# --------------------------------------------------------------------------- #
def test_store_5_cloudwatch_metrics_makes_no_attempt(isolated, egress_recorder):
    """``sigma_engine.py:362`` constructs ``MetricsPublisher()`` lazily and awaits
    ``publish_sigma_alarm_metric``. Under I4 that resolves to the null object and
    no connection is attempted."""
    from app.utils.metrics_publisher import MetricsPublisher

    publisher = MetricsPublisher()
    assert isinstance(publisher, NullMetricsPublisher)

    asyncio.run(publisher.publish_sigma_alarm_metric("PromptSignatureRulesUnavailable"))
    asyncio.run(
        publisher.publish_validation_metrics(
            decision="DENY", latency_ms=12.5, agent_id="bench-agent", trust_score=0.4
        )
    )
    asyncio.run(publisher.publish_sigma_match_metric("sigma-llm-001"))

    assert egress_recorder == []
    assert publisher.total_calls == 3


# --------------------------------------------------------------------------- #
# Store #4 — audit + signal store. Fire-and-forget, so a failure here would be
# swallowed rather than surfaced: I4 rather than I2 is the primary control.
# --------------------------------------------------------------------------- #
def test_store_4_audit_writer_makes_no_attempt(isolated, egress_recorder):
    from app.utils.audit_logger import AuditLogger

    writer = AuditLogger()
    assert isinstance(writer, NullAuditWriter)

    asyncio.run(writer.log_decision({"decision": "DENY", "agent_id": "bench-agent"}))
    asyncio.run(writer.log_signals({"agent_id": "bench-agent"}, []))

    assert egress_recorder == []
    assert writer.total_calls == 2


def test_constructing_the_null_objects_opens_no_connection(isolated, egress_recorder):
    """The real constructors are where the boto3 clients are built
    (``metrics_publisher.py:34``, ``audit_logger.py:110``) — and
    ``AuditLogger.__init__`` additionally calls ``create_log_group``. Construction
    alone must be silent."""
    from app.utils.audit_logger import AuditLogger
    from app.utils.metrics_publisher import MetricsPublisher

    for _ in range(3):
        MetricsPublisher()
        AuditLogger()

    assert egress_recorder == []


# --------------------------------------------------------------------------- #
# Store #6 — discharged statically: it is not on the in-process path at all.
# --------------------------------------------------------------------------- #
def test_store_6_rps_quota_is_route_handler_only():
    """The rig calls ``validate_tool_call`` directly, *below* the handler, so the
    RPS quota check is never reached in-process. Asserted against the source
    rather than trusted: if a future refactor moves ``check_validate_rps`` into
    the service, this fails and the table row needs re-deriving."""
    app_root = REPO_ROOT / "src" / "security-controller" / "app"
    callers = sorted(
        path.relative_to(app_root).as_posix()
        for path in app_root.rglob("*.py")
        if "check_validate_rps" in path.read_text(encoding="utf-8")
    )
    assert callers, "check_validate_rps not found — the §11 row needs re-deriving"
    assert all(
        caller.startswith("api/") or caller.startswith("services/quota")
        for caller in callers
    ), f"check_validate_rps escaped the route-handler layer: {callers}"


# --------------------------------------------------------------------------- #
# The other five — enumerated with their owner, never quietly omitted.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("store_id", sorted(SEVEN_STORES))
def test_every_store_has_a_named_neutralization_and_owner(store_id):
    name, neutralization, owner = SEVEN_STORES[store_id]
    assert name and neutralization and owner
    if store_id in OWNED_HERE:
        assert owner == "WS-B"


@pytest.mark.parametrize(
    "store_id", [s for s in sorted(SEVEN_STORES) if s not in OWNED_HERE and s != 6]
)
def test_store_neutralization_not_owned_by_ws_b(store_id):
    name, neutralization, owner = SEVEN_STORES[store_id]
    pytest.skip(
        f"store #{store_id} ({name}) is neutralized by {neutralization}, owned by "
        f"{owner}. Its egress discharge lands with that workstream; WS-B owns #4 "
        "and #5 only. Deliberately skipped, not omitted."
    )
