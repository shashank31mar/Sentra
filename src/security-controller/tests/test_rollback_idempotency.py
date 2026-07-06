"""Rollback idempotency ledger tests (WS-M M2.4 / lld/39 §3.4).

The prior replay guard (``rollback_status == 'ROLLED_BACK'`` on the immutable record)
was provably dead — that field is written once as ``NOT_ROLLED_BACK`` and never
mutated, and ``_rollback_refund`` was an unconditional ``update_item``. The fix is a
durable conditional-PutItem ledger keyed on ``action_id``: the first caller claims,
a duplicate/concurrent second caller fails the condition → "already rolled back".
"""
from __future__ import annotations

import json

import pytest
from botocore.exceptions import ClientError
from unittest.mock import Mock, patch

from app.utils.rollback_coordinator import RollbackCoordinator

_VALID = "act-process_refund-20260706120000-a1b2c3"


@pytest.fixture
def coordinator():
    with patch("app.utils.rollback_coordinator.boto3") as mock_boto3, \
         patch("app.utils.rollback_coordinator.AuditLogger"):
        logs = Mock()
        ddb = Mock()
        orders = Mock()
        ledger = Mock()
        mock_boto3.client.return_value = logs
        mock_boto3.resource.return_value = ddb
        # RollbackCoordinator.__init__ binds orders_table via dynamodb.Table('sentra-demo-orders');
        # _rollback_ledger_table() calls dynamodb.Table(<ledger name>) lazily. Route
        # Table() by name so the ledger and orders are distinct mocks.
        def _table(name):
            return ledger if "ledger" in name else orders
        ddb.Table.side_effect = _table
        c = RollbackCoordinator()
        c.cloudwatch_logs = logs
        c.dynamodb = ddb
        c.orders_table = orders
        c._ledger = ledger
        c._orders = orders
        yield c


def _mk_action(coordinator):
    coordinator.cloudwatch_logs.start_query.return_value = {"queryId": "q1"}
    coordinator.cloudwatch_logs.get_query_results.return_value = {
        "status": "Complete",
        "results": [[{"field": "@message", "value": json.dumps({
            "action_id": _VALID, "tool_name": "process_refund", "tenant_id": "t_a",
            "tool_params": {"order_id": "O1", "amount": 10},
            "rollback_status": "NOT_ROLLED_BACK"})}]],
    }


def _conditional_fail():
    return ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")


@pytest.mark.asyncio
async def test_rollback_ledger_conditional_put(coordinator):
    """The claim uses a conditional PutItem with attribute_not_exists(action_id)."""
    _mk_action(coordinator)
    await coordinator.rollback_action(action_id=_VALID, action_type="process_refund",
                                      reason="r", operator_id="op", tenant_id="t_a")
    put = coordinator._ledger.put_item.call_args
    assert put.kwargs["ConditionExpression"] == "attribute_not_exists(action_id)"
    assert put.kwargs["Item"]["action_id"] == _VALID


@pytest.mark.asyncio
async def test_serial_second_rollback_returns_already_done(coordinator):
    """A second serial rollback (ledger row already present → conditional fails)
    returns 'already rolled back' and does NOT reverse again."""
    _mk_action(coordinator)
    # First claim succeeds, second raises the conditional-check failure.
    coordinator._ledger.put_item.side_effect = [None, _conditional_fail()]

    first = await coordinator.rollback_action(action_id=_VALID, action_type="process_refund",
                                              reason="r", operator_id="op", tenant_id="t_a")
    assert first["success"] is True
    reverse_calls_after_first = coordinator._orders.update_item.call_count

    second = await coordinator.rollback_action(action_id=_VALID, action_type="process_refund",
                                               reason="r", operator_id="op", tenant_id="t_a")
    assert second["success"] is False
    assert "already rolled back" in second["message"].lower()
    # The reversal (orders update_item) did NOT run a second time.
    assert coordinator._orders.update_item.call_count == reverse_calls_after_first


@pytest.mark.asyncio
async def test_ledger_unavailable_fails_secure_denies(coordinator):
    """If the ledger is unavailable we DENY (never an un-guarded double-reverse)."""
    _mk_action(coordinator)
    coordinator._ledger.put_item.side_effect = RuntimeError("ledger down")
    out = await coordinator.rollback_action(action_id=_VALID, action_type="process_refund",
                                            reason="r", operator_id="op", tenant_id="t_a")
    assert out["success"] is False
    coordinator._orders.update_item.assert_not_called()


@pytest.mark.asyncio
async def test_failed_reversal_releases_claim_so_retry_can_reverse(coordinator):
    """WS-M M2.4 FIX-B (CRITICAL): the ledger claim is a TENTATIVE lock, not proof the
    reversal happened. When the reversal itself fails, the claim MUST be released so a
    legitimate retry can re-attempt — otherwise a money action that was NEVER reversed
    becomes permanently un-reversible (every retry hits ConditionalCheckFailedException
    → 'already rolled back'). This test FAILS against the pre-fix code (which left the
    claim on failure)."""
    _mk_action(coordinator)
    # First attempt: claim succeeds, then the reversal (orders update_item) BLOWS UP.
    coordinator._orders.update_item.side_effect = RuntimeError("orders table down")

    first = await coordinator.rollback_action(action_id=_VALID, action_type="process_refund",
                                              reason="r", operator_id="op", tenant_id="t_a")
    assert first["success"] is False, "a failed reversal must not report success"
    # The claim was RELEASED (delete_item on the ledger) so the row does not persist.
    coordinator._ledger.delete_item.assert_called_once()
    assert coordinator._ledger.delete_item.call_args.kwargs["Key"]["action_id"] == _VALID

    # Second attempt: the substrate is healthy now. The claim must be re-obtainable
    # (attribute_not_exists holds again because we released) and the reversal succeeds.
    coordinator._orders.update_item.side_effect = None
    coordinator._orders.update_item.reset_mock()
    second = await coordinator.rollback_action(action_id=_VALID, action_type="process_refund",
                                               reason="r", operator_id="op", tenant_id="t_a")
    assert second["success"] is True, "a genuinely-failed reversal MUST be retryable"
    coordinator._orders.update_item.assert_called_once()


@pytest.mark.asyncio
async def test_unimplemented_handler_releases_claim(coordinator):
    """A claimed action whose action_type has no reversal handler reverses NOTHING —
    so the claim must be released (nothing to be idempotent about) rather than
    permanently locking the action_id out of a future valid rollback."""
    # create_order is a REVERSIBLE_ACTIONS key but has no handler branch in
    # rollback_action → the 'handler not implemented' path.
    coordinator.cloudwatch_logs.start_query.return_value = {"queryId": "q1"}
    coordinator.cloudwatch_logs.get_query_results.return_value = {
        "status": "Complete",
        "results": [[{"field": "@message", "value": json.dumps({
            "action_id": _VALID, "tool_name": "create_order", "tenant_id": "t_a",
            "rollback_status": "NOT_ROLLED_BACK"})}]],
    }
    out = await coordinator.rollback_action(action_id=_VALID, action_type="create_order",
                                            reason="r", operator_id="op", tenant_id="t_a")
    assert out["success"] is False
    assert "not implemented" in out["message"].lower()
    coordinator._ledger.delete_item.assert_called_once()


@pytest.mark.asyncio
async def test_release_delete_failure_does_not_mask_reversal_error(coordinator):
    """If releasing the claim (ledger delete) itself fails, the ORIGINAL reversal error
    is still surfaced (delete failure is logged, never raised) — the response reflects
    the real failure, not a swallowed cleanup error."""
    _mk_action(coordinator)
    coordinator._orders.update_item.side_effect = RuntimeError("orders table down")
    coordinator._ledger.delete_item.side_effect = RuntimeError("ledger delete failed too")
    out = await coordinator.rollback_action(action_id=_VALID, action_type="process_refund",
                                            reason="r", operator_id="op", tenant_id="t_a")
    assert out["success"] is False
    assert "rollback failed" in out["message"].lower()
