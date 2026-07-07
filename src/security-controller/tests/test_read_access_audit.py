"""WS-N N9 / lld/40 §8 SEC-5 (D12) — read-access attribution (non-repudiation).

Every resolve_operator_tenant-bound READ must leave an attributable event
(operator_sub + resolved tenant_id + route scope) in the platform-audit ledger — the
SOC2/HIPAA system-of-record obligation for "which operator viewed which tenant's data".
Emitted from inside resolve_operator_tenant so coverage == the bound read set by
construction. GET-only; fire-and-forget (never breaks the read).
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.api import read_access_audit as R9


class _FakeQP(dict):
    """A query_params-like mapping (supports `in` + [] like Starlette's)."""


def _req(method="GET", path="/v1/sessions/{session_id}/trail", headers=None, **params):
    return SimpleNamespace(
        method=method,
        headers=headers or {},
        url=SimpleNamespace(path=path.replace("{session_id}", "s1")),
        scope={"route": SimpleNamespace(path=path)},
        query_params=_FakeQP(params),
    )


class TestBoundReadEmitsAccessEvent:
    def test_bound_read_emits_access_event(self):
        """A customer GET read writes an event with sub + tenant_id + route scope."""
        with patch("app.services.platform_audit.get_platform_audit_store") as store:
            R9.emit_read_access_event(
                _req(path="/v1/agents"),
                operator_sub="op-cust", tenant_id="t_a", is_platform=False,
            )
        rec = store.return_value.record
        rec.assert_called_once()
        kw = rec.call_args.kwargs
        assert kw["operator_sub"] == "op-cust"
        assert kw["target_tenant"] == "t_a"
        assert kw["what"] == "read:/v1/agents"
        assert kw["read_type"] == "operator_read"
        assert kw["decision"] == "READ"
        assert kw["consent_state"] == "own_tenant"

    def test_non_get_is_not_attributed_here(self):
        """A mutation (POST/PUT/DELETE) is NOT recorded by the read trail — it has its
        own audit path; double-logging would be noise."""
        with patch("app.services.platform_audit.get_platform_audit_store") as store:
            R9.emit_read_access_event(
                _req(method="POST", path="/v1/policies"),
                operator_sub="op", tenant_id="t_a", is_platform=False,
            )
        store.return_value.record.assert_not_called()


class TestPlatformCrossTenantReadAttributed:
    def test_platform_cross_tenant_read_is_attributed(self):
        """A _platform (break-glass) operator's read records the SPECIFIC resolved
        target tenant_id (never '*'), so the operator-lane cross-tenant read is
        non-repudiable — complementing _audit_platform_read's aggregate '*' rows."""
        with patch("app.services.platform_audit.get_platform_audit_store") as store:
            R9.emit_read_access_event(
                _req(path="/v1/sessions/{session_id}/trail", request_id="r1"),
                operator_sub="op-staff", tenant_id="t_customer_b", is_platform=True,
            )
        kw = store.return_value.record.call_args.kwargs
        assert kw["target_tenant"] == "t_customer_b"   # the specific tenant, NOT "*"
        assert kw["target_tenant"] != "*"
        assert kw["consent_state"] == "platform_break_glass"


class TestNeverBreaksTheRead:
    def test_audit_write_failure_does_not_raise(self):
        """A ledger write failure must not break the read (best-effort attribution)."""
        with patch("app.services.platform_audit.get_platform_audit_store",
                   side_effect=RuntimeError("ddb down")):
            # Must not raise.
            R9.emit_read_access_event(
                _req(path="/v1/agents"),
                operator_sub="op", tenant_id="t_a", is_platform=False,
            )

    def test_scope_only_records_bounded_params(self):
        """The recorded scope must only pull bounded id/filter params — never arbitrary
        free-text (which could carry PII). An unknown param is dropped."""
        scope = R9._safe_scope(_req(path="/v1/decisions", agent_id="a1", secret="leak-me"))
        assert scope == {"agent_id": "a1"}
        assert "secret" not in scope


class TestCoverageEqualsBoundReadSet:
    """N9 acceptance: coverage == the bound read set BY CONSTRUCTION — the event is
    emitted from resolve_operator_tenant, so every route carrying it is attributed and
    a bound-but-unattributed read is impossible. This test proves the wiring: driving
    resolve_operator_tenant for a GET emits the event."""

    @pytest.mark.asyncio
    async def test_resolve_operator_tenant_emits_read_event(self):
        import app.api.deps as deps
        from unittest.mock import Mock

        m = Mock()
        m.tenant_id = "t_a"
        m.role = "viewer"
        m.is_primary = True
        req = _req(path="/v1/agents")

        deps._alb_claims_override = lambda r: {"sub": "op_a", "email": "a@x"}
        try:
            with patch("app.api.deps.get_member_store") as gms, \
                 patch("app.api.read_access_audit.emit_read_access_event") as emit:
                gms.return_value.by_operator.return_value = [m]
                ctx = await deps.resolve_operator_tenant(req)
            assert ctx.tenant_id == "t_a"
            emit.assert_called_once()
            assert emit.call_args.kwargs["operator_sub"] == "op_a"
            assert emit.call_args.kwargs["tenant_id"] == "t_a"
        finally:
            deps._alb_claims_override = None
            from app.utils import tenancy
            tenancy.set_current_tenant(tenancy.DEFAULT_TENANT)
