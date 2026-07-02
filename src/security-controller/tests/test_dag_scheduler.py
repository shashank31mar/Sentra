"""WS-C — Cost-annotated DAG scheduler tests (FR-2.8 / ADR-030 / LLD 31 §15).

NO-FLAG cutover: the DAG is the ONLY pipeline. There is no `dag_scheduler_enabled`
flag, no retained sequential body, and no shadow-mode toggle — the ML classifier
ALWAYS ENFORCES when it runs. Equivalence is proven against a FROZEN GOLDEN
BASELINE captured with ML ENFORCING (T-EQUIV): `run_dag(fail_fast)` must reproduce
the baseline `(decision, should_deny, winning_source)` tuple — NOT full signals[]
equality (a cheap-DENY legitimately drops the ML signal; LLD 24 §9:227). The one
deliberate verdict change (ML DENY now blocks) is pinned SEPARATELY as
T-ML-ENFORCE.

Test IDs map to LLD 31 §15:
  T-EQUIV        — run_dag(fail_fast) reproduces the frozen golden baseline on
                   (decision, should_deny, winning_source), incl. the two-
                   simultaneous-tier-0-DENY step-order case.
  T-ML-ENFORCE   — the one deliberate change: a live ML DENY now DECIDES the
                   verdict (winning_source=sentra.ml_classifier), where the old
                   shadow path let it fall through to ALLOW.
  T-DAG-01       — a tier-0 DENY short-circuits BEFORE the ML node is awaited.
  T-DAG-02       — evaluate_all runs the whole frontier; verdict tuple identical
                   to fail_fast; tier-1-only live DENY still decides.
  T-MULTI-DENY   — tier-1 multi-DENY uses the ONE shared ranking helper.
  T-COMBINER-CLEAN — DEFAULT_PRIORITIES + the rank tuple/tie-break unchanged.
  T-ISOLATE      — a tier-1 exception is isolated (peers not cancelled) then
                   re-raised fail-secure (5xx→DENY at the edge); a tier-1
                   returned-abstain falls to the floor; a tier-0 raise fails secure.
  T-CHAIN        — a WS-C fixture chain runs sequentially; upstream abstain fails
                   the downstream node to the floor.
  T-CTX-ISO      — chain ctx / session isolation across the gather.
  T-PARALLEL     — independent tier-1 nodes gather (max, not sum).
  T-TOPO         — _toposort order + cycle detection (pure unit).
  T-PHASE        — per-phase node selection degrades to the request floor.
  T-POLICY-NODE  — the sentra.policy Cedar cutover/shadow/fail-secure selection
                   through the DAG.
  T-STAMP        — cross-cloud field propagation through the DAG.
"""

import asyncio

import pytest
from unittest.mock import AsyncMock, Mock, patch

from app.api.models import ValidationRequest, ValidationResult
from app.combiners import DenyOverrides, Source, pick_top_denier
from app.services.scheduler.node import CostTier, ValidatorNode
from app.services.scheduler.run import (
    EVALUATE_ALL,
    FAIL_FAST,
    _is_hard_deny,
    _toposort,
    run_dag,
)


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture
def mock_session():
    return {
        "session_id": "sess-dag",
        "user_id": "user-1",
        "agent_id": "test-agent",
        "trust_score": 80.0,
        "action_count": 3,
    }


@pytest.fixture
def sample_request():
    return ValidationRequest(
        request_id="req-dag",
        session_id="sess-dag",
        agent_id="test-agent",
        tool_name="get_user_info",
        tool_params={"user_id": "1"},
        user_input="Get user info",
        timestamp="2026-07-01T10:00:00Z",
        operation_type="READ",
    )


def _allow(source: str) -> ValidationResult:
    r = ValidationResult(decision="ALLOW", reason="OK", should_deny=False)
    r.source = source
    return r


def _deny(source: str, threat_type: str = "THREAT") -> ValidationResult:
    r = ValidationResult(
        decision="DENY",
        reason=f"{source} denied",
        should_deny=True,
        violation_type=threat_type,
        threat_type=threat_type,
    )
    r.source = source
    return r


def _allow_with_cloud(source: str, platform: str, cloud_region: str) -> ValidationResult:
    """An ALLOW result that natively carries the agent-sourced cross-cloud fields
    — models the policy engine stamping platform/cloud_region from the AGENT
    record (agent-policy-management §2.3/C2)."""
    r = _allow(source)
    r.platform = platform
    r.cloud_region = cloud_region
    return r


def _cloud_fields(result: ValidationResult):
    return (result.platform, result.cloud_region)


def _pipeline_service(mock_session):
    """A ValidationService with every validator mocked to ALLOW. Cedar engine
    is absent (getattr → None) so _run_policy_step takes the legacy branch."""
    from app.services.validation_service import ValidationService

    with patch.object(ValidationService, "__init__", lambda self: None):
        service = ValidationService()

    service.cedar_engine = None
    service.session_manager = Mock()
    service.session_manager.get_or_create_session = AsyncMock(return_value=mock_session)

    service.trust_checker = Mock()
    service.trust_checker.check = AsyncMock(return_value=_allow(Source.SENTRA_TRUST))

    service.policy_engine = Mock()
    service.policy_engine.validate = AsyncMock(return_value=_allow(Source.SENTRA_POLICY))
    service.policy_engine.get_agent_policy = AsyncMock(return_value={"rate_limit": 100})
    service.policy_engine.get_agent_cloud_identity = Mock(return_value=(None, None))

    service.cross_agent_validator = Mock()
    service.cross_agent_validator.validate = AsyncMock(return_value=_allow(Source.SENTRA_CROSS_AGENT))

    service.sigma_engine = Mock()
    service.sigma_engine.match_rules = AsyncMock(return_value=_allow(Source.SENTRA_SIGMA))

    # Default: ML classifier abstains (disabled). Tests that need an ML verdict
    # override .validate; the registry wrapper stamps enforce=True on any concrete
    # verdict (NO-FLAG: ML always enforces).
    service.ml_classifier = Mock()
    service.ml_classifier.validate = AsyncMock(
        return_value=ValidationResult.abstain("ml_classifier disabled")
    )

    service.context_validator = Mock()
    service.context_validator.validate_sequence = AsyncMock(return_value=_allow(Source.SENTRA_CONTEXT))

    service.abuse_detector = Mock()
    service.abuse_detector.check_rate_limit = AsyncMock(return_value=_allow(Source.SENTRA_ABUSE))

    return service


def _winning_source(signals):
    """The downstream combiner's winning_source over the run's signals — the
    exact computation decisions/audit does today."""
    if not signals:
        return None
    combined = DenyOverrides().combine(signals)
    return combined.metadata.get("winning_source")


def _verdict_tuple(result, signals):
    return (result.decision, result.should_deny, _winning_source(signals))


# --------------------------------------------------------------------------- #
# T-TOPO — pure unit: topological order + cycle detection
# --------------------------------------------------------------------------- #
def test_t_topo_order_matches_legacy_step_order():
    """tier-0 toposort yields trust -> policy -> {cross_agent, sigma, context,
    abuse} with the post-policy nodes in legacy STEP order (order_key), NOT
    alphabetical."""
    async def _noop(req, sess):
        return _allow("x")

    nodes = [
        ValidatorNode(Source.SENTRA_ABUSE, CostTier.DETERMINISTIC, _noop, (Source.SENTRA_POLICY,), order_key=6),
        ValidatorNode(Source.SENTRA_TRUST, CostTier.DETERMINISTIC, _noop, (), order_key=1),
        ValidatorNode(Source.SENTRA_CROSS_AGENT, CostTier.DETERMINISTIC, _noop, (Source.SENTRA_POLICY,), order_key=3),
        ValidatorNode(Source.SENTRA_POLICY, CostTier.DETERMINISTIC, _noop, (Source.SENTRA_TRUST,), order_key=2),
        ValidatorNode(Source.SENTRA_SIGMA, CostTier.DETERMINISTIC, _noop, (Source.SENTRA_POLICY,), order_key=4),
        ValidatorNode(Source.SENTRA_CONTEXT, CostTier.DETERMINISTIC, _noop, (Source.SENTRA_POLICY,), order_key=5),
    ]
    order = [n.source for n in _toposort(nodes)]
    assert order == [
        Source.SENTRA_TRUST,
        Source.SENTRA_POLICY,
        Source.SENTRA_CROSS_AGENT,
        Source.SENTRA_SIGMA,
        Source.SENTRA_CONTEXT,
        Source.SENTRA_ABUSE,
    ]


def test_t_topo_cycle_raises():
    async def _noop(req, sess):
        return _allow("x")

    a = ValidatorNode("sentra.trust", CostTier.DETERMINISTIC, _noop, ("sentra.policy",))
    b = ValidatorNode("sentra.policy", CostTier.DETERMINISTIC, _noop, ("sentra.trust",))
    with pytest.raises(ValueError, match="cycle"):
        _toposort([a, b])


# --------------------------------------------------------------------------- #
# T-PHASE — build_dag per-phase node selection degrades to the request floor.
# --------------------------------------------------------------------------- #
def _request_node_sources():
    return {
        Source.SENTRA_TRUST,
        Source.SENTRA_POLICY,
        Source.SENTRA_CROSS_AGENT,
        Source.SENTRA_SIGMA,
        Source.SENTRA_CONTEXT,
        Source.SENTRA_ABUSE,
        Source.SENTRA_ML_CLASSIFIER,
    }


def test_t_phase_degrade_unknown_phase_falls_back_to_request_floor(mock_session):
    """An unknown/absent phase degrades to the FULL request node set (the
    deterministic floor still runs), never an empty graph — the deny-by-default
    posture (LLD 31 §5.4).

    WS-E2 update (LLD 29 §4.1): the KNOWN content-bearing phases (content/output/
    memory) now ALSO carry the Tier-2 NER redaction barrier entry node ON TOP of
    the request floor — a deliberate additive change (the F1 barrier). A genuinely
    UNKNOWN phase (`totally-unknown`) still degrades to EXACTLY the request floor
    (no barrier). Both cases still run the full deterministic floor — the deny-by-
    default posture is unchanged; only the content phases gained the extra barrier."""
    from app.services.scheduler import build_dag
    from app.combiners import Source

    service = _pipeline_service(mock_session)
    stamp_ctx = {"platform": None, "cloud_region": None}

    request_nodes = build_dag(service, "request", stamp_ctx)

    # Content-bearing phases: the request floor PLUS the WS-E2 NER barrier.
    for phase in ("content", "output", "memory"):
        degraded = build_dag(service, phase, dict(stamp_ctx))
        assert degraded, f"phase {phase!r} degraded to an EMPTY graph — a fail-OPEN"
        sources = {n.source for n in degraded}
        assert Source.REDACTION_NER in sources, f"phase {phase!r} missing the NER barrier"
        # The full request floor still runs (never fewer checks than request).
        assert _request_node_sources() <= sources
        assert sources == _request_node_sources() | {Source.REDACTION_NER}

    # An UNKNOWN phase degrades to EXACTLY the request floor — no barrier added.
    degraded = build_dag(service, "totally-unknown", dict(stamp_ctx))
    assert degraded, "unknown phase degraded to an EMPTY graph — a fail-OPEN"
    assert {n.source for n in degraded} == _request_node_sources()
    assert {n.source for n in degraded} == {n.source for n in request_nodes}


def test_t_phase_degrade_request_phase_builds_full_floor(mock_session):
    """Sanity: the request phase builds the seven-node floor with the correct
    tier split (six tier-0 + the ml tier-1)."""
    from app.services.scheduler import build_dag

    service = _pipeline_service(mock_session)
    nodes = build_dag(service, "request", {"platform": None, "cloud_region": None})
    assert {n.source for n in nodes} == _request_node_sources()
    tier0 = {n.source for n in nodes if n.cost_tier == CostTier.DETERMINISTIC}
    tier1 = {n.source for n in nodes if n.cost_tier == CostTier.EXPENSIVE_MODEL}
    assert Source.SENTRA_ML_CLASSIFIER in tier1
    assert Source.SENTRA_ML_CLASSIFIER not in tier0
    assert len(tier0) == 6


# --------------------------------------------------------------------------- #
# pick_top_denier — shared ranking helper (additive; ranking unchanged)
# --------------------------------------------------------------------------- #
def test_pick_top_denier_matches_combine_winner():
    """The shared helper picks the same source combine() names as winning_source."""
    signals = [
        _deny(Source.SENTRA_ABUSE).to_signal(),         # priority 50
        _deny(Source.SENTRA_CROSS_AGENT).to_signal(),   # priority 50
        _allow(Source.SENTRA_TRUST).to_signal(),        # ALLOW, not a denier
    ]
    top = pick_top_denier(signals)
    combined = DenyOverrides().combine(signals)
    # equal priority + equal (None->0.0) confidence -> alphabetically-smaller
    # source wins: 'sentra.abuse' < 'sentra.cross_agent'
    assert top.source == Source.SENTRA_ABUSE
    assert top.source == combined.metadata["winning_source"]


def test_pick_top_denier_none_when_no_deny():
    signals = [_allow(Source.SENTRA_TRUST).to_signal(), _allow(Source.SENTRA_POLICY).to_signal()]
    assert pick_top_denier(signals) is None


# --------------------------------------------------------------------------- #
# T-COMBINER-CLEAN — priorities + rank tuple UNCHANGED (byte-for-byte).
# --------------------------------------------------------------------------- #
def test_t_combiner_clean_priorities_unchanged():
    from app.combiners import DEFAULT_PRIORITIES, default_priority

    # The VOTING priorities (every source that can decide a verdict) are byte-for-
    # byte unchanged — the deny-overrides ranking is untouched.
    voting = {k: v for k, v in DEFAULT_PRIORITIES.items() if k != Source.REDACTION_NER}
    assert voting == {
        Source.SENTRA_TRUST: 90,
        Source.SENTRA_POLICY: 80,
        Source.SENTRA_SIGMA: 70,
        Source.SENTRA_ML_CLASSIFIER: 65,
        Source.SENTRA_CONTEXT: 60,
        Source.SENTRA_ABUSE: 50,
        Source.SENTRA_CROSS_AGENT: 50,
        Source.BEDROCK_GUARDRAIL: 40,
        Source.AZURE_CONTENT_FILTER: 40,
    }
    # WS-E2 (LLD 29 §4.1 FOOTGUN 2): the NER barrier source is REGISTERED so the
    # WS-D trail can join on it, but at priority 0 — it NEVER votes on a verdict
    # (the node returns ALLOW/ABSTAIN, never a DENY), so the ranking above is
    # unaffected. A priority > 0 here would be the regression to catch.
    assert default_priority(Source.REDACTION_NER) == 0


def test_t_combiner_clean_rank_tuple_order_unchanged():
    """The rank tuple is (priority, confidence or 0.0, _neg_source(source)) —
    a None confidence coalesces to 0.0 and the alphabetically-smaller source
    wins the tie. Pins the ordering algebra the DAG relies on."""
    hi = _deny(Source.SENTRA_ABUSE)
    hi.confidence = 0.9
    lo = _deny(Source.SENTRA_ABUSE)  # confidence None -> 0.0
    combined = DenyOverrides().combine([lo.to_signal(), hi.to_signal()])
    assert combined.confidence == 0.9
    tie = DenyOverrides().combine([
        _deny(Source.SENTRA_CROSS_AGENT).to_signal(),
        _deny(Source.SENTRA_ABUSE).to_signal(),
    ])
    assert tie.metadata["winning_source"] == Source.SENTRA_ABUSE


# --------------------------------------------------------------------------- #
# T-EQUIV — run_dag(fail_fast) reproduces the FROZEN GOLDEN BASELINE.
#
# The baseline was captured with ML ENFORCING (NO-FLAG). Each case asserts the
# DAG's (decision, should_deny, winning_source) tuple against the hard-coded
# golden value — NOT full signals[] equality (a cheap-DENY legitimately drops the
# ML signal; LLD 24 §9:227). A divergence from the golden tuple fails the build.
# --------------------------------------------------------------------------- #
async def _run_ff(service, request, session, monkeypatch):
    """Run the request through the DAG in fail_fast (the production default)."""
    from app.config import settings as _settings

    monkeypatch.setattr(_settings, "dag_run_mode", FAIL_FAST)
    return await service._run_validation_pipeline(request, session)


@pytest.mark.asyncio
async def test_t_equiv_all_allow(mock_session, sample_request, monkeypatch):
    """GOLDEN: tier-0 all-ALLOW + ML ALLOW → ALLOW, winning_source=None."""
    service = _pipeline_service(mock_session)
    ml_allow = _allow(Source.SENTRA_ML_CLASSIFIER)
    ml_allow.confidence = 0.95
    service.ml_classifier.validate = AsyncMock(return_value=ml_allow)

    result, signals = await _run_ff(service, sample_request, mock_session, monkeypatch)
    assert _verdict_tuple(result, signals) == ("ALLOW", False, None)


@pytest.mark.asyncio
async def test_t_equiv_trust_deny(mock_session, sample_request, monkeypatch):
    """GOLDEN: trust DENY → DENY, winning_source=sentra.trust; ML never runs."""
    service = _pipeline_service(mock_session)
    service.trust_checker.check = AsyncMock(return_value=_deny(Source.SENTRA_TRUST, "QUARANTINE"))

    result, signals = await _run_ff(service, sample_request, mock_session, monkeypatch)
    assert _verdict_tuple(result, signals) == ("DENY", True, Source.SENTRA_TRUST)
    assert result.source == Source.SENTRA_TRUST
    service.ml_classifier.validate.assert_not_called()


@pytest.mark.asyncio
async def test_t_equiv_policy_deny(mock_session, sample_request, monkeypatch):
    """GOLDEN: policy DENY → DENY, winning_source=sentra.policy; ML never runs."""
    service = _pipeline_service(mock_session)
    service.policy_engine.validate = AsyncMock(return_value=_deny(Source.SENTRA_POLICY, "TOOL_NOT_ALLOWED"))

    result, signals = await _run_ff(service, sample_request, mock_session, monkeypatch)
    assert _verdict_tuple(result, signals) == ("DENY", True, Source.SENTRA_POLICY)
    service.ml_classifier.validate.assert_not_called()


@pytest.mark.asyncio
async def test_t_equiv_sigma_deny_ml_never_runs(mock_session, sample_request, monkeypatch):
    """GOLDEN: sigma DENY → DENY, winning_source=sentra.sigma; the ~600ms ML call
    is skipped (tier-0 short-circuit before any model)."""
    service = _pipeline_service(mock_session)
    service.sigma_engine.match_rules = AsyncMock(return_value=_deny(Source.SENTRA_SIGMA, "PII_EXPOSURE"))

    result, signals = await _run_ff(service, sample_request, mock_session, monkeypatch)
    assert _verdict_tuple(result, signals) == ("DENY", True, Source.SENTRA_SIGMA)
    service.ml_classifier.validate.assert_not_called()
    assert Source.SENTRA_ML_CLASSIFIER not in [s.source for s in signals]


@pytest.mark.asyncio
async def test_t_equiv_abuse_deny(mock_session, sample_request, monkeypatch):
    """GOLDEN: the last tier-0 node (abuse) DENYs → DENY, winning_source=abuse;
    ML still never runs (abuse short-circuits before tier-1)."""
    service = _pipeline_service(mock_session)
    service.abuse_detector.check_rate_limit = AsyncMock(return_value=_deny(Source.SENTRA_ABUSE, "RATE_LIMIT"))

    result, signals = await _run_ff(service, sample_request, mock_session, monkeypatch)
    assert _verdict_tuple(result, signals) == ("DENY", True, Source.SENTRA_ABUSE)
    service.ml_classifier.validate.assert_not_called()


@pytest.mark.asyncio
async def test_t_equiv_two_simultaneous_tier0_deny_step_order(mock_session, sample_request, monkeypatch):
    """GOLDEN (LLD 31 §15 worked trace): cross_agent + abuse both DENY (priority
    50). In fail_fast the chain short-circuits at cross_agent (STEP 2.5, order_key
    3), so abuse never runs and its signal is absent — the returned-object .source
    AND the winning_source are BOTH cross_agent. The step-order tie-break (NOT
    alphabetical) is what makes the DAG return cross_agent, not abuse, on this tie."""
    service = _pipeline_service(mock_session)
    service.cross_agent_validator.validate = AsyncMock(return_value=_deny(Source.SENTRA_CROSS_AGENT, "CROSS_AGENT"))
    service.abuse_detector.check_rate_limit = AsyncMock(return_value=_deny(Source.SENTRA_ABUSE, "RATE_LIMIT"))

    result, signals = await _run_ff(service, sample_request, mock_session, monkeypatch)
    assert result.source == Source.SENTRA_CROSS_AGENT
    assert _verdict_tuple(result, signals) == ("DENY", True, Source.SENTRA_CROSS_AGENT)
    # abuse never ran (short-circuit at cross_agent), so it is absent from the trail
    assert Source.SENTRA_ABUSE not in [s.source for s in signals]


def test_combiner_tie_break_abuse_beats_cross_agent_when_both_present():
    """The combiner's alphabetical (_neg_source) tie-break: when BOTH equal-
    priority DENY signals are present (as in evaluate_all), abuse wins because
    'sentra.abuse' < 'sentra.cross_agent' — the §15 worked-trace (b)."""
    combined = DenyOverrides().combine([
        _deny(Source.SENTRA_CROSS_AGENT, "CROSS_AGENT").to_signal(),
        _deny(Source.SENTRA_ABUSE, "RATE_LIMIT").to_signal(),
    ])
    assert combined.metadata["winning_source"] == Source.SENTRA_ABUSE


# --------------------------------------------------------------------------- #
# T-ML-ENFORCE — the ONE deliberate verdict change (NO-FLAG (3) / (4)).
#
# ML no longer has a shadow mode: a live ML DENY now DECIDES the verdict. The old
# shadow path (ml_classifier_shadow_mode=true) let an ML DENY fall through to
# ALLOW; that behavior is DELETED. This test pins the new contract — it FAILS if
# the enforce wrapper ever stopped stamping enforce=True (regressing to advisory).
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_t_ml_enforce_live_ml_deny_decides_verdict(mock_session, sample_request, monkeypatch):
    """tier-0 all-ALLOW + a live ML DENY → DENY, winning_source=ml_classifier.
    This is the deliberate change from the removed shadow behavior."""
    service = _pipeline_service(mock_session)
    ml_deny = _deny(Source.SENTRA_ML_CLASSIFIER, "PROMPT_INJECTION")
    ml_deny.confidence = 0.99
    service.ml_classifier.validate = AsyncMock(return_value=ml_deny)

    result, signals = await _run_ff(service, sample_request, mock_session, monkeypatch)
    assert _verdict_tuple(result, signals) == ("DENY", True, Source.SENTRA_ML_CLASSIFIER)
    assert result.source == Source.SENTRA_ML_CLASSIFIER
    # the wrapper stamped enforce=True → _is_hard_deny lets it decide
    assert result.metadata.get("enforce") is True


@pytest.mark.asyncio
async def test_t_ml_enforce_ml_allow_stays_allow(mock_session, sample_request, monkeypatch):
    """An ML ALLOW does not spuriously block — enforce=True is harmless on ALLOW."""
    service = _pipeline_service(mock_session)
    ml_allow = _allow(Source.SENTRA_ML_CLASSIFIER)
    ml_allow.confidence = 0.9
    service.ml_classifier.validate = AsyncMock(return_value=ml_allow)

    result, signals = await _run_ff(service, sample_request, mock_session, monkeypatch)
    assert _verdict_tuple(result, signals) == ("ALLOW", False, None)


@pytest.mark.asyncio
async def test_t_ml_enforce_abstain_emits_no_signal_and_allows(mock_session, sample_request, monkeypatch):
    """A disabled/abstaining ML classifier emits NO signal and the deterministic
    floor decides ALLOW (RES-4 — matches the disabled-classifier production path).
    The enforce wrapper must NOT stamp an abstain into a signal."""
    service = _pipeline_service(mock_session)
    # default mock already abstains ("ml_classifier disabled")
    result, signals = await _run_ff(service, sample_request, mock_session, monkeypatch)
    assert _verdict_tuple(result, signals) == ("ALLOW", False, None)
    assert Source.SENTRA_ML_CLASSIFIER not in [s.source for s in signals]


def test_t_ml_enforce_wrapper_stamps_enforce_true():
    """Unit: the registry ML wrapper stamps enforce=True on a concrete verdict and
    leaves an abstain untouched (no signal)."""
    from app.services.scheduler.registry import _apply_ml_enforce_wrapper

    deny = _deny(Source.SENTRA_ML_CLASSIFIER, "PROMPT_INJECTION")
    wrapped = _apply_ml_enforce_wrapper(deny)
    assert wrapped.metadata.get("enforce") is True
    assert _is_hard_deny(wrapped) is True
    # the classifier's returned object is not mutated in place
    assert deny.metadata is None or deny.metadata.get("enforce") is None

    abstain = ValidationResult.abstain("ml_classifier disabled")
    assert _apply_ml_enforce_wrapper(abstain) is abstain


# --------------------------------------------------------------------------- #
# T-POLICY-NODE — the sentra.policy node's Cedar cutover/shadow/fail-secure
# selection, exercised THROUGH the DAG scheduler with a REAL (mocked) cedar_engine.
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_t_policy_node_cedar_cutover_deny_through_dag(mock_session, sample_request, monkeypatch):
    """cedar_enabled & NOT shadow → Cedar IS the decision. A Cedar DENY flows
    through the DAG's sentra.policy node, short-circuits tier-0, ML never awaited."""
    from app.config import settings as _settings

    monkeypatch.setattr(_settings, "cedar_enabled", True)
    monkeypatch.setattr(_settings, "cedar_shadow_mode", False)
    service = _pipeline_service(mock_session)
    service.cedar_engine = Mock()
    service.cedar_engine.validate = AsyncMock(
        return_value=_deny(Source.SENTRA_POLICY, "TOOL_NOT_ALLOWED")
    )

    result, signals = await service._run_validation_pipeline(sample_request, mock_session)

    assert result.should_deny
    assert result.source == Source.SENTRA_POLICY
    service.cedar_engine.validate.assert_awaited_once()
    service.policy_engine.validate.assert_not_called()
    service.ml_classifier.validate.assert_not_called()
    assert _winning_source(signals) == Source.SENTRA_POLICY


@pytest.mark.asyncio
async def test_t_policy_node_cedar_abstain_legacy_retired_fail_secure_deny_through_dag(
    mock_session, sample_request, monkeypatch
):
    """cutover + Cedar abstain + legacy_retired → fail-secure POLICY_NOT_MIGRATED
    DENY on the DAG path (FR-2.4 / LLD 28 §4.3)."""
    from app.config import settings as _settings

    monkeypatch.setattr(_settings, "cedar_enabled", True)
    monkeypatch.setattr(_settings, "cedar_shadow_mode", False)
    monkeypatch.setattr(_settings, "legacy_retired", True)
    service = _pipeline_service(mock_session)
    service.metrics_publisher = Mock()
    service.metrics_publisher.publish_cedar_abstain_metric = AsyncMock()
    service.cedar_engine = Mock()
    service.cedar_engine.validate = AsyncMock(
        return_value=ValidationResult.abstain("agent not Cedar-migrated")
    )

    result, signals = await service._run_validation_pipeline(sample_request, mock_session)

    assert result.should_deny
    assert result.violation_type == "POLICY_NOT_MIGRATED"
    service.policy_engine.validate.assert_not_called()
    service.ml_classifier.validate.assert_not_called()


@pytest.mark.asyncio
async def test_t_policy_node_cedar_abstain_rollout_falls_back_to_legacy_through_dag(
    mock_session, sample_request, monkeypatch
):
    """cutover + Cedar abstain + legacy_retired=False → permissive fallback to the
    legacy engine on the DAG path (no un-enforced window during CT08 backfill)."""
    from app.config import settings as _settings

    monkeypatch.setattr(_settings, "cedar_enabled", True)
    monkeypatch.setattr(_settings, "cedar_shadow_mode", False)
    monkeypatch.setattr(_settings, "legacy_retired", False)
    service = _pipeline_service(mock_session)
    service.metrics_publisher = Mock()
    service.metrics_publisher.publish_cedar_abstain_metric = AsyncMock()
    service.cedar_engine = Mock()
    service.cedar_engine.validate = AsyncMock(
        return_value=ValidationResult.abstain("agent not Cedar-migrated")
    )
    service.policy_engine.validate = AsyncMock(return_value=_allow(Source.SENTRA_POLICY))

    result, _ = await service._run_validation_pipeline(sample_request, mock_session)

    service.cedar_engine.validate.assert_awaited_once()
    service.policy_engine.validate.assert_awaited_once()
    assert result.decision == "ALLOW"


@pytest.mark.asyncio
async def test_t_policy_node_cedar_shadow_compare_runs_on_dag_path(mock_session, sample_request, monkeypatch):
    """cedar_enabled & shadow → legacy decides; Cedar runs alongside via
    _cedar_shadow_compare, records disagreement, does NOT influence the verdict."""
    from app.config import settings as _settings

    monkeypatch.setattr(_settings, "cedar_enabled", True)
    monkeypatch.setattr(_settings, "cedar_shadow_mode", True)
    service = _pipeline_service(mock_session)
    service.cedar_engine = Mock()
    service._cedar_shadow_compare = AsyncMock()
    service.policy_engine.validate = AsyncMock(return_value=_deny(Source.SENTRA_POLICY, "TOOL_NOT_ALLOWED"))

    result, _ = await service._run_validation_pipeline(sample_request, mock_session)

    assert result.should_deny
    assert result.source == Source.SENTRA_POLICY
    service._cedar_shadow_compare.assert_awaited_once()
    service.ml_classifier.validate.assert_not_called()


# --------------------------------------------------------------------------- #
# T-STAMP — cross-cloud field propagation through the DAG (WS-15 preserved).
# The sentra.policy node writes platform/cloud_region into stamp_ctx; the DAG's
# _stamp closure attaches them to downstream results that don't carry them.
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_t_stamp_downstream_tier0_deny_carries_policy_cloud_fields(
    mock_session, sample_request, monkeypatch
):
    """policy ALLOWs carrying platform=azure/cloud_region=eastus; a downstream
    tier-0 DENY (sigma) with NO native cloud fields must be stamped azure/eastus."""
    service = _pipeline_service(mock_session)
    service.policy_engine.validate = AsyncMock(
        return_value=_allow_with_cloud(Source.SENTRA_POLICY, "azure", "eastus")
    )
    service.sigma_engine.match_rules = AsyncMock(
        return_value=_deny(Source.SENTRA_SIGMA, "PII_EXPOSURE")
    )

    result, _ = await service._run_validation_pipeline(sample_request, mock_session)

    assert result.should_deny
    assert result.source == Source.SENTRA_SIGMA
    assert _cloud_fields(result) == ("azure", "eastus")


@pytest.mark.asyncio
async def test_t_stamp_all_allow_carries_policy_cloud_fields(
    mock_session, sample_request, monkeypatch
):
    """All-ALLOW: the synthetic ALLOW at the DAG tail carries the policy-sourced
    platform/cloud_region."""
    service = _pipeline_service(mock_session)
    service.policy_engine.validate = AsyncMock(
        return_value=_allow_with_cloud(Source.SENTRA_POLICY, "bedrock", "us-east-1")
    )

    result, _ = await service._run_validation_pipeline(sample_request, mock_session)

    assert result.decision == "ALLOW"
    assert _cloud_fields(result) == ("bedrock", "us-east-1")


@pytest.mark.asyncio
async def test_t_stamp_trust_deny_resolves_cloud_identity(mock_session, sample_request, monkeypatch):
    """A trust DENY runs before the policy node populates stamp_ctx — the trust
    node resolves cloud identity from the agent registry (pre-DAG WS-15 behavior
    preserved). If the trust node dropped this, the DENY would carry (None, None)."""
    service = _pipeline_service(mock_session)
    service.trust_checker.check = AsyncMock(return_value=_deny(Source.SENTRA_TRUST, "QUARANTINE"))
    service.policy_engine.get_agent_cloud_identity = Mock(return_value=("gcp", "us-central1"))

    result, _ = await service._run_validation_pipeline(sample_request, mock_session)

    assert result.should_deny
    assert result.source == Source.SENTRA_TRUST
    assert _cloud_fields(result) == ("gcp", "us-central1")


# --------------------------------------------------------------------------- #
# T-PHASE-SEAM — request.phase -> build_dag wiring, exercised end-to-end.
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_t_phase_seam_request_phase_forwarded_to_build_dag(
    mock_session, sample_request, monkeypatch
):
    """A request with an explicit WS-A `phase` value has that exact value handed
    to build_dag by _run_validation_pipeline (the request.phase -> build_dag seam)."""
    import app.services.scheduler as scheduler_pkg

    service = _pipeline_service(mock_session)
    content_request = sample_request.model_copy(update={"phase": "content"})

    seen_phase = {}
    real_build_dag = scheduler_pkg.build_dag

    def _spy_build_dag(svc, phase, stamp_ctx):
        seen_phase["phase"] = phase
        return real_build_dag(svc, phase, stamp_ctx)

    monkeypatch.setattr(scheduler_pkg, "build_dag", _spy_build_dag)

    await service._run_validation_pipeline(content_request, mock_session)

    assert seen_phase["phase"] == "content"


@pytest.mark.asyncio
async def test_t_phase_seam_content_phase_degrades_to_request_floor_end_to_end(
    mock_session, sample_request, monkeypatch
):
    """A content-phase request flows through the full pipeline and (WS-C owning
    only the request phase today) degrades to the request floor: tier-0 nodes run
    and a verdict is produced (deny-by-default, never 'no checks')."""
    service = _pipeline_service(mock_session)
    content_request = sample_request.model_copy(update={"phase": "content"})

    result, signals = await service._run_validation_pipeline(content_request, mock_session)

    assert result.decision in ("ALLOW", "DENY")
    service.trust_checker.check.assert_called()
    service.policy_engine.validate.assert_called()
    assert Source.SENTRA_TRUST in [s.source for s in signals]


@pytest.mark.asyncio
async def test_t_phase_seam_content_phase_tier0_deny_still_short_circuits(
    mock_session, sample_request, monkeypatch
):
    """The phase seam does not weaken enforcement: a content-phase request whose
    tier-0 policy node DENYs still short-circuits before the ML model."""
    service = _pipeline_service(mock_session)
    service.policy_engine.validate = AsyncMock(
        return_value=_deny(Source.SENTRA_POLICY, "TOOL_NOT_ALLOWED")
    )
    content_request = sample_request.model_copy(update={"phase": "content"})

    result, _ = await service._run_validation_pipeline(content_request, mock_session)

    assert result.should_deny
    assert result.source == Source.SENTRA_POLICY
    service.ml_classifier.validate.assert_not_called()


# --------------------------------------------------------------------------- #
# T-DAG-01 — tier-0 DENY skips the model
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_t_dag_01_tier0_deny_skips_ml(mock_session, sample_request, monkeypatch):
    service = _pipeline_service(mock_session)
    service.policy_engine.validate = AsyncMock(return_value=_deny(Source.SENTRA_POLICY, "TOOL_NOT_ALLOWED"))

    result, signals = await service._run_validation_pipeline(sample_request, mock_session)

    assert result.should_deny
    service.ml_classifier.validate.assert_not_called()  # no model on cheap-DENY
    assert Source.SENTRA_ML_CLASSIFIER not in [s.source for s in signals]


# --------------------------------------------------------------------------- #
# T-DAG-02 — evaluate_all vs fail_fast (verdict-neutral)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_t_dag_02_evaluate_all_runs_whole_frontier(mock_session, sample_request, monkeypatch):
    from app.config import settings as _settings

    monkeypatch.setattr(_settings, "dag_run_mode", "evaluate_all")
    service = _pipeline_service(mock_session)
    service.policy_engine.validate = AsyncMock(return_value=_deny(Source.SENTRA_POLICY, "TOOL_NOT_ALLOWED"))

    result, signals = await service._run_validation_pipeline(sample_request, mock_session)

    assert result.should_deny  # verdict unchanged vs fail_fast
    sources = [s.source for s in signals]
    assert Source.SENTRA_CROSS_AGENT in sources
    assert Source.SENTRA_SIGMA in sources
    assert Source.SENTRA_ABUSE in sources
    service.abuse_detector.check_rate_limit.assert_called()


@pytest.mark.asyncio
async def test_t_dag_02_evaluate_all_verdict_neutral_vs_fail_fast(mock_session, sample_request, monkeypatch):
    from app.config import settings as _settings

    service = _pipeline_service(mock_session)
    service.policy_engine.validate = AsyncMock(return_value=_deny(Source.SENTRA_POLICY, "TOOL_NOT_ALLOWED"))

    monkeypatch.setattr(_settings, "dag_run_mode", "fail_fast")
    ff_result, ff_signals = await service._run_validation_pipeline(sample_request, mock_session)
    monkeypatch.setattr(_settings, "dag_run_mode", "evaluate_all")
    ea_result, ea_signals = await service._run_validation_pipeline(sample_request, mock_session)

    assert _verdict_tuple(ff_result, ff_signals) == _verdict_tuple(ea_result, ea_signals)


@pytest.mark.asyncio
async def test_t_dag_02_evaluate_all_verdict_neutral_low_prio_tier0_deny_under_live_ml(
    mock_session, sample_request, monkeypatch
):
    """Verdict-neutrality holds even when the tier-0 denier's priority is BELOW a
    concurrently-denying LIVE tier-1 node (LLD 31 §6.7).

    context (priority 60) DENYs; ML is live-enforce and also DENYs (priority 65).
      * fail_fast: context short-circuits, ML never runs → winning_source=context.
      * evaluate_all: the whole frontier + tier-1 run for the trail; the live ML
        DENY is captured but ADVISORY-for-trail (a tier-0 hard DENY already decided),
        so it can NEVER outrank context. winning_source=context in BOTH modes."""
    from app.config import settings as _settings

    service = _pipeline_service(mock_session)
    service.context_validator.validate_sequence = AsyncMock(
        return_value=_deny(Source.SENTRA_CONTEXT, "SEQUENCE_VIOLATION")
    )
    ml_deny = _deny(Source.SENTRA_ML_CLASSIFIER, "PROMPT_INJECTION")
    ml_deny.confidence = 0.99
    service.ml_classifier.validate = AsyncMock(return_value=ml_deny)

    monkeypatch.setattr(_settings, "dag_run_mode", "fail_fast")
    ff_result, ff_signals = await service._run_validation_pipeline(sample_request, mock_session)
    monkeypatch.setattr(_settings, "dag_run_mode", "evaluate_all")
    ea_result, ea_signals = await service._run_validation_pipeline(sample_request, mock_session)

    assert _verdict_tuple(ff_result, ff_signals) == _verdict_tuple(ea_result, ea_signals)
    assert _winning_source(ff_signals) == Source.SENTRA_CONTEXT
    assert _winning_source(ea_signals) == Source.SENTRA_CONTEXT
    assert ff_result.source == ea_result.source == Source.SENTRA_CONTEXT
    # evaluate_all STILL records the deep tier ran (advisory, non-deciding).
    assert Source.SENTRA_ML_CLASSIFIER in [s.source for s in ea_signals]
    assert Source.SENTRA_ML_CLASSIFIER not in [s.source for s in ff_signals]


@pytest.mark.asyncio
async def test_t_dag_02_evaluate_all_verdict_neutral_two_tier0_deny_higher_prio_later(
    mock_session, sample_request, monkeypatch
):
    """Verdict-neutrality when TWO tier-0 nodes DENY and the HIGHER-priority denier
    is NOT first in topo order (LLD 31 §6.7).

    cross_agent (order_key 3, prio 50) DENYs, and sigma (order_key 4, prio 70)
    DENYs. In BOTH modes the deciding source is the topo-FIRST denier (cross_agent):
    evaluate_all captures every tier-0 DENY after the topo-first as advisory-for-
    trail, so sigma@70 can never outrank cross_agent@50 by run mode."""
    from app.config import settings as _settings

    service = _pipeline_service(mock_session)
    service.cross_agent_validator.validate = AsyncMock(
        return_value=_deny(Source.SENTRA_CROSS_AGENT, "CROSS_AGENT")
    )
    service.sigma_engine.match_rules = AsyncMock(
        return_value=_deny(Source.SENTRA_SIGMA, "PII_EXPOSURE")
    )

    monkeypatch.setattr(_settings, "dag_run_mode", "fail_fast")
    ff_result, ff_signals = await service._run_validation_pipeline(sample_request, mock_session)
    monkeypatch.setattr(_settings, "dag_run_mode", "evaluate_all")
    ea_result, ea_signals = await service._run_validation_pipeline(sample_request, mock_session)

    assert _verdict_tuple(ff_result, ff_signals) == _verdict_tuple(ea_result, ea_signals)
    assert _winning_source(ff_signals) == Source.SENTRA_CROSS_AGENT
    assert _winning_source(ea_signals) == Source.SENTRA_CROSS_AGENT
    assert ea_result.source == _winning_source(ea_signals) == Source.SENTRA_CROSS_AGENT
    assert ff_result.source == Source.SENTRA_CROSS_AGENT
    assert Source.SENTRA_SIGMA in [s.source for s in ea_signals]
    assert Source.SENTRA_SIGMA not in [s.source for s in ff_signals]


@pytest.mark.asyncio
async def test_t_dag_02_evaluate_all_tier1_only_live_deny_decides(mock_session, sample_request, monkeypatch):
    """tier-0 all-ALLOW + a live ml DENY → evaluate_all returns DENY (mode-
    independent hard-DENY capture, LLD 31 §6.1)."""
    from app.config import settings as _settings

    monkeypatch.setattr(_settings, "dag_run_mode", "evaluate_all")
    service = _pipeline_service(mock_session)
    ml_deny = _deny(Source.SENTRA_ML_CLASSIFIER, "PROMPT_INJECTION")
    ml_deny.confidence = 0.99
    service.ml_classifier.validate = AsyncMock(return_value=ml_deny)

    result, signals = await service._run_validation_pipeline(sample_request, mock_session)
    assert result.should_deny
    assert result.source == Source.SENTRA_ML_CLASSIFIER


# --------------------------------------------------------------------------- #
# T-ENFORCE-DEFAULT — a tier-1 DENY with no enforce metadata is advisory.
# --------------------------------------------------------------------------- #
def test_t_forgotten_enforce_flag_is_advisory():
    """Fail-safe default: a tier-1 DENY with no enforce metadata (and
    metadata=None) is advisory / non-deciding (LLD 31 §6.5)."""
    r_none = ValidationResult(decision="DENY", reason="x", should_deny=True, metadata=None)
    r_empty = ValidationResult(decision="DENY", reason="x", should_deny=True, metadata={})
    r_enforce = ValidationResult(decision="DENY", reason="x", should_deny=True, metadata={"enforce": True})
    assert _is_hard_deny(r_none) is False
    assert _is_hard_deny(r_empty) is False
    assert _is_hard_deny(r_enforce) is True


# --------------------------------------------------------------------------- #
# T-MULTI-DENY — tier-1 multi-DENY uses the ONE shared ranking
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_t_multi_deny_scheduler_uses_shared_ranking(mock_session, sample_request):
    """Two live tier-1 DENYs: run_dag's returned-result source == the downstream
    combine() winning_source (scheduler reuses the shared ranking). LLD 31 §6.4."""
    ml_deny = _deny(Source.SENTRA_ML_CLASSIFIER, "PROMPT_INJECTION")
    ml_deny.confidence = 0.9
    ml_deny.metadata = {"enforce": True}
    dnode_deny = _deny(Source.BEDROCK_GUARDRAIL, "OTHER")
    dnode_deny.metadata = {"enforce": True}

    async def _ml(req, sess):
        return ml_deny

    async def _dnode(req, sess):
        return dnode_deny

    nodes = [
        ValidatorNode(Source.SENTRA_ML_CLASSIFIER, CostTier.EXPENSIVE_MODEL, _ml, (), order_key=7),
        ValidatorNode(Source.BEDROCK_GUARDRAIL, CostTier.EXPENSIVE_MODEL, _dnode, (), order_key=8),
    ]
    signals = []

    def capture(r):
        if not r.is_abstain:
            s = r.to_signal()
            if s is not None:
                signals.append(s)
        return r

    def stamp(r):
        return r

    async def timed(label, coro):
        return await coro

    result, sigs = await run_dag(
        nodes, sample_request, mock_session, capture, stamp, timed,
        mode=FAIL_FAST, all_allow=lambda: _allow(Source.SENTRA_COMBINED),
        signals=signals,
    )
    assert result.should_deny
    assert result.source == Source.SENTRA_ML_CLASSIFIER  # 65 > 40
    assert result.source == _winning_source(sigs)


@pytest.mark.asyncio
async def test_t_multi_deny_lower_priority_denier_ordered_first(
    mock_session, sample_request
):
    """Two live tier-1 hard-DENYs where the LOWER-priority denier appears FIRST in
    node order: run_dag's returned source equals the combiner's winning_source
    regardless of node order (order-independence, LLD 31 §6.4)."""
    ml_deny = _deny(Source.SENTRA_ML_CLASSIFIER, "PROMPT_INJECTION")
    ml_deny.confidence = 0.9
    ml_deny.metadata = {"enforce": True}
    dnode_deny = _deny(Source.BEDROCK_GUARDRAIL, "OTHER")
    dnode_deny.metadata = {"enforce": True}

    async def _ml(req, sess):
        return ml_deny

    async def _dnode(req, sess):
        return dnode_deny

    nodes = [
        # reversed declaration order vs the sibling test
        ValidatorNode(Source.BEDROCK_GUARDRAIL, CostTier.EXPENSIVE_MODEL, _dnode, (), order_key=8),
        ValidatorNode(Source.SENTRA_ML_CLASSIFIER, CostTier.EXPENSIVE_MODEL, _ml, (), order_key=7),
    ]
    signals = []

    def capture(r):
        if not r.is_abstain:
            s = r.to_signal()
            if s is not None:
                signals.append(s)
        return r

    def stamp(r):
        return r

    async def timed(label, coro):
        return await coro

    result, sigs = await run_dag(
        nodes, sample_request, mock_session, capture, stamp, timed,
        mode=FAIL_FAST, all_allow=lambda: _allow(Source.SENTRA_COMBINED),
        signals=signals,
    )
    assert result.should_deny
    assert result.source == Source.SENTRA_ML_CLASSIFIER
    assert result.source == _winning_source(sigs)
    assert result.reason == ml_deny.reason


@pytest.mark.asyncio
async def test_top_tier1_denier_matches_combine_winning_source():
    """Unit: `_top_tier1_denier` selects the same source `combine()` names, for
    BOTH input orderings (order-independence)."""
    from app.services.scheduler.run import _top_tier1_denier

    ml = _deny(Source.SENTRA_ML_CLASSIFIER, "PROMPT_INJECTION")
    ml.confidence = 0.9
    ml.metadata = {"enforce": True}
    bg = _deny(Source.BEDROCK_GUARDRAIL, "OTHER")
    bg.metadata = {"enforce": True}

    for ordering in ([ml, bg], [bg, ml]):
        picked = _top_tier1_denier(ordering)
        signals = [r.to_signal() for r in ordering]
        assert picked.source == _winning_source(signals) == Source.SENTRA_ML_CLASSIFIER

    assert _top_tier1_denier([bg]) is bg


# --------------------------------------------------------------------------- #
# T-ISOLATE — tier-1 exception isolation; tier-0 exception fails secure
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_t_isolate_tier1_returned_abstain_falls_to_floor(mock_session, sample_request, monkeypatch):
    """The ML classifier's OWN handled Bedrock-outage path RETURNS an abstain (it
    never raises) → the tier-0 floor decides ALLOW and no ml_classifier signal is
    emitted (RES-4)."""
    service = _pipeline_service(mock_session)
    service.ml_classifier.validate = AsyncMock(
        return_value=ValidationResult.abstain("bedrock outage")
    )

    result, signals = await _run_ff(service, sample_request, mock_session, monkeypatch)
    assert result.decision == "ALLOW"
    assert Source.SENTRA_ML_CLASSIFIER not in [s.source for s in signals]


@pytest.mark.asyncio
async def test_t_isolate_tier1_unexpected_raise_fails_secure_not_open(mock_session, sample_request, monkeypatch):
    """An UNEXPECTED raise from a tier-1 node must FAIL SECURE: it is harvested
    (peers not cancelled) then RE-RAISED so it bubbles to validate_tool_call's
    outer handler → error→DENY (5xx→fail-secure DENY at the edge), NEVER swallowed
    to abstain→floor→ALLOW (Tenet 2: fail secure, not open)."""
    service = _pipeline_service(mock_session)
    service.ml_classifier.validate = AsyncMock(side_effect=RuntimeError("bedrock exploded"))
    with pytest.raises(RuntimeError, match="bedrock exploded"):
        await service._run_validation_pipeline(sample_request, mock_session)


@pytest.mark.asyncio
async def test_t_isolate_tier0_exception_bubbles_fail_secure(mock_session, sample_request, monkeypatch):
    """A tier-0 node raising is NOT swallowed by the scheduler — it bubbles to
    validate_tool_call's outer handler → fail-secure error DENY."""
    service = _pipeline_service(mock_session)
    service.trust_checker.check = AsyncMock(side_effect=RuntimeError("trust store down"))

    with pytest.raises(RuntimeError, match="trust store down"):
        await service._run_validation_pipeline(sample_request, mock_session)


@pytest.mark.asyncio
async def test_t_isolate_tier1_raise_does_not_cancel_peer(mock_session, sample_request):
    """return_exceptions=True: a raise in one gathered tier-1 node does not cancel
    an in-flight peer — the peer completes (its side-effect runs) before the raise
    is re-raised. Guards against a bare gather that cancels peers on first error."""
    peer_completed = {"done": False}

    async def _raiser(req, sess):
        await asyncio.sleep(0.02)
        raise RuntimeError("node A exploded")

    async def _peer(req, sess):
        await asyncio.sleep(0.05)
        peer_completed["done"] = True
        return _allow(Source.BEDROCK_GUARDRAIL)

    nodes = [
        ValidatorNode(Source.SENTRA_ML_CLASSIFIER, CostTier.EXPENSIVE_MODEL, _raiser, (), order_key=7),
        ValidatorNode(Source.BEDROCK_GUARDRAIL, CostTier.EXPENSIVE_MODEL, _peer, (), order_key=8),
    ]

    def capture(r):
        return r

    def stamp(r):
        return r

    async def timed(label, coro):
        return await coro

    with pytest.raises(RuntimeError, match="node A exploded"):
        await run_dag(
            nodes, sample_request, mock_session, capture, stamp, timed,
            mode=FAIL_FAST, all_allow=lambda: _allow(Source.SENTRA_COMBINED),
            signals=[],
        )
    # the peer was NOT cancelled — it ran to completion before the re-raise
    assert peer_completed["done"] is True


# --------------------------------------------------------------------------- #
# T-CHAIN — dependency-chain sequencing + upstream-abstain fails to floor
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_t_chain_runs_sequentially_and_threads_context(mock_session, sample_request):
    """A WS-C fixture chain D2->D4: D4 sees D2's result threaded via ctx (chain is
    SEQUENTIAL). Exercises _run_tier1_with_edges + the depends_on contract WS-D
    populates for the real D2->D4->D5 chain."""
    D2 = "d2.taint"
    D4 = "d4.ifc"
    seen = {}

    async def _d2(req, sess):
        r = ValidationResult(decision="ALLOW", reason="taint", should_deny=False, metadata={"taint": "yes"})
        r.source = Source.SENTRA_SIGMA
        return r

    async def _d4(req, sess):
        seen["ctx_keys"] = [k for k in sess.keys() if k == D2]
        r = ValidationResult(decision="ALLOW", reason="ifc", should_deny=False)
        r.source = Source.SENTRA_CONTEXT
        return r

    nodes = [
        ValidatorNode(D2, CostTier.EXPENSIVE_MODEL, _d2, (), order_key=1),
        ValidatorNode(D4, CostTier.EXPENSIVE_MODEL, _d4, (D2,), order_key=2),
    ]

    def capture(r):
        return r

    def stamp(r):
        return r

    async def timed(label, coro):
        return await coro

    result, _ = await run_dag(
        nodes, sample_request, mock_session, capture, stamp, timed,
        mode=FAIL_FAST, all_allow=lambda: _allow(Source.SENTRA_COMBINED),
        signals=[],
    )
    assert seen["ctx_keys"] == [D2]
    assert result.decision == "ALLOW"


@pytest.mark.asyncio
async def test_t_chain_upstream_abstain_fails_downstream_to_floor(mock_session, sample_request):
    """If the chain upstream abstains, the downstream node MUST abstain (fail to
    the floor) — never treat the missing upstream taint label as clean (HLD §A
    inv 2)."""
    D2 = "d2.taint"
    D4 = "d4.ifc"
    d4_ran = {"called": False}

    async def _d2(req, sess):
        return ValidationResult.abstain("d2 label unavailable")

    async def _d4(req, sess):
        d4_ran["called"] = True
        return _allow(Source.SENTRA_CONTEXT)

    nodes = [
        ValidatorNode(D2, CostTier.EXPENSIVE_MODEL, _d2, (), order_key=1),
        ValidatorNode(D4, CostTier.EXPENSIVE_MODEL, _d4, (D2,), order_key=2),
    ]
    captured = []

    def capture(r):
        captured.append(r)
        return r

    def stamp(r):
        return r

    async def timed(label, coro):
        return await coro

    result, _ = await run_dag(
        nodes, sample_request, mock_session, capture, stamp, timed,
        mode=FAIL_FAST, all_allow=lambda: _allow(Source.SENTRA_COMBINED),
        signals=[],
    )
    assert d4_ran["called"] is False
    assert all(r.is_abstain for r in captured)
    assert result.decision == "ALLOW"


# --------------------------------------------------------------------------- #
# T-PARALLEL — independent tier-1 nodes gather (max, not sum)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_t_parallel_independent_tier1_gather_max_not_sum(mock_session, sample_request):
    """Two independent tier-1 nodes each sleeping 0.1s: wall-time ~= max (0.1s),
    not sum (0.2s), proving they gather concurrently."""
    import time

    async def _slow(req, sess):
        await asyncio.sleep(0.1)
        return _allow(Source.SENTRA_ML_CLASSIFIER)

    async def _slow2(req, sess):
        await asyncio.sleep(0.1)
        return _allow(Source.BEDROCK_GUARDRAIL)

    nodes = [
        ValidatorNode(Source.SENTRA_ML_CLASSIFIER, CostTier.EXPENSIVE_MODEL, _slow, (), order_key=7),
        ValidatorNode(Source.BEDROCK_GUARDRAIL, CostTier.EXPENSIVE_MODEL, _slow2, (), order_key=8),
    ]

    def capture(r):
        return r

    def stamp(r):
        return r

    async def timed(label, coro):
        return await coro

    t0 = time.perf_counter()
    await run_dag(
        nodes, sample_request, mock_session, capture, stamp, timed,
        mode=FAIL_FAST, all_allow=lambda: _allow(Source.SENTRA_COMBINED),
        signals=[],
    )
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.18  # ~0.1s concurrent, well under the 0.2s sum


# --------------------------------------------------------------------------- #
# T-CTX-ISO — chain ctx / session isolation across the gather
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_t_ctx_iso_top_level_rebind_isolated(mock_session, sample_request):
    """Two independent tier-1 nodes under gather; chain ctx is chain-local and
    does not leak into an independent peer's session view (read-only-on-session
    contract for WS-D)."""
    observed = {}

    async def _mutator(req, sess):
        return _allow(Source.SENTRA_ML_CLASSIFIER)

    async def _observer(req, sess):
        observed["keys"] = set(sess.keys())
        return _allow(Source.BEDROCK_GUARDRAIL)

    nodes = [
        ValidatorNode(Source.SENTRA_ML_CLASSIFIER, CostTier.EXPENSIVE_MODEL, _mutator, (), order_key=7),
        ValidatorNode(Source.BEDROCK_GUARDRAIL, CostTier.EXPENSIVE_MODEL, _observer, (), order_key=8),
    ]

    def capture(r):
        return r

    def stamp(r):
        return r

    async def timed(label, coro):
        return await coro

    await run_dag(
        nodes, sample_request, mock_session, capture, stamp, timed,
        mode=FAIL_FAST, all_allow=lambda: _allow(Source.SENTRA_COMBINED),
        signals=[],
    )
    assert "d2.taint" not in observed["keys"]
    assert observed["keys"] == set(mock_session.keys())


# --------------------------------------------------------------------------- #
# T-CHAIN-DENY — an upstream hard-DENY does NOT abort the chain (pins the
# intended chain-DENY semantics before WS-D lands the real D2->D4->D5 chain;
# integration-sentinel FIX-B LOW, run.py run_chain).
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_t_chain_upstream_hard_deny_does_not_abort_downstream(mock_session, sample_request):
    """A chain-upstream hard-DENY differs from an upstream ABSTAIN: the DENY is a
    real, captured verdict, so the downstream node STILL runs (defense-in-depth,
    keep evaluating the deep tier for the trail) with the denier's result threaded
    into ctx — it does NOT fail to the floor the way an abstain does. The combiner
    is order-independent, so the upstream DENY still decides the verdict regardless
    of the downstream node's opinion. Pins the intended semantics WS-D inherits."""
    D2 = "d2.taint"
    D4 = "d4.ifc"
    d4_saw = {}

    async def _d2_deny(req, sess):
        r = _deny(Source.SENTRA_SIGMA, "INDIRECT_INJECTION")
        r.metadata = {"enforce": True}
        return r

    async def _d4(req, sess):
        # downstream node runs and sees the upstream DENY threaded via ctx
        d4_saw["ran"] = True
        d4_saw["ctx_has_d2"] = D2 in sess
        return _allow(Source.SENTRA_CONTEXT)

    nodes = [
        ValidatorNode(D2, CostTier.EXPENSIVE_MODEL, _d2_deny, (), order_key=1),
        ValidatorNode(D4, CostTier.EXPENSIVE_MODEL, _d4, (D2,), order_key=2),
    ]
    captured = []

    def capture(r):
        captured.append(r)
        return r

    def stamp(r):
        return r

    async def timed(label, coro):
        return await coro

    result, signals = await run_dag(
        nodes, sample_request, mock_session, capture, stamp, timed,
        mode=FAIL_FAST, all_allow=lambda: _allow(Source.SENTRA_COMBINED),
        signals=[],
    )
    # downstream RAN (contrast test_t_chain_upstream_abstain_fails_downstream_to_floor)
    assert d4_saw["ran"] is True
    assert d4_saw["ctx_has_d2"] is True
    # and the upstream DENY still decides the verdict (order-independent combiner)
    assert result.decision == "DENY"
    assert result.should_deny is True
    assert result.source == Source.SENTRA_SIGMA
    # neither captured result is an abstain — the chain did NOT fail to the floor
    assert not any(r.is_abstain for r in captured)


# --------------------------------------------------------------------------- #
# T-CHAIN-RAISE-ATTR — a MIDDLE/LATE chain-node raise fails secure AND the
# diagnostic log names the actual raiser, not the chain anchor (c[0])
# (integration-sentinel FIX-B LOW, run.py node_order reconstruction).
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_t_chain_middle_node_raise_logs_actual_raiser_not_anchor(
    mock_session, sample_request, caplog
):
    """When a NON-anchor chain node raises, the request still fails secure (the
    exception is re-raised → outer handler DENY), and the error log attributes the
    raise to the actual raising node's source, NOT the chain's topo-first anchor.
    Guards the node_order reconstruction, which keys on c[0] (the anchor)."""
    import logging

    D2 = "d2.taint"   # anchor (topo-first)
    D4 = "d4.ifc"     # downstream — the raiser

    async def _d2(req, sess):
        r = _allow(Source.SENTRA_SIGMA)
        r.metadata = {"taint": "yes"}
        return r

    async def _d4_raise(req, sess):
        raise RuntimeError("d4 IFC exploded")

    nodes = [
        ValidatorNode(D2, CostTier.EXPENSIVE_MODEL, _d2, (), order_key=1),
        ValidatorNode(D4, CostTier.EXPENSIVE_MODEL, _d4_raise, (D2,), order_key=2),
    ]

    def capture(r):
        return r

    def stamp(r):
        return r

    async def timed(label, coro):
        return await coro

    with caplog.at_level(logging.ERROR, logger="app.services.scheduler.run"):
        with pytest.raises(RuntimeError, match="d4 IFC exploded"):
            await run_dag(
                nodes, sample_request, mock_session, capture, stamp, timed,
                mode=FAIL_FAST, all_allow=lambda: _allow(Source.SENTRA_COMBINED),
                signals=[],
            )
    # the error line names the ACTUAL raiser (D4), not the anchor (D2)
    tier1_errs = [r.getMessage() for r in caplog.records if "raised unexpectedly" in r.getMessage()]
    assert tier1_errs, "expected a tier-1 raise error log line"
    assert D4 in tier1_errs[0]
    assert D2 not in tier1_errs[0]


# --------------------------------------------------------------------------- #
# T-CFG-COERCE — the dag_run_mode field_validator coerces any unknown
# DAG_RUN_MODE to the safe default at LOAD time (RES-6 fail-secure). Pins the
# validator's OWN behavior: monkeypatching settings post-construction bypasses
# it, so this constructs Settings through the validator
# (integration-sentinel FIX-B LOW, config.py _coerce_dag_run_mode).
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("evaluate_none", "fail_fast"),  # unknown value -> safe default
        ("", "fail_fast"),               # empty string -> safe default
        ("FAIL_FAST", "fail_fast"),      # case/whitespace not in the set -> safe default
        ("evaluate_all", "evaluate_all"),  # known value preserved
        ("fail_fast", "fail_fast"),        # known value preserved
    ],
)
def test_t_cfg_coerce_dag_run_mode(raw, expected):
    """RES-6: an unknown DAG_RUN_MODE coerces to fail_fast; a known value passes
    through. Constructs Settings via the DAG_RUN_MODE validation_alias so the
    @field_validator actually runs (deleting the validator makes this FAIL)."""
    from app.config import Settings

    s = Settings(DAG_RUN_MODE=raw)
    assert s.dag_run_mode == expected


def test_t_cfg_dag_run_mode_default_is_fail_fast():
    """With DAG_RUN_MODE unset, the production default is fail_fast (LLD 31 §6.7).
    Constructed fresh so no env leaks the value in."""
    import os
    from app.config import Settings

    saved = os.environ.pop("DAG_RUN_MODE", None)
    try:
        assert Settings().dag_run_mode == "fail_fast"
    finally:
        if saved is not None:
            os.environ["DAG_RUN_MODE"] = saved


# --------------------------------------------------------------------------- #
# T-TIMING — per-node timing instrumentation preserved through the DAG cutover
# (LLD 31 §6.6 / task C6.3). The pre-DAG pipeline emitted a `validation.timing`
# structured log carrying a per-step ms breakdown; the refactor claims this is
# preserved byte-for-byte. These tests pin the LABEL SET the DAG populates so a
# future edit that drops a sub-step (as the abuse_policy_load regression did —
# integration-sentinel FIX-B LOW) fails the build instead of silently blinding
# LLD 24's latency re-baseline.
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_t_timing_dag_emits_per_node_labels(mock_session, sample_request, monkeypatch):
    """All-tier-0-ALLOW + ML ALLOW → the per-request timing dict carries one
    entry per validator node that ran, keyed by its Source.SENTRA_* label, plus
    the policy node's own `policy` sub-label. Pins that run_dag's `timed(node.
    source, ...)` wrapping still records every node (a dropped node = a blinded
    latency metric)."""
    from app.services import validation_service as vs

    service = _pipeline_service(mock_session)
    ml_allow = _allow(Source.SENTRA_ML_CLASSIFIER)
    ml_allow.confidence = 0.9
    service.ml_classifier.validate = AsyncMock(return_value=ml_allow)

    # Initialise the per-request timing contextvar exactly as validate_tool_call
    # does at the top of a real request (validation_service.py M1). Without this
    # _timed is a documented no-op, so the assertion would be vacuous.
    token = vs._step_timings.set({})
    try:
        await _run_ff(service, sample_request, mock_session, monkeypatch)
        timings = vs._step_timings.get()
    finally:
        vs._step_timings.reset(token)

    assert timings is not None
    # Every tier-0 node + the tier-1 ML node recorded its own per-node ms.
    for label in (
        Source.SENTRA_TRUST,
        Source.SENTRA_POLICY,
        Source.SENTRA_CROSS_AGENT,
        Source.SENTRA_SIGMA,
        Source.SENTRA_CONTEXT,
        Source.SENTRA_ABUSE,
        Source.SENTRA_ML_CLASSIFIER,
    ):
        assert label in timings, f"missing per-node timing for {label}: {sorted(timings)}"
    # The policy node's internal selection sub-label is preserved.
    assert "policy" in timings


@pytest.mark.asyncio
async def test_t_timing_abuse_policy_load_sub_step_preserved(mock_session, sample_request, monkeypatch):
    """REGRESSION (integration-sentinel FIX-B LOW): the pre-DAG pipeline timed
    the abuse node's agent-policy fetch under a DISTINCT `abuse_policy_load`
    label (old validation_service.py:414) separate from the `sentra.abuse`
    rate-limit check. The DAG's per-node wrapper only labels the whole node body
    as `sentra.abuse`, so this sub-step was silently dropped. Assert BOTH labels
    are present — reverting the in-node `_timed("abuse_policy_load", ...)` fetch
    makes this FAIL."""
    from app.services import validation_service as vs

    service = _pipeline_service(mock_session)

    token = vs._step_timings.set({})
    try:
        await _run_ff(service, sample_request, mock_session, monkeypatch)
        timings = vs._step_timings.get()
    finally:
        vs._step_timings.reset(token)

    assert "abuse_policy_load" in timings, (
        "abuse_policy_load timing sub-step dropped — the agent-policy fetch inside "
        f"the abuse node is no longer wrapped in _timed(); labels={sorted(timings)}"
    )
    assert Source.SENTRA_ABUSE in timings, (
        "the abuse rate-limit check's own per-node timing must remain distinct "
        "from the policy-load sub-step"
    )
    # The two are genuinely distinct labels (policy-load vs rate-limit check),
    # not one collapsed onto the other.
    assert "abuse_policy_load" != Source.SENTRA_ABUSE
