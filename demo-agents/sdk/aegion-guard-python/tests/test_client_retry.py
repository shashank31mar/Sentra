"""client.py transport semantics — the connect-retry vs read-timeout subtlety.

The most important behavior here (LLD 23 §12.1 caveat 1): a read-timeout must
NOT be retried (retrying just doubles the wall-clock before fail-secure), while a
connection-establishment failure (DNS/refused) IS retried up to connect_retries.
"""
from __future__ import annotations

import socket
import urllib.error

import pytest

from aegion_guard.client import TransportError, ValidateClient


def _client(monkeypatch, urlopen_side_effects, connect_retries=2):
    client = ValidateClient(
        validate_url="https://x.example.com/prod/v1/validate",
        api_key="k",
        timeout_s=5.0,
        connect_retries=connect_retries,
        user_agent="test",
    )
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None, context=None):
        i = calls["n"]
        calls["n"] += 1
        effect = urlopen_side_effects[min(i, len(urlopen_side_effects) - 1)]
        if isinstance(effect, BaseException):
            raise effect
        return effect  # a context-manager-like fake

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    return client, calls


class _FakeResp:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        return self._body


def test_connection_error_is_retried(monkeypatch):
    # First two attempts: DNS/connection error; third: success.
    refused = urllib.error.URLError(ConnectionRefusedError("refused"))
    ok = _FakeResp(b'{"decision":"ALLOW"}')
    client, calls = _client(monkeypatch, [refused, refused, ok], connect_retries=2)
    monkeypatch.setattr("time.sleep", lambda *_: None)

    result = client.post({"x": 1})
    assert result["decision"] == "ALLOW"
    assert calls["n"] == 3  # two failures + one success


def test_read_timeout_is_not_retried(monkeypatch):
    # socket.timeout must fail immediately, NOT consume retries.
    client, calls = _client(monkeypatch, [socket.timeout("timed out")], connect_retries=3)
    monkeypatch.setattr("time.sleep", lambda *_: None)

    with pytest.raises(TransportError) as exc:
        client.post({"x": 1})
    assert "timed out" in str(exc.value)
    assert calls["n"] == 1  # no retries despite connect_retries=3


def test_urlerror_wrapping_timeout_is_not_retried(monkeypatch):
    # urllib sometimes wraps a read-timeout as URLError(reason=socket.timeout).
    wrapped = urllib.error.URLError(socket.timeout("timed out"))
    client, calls = _client(monkeypatch, [wrapped], connect_retries=3)
    monkeypatch.setattr("time.sleep", lambda *_: None)

    with pytest.raises(TransportError) as exc:
        client.post({"x": 1})
    assert "timed out" in str(exc.value)
    assert calls["n"] == 1


def test_http_error_not_retried(monkeypatch):
    err = urllib.error.HTTPError(
        url="u", code=403, msg="Forbidden", hdrs=None, fp=None
    )
    client, calls = _client(monkeypatch, [err], connect_retries=3)
    with pytest.raises(TransportError) as exc:
        client.post({"x": 1})
    assert "403" in str(exc.value)
    assert calls["n"] == 1


def test_non_json_body_is_transport_error(monkeypatch):
    client, _ = _client(monkeypatch, [_FakeResp(b"<html>nope</html>")])
    with pytest.raises(TransportError, match="not valid JSON"):
        client.post({"x": 1})


def test_transport_error_carries_status_code(monkeypatch):
    """WS-B (LLD 30 §3.6): a non-2xx HTTPError sets TransportError.status_code
    from exc.code (so the guard can tell a 422 from a 5xx); a timeout/connection
    error — no HTTP response — leaves it None."""
    # 422 from a non-2xx HTTP response → status_code == 422.
    err_422 = urllib.error.HTTPError(url="u", code=422, msg="Unprocessable", hdrs=None, fp=None)
    client, _ = _client(monkeypatch, [err_422], connect_retries=0)
    with pytest.raises(TransportError) as exc:
        client.post({"x": 1})
    assert exc.value.status_code == 422

    # 502 gateway error → status_code == 502 (NOT 422 — must stay fail-secure).
    err_502 = urllib.error.HTTPError(url="u", code=502, msg="Bad Gateway", hdrs=None, fp=None)
    client, _ = _client(monkeypatch, [err_502], connect_retries=0)
    with pytest.raises(TransportError) as exc:
        client.post({"x": 1})
    assert exc.value.status_code == 502

    # Read-timeout: the request was sent but no HTTP response arrived → None.
    client, _ = _client(monkeypatch, [socket.timeout("timed out")], connect_retries=0)
    monkeypatch.setattr("time.sleep", lambda *_: None)
    with pytest.raises(TransportError) as exc:
        client.post({"x": 1})
    assert exc.value.status_code is None


def test_retries_exhausted_raises(monkeypatch):
    refused = urllib.error.URLError(ConnectionRefusedError("refused"))
    client, calls = _client(monkeypatch, [refused], connect_retries=2)
    monkeypatch.setattr("time.sleep", lambda *_: None)
    with pytest.raises(TransportError):
        client.post({"x": 1})
    assert calls["n"] == 3  # initial + 2 retries
