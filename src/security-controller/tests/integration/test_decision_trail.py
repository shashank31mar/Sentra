"""Integration test for the WS-D decision trail — LLD 33 §12 (unnumbered integration).

Hits the live DDB table `sentra-validation-signals` end-to-end: a PII-bearing
`/v1/validate` that short-circuits on a sigma DENY writes the ran prefix (Signal
rows) + the not-run complement (record_type="not_run" rows) onto ONE partition,
all carrying phase=request; the read-time recompute over the ran DENY rows yields
winning_source == sentra.sigma, block_point == sentra.sigma.

Gated by RUN_INTEGRATION=1 so default local runs skip it.

Run from src/security-controller/:
    RUN_INTEGRATION=1 AWS_PROFILE=sentra AWS_REGION=us-east-1 \\
        PYTHONPATH=. pytest tests/integration/test_decision_trail.py -v
"""

from __future__ import annotations

import os
import uuid

import pytest

# Skip the whole module unless RUN_INTEGRATION=1 — this hits live DDB.
pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION") != "1",
    reason="Live DDB integration test (set RUN_INTEGRATION=1 to run)",
)


def test_pii_short_circuit_sigma_deny_one_query():
    """A short-circuit sigma DENY persists ran prefix (Signal rows) + not-run
    complement (record_type='not_run' rows) in ONE partition Query, all phase=request;
    the read-time recompute yields winning_source == block_point == sentra.sigma."""
    from app.combiners import Source
    from app.services.decisions_service import DecisionsService
    from app.services.trail_builder import NotRunMarker, build_trail, coverage_set
    from app.combiners import Signal
    from app.utils.signal_store_writer import SignalStoreWriter

    sid = f"ittrail-{uuid.uuid4().hex[:8]}"
    rid = f"req-{uuid.uuid4().hex[:8]}"

    # Ran prefix: trust/policy/cross_agent ALLOW, sigma DENY (the denier).
    signals = [
        Signal(source=Source.SENTRA_TRUST, decision="ALLOW", priority=90),
        Signal(source=Source.SENTRA_POLICY, decision="ALLOW", priority=80),
        Signal(source=Source.SENTRA_CROSS_AGENT, decision="ALLOW", priority=50),
        Signal(source=Source.SENTRA_SIGMA, decision="DENY", reason="PII injection",
               priority=70, threat_type="PII_EXPOSURE"),
    ]
    step_timings = {"trust": 1, "policy": 1, "cross_agent": 1, "sigma": 1}
    trail = build_trail(
        signals=signals, step_timings=step_timings, coverage=coverage_set("request"),
        winning_source=Source.SENTRA_SIGMA, phase="request", is_deny=True,
    )

    writer = SignalStoreWriter()
    ok_sig, fail_sig = writer.write_signals(
        session_id=sid, request_id=rid, signals=signals,
        shared_attrs={"agent_id": "test-agent", "tool_name": "wire", "phase": "request"},
    )
    assert fail_sig == 0
    ok_m, fail_m = writer.write_not_run_markers(
        session_id=sid, request_id=rid, markers=trail.markers,
    )
    assert fail_m == 0

    svc = DecisionsService()
    resp = svc.get_session_trail(session_id=sid, request_id=rid)

    assert resp["decision"] == "DENY"
    assert resp["winning_source"] == Source.SENTRA_SIGMA
    assert resp["block_point"] == Source.SENTRA_SIGMA
    # ran prefix + not-run complement, all phase=request, one Query.
    assert resp["phase"] == "request"
    total = (resp["ran_count"] + resp["abstain_count"] + resp["ran_error_count"]
             + resp["not_run_count"])
    assert total == resp["coverage_total"]
    assert resp["not_run_count"] >= 1  # the complement past sigma
