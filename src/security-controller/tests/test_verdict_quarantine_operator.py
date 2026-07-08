"""WS-G M-G3.13 backend half (lld/40 §6.9) — the server does NOT require a client
`operator_id`; it derives the operator from the verified `ctx.sub`.

This proves the frontend can drop its dead `operator_id:'dana.reyes'` stub: a
verdict / quarantine call with NO `operator_id` in the body succeeds, and the
attribution written is `ctx.sub`, never a client-supplied value. If the server
had 422-required the field, this test would fail loud (a real gap to fix, not a
test to soften).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api.deps import OperatorContext, resolve_operator_tenant, require_role


@pytest.fixture
def admin_client():
    # verdict = editor floor, quarantine = admin floor — an owner satisfies both.
    ctx = OperatorContext(sub="op-verified-sub", tenant_id="t_x", role="owner",
                          email="op@x.co")
    app.dependency_overrides[resolve_operator_tenant] = lambda: ctx
    # require_role returns a fresh dep per call-site; override the *factory* results
    # is impractical, so also override the specific dep instances by clearing the
    # role gate to the same ctx (the gate reads role from ctx, which is 'owner').
    with patch("app.api.routes.assert_owns", return_value=None):
        yield TestClient(app, raise_server_exceptions=False), ctx
    app.dependency_overrides.pop(resolve_operator_tenant, None)


def test_verdict_operator_id_from_ctx_sub_not_request_body(admin_client):
    client, ctx = admin_client
    captured = {}

    def _record(decision_id, verdict, reason, operator_id):
        captured["operator_id"] = operator_id
        return {"decision_id": decision_id, "verdict": verdict, "recorded": True}

    with patch("app.api.routes._decisions_service") as svc:
        svc.return_value.record_verdict.side_effect = _record
        # Body carries NO operator_id — the frontend can drop the stub.
        resp = client.post("/v1/decisions/sess-1:req-1/verdict",
                           json={"verdict": "false_positive", "reason": "benign"})
    assert resp.status_code == 200, resp.text
    assert captured["operator_id"] == ctx.sub, "operator must be the verified ctx.sub"
    assert captured["operator_id"] != "dana.reyes", "never a client-supplied stub"


def test_quarantine_operator_id_from_ctx_sub_not_request_body(admin_client):
    client, ctx = admin_client
    captured = {}

    async def _quarantine(session_id, reason, operator_id):
        captured["operator_id"] = operator_id
        return {"session_id": session_id, "quarantine_status": "quarantined"}

    with patch("app.utils.session_manager.SessionManager") as SM:
        inst = SM.return_value
        inst.get_session = AsyncMock(return_value={"quarantine_status": "active", "trust_score": 50})
        inst.manual_quarantine = AsyncMock(side_effect=_quarantine)
        # Body carries only `reason` — NO operator_id.
        resp = client.post("/v1/quarantine/sess-1", json={"reason": "suspicious"})
    assert resp.status_code == 200, resp.text
    assert captured["operator_id"] == ctx.sub, "operator must be the verified ctx.sub"
    assert captured["operator_id"] != "operator", "never the old query-default stub"
