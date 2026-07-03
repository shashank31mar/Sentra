"""WS-L M6 — the distilled front-runner: LIVE, short-circuit ON, no shadow.

Config fields (no `_shortcircuit_enabled` flag) + the interim classifier + the
`sentra.distilled` LIVE chain-head + the intrinsic short-circuit in `_run_ml`.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.api.models import ValidationRequest, ValidationResult
from app.combiners import Source
from app.config import Settings, settings
from app.services.scheduler import build_dag
from app.services.scheduler.node import CostTier
from app.validators.distilled_classifier import DistilledClassifier


def _req():
    return ValidationRequest(
        request_id="r", session_id="s", agent_id="a", tool_name="chat",
        tool_params={}, user_input="hi", timestamp="2026-07-03T00:00:00Z",
        operation_type="READ",
    )


def _svc(distilled=None):
    from app.services.validation_service import ValidationService
    with patch.object(ValidationService, "__init__", lambda self: None):
        svc = ValidationService()
    svc.distilled_classifier = distilled or DistilledClassifier()
    svc.ml_classifier = Mock()
    svc.ml_classifier.validate = AsyncMock(return_value=ValidationResult.abstain("off"))
    return svc


# ------------------------------------------------------------------ M6.0
def test_distilled_config_defaults():
    """distilled_enabled defaults True (LIVE front-runner); threshold 0.9; timeout
    100ms; there is NO `distilled_shortcircuit_enabled` field (intrinsic short-circuit)."""
    s = Settings()
    assert s.distilled_enabled is True
    assert s.distilled_confidence_trust_threshold == 0.9
    assert s.distilled_timeout_ms == 100
    assert not hasattr(s, "distilled_shortcircuit_enabled")
    # each field reads its validation_alias.
    with patch.dict("os.environ", {"DISTILLED_ENABLED": "false",
                                   "DISTILLED_CONFIDENCE_TRUST_THRESHOLD": "0.75",
                                   "DISTILLED_TIMEOUT_MS": "50"}):
        s2 = Settings()
        assert s2.distilled_enabled is False
        assert s2.distilled_confidence_trust_threshold == 0.75
        assert s2.distilled_timeout_ms == 50


@pytest.mark.asyncio
async def test_distilled_interim_is_escalate_not_abstain():
    """The interim classify() returns a CONCRETE escalate verdict (should_deny=False,
    confidence 0.0, metadata escalate True) and is NOT an abstain (so run_chain does
    not abort; Haiku runs)."""
    result = await DistilledClassifier().classify(_req())
    assert result.should_deny is False
    assert result.confidence == 0.0
    assert result.metadata["escalate"] is True
    assert result.is_abstain is False


# ------------------------------------------------------------------ M6.1
def test_distilled_is_live_tier1_chain_head():
    """With defaults (distilled_enabled True): sentra.distilled is in the request node
    set, tier-1, and ml chains behind it (depends_on == (SENTRA_DISTILLED,))."""
    from app.services.scheduler.run import _build_chains

    nodes = build_dag(_svc(), "request", {"platform": None, "cloud_region": None})
    by_src = {n.source: n for n in nodes}
    assert Source.SENTRA_DISTILLED in by_src
    assert by_src[Source.SENTRA_DISTILLED].cost_tier == CostTier.EXPENSIVE_MODEL
    assert by_src[Source.SENTRA_ML_CLASSIFIER].depends_on == (Source.SENTRA_DISTILLED,)

    # _build_chains groups distilled → ml into one chain, distilled first.
    tier1 = [n for n in nodes if n.cost_tier == CostTier.EXPENSIVE_MODEL]
    chains = _build_chains([n for n in tier1
                            if set(n.depends_on) & {t.source for t in tier1}
                            or n.source in {d for t in tier1 for d in t.depends_on if d in {x.source for x in tier1}}])
    # the distilled→ml chain exists with distilled before ml.
    chain = next(c for c in chains if any(n.source == Source.SENTRA_ML_CLASSIFIER for n in c))
    srcs = [n.source for n in chain]
    assert srcs.index(Source.SENTRA_DISTILLED) < srcs.index(Source.SENTRA_ML_CLASSIFIER)


def test_distilled_emits_so_fallback_order_valid():
    """The LIVE distilled node emits on a survivor → SENTRA_DISTILLED is in
    STATIC_FALLBACK_ORDER, _ORDER, and STEP_LABEL_TO_SOURCE.values() (triple-equality)."""
    from app.combiners.sources import STATIC_FALLBACK_ORDER, STEP_LABEL_TO_SOURCE
    from app.services.scheduler.registry import _ORDER

    assert Source.SENTRA_DISTILLED in set(STATIC_FALLBACK_ORDER)
    assert Source.SENTRA_DISTILLED in set(_ORDER)
    assert Source.SENTRA_DISTILLED in set(STEP_LABEL_TO_SOURCE.values())
    assert set(STATIC_FALLBACK_ORDER) == set(_ORDER) == set(STEP_LABEL_TO_SOURCE.values())


def test_distilled_killswitch_off_restores_graph():
    """distilled_enabled=False (operability kill-switch): no distilled node,
    ml.depends_on == (SENTRA_POLICY,) — the byte-identical rollback graph."""
    with patch.object(settings, "distilled_enabled", False):
        nodes = build_dag(_svc(), "request", {"platform": None, "cloud_region": None})
    by_src = {n.source: n for n in nodes}
    assert Source.SENTRA_DISTILLED not in by_src
    assert by_src[Source.SENTRA_ML_CLASSIFIER].depends_on == (Source.SENTRA_POLICY,)


@pytest.mark.asyncio
async def test_distilled_never_abstains_on_error():
    """_run_distilled whose inner classify raises / times out returns a CONCRETE
    should_deny=False verdict with metadata escalate + is_abstain False (chain
    continues to Haiku; fail-secure, never ALLOW-and-stop)."""
    class _Boom:
        async def classify(self, req):
            raise RuntimeError("distilled model crashed")

    svc = _svc(distilled=_Boom())
    nodes = build_dag(svc, "request", {"platform": None, "cloud_region": None})
    distilled_node = next(n for n in nodes if n.source == Source.SENTRA_DISTILLED)
    result = await distilled_node.run(_req(), {})
    assert result.should_deny is False
    assert result.metadata.get("escalate") is True
    assert result.is_abstain is False


@pytest.mark.asyncio
async def test_distilled_run_is_single_awaitable():
    """_run_distilled issues no asyncio.gather (one classify awaitable)."""
    svc = _svc()
    svc.distilled_classifier.classify = AsyncMock(
        return_value=ValidationResult(decision="ALLOW", reason="x", should_deny=False,
                                      confidence=0.0, metadata={"escalate": True}))
    nodes = build_dag(svc, "request", {"platform": None, "cloud_region": None})
    distilled_node = next(n for n in nodes if n.source == Source.SENTRA_DISTILLED)
    with patch("asyncio.gather", side_effect=AssertionError("must not gather")):
        await distilled_node.run(_req(), {})
    svc.distilled_classifier.classify.assert_awaited_once()


# ------------------------------------------------------------------ M6.2 (the LIVE short-circuit)
def _ml_node(svc):
    nodes = build_dag(svc, "request", {"platform": None, "cloud_region": None})
    return next(n for n in nodes if n.source == Source.SENTRA_ML_CLASSIFIER)


@pytest.mark.asyncio
async def test_confident_distilled_shortcircuits_haiku():
    """A CONFIDENT distilled result in sess → _run_ml returns abstain(distilled_
    shortcircuit) and ml_classifier.validate is NOT called (both ALLOW and DENY)."""
    for decision, deny in (("ALLOW", False), ("DENY", True)):
        svc = _svc()
        confident = ValidationResult(
            decision=decision, reason="confident", should_deny=deny, confidence=0.95,
            source=Source.SENTRA_DISTILLED, metadata={})
        node = _ml_node(svc)
        result = await node.run(_req(), {Source.SENTRA_DISTILLED: confident})
        assert result.is_abstain
        assert result.reason == "distilled_shortcircuit"
        svc.ml_classifier.validate.assert_not_called()


@pytest.mark.asyncio
async def test_confident_distilled_deny_is_enforce_stamped():
    """integration-sentinel FIX-B HIGH — a CONFIDENT distilled DENY returned by the
    `_run_distilled` NODE carries metadata['enforce']=True, so `_is_hard_deny` lets it
    DECIDE the verdict after it short-circuits Haiku. Before the fix the DENY was never
    enforce-stamped → excluded from hard_denies → run_dag fell through to ALLOW (blocked
    nothing while ALSO disabling Haiku). A confident ALLOW is NOT stamped."""
    from app.services.scheduler.run import _is_hard_deny

    class _ConfidentDeny:
        async def classify(self, req):
            return ValidationResult(
                decision="DENY", reason="distilled: malicious", should_deny=True,
                confidence=0.95, source=Source.SENTRA_DISTILLED, metadata={})

    svc = _svc(distilled=_ConfidentDeny())
    node = next(n for n in build_dag(svc, "request", {"platform": None, "cloud_region": None})
                if n.source == Source.SENTRA_DISTILLED)
    result = await node.run(_req(), {})
    assert result.should_deny is True
    assert (result.metadata or {}).get("enforce") is True
    assert _is_hard_deny(result) is True, "a confident distilled DENY must be able to decide"

    # A confident ALLOW is not enforce-stamped (an ALLOW is never a hard-DENY).
    class _ConfidentAllow:
        async def classify(self, req):
            return ValidationResult(
                decision="ALLOW", reason="distilled: clean", should_deny=False,
                confidence=0.95, source=Source.SENTRA_DISTILLED, metadata={})

    svc2 = _svc(distilled=_ConfidentAllow())
    node2 = next(n for n in build_dag(svc2, "request", {"platform": None, "cloud_region": None})
                 if n.source == Source.SENTRA_DISTILLED)
    allow = await node2.run(_req(), {})
    assert allow.should_deny is False
    assert (allow.metadata or {}).get("enforce") is not True


@pytest.mark.asyncio
async def test_lowconf_distilled_deny_not_enforce_stamped():
    """A LOW-confidence distilled DENY (below the distilled threshold) is NOT
    enforce-stamped: it does not short-circuit Haiku, so Haiku is the intended
    decider and a non-confident distilled DENY must stay advisory (fail-safe
    under-block, never surprise-block)."""
    from app.services.scheduler.run import _is_hard_deny

    class _LowConfDeny:
        async def classify(self, req):
            return ValidationResult(
                decision="DENY", reason="distilled: maybe", should_deny=True,
                confidence=0.4, source=Source.SENTRA_DISTILLED, metadata={})

    svc = _svc(distilled=_LowConfDeny())
    node = next(n for n in build_dag(svc, "request", {"platform": None, "cloud_region": None})
                if n.source == Source.SENTRA_DISTILLED)
    result = await node.run(_req(), {})
    assert result.should_deny is True
    assert (result.metadata or {}).get("enforce") is not True
    assert _is_hard_deny(result) is False


@pytest.mark.asyncio
async def test_confident_distilled_deny_blocks_full_pipeline():
    """integration-sentinel FIX-B HIGH (the end-to-end repro) — a CONFIDENT distilled
    DENY drives the FULL pipeline to a blocking DENY verdict with winning_source =
    sentra.distilled, AND Haiku (ml_classifier.validate) is NOT called. Before the fix
    this trajectory returned ALLOW (all_allow fall-through) while having suppressed
    Haiku — strictly worse than not short-circuiting."""
    from app.services.validation_service import ValidationService

    class _ConfidentDeny:
        async def classify(self, req):
            return ValidationResult(
                decision="DENY", reason="distilled: injection detected", should_deny=True,
                confidence=0.97, source=Source.SENTRA_DISTILLED, metadata={})

    with patch.object(ValidationService, "__init__", lambda self: None):
        svc = ValidationService()
    svc.cedar_engine = None
    allow = ValidationResult(decision="ALLOW", reason="ok", should_deny=False)
    svc.trust_checker = Mock(); svc.trust_checker.check = AsyncMock(return_value=allow)
    svc.policy_engine = Mock()
    svc.policy_engine.validate = AsyncMock(return_value=allow)
    svc.policy_engine.get_agent_policy = AsyncMock(return_value={"rate_limit": 100})
    svc.policy_engine.get_agent_cloud_identity = Mock(return_value=(None, None))
    svc.cross_agent_validator = Mock()
    svc.cross_agent_validator.validate = AsyncMock(return_value=allow)
    svc.sigma_engine = Mock()
    svc.sigma_engine.match_rules = AsyncMock(return_value=allow)
    svc.context_validator = Mock()
    svc.context_validator.validate_sequence = AsyncMock(return_value=allow)
    svc.abuse_detector = Mock()
    svc.abuse_detector.check_rate_limit = AsyncMock(return_value=allow)
    svc.ml_classifier = Mock()
    svc.ml_classifier.validate = AsyncMock(return_value=ValidationResult.abstain("off"))
    svc.distilled_classifier = _ConfidentDeny()
    svc.metrics_publisher = Mock()
    svc.metrics_publisher.publish_node_metrics = AsyncMock()

    session = {"session_id": "s", "agent_id": "a", "trust_score": 80.0, "action_count": 1}
    result, _signals = await svc._run_validation_pipeline(_req(), dict(session))

    assert result.should_deny is True, "a confident distilled DENY must BLOCK the pipeline"
    assert result.decision == "DENY"
    assert result.source == Source.SENTRA_DISTILLED
    svc.ml_classifier.validate.assert_not_called()  # Haiku was short-circuited


@pytest.mark.asyncio
async def test_interim_distilled_runs_haiku():
    """The interim distilled result (escalate True, confidence 0.0) → Haiku runs."""
    svc = _svc()
    interim = ValidationResult(decision="ALLOW", reason="interim", should_deny=False,
                               confidence=0.0, source=Source.SENTRA_DISTILLED,
                               metadata={"escalate": True})
    node = _ml_node(svc)
    await node.run(_req(), {Source.SENTRA_DISTILLED: interim})
    svc.ml_classifier.validate.assert_awaited_once()


@pytest.mark.asyncio
async def test_lowconf_distilled_runs_haiku():
    """A real-but-low-confidence distilled verdict (confidence < threshold) → Haiku runs."""
    svc = _svc()
    lowconf = ValidationResult(decision="ALLOW", reason="lowconf", should_deny=False,
                               confidence=0.5, source=Source.SENTRA_DISTILLED, metadata={})
    node = _ml_node(svc)
    await node.run(_req(), {Source.SENTRA_DISTILLED: lowconf})
    svc.ml_classifier.validate.assert_awaited_once()


@pytest.mark.asyncio
async def test_distilled_own_threshold():
    """FIX-A3: the short-circuit gate compares against distilled_confidence_trust_
    threshold, NOT ml_confidence_trust_threshold. Construct a confidence BETWEEN the
    two and assert the distilled threshold governs."""
    # distilled threshold 0.8, ml threshold 0.95 → a 0.85 confidence is confident for
    # distilled (short-circuits) but would be below the ml threshold.
    with patch.object(settings, "distilled_confidence_trust_threshold", 0.8), \
         patch.object(settings, "ml_confidence_trust_threshold", 0.95):
        svc = _svc()
        mid = ValidationResult(decision="ALLOW", reason="mid", should_deny=False,
                               confidence=0.85, source=Source.SENTRA_DISTILLED, metadata={})
        node = _ml_node(svc)
        result = await node.run(_req(), {Source.SENTRA_DISTILLED: mid})
        assert result.is_abstain   # short-circuited on the DISTILLED threshold (0.8), not ml's 0.95
        svc.ml_classifier.validate.assert_not_called()


def test_no_shortcircuit_enable_flag():
    """There is NO distilled_shortcircuit_enabled setting; the short-circuit is
    intrinsic (fires purely on confidence)."""
    assert not hasattr(settings, "distilled_shortcircuit_enabled")
    assert "distilled_shortcircuit_enabled" not in Settings.model_fields


# ------------------------------------------------------------------ M6.1 INTEG (verdict-equivalence)
@pytest.mark.asyncio
async def test_interim_distilled_verdict_equivalent_to_killswitch_off():
    """T-EQUIV: with defaults (distilled LIVE + interim classifier) the request verdict
    equals the kill-switch-off graph verdict — the interim always escalates so Haiku
    still decides. Drives the full pipeline both ways with mocked validators."""
    from app.services.validation_service import ValidationService

    def _full_svc():
        with patch.object(ValidationService, "__init__", lambda self: None):
            svc = ValidationService()
        svc.cedar_engine = None
        allow = ValidationResult(decision="ALLOW", reason="ok", should_deny=False)
        svc.trust_checker = Mock(); svc.trust_checker.check = AsyncMock(return_value=allow)
        svc.policy_engine = Mock()
        svc.policy_engine.validate = AsyncMock(return_value=allow)
        svc.policy_engine.get_agent_policy = AsyncMock(return_value={"rate_limit": 100})
        svc.policy_engine.get_agent_cloud_identity = Mock(return_value=(None, None))
        svc.cross_agent_validator = Mock()
        svc.cross_agent_validator.validate = AsyncMock(return_value=allow)
        svc.sigma_engine = Mock()
        svc.sigma_engine.match_rules = AsyncMock(return_value=allow)
        svc.context_validator = Mock()
        svc.context_validator.validate_sequence = AsyncMock(return_value=allow)
        svc.abuse_detector = Mock()
        svc.abuse_detector.check_rate_limit = AsyncMock(return_value=allow)
        svc.ml_classifier = Mock()
        svc.ml_classifier.validate = AsyncMock(return_value=ValidationResult.abstain("off"))
        svc.distilled_classifier = DistilledClassifier()
        svc.metrics_publisher = Mock()
        svc.metrics_publisher.publish_node_metrics = AsyncMock()
        return svc

    session = {"session_id": "s", "agent_id": "a", "trust_score": 80.0, "action_count": 1}

    live_result, _ = await _full_svc()._run_validation_pipeline(_req(), dict(session))
    with patch.object(settings, "distilled_enabled", False):
        off_result, _ = await _full_svc()._run_validation_pipeline(_req(), dict(session))

    assert (live_result.decision, live_result.should_deny) == (off_result.decision, off_result.should_deny)
