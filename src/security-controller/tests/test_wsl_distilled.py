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
    """The trained-v1 SIDECAR config (2026-07-10): DENY short-circuit ON at 0.95;
    ALLOW short-circuit gated OFF (fail-open until shadow-proven); service url empty
    (interim escalate path). NO `distilled_shortcircuit_enabled` field."""
    s = Settings()
    assert s.distilled_enabled is True
    assert s.distilled_timeout_ms == 100
    assert s.distilled_service_url == ""                         # unset → escalate path
    assert s.distilled_deny_shortcircuit_min_confidence == 0.95  # DENY safe direction
    assert s.distilled_allow_shortcircuit_min_confidence == 0.95
    assert s.distilled_allow_shortcircuit_enabled is False       # fast-ALLOW gated OFF
    assert not hasattr(s, "distilled_shortcircuit_enabled")
    with patch.dict("os.environ", {"DISTILLED_SERVICE_URL": "http://d.sentra.internal:8080",
                                   "DISTILLED_ALLOW_SHORTCIRCUIT_ENABLED": "true",
                                   "DISTILLED_TIMEOUT_MS": "80"}):
        s2 = Settings()
        assert s2.distilled_service_url == "http://d.sentra.internal:8080"
        assert s2.distilled_allow_shortcircuit_enabled is True
        assert s2.distilled_timeout_ms == 80


@pytest.mark.asyncio
async def test_distilled_client_escalates_when_service_unset():
    """The CLIENT (no service url wired) returns a CONCRETE escalate verdict
    (should_deny=False, confidence 0.0, metadata escalate True), NOT an abstain — so
    run_chain does not abort and Haiku runs. The pre-deploy / fail-secure steady state."""
    with patch.object(settings, "distilled_service_url", ""):
        result = await DistilledClassifier().classify(_req())
    assert result.should_deny is False
    assert result.confidence == 0.0
    assert result.metadata["escalate"] is True
    assert result.is_abstain is False


@pytest.mark.asyncio
async def test_distilled_client_fail_secure_on_service_error():
    """If the model service errors/times out, the client escalates to Haiku (never a
    silent ALLOW-and-stop). Fail-secure: a concrete escalate, not an abstain."""
    with patch.object(settings, "distilled_service_url", "http://unreachable.invalid:8080"), \
         patch.object(settings, "distilled_timeout_ms", 50):
        result = await DistilledClassifier().classify(_req())
    assert result.metadata["escalate"] is True
    assert result.is_abstain is False
    assert result.should_deny is False


@pytest.mark.asyncio
async def test_distilled_client_maps_service_verdict():
    """A well-formed service response maps to a concrete ValidationResult carrying the
    decision + confidence (no escalate key), so the gate can apply the thresholds."""
    from unittest.mock import MagicMock
    fake = {"decision": "DENY", "confidence": 0.97, "model": "distilled_v1_multilingual"}
    dc = DistilledClassifier()
    with patch.object(settings, "distilled_service_url", "http://d.sentra.internal:8080"), \
         patch.object(dc, "_post_sync", return_value=fake):
        r = await dc.classify(_req())
    assert r.decision == "DENY" and r.should_deny is True
    assert r.confidence == 0.97
    assert not (r.metadata or {}).get("escalate")   # concrete verdict → gate decides


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
async def test_confident_distilled_DENY_shortcircuits_haiku():
    """ASYMMETRIC gate (2026-07-10): a CONFIDENT distilled DENY (>= deny threshold)
    ALWAYS short-circuits — _run_ml abstains, Haiku is NOT called. DENY precision was
    measured 1.0 (0 false-blocks) so a DENY short-circuit is fail-secure."""
    svc = _svc()
    confident_deny = ValidationResult(
        decision="DENY", reason="confident", should_deny=True, confidence=0.96,
        source=Source.SENTRA_DISTILLED, metadata={})
    node = _ml_node(svc)
    result = await node.run(_req(), {Source.SENTRA_DISTILLED: confident_deny})
    assert result.is_abstain
    assert result.reason == "distilled_shortcircuit"
    svc.ml_classifier.validate.assert_not_called()


@pytest.mark.asyncio
async def test_confident_distilled_ALLOW_gated_off_runs_haiku():
    """ASYMMETRIC gate: a CONFIDENT distilled ALLOW does NOT short-circuit by default
    (distilled_allow_shortcircuit_enabled=False) — a false-ALLOW is fail-OPEN, gated
    until shadow-proven. Haiku RUNS. Flipping the flag on makes it short-circuit."""
    confident_allow = ValidationResult(
        decision="ALLOW", reason="confident", should_deny=False, confidence=0.96,
        source=Source.SENTRA_DISTILLED, metadata={})

    # default: gate OFF → Haiku runs (the mock Haiku returns abstain, so we assert
    # the CALL happened rather than the result shape — Haiku ran, not short-circuited).
    svc = _svc()
    node = _ml_node(svc)
    with patch.object(settings, "distilled_allow_shortcircuit_enabled", False):
        await node.run(_req(), {Source.SENTRA_DISTILLED: confident_allow})
    svc.ml_classifier.validate.assert_called_once()

    # gate ON (post-shadow) → confident ALLOW short-circuits, Haiku skipped
    svc2 = _svc()
    node2 = _ml_node(svc2)
    with patch.object(settings, "distilled_allow_shortcircuit_enabled", True), \
         patch.object(settings, "distilled_allow_shortcircuit_min_confidence", 0.95):
        result2 = await node2.run(_req(), {Source.SENTRA_DISTILLED: confident_allow})
    assert result2.is_abstain
    svc2.ml_classifier.validate.assert_not_called()


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
async def test_escalate_distilled_runs_haiku():
    """An escalate verdict (escalate True, confidence 0.0 — service unset/error) → Haiku runs."""
    svc = _svc()
    escalate = ValidationResult(decision="ALLOW", reason="escalate", should_deny=False,
                                confidence=0.0, source=Source.SENTRA_DISTILLED,
                                metadata={"escalate": True})
    node = _ml_node(svc)
    await node.run(_req(), {Source.SENTRA_DISTILLED: escalate})
    svc.ml_classifier.validate.assert_awaited_once()


@pytest.mark.asyncio
async def test_lowconf_distilled_DENY_runs_haiku():
    """A low-confidence distilled DENY (< deny threshold) → Haiku runs (does not
    short-circuit; the confident-DENY floor is 0.95)."""
    svc = _svc()
    lowconf = ValidationResult(decision="DENY", reason="lowconf", should_deny=True,
                               confidence=0.5, source=Source.SENTRA_DISTILLED, metadata={})
    node = _ml_node(svc)
    await node.run(_req(), {Source.SENTRA_DISTILLED: lowconf})
    svc.ml_classifier.validate.assert_awaited_once()


@pytest.mark.asyncio
async def test_deny_uses_deny_threshold_not_ml_threshold():
    """The DENY short-circuit gate compares against distilled_deny_shortcircuit_min_
    confidence (0.95), NOT ml_confidence_trust_threshold. A 0.96 DENY short-circuits."""
    with patch.object(settings, "distilled_deny_shortcircuit_min_confidence", 0.95), \
         patch.object(settings, "ml_confidence_trust_threshold", 0.99):
        svc = _svc()
        deny = ValidationResult(decision="DENY", reason="conf", should_deny=True,
                                confidence=0.96, source=Source.SENTRA_DISTILLED, metadata={})
        node = _ml_node(svc)
        result = await node.run(_req(), {Source.SENTRA_DISTILLED: deny})
        assert result.is_abstain   # short-circuited on the DENY threshold (0.95)
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
