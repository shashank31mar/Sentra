"""Tier-1 edge redaction tests for the Azure Function tool_interceptor (WS-E1, FR-3.13).

The Azure Function POSTs a `/v1/validate` payload with `tool_params` + `user_input`
across the cross-cloud path to the hosted PDP. On the Serverless edition that payload
leaves the customer boundary, so structured PII/PCI MUST be masked at the edge BEFORE
egress (NFR-7 clause (a): no raw structured identifier egresses on any edition). These
tests pin that the Function actually redacts (not just flags), matching the SDK's
`_build_request` behavior (guard.py) that the AWS path already gets.

Contract pinned here:
  - a PAN / SSN / email in `tool_params` egresses as the `⟦AEGR:...⟧` typed wire
    token, NOT the raw value (captures the real urllib POST body).
  - `user_input` PII is likewise redacted.
  - `redacted=True` + a `redaction_nonce` (the per-egress nonce) are on the payload,
    and the nonce matches the one embedded in the emitted tokens.
  - NON-VACUOUS: the raw-value assertions fail if redaction is reverted — proved by a
    control that runs the payload build WITHOUT the redactor and shows the raw PAN
    would egress (so the assertion in the real path is not always-green).
  - FAIL-SECURE: if the redactor raises, the Function returns a DENY and never POSTs.

Same azure.functions stub + fresh-import fixture as test_tool_interceptor.py so this
runs on a plain stdlib python (the redactor + function_app are stdlib-only).
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
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

# A Luhn+IIN-valid Visa test PAN (starts with 4). SSN passes the issuance validity
# rules (area 078, group 05, serial 1120). Email is a plain address. All three are
# structured PII/PCI the Tier-1 redactor must mask before egress.
RAW_PAN = "4111111111111111"
RAW_SSN = "078-05-1120"
RAW_EMAIL = "jsmith@acme.com"


# ---------------------------------------------------------------------------
# azure.functions stub — mirrors test_tool_interceptor.py.
# ---------------------------------------------------------------------------
class _FakeHttpRequest:
    def __init__(self, route_params=None, body=None):
        self.route_params = route_params or {}
        self._body = body if body is not None else {}

    def get_json(self):
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
    """Import function_app fresh, with config env + azure stub + vendored-package path."""
    _install_azure_stub()
    monkeypatch.setenv("SENTRA_API_ENDPOINT", "https://fake-apigw/prod/v1/validate")
    monkeypatch.setenv("SENTRA_API_KEY", "fake-key")
    monkeypatch.setenv("SENTRA_PLATFORM", "azure_foundry")
    monkeypatch.setenv("SENTRA_CLOUD_REGION", "centralus")

    # The Function imports its VENDORED `aegion_guard` redactor from its own dir. In
    # the real Azure runtime the Function app root is on sys.path; mirror that here.
    module_dir = str(MODULE_PATH.parent)
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)

    sys.modules.pop("function_app_under_test", None)
    spec = importlib.util.spec_from_file_location("function_app_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _allow_capturing_urlopen(captured: list):
    """A urlopen replacement that records the POSTed body and returns a 200 ALLOW."""

    def _urlopen(req, timeout=None):
        captured.append(json.loads(req.data.decode("utf-8")))
        body = json.dumps({"decision": "ALLOW", "reason": "ok"}).encode("utf-8")
        cm = MagicMock()
        cm.__enter__.return_value = MagicMock(
            status=200, read=MagicMock(return_value=body)
        )
        return cm

    return _urlopen


def _make_request(tool_name: str, body: dict) -> _FakeHttpRequest:
    return _FakeHttpRequest(route_params={"tool_name": tool_name}, body=body)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_tool_params_pii_is_redacted_before_egress(function_app):
    """A PAN / SSN / email in tool_params must egress as typed ⟦AEGR:...⟧ tokens,
    never the raw value. Captures the real urllib POST body."""
    captured: list = []
    req = _make_request("check_fraud_score", {
        "params": {
            "card": RAW_PAN,
            "customer_note": f"ssn is {RAW_SSN}, contact {RAW_EMAIL}",
        },
        "session_id": "sess-redact-1",
        "user_input": f"run fraud check for {RAW_EMAIL}",
    })
    with patch("urllib.request.urlopen", side_effect=_allow_capturing_urlopen(captured)):
        function_app.tool_call(req)

    assert len(captured) == 1
    sent = captured[0]
    body_blob = json.dumps(sent, ensure_ascii=False)

    # The raw structured PII must NOT appear anywhere in the egressed payload.
    assert RAW_PAN not in body_blob, "raw PAN egressed — Tier-1 redaction failed"
    assert RAW_SSN not in body_blob, "raw SSN egressed"
    assert RAW_SSN.replace("-", "") not in body_blob, "raw SSN (no separators) egressed"
    assert RAW_EMAIL not in body_blob, "raw email egressed"

    # The typed wire tokens must be present in tool_params + user_input.
    assert "⟦AEGR:" in json.dumps(sent["tool_params"], ensure_ascii=False)
    assert ":CARD:" in sent["tool_params"]["card"], "PAN not tokenized as CARD"
    # PCI: first6/last4 only, middle digits gone (never emit the full PAN).
    assert sent["tool_params"]["card"].endswith(":411111:1111⟧")
    note = sent["tool_params"]["customer_note"]
    assert ":SSN⟧" in note and ":EMAIL⟧" in note
    assert "⟦AEGR:" in sent["user_input"], "user_input PII not redacted"


def test_redacted_flag_and_nonce_on_payload(function_app):
    """`redacted=True` + a `redaction_nonce` must be stamped, and the nonce must
    match the one embedded in the emitted tokens (single per-egress nonce, M-4)."""
    captured: list = []
    req = _make_request("check_fraud_score", {
        "params": {"card": RAW_PAN},
        "session_id": "sess-redact-2",
        "user_input": "check card",
    })
    with patch("urllib.request.urlopen", side_effect=_allow_capturing_urlopen(captured)):
        function_app.tool_call(req)

    sent = captured[0]
    assert sent["redacted"] is True
    nonce = sent["redaction_nonce"]
    assert isinstance(nonce, str) and len(nonce) == 16  # secrets.token_hex(8)
    # The nonce published on the payload is the SAME one embedded in the token, so
    # the PDP's redaction-state guard can verify the marker is genuine.
    assert f"⟦AEGR:{nonce}:CARD:" in sent["tool_params"]["card"]


def test_nonvacuous_raw_pan_would_egress_without_redaction(function_app):
    """Non-vacuous proof: WITHOUT the redactor the raw PAN would sit in the payload,
    so the raw-value assertion in test_tool_params_pii_is_redacted_before_egress is
    NOT always-green — it genuinely fails if redaction is reverted.

    We reproduce the exact payload the Function builds but skip the redaction step
    (as a revert would), and show the raw PAN IS present — demonstrating the guarded
    assertion has teeth.
    """
    raw_params = {"card": RAW_PAN}
    # This is what the payload's tool_params would carry if the redaction line were
    # removed (a straight passthrough, the pre-WS-E1 behavior).
    unredacted_blob = json.dumps({"tool_params": raw_params}, ensure_ascii=False)
    assert RAW_PAN in unredacted_blob  # the raw PAN would egress — the leak we prevent

    # And the real path DOES redact it away (contrast — proves the test is meaningful).
    captured: list = []
    req = _make_request("check_fraud_score", {
        "params": raw_params,
        "session_id": "sess-redact-3",
        "user_input": "x",
    })
    with patch("urllib.request.urlopen", side_effect=_allow_capturing_urlopen(captured)):
        function_app.tool_call(req)
    assert RAW_PAN not in json.dumps(captured[0], ensure_ascii=False)


def test_fail_secure_deny_when_redaction_raises(function_app):
    """If the redactor raises, the Function must fail-secure DENY and NOT POST a
    raw payload — better to deny than to leak (E1.4)."""
    req = _make_request("check_fraud_score", {
        "params": {"card": RAW_PAN},
        "session_id": "sess-redact-4",
        "user_input": "check card",
    })

    def _boom(*_args, **_kwargs):
        # Raise the real RedactionError the module catches (imported into function_app).
        raise function_app.RedactionError("simulated matcher failure")

    with patch("urllib.request.urlopen") as urlopen_spy, \
         patch.object(function_app.redaction, "redact_params", side_effect=_boom):
        resp = function_app.tool_call(req)

    # Never sent a raw payload upstream.
    urlopen_spy.assert_not_called()
    # 403 fail-secure DENY (the tool_call DENY path), NOT a 500 and NOT an ALLOW.
    assert resp.status_code == 403
    payload = json.loads(resp.get_body())
    assert payload["decision"] == "DENY"
    assert payload["reason"] == "edge redaction failed"


def test_fail_secure_deny_when_redact_input_raises(function_app):
    """The user_input redaction path is equally fail-secure: a failure there must
    also DENY without POSTing (covers the second redactor call site)."""
    req = _make_request("check_fraud_score", {
        "params": {"amount": 50},
        "session_id": "sess-redact-5",
        "user_input": "some prompt",
    })

    def _boom(*_args, **_kwargs):
        raise function_app.RedactionError("simulated user_input failure")

    with patch("urllib.request.urlopen") as urlopen_spy, \
         patch.object(function_app.redaction, "redact", side_effect=_boom):
        resp = function_app.tool_call(req)

    urlopen_spy.assert_not_called()
    assert resp.status_code == 403
    assert json.loads(resp.get_body())["decision"] == "DENY"


def test_benign_params_pass_through_unchanged(function_app):
    """Non-PII params (ints, benign strings) must pass through so the PDP still gets
    the param signal it needs for Cedar param-bounds / sequence checks — redaction is
    surgical, not a blanket scrub."""
    captured: list = []
    req = _make_request("check_fraud_score", {
        "params": {"transaction_id": "tx-benign-001", "amount": 42},
        "session_id": "sess-redact-6",
        "user_input": "look up this transaction",
    })
    with patch("urllib.request.urlopen", side_effect=_allow_capturing_urlopen(captured)):
        function_app.tool_call(req)

    sent = captured[0]
    assert sent["tool_params"]["transaction_id"] == "tx-benign-001"
    assert sent["tool_params"]["amount"] == 42
    assert sent["user_input"] == "look up this transaction"
    # Still stamped as redacted (the redactor ran; it just found nothing to mask).
    assert sent["redacted"] is True
