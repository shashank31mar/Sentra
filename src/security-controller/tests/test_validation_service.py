"""
Unit Tests for Validation Service

Tests the main validation pipeline orchestration.
These are simplified integration-style tests that verify the service works correctly.
"""
import asyncio
import pytest
from unittest.mock import Mock, patch, AsyncMock
from app.api.models import ValidationRequest, ValidationResult


async def _drain_bg():
    """WS24 M4.2: audit + metrics are emitted off the response path via
    fire-and-forget tasks. Await any pending ones so telemetry assertions are
    deterministic."""
    import app.services.validation_service as _vs
    pending = list(_vs._bg_tasks)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


@pytest.fixture
def mock_session():
    """Mock session data"""
    return {
        "session_id": "sess-123",
        "user_id": "user-456",
        "agent_id": "test-agent",
        "trust_score": 75.0,
        "created_at": "2025-11-19T10:00:00Z",
        "last_activity": "2025-11-19T10:00:00Z",
        "action_count": 5
    }


@pytest.fixture
def sample_request():
    """Sample validation request"""
    return ValidationRequest(
        request_id="req-123",
        session_id="sess-123",
        agent_id="test-agent",
        tool_name="get_user_info",
        tool_params={"user_id": "123"},
        user_input="Get user information",
        timestamp="2025-11-19T10:00:00Z",
        operation_type="READ"
    )


# ============================================================
# Basic Structure Tests
# ============================================================

@pytest.mark.asyncio
async def test_validation_service_imports():
    """Test that ValidationService can be imported and instantiated"""
    with patch('app.utils.session_manager.SessionManager'), \
         patch('app.utils.audit_logger.AuditLogger'), \
         patch('app.utils.metrics_publisher.MetricsPublisher'):
        
        from app.services.validation_service import ValidationService
        service = ValidationService()
        
        assert service is not None
        assert hasattr(service, 'session_manager')
        assert hasattr(service, 'trust_checker')
        assert hasattr(service, 'policy_engine')
        assert hasattr(service, 'sigma_engine')
        assert hasattr(service, 'context_validator')
        assert hasattr(service, 'abuse_detector')
        assert hasattr(service, 'audit_logger')
        assert hasattr(service, 'metrics_publisher')


@pytest.mark.asyncio
async def test_validation_service_has_validate_method():
    """Test that ValidationService has validate_tool_call method"""
    with patch('app.utils.session_manager.SessionManager'), \
         patch('app.utils.audit_logger.AuditLogger'), \
         patch('app.utils.metrics_publisher.MetricsPublisher'):
        
        from app.services.validation_service import ValidationService
        service = ValidationService()
        
        assert hasattr(service, 'validate_tool_call')
        assert callable(service.validate_tool_call)


@pytest.mark.asyncio
async def test_validation_service_structure():
    """Test that ValidationService has correct structure and dependencies"""
    with patch('app.utils.session_manager.SessionManager'), \
         patch('app.utils.audit_logger.AuditLogger'), \
         patch('app.utils.metrics_publisher.MetricsPublisher'):
        
        from app.services.validation_service import ValidationService
        
        service = ValidationService()
        
        # Verify all validators are initialized
        assert service.trust_checker is not None
        assert service.policy_engine is not None
        assert service.sigma_engine is not None
        assert service.context_validator is not None
        assert service.abuse_detector is not None
        assert service.audit_logger is not None
        assert service.metrics_publisher is not None
        assert service.session_manager is not None


# ============================================================
# Pipeline Flow Tests
# ============================================================

@pytest.mark.asyncio
async def test_validation_pipeline_full_allow(mock_session, sample_request):
    """Test full ALLOW flow when all validators pass"""
    # This test verifies the actual pipeline works end-to-end
    # We're testing with real validators but mocked dependencies
    from app.services.validation_service import ValidationService
    
    # Mock the session manager to return our test session
    with patch.object(ValidationService, '__init__', lambda self: None):
        service = ValidationService()
        
        # Setup mocked dependencies
        service.session_manager = Mock()
        service.session_manager.get_or_create_session = AsyncMock(return_value=mock_session)
        service.session_manager.update_trust_score_allow = AsyncMock(return_value={**mock_session, "trust_score": 76.0})
        
        # Mock all validators to pass
        service.trust_checker = Mock()
        service.trust_checker.check = AsyncMock(return_value=ValidationResult(
            decision="ALLOW", reason="OK", should_deny=False
        ))
        
        service.policy_engine = Mock()
        service.policy_engine.validate = AsyncMock(return_value=ValidationResult(
            decision="ALLOW", reason="OK", should_deny=False
        ))
        service.policy_engine.get_agent_policy = AsyncMock(return_value={"rate_limit": 100})

        # Workstream 12 added cross_agent_validator as step 2.5 of the pipeline.
        # Tests that mock the full pipeline must also mock this validator or the
        # orchestrator will hit the real (unmocked) implementation and fail.
        service.cross_agent_validator = Mock()
        service.cross_agent_validator.validate = AsyncMock(return_value=ValidationResult(
            decision="ALLOW", reason="OK", should_deny=False
        ))

        service.sigma_engine = Mock()
        service.sigma_engine.match_rules = AsyncMock(return_value=ValidationResult(
            decision="ALLOW", reason="OK", should_deny=False
        ))
        
        service.context_validator = Mock()
        service.context_validator.validate_sequence = AsyncMock(return_value=ValidationResult(
            decision="ALLOW", reason="OK", should_deny=False
        ))
        
        service.abuse_detector = Mock()
        service.abuse_detector.check_rate_limit = AsyncMock(return_value=ValidationResult(
            decision="ALLOW", reason="OK", should_deny=False
        ))

        # Workstream 19 added ml_classifier as step 3.5 of the pipeline. Default
        # production behavior is ABSTAIN (flag off) — mock that here so the
        # orchestrator doesn't hit the real Bedrock-backed validator.
        service.ml_classifier = Mock()
        service.ml_classifier.validate = AsyncMock(
            return_value=ValidationResult.abstain("ml_classifier disabled")
        )

        # WS-L M6: the distilled front-runner is a LIVE tier-1 node — mock it so the
        # scheduler's _run_distilled doesn't hit the real classifier. Interim
        # behaviour = escalate → Haiku (the mocked ml) still decides (T-EQUIV).
        service.distilled_classifier = Mock()
        service.distilled_classifier.classify = AsyncMock(
            return_value=ValidationResult.abstain("distilled test-stub")
        )

        service.audit_logger = Mock()
        service.audit_logger.log_decision = AsyncMock()
        # WS-L: the distilled node stamps a real Source, so `signals` is non-empty on
        # an all-ALLOW request and the off-path audit dual-write takes the log_signals
        # branch (previously the bare-mock validators emitted no source → empty
        # signals → log_decision branch). Mock it async so the fire-and-forget task
        # is a real coroutine.
        service.audit_logger.log_signals = AsyncMock()

        service.metrics_publisher = Mock()
        service.metrics_publisher.publish_validation_metrics = AsyncMock()
        service.metrics_publisher.publish_node_metrics = AsyncMock()  # WS-L M1.6 per-node metric

        result = await service.validate_tool_call(sample_request)
        await _drain_bg()  # WS24 M4.2: let fire-and-forget telemetry finish

        # Verify ALLOW decision
        assert result["decision"] == "ALLOW"
        assert result["reason"] == "All validation checks passed"
        assert result["trust_score"] == 76.0
        assert result["session_id"] == "sess-123"
        assert "latency_ms" in result

        # WS-21 T01: decision metrics emitted at validation time (correct kwargs)
        service.metrics_publisher.publish_validation_metrics.assert_awaited_once()
        kwargs = service.metrics_publisher.publish_validation_metrics.await_args.kwargs
        assert kwargs["decision"] == "ALLOW"
        assert kwargs["trust_score"] == 76.0
        assert kwargs["agent_id"] == sample_request.agent_id


@pytest.mark.asyncio
async def test_validation_pipeline_deny_at_trust_checker(mock_session, sample_request):
    """Test DENY when trust checker fails"""
    from app.services.validation_service import ValidationService
    
    with patch.object(ValidationService, '__init__', lambda self: None):
        service = ValidationService()
        
        # Setup mocked dependencies
        service.session_manager = Mock()
        service.session_manager.get_or_create_session = AsyncMock(return_value=mock_session)
        service.session_manager.update_trust_score_deny = AsyncMock(return_value={**mock_session, "trust_score": 60.0})
        
        # Trust checker denies
        service.trust_checker = Mock()
        service.trust_checker.check = AsyncMock(return_value=ValidationResult(
            decision="DENY",
            reason="Trust score too low",
            should_deny=True,
            violation_type="LOW_TRUST"
        ))
        
        service.audit_logger = Mock()
        service.audit_logger.log_decision = AsyncMock()
        
        service.metrics_publisher = Mock()
        service.metrics_publisher.publish_validation_metrics = AsyncMock()
        
        result = await service.validate_tool_call(sample_request)
        await _drain_bg()  # WS24 M4.2: let fire-and-forget telemetry finish

        # Verify DENY decision
        assert result["decision"] == "DENY"
        assert result["reason"] == "Trust score too low"
        assert result["trust_score"] == 60.0
        assert result["violation_type"] == "LOW_TRUST"

        # WS-21 T01: DENY decision metric emitted at validation time
        service.metrics_publisher.publish_validation_metrics.assert_awaited_once()
        dkwargs = service.metrics_publisher.publish_validation_metrics.await_args.kwargs
        assert dkwargs["decision"] == "DENY"
        assert dkwargs["trust_score"] == 60.0


@pytest.mark.asyncio
async def test_action_id_generation_for_write_operations(mock_session):
    """Test that action_id is generated for WRITE operations on reversible tools"""
    from app.services.validation_service import ValidationService
    
    with patch.object(ValidationService, '__init__', lambda self: None):
        service = ValidationService()
        
        # Setup mocked dependencies
        service.session_manager = Mock()
        service.session_manager.get_or_create_session = AsyncMock(return_value=mock_session)
        service.session_manager.update_trust_score_allow = AsyncMock(return_value=mock_session)
        
        # Mock all validators to pass
        service.trust_checker = Mock()
        service.trust_checker.check = AsyncMock(return_value=ValidationResult(
            decision="ALLOW", reason="OK", should_deny=False
        ))
        
        service.policy_engine = Mock()
        service.policy_engine.validate = AsyncMock(return_value=ValidationResult(
            decision="ALLOW", reason="OK", should_deny=False
        ))
        service.policy_engine.get_agent_policy = AsyncMock(return_value={"rate_limit": 100})

        # Workstream 12 added cross_agent_validator as step 2.5 of the pipeline.
        # Tests that mock the full pipeline must also mock this validator or the
        # orchestrator will hit the real (unmocked) implementation and fail.
        service.cross_agent_validator = Mock()
        service.cross_agent_validator.validate = AsyncMock(return_value=ValidationResult(
            decision="ALLOW", reason="OK", should_deny=False
        ))

        service.sigma_engine = Mock()
        service.sigma_engine.match_rules = AsyncMock(return_value=ValidationResult(
            decision="ALLOW", reason="OK", should_deny=False
        ))
        
        service.context_validator = Mock()
        service.context_validator.validate_sequence = AsyncMock(return_value=ValidationResult(
            decision="ALLOW", reason="OK", should_deny=False
        ))
        
        service.abuse_detector = Mock()
        service.abuse_detector.check_rate_limit = AsyncMock(return_value=ValidationResult(
            decision="ALLOW", reason="OK", should_deny=False
        ))

        # Workstream 19 added ml_classifier as step 3.5 of the pipeline. Default
        # production behavior is ABSTAIN (flag off) — mock that here so the
        # orchestrator doesn't hit the real Bedrock-backed validator.
        service.ml_classifier = Mock()
        service.ml_classifier.validate = AsyncMock(
            return_value=ValidationResult.abstain("ml_classifier disabled")
        )

        # WS-L M6: mock the LIVE distilled front-runner node.
        service.distilled_classifier = Mock()
        service.distilled_classifier.classify = AsyncMock(
            return_value=ValidationResult.abstain("distilled test-stub")
        )

        service.audit_logger = Mock()
        service.audit_logger.log_decision = AsyncMock()
        service.audit_logger.log_signals = AsyncMock()  # WS-L: distilled stamps a source → log_signals branch

        service.metrics_publisher = Mock()
        service.metrics_publisher.publish_validation_metrics = AsyncMock()
        service.metrics_publisher.publish_node_metrics = AsyncMock()  # WS-L M1.6

        # Test WRITE operation on reversible tool
        request = ValidationRequest(
            request_id="req-123",
            session_id="sess-123",
            agent_id="test-agent",
            tool_name="process_refund",
            tool_params={"amount": 100},
            user_input="Process refund",
            timestamp="2025-11-19T10:00:00Z",
            operation_type="WRITE"
        )
        
        result = await service.validate_tool_call(request)
        
        assert result["decision"] == "ALLOW"
        assert "action_id" in result
        assert result["action_id"] is not None
        assert result["action_id"].startswith("act-process_refund-")


@pytest.mark.asyncio
async def test_validation_pipeline_fail_secure_on_error():
    """Test that validation fails secure (DENY) on unexpected errors"""
    with patch('app.utils.session_manager.SessionManager') as mock_sm, \
         patch('app.utils.audit_logger.AuditLogger'), \
         patch('app.utils.metrics_publisher.MetricsPublisher'):
        
        # Make session_manager raise an error
        mock_sm_instance = Mock()
        mock_sm_instance.get_or_create_session = AsyncMock(side_effect=Exception("Test error"))
        mock_sm.return_value = mock_sm_instance
        
        from app.services.validation_service import ValidationService
        
        service = ValidationService()
        
        request = ValidationRequest(
            request_id="test-123",
            session_id="sess-123",
            agent_id="test-agent",
            tool_name="test_tool",
            tool_params={},
            user_input="test",
            timestamp="2025-11-19T10:00:00Z",
            operation_type="READ"
        )
        
        result = await service.validate_tool_call(request)
        
        # Should fail secure with DENY
        assert result["decision"] == "DENY"
        assert "error" in result["reason"].lower() or "internal" in result["reason"].lower()
        assert result["trust_score"] == 0.0
        assert result["violation_type"] == "SYSTEM_ERROR"


@pytest.mark.asyncio
async def test_audit_and_metrics_called_on_allow(mock_session, sample_request):
    """Test that audit log and metrics are called on ALLOW"""
    from app.services.validation_service import ValidationService
    
    with patch.object(ValidationService, '__init__', lambda self: None):
        service = ValidationService()
        
        # Setup mocked dependencies
        service.session_manager = Mock()
        service.session_manager.get_or_create_session = AsyncMock(return_value=mock_session)
        service.session_manager.update_trust_score_allow = AsyncMock(return_value=mock_session)
        
        # Mock all validators to pass
        service.trust_checker = Mock()
        service.trust_checker.check = AsyncMock(return_value=ValidationResult(
            decision="ALLOW", reason="OK", should_deny=False
        ))
        
        service.policy_engine = Mock()
        service.policy_engine.validate = AsyncMock(return_value=ValidationResult(
            decision="ALLOW", reason="OK", should_deny=False
        ))
        service.policy_engine.get_agent_policy = AsyncMock(return_value={"rate_limit": 100})

        # Workstream 12 added cross_agent_validator as step 2.5 of the pipeline.
        # Tests that mock the full pipeline must also mock this validator or the
        # orchestrator will hit the real (unmocked) implementation and fail.
        service.cross_agent_validator = Mock()
        service.cross_agent_validator.validate = AsyncMock(return_value=ValidationResult(
            decision="ALLOW", reason="OK", should_deny=False
        ))

        service.sigma_engine = Mock()
        service.sigma_engine.match_rules = AsyncMock(return_value=ValidationResult(
            decision="ALLOW", reason="OK", should_deny=False
        ))
        
        service.context_validator = Mock()
        service.context_validator.validate_sequence = AsyncMock(return_value=ValidationResult(
            decision="ALLOW", reason="OK", should_deny=False
        ))
        
        service.abuse_detector = Mock()
        service.abuse_detector.check_rate_limit = AsyncMock(return_value=ValidationResult(
            decision="ALLOW", reason="OK", should_deny=False
        ))

        # Workstream 19 added ml_classifier as step 3.5 of the pipeline. Default
        # production behavior is ABSTAIN (flag off) — mock that here so the
        # orchestrator doesn't hit the real Bedrock-backed validator.
        service.ml_classifier = Mock()
        service.ml_classifier.validate = AsyncMock(
            return_value=ValidationResult.abstain("ml_classifier disabled")
        )

        # WS-L M6: mock the LIVE distilled front-runner node.
        service.distilled_classifier = Mock()
        service.distilled_classifier.classify = AsyncMock(
            return_value=ValidationResult.abstain("distilled test-stub")
        )

        service.audit_logger = Mock()
        service.audit_logger.log_decision = AsyncMock()
        service.audit_logger.log_signals = AsyncMock()  # WS-L: distilled stamps a source → log_signals branch

        service.metrics_publisher = Mock()
        service.metrics_publisher.publish_validation_metrics = AsyncMock()
        service.metrics_publisher.publish_node_metrics = AsyncMock()  # WS-L M1.6

        await service.validate_tool_call(sample_request)
        await _drain_bg()  # WS-L: let the off-path log_signals / log_decision task finish

        # Verify the audit dual-write was called. Metrics publishing was
        # intentionally removed from _handle_allow/_handle_deny (2025-12-02 commit,
        # see validation_service.py:241) — metrics now publish from agents after
        # actual tool execution, not during validation.
        #
        # WS-L: the LIVE distilled node stamps a real Source and emits a Signal on
        # this all-ALLOW request, so `signals` is non-empty and the ALLOW audit
        # dual-write takes the `log_signals` branch (§9.1) — NOT the empty-signals
        # `log_decision` fallback the bare-mock validators used to hit. The audit
        # write still happens; assert on the branch that actually fires now.
        assert (
            service.audit_logger.log_signals.await_count == 1
            or service.audit_logger.log_decision.await_count == 1
        )


@pytest.mark.asyncio
async def test_audit_called_on_deny(mock_session, sample_request):
    """Test that audit log is called on DENY (metrics removed 2025-12-02)"""
    from app.services.validation_service import ValidationService
    
    with patch.object(ValidationService, '__init__', lambda self: None):
        service = ValidationService()
        
        # Setup mocked dependencies
        service.session_manager = Mock()
        service.session_manager.get_or_create_session = AsyncMock(return_value=mock_session)
        service.session_manager.update_trust_score_deny = AsyncMock(return_value=mock_session)
        
        # Trust checker denies
        service.trust_checker = Mock()
        service.trust_checker.check = AsyncMock(return_value=ValidationResult(
            decision="DENY",
            reason="Trust too low",
            should_deny=True,
            violation_type="LOW_TRUST"
        ))
        
        service.audit_logger = Mock()
        service.audit_logger.log_decision = AsyncMock()
        
        service.metrics_publisher = Mock()
        service.metrics_publisher.publish_validation_metrics = AsyncMock()
        
        await service.validate_tool_call(sample_request)

        # Verify audit log was called. See note above re: metrics removal.
        service.audit_logger.log_decision.assert_called_once()


# ============================================================
# Workstream 19 / LLD 19 §12.3 — ML Classifier Pipeline Tests (T-PIPE-01..05)
# ============================================================
#
# These verify the ML classifier's interaction with the pipeline + signal
# collection. NOTE: the real pipeline is sequential with short-circuit-on-DENY
# (not the parallel asyncio.gather the LLD §3.1 diagram shows). ML is slotted
# AFTER sigma (validation_service STEP 3.5), so sigma DENYs short-circuit
# before ML runs. The deny-overrides COMBINER internals are tested separately
# in test_combiner.py; here we assert the end-to-end pipeline outcome + which
# signals get collected.

from app.combiners import Source


def _allow(source: str) -> ValidationResult:
    """A stamped ALLOW result for a mocked validator."""
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


def _pipeline_service(mock_session):
    """Build a ValidationService with every validator mocked to ALLOW (and
    properly source-stamped so to_signal() works). Individual tests override
    sigma_engine.match_rules / ml_classifier.validate to inject behavior."""
    from app.services.validation_service import ValidationService

    with patch.object(ValidationService, "__init__", lambda self: None):
        service = ValidationService()

    service.session_manager = Mock()
    service.session_manager.get_or_create_session = AsyncMock(return_value=mock_session)

    service.trust_checker = Mock()
    service.trust_checker.check = AsyncMock(return_value=_allow(Source.SENTRA_TRUST))

    service.policy_engine = Mock()
    service.policy_engine.validate = AsyncMock(return_value=_allow(Source.SENTRA_POLICY))
    service.policy_engine.get_agent_policy = AsyncMock(return_value={"rate_limit": 100})

    service.cross_agent_validator = Mock()
    service.cross_agent_validator.validate = AsyncMock(return_value=_allow(Source.SENTRA_CROSS_AGENT))

    service.sigma_engine = Mock()
    service.sigma_engine.match_rules = AsyncMock(return_value=_allow(Source.SENTRA_SIGMA))

    service.ml_classifier = Mock()
    service.ml_classifier.validate = AsyncMock(
        return_value=ValidationResult.abstain("ml_classifier disabled")
    )

    service.context_validator = Mock()
    service.context_validator.validate_sequence = AsyncMock(return_value=_allow(Source.SENTRA_CONTEXT))

    service.abuse_detector = Mock()
    service.abuse_detector.check_rate_limit = AsyncMock(return_value=_allow(Source.SENTRA_ABUSE))

    return service


def _sources(signals) -> list:
    return [s.source for s in signals]


@pytest.mark.asyncio
async def test_t_pipe_01_ml_signal_participates(mock_session, sample_request):
    """ML emits a signal that lands in the collected signals list when it votes."""
    service = _pipeline_service(mock_session)
    ml_allow = _allow(Source.SENTRA_ML_CLASSIFIER)
    ml_allow.confidence = 0.95
    service.ml_classifier.validate = AsyncMock(return_value=ml_allow)

    result, signals = await service._run_validation_pipeline(sample_request, mock_session)

    assert result.decision == "ALLOW"
    assert Source.SENTRA_ML_CLASSIFIER in _sources(signals)


@pytest.mark.asyncio
async def test_t_pipe_02_ml_abstain_emits_no_signal(mock_session, sample_request):
    """ML ABSTAIN → no ml_classifier signal; pipeline still reaches ALLOW."""
    service = _pipeline_service(mock_session)
    # default mock already returns abstain
    result, signals = await service._run_validation_pipeline(sample_request, mock_session)

    assert result.decision == "ALLOW"
    assert Source.SENTRA_ML_CLASSIFIER not in _sources(signals)
    # The deterministic validators still emitted their signals.
    assert Source.SENTRA_SIGMA in _sources(signals)


@pytest.mark.asyncio
async def test_t_pipe_03_ml_deny_sigma_allow_combined_deny(mock_session, sample_request):
    """ML DENY while sigma ALLOWs → pipeline DENY, ml_classifier is the source."""
    service = _pipeline_service(mock_session)
    service.sigma_engine.match_rules = AsyncMock(return_value=_allow(Source.SENTRA_SIGMA))
    service.ml_classifier.validate = AsyncMock(
        return_value=_deny(Source.SENTRA_ML_CLASSIFIER, "PROMPT_INJECTION")
    )

    result, signals = await service._run_validation_pipeline(sample_request, mock_session)

    assert result.should_deny
    assert result.threat_type == "PROMPT_INJECTION"
    assert Source.SENTRA_ML_CLASSIFIER in _sources(signals)
    # Sigma ran first and ALLOWed, so its signal is present too.
    assert Source.SENTRA_SIGMA in _sources(signals)


@pytest.mark.asyncio
async def test_t_pipe_04_sigma_deny_short_circuits_before_ml(mock_session, sample_request):
    """Sigma DENY short-circuits → combined DENY (sigma); ML never invoked.

    Same end-state as the LLD's "ML ALLOW + sigma DENY → DENY" deny-overrides
    case, achieved more cheaply: the ~600ms ML call is skipped entirely when a
    ~50ms sigma rule already caught the threat."""
    service = _pipeline_service(mock_session)
    service.sigma_engine.match_rules = AsyncMock(return_value=_deny(Source.SENTRA_SIGMA, "PII_EXPOSURE"))

    result, signals = await service._run_validation_pipeline(sample_request, mock_session)

    assert result.should_deny
    assert result.threat_type == "PII_EXPOSURE"
    service.ml_classifier.validate.assert_not_called()  # ML cost avoided
    assert Source.SENTRA_ML_CLASSIFIER not in _sources(signals)


@pytest.mark.asyncio
async def test_t_pipe_ml_deny_now_enforces(mock_session, sample_request):
    """T-ML-ENFORCE (WS-C / ADR-030, NO-FLAG): the ML shadow mode is REMOVED —
    a live ML DENY now DECIDES the verdict.

    This is the ONE deliberate verdict change vs the old shadow contract (which
    let an ML DENY fall through to ALLOW). The DAG's tier-1 ML node stamps
    enforce=True on every concrete verdict, so a tier-0-all-ALLOW request with an
    ML DENY is now blocked with winning_source=sentra.ml_classifier. It FAILS if
    the enforce wrapper regresses to advisory."""
    service = _pipeline_service(mock_session)
    service.ml_classifier.validate = AsyncMock(
        return_value=_deny(Source.SENTRA_ML_CLASSIFIER, "PROMPT_INJECTION")
    )

    result, signals = await service._run_validation_pipeline(sample_request, mock_session)

    # ML now ENFORCES: the verdict is DENY (was ALLOW under the removed shadow mode).
    assert result.should_deny is True
    assert result.decision == "DENY"
    assert result.source == Source.SENTRA_ML_CLASSIFIER
    # ML signal is recorded and it is the deciding source.
    assert Source.SENTRA_ML_CLASSIFIER in _sources(signals)
    ml_signal = next(s for s in signals if s.source == Source.SENTRA_ML_CLASSIFIER)
    assert ml_signal.decision == "DENY"
    # Every tier-0 node ran and ALLOWed before the ML node was reached.
    assert Source.SENTRA_CONTEXT in _sources(signals)
    assert Source.SENTRA_ABUSE in _sources(signals)


@pytest.mark.asyncio
async def test_t_pipe_05_both_deny_sigma_is_decision(mock_session, sample_request):
    """When both sigma and ML would DENY, sigma runs first and is the decision;
    ML is not invoked (consistent with priority: sigma is higher-priority and
    its deterministic reason is preferred for audit — LLD 19 §6.1)."""
    service = _pipeline_service(mock_session)
    service.sigma_engine.match_rules = AsyncMock(return_value=_deny(Source.SENTRA_SIGMA, "DATA_THEFT"))
    service.ml_classifier.validate = AsyncMock(
        return_value=_deny(Source.SENTRA_ML_CLASSIFIER, "DATA_THEFT")
    )

    result, signals = await service._run_validation_pipeline(sample_request, mock_session)

    assert result.should_deny
    assert result.source == Source.SENTRA_SIGMA
    service.ml_classifier.validate.assert_not_called()
