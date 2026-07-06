"""Conversation-rollback cross-tenant IDOR + idempotency tests (WS-M M2.3 fix).

The CONFIRMED bug (caught by integration-sentinel): the conversation rollback path
mirrored NONE of the three single-action protections —

  1. the enumeration ``query_logs_by_conversation`` had NO tenant filter, so an admin
     of tenant A owning ONE event in a shared/colliding ``conversation_id`` could
     enumerate + reverse tenant B's reversible money actions;
  2. ``_rollback_single_action`` did NO per-action tenant re-verify; and
  3. it NEVER claimed the durable idempotency ledger, so two concurrent conversation
     rollbacks double-reversed each action (the in-log ``rollback_status`` filter is
     provably dead — written once, never mutated).

These tests exercise the REAL execution path (they do NOT AsyncMock the coordinator
away, and they do NOT AsyncMock ``query_logs_by_conversation`` — the prior tests did,
which is exactly why the missing filter went unseen). Each test FAILS if its
corresponding protection is reverted — that is the anti-regression bar the sentinel
demanded.
"""
from __future__ import annotations

import json

import pytest
from botocore.exceptions import ClientError
from unittest.mock import Mock, patch

from app.utils.audit_logger import AuditLogger
from app.utils.rollback_coordinator import RollbackCoordinator


_CONV = "conv-abc123"


# --------------------------------------------------------------------------- #
# Fixtures — a coordinator whose ledger/orders are DISTINCT mocks and whose
# audit_logger is a REAL AuditLogger over a mocked CloudWatch client, so the
# enumeration query is actually built and observable.
# --------------------------------------------------------------------------- #
@pytest.fixture
def coordinator():
    with patch("app.utils.rollback_coordinator.boto3") as rb_boto3, \
         patch("app.utils.audit_logger.boto3") as al_boto3, \
         patch("app.utils.audit_logger.SignalStoreWriter"):
        rb_logs = Mock()
        rb_ddb = Mock()
        orders = Mock()
        ledger = Mock()

        def _table(name):
            return ledger if "ledger" in name else orders

        rb_ddb.Table.side_effect = _table
        rb_boto3.client.return_value = rb_logs
        rb_boto3.resource.return_value = rb_ddb

        # A real AuditLogger, but its CloudWatch client is a mock we can spy on.
        al_logs = Mock()
        al_boto3.client.return_value = al_logs

        c = RollbackCoordinator()
        c.cloudwatch_logs = rb_logs
        c.dynamodb = rb_ddb
        c.orders_table = orders
        c._ledger = ledger
        c._orders = orders
        # Bind a real AuditLogger (not the patched-away MagicMock) with the spy client.
        c.audit_logger = AuditLogger()
        c.audit_logger.cloudwatch_logs = al_logs
        c._al_logs = al_logs
        yield c


def _enumeration_returns(coordinator, logs):
    """Wire the REAL query_logs_by_conversation substrate to return ``logs``."""
    coordinator._al_logs.start_query.return_value = {"queryId": "q1"}
    coordinator._al_logs.get_query_results.return_value = {
        "status": "Complete",
        "results": [
            [{"field": "@message", "value": json.dumps(log)}] for log in logs
        ],
    }


def _reversible(action_id, tenant_id, tool="process_refund", order="O1"):
    return {
        "action_id": action_id,
        "tool_name": tool,
        "operation_type": "WRITE",
        "decision": "ALLOW",
        "reversible": True,
        "rollback_status": "NOT_ROLLED_BACK",
        "tenant_id": tenant_id,
        "timestamp": "2026-07-06T00:00:00Z",
        "tool_params": {"order_id": order, "amount": 10},
    }


def _conditional_fail():
    return ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")


# --------------------------------------------------------------------------- #
# Protection 1 — the enumeration is TENANT-SCOPED (the query the route drives
# through the coordinator carries an exact tenant_id filter).
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_conversation_enumeration_is_tenant_scoped(coordinator):
    """rollback_conversation MUST pass tenant_id INTO query_logs_by_conversation, and
    the built Logs-Insights query MUST carry an exact tenant filter (never a substring
    `like`). FAILS if the tenant scoping is dropped from the enumeration."""
    _enumeration_returns(coordinator, [])  # zero owned events is a normal 0-count OK

    result = await coordinator.rollback_conversation(
        conversation_id=_CONV, reason="r", operator_id="op", tenant_id="t_a"
    )

    # 0 owned reversible actions is a normal success, not an error.
    assert result["success"] is True
    assert result["rolled_back_count"] == 0

    q = coordinator._al_logs.start_query.call_args.kwargs["queryString"]
    assert f'filter multi_agent_context.conversation_id = "{_CONV}"' in q
    assert 'filter tenant_id = "t_a"' in q
    assert " like " not in q


def test_query_logs_by_conversation_default_none_is_backward_compatible():
    """The new tenant_id param defaults to None → NO tenant clause (legacy callers)."""
    with patch("app.utils.audit_logger.boto3") as al_boto3, \
         patch("app.utils.audit_logger.SignalStoreWriter"):
        al_logs = Mock()
        al_boto3.client.return_value = al_logs
        al = AuditLogger()
        al.cloudwatch_logs = al_logs
        al_logs.start_query.return_value = {"queryId": "q1"}
        al_logs.get_query_results.return_value = {"status": "Complete", "results": []}

        import asyncio
        asyncio.get_event_loop().run_until_complete(
            al.query_logs_by_conversation(_CONV)
        )
        q = al_logs.start_query.call_args.kwargs["queryString"]
        assert f'filter multi_agent_context.conversation_id = "{_CONV}"' in q
        assert "filter tenant_id" not in q


# --------------------------------------------------------------------------- #
# Protection 2 — DEFENCE-IN-DEPTH: a foreign-tenant event that somehow slips into
# the batch is SKIPPED by the per-action re-verify and NEVER reversed.
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_foreign_tenant_action_skipped_never_reversed(coordinator):
    """Even if the enumeration returned a cross-tenant record (defence-in-depth), the
    per-action re-verify SKIPS it — the money action is never reversed. FAILS if the
    per-action tenant re-verify in _rollback_single_action is removed."""
    _enumeration_returns(coordinator, [
        _reversible("act-mine", "t_a", tool="process_refund", order="MINE"),
        _reversible("act-foreign", "t_OTHER", tool="process_refund", order="FOREIGN"),
    ])
    coordinator._orders.update_item.return_value = {}

    result = await coordinator.rollback_conversation(
        conversation_id=_CONV, reason="r", operator_id="op", tenant_id="t_a"
    )

    # Only the owned action reversed; the foreign one is skipped (not failed).
    assert result["rolled_back_count"] == 1
    assert result["skipped_count"] == 1
    assert result["failed_count"] == 0
    assert result["success"] is True
    reversed_ids = {a["action_id"] for a in result["rolled_back_actions"]}
    assert reversed_ids == {"act-mine"}
    # The foreign action was NEVER claimed in the ledger (skipped before the claim).
    claimed = {c.kwargs["Item"]["action_id"] for c in coordinator._ledger.put_item.call_args_list}
    assert "act-foreign" not in claimed


# --------------------------------------------------------------------------- #
# Protection 3 — IDEMPOTENCY on the CONVERSATION path (the _claim_rollback
# conditional PutItem trips on a second/concurrent rollback → no double-reverse).
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_conversation_claims_ledger_before_reversal(coordinator):
    """Each reversal claims the ledger via a conditional PutItem BEFORE reversing.
    FAILS if the idempotency claim is dropped from the conversation path."""
    _enumeration_returns(coordinator, [_reversible("act-mine", "t_a")])
    coordinator._orders.update_item.return_value = {}

    await coordinator.rollback_conversation(
        conversation_id=_CONV, reason="r", operator_id="op", tenant_id="t_a"
    )

    put = coordinator._ledger.put_item.call_args
    assert put.kwargs["ConditionExpression"] == "attribute_not_exists(action_id)"
    assert put.kwargs["Item"]["action_id"] == "act-mine"


@pytest.mark.asyncio
async def test_second_conversation_rollback_does_not_double_reverse(coordinator):
    """A second/concurrent conversation rollback of the same action fails the
    conditional-put claim → the action is skipped (already done) and the reversal
    (orders update_item) does NOT run twice. FAILS if the claim is dropped."""
    _enumeration_returns(coordinator, [_reversible("act-mine", "t_a")])
    coordinator._orders.update_item.return_value = {}
    # First rollback claims OK; the concurrent second claim fails the condition.
    coordinator._ledger.put_item.side_effect = [None, _conditional_fail()]

    first = await coordinator.rollback_conversation(
        conversation_id=_CONV, reason="r", operator_id="op", tenant_id="t_a"
    )
    assert first["rolled_back_count"] == 1
    reverse_calls_after_first = coordinator._orders.update_item.call_count
    assert reverse_calls_after_first == 1

    second = await coordinator.rollback_conversation(
        conversation_id=_CONV, reason="r", operator_id="op", tenant_id="t_a"
    )
    # The already-claimed action is skipped, not reversed again, not failed.
    assert second["rolled_back_count"] == 0
    assert second["skipped_count"] == 1
    assert second["failed_count"] == 0
    assert second["success"] is True
    # The money reversal did NOT run a second time.
    assert coordinator._orders.update_item.call_count == reverse_calls_after_first


@pytest.mark.asyncio
async def test_failed_reversal_releases_claim_on_conversation_path(coordinator):
    """A reversal that raises RELEASES its tentative claim (delete_item) so a retry can
    re-attempt an un-reversed money action — mirrors the single-action FIX-B."""
    _enumeration_returns(coordinator, [_reversible("act-mine", "t_a")])
    coordinator._orders.update_item.side_effect = RuntimeError("orders table down")

    result = await coordinator.rollback_conversation(
        conversation_id=_CONV, reason="r", operator_id="op", tenant_id="t_a"
    )

    assert result["failed_count"] == 1
    assert result["success"] is False
    coordinator._ledger.delete_item.assert_called_once()
    assert coordinator._ledger.delete_item.call_args.kwargs["Key"]["action_id"] == "act-mine"


# --------------------------------------------------------------------------- #
# Backward-compat — a legacy call with tenant_id=None still works (no re-verify,
# still claims). Guards against the fix breaking the demo/offline path.
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_tenant_none_reverts_to_legacy_no_reverify(coordinator):
    """With tenant_id=None the per-action re-verify is skipped (legacy behaviour) but
    the reversal + claim still run — a foreign-looking tenant_id is NOT filtered."""
    _enumeration_returns(coordinator, [_reversible("act-x", "t_whatever")])
    coordinator._orders.update_item.return_value = {}

    result = await coordinator.rollback_conversation(
        conversation_id=_CONV, reason="r", operator_id="op"
    )
    assert result["rolled_back_count"] == 1
    assert result["skipped_count"] == 0
