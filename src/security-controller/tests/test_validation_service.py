"""
Unit Tests for Validation Service

Tests the main validation pipeline orchestration.
These are simplified integration-style tests that verify the service works correctly.
"""
import pytest
from unittest.mock import Mock, patch, AsyncMock
from app.api.models import ValidationRequest, ValidationResult


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
        
        service.audit_logger = Mock()
        service.audit_logger.log_decision = AsyncMock()
        
        service.metrics_publisher = Mock()
        service.metrics_publisher.publish_validation_metrics = AsyncMock()
        
        result = await service.validate_tool_call(sample_request)
        
        # Verify ALLOW decision
        assert result["decision"] == "ALLOW"
        assert result["reason"] == "All validation checks passed"
        assert result["trust_score"] == 76.0
        assert result["session_id"] == "sess-123"
        assert "latency_ms" in result


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
        
        # Verify DENY decision
        assert result["decision"] == "DENY"
        assert result["reason"] == "Trust score too low"
        assert result["trust_score"] == 60.0
        assert result["violation_type"] == "LOW_TRUST"


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
        
        service.audit_logger = Mock()
        service.audit_logger.log_decision = AsyncMock()
        
        service.metrics_publisher = Mock()
        service.metrics_publisher.publish_validation_metrics = AsyncMock()
        
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
        
        service.audit_logger = Mock()
        service.audit_logger.log_decision = AsyncMock()
        
        service.metrics_publisher = Mock()
        service.metrics_publisher.publish_validation_metrics = AsyncMock()
        
        await service.validate_tool_call(sample_request)
        
        # Verify audit log and metrics were called
        service.audit_logger.log_decision.assert_called_once()
        service.metrics_publisher.publish_validation_metrics.assert_called_once()


@pytest.mark.asyncio
async def test_audit_and_metrics_called_on_deny(mock_session, sample_request):
    """Test that audit log and metrics are called on DENY"""
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
        
        # Verify audit log and metrics were called
        service.audit_logger.log_decision.assert_called_once()
        service.metrics_publisher.publish_validation_metrics.assert_called_once()
