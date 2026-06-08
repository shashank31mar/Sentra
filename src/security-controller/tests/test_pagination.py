"""Unit tests for the canonical cursor pagination helpers (WS-21 T06)."""
import pytest

from app.utils.pagination import (
    encode_cursor,
    decode_cursor,
    next_token_from_response,
)


def test_encode_decode_round_trip():
    key = {"session_id": "s-1", "sk": "req#123#sigma"}
    token = encode_cursor(key)
    assert isinstance(token, str)
    assert decode_cursor(token) == key


def test_encode_is_opaque_base64():
    token = encode_cursor({"agent_id": "a-1"})
    # opaque: not human-readable JSON, decodes cleanly
    assert "agent_id" not in token
    assert decode_cursor(token) == {"agent_id": "a-1"}


def test_decode_invalid_raises_value_error():
    with pytest.raises(ValueError):
        decode_cursor("not-base64-at-all!!")


def test_decode_non_json_raises_value_error():
    import base64
    bad = base64.b64encode(b"not json").decode("ascii")
    with pytest.raises(ValueError):
        decode_cursor(bad)


def test_next_token_present_when_more_pages():
    resp = {"Items": [], "LastEvaluatedKey": {"agent_id": "a-9"}}
    token = next_token_from_response(resp)
    assert token is not None
    assert decode_cursor(token) == {"agent_id": "a-9"}


def test_next_token_none_on_last_page():
    assert next_token_from_response({"Items": []}) is None
    assert next_token_from_response({"Items": [], "LastEvaluatedKey": None}) is None
