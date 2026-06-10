"""Cloud adapter parsing — faithful to the real Bedrock/Azure interceptor shapes."""
from __future__ import annotations

import json

from aegion_guard import from_azure_request, from_bedrock_event


def test_bedrock_request_body_params():
    event = {
        "inputText": "show CA customers",
        "sessionId": "sess-123",
        "apiPath": "/query_customers",
        "requestBody": {
            "content": {
                "application/json": {
                    "properties": [{"name": "state", "value": "CA"}]
                }
            }
        },
    }
    ctx = from_bedrock_event(event)
    assert ctx == {
        "session_id": "sess-123",
        "user_input": "show CA customers",
        "tool_name": "query_customers",
        "params": {"state": "CA"},
        "request_id": None,
    }


def test_bedrock_parameters_array_fallback():
    event = {
        "inputText": "refund",
        "sessionId": "s",
        "apiPath": "/process_refund",
        "parameters": [
            {"name": "order_id", "value": "O1"},
            {"name": "amount", "value": "50"},
        ],
    }
    ctx = from_bedrock_event(event)
    assert ctx["tool_name"] == "process_refund"
    assert ctx["params"] == {"order_id": "O1", "amount": "50"}


def test_bedrock_threaded_request_id():
    event = {
        "apiPath": "/x",
        "sessionId": "s",
        "inputText": "hi",
        "sessionAttributes": {"sentra_request_id": "req-threaded-1"},
    }
    assert from_bedrock_event(event)["request_id"] == "req-threaded-1"


def test_bedrock_missing_fields_safe_defaults():
    ctx = from_bedrock_event({})
    assert ctx["session_id"] == "unknown"
    assert ctx["tool_name"] == ""
    assert ctx["params"] == {}


def test_azure_dict_shape():
    req = {
        "route_params": {"tool_name": "verify_identity"},
        "body": {"session_id": "s9", "user_input": "verify", "params": {"subscriber_id": "SUB1"}},
    }
    ctx = from_azure_request(req)
    assert ctx == {
        "session_id": "s9",
        "user_input": "verify",
        "tool_name": "verify_identity",
        "params": {"subscriber_id": "SUB1"},
        "request_id": None,
    }


def test_azure_params_at_top_level():
    req = {
        "route_params": {"tool_name": "reset_sim"},
        "body": {"session_id": "s", "user_input": "swap", "subscriber_id": "SUB1"},
    }
    ctx = from_azure_request(req)
    assert ctx["params"] == {"subscriber_id": "SUB1"}


def test_azure_httprequest_duck_type():
    class FakeReq:
        route_params = {"tool_name": "check_fraud_score"}

        def get_json(self):
            return {"session_id": "s", "user_input": "score", "params": {"id": "x"},
                    "request_id": "az-1"}

    ctx = from_azure_request(FakeReq())
    assert ctx["tool_name"] == "check_fraud_score"
    assert ctx["request_id"] == "az-1"


def test_azure_bytes_body():
    req = {
        "route_params": {"tool_name": "t"},
        "body": json.dumps({"session_id": "s", "user_input": "u"}).encode("utf-8"),
    }
    ctx = from_azure_request(req)
    assert ctx["session_id"] == "s"
