"""Quarantine / release authz tests (WS-M M2.2 / lld/39 §2.3 rows 13-14).

FOOTGUN this closes: ``release_session`` took an ``operator_id`` query default
(``"operator"``) with NO auth, so a *contained agent could lift its own quarantine*.
De-containment is now ``require_role("admin")`` + ``assert_owns(SESSION)`` and the
operator derives from the verified ``ctx.sub``, never a body/query field.
"""
from __future__ import annotations

import inspect

import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, patch

from app.api import routes as R
from app.api.deps import OperatorContext
from app.api.ownership import ResourceKind


def _ctx(role="admin", tenant_id="t_a", sub="op-real"):
    return OperatorContext(sub=sub, tenant_id=tenant_id, role=role, email="op@x")


def _min_role_of(handler) -> str:
    dep = inspect.signature(handler).parameters["ctx"].default.dependency
    vals = {c.cell_contents for c in (dep.__closure__ or ())}
    return next(iter({v for v in vals if isinstance(v, str)}))


def test_release_session_requires_admin():
    assert _min_role_of(R.release_session) == "admin"


def test_quarantine_session_requires_admin():
    assert _min_role_of(R.quarantine_session) == "admin"


def test_release_session_no_longer_takes_operator_id_query():
    """The spoofable ``operator_id`` query param (default "operator") is gone."""
    assert "operator_id" not in inspect.signature(R.release_session).parameters


@pytest.mark.asyncio
async def test_release_asserts_session_ownership_before_release():
    """A foreign session → the ownership assert blocks release (no self-release / no
    cross-tenant de-containment)."""
    with patch("app.api.routes.assert_owns", side_effect=HTTPException(404)), \
         patch("app.utils.session_manager.SessionManager") as SM:
        with pytest.raises(HTTPException) as ei:
            await R.release_session("sess-foreign", ctx=_ctx())
    assert ei.value.status_code == 404
    SM.return_value.manual_release.assert_not_called()


@pytest.mark.asyncio
async def test_quarantine_operator_from_ctx_not_body():
    """The operator recorded is the verified ctx.sub, not a body operator_id."""
    captured = {}
    sm = AsyncMock()
    sm.get_session = AsyncMock(return_value={"quarantine_status": "active", "trust_score": 90})

    async def _manual_quarantine(session_id, reason, operator_id):
        captured["operator_id"] = operator_id
        return {"quarantine_status": "quarantined", "trust_score": 10}

    sm.manual_quarantine = _manual_quarantine
    with patch("app.api.routes.assert_owns", return_value=None), \
         patch("app.utils.session_manager.SessionManager", return_value=sm):
        await R.quarantine_session(
            "sess-own",
            {"reason": "manual", "operator_id": "attacker-supplied"},
            ctx=_ctx(sub="op-verified"),
        )
    assert captured["operator_id"] == "op-verified"


@pytest.mark.asyncio
async def test_release_operator_from_ctx_not_default_query():
    captured = {}
    sm = AsyncMock()
    sm.get_session = AsyncMock(return_value={"quarantine_status": "quarantined", "trust_score": 10})

    async def _manual_release(session_id, operator_id):
        captured["operator_id"] = operator_id
        return {"quarantine_status": "active", "trust_score": 80}

    sm.manual_release = _manual_release
    with patch("app.api.routes.assert_owns", return_value=None), \
         patch("app.utils.session_manager.SessionManager", return_value=sm):
        await R.release_session("sess-own", ctx=_ctx(sub="op-verified"))
    assert captured["operator_id"] == "op-verified"
