"""Rollback anti-IDOR + injection-safety + idempotency + tenant-stamp tests
(WS-M M2.3 / M2.4 / M2.5, lld/39 §3.3-3.4).

The money-movement path gets two independent tenant checks (a tenant-filtered
Logs-Insights query AND an in-code re-verify), an injection-safe exact-match query
with an action_id grammar reject, a durable idempotency ledger, and a distinct
retryable status on a resolution-substrate timeout (never a cross-tenant 404).
"""
from __future__ import annotations

import json

import pytest
from unittest.mock import Mock, patch, MagicMock

from app.utils.rollback_coordinator import (
    RESOLUTION_UNAVAILABLE,
    RollbackCoordinator,
    _ACTION_ID_RE,
    _CONVERSATION_ID_RE,
    _tenant_of_action,
    _tenant_of_conversation,
)

_VALID = "act-process_refund-20260706120000-a1b2c3"


@pytest.fixture
def coordinator():
    with patch("app.utils.rollback_coordinator.boto3") as mock_boto3, \
         patch("app.utils.rollback_coordinator.AuditLogger"):
        logs = Mock()
        ddb = Mock()
        table = Mock()
        mock_boto3.client.return_value = logs
        mock_boto3.resource.return_value = ddb
        ddb.Table.return_value = table
        c = RollbackCoordinator()
        c.cloudwatch_logs = logs
        c.orders_table = table
        c.dynamodb = ddb
        yield c


def _mk_logs_result(coordinator, log_data):
    coordinator.cloudwatch_logs.start_query.return_value = {"queryId": "q1"}
    coordinator.cloudwatch_logs.get_query_results.return_value = {
        "status": "Complete",
        "results": [[{"field": "@message", "value": json.dumps(log_data)}]],
    }


# --------------------------------------------------------------------------- #
# Piece 1 — the tenant-stamp predecessor (audit_logger._build_log_event)
# --------------------------------------------------------------------------- #
def test_build_log_event_stamps_tenant_id():
    """A reversible action record MUST carry a stamped tenant_id (from the ambient
    verified-tenant contextvar) — the predecessor _tenant_of_action depends on."""
    from app.utils.audit_logger import AuditLogger
    from app.utils import tenancy

    with patch("app.utils.audit_logger.boto3"), patch("app.utils.audit_logger.AuditLogger.__init__", return_value=None):
        al = AuditLogger()
    token = tenancy.set_current_tenant("t_stamped")
    try:
        event = al._build_log_event(
            decision="ALLOW",
            request={"request_id": "r1", "session_id": "s1", "agent_id": "t_stamped-x",
                     "tool_name": "process_refund", "operation_type": "WRITE", "user_input": ""},
            session={"trust_score": 100.0},
            validation_result=None,
            latency_ms=1.0,
        )
    finally:
        tenancy.reset_current_tenant(token)
    assert event["reversible"] is True
    assert event["tenant_id"] == "t_stamped"


# --------------------------------------------------------------------------- #
# Piece 2 — injection-safe action_id grammar
# --------------------------------------------------------------------------- #
def test_action_id_regex_shape():
    assert _ACTION_ID_RE.match(_VALID)
    for bad in ['act-refund-123', 'act-x-20260706120000-a1b2c3" | filter x',
                "'; drop", "act-x-2026-a1b2c3", ""]:
        assert not _ACTION_ID_RE.match(bad), bad


@pytest.mark.asyncio
async def test_rollback_action_id_regex_rejects_crafted(coordinator):
    """A crafted action_id is rejected up front — never interpolated into the query."""
    result = await coordinator.rollback_action(
        action_id='act-x" | filter tenant_id="t_b',
        action_type="process_refund", reason="r", operator_id="op",
        tenant_id="t_a",
    )
    assert result["success"] is False
    assert "not found or not reversible" in result["message"].lower()
    coordinator.cloudwatch_logs.start_query.assert_not_called()


# --------------------------------------------------------------------------- #
# anti-IDOR — cross-tenant action rollback blocked (in-code re-verify)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_rollback_cross_tenant_action_404(coordinator):
    """Even if a record surfaced with a foreign tenant_id, the in-code re-verify
    blocks the reversal (never a double-check bypass)."""
    _mk_logs_result(coordinator, {"action_id": _VALID, "tool_name": "process_refund",
                                  "tenant_id": "t_OTHER", "rollback_status": "NOT_ROLLED_BACK"})
    result = await coordinator.rollback_action(
        action_id=_VALID, action_type="process_refund", reason="r",
        operator_id="op", tenant_id="t_a",
    )
    assert result["success"] is False
    coordinator.orders_table.update_item.assert_not_called()


@pytest.mark.asyncio
async def test_rollback_freshly_stamped_action_ok(coordinator):
    """Stamp → tenant-filtered query → in-code re-verify → idempotency claim →
    reversal, all wired for a same-tenant action."""
    _mk_logs_result(coordinator, {"action_id": _VALID, "tool_name": "process_refund",
                                  "tenant_id": "t_a", "tool_params": {"order_id": "O1", "amount": 10},
                                  "rollback_status": "NOT_ROLLED_BACK"})
    result = await coordinator.rollback_action(
        action_id=_VALID, action_type="process_refund", reason="r",
        operator_id="op", tenant_id="t_a",
    )
    assert result["success"] is True
    assert coordinator.orders_table.update_item.called


# --------------------------------------------------------------------------- #
# M2.5 — resolution-substrate timeout is a distinct retryable status, not a 404
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_rollback_logs_timeout_returns_retryable_not_404(coordinator):
    coordinator.cloudwatch_logs.start_query.return_value = {"queryId": "q1"}
    coordinator.cloudwatch_logs.get_query_results.return_value = {"status": "Running"}
    result = await coordinator.rollback_action(
        action_id=_VALID, action_type="process_refund", reason="r",
        operator_id="op", tenant_id="t_a",
    )
    assert result["success"] is False
    assert result.get("status") == RESOLUTION_UNAVAILABLE
    assert result.get("retryable") is True


@pytest.mark.asyncio
async def test_query_failed_returns_resolution_unavailable(coordinator):
    coordinator.cloudwatch_logs.start_query.return_value = {"queryId": "q1"}
    coordinator.cloudwatch_logs.get_query_results.return_value = {"status": "Failed"}
    out = coordinator._query_action_sync(_VALID, tenant_id="t_a")
    assert out == RESOLUTION_UNAVAILABLE


# --------------------------------------------------------------------------- #
# _tenant_of_action — the ownership resolution consumed by assert_owns(ACTION)
# --------------------------------------------------------------------------- #
def test_tenant_of_action_rejects_crafted_id_without_query():
    with patch("app.utils.rollback_coordinator.RollbackCoordinator") as RC:
        assert _tenant_of_action('bad" | filter', "t_a") is None
        RC.assert_not_called()


# --------------------------------------------------------------------------- #
# Route-level wiring (WS-M M2.3): rollback routes are admin-gated + assert_owns
# --------------------------------------------------------------------------- #
def test_rollback_routes_admin_gated():
    import inspect
    from app.api import routes as R

    for handler in (R.rollback_action, R.rollback_conversation):
        dep = inspect.signature(handler).parameters["ctx"].default.dependency
        vals = {c.cell_contents for c in (dep.__closure__ or ())}
        assert "admin" in {v for v in vals if isinstance(v, str)}, handler.__name__


@pytest.mark.asyncio
async def test_rollback_action_route_asserts_action_ownership():
    from fastapi import HTTPException
    from app.api import routes as R
    from app.api.deps import OperatorContext
    from app.api.ownership import ResourceKind

    calls = []
    with patch("app.api.routes.assert_owns", side_effect=lambda c, k, i: calls.append(k)), \
         patch("app.utils.rollback_coordinator.RollbackCoordinator") as RC:
        RC.return_value.rollback_action = _AsyncReturn({"success": True, "action_id": _VALID})
        await R.rollback_action(
            {"action_id": _VALID, "action_type": "process_refund", "reason": "r"},
            ctx=OperatorContext(sub="op", tenant_id="t_a", role="admin", email="op@x"),
        )
    assert ResourceKind.ACTION in calls


# --------------------------------------------------------------------------- #
# WS-M FIX-B — CONVERSATION resolves via CloudWatch Logs, NOT the session table.
# The prior dispatch pointed CONVERSATION at the session_context store; a
# conversation_id is never a key there, so every legitimate rollback 404'd. These
# tests pin the corrected Logs-Insights resolution (mocked substrate, like ACTION).
# --------------------------------------------------------------------------- #
_CONV = "conv-abc123"


def test_conversation_id_regex_shape():
    """Grammar accepts real ids, rejects Logs-Insights query metacharacters."""
    for ok in (_CONV, "conv_1", "a1b2c3", "550e8400-e29b-41d4-a716-446655440000"):
        assert _CONVERSATION_ID_RE.match(ok), ok
    for bad in ['conv" | filter tenant_id="t_b', "conv-1'; drop", "conv 1", "", "a" * 129]:
        assert not _CONVERSATION_ID_RE.match(bad), bad


def test_tenant_of_conversation_rejects_crafted_id_without_query():
    """A crafted conversation_id is rejected up front — never interpolated."""
    with patch("app.utils.rollback_coordinator.RollbackCoordinator") as RC:
        assert _tenant_of_conversation('conv" | filter x', "t_a") is None
        RC.assert_not_called()


def test_query_conversation_tenant_sync_returns_stamped_owner(coordinator):
    """A matching reversible-action event's stamped tenant_id is returned as owner."""
    coordinator.cloudwatch_logs.start_query.return_value = {"queryId": "q1"}
    coordinator.cloudwatch_logs.get_query_results.return_value = {
        "status": "Complete",
        "results": [[{"field": "@message", "value": json.dumps({
            "tenant_id": "t_a",
            "multi_agent_context": {"conversation_id": _CONV},
        })}]],
    }
    out = coordinator._query_conversation_tenant_sync(_CONV, tenant_id="t_a")
    assert out == {"tenant_id": "t_a"}


def test_query_conversation_tenant_sync_no_match_returns_none(coordinator):
    coordinator.cloudwatch_logs.start_query.return_value = {"queryId": "q1"}
    coordinator.cloudwatch_logs.get_query_results.return_value = {
        "status": "Complete", "results": [],
    }
    assert coordinator._query_conversation_tenant_sync(_CONV, tenant_id="t_a") is None


def test_query_conversation_tenant_sync_timeout_is_retryable(coordinator):
    coordinator.cloudwatch_logs.start_query.return_value = {"queryId": "q1"}
    coordinator.cloudwatch_logs.get_query_results.return_value = {"status": "Running"}
    assert coordinator._query_conversation_tenant_sync(_CONV, tenant_id="t_a") == RESOLUTION_UNAVAILABLE


def test_query_conversation_tenant_sync_query_failed_is_retryable(coordinator):
    coordinator.cloudwatch_logs.start_query.return_value = {"queryId": "q1"}
    coordinator.cloudwatch_logs.get_query_results.return_value = {"status": "Failed"}
    assert coordinator._query_conversation_tenant_sync(_CONV, tenant_id="t_a") == RESOLUTION_UNAVAILABLE


def test_query_conversation_tenant_sync_filters_by_tenant(coordinator):
    """The resolution query MUST carry an exact tenant_id filter (cross-tenant record
    never returned) and NOT a substring `like`."""
    coordinator.cloudwatch_logs.start_query.return_value = {"queryId": "q1"}
    coordinator.cloudwatch_logs.get_query_results.return_value = {
        "status": "Complete", "results": [],
    }
    coordinator._query_conversation_tenant_sync(_CONV, tenant_id="t_a")
    q = coordinator.cloudwatch_logs.start_query.call_args.kwargs["queryString"]
    assert f'filter multi_agent_context.conversation_id = "{_CONV}"' in q
    assert 'filter tenant_id = "t_a"' in q
    assert " like " not in q


def test_tenant_of_conversation_maps_result(coordinator):
    """End-to-end module-fn: a stamped event resolves to its owner tenant."""
    with patch("app.utils.rollback_coordinator.RollbackCoordinator", return_value=coordinator):
        coordinator.cloudwatch_logs.start_query.return_value = {"queryId": "q1"}
        coordinator.cloudwatch_logs.get_query_results.return_value = {
            "status": "Complete",
            "results": [[{"field": "@message", "value": json.dumps({
                "tenant_id": "t_a",
                "multi_agent_context": {"conversation_id": _CONV},
            })}]],
        }
        assert _tenant_of_conversation(_CONV, "t_a") == "t_a"


@pytest.mark.asyncio
async def test_rollback_conversation_route_asserts_conversation_ownership():
    """The route MUST assert_owns(CONVERSATION, id) before reversing anything."""
    from app.api import routes as R
    from app.api.deps import OperatorContext
    from app.api.ownership import ResourceKind

    calls = []
    with patch("app.api.routes.assert_owns", side_effect=lambda c, k, i: calls.append(k)), \
         patch("app.utils.rollback_coordinator.RollbackCoordinator") as RC:
        RC.return_value.rollback_conversation = _AsyncReturn(
            {"success": True, "conversation_id": _CONV, "rolled_back_count": 1}
        )
        await R.rollback_conversation(
            _CONV,
            {"reason": "r"},
            ctx=OperatorContext(sub="op", tenant_id="t_a", role="admin", email="op@x"),
        )
    assert ResourceKind.CONVERSATION in calls


@pytest.mark.asyncio
async def test_rollback_conversation_route_threads_tenant_id_into_coordinator():
    """WS-M M2.3 conversation-path fix: the route MUST pass ctx.tenant_id (NOT a body
    value) into RollbackCoordinator.rollback_conversation, alongside operator_id=ctx.sub.
    FAILS if the route stops threading the verified tenant into the coordinator."""
    from app.api import routes as R
    from app.api.deps import OperatorContext

    captured = {}

    async def _capture(**kwargs):
        captured.update(kwargs)
        return {"success": True, "conversation_id": _CONV, "rolled_back_count": 0}

    with patch("app.api.routes.assert_owns"), \
         patch("app.utils.rollback_coordinator.RollbackCoordinator") as RC:
        RC.return_value.rollback_conversation = _capture
        await R.rollback_conversation(
            _CONV,
            {"reason": "r"},
            ctx=OperatorContext(sub="op", tenant_id="t_a", role="admin", email="op@x"),
        )
    assert captured.get("tenant_id") == "t_a"
    assert captured.get("operator_id") == "op"
    assert captured.get("conversation_id") == _CONV


@pytest.mark.asyncio
async def test_rollback_conversation_total_failure_maps_to_500_not_fake_200():
    """Honest error contract: a TOTAL conversation-rollback failure (coordinator
    outer-except shape — success=False, a top-level message, zero processed actions)
    MUST surface as HTTP 500, NOT a fake-200 wrapping an error body. FAILS if the
    route returns the failure dict as a 200."""
    from fastapi import HTTPException
    from app.api import routes as R
    from app.api.deps import OperatorContext

    total_failure = {
        "success": False,
        "conversation_id": _CONV,
        "rolled_back_count": 0,
        "failed_count": 0,
        "message": "Conversation rollback failed due to an internal error (correlation_id=deadbeef)",
        "correlation_id": "deadbeef",
        "rolled_back_actions": [],
        "failed_actions": [],
        "reason": "r",
    }
    with patch("app.api.routes.assert_owns"), \
         patch("app.utils.rollback_coordinator.RollbackCoordinator") as RC:
        RC.return_value.rollback_conversation = _AsyncReturn(total_failure)
        with pytest.raises(HTTPException) as ei:
            await R.rollback_conversation(
                _CONV, {"reason": "r"},
                ctx=OperatorContext(sub="op", tenant_id="t_a", role="admin", email="op@x"),
            )
    assert ei.value.status_code == 500
    # customer-safe: correlation id present, no raw exception/ARN/query leaked
    assert "correlation_id" in str(ei.value.detail)


@pytest.mark.asyncio
async def test_rollback_conversation_partial_result_stays_200_batch_semantics():
    """A PARTIAL result (some actions reversed, some failed) is a legitimate batch
    response with per-item statuses — it MUST stay 200 (the route returns the dict),
    NOT be coerced to 5XX. FAILS if the honest-status guard over-fires on partials."""
    from app.api import routes as R
    from app.api.deps import OperatorContext

    partial = {
        "success": False,               # a per-action failure occurred
        "conversation_id": _CONV,
        "rolled_back_count": 1,
        "failed_count": 1,
        "skipped_count": 0,
        "rolled_back_actions": [{"action_id": "act-1", "tool_name": "process_refund"}],
        "failed_actions": [{"action_id": "act-2", "tool_name": "create_order", "error": "boom"}],
        "skipped_actions": [],
        "reason": "r",
    }
    with patch("app.api.routes.assert_owns"), \
         patch("app.utils.rollback_coordinator.RollbackCoordinator") as RC:
        RC.return_value.rollback_conversation = _AsyncReturn(partial)
        result = await R.rollback_conversation(
            _CONV, {"reason": "r"},
            ctx=OperatorContext(sub="op", tenant_id="t_a", role="admin", email="op@x"),
        )
    # No raise → 200; the batch body carries the per-item failure.
    assert result["failed_count"] == 1
    assert result["rolled_back_count"] == 1


@pytest.mark.asyncio
async def test_rollback_conversation_outer_except_message_is_sanitized():
    """The coordinator's total-failure message MUST NOT leak the raw exception string
    (which can carry ARNs/host/query text) across the API boundary — it returns a
    customer-safe message + correlation id and logs the internal detail server-side.
    FAILS if the raw str(e) is interpolated back into the returned message."""
    coord = RollbackCoordinator()
    secret = "AssumeRole arn:aws:iam::531109575379:role/secret-internal FAILED"

    async def _boom(*a, **k):
        raise RuntimeError(secret)

    # Force the outer-except path: the enumeration itself raises.
    coord.audit_logger.query_logs_by_conversation = _boom
    out = await coord.rollback_conversation(_CONV, reason="r", tenant_id="t_a")
    assert out["success"] is False
    assert secret not in out["message"]
    assert "arn:aws" not in out["message"].lower()
    assert out.get("correlation_id")


class _AsyncReturn:
    def __init__(self, val):
        self.val = val

    async def __call__(self, *a, **k):
        return self.val
