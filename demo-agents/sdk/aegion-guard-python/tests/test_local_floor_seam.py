"""WS-A (lld/36) — the frozen LocalFloorVerdict enum + the no-op local-floor seam.

The seam is a PLUG, not a feature: in SDK 0.2.0 there is no interpreter, so every
state routes to the hosted PDP (fail-secure). These tests pin:

  * A2.1 — the LocalFloorVerdict enum is frozen (exactly four members + values).
  * A3.2/A3.3 — flag off → `_send` reached (sync + async); flag on without an
    interpreter → still routes to `_send` (never local-allow / skip / deny-all);
    the "floor absent" WARNING fires once per guard and leaks no payload.
  * type contract — `_local_floor_verdict` returns a Decision or None, never a
    bare LocalFloorVerdict (a str-Enum reads truthy → fail-OPEN).
  * A3.4 — AST: every `_send` reference in guard.py is dominated by a
    `_local_floor_verdict` reference in the same function; import-graph: the
    aegion_guard package has no path to app.combiners (no Signal minted).
"""
from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest

from aegion_guard import Decision, LocalFloorVerdict
from aegion_guard.guard import AegionGuard

_GUARD_PY = Path(__file__).resolve().parents[1] / "src" / "aegion_guard" / "guard.py"


# ================================================================ A2.1 enum frozen


def test_verdict_enum_frozen():
    """The LocalFloorVerdict contract is FROZEN: exactly the four members with
    their exact string values. lld/37 + WS-J code against these names, so a member
    added / removed / renamed / re-valued is a contract change that must fail here
    (not slip in silently). Non-vacuous: any drift in the member set or a value
    trips one of these asserts."""
    members = {m.name: m.value for m in LocalFloorVerdict}
    assert members == {
        "LOCAL_ALLOW": "LOCAL_ALLOW",
        "LOCAL_DENY": "LOCAL_DENY",
        "ESCALATE": "ESCALATE",
        "DENY_BY_DEFAULT": "DENY_BY_DEFAULT",
    }
    # str-Enum so a member serializes as its plain string value on the wire.
    assert issubclass(LocalFloorVerdict, str)
    assert LocalFloorVerdict.ESCALATE == "ESCALATE"


# ================================================================ A3.2/A3.3 seam


def test_seam_off_routes_to_send(make_guard, fake_client):
    """STATE 1 (default, flag off): _local_floor_verdict returns None and _send is
    reached exactly once — the sync path is a true no-op."""
    guard = make_guard()  # default local_floor_enabled=False
    fake_client.set_default({"decision": "ALLOW"})

    calls = {"send": 0, "hook": 0}
    real_send = guard._send
    real_hook = guard._local_floor_verdict

    def spy_send(payload):
        calls["send"] += 1
        return real_send(payload)

    def spy_hook(payload):
        calls["hook"] += 1
        return real_hook(payload)

    guard._send = spy_send  # type: ignore[assignment]
    guard._local_floor_verdict = spy_hook  # type: ignore[assignment]

    decision = guard.validate(
        tool_name="lookup", tool_params={"id": "x"},
        session_id="s1", user_input="hi",
    )
    assert decision.allowed is True
    assert calls["hook"] == 1  # traversed exactly once during validate()
    assert calls["send"] == 1  # and reached _send exactly once
    # The real hook (not the spy) returns None when the flag is off.
    assert real_hook({"request_id": "r"}) is None


async def test_seam_off_routes_to_send_async(make_guard, fake_client):
    """STATE 1 on the async path: avalidate traverses _local_floor_verdict exactly
    once, BEFORE _send, and the to_thread(_send) line still runs. Byte-identical."""
    guard = make_guard()
    fake_client.set_default({"decision": "ALLOW"})

    order: list = []
    real_send = guard._send
    real_hook = guard._local_floor_verdict

    def spy_send(payload):
        order.append("send")
        return real_send(payload)

    def spy_hook(payload):
        order.append("hook")
        return real_hook(payload)

    guard._send = spy_send  # type: ignore[assignment]
    guard._local_floor_verdict = spy_hook  # type: ignore[assignment]

    decision = await guard.avalidate(
        tool_name="lookup", tool_params={"id": "x"},
        session_id="s1", user_input="hi",
    )
    assert decision.allowed is True
    # exactly once each, hook strictly before send.
    assert order == ["hook", "send"]


def test_seam_on_without_interpreter_fails_secure_to_hosted(make_guard, fake_client):
    """STATE 2 (flag on, no interpreter): the sync seam still routes to hosted
    _send — it NEVER local-allows, skips validation, or deny-alls. A DENY from the
    hosted PDP is honored (not a local ALLOW)."""
    guard = make_guard(local_floor_enabled=True)
    assert guard._config.local_floor_enabled is True

    # A hosted DENY must be returned unchanged — proving the seam did not local-allow.
    fake_client.set_default({"decision": "DENY", "reason": "hosted-said-no"})
    decision = guard.validate(
        tool_name="t", tool_params={}, session_id="s1", user_input="hi",
    )
    assert decision.decision == "DENY"
    assert decision.reason == "hosted-said-no"
    assert len(fake_client.sent) == 1  # the call reached the hosted client
    # The hook itself returns None (route to hosted), never a bare verdict.
    assert guard._local_floor_verdict({"request_id": "r"}) is None


async def test_seam_on_without_interpreter_fails_secure_to_hosted_async(
    make_guard, fake_client
):
    """STATE 2 on the async path: avalidate still routes to hosted _send; a hosted
    DENY is honored (no local allow / skip)."""
    guard = make_guard(local_floor_enabled=True)
    fake_client.set_default({"decision": "DENY", "reason": "hosted-said-no"})
    decision = await guard.avalidate(
        tool_name="t", tool_params={}, session_id="s1", user_input="hi",
    )
    assert decision.decision == "DENY"
    assert len(fake_client.sent) == 1


def test_floor_absent_warns_once_per_guard(make_guard, fake_client, caplog):
    """STATE 2 warns ONCE per guard (not per call), and the log record carries NO
    payload/PII substring (the message is static, on the redacted-payload hot path).
    N guards → N warnings (one each)."""
    fake_client.set_default({"decision": "ALLOW"})
    with caplog.at_level(logging.WARNING, logger="aegion_guard"):
        guard = make_guard(local_floor_enabled=True)
        # three calls carrying a would-be-secret in the input; still one warning.
        for _ in range(3):
            guard.validate(
                tool_name="t", tool_params={"pan": "4111111111111111"},
                session_id="s1", user_input="SSN 078-05-1120 secret-token-xyz",
            )

    floor_warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "local floor" in r.getMessage()
    ]
    assert len(floor_warnings) == 1, "must warn exactly once per guard, not per call"
    msg = floor_warnings[0].getMessage()
    # STATIC message: no payload / PII leaked into the log line.
    assert "4111111111111111" not in msg
    assert "078-05-1120" not in msg
    assert "secret-token-xyz" not in msg
    assert "Edge enforcement is NOT active" in msg

    # A SECOND guard warns again (once-per-guard, not once-per-process).
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="aegion_guard"):
        guard2 = make_guard(local_floor_enabled=True)
        guard2.validate(tool_name="t", tool_params={}, session_id="s2", user_input="hi")
    assert sum(
        1 for r in caplog.records if "local floor" in r.getMessage()
    ) == 1


def test_seam_returns_decision_or_none(make_guard, fake_client):
    """Type contract: _local_floor_verdict returns a Decision or None — NEVER a
    bare LocalFloorVerdict. An escaped str-Enum reads truthy → fail-OPEN, so this
    guards the type boundary before lld/37 wires a producer."""
    for flag in (False, True):
        guard = make_guard(local_floor_enabled=flag)
        result = guard._local_floor_verdict({"request_id": "r"})
        assert result is None or isinstance(result, Decision)
        assert not isinstance(result, LocalFloorVerdict)


# ================================================================ A3.4 structural


def _function_defs(tree: ast.AST):
    """Yield every (sync/async) function/method definition node in the tree."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def test_no_send_outside_seam():
    """AST dominator (A3.4): every reference to `self._send` in guard.py — call
    form `self._send(...)` AND bare-attribute form `to_thread(ctx.run, self._send,
    ...)` — sits in a function that ALSO references `_local_floor_verdict`, and the
    hook reference precedes the _send reference in source order. This is the
    coarse dominator the task specifies (word-boundary `self._send`, not a naive
    `self._send(` grep that would miss the bare async reference).

    Non-vacuous: moving a `self._send` into a function that does not pre-check
    `_local_floor_verdict` fails this test."""
    tree = ast.parse(_GUARD_PY.read_text(encoding="utf-8"))

    def _send_attr_lines(fn) -> list:
        lines = []
        for n in ast.walk(fn):
            # `self._send` as an attribute access (covers both call + bare ref).
            if isinstance(n, ast.Attribute) and n.attr == "_send" and \
                    isinstance(n.value, ast.Name) and n.value.id == "self":
                lines.append(n.lineno)
        return lines

    def _hook_ref_lines(fn) -> list:
        lines = []
        for n in ast.walk(fn):
            if isinstance(n, ast.Attribute) and n.attr == "_local_floor_verdict" \
                    and isinstance(n.value, ast.Name) and n.value.id == "self":
                lines.append(n.lineno)
        return lines

    send_sites_found = 0
    for fn in _function_defs(tree):
        # Skip the seam method itself and _send's own definition (a def is not a ref).
        if fn.name in ("_local_floor_verdict", "_send"):
            continue
        send_lines = _send_attr_lines(fn)
        if not send_lines:
            continue
        send_sites_found += 1
        hook_lines = _hook_ref_lines(fn)
        assert hook_lines, (
            f"{fn.name}() references self._send without a _local_floor_verdict "
            f"pre-check — a _send outside the seam (fail-open risk)"
        )
        # The hook reference must precede the earliest _send reference.
        assert min(hook_lines) < min(send_lines), (
            f"{fn.name}(): _local_floor_verdict must be checked BEFORE self._send"
        )

    # Guard against a false-green: we DID find the real _send call sites (validate
    # + avalidate). If a refactor removed them entirely this would be 0 and we'd
    # want to know the test lost its subject.
    assert send_sites_found >= 2, "expected _send references in validate + avalidate"


def test_seam_mints_no_signal():
    """Import-graph (A3.4): NO module in the aegion_guard package imports
    app.combiners (or app.*) — so no LocalFloorVerdict can ever leak into
    DenyOverrides.combine() (ADR-031 boundary). The SDK is a standalone package;
    it mints no Signal. Non-vacuous: adding `import app.combiners` to any SDK
    module fails this scan."""
    pkg_dir = _GUARD_PY.parent
    offenders = []
    for py in pkg_dir.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level:
                names = [node.module or ""]
            for n in names:
                top = n.split(".")[0]
                if top == "app" or n.startswith("app.combiners"):
                    offenders.append(f"{py.name}: {n}")
    assert not offenders, (
        "aegion_guard must not import the controller's app.* / app.combiners "
        f"(ADR-031 boundary); found: {offenders}"
    )


# ================================================================ A3.4 seam e2e


@pytest.mark.parametrize("flag", [False, True])
async def test_seam_end_to_end_routes_to_hosted(make_guard, fake_client, flag):
    """The shared-contract seam integration: with a stub hosted endpoint, BOTH
    validate and avalidate — flag off AND flag on-without-interpreter — reach the
    stub and return its Decision. Proves the seam does not intercept the real
    request path (it is a pass-through in 0.2.0)."""
    guard = make_guard(local_floor_enabled=flag)
    fake_client.set_default({"decision": "ALLOW", "reason": "hosted-ok"})

    sync_decision = guard.validate(
        tool_name="t", tool_params={"id": "x"}, session_id="s1", user_input="hi",
    )
    async_decision = await guard.avalidate(
        tool_name="t", tool_params={"id": "y"}, session_id="s1", user_input="hi",
    )

    # Both returned the STUB's decision (came from the hosted client, not a local mint).
    assert sync_decision.reason == "hosted-ok" and sync_decision.allowed
    assert async_decision.reason == "hosted-ok" and async_decision.allowed
    # Two payloads hit the stubbed hosted client — the seam routed both there.
    assert len(fake_client.sent) == 2
