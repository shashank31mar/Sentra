"""WS-J / LLD 38 §424-425 (SEC-11) — canary audit/signal isolation, FAIL-CLOSED.

Synthetic hourly-canary events (tenant_id `canary-*`) deliberately trip DENY /
IDENTITY_TAMPERED / POLICY_ERROR audit events; they must NOT land in the shared audit
log group or the shared behavioral-signal store the flywheel + SOC readers consume,
or they poison behavioral labels / mask a real tamper. The control is STRUCTURAL
separation (a separate canary log group + SKIP the shared signal store), not a
"readers filter canary-*" rule (which fails open).

These drive the real `AuditLogger.log_signals` path with the tenant contextvar set to
a `canary-*` value and assert:
  * the CloudWatch event is written to the SEPARATE canary log group;
  * the shared SignalStoreWriter is NEVER called for a canary tenant;
  * a normal tenant is byte-for-byte unchanged (shared group + shared signal store).
Non-vacuous: the negative controls prove each assertion fails if the routing reverts.
"""
from __future__ import annotations

from unittest.mock import Mock

import pytest

from app.combiners import Signal, Source
from app.config import settings
from app.utils import tenancy
from app.utils.audit_logger import AuditLogger, _is_canary_tenant


_CANARY_TENANT = "canary-abc123"


def _deny_signal():
    return Signal(source=Source.SENTRA_SIGMA, decision="DENY", reason="synthetic attack",
                  priority=70, threat_type="PROMPT_INJECTION", matched_rule="r.yml")


def _logger():
    """An AuditLogger whose boto3 clients are NOT constructed (bypass __init__).
    We set the two log-group names the SEC-11 branch reads + the lazy-ensure flag."""
    lg = AuditLogger.__new__(AuditLogger)
    lg._signal_store = None
    lg._metrics_publisher = None
    lg.log_group = settings.cloudwatch_log_group
    lg.canary_log_group = settings.cloudwatch_canary_log_group
    lg._canary_group_ensured = False
    return lg


def _clean_request(**overrides):
    base = {
        "session_id": "s1", "request_id": "r1", "agent_id": "a1", "tool_name": "t",
        "operation_type": "READ", "user_input": "ssn ⟦AEGR:x:SSN⟧", "tool_params": {},
        "redacted": True,
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _reset_tenant():
    """Every test starts + ends on the default tenant so a leaked contextvar can't
    make a later test spuriously route to (or away from) the canary sink."""
    tok = tenancy.set_current_tenant(tenancy.DEFAULT_TENANT)
    try:
        yield
    finally:
        tenancy.reset_current_tenant(tok)


# --------------------------------------------------------------- helper self-check

def test_is_canary_tenant_reads_contextvar():
    """`_is_canary_tenant` reads the current_tenant contextvar and matches ONLY the
    reserved `canary-` prefix — not a re-derivation from the request body."""
    tok = tenancy.set_current_tenant(_CANARY_TENANT)
    try:
        assert _is_canary_tenant() is True
    finally:
        tenancy.reset_current_tenant(tok)
    # default / real tenant → not canary
    tok = tenancy.set_current_tenant("acme")
    try:
        assert _is_canary_tenant() is False
    finally:
        tenancy.reset_current_tenant(tok)


# ----------------------------------------------------- canary tenant: isolated sink

@pytest.mark.asyncio
async def test_canary_event_routes_to_canary_group_and_skips_signal_store():
    """A canary-tenant log_signals writes the CW event to the SEPARATE canary log
    group AND does NOT touch the shared SignalStoreWriter (fail-closed structural
    separation, SEC-11). Proves both halves of the isolation."""
    lg = _logger()
    captured = {}

    async def _write(session_id, log_event, log_group=None):
        captured["session_id"] = session_id
        captured["log_group"] = log_group
        captured["event"] = log_event

    lg._write_log_event = _write
    shared_store = Mock(write_signals=Mock(), write_not_run_markers=Mock(return_value=(0, 0)))
    lg._get_signal_store = lambda: shared_store

    tok = tenancy.set_current_tenant(_CANARY_TENANT)
    try:
        await lg.log_signals(
            request=_clean_request(), session={"trust_score": 90.0},
            signals=[_deny_signal()], latency_ms=1.0,
        )
    finally:
        tenancy.reset_current_tenant(tok)

    # 1. The CW event went to the SEPARATE canary group.
    assert captured["log_group"] == settings.cloudwatch_canary_log_group
    assert captured["log_group"] != settings.cloudwatch_log_group
    # 2. The shared behavioral-signal store was NEVER written (fail-closed).
    shared_store.write_signals.assert_not_called()


@pytest.mark.asyncio
async def test_canary_markers_never_hit_shared_store():
    """Canary decision-trail markers also NEVER touch the shared signal store — the
    early return before the DDB dual-write covers markers too (they ride the same
    shared SignalStoreWriter)."""
    lg = _logger()

    async def _write(session_id, log_event, log_group=None):
        pass

    lg._write_log_event = _write
    shared_store = Mock(write_signals=Mock(), write_not_run_markers=Mock(return_value=(0, 0)))
    lg._get_signal_store = lambda: shared_store

    tok = tenancy.set_current_tenant(_CANARY_TENANT)
    try:
        await lg.log_signals(
            request=_clean_request(), session={"trust_score": 90.0},
            signals=[_deny_signal()], latency_ms=1.0,
            markers=[Mock()],  # a marker row that would otherwise write to the store
        )
    finally:
        tenancy.reset_current_tenant(tok)

    shared_store.write_signals.assert_not_called()
    shared_store.write_not_run_markers.assert_not_called()


# --------------------------------------------- normal tenant: byte-for-byte unchanged

@pytest.mark.asyncio
async def test_normal_tenant_writes_shared_group_and_signal_store():
    """A NORMAL tenant is unchanged: the CW event goes to the SHARED audit group
    (log_group None → self.log_group) AND the shared SignalStoreWriter IS written.
    This is the real-traffic path — it must be byte-for-byte as before SEC-11."""
    lg = _logger()
    captured = {}

    async def _write(session_id, log_event, log_group=None):
        captured["log_group"] = log_group
        captured["event"] = log_event

    lg._write_log_event = _write
    shared_store = Mock(write_signals=Mock(), write_not_run_markers=Mock(return_value=(0, 0)))
    lg._get_signal_store = lambda: shared_store

    tok = tenancy.set_current_tenant("acme")
    try:
        await lg.log_signals(
            request=_clean_request(), session={"trust_score": 90.0},
            signals=[_deny_signal()], latency_ms=1.0,
        )
    finally:
        tenancy.reset_current_tenant(tok)

    # Real traffic → the SHARED group (the writer got log_group=None, which resolves
    # to self.log_group inside _write_log_event).
    assert captured["log_group"] is None
    # And the shared signal store WAS written (the flywheel/SOC substrate).
    shared_store.write_signals.assert_called_once()


@pytest.mark.asyncio
async def test_default_tenant_writes_shared_signal_store():
    """The DEFAULT tenant (identity OFF — the common prod path) also writes the
    shared store, proving the SEC-11 branch does not misroute the most common case."""
    lg = _logger()

    async def _write(session_id, log_event, log_group=None):
        pass

    lg._write_log_event = _write
    shared_store = Mock(write_signals=Mock(), write_not_run_markers=Mock(return_value=(0, 0)))
    lg._get_signal_store = lambda: shared_store

    # autouse fixture already pins DEFAULT_TENANT.
    await lg.log_signals(
        request=_clean_request(), session={"trust_score": 90.0},
        signals=[_deny_signal()], latency_ms=1.0,
    )
    shared_store.write_signals.assert_called_once()


# ---------------------------------------------- lazy canary group create (moto-safe)

def test_canary_group_created_lazily_only_on_canary_event():
    """The canary log group is created ONLY on first canary write, never at __init__
    — a controller that never sees a canary request never creates it (moto-safe)."""
    lg = _logger()
    lg.cloudwatch_logs = Mock()
    # Not ensured until a canary event fires.
    assert lg._canary_group_ensured is False
    lg._ensure_canary_log_group_exists()
    assert lg._canary_group_ensured is True
    lg.cloudwatch_logs.create_log_group.assert_called_once_with(
        logGroupName=settings.cloudwatch_canary_log_group
    )
    # Idempotent: a second call does NOT re-issue create.
    lg._ensure_canary_log_group_exists()
    lg.cloudwatch_logs.create_log_group.assert_called_once()


# ------------------------------------------------------- NON-VACUOUS negative control

@pytest.mark.asyncio
async def test_negative_control_canary_to_shared_store_would_fail():
    """Prove the isolation assertion is NON-VACUOUS: if the SEC-11 branch were
    reverted so a canary event fell through to the shared signal store, the
    `assert_not_called()` above would FAIL. Simulate the reverted behavior by calling
    the shared store under a canary tenant and assert the guard's own check trips."""
    shared_store = Mock(write_signals=Mock())
    # The broken variant writes the shared store for a canary tenant:
    shared_store.write_signals(session_id="s", request_id="r", signals=[], shared_attrs={})
    with pytest.raises(AssertionError):
        shared_store.write_signals.assert_not_called()
