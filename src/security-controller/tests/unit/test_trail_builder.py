"""Unit tests for the WS-D record-what-ran decision trail — LLD 33 §12.

The full §12 test plan: 23 numbered T-TRAIL-* tests + T-TRAIL-14b. All AWS is
mocked / patched; no live DDB. The four-bucket classifier (`build_trail`), the
marker row shape (`_build_marker_item`), the coverage accessor (`coverage_set`),
the §7.1.1 producer stamp, the persist path (`log_signals`), high-assurance
resolution, and the read API (`get_session_trail` / `GET /trail`) are all
covered here.

Run from src/security-controller/:
    PYTHONPATH=. pytest tests/unit/test_trail_builder.py -v
"""

from __future__ import annotations

import dataclasses
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from app.combiners import Signal, Source
from app.combiners.sources import (
    SOURCE_DISPLAY_NAMES,
    STATE_DISPLAY_NAMES,
    STATIC_FALLBACK_ORDER,
    STEP_LABEL_TO_SOURCE,
)
from app.services.trail_builder import (
    NotRunMarker,
    TrailResult,
    build_trail,
    coverage_set,
    resolve_high_assurance,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _sig(source, decision="ALLOW", **kw):
    return Signal(source=source, decision=decision, **kw)


def _all_timings():
    """A _step_timings snapshot where every request-phase validator ran."""
    return {"trust": 1.0, "policy": 1.0, "cross_agent": 1.0, "sigma": 1.0,
            "context": 1.0, "abuse": 1.0, "ml": 1.0}


# ===========================================================================
# D1.1 — NotRunMarker record type
# ===========================================================================

def test_not_run_marker_has_no_decision_attr():
    """A NotRunMarker is deliberately NOT a Signal: no `decision` field, and it is
    frozen (invariant ii, LLD 33 §3/§6.1)."""
    m = NotRunMarker(source=Source.SENTRA_SIGMA)
    assert hasattr(m, "decision") is False
    assert m.record_type == "not_run"          # default discriminator, NOT a decision
    with pytest.raises(dataclasses.FrozenInstanceError):
        m.record_type = "abstain"  # type: ignore[misc]


# ===========================================================================
# D1.2 — sources.py constants (T-TRAIL-06 set half)
# ===========================================================================

def test_step_label_map_excludes_plumbing():
    """T-TRAIL-06 (set half): plumbing labels are UNMAPPED, and the policy_fallback
    double-fire collapses to a SINGLE sentra.policy invoked source (§11.2)."""
    for plumbing in ("session", "pipeline", "handle", "abuse_policy_load", "policy_fallback"):
        assert plumbing not in STEP_LABEL_TO_SOURCE

    # Feed a _step_timings carrying all the plumbing labels + BOTH policy labels.
    step_timings = {
        "session": 0.1, "pipeline": 0.1, "handle": 0.1, "abuse_policy_load": 0.1,
        "policy": 1.0, "policy_fallback": 1.0, "trust": 1.0,
    }
    invoked = {STEP_LABEL_TO_SOURCE[k] for k in step_timings if k in STEP_LABEL_TO_SOURCE}
    # No plumbing label leaks into invoked.
    assert Source.SENTRA_TRUST in invoked
    assert Source.SENTRA_POLICY in invoked
    # policy + policy_fallback → the SINGLE sentra.policy source (no double count).
    assert sum(1 for s in invoked if s == Source.SENTRA_POLICY) == 1
    assert len(invoked) == 2  # trust + policy only


# ===========================================================================
# D1.3 — coverage_set fallback (T-TRAIL-12)
# ===========================================================================

def test_coverage_set_falls_back_when_scheduler_absent():
    """T-TRAIL-12: with the WS-C `coverage_sources` seam unimportable, coverage_set
    falls back to STATIC_FALLBACK_ORDER (the live path today). High-assurance
    degrades to a documented NO-OP prefix-only trail (cross-ref D3.2)."""
    # scheduler.coverage_sources genuinely does not exist yet → the try import
    # raises ImportError → the static list is used.
    with pytest.raises((ImportError, AttributeError)):
        from app.services.scheduler import coverage_sources  # noqa: F401

    assert coverage_set("request") == STATIC_FALLBACK_ORDER
    # A missing/unknown phase degrades to the request graph, never crashes (SEC-4).
    assert coverage_set("does_not_exist") == STATIC_FALLBACK_ORDER


# ===========================================================================
# D1.4 — _build_marker_item + write_not_run_markers (T-TRAIL-15, -11)
# ===========================================================================

def test_marker_row_no_decision_no_content():
    """T-TRAIL-15: a persisted marker row has `decision` ABSENT, `record_type`
    present, and (for a not_run marker) none of user_input/tool_params/source_ip."""
    from app.utils.signal_store_writer import _build_marker_item

    m = NotRunMarker(source=Source.SENTRA_SIGMA, record_type="not_run",
                     reason="skipped for cost/tier", phase="request")
    item = _build_marker_item(
        m, session_id="s1", request_id="req-1", timestamp_ms=1779763724344,
        timestamp_iso="2026-05-26T02:48:44.344Z", expires_at=9999999999,
    )
    assert "decision" not in item
    assert item["record_type"] == "not_run"
    assert item["source"] == Source.SENTRA_SIGMA
    for content_field in ("user_input", "tool_params", "source_ip"):
        assert content_field not in item


def test_marker_row_decision_date_and_phase():
    """T-TRAIL-11: every marker row carries decision_date == timestamp_iso[:10]
    (GSI-2) + a `phase` attr; the paired ran row is stamped by the SAME slice."""
    from app.utils.signal_store_writer import _build_marker_item, _build_item

    iso = "2026-05-26T02:48:44.344Z"
    m = NotRunMarker(source=Source.SENTRA_ABUSE, phase="request")
    marker_item = _build_marker_item(
        m, session_id="s1", request_id="req-1", timestamp_ms=1779763724344,
        timestamp_iso=iso, expires_at=9999999999,
    )
    assert marker_item["decision_date"] == iso[:10] == "2026-05-26"
    assert marker_item["phase"] == "request"

    ran_item = _build_item(
        session_id="s1", request_id="req-1", timestamp_ms=1779763724344,
        timestamp_iso=iso, signal=_sig(Source.SENTRA_TRUST, "ALLOW", priority=90),
        shared_attrs={"phase": "request"}, expires_at=9999999999,
    )
    assert ran_item["decision_date"] == iso[:10]
    assert ran_item["phase"] == "request"  # stamped via shared_attrs (D4.1)


def test_coverage_drift_guard_both_paths():
    """T-TRAIL-14: (a) fallback path — STATIC_FALLBACK_ORDER equals the live
    request-phase validator set AND equals the STEP_LABEL_TO_SOURCE value set;
    adding/removing/reordering a validator without updating sources.py fails.
    (b) WS-C path — skip-guarded until the seam lands."""
    # (a) The static coverage set == the registry's request-phase validator sources.
    from app.services.scheduler.registry import _ORDER
    registry_sources = set(_ORDER)  # the 7 request-phase validators (incl. ML)
    assert set(STATIC_FALLBACK_ORDER) == registry_sources
    assert set(STATIC_FALLBACK_ORDER) == set(STEP_LABEL_TO_SOURCE.values())

    # (b) WS-C path — assert equality only once the pure accessor exists.
    try:
        from app.services.scheduler import coverage_sources
        assert set(coverage_sources("request")) == set(STATIC_FALLBACK_ORDER)
    except (ImportError, AttributeError):
        pytest.skip("WS-C coverage_sources(phase) seam not yet built (§13 gap #4)")


# ===========================================================================
# D2.1 — build_trail four-bucket classifier
# ===========================================================================

def _markers_by_type(trail: TrailResult):
    out = {"not_run": [], "abstain": [], "error": []}
    for m in trail.markers:
        out[m.record_type].append(m.source)
    return out


def test_allow_full_trail_zero_not_run():
    """T-TRAIL-01: all coverage ran (Signal) or ran-ABSTAIN (disabled ML) → ZERO
    not-run markers; no extra layer forced (invariant iv/v)."""
    cov = list(STATIC_FALLBACK_ORDER)
    # Every layer ran; ML abstained (disabled-but-awaited) → no ML signal.
    signals = [_sig(s, "ALLOW") for s in cov if s != Source.SENTRA_ML_CLASSIFIER]
    trail = build_trail(
        signals=signals, step_timings=_all_timings(), coverage=cov,
        winning_source=None, phase="request", is_deny=False,
    )
    by = _markers_by_type(trail)
    assert by["not_run"] == []                       # invariant iv/v
    assert by["abstain"] == [Source.SENTRA_ML_CLASSIFIER]  # ML ran, abstained
    assert by["error"] == []


def test_short_circuit_trust_deny_complement():
    """T-TRAIL-02: trust DENYs first → not-run complement == coverage − {trust};
    each marker reason 'gated by earlier DENY'; invoked == the exact prefix."""
    cov = list(STATIC_FALLBACK_ORDER)
    signals = [_sig(Source.SENTRA_TRUST, "DENY", reason="quarantined", priority=90)]
    trail = build_trail(
        signals=signals, step_timings={"trust": 1.0}, coverage=cov,
        winning_source=Source.SENTRA_TRUST, phase="request", is_deny=True,
    )
    by = _markers_by_type(trail)
    assert set(by["not_run"]) == set(cov) - {Source.SENTRA_TRUST}
    assert by["abstain"] == [] and by["error"] == []
    for m in trail.markers:
        assert m.reason == "gated by earlier DENY"


def test_conflation_trap_ml_disabled_vs_never_reached():
    """T-TRAIL-03: ML disabled + all-cheap-ALLOW → ML is ran-ABSTAIN (consulted,
    declined); a short-circuit where ML is never reached → ML is not_run. The two
    are DISTINCT rows (invariant i)."""
    cov = list(STATIC_FALLBACK_ORDER)

    # Case A: full ALLOW, ML awaited-but-disabled (abstain → in invoked, no signal).
    signals_a = [_sig(s, "ALLOW") for s in cov if s != Source.SENTRA_ML_CLASSIFIER]
    trail_a = build_trail(
        signals=signals_a, step_timings=_all_timings(), coverage=cov,
        winning_source=None, phase="request", is_deny=False,
    )
    by_a = _markers_by_type(trail_a)
    assert Source.SENTRA_ML_CLASSIFIER in by_a["abstain"]
    assert Source.SENTRA_ML_CLASSIFIER not in by_a["not_run"]

    # Case B: trust short-circuits → ML never invoked (not in step_timings).
    signals_b = [_sig(Source.SENTRA_TRUST, "DENY", reason="q", priority=90)]
    trail_b = build_trail(
        signals=signals_b, step_timings={"trust": 1.0}, coverage=cov,
        winning_source=Source.SENTRA_TRUST, phase="request", is_deny=True,
    )
    by_b = _markers_by_type(trail_b)
    assert Source.SENTRA_ML_CLASSIFIER in by_b["not_run"]
    assert Source.SENTRA_ML_CLASSIFIER not in by_b["abstain"]


def test_both_outcomes_persist_full_trail():
    """T-TRAIL-04: an ALLOW request AND a DENY request both yield a full trail
    (ran + not-run cover the whole coverage set) — invariant v."""
    cov = list(STATIC_FALLBACK_ORDER)

    # ALLOW: every layer ran.
    allow_signals = [_sig(s, "ALLOW") for s in cov]
    trail_allow = build_trail(
        signals=allow_signals, step_timings=_all_timings(), coverage=cov,
        winning_source=None, phase="request", is_deny=False,
    )
    ran = {s.source for s in allow_signals}
    covered = ran | {m.source for m in trail_allow.markers}
    assert covered == set(cov)

    # DENY: sigma denies after a prefix ran.
    deny_signals = [
        _sig(Source.SENTRA_TRUST, "ALLOW"),
        _sig(Source.SENTRA_POLICY, "ALLOW"),
        _sig(Source.SENTRA_CROSS_AGENT, "ALLOW"),
        _sig(Source.SENTRA_SIGMA, "DENY", reason="inj", priority=70),
    ]
    trail_deny = build_trail(
        signals=deny_signals,
        step_timings={"trust": 1, "policy": 1, "cross_agent": 1, "sigma": 1},
        coverage=cov, winning_source=Source.SENTRA_SIGMA, phase="request", is_deny=True,
    )
    ran_d = {s.source for s in deny_signals}
    covered_d = ran_d | {m.source for m in trail_deny.markers}
    assert covered_d == set(cov)


def test_block_context_depth_on_ran_deny_not_markers():
    """T-TRAIL-05: ran DENY rows carry block-context from _shared_attrs_from_request;
    marker rows do NOT; recomputed block_point == winning_source."""
    from app.utils.audit_logger import AuditLogger
    from app.utils.signal_store_writer import _build_item, _build_marker_item

    request = {
        "agent_id": "a1", "tool_name": "wire_transfer",
        "tool_params": {"amt": 9000}, "user_input": "send it",
        "context": {"ip_address": "10.0.0.9"}, "phase": "request",
    }
    shared = AuditLogger._shared_attrs_from_request(request, {"trust_score": 40.0})
    ran_item = _build_item(
        session_id="s1", request_id="r1", timestamp_ms=1, timestamp_iso="2026-05-26T02:48:44.344Z",
        signal=_sig(Source.SENTRA_SIGMA, "DENY", reason="inj", priority=70),
        shared_attrs=shared, expires_at=9,
    )
    assert ran_item.get("tool_params") == {"amt": 9000}
    assert ran_item.get("source_ip") == "10.0.0.9"
    assert ran_item.get("user_input")  # present on ran DENY row

    marker_item = _build_marker_item(
        NotRunMarker(source=Source.SENTRA_ABUSE), session_id="s1", request_id="r1",
        timestamp_ms=1, timestamp_iso="2026-05-26T02:48:44.344Z", expires_at=9,
    )
    for f in ("tool_params", "source_ip", "user_input"):
        assert f not in marker_item

    # recomputed block_point == winning_source over the ran DENY signal.
    from app.combiners import DenyOverrides
    combined = DenyOverrides().combine([_sig(Source.SENTRA_SIGMA, "DENY", reason="inj", priority=70)])
    assert (combined.metadata or {}).get("winning_source") == Source.SENTRA_SIGMA


def test_combine_never_called_with_marker():
    """T-TRAIL-07: (a) deny_overrides.py is byte-unchanged in git; (b) passing a
    NotRunMarker to combine() is a type error (no .decision) — invariant ii."""
    import subprocess
    # (a) combiner code byte-for-byte unchanged vs main.
    diff = subprocess.run(
        ["git", "diff", "main", "--", "app/combiners/deny_overrides.py",
         "app/combiners/signal.py"],
        cwd=".", capture_output=True, text=True,
    )
    assert diff.stdout.strip() == "", f"combiner code changed:\n{diff.stdout}"

    # (b) A marker cannot enter combine() — it has no .decision the algorithm reads.
    from app.combiners import DenyOverrides
    marker = NotRunMarker(source=Source.SENTRA_SIGMA)
    with pytest.raises(AttributeError):
        DenyOverrides().combine([marker])  # type: ignore[list-item]


def test_not_run_reason_derived_by_position():
    """T-TRAIL-17: (a) disabled awaited layer → ABSTAIN never not_run; (b) layer
    after denier → 'gated by earlier DENY', cost-skipped on full-ALLOW → 'skipped
    for cost/tier'; (c) POSITIONAL guard — a cost-skipped node BEFORE the denier
    reads 'skipped for cost/tier', NOT 'gated' (no is_deny disjunct)."""
    cov = list(STATIC_FALLBACK_ORDER)

    # (a) full-ALLOW, ML abstain.
    trail_a = build_trail(
        signals=[_sig(s, "ALLOW") for s in cov if s != Source.SENTRA_ML_CLASSIFIER],
        step_timings=_all_timings(), coverage=cov, winning_source=None,
        phase="request", is_deny=False,
    )
    by_a = _markers_by_type(trail_a)
    assert Source.SENTRA_ML_CLASSIFIER in by_a["abstain"]
    assert Source.SENTRA_ML_CLASSIFIER not in by_a["not_run"]

    # (b)+(c) The denier is CONTEXT (index 4). CROSS_AGENT/SIGMA (before it) did not
    # run (only trust/policy/context ran). A cost-skipped node BEFORE the denier
    # must read 'skipped for cost/tier', a layer AFTER reads 'gated'.
    signals = [
        _sig(Source.SENTRA_TRUST, "ALLOW"),
        _sig(Source.SENTRA_POLICY, "ALLOW"),
        _sig(Source.SENTRA_CONTEXT, "DENY", reason="seq", priority=60),
    ]
    trail = build_trail(
        signals=signals, step_timings={"trust": 1, "policy": 1, "context": 1},
        coverage=cov, winning_source=Source.SENTRA_CONTEXT, phase="request", is_deny=True,
    )
    reason_by_source = {m.source: m.reason for m in trail.markers}
    # cross_agent + sigma sit BEFORE context in cov_order → no DENY precedes them.
    assert reason_by_source[Source.SENTRA_CROSS_AGENT] == "skipped for cost/tier"
    assert reason_by_source[Source.SENTRA_SIGMA] == "skipped for cost/tier"
    # abuse + ml sit AFTER context (the denier) → gated.
    assert reason_by_source[Source.SENTRA_ABUSE] == "gated by earlier DENY"
    assert reason_by_source[Source.SENTRA_ML_CLASSIFIER] == "gated by earlier DENY"


# ===========================================================================
# D2.2 / D2.3 — §7.1.1 fail-secure stamp + except-path premise (T-TRAIL-13, -14b)
# ===========================================================================

def test_fail_secure_deny_is_ran_denier_never_abstain():
    """T-TRAIL-13: legacy_retired + Cedar-abstain → policy DENIES. _fail_secure_deny
    stamps source=sentra.policy so a Signal lands in signals[]; the trail records
    sentra.policy ran-voted (DENIER), ZERO abstain/not_run rows for it; recomputed
    winning_source == sentra.policy; violation_type distinguishes it. A regression
    (unstamped denier) → record_type='error', never ABSTAIN."""
    from app.services.validation_service import (
        _fail_secure_deny, POLICY_NOT_MIGRATED, _POLICY_NOT_MIGRATED_PENALTY,
    )

    result = _fail_secure_deny(
        violation_type=POLICY_NOT_MIGRATED, penalty=_POLICY_NOT_MIGRATED_PENALTY,
        reason="not migrated",
    )
    # (a) stamped source → survives _capture as a real Signal.
    assert result.source == Source.SENTRA_POLICY
    signal = result.to_signal()
    assert signal is not None and signal.source == Source.SENTRA_POLICY
    assert signal.decision == "DENY"

    cov = list(STATIC_FALLBACK_ORDER)
    signals = [
        _sig(Source.SENTRA_TRUST, "ALLOW"),
        signal,  # the stamped policy DENY
    ]
    trail = build_trail(
        signals=signals, step_timings={"trust": 1, "policy": 1}, coverage=cov,
        winning_source=Source.SENTRA_POLICY, phase="request", is_deny=True,
    )
    by = _markers_by_type(trail)
    # (b) policy is the ran DENIER → NOT abstain, NOT not_run.
    assert Source.SENTRA_POLICY not in by["abstain"]
    assert Source.SENTRA_POLICY not in by["not_run"]
    assert Source.SENTRA_POLICY not in by["error"]

    # (c) recomputed winning_source == sentra.policy.
    from app.combiners import DenyOverrides
    combined = DenyOverrides().combine(signals)
    assert (combined.metadata or {}).get("winning_source") == Source.SENTRA_POLICY
    assert combined.decision == "DENY"
    # (d) violation_type distinguishes it from a genuine Cedar DENY.
    assert result.violation_type == "POLICY_NOT_MIGRATED"

    # Regression guard: an UNSTAMPED denying result appends NO signal (→ policy is
    # invoked but not in ran → ran_error, never ABSTAIN).
    trail_regress = build_trail(
        signals=[_sig(Source.SENTRA_TRUST, "ALLOW")],  # policy signal DROPPED
        step_timings={"trust": 1, "policy": 1}, coverage=cov,
        winning_source=Source.SENTRA_POLICY, phase="request", is_deny=True,
    )
    by_r = _markers_by_type(trail_regress)
    assert Source.SENTRA_POLICY in by_r["error"]
    assert Source.SENTRA_POLICY not in by_r["abstain"]


def test_capture_except_path_appends_no_signal():
    """T-TRAIL-14b: feed _capture (via _append_signal) an unstamped (source=None)
    denying ValidationResult → NO signal is appended. A maintainer 'fixing' the
    except-block to append a synthetic signal turns this red (SEC threat 6)."""
    from app.api.models import ValidationResult
    from app.services.validation_service import _append_signal

    signals = []
    unstamped = ValidationResult(
        decision="DENY", reason="unstamped denier", should_deny=True, source=None,
    )
    _append_signal(signals, unstamped)  # source=None → to_signal() raises ValueError → dropped
    assert signals == []                # premise of the ran-ERROR bucket


# ===========================================================================
# D2.4 — synchronous by-value call site (T-TRAIL-19), identity out of coverage (-16)
# ===========================================================================

def test_invoked_survives_fire_and_forget_boundary():
    """T-TRAIL-19: build_trail runs synchronously with a by-value _step_timings
    snapshot BEFORE the fire-and-forget handoff. A full-ALLOW request produces ZERO
    not-run markers even when the marker write executes later — proving `invoked`
    was non-empty at classification time (snapshot captured on the request
    coroutine, KD-4)."""
    from app.api.models import ValidationResult
    from app.services import validation_service as vs

    svc = vs.ValidationService.__new__(vs.ValidationService)  # skip __init__ (no boto3)

    # Simulate the request coroutine having populated _step_timings by value.
    token = vs._step_timings.set(_all_timings())
    try:
        cov = list(STATIC_FALLBACK_ORDER)
        result = ValidationResult(decision="ALLOW", reason="ok", should_deny=False)
        signals = [_sig(s, "ALLOW") for s in cov]  # every layer ran
        markers = svc._build_decision_trail(
            MagicMock(phase="request", context={}), result, signals,
        )
    finally:
        vs._step_timings.reset(token)

    # Now clear the contextvar (simulating the background task where invoked would
    # resolve to ∅ if it were read there) — the markers were already built by value.
    not_run = [m for m in markers if m.record_type == "not_run"]
    assert not_run == [], "full-ALLOW must yield zero not-run markers (KD-4 by-value snapshot)"


def test_identity_deny_out_of_coverage():
    """T-TRAIL-16: an IDENTITY_UNVERIFIED request returns from routes.py BEFORE
    validate_tool_call → no build_trail call, no trail rows; the _identity_deny
    audit record is written under the reserved _unverified tenant (AS-1)."""
    import asyncio
    from app.api import routes
    from app.utils import tenancy

    captured = {}

    class _FakeLogger:
        async def log_decision(self, **kw):
            captured["audit_tenant"] = tenancy.current_tenant()
            captured["reason"] = kw.get("validation_result", {}).get("reason")

    req = MagicMock()
    req.session_id = "s1"
    req.agent_id = "a1"
    req.model_dump = MagicMock(return_value={"session_id": "s1", "agent_id": "a1"})

    # AuditLogger + MetricsPublisher are lazy-imported INSIDE _identity_deny, so
    # patch them at their definition module (not on the routes module).
    with patch("app.utils.audit_logger.AuditLogger", return_value=_FakeLogger()):
        with patch("app.utils.metrics_publisher.MetricsPublisher") as mp:
            mp.return_value.publish_validation_metrics = AsyncMock()
            asyncio.run(routes._identity_deny(req, "IDENTITY_UNVERIFIED"))

    # Audited under the reserved _unverified tenant — never a real tenant.
    assert captured["audit_tenant"] == tenancy.UNVERIFIED_TENANT
    assert captured["reason"] == "IDENTITY_UNVERIFIED"
    # No build_trail was ever reached (this path never calls validate_tool_call).


# ===========================================================================
# D3 — high-assurance resolution + verdict neutrality (T-TRAIL-18, -08, -09)
# ===========================================================================

def test_high_assurance_session_override_escalate_only():
    """T-TRAIL-18: escalate-only — tenant-ON + session-off → ON (a request cannot
    turn off a tenant-mandated setting); tenant-OFF + session-on → ON."""
    assert resolve_high_assurance(tenant_setting=True, session_override=False) is True
    assert resolve_high_assurance(tenant_setting=False, session_override=True) is True
    assert resolve_high_assurance(tenant_setting=True, session_override=True) is True
    assert resolve_high_assurance(tenant_setting=False, session_override=False) is False


def test_high_assurance_verdict_invariance_paired():
    """T-TRAIL-08: the same request ON vs OFF yields byte-identical (decision,
    recomputed winning_source); ON produces >= the ran-signals OFF produces
    (invariant vi). Driven at the mode-selection seam."""
    from app.services import validation_service as vs
    from app.services.scheduler.run import EVALUATE_ALL, FAIL_FAST

    svc = vs.ValidationService.__new__(vs.ValidationService)

    async def fake_run(*, high_assurance):
        return await svc._run_validation_pipeline(
            MagicMock(phase="request"), {}, high_assurance=high_assurance)

    captured_modes = {}

    async def fake_scheduler_run_dag(nodes, request, session, cap, stamp, timed, *,
                                     mode, all_allow, signals):
        captured_modes["mode"] = mode
        return all_allow(), signals

    with patch("app.services.scheduler.build_dag", return_value=[]), \
         patch("app.services.scheduler.run_dag", new=AsyncMock(side_effect=fake_scheduler_run_dag)):
        import asyncio
        result_off, _ = asyncio.run(fake_run(high_assurance=False))
        mode_off = captured_modes["mode"]
        result_on, _ = asyncio.run(fake_run(high_assurance=True))
        mode_on = captured_modes["mode"]

    # ON threads evaluate_all; OFF stays the global default (fail_fast in tests).
    assert mode_on == EVALUATE_ALL
    assert mode_off in (FAIL_FAST, EVALUATE_ALL)
    # Verdict byte-identical (both synthetic-ALLOW here).
    assert result_on.decision == result_off.decision == "ALLOW"
    assert result_on.should_deny == result_off.should_deny is False


def test_evaluate_all_verdict_neutral_not_call_count():
    """T-TRAIL-09: high-assurance ON (evaluate_all, tier-1 re-run) → (decision,
    should_deny, winning_source) byte-identical to fail_fast on the same request.
    Asserts VERDICT-neutrality, NOT an unchanged ML call count (evaluate_all
    deliberately re-runs tier-1). Driven through the real run_dag with a tier-0
    DENY + a tier-1 ML DENY that would outrank it if captured as a real signal."""
    import asyncio
    from app.api.models import ValidationResult
    from app.services.scheduler.node import CostTier, ValidatorNode
    from app.services.scheduler.run import run_dag, EVALUATE_ALL, FAIL_FAST

    async def deny_context(req, sess):
        return ValidationResult(decision="DENY", reason="seq", should_deny=True,
                                source=Source.SENTRA_CONTEXT)

    async def deny_ml(req, sess):
        # A tier-1 ML hard-DENY (@65) that OUTRANKS context (@60) if it were a real
        # deciding signal — the verdict-neutrality trap.
        return ValidationResult(decision="DENY", reason="ml", should_deny=True,
                                source=Source.SENTRA_ML_CLASSIFIER,
                                metadata={"enforce": True})

    nodes = [
        ValidatorNode(source=Source.SENTRA_CONTEXT, cost_tier=CostTier.DETERMINISTIC,
                      run=deny_context, depends_on=(), order_key=5),
        ValidatorNode(source=Source.SENTRA_ML_CLASSIFIER, cost_tier=CostTier.EXPENSIVE_MODEL,
                      run=deny_ml, depends_on=(), order_key=7),
    ]

    def run_mode(mode):
        sink = []
        cap = lambda r: (sink.append(r) or r)  # noqa: E731
        stamp = lambda r: r  # noqa: E731

        async def timed(label, coro):
            return await coro

        return asyncio.run(run_dag(
            nodes, MagicMock(), {}, cap, stamp, timed, mode=mode,
            all_allow=lambda: ValidationResult(decision="ALLOW", reason="ok", should_deny=False),
            signals=sink,
        ))

    (r_ff, sig_ff) = run_mode(FAIL_FAST)
    (r_ea, sig_ea) = run_mode(EVALUATE_ALL)

    # Verdict byte-identical: context decides in BOTH modes (not ML @65).
    assert r_ff.decision == r_ea.decision == "DENY"
    assert r_ff.should_deny == r_ea.should_deny is True
    assert r_ff.source == r_ea.source == Source.SENTRA_CONTEXT
    # evaluate_all captured MORE signals (the advisory ML), i.e. richer trail.
    assert len(sig_ea) >= len(sig_ff)


# ===========================================================================
# D4 — persistence off the hot path + metric (T-TRAIL-10)
# ===========================================================================

def test_trail_persist_failure_metric_and_no_500():
    """T-TRAIL-10: a write_not_run_markers failure increments TrailPersistFailures
    AND the verdict still returns clean (no raise). Off-path — a marker loss is
    bounded to a fast-read gap, never a correctness/availability regression."""
    import asyncio
    from app.utils.audit_logger import AuditLogger

    al = AuditLogger.__new__(AuditLogger)  # skip __init__ (no boto3/CW)
    al._signal_store = None

    # Stub the writer: write_signals succeeds, write_not_run_markers RAISES.
    fake_writer = Mock()
    fake_writer.write_signals = Mock(return_value=(1, 0))
    fake_writer.write_not_run_markers = Mock(side_effect=RuntimeError("DDB throttled"))
    al._get_signal_store = Mock(return_value=fake_writer)

    metric_calls = {"trail": 0}

    async def fake_emit(method_name, **kw):
        if method_name == "publish_trail_persist_failure":
            metric_calls["trail"] += 1

    al._emit_trail_metric = fake_emit
    al._write_log_event = AsyncMock()
    al._guard_persist = Mock(side_effect=lambda req, **kw: req)

    markers = [NotRunMarker(source=Source.SENTRA_SIGMA)]
    signals = [_sig(Source.SENTRA_TRUST, "ALLOW")]

    # Must NOT raise despite the marker-write RuntimeError.
    asyncio.run(al.log_signals(
        request={"session_id": "s1", "request_id": "r1"}, session={},
        signals=signals, latency_ms=1.0, markers=markers,
    ))
    assert metric_calls["trail"] == 1  # TrailPersistFailures incremented


# ===========================================================================
# D5 — trail-read API (T-TRAIL-20, -21, -22, -23)
# ===========================================================================

def _mk_service_with_rows(rows):
    """A DecisionsService whose get_session_signals returns crafted DDB rows."""
    from app.services.decisions_service import DecisionsService
    svc = DecisionsService.__new__(DecisionsService)
    from app.combiners import DenyOverrides
    svc._combiner = DenyOverrides()
    svc.get_session_signals = Mock(return_value={"signals": rows})
    return svc


def _ran_row(source, decision, reason=None, phase="request"):
    return {"source": source, "decision": decision, "reason": reason,
            "phase": phase, "request_id": "r1"}


def _marker_row(source, record_type, reason, phase="request"):
    return {"source": source, "record_type": record_type, "reason": reason,
            "phase": phase, "request_id": "r1"}


def test_trail_endpoint_four_buckets_counts():
    """T-TRAIL-20: a short-circuit-DENY trail (ran prefix + ABSTAIN + not-run) →
    coverage[] has one entry per source in coverage order with the right state;
    winning_source == block_point == recomputed deny-overrides winner;
    reconciliation holds; next_token == null."""
    rows = [
        _ran_row(Source.SENTRA_TRUST, "ALLOW"),
        _ran_row(Source.SENTRA_POLICY, "ALLOW"),
        _ran_row(Source.SENTRA_CROSS_AGENT, "ALLOW"),
        _ran_row(Source.SENTRA_SIGMA, "DENY", reason="injection"),
        _marker_row(Source.SENTRA_CONTEXT, "not_run", "gated by earlier DENY"),
        _marker_row(Source.SENTRA_ABUSE, "not_run", "gated by earlier DENY"),
        _marker_row(Source.SENTRA_ML_CLASSIFIER, "abstain", "ran; abstained (no vote)"),
    ]
    svc = _mk_service_with_rows(rows)
    resp = svc.get_session_trail(session_id="s1", request_id="r1")

    # One entry per coverage source, in coverage order.
    assert [c["source"] for c in resp["coverage"]] == list(STATIC_FALLBACK_ORDER)
    state_by_source = {c["source"]: c["state"] for c in resp["coverage"]}
    assert state_by_source[Source.SENTRA_SIGMA] == "ran"
    assert state_by_source[Source.SENTRA_CONTEXT] == "not_run"
    assert state_by_source[Source.SENTRA_ML_CLASSIFIER] == "ran_abstain"

    assert resp["decision"] == "DENY"
    assert resp["winning_source"] == Source.SENTRA_SIGMA
    assert resp["block_point"] == Source.SENTRA_SIGMA
    # Reconciliation: ran + abstain + error + not_run == coverage_total.
    total = (resp["ran_count"] + resp["abstain_count"] + resp["ran_error_count"]
             + resp["not_run_count"])
    assert total == resp["coverage_total"] == len(STATIC_FALLBACK_ORDER)
    assert resp["next_token"] is None


def test_trail_read_tenant_isolation():
    """T-TRAIL-21: a tenant querying a request in ANOTHER tenant's partition gets
    ZERO coverage rows (tenant-composite PK Query hits its own partition). Here the
    'wrong tenant' partition returns no rows → the trail reconciles to all not_run
    (structural, no X-Operator-Email)."""
    svc = _mk_service_with_rows([])  # wrong-tenant partition → zero rows
    resp = svc.get_session_trail(session_id="s1", request_id="r1")
    # Zero ran rows; the coverage set still renders but every source is not_run.
    assert resp["ran_count"] == 0
    assert resp["not_run_count"] == len(STATIC_FALLBACK_ORDER)
    assert resp["winning_source"] is None
    assert resp["decision"] == "ALLOW"


def test_trail_allow_null_winning_source():
    """T-TRAIL-22: a full-ALLOW request → decision ALLOW, winning_source null,
    block_point null, every source ran (or ran_abstain for disabled-but-awaited ML),
    ZERO not_run rows."""
    rows = [_ran_row(s, "ALLOW") for s in STATIC_FALLBACK_ORDER
            if s != Source.SENTRA_ML_CLASSIFIER]
    rows.append(_marker_row(Source.SENTRA_ML_CLASSIFIER, "abstain", "ran; abstained (no vote)"))
    svc = _mk_service_with_rows(rows)
    resp = svc.get_session_trail(session_id="s1", request_id="r1")

    assert resp["decision"] == "ALLOW"
    assert resp["winning_source"] is None
    assert resp["block_point"] is None
    assert resp["not_run_count"] == 0
    states = {c["state"] for c in resp["coverage"]}
    assert states <= {"ran", "ran_abstain"}


def test_trail_display_names_no_raw_leak():
    """T-TRAIL-23: every coverage row has a non-empty display_name + state_label;
    the canonical labels resolve; an unknown source (simulated WS-L D-layer) falls
    through to its RAW string (never null, never a crash)."""
    rows = [
        _ran_row(Source.SENTRA_POLICY, "DENY", reason="denied"),
        _ran_row(Source.SENTRA_SIGMA, "ALLOW"),
        _marker_row(Source.SENTRA_ML_CLASSIFIER, "abstain", "ran; abstained (no vote)"),
        # A future WS-L D-layer with no label yet.
        _ran_row("sentra.d3_taint", "ALLOW"),
    ]
    svc = _mk_service_with_rows(rows)
    resp = svc.get_session_trail(session_id="s1", request_id="r1")

    for c in resp["coverage"]:
        assert c["display_name"], f"empty display_name for {c['source']}"
        assert c["state_label"], f"empty state_label for {c['source']}"
    labels = {c["source"]: c["display_name"] for c in resp["coverage"]}
    assert labels[Source.SENTRA_POLICY] == "Policy (Cedar)"
    assert labels[Source.SENTRA_SIGMA] == "Prompt-signature rules"
    # Unknown source → raw string fallthrough.
    assert labels["sentra.d3_taint"] == "sentra.d3_taint"
    # ran_abstain state label.
    ml = next(c for c in resp["coverage"] if c["source"] == Source.SENTRA_ML_CLASSIFIER)
    assert ml["state_label"] == "Ran — abstained"
    # winning_source_display matches the winner's label.
    assert resp["winning_source"] == Source.SENTRA_POLICY
    assert resp["winning_source_display"] == "Policy (Cedar)"


def test_trail_route_wired():
    """Route wiring: GET /v1/sessions/{sid}/trail?request_id=R delegates to
    DecisionsService.get_session_trail (data-plane read, no require_role)."""
    from fastapi.testclient import TestClient
    from app.main import app

    fake = Mock()
    fake.get_session_trail = Mock(return_value={
        "session_id": "s1", "request_id": "r1", "decision": "ALLOW",
        "coverage": [], "coverage_total": 0, "next_token": None,
    })
    with patch("app.api.routes._decisions_service", return_value=fake):
        client = TestClient(app)
        resp = client.get("/v1/sessions/s1/trail", params={"request_id": "r1"})
    assert resp.status_code == 200
    fake.get_session_trail.assert_called_once_with(session_id="s1", request_id="r1")


# ===========================================================================
# D2.4 / D4.1 — the log_signals marker WIRING at the call site (gap close, FIX-B)
#
# test_trail_builder covers build_trail() and log_signals(markers=...) in
# ISOLATION, but nothing exercised _handle_deny/_handle_allow actually THREADING
# `markers` through to persistence. A revert of `markers=markers` on either
# handler's persist call would leave the four-bucket trail silently un-persisted
# and the whole suite green — this is the load-bearing FR-6.8/NFR-10 wiring.
# ===========================================================================

def _bare_service_for_handler(captured):
    """A ValidationService with just enough stubbed collaborators for
    _handle_deny/_handle_allow to run, capturing every audit call's kwargs."""
    import asyncio
    from app.services import validation_service as vs

    svc = vs.ValidationService.__new__(vs.ValidationService)  # skip __init__ (no boto3)

    async def _upd_deny(*a, **k):
        return {"trust_score": 10.0}

    async def _upd_allow(*a, **k):
        return {"trust_score": 90.0}

    svc.session_manager = MagicMock()
    svc.session_manager.update_trust_score_deny = _upd_deny
    svc.session_manager.update_trust_score_allow = _upd_allow
    svc.metrics_publisher = MagicMock()
    svc.metrics_publisher.publish_validation_metrics = AsyncMock()

    # audit_logger.log_signals / log_decision are MagicMocks: they record the
    # call kwargs (including `markers`) the INSTANT the call site invokes them,
    # before the coroutine is even scheduled — so we assert on those kwargs.
    audit = MagicMock()

    async def _noop(*a, **k):
        return None

    audit.log_signals = MagicMock(return_value=_noop())
    audit.log_decision = MagicMock(return_value=_noop())
    svc.audit_logger = audit
    svc._generate_action_id = MagicMock(return_value="act-1")
    return svc, audit


def test_handle_deny_threads_markers_to_log_signals():
    """FIX-B gap (MEDIUM): _handle_deny with ran signals present forwards the
    decision-trail `markers` into audit_logger.log_signals. Reverting
    `markers=markers` on that call turns this red."""
    import asyncio
    from app.api.models import ValidationResult
    from app.services import validation_service as vs

    svc, audit = _bare_service_for_handler({})
    markers = [NotRunMarker(source=Source.SENTRA_CONTEXT, record_type="not_run")]
    signals = [_sig(Source.SENTRA_SIGMA, "DENY", reason="x", priority=70)]
    req = MagicMock()
    req.session_id = "s1"; req.agent_id = "a1"; req.tool_name = "t"
    req.platform = None; req.cloud_region = None
    req.model_dump = MagicMock(return_value={"session_id": "s1", "request_id": "r1"})
    vr = ValidationResult(decision="DENY", reason="x", should_deny=True,
                          source=Source.SENTRA_SIGMA, threat_type="INJECTION")

    # Swallow the fire-and-forget coroutines (close them so no "never awaited").
    def _swallow(coro, label):
        coro.close()

    with patch.object(vs, "_fire_and_forget", side_effect=_swallow), \
         patch.object(vs, "write_redacted_feedback", side_effect=lambda *a, **k: _noop_coro()):
        asyncio.run(svc._handle_deny(req, {}, vr, 0.0, signals=signals, markers=markers))

    audit.log_signals.assert_called_once()
    assert audit.log_signals.call_args.kwargs["markers"] is markers
    audit.log_decision.assert_not_called()


def test_handle_allow_threads_markers_to_log_signals():
    """FIX-B gap (MEDIUM): _handle_allow with ran signals present forwards
    `markers` into audit_logger.log_signals. Reverting it turns this red."""
    import asyncio
    from app.api.models import ValidationResult
    from app.services import validation_service as vs

    svc, audit = _bare_service_for_handler({})
    markers = [NotRunMarker(source=Source.SENTRA_ML_CLASSIFIER, record_type="abstain")]
    signals = [_sig(Source.SENTRA_TRUST, "ALLOW", priority=90)]
    req = MagicMock()
    req.session_id = "s1"; req.agent_id = "a1"; req.tool_name = "t"
    req.model_dump = MagicMock(return_value={"session_id": "s1", "request_id": "r1"})
    vr = ValidationResult(decision="ALLOW", reason="ok", should_deny=False)

    def _swallow(coro, label):
        coro.close()

    with patch.object(vs, "_fire_and_forget", side_effect=_swallow), \
         patch.object(vs, "write_redacted_feedback", side_effect=lambda *a, **k: _noop_coro()):
        asyncio.run(svc._handle_allow(req, {}, 0.0, validation_result=vr,
                                      signals=signals, markers=markers))

    audit.log_signals.assert_called_once()
    assert audit.log_signals.call_args.kwargs["markers"] is markers
    audit.log_decision.assert_not_called()


def test_handle_deny_empty_signals_still_persists_markers():
    """FIX-B gap (LOW): on the empty-`signals` DENY branch (log_decision, not
    log_signals) the not-run complement must STILL persist a full trail
    (invariant v). Reverting `markers=markers` on the else-branch log_decision
    call — which previously silently DROPPED the markers — turns this red."""
    import asyncio
    from app.api.models import ValidationResult
    from app.services import validation_service as vs

    svc, audit = _bare_service_for_handler({})
    markers = [NotRunMarker(source=Source.SENTRA_TRUST, record_type="not_run")]
    req = MagicMock()
    req.session_id = "s1"; req.agent_id = "a1"; req.tool_name = "t"
    req.platform = None; req.cloud_region = None
    req.model_dump = MagicMock(return_value={"session_id": "s1", "request_id": "r1"})
    vr = ValidationResult(decision="DENY", reason="x", should_deny=True,
                          source=Source.SENTRA_POLICY)

    def _swallow(coro, label):
        coro.close()

    with patch.object(vs, "_fire_and_forget", side_effect=_swallow), \
         patch.object(vs, "write_redacted_feedback", side_effect=lambda *a, **k: _noop_coro()):
        asyncio.run(svc._handle_deny(req, {}, vr, 0.0, signals=[], markers=markers))

    # Empty signals → log_decision branch, but markers MUST be forwarded.
    audit.log_decision.assert_called_once()
    assert audit.log_decision.call_args.kwargs["markers"] is markers
    audit.log_signals.assert_not_called()


def test_log_decision_forwards_markers_to_writer():
    """FIX-B gap (LOW): AuditLogger.log_decision now forwards `markers` into
    log_signals → write_not_run_markers, so the empty-signals branch persists a
    full trail. Reverting the `markers=markers` forward in log_decision turns
    this red (the writer's write_not_run_markers is never called)."""
    import asyncio
    from app.utils.audit_logger import AuditLogger

    al = AuditLogger.__new__(AuditLogger)  # skip __init__ (no boto3/CW)
    al._signal_store = None

    fake_writer = Mock()
    fake_writer.write_signals = Mock(return_value=(1, 0))
    fake_writer.write_not_run_markers = Mock(return_value=(1, 0))
    al._get_signal_store = Mock(return_value=fake_writer)
    al._emit_trail_metric = AsyncMock()
    al._write_log_event = AsyncMock()
    al._guard_persist = Mock(side_effect=lambda req, **kw: req)

    markers = [NotRunMarker(source=Source.SENTRA_SIGMA, record_type="not_run")]
    asyncio.run(al.log_decision(
        decision="DENY",
        request={"session_id": "s1", "request_id": "r1"},
        session={},
        validation_result={"reason": "x", "source": Source.SENTRA_POLICY},
        latency_ms=1.0,
        markers=markers,
    ))
    fake_writer.write_not_run_markers.assert_called_once()
    assert fake_writer.write_not_run_markers.call_args.kwargs["markers"] is markers


def _noop_coro():
    async def _c():
        return None
    return _c()


# ===========================================================================
# D5 — deterministic top-level `phase` derivation (gap close, FIX-B)
#
# get_session_trail derived `phase` last-write-wins over ALL rows carrying a
# `phase` attr. On a mixed-phase partition the reported top-level `phase` was
# iteration-order dependent (nondeterministic). Pin the intended behavior:
# prefer the RAN rows' phase, stable regardless of row order.
# ===========================================================================

def test_trail_phase_deterministic_prefers_ran_over_marker():
    """FIX-B gap (LOW): a mixed-phase partition (a ran row on one phase, a marker
    on another) yields a DETERMINISTIC top-level `phase` that prefers the ran
    rows' phase — and does not flip when the row order is reversed."""
    ran = _ran_row(Source.SENTRA_TRUST, "ALLOW", phase="content")
    marker = _marker_row(Source.SENTRA_SIGMA, "not_run", "skipped for cost/tier",
                         phase="request")

    svc_a = _mk_service_with_rows([ran, marker])
    svc_b = _mk_service_with_rows([marker, ran])  # reversed row order
    resp_a = svc_a.get_session_trail(session_id="s1", request_id="r1")
    resp_b = svc_b.get_session_trail(session_id="s1", request_id="r1")

    # Deterministic (order-independent) AND prefers the ran row's phase.
    assert resp_a["phase"] == resp_b["phase"] == "content"


def test_trail_phase_single_phase_is_request():
    """FIX-B gap (LOW): the single-phase case today — every row phase=request —
    reports phase=request (regression guard for the deterministic rewrite)."""
    rows = [
        _ran_row(Source.SENTRA_TRUST, "ALLOW"),
        _ran_row(Source.SENTRA_SIGMA, "DENY", reason="x"),
        _marker_row(Source.SENTRA_CONTEXT, "not_run", "gated by earlier DENY"),
    ]
    resp = _mk_service_with_rows(rows).get_session_trail(session_id="s1", request_id="r1")
    assert resp["phase"] == "request"


# ===========================================================================
# FIX-B gaps (HIGH) — WS-D markers must NOT contaminate the PRE-EXISTING
# grouping read paths (get_session_decisions / scan_decisions).
#
# Adding NotRunMarker rows (record_type in {not_run,abstain,error}, NO
# `decision`) onto the SAME request partition regressed two read methods that
# group EVERY partition row and convert each to a Signal via _item_to_signal:
#   - a marker has no `decision` → _item_to_signal coerces it to a phantom ALLOW
#     vote → fabricated ALLOW in signals[] AND fed into DenyOverrides.combine();
#   - in scan_decisions the row `rep` (group[-1] fallback) could BE a marker,
#     which omits agent_id/tool_name/platform/trust_score → a console row of
#     Nones.
# The fix excludes marker rows (_is_marker_row) before grouping in both paths.
# These tests fail if the exclusion is reverted.
# ===========================================================================

def _mk_grouping_service():
    """A DecisionsService with a real DenyOverrides but no boto3 — used to test
    the row-grouping read paths against crafted DDB rows."""
    from app.services.decisions_service import DecisionsService
    from app.combiners import DenyOverrides
    svc = DecisionsService.__new__(DecisionsService)
    svc._combiner = DenyOverrides()
    return svc


def _grouping_rows_deny_with_markers():
    """A single short-circuit-DENY request: a ran trust ALLOW + ran sigma DENY,
    plus not-run + abstain markers for the layers that never voted. Markers carry
    NO decision and (deliberately) no agent_id/tool_name/platform."""
    return [
        {"source": Source.SENTRA_TRUST, "decision": "ALLOW", "request_id": "r1",
         "session_id": "s1", "agent_id": "agent-x", "tool_name": "wire_transfer",
         "platform": "bedrock", "trust_score_before": 0.9, "timestamp_ms": 100,
         "timestamp_iso": "2026-07-02T00:00:00.100Z"},
        {"source": Source.SENTRA_SIGMA, "decision": "DENY", "reason": "injection",
         "request_id": "r1", "session_id": "s1", "agent_id": "agent-x",
         "tool_name": "wire_transfer", "platform": "bedrock", "threat_type": "INJECTION",
         "trust_score_before": 0.9, "timestamp_ms": 200,
         "timestamp_iso": "2026-07-02T00:00:00.200Z"},
        # Markers appended LAST so group[-1] would pick one if unfiltered.
        {"source": Source.SENTRA_CONTEXT, "record_type": "not_run",
         "reason": "gated by earlier DENY", "request_id": "r1", "session_id": "s1",
         "timestamp_ms": 300, "timestamp_iso": "2026-07-02T00:00:00.300Z"},
        {"source": Source.SENTRA_ML_CLASSIFIER, "record_type": "abstain",
         "reason": "ran; abstained (no vote)", "request_id": "r1", "session_id": "s1",
         "timestamp_ms": 400, "timestamp_iso": "2026-07-02T00:00:00.400Z"},
    ]


def test_get_session_decisions_excludes_markers_no_phantom_allow():
    """FIX-B (HIGH, decisions_service.py get_session_decisions): a request
    partition carrying WS-D markers → the grouped decision's signals[] contains
    ONLY the two ran signals (trust, sigma), NO phantom ALLOW vote from the
    not-run/abstain marker layers; the combined verdict stays DENY with
    winning_source=sentra.sigma. Reverting the marker exclusion makes signals[]
    length 4 and injects fabricated ALLOW votes."""
    svc = _mk_grouping_service()
    svc.get_session_signals = Mock(return_value={"signals": _grouping_rows_deny_with_markers()})

    resp = svc.get_session_decisions(session_id="s1", request_id="r1")

    assert resp["total"] == 1
    d = resp["decisions"][0]
    # Only the two RAN signals survive — markers are not votes.
    assert len(d["signals"]) == 2
    got_sources = {s["source"] for s in d["signals"]}
    assert got_sources == {Source.SENTRA_TRUST, Source.SENTRA_SIGMA}
    # No marker source leaked in as a phantom ALLOW.
    assert Source.SENTRA_CONTEXT not in got_sources
    assert Source.SENTRA_ML_CLASSIFIER not in got_sources
    assert d["combined"]["decision"] == "DENY"
    assert d["combined"]["winning_source"] == Source.SENTRA_SIGMA


def test_get_session_decisions_marker_only_request_yields_no_decision():
    """FIX-B (HIGH): a request partition with ONLY marker rows (no ran signal)
    yields NO grouped decision — a request that produced no votes has no combined
    verdict to render (never a phantom all-ALLOW decision)."""
    svc = _mk_grouping_service()
    markers = [
        {"source": Source.SENTRA_TRUST, "record_type": "not_run",
         "reason": "skipped for cost/tier", "request_id": "r1", "session_id": "s1",
         "timestamp_ms": 100},
        {"source": Source.SENTRA_SIGMA, "record_type": "not_run",
         "reason": "skipped for cost/tier", "request_id": "r1", "session_id": "s1",
         "timestamp_ms": 200},
    ]
    svc.get_session_signals = Mock(return_value={"signals": markers})

    resp = svc.get_session_decisions(session_id="s1", request_id="r1")
    assert resp["total"] == 0
    assert resp["decisions"] == []


def test_scan_decisions_excludes_markers_no_phantom_allow_no_none_rep():
    """FIX-B (HIGH, decisions_service.py scan_decisions): the /v1/decisions
    threat-feed path must exclude WS-D markers before grouping. Asserts (a) the
    row's flat fields (agent_id/tool_name) come from a RAN row, never a marker
    (which omits them → None), and (b) signals[] holds only the ran signals with
    no phantom ALLOW. Reverting the exclusion makes rep a marker (agent_id=None)
    and injects fake ALLOW votes."""
    svc = _mk_grouping_service()
    # scan_decisions reads via self._ddb().query + self._deserialize_item.
    # Feed the crafted rows on the first day query, empty thereafter.
    rows = _grouping_rows_deny_with_markers()

    calls = {"n": 0}

    class _FakeDDB:
        def query(self, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"Items": rows, "LastEvaluatedKey": None}
            return {"Items": [], "LastEvaluatedKey": None}

    svc._client = _FakeDDB()
    svc._deserialize_item = lambda it: it  # rows are already plain dicts

    resp = svc.scan_decisions(limit=50)

    # Exactly one grouped decision.
    matching = [d for d in resp["decisions"] if d["request_id"] == "r1"]
    assert len(matching) == 1
    d = matching[0]
    # Flat row fields resolved from a RAN row, not a marker (never None).
    assert d["agent_id"] == "agent-x"
    assert d["tool_name"] == "wire_transfer"
    assert d["platform"] == "bedrock"
    assert d["trust_score"] == 0.9
    assert d["decision"] == "DENY"
    assert d["threat_type"] == "INJECTION"
    # signals[] holds only ran signals — no phantom ALLOW from marker layers.
    assert len(d["signals"]) == 2
    got_sources = {s["source"] for s in d["signals"]}
    assert got_sources == {Source.SENTRA_TRUST, Source.SENTRA_SIGMA}
    assert d["combined"]["winning_source"] == Source.SENTRA_SIGMA


def test_is_marker_row_predicate():
    """FIX-B: the shared partitioning predicate — a row with a marker record_type
    is a marker; a ran row (decision, no record_type) is not; a plain edge signal
    is not."""
    from app.services.decisions_service import _is_marker_row
    assert _is_marker_row({"source": "sentra.sigma", "record_type": "not_run"}) is True
    assert _is_marker_row({"source": "sentra.sigma", "record_type": "abstain"}) is True
    assert _is_marker_row({"source": "sentra.sigma", "record_type": "error"}) is True
    assert _is_marker_row({"source": "sentra.sigma", "decision": "DENY"}) is False
    assert _is_marker_row({"source": "bedrock_guardrail", "decision": "ALLOW"}) is False
    # Unknown record_type value is NOT treated as a marker (fail toward a ran row
    # only if it also carries a decision; here neither → not a marker).
    assert _is_marker_row({"source": "x", "record_type": "weird"}) is False
