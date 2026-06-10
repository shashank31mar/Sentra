"""operation_type inference: auto heuristic, substring misfires, explicit-wins."""
from __future__ import annotations

import pytest

from aegion_guard import infer_operation_type


@pytest.mark.parametrize(
    "name,expected",
    [
        ("process_refund", "WRITE"),
        ("transfer_funds", "WRITE"),
        ("reset_sim", "WRITE"),
        ("port_out_number", "WRITE"),
        ("change_plan", "WRITE"),
        ("create_ticket", "WRITE"),
        ("update_profile", "WRITE"),
        ("delete_record", "WRITE"),
        ("lookup_account", "READ"),
        ("get_transactions", "READ"),
        ("verify_identity", "READ"),
        ("check_fraud_score", "READ"),
    ],
)
def test_auto_inference(name, expected):
    assert infer_operation_type(name) == expected


def test_substring_misfire_is_documented_behavior():
    # "update" is a substring of get_update_history → auto MIS-classifies as WRITE.
    # This is the known fragility (LLD 23 §3.1); explicit op_type is the fix.
    assert infer_operation_type("get_update_history") == "WRITE"


def test_explicit_operation_type_wins(make_guard, fake_client):
    guard = make_guard()

    # name says READ-ish, but we force WRITE explicitly.
    @guard.tool(operation_type="WRITE")
    def lookup_account(account_id):
        return "ran"

    with guard.session(session_id="s1", user_input="hi"):
        lookup_account("A1")
    assert fake_client.last["operation_type"] == "WRITE"


def test_auto_sends_inferred_value(make_guard, fake_client):
    guard = make_guard()

    @guard.tool()  # auto
    def transfer_funds(a, b):
        return "ran"

    with guard.session(session_id="s1", user_input="hi"):
        transfer_funds("A1", 5)
    assert fake_client.last["operation_type"] == "WRITE"


def test_invalid_explicit_op_type_raises(make_guard, fake_client):
    guard = make_guard()

    @guard.tool(operation_type="SIDEWAYS")
    def thing():
        return "ran"

    with guard.session(session_id="s1", user_input="hi"):
        with pytest.raises(Exception):  # ConfigError (ValueError subclass)
            thing()
