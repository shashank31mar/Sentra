"""Connection-route authz + error-contract tests (WS-M M2.1 + M2.9 / lld/39 §2.3, §3.7).

Routes 7-11 write IAM ``role_arn`` / Azure SP ``secret_ref`` and drive live
``sts:AssumeRole`` on ``test``/``scan`` — an ungated caller (or a mere ``viewer``)
triggers cross-account calls. The gap is a role/privilege gap (cross-tenant is already
blocked by the born-tenant-scoped PK), so create/update/delete are ``admin`` and
test/scan are ``editor``; each id-bearing route asserts ``assert_owns(CONNECTION)``.

M2.9: ``_raise_connection_http`` RAISES (NoReturn) — a caller can't accidentally
swallow the failure into a fake-200. The one legitimate 200-envelope
(``test_connection`` rejected credential) keeps the envelope but SANITIZES the message
(no raw STS/principal-ARN detail crosses the boundary).
"""
from __future__ import annotations

import inspect

import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, Mock, patch

from app.api import routes as R
from app.api.deps import OperatorContext
from app.api.ownership import ResourceKind


def _ctx(role="admin", tenant_id="t_a", sub="op-v"):
    return OperatorContext(sub=sub, tenant_id=tenant_id, role=role, email="op@x")


def _min_role_of(handler) -> str:
    dep = inspect.signature(handler).parameters["ctx"].default.dependency
    vals = {c.cell_contents for c in (dep.__closure__ or ())}
    roles = {v for v in vals if isinstance(v, str)}
    assert roles, f"{handler.__name__} carries no require_role gate"
    return next(iter(roles))


# --------------------------------------------------------------------------- #
# (wiring) each mutating connection route carries the right role gate
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("handler,expected_role", [
    (R.create_connection, "admin"),
    (R.update_connection, "admin"),
    (R.delete_connection, "admin"),
    (R.test_connection, "editor"),
    (R.scan_connection, "editor"),
])
def test_connection_route_carries_expected_role_gate(handler, expected_role):
    assert _min_role_of(handler) == expected_role


def test_update_connection_requires_admin():
    assert _min_role_of(R.update_connection) == "admin"


def test_test_connection_requires_editor():
    assert _min_role_of(R.test_connection) == "editor"


# --------------------------------------------------------------------------- #
# (anti-IDOR) id-bearing routes assert ownership BEFORE touching the service
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_update_connection_asserts_ownership_before_mutating():
    svc = Mock()
    with patch("app.api.routes.assert_owns", side_effect=HTTPException(404)), \
         patch("app.services.connections_service.ConnectionsService", return_value=svc):
        with pytest.raises(HTTPException) as ei:
            await R.update_connection("c-foreign", {"role_arn": "arn:..."}, ctx=_ctx())
    assert ei.value.status_code == 404
    svc.set_role_arn.assert_not_called()


@pytest.mark.asyncio
async def test_connection_cross_tenant_404():
    """A foreign connection id → 404 (existence-masked) via assert_owns, before the
    delete runs."""
    svc = Mock()
    with patch("app.api.routes.assert_owns", side_effect=HTTPException(404)), \
         patch("app.services.connections_service.ConnectionsService", return_value=svc):
        with pytest.raises(HTTPException) as ei:
            await R.delete_connection("c-foreign", ctx=_ctx())
    assert ei.value.status_code == 404
    svc.delete_connection.assert_not_called()


@pytest.mark.asyncio
async def test_test_connection_asserts_own_kind_connection():
    calls = []
    svc = Mock()
    svc.test_connection = Mock(return_value={"ok": True, "agents_visible": 2, "message": "ok"})
    with patch("app.api.routes.assert_owns", side_effect=lambda c, k, i: calls.append(k)), \
         patch("app.services.connections_service.ConnectionsService", return_value=svc):
        await R.test_connection("c-own", {}, ctx=_ctx(role="editor"))
    assert calls == [ResourceKind.CONNECTION]


# --------------------------------------------------------------------------- #
# (M2.9) error contract — real status, not fake-200; sanitized probe message
# --------------------------------------------------------------------------- #
def test_raise_connection_http_raises_not_returns():
    """The factory RAISES (NoReturn) — an unknown connection maps to a real 404,
    never a returned object a caller could drop."""
    from app.services.connections_service import ConnectionNotFound
    with pytest.raises(HTTPException) as ei:
        R._raise_connection_http(ConnectionNotFound("nope"))
    assert ei.value.status_code == 404


def test_connection_error_maps_to_real_status_not_200():
    from app.services.connections_service import (
        InvalidRoleArn, NotConnected, ProviderNotAvailable,
    )
    cases = [(ProviderNotAvailable("x"), 409), (NotConnected("x"), 409),
             (InvalidRoleArn("x"), 400), (RuntimeError("weird"), 500)]
    for exc, expected in cases:
        with pytest.raises(HTTPException) as ei:
            R._raise_connection_http(exc)
        assert ei.value.status_code == expected


@pytest.mark.asyncio
async def test_test_connection_rejected_credential_message_sanitized():
    """A rejected credential keeps the 200 {ok:false} envelope (partial-success
    carve-out) but the message must NOT leak the raw STS/principal-ARN detail."""
    raw = ("AssumeRole OK but probe failed — AccessDeniedException: User "
           "arn:aws:sts::531109575379:assumed-role/secret-internal/xyz is not authorized")
    svc = Mock()
    svc.test_connection = Mock(return_value={"ok": False, "agents_visible": None, "message": raw})
    with patch("app.api.routes.assert_owns", return_value=None), \
         patch("app.services.connections_service.ConnectionsService", return_value=svc):
        out = await R.test_connection("c-own", {}, ctx=_ctx(role="editor"))
    assert out["ok"] is False
    # the raw ARN / account id is gone from the customer-facing message
    assert "arn:aws:sts::" not in out["message"]
    assert "531109575379" not in out["message"]
    assert "secret-internal" not in out["message"]
    # but it is still a useful, non-empty classification
    assert out["message"]


@pytest.mark.asyncio
async def test_test_connection_success_message_untouched():
    svc = Mock()
    svc.test_connection = Mock(return_value={"ok": True, "agents_visible": 3, "message": "AssumeRole OK · 3 agents visible"})
    with patch("app.api.routes.assert_owns", return_value=None), \
         patch("app.services.connections_service.ConnectionsService", return_value=svc):
        out = await R.test_connection("c-own", {}, ctx=_ctx(role="editor"))
    assert out["ok"] is True
    assert out["agents_visible"] == 3
