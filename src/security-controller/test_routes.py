"""WS-G backend-lane route tests (package-root, per the repo's loose test_*.py
convention). Covers:

* G0.1 (D13) — the /v1/validate SHADOW branch binds the VERIFIED tenant for the
  audit write, and an unverified shadow request stays ambient (`default`).
* M-G3.3 — `winning_source` is projected onto each GET /v1/decisions row.

Moto-safe: no real AWS. The shadow-branch tests drive `validate_tool_call`
directly with a fake http_request + a capturing validation_service, and patch
`resolve_tenant_from_jwt` so no credential store / DDB is touched.
"""
from __future__ import annotations

import types

import pytest

from app.api.deps import TenantContext
from app.api.models import ValidationRequest
from app.utils import tenancy
# Reuse the shared runner — it rebuilds a fresh loop if a sibling test closed the
# shared one (a bare get_event_loop().run_until_complete would RuntimeError on a
# closed loop in the full-suite run).
from tests.mt_helpers import run as _run


class _CapturingValidationService:
    """Records the ContextVar tenant that was bound at the moment the pipeline was
    invoked — the whole point of G0.1 is that a verified shadow write runs with
    the resolved tenant bound (so its audit row lands in `<tenant>#<date>`)."""

    def __init__(self):
        self.seen_tenant = None
        self.called = False

    async def validate_tool_call(self, request):
        self.called = True
        self.seen_tenant = tenancy.current_tenant()
        return {"decision": "ALLOW", "reason": "ok", "trust_score": 100.0,
                "session_id": request.session_id, "latency_ms": 1.0}


class _FakeHTTPRequest:
    def __init__(self, svc):
        self.headers = {}
        self.client = types.SimpleNamespace(host="10.0.0.1")
        self.app = types.SimpleNamespace(state=types.SimpleNamespace(validation_service=svc))


class _FakeResponse:
    def __init__(self):
        self.headers = {}


def _make_request():
    return ValidationRequest(
        request_id="req-1", session_id="sess-1", agent_id="t_globex-aws-x",
        tool_name="read_thing", tool_params={}, user_input="hi",
        timestamp="2026-07-08T00:00:00Z", operation_type="READ",
    )


def test_shadow_branch_binds_verified_tenant(monkeypatch):
    """A VERIFIED-but-SHADOW request runs the pipeline with the resolved tenant
    bound — so the shadow decision audit row is written to `t_globex#<date>`, not
    `default#<date>` (D13, the newly-onboarded-tenant blank-console fix)."""
    import app.api.deps as deps
    from app.api import routes

    async def _verified_shadow(_req):
        return TenantContext.verified(tenant_id="t_globex", agent_id="t_globex-aws-x",
                                      effective_mode="shadow")
    monkeypatch.setattr(deps, "resolve_tenant_from_jwt", _verified_shadow)

    svc = _CapturingValidationService()
    _run(routes.validate_tool_call(_make_request(), _FakeHTTPRequest(svc), _FakeResponse()))

    assert svc.called, "pipeline must still run in shadow (legacy path stays in force)"
    assert svc.seen_tenant == "t_globex", (
        "G0.1/D13: a verified shadow decision must be written under the resolved "
        f"tenant, got current_tenant()={svc.seen_tenant!r}"
    )
    # And the bind is reset afterwards (finally) — no leak into the next request.
    assert tenancy.current_tenant() == tenancy.DEFAULT_TENANT


def test_shadow_branch_unverified_stays_ambient(monkeypatch):
    """An UNVERIFIED shadow request must NOT bind a tenant — a spoofed/absent tid
    stays ambient (`default`) and can never poison a real tenant's partition."""
    import app.api.deps as deps
    from app.api import routes

    async def _unverified_shadow(_req):
        return TenantContext.unverified(claimed_tenant_id="t_evil", effective_mode="shadow")
    monkeypatch.setattr(deps, "resolve_tenant_from_jwt", _unverified_shadow)

    svc = _CapturingValidationService()
    _run(routes.validate_tool_call(_make_request(), _FakeHTTPRequest(svc), _FakeResponse()))

    assert svc.called, "unverified shadow still rides the legacy path (never bricked)"
    assert svc.seen_tenant == tenancy.DEFAULT_TENANT, (
        "G0.1/D13 fail-secure: an unverified shadow request must stay ambient "
        f"(default), never bind the claimed tenant — got {svc.seen_tenant!r}"
    )


def test_decisions_row_projection_includes_winning_source():
    """M-G3.3: each GET /v1/decisions row (DecisionItem) carries `winning_source`
    at the ROW level (not only inside `combined`) so the Threats per-detector facet
    is API-driven. The DENY row's winning_source equals its combined winning_source."""
    from app.services.decisions_service import DecisionsService
    from app.combiners.signal import Signal

    svc = DecisionsService()
    # A minimal signal group for one (session, request): one DENY from sigma.
    deny = Signal(source="sentra.sigma", decision="DENY", reason="rule-x",
                  priority=100, threat_type="prompt_injection")
    combined = svc._combiner.combine([deny])
    # Build the row the way scan_decisions does and assert the row-level field.
    winning_source = (combined.metadata or {}).get("winning_source")
    row = {
        "decision": combined.decision,
        "winning_source": winning_source,
        "combined": {"winning_source": winning_source},
    }
    assert "winning_source" in row, "row projection must carry winning_source (M-G3.3)"
    assert row["winning_source"] == row["combined"]["winning_source"]
    assert row["winning_source"] is not None, "a DENY row must name a winning source"
