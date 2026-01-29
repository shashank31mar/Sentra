"""
Unit Tests for Trust Checker

Tests trust score validation and quarantine status checks.
Coverage target: >80%
"""
import pytest
from app.validators.trust_checker import TrustChecker
from app.api.models import ValidationRequest


@pytest.fixture
def trust_checker():
    """Create TrustChecker instance"""
    return TrustChecker()


@pytest.fixture
def sample_request():
    """Create sample validation request"""
    return ValidationRequest(
        request_id="req-test-123",
        session_id="sess-test-789",
        agent_id="test-agent",
        tool_name="test_tool",
        tool_params={},
        user_input="test input",
        timestamp="2025-01-18T10:00:00Z",
        operation_type="READ"
    )


@pytest.mark.asyncio
async def test_suspended_session_denies_all_operations(trust_checker, sample_request):
    """Test: Suspended session (trust_score < 10) returns DENY for all operations"""
    # Test READ operation
    session = {
        'session_id': 'sess-test-789',
        'trust_score': 5.0,
        'quarantine_status': 'suspended'
    }
    
    result = await trust_checker.check(session, sample_request)
    
    assert result.decision == "DENY"
    assert result.should_deny is True
    assert result.violation_type == "SESSION_SUSPENDED"
    assert "suspended" in result.reason.lower()
    
    # Test WRITE operation
    sample_request.operation_type = "WRITE"
    result = await trust_checker.check(session, sample_request)
    
    assert result.decision == "DENY"
    assert result.should_deny is True


@pytest.mark.asyncio
async def test_quarantined_session_allows_read(trust_checker, sample_request):
    """Test: Quarantined session (trust_score 10-39) allows READ operations"""
    session = {
        'session_id': 'sess-test-789',
        'trust_score': 30.0,
        'quarantine_status': 'quarantined'
    }
    
    sample_request.operation_type = "READ"
    result = await trust_checker.check(session, sample_request)
    
    assert result.decision == "ALLOW"
    assert result.should_deny is False


@pytest.mark.asyncio
async def test_quarantined_session_denies_write(trust_checker, sample_request):
    """Test: Quarantined session (trust_score 10-39) denies WRITE operations"""
    session = {
        'session_id': 'sess-test-789',
        'trust_score': 30.0,
        'quarantine_status': 'quarantined'
    }
    
    sample_request.operation_type = "WRITE"
    result = await trust_checker.check(session, sample_request)
    
    assert result.decision == "DENY"
    assert result.should_deny is True
    assert result.violation_type == "QUARANTINE_WRITE_BLOCKED"
    assert "write operations blocked" in result.reason.lower()


@pytest.mark.asyncio
async def test_warning_session_allows_all(trust_checker, sample_request):
    """Test: Warning session (trust_score 40-69) allows all operations"""
    session = {
        'session_id': 'sess-test-789',
        'trust_score': 50.0,
        'quarantine_status': 'warning'
    }
    
    # Test READ
    sample_request.operation_type = "READ"
    result = await trust_checker.check(session, sample_request)
    assert result.decision == "ALLOW"
    assert result.should_deny is False
    
    # Test WRITE
    sample_request.operation_type = "WRITE"
    result = await trust_checker.check(session, sample_request)
    assert result.decision == "ALLOW"
    assert result.should_deny is False


@pytest.mark.asyncio
async def test_active_session_allows_all(trust_checker, sample_request):
    """Test: Active session (trust_score >= 70) allows all operations"""
    session = {
        'session_id': 'sess-test-789',
        'trust_score': 80.0,
        'quarantine_status': 'active'
    }
    
    # Test READ
    sample_request.operation_type = "READ"
    result = await trust_checker.check(session, sample_request)
    assert result.decision == "ALLOW"
    assert result.should_deny is False
    
    # Test WRITE
    sample_request.operation_type = "WRITE"
    result = await trust_checker.check(session, sample_request)
    assert result.decision == "ALLOW"
    assert result.should_deny is False


@pytest.mark.asyncio
async def test_edge_case_trust_score_10(trust_checker, sample_request):
    """Test: Trust score exactly 10 (boundary between suspended and quarantined)"""
    session = {
        'session_id': 'sess-test-789',
        'trust_score': 10.0,
        'quarantine_status': 'quarantined'
    }
    
    # Should allow READ
    sample_request.operation_type = "READ"
    result = await trust_checker.check(session, sample_request)
    assert result.decision == "ALLOW"
    
    # Should deny WRITE
    sample_request.operation_type = "WRITE"
    result = await trust_checker.check(session, sample_request)
    assert result.decision == "DENY"


@pytest.mark.asyncio
async def test_edge_case_trust_score_40(trust_checker, sample_request):
    """Test: Trust score exactly 40 (boundary between quarantined and warning)"""
    session = {
        'session_id': 'sess-test-789',
        'trust_score': 40.0,
        'quarantine_status': 'warning'
    }
    
    # Should allow both READ and WRITE
    sample_request.operation_type = "READ"
    result = await trust_checker.check(session, sample_request)
    assert result.decision == "ALLOW"
    
    sample_request.operation_type = "WRITE"
    result = await trust_checker.check(session, sample_request)
    assert result.decision == "ALLOW"


@pytest.mark.asyncio
async def test_edge_case_trust_score_70(trust_checker, sample_request):
    """Test: Trust score exactly 70 (boundary between warning and active)"""
    session = {
        'session_id': 'sess-test-789',
        'trust_score': 70.0,
        'quarantine_status': 'active'
    }
    
    # Should allow all operations
    sample_request.operation_type = "READ"
    result = await trust_checker.check(session, sample_request)
    assert result.decision == "ALLOW"
    
    sample_request.operation_type = "WRITE"
    result = await trust_checker.check(session, sample_request)
    assert result.decision == "ALLOW"


@pytest.mark.asyncio
async def test_missing_session_fields_defaults(trust_checker, sample_request):
    """Test: Missing session fields use safe defaults"""
    session = {
        'session_id': 'sess-test-789'
        # Missing trust_score and quarantine_status
    }
    
    result = await trust_checker.check(session, sample_request)
    
    # Should default to trust_score=100, status=active and allow
    assert result.decision == "ALLOW"
    assert result.should_deny is False


@pytest.mark.asyncio
async def test_error_handling_returns_deny(trust_checker, sample_request):
    """Test: Error handling returns DENY (fail-secure)"""
    # Pass invalid session (None) to trigger exception
    session = None
    
    result = await trust_checker.check(session, sample_request)
    
    assert result.decision == "DENY"
    assert result.should_deny is True
    assert result.violation_type == "SYSTEM_ERROR"
