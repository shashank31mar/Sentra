"""Route-19 interim fail-closed guard tests (WS-M M2.8 / lld/39 §4.M2.8).

``POST /v1/sessions/{id}/signals`` is an external-producer write. Until the full
producer credential lands (design-only/deferred D4), external writes are REJECTED
(403) — the prior lenient-accept path is removed. No first-party signal is lost
(agents post via ``/validate``). A flag (``external_signal_write_enabled``, default
False) flips it back on when the credential ships; fail-secure when unset.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from unittest.mock import Mock, patch

from app.api import routes as R
from app.config import settings


@pytest.mark.asyncio
async def test_external_signal_rejected_failclosed(monkeypatch):
    """Default (flag off) → 403, and the underlying post_signal is never reached."""
    monkeypatch.setattr(settings, "external_signal_write_enabled", False)
    svc = Mock()
    with patch("app.api.routes._decisions_service", return_value=svc):
        with pytest.raises(HTTPException) as ei:
            await R.post_session_signal("s1", {"source": "x", "priority": 5})
    assert ei.value.status_code == 403
    svc.post_signal.assert_not_called()


@pytest.mark.asyncio
async def test_lenient_accept_path_removed(monkeypatch):
    """With the flag off, even a well-formed external signal is rejected — the
    prior 'store unknown source with priority=0' lenient path is gone."""
    monkeypatch.setattr(settings, "external_signal_write_enabled", False)
    svc = Mock()
    svc.post_signal = Mock(return_value={"stored": True})
    with patch("app.api.routes._decisions_service", return_value=svc):
        with pytest.raises(HTTPException) as ei:
            await R.post_session_signal("s1", {"source": "unknown-producer"})
    assert ei.value.status_code == 403
    svc.post_signal.assert_not_called()


@pytest.mark.asyncio
async def test_flag_on_allows_write(monkeypatch):
    """When the producer credential ships and the flag flips on, the route works."""
    monkeypatch.setattr(settings, "external_signal_write_enabled", True)
    svc = Mock()
    svc.post_signal = Mock(return_value={"stored": True})
    with patch("app.api.routes._decisions_service", return_value=svc):
        out = await R.post_session_signal("s1", {"source": "bedrock", "priority": 3})
    assert out == {"stored": True}
    svc.post_signal.assert_called_once()
