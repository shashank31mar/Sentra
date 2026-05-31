"""Unit tests for the Azure Function tool_interceptor — Kiro M4 review Issue #15.

The Function is the single point between the Azure agent and the Sentra
controller. A silent regression in validate_with_sentra would fail-secure
every Azure call after the demo recording with no obvious symptom. These
tests lock the contract in:

  - ALLOW path executes the tool and returns 200 with `result`
  - DENY path returns 403 and never executes the tool
  - HTTPError from controller -> fail-secure DENY (not a 500)
  - URLError (network) -> fail-secure DENY (not a 500)
  - Non-JSON 200 body -> fail-secure DENY
  - Unknown tool name -> 404 without touching Sentra
  - Missing session_id -> 400 without touching Sentra

The `azure.functions` SDK is stubbed in sys.modules before import so the test
file runs without an extra pip dependency on the dashboard side.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import types
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = (
    REPO_ROOT
    / "src"
    / "connectors"
    / "azure_foundry"
    / "azure_function"
    / "tool_interceptor"
    / "function_app.py"
)


# ---------------------------------------------------------------------------
# azure.functions stub — minimal surface area to satisfy function_app imports.
# ---------------------------------------------------------------------------
class _FakeHttpRequest:
    def __init__(self, route_params=None, body=None):
        self.route_params = route_params or {}
        self._body = body if body is not None else {}

    def get_json(self):
        if isinstance(self._body, str) and self._body == "__invalid__":
            raise ValueError("invalid json")
        return self._body


class _FakeHttpResponse:
    def __init__(self, body=None, status_code=200, mimetype=None):
        self.body = body
        self.status_code = status_code
        self.mimetype = mimetype

    def get_body(self) -> bytes:
        if isinstance(self.body, bytes):
            return self.body
        return (self.body or "").encode("utf-8")


class _AuthLevel:
    ANONYMOUS = "anonymous"


class _FakeFunctionApp:
    def __init__(self, http_auth_level=None):
        self.http_auth_level = http_auth_level
        self._routes = {}

    def route(self, route=None, methods=None, auth_level=None):
        def decorator(fn):
            self._routes[(route, tuple(methods or []))] = fn
            return fn
        return decorator


def _install_azure_stub():
    """Insert a fake `azure.functions` into sys.modules before import."""
    azure_pkg = types.ModuleType("azure")
    func_mod = types.ModuleType("azure.functions")
    func_mod.HttpRequest = _FakeHttpRequest
    func_mod.HttpResponse = _FakeHttpResponse
    func_mod.AuthLevel = _AuthLevel
    func_mod.FunctionApp = _FakeFunctionApp
    azure_pkg.functions = func_mod
    sys.modules["azure"] = azure_pkg
    sys.modules["azure.functions"] = func_mod


@pytest.fixture
def function_app(monkeypatch):
    """Import the function_app module fresh with config env vars + azure stub set."""
    _install_azure_stub()
    monkeypatch.setenv("SENTRA_API_ENDPOINT", "https://fake-apigw/prod/v1/validate")
    monkeypatch.setenv("SENTRA_API_KEY", "fake-key")
    monkeypatch.setenv("SENTRA_PLATFORM", "azure_foundry")
    monkeypatch.setenv("SENTRA_CLOUD_REGION", "centralus")

    # Force a fresh import so module-level config picks up the env vars.
    sys.modules.pop("function_app_under_test", None)
    spec = importlib.util.spec_from_file_location("function_app_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _allow_response(reason: str = "ok") -> MagicMock:
    """urllib.request.urlopen() context manager returning a 200 ALLOW body."""
    body = json.dumps({"decision": "ALLOW", "reason": reason}).encode("utf-8")
    cm = MagicMock()
    cm.__enter__.return_value = MagicMock(status=200, read=MagicMock(return_value=body))
    return cm


def _make_request(tool_name: str, body: dict | str | None) -> _FakeHttpRequest:
    return _FakeHttpRequest(route_params={"tool_name": tool_name}, body=body)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_allow_path_executes_tool_and_returns_200(function_app):
    """Happy path: Sentra ALLOWs, tool runs, response includes the result."""
    req = _make_request("check_fraud_score", {
        "params": {"transaction_id": "tx-001"},
        "session_id": "sess-1",
        "user_input": "check this transaction",
    })
    with patch("urllib.request.urlopen", return_value=_allow_response()):
        resp = function_app.tool_call(req)

    assert resp.status_code == 200
    payload = json.loads(resp.get_body())
    assert payload["decision"] == "ALLOW"
    assert payload["tool_name"] == "check_fraud_score"
    # Deterministic mock: tx-001 has no "high" -> low-risk score
    assert payload["result"]["score"] == 12


def test_deny_path_returns_403_and_does_not_execute_tool(function_app):
    """If Sentra DENYs, the tool function must not run."""
    deny_body = json.dumps({"decision": "DENY", "reason": "policy violation"}).encode("utf-8")
    deny_cm = MagicMock()
    deny_cm.__enter__.return_value = MagicMock(status=200, read=MagicMock(return_value=deny_body))

    req = _make_request("verify_image_authenticity", {
        "params": {"image_url": "https://x/fake.jpg", "expected_subject": "eggs"},
        "session_id": "sess-2",
        "user_input": "verify this",
    })
    # Spy on the tool function to confirm it's not invoked.
    with patch("urllib.request.urlopen", return_value=deny_cm), \
         patch.object(function_app, "execute_verify_image_authenticity") as tool_spy:
        resp = function_app.tool_call(req)

    assert resp.status_code == 403
    tool_spy.assert_not_called()
    payload = json.loads(resp.get_body())
    assert payload["decision"] == "DENY"
    assert payload["reason"] == "policy violation"


def test_http_error_from_controller_fails_secure(function_app):
    """A 5xx (or 403) from the controller must surface as DENY, not a 500."""
    err = urllib.error.HTTPError(
        url="https://fake-apigw/prod/v1/validate",
        code=502,
        msg="Bad Gateway",
        hdrs=None,
        fp=io.BytesIO(b'{"detail":"controller down"}'),
    )
    req = _make_request("check_fraud_score", {
        "params": {"transaction_id": "tx-002"},
        "session_id": "sess-3",
        "user_input": "x",
    })
    with patch("urllib.request.urlopen", side_effect=err):
        resp = function_app.tool_call(req)

    assert resp.status_code == 403, "HTTPError must fail-secure to DENY, never 500"
    payload = json.loads(resp.get_body())
    assert payload["decision"] == "DENY"
    assert "HTTP 502" in payload["reason"]


def test_url_error_from_controller_fails_secure(function_app):
    """A network error must surface as DENY, not a 500."""
    req = _make_request("check_fraud_score", {
        "params": {"transaction_id": "tx-003"},
        "session_id": "sess-4",
        "user_input": "x",
    })
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("dns lookup failed")):
        resp = function_app.tool_call(req)

    assert resp.status_code == 403
    payload = json.loads(resp.get_body())
    assert payload["decision"] == "DENY"
    assert "unreachable" in payload["reason"]


def test_non_json_200_body_fails_secure(function_app):
    """If the controller returns 200 with garbage, treat as DENY."""
    bad_cm = MagicMock()
    bad_cm.__enter__.return_value = MagicMock(
        status=200, read=MagicMock(return_value=b"<html>oops</html>")
    )
    req = _make_request("check_fraud_score", {
        "params": {"transaction_id": "tx-004"},
        "session_id": "sess-5",
        "user_input": "x",
    })
    with patch("urllib.request.urlopen", return_value=bad_cm):
        resp = function_app.tool_call(req)

    assert resp.status_code == 403
    payload = json.loads(resp.get_body())
    assert payload["decision"] == "DENY"
    assert "invalid JSON" in payload["reason"]


def test_unknown_tool_returns_404_without_calling_sentra(function_app):
    """Routing should reject unknown tool names before touching Sentra."""
    req = _make_request("not_a_real_tool", {"params": {}, "session_id": "sess-6", "user_input": "x"})
    with patch("urllib.request.urlopen") as urlopen_spy:
        resp = function_app.tool_call(req)

    urlopen_spy.assert_not_called()
    assert resp.status_code == 404


def test_missing_session_id_returns_400(function_app):
    """A request without session_id must 400 before touching Sentra — every audit
    log entry needs a session_id, so accepting an empty one would silently drop
    correlation."""
    req = _make_request("check_fraud_score", {"params": {}, "user_input": "x"})  # no session_id
    with patch("urllib.request.urlopen") as urlopen_spy:
        resp = function_app.tool_call(req)

    urlopen_spy.assert_not_called()
    assert resp.status_code == 400


def test_invalid_json_body_returns_400(function_app):
    """If the inbound body isn't JSON, return 400 not 500."""
    req = _make_request("check_fraud_score", "__invalid__")  # triggers ValueError in _FakeHttpRequest
    with patch("urllib.request.urlopen") as urlopen_spy:
        resp = function_app.tool_call(req)

    urlopen_spy.assert_not_called()
    assert resp.status_code == 400


def test_validation_payload_marks_write_for_refund_tools(function_app):
    """WRITE/READ heuristic must mirror the Bedrock Lambda — refund/modify/delete
    tools mark WRITE so the policy engine can rate-limit + audit appropriately.
    This is what makes the controller's audit table cross-cloud-uniform."""
    captured_payloads = []

    def capturing_urlopen(req, timeout=None):
        captured_payloads.append(json.loads(req.data.decode("utf-8")))
        return _allow_response()

    # Use a tool name with "refund" in it
    req = _make_request("check_fraud_score", {  # check_fraud_score is in TOOL_DISPATCH
        "params": {"transaction_id": "tx-007"},
        "session_id": "sess-7",
        "user_input": "x",
    })
    with patch("urllib.request.urlopen", side_effect=capturing_urlopen):
        function_app.tool_call(req)

    assert len(captured_payloads) == 1
    # check_fraud_score is a READ tool
    assert captured_payloads[0]["operation_type"] == "READ"
    assert captured_payloads[0]["platform"] == "azure_foundry"
    assert captured_payloads[0]["cloud_region"] == "centralus"
    assert captured_payloads[0]["agent_id"] == "azure-verification-agent"


def test_health_reports_config_present(function_app):
    """Health endpoint must expose whether SENTRA_* config was read at cold-start —
    this is the documented escape hatch in Kiro's review Issue #6."""
    req = _FakeHttpRequest()
    resp = function_app.health(req)
    payload = json.loads(resp.get_body())
    assert resp.status_code == 200
    assert payload["status"] == "healthy"
    assert payload["config_present"]["SENTRA_API_ENDPOINT"] is True
    assert payload["config_present"]["SENTRA_API_KEY"] is True
    assert "verify_image_authenticity" in payload["tools_registered"]
    assert "check_fraud_score" in payload["tools_registered"]


def test_tool_execution_failure_returns_500(function_app):
    """If the tool itself blows up post-ALLOW, surface a 500 — this is a tool
    bug, not a security event, and a DENY would mislead audit triage.

    Note: TOOL_DISPATCH captures function references at module-load time, so we
    swap the dict entry directly rather than patching the module attribute.
    """
    req = _make_request("check_fraud_score", {
        "params": {"transaction_id": "tx-008"},
        "session_id": "sess-8",
        "user_input": "x",
    })

    def boom(_params):
        raise RuntimeError("kaboom")

    original = function_app.TOOL_DISPATCH["check_fraud_score"]
    function_app.TOOL_DISPATCH["check_fraud_score"] = boom
    try:
        with patch("urllib.request.urlopen", return_value=_allow_response()):
            resp = function_app.tool_call(req)
    finally:
        function_app.TOOL_DISPATCH["check_fraud_score"] = original

    assert resp.status_code == 500
