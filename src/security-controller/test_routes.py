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


def _mk_scan_service(rows):
    """A DecisionsService with a real DenyOverrides combiner but no boto3, wired to a
    FakeDDB that returns `rows` on the first query and nothing after — so the REAL
    `scan_decisions` grouping+projection runs (same pattern as
    tests/unit/test_trail_builder.py::test_scan_decisions_*). This is what makes the
    winning_source assertion non-vacuous: it exercises decisions_service.py:554, so
    deleting that line breaks this test."""
    from app.services.decisions_service import DecisionsService
    from app.combiners import DenyOverrides

    svc = DecisionsService.__new__(DecisionsService)
    svc._combiner = DenyOverrides()

    calls = {"n": 0}

    class _FakeDDB:
        def query(self, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"Items": rows, "LastEvaluatedKey": None}
            return {"Items": [], "LastEvaluatedKey": None}

    svc._client = _FakeDDB()
    svc._deserialize_item = lambda it: it  # rows are already plain dicts
    return svc


def test_decisions_row_projection_includes_winning_source():
    """M-G3.3: each GET /v1/decisions row (DecisionItem) carries `winning_source` at
    the TOP LEVEL of the row (not only inside `combined`) so the Threats per-detector
    facet is API-driven. Drives the REAL `scan_decisions` projection so it guards
    decisions_service.py:554 — deleting the row-level field FAILS this test."""
    from app.combiners import Source

    # One (session, request) group: trust ALLOW + sigma DENY → combined DENY, the
    # winning source is sigma (the top-priority denier under deny-overrides).
    rows = [
        {"source": Source.SENTRA_TRUST, "decision": "ALLOW", "request_id": "r1",
         "session_id": "s1", "agent_id": "agent-x", "tool_name": "wire_transfer",
         "platform": "bedrock", "trust_score_before": 0.9, "timestamp_ms": 100,
         "timestamp_iso": "2026-07-08T00:00:00.100Z"},
        {"source": Source.SENTRA_SIGMA, "decision": "DENY", "reason": "injection",
         "request_id": "r1", "session_id": "s1", "agent_id": "agent-x",
         "tool_name": "wire_transfer", "platform": "bedrock", "threat_type": "INJECTION",
         "trust_score_before": 0.9, "timestamp_ms": 200,
         "timestamp_iso": "2026-07-08T00:00:00.200Z"},
    ]
    svc = _mk_scan_service(rows)

    resp = svc.scan_decisions(limit=50)
    matching = [d for d in resp["decisions"] if d["request_id"] == "r1"]
    assert len(matching) == 1
    d = matching[0]

    assert "winning_source" in d, (
        "M-G3.3: the /v1/decisions ROW projection must carry a top-level "
        "`winning_source` (DecisionItem), not only inside `combined`"
    )
    assert d["decision"] == "DENY"
    assert d["winning_source"] == Source.SENTRA_SIGMA, (
        "a DENY row's row-level winning_source must name the deciding detector"
    )
    # Row-level value mirrors the nested combined value (same source of truth).
    assert d["winning_source"] == d["combined"]["winning_source"]
    assert d["winning_source"] is not None, "a DENY row must name a winning source"


def test_decisions_row_winning_source_null_on_allow_only_group():
    """M-G3.3 (the ALLOW half): an all-ALLOW (session, request) group has NO denying
    source, so the row-level `winning_source` MUST be null — the client then renders
    no per-detector facet chip (decisions_service.py:554 + the deny_overrides ALLOW
    branch that sets metadata.winning_source=None). This is the negative pin the DENY
    test can't give: if the projection ever FABRICATED a source on an ALLOW row (a
    spurious facet chip), this test FAILS. Same nested/row mirroring asserted."""
    from app.combiners import Source

    # One (session, request) group, both signals ALLOW → combined ALLOW, no winner.
    rows = [
        {"source": Source.SENTRA_TRUST, "decision": "ALLOW", "request_id": "r2",
         "session_id": "s2", "agent_id": "agent-y", "tool_name": "read_ledger",
         "platform": "bedrock", "trust_score_before": 0.95, "timestamp_ms": 100,
         "timestamp_iso": "2026-07-08T00:00:00.100Z"},
        {"source": Source.SENTRA_SIGMA, "decision": "ALLOW", "request_id": "r2",
         "session_id": "s2", "agent_id": "agent-y", "tool_name": "read_ledger",
         "platform": "bedrock", "trust_score_before": 0.95, "timestamp_ms": 200,
         "timestamp_iso": "2026-07-08T00:00:00.200Z"},
    ]
    svc = _mk_scan_service(rows)

    resp = svc.scan_decisions(limit=50)
    matching = [d for d in resp["decisions"] if d["request_id"] == "r2"]
    assert len(matching) == 1
    d = matching[0]

    assert d["decision"] == "ALLOW"
    assert "winning_source" in d, "the row must still carry the field (null), not omit it"
    assert d["winning_source"] is None, (
        "an ALLOW-only group has no denying source — the row-level winning_source "
        "must be null, never a fabricated detector (no spurious facet chip)"
    )
    # Row-level mirrors the nested combined value — both null on an ALLOW.
    assert d["combined"]["winning_source"] is None
    assert d["winning_source"] == d["combined"]["winning_source"]
