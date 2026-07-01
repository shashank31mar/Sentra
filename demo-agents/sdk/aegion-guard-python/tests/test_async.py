"""Async tool support: coroutine detection, awaited validation, contextvar flow."""
from __future__ import annotations

import pytest

from aegion_guard import ToolDenied


async def test_async_tool_allows_and_awaits(make_guard, fake_client):
    guard = make_guard()
    fake_client.set_default({"decision": "ALLOW"})

    @guard.tool()
    async def verify_identity(subscriber_id):
        return {"verified": True, "id": subscriber_id}

    with guard.session(session_id="s1", user_input="verify me"):
        result = await verify_identity("SUB1")

    assert result == {"verified": True, "id": "SUB1"}
    assert fake_client.last["tool_name"] == "verify_identity"


async def test_async_tool_blocks_on_deny(make_guard, fake_client):
    guard = make_guard()
    fake_client.set_default({"decision": "DENY", "reason": "no"})
    ran = {"called": False}

    @guard.tool(operation_type="WRITE")
    async def reset_sim(subscriber_id):
        ran["called"] = True
        return "done"

    with guard.session(session_id="s1", user_input="swap the sim"):
        with pytest.raises(ToolDenied):
            await reset_sim("SUB1")
    assert ran["called"] is False


async def test_async_context_survives_await(make_guard, fake_client):
    guard = make_guard()

    @guard.tool()
    async def inner(x):
        return x

    # The contextvar set by session() must still resolve inside the awaited
    # validation that runs in a worker thread.
    with guard.session(session_id="async-sess", user_input="hi"):
        await inner(1)

    assert fake_client.last["session_id"] == "async-sess"


async def test_avalidate_explicit(make_guard, fake_client):
    guard = make_guard()
    fake_client.set_default({"decision": "ALLOW"})

    decision = await guard.avalidate(
        tool_name="check_fraud_score", tool_params={"id": "x"},
        session_id="s1", user_input="hi",
    )
    assert decision.allowed is True


async def test_async_content_decorator_threads_phase(make_guard, fake_client):
    """WS-B (LLD 30 §4): a @guard.content on an async fn threads phase +
    content_text through the same async path as @guard.tool (reuses
    _avalidate_or_raise)."""
    guard = make_guard()
    fake_client.set_default({"decision": "ALLOW"})

    @guard.content()
    async def ingest(doc):
        return {"seen": doc}

    with guard.session(session_id="s1", user_input="untrusted-doc-body"):
        result = await ingest("d")

    assert result == {"seen": "d"}
    assert fake_client.last["phase"] == "content"
    assert fake_client.last["content_text"] == "untrusted-doc-body"
