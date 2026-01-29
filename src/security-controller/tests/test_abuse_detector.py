"""
Unit Tests for Abuse Detector

Tests rate limiting functionality.
Coverage target: >80%
"""
import pytest
import time
from app.validators.abuse_detector import AbuseDetector
from app.api.models import ValidationRequest


@pytest.fixture
def abuse_detector():
    """Create AbuseDetector instance"""
    return AbuseDetector()


@pytest.fixture
def sample_policy():
    """Create sample policy with rate limit"""
    return {
        "policy_id": "pol-test-001",
        "agent_id": "test-agent",
        "max_calls_per_minute": 10,
    }


@pytest.mark.asyncio
async def test_within_limit_returns_pass(abuse_detector, sample_policy):
    """Test: Within limit returns PASS"""
    current_minute = int(time.time()) // 60

    session = {
        "session_id": "sess-test-789",
        "abuse_counters": {"calls_this_minute": 5, "last_minute_reset": current_minute},
    }

    result = await abuse_detector.check_rate_limit(session, sample_policy)

    assert result.decision == "ALLOW"
    assert result.should_deny is False
    # Counter should be incremented
    assert session["abuse_counters"]["calls_this_minute"] == 6


@pytest.mark.asyncio
async def test_11th_request_in_same_minute_returns_deny(abuse_detector, sample_policy):
    """Test: 11th request in same minute (limit=10) returns DENY"""
    current_minute = int(time.time()) // 60

    session = {
        "session_id": "sess-test-789",
        "abuse_counters": {"calls_this_minute": 10, "last_minute_reset": current_minute},
    }

    result = await abuse_detector.check_rate_limit(session, sample_policy)

    assert result.decision == "DENY"
    assert result.should_deny is True
    assert result.violation_type == "RATE_LIMIT_EXCEEDED"
    assert "rate limit exceeded" in result.reason.lower()
    assert result.penalty == -10


@pytest.mark.asyncio
async def test_counter_resets_after_minute_boundary(abuse_detector, sample_policy):
    """Test: Counter resets after minute boundary"""
    current_minute = int(time.time()) // 60
    previous_minute = current_minute - 1

    # Session from previous minute with 10 calls
    session = {
        "session_id": "sess-test-789",
        "abuse_counters": {
            "calls_this_minute": 10,
            "last_minute_reset": previous_minute,
        },
    }

    result = await abuse_detector.check_rate_limit(session, sample_policy)

    # Should pass because counter reset to 1
    assert result.decision == "ALLOW"
    assert result.should_deny is False
    assert session["abuse_counters"]["calls_this_minute"] == 1
    assert session["abuse_counters"]["last_minute_reset"] == current_minute


@pytest.mark.asyncio
async def test_different_sessions_have_independent_counters(
    abuse_detector, sample_policy
):
    """Test: Different sessions have independent counters"""
    current_minute = int(time.time()) // 60

    session1 = {
        "session_id": "sess-1",
        "abuse_counters": {"calls_this_minute": 5, "last_minute_reset": current_minute},
    }

    session2 = {
        "session_id": "sess-2",
        "abuse_counters": {"calls_this_minute": 8, "last_minute_reset": current_minute},
    }

    # Check session1
    result1 = await abuse_detector.check_rate_limit(session1, sample_policy)
    assert result1.decision == "ALLOW"
    assert session1["abuse_counters"]["calls_this_minute"] == 6

    # Check session2
    result2 = await abuse_detector.check_rate_limit(session2, sample_policy)
    assert result2.decision == "ALLOW"
    assert session2["abuse_counters"]["calls_this_minute"] == 9

    # Counters are independent
    assert session1["abuse_counters"]["calls_this_minute"] != session2["abuse_counters"][
        "calls_this_minute"
    ]


@pytest.mark.asyncio
async def test_missing_abuse_counters_initializes_to_1(abuse_detector, sample_policy):
    """Test: Missing abuse_counters field initializes to 1"""
    session = {"session_id": "sess-test-789"}  # No abuse_counters

    result = await abuse_detector.check_rate_limit(session, sample_policy)

    assert result.decision == "ALLOW"
    assert session["abuse_counters"]["calls_this_minute"] == 1


@pytest.mark.asyncio
async def test_empty_abuse_counters_initializes_to_1(abuse_detector, sample_policy):
    """Test: Empty abuse_counters dict initializes to 1"""
    session = {"session_id": "sess-test-789", "abuse_counters": {}}

    result = await abuse_detector.check_rate_limit(session, sample_policy)

    assert result.decision == "ALLOW"
    assert session["abuse_counters"]["calls_this_minute"] == 1


@pytest.mark.asyncio
async def test_exactly_at_limit_passes(abuse_detector, sample_policy):
    """Test: Exactly at limit (10th request) passes"""
    current_minute = int(time.time()) // 60

    session = {
        "session_id": "sess-test-789",
        "abuse_counters": {"calls_this_minute": 9, "last_minute_reset": current_minute},
    }

    result = await abuse_detector.check_rate_limit(session, sample_policy)

    assert result.decision == "ALLOW"
    assert session["abuse_counters"]["calls_this_minute"] == 10


@pytest.mark.asyncio
async def test_one_over_limit_denies(abuse_detector, sample_policy):
    """Test: One over limit (11th request) denies"""
    current_minute = int(time.time()) // 60

    session = {
        "session_id": "sess-test-789",
        "abuse_counters": {"calls_this_minute": 10, "last_minute_reset": current_minute},
    }

    result = await abuse_detector.check_rate_limit(session, sample_policy)

    assert result.decision == "DENY"


@pytest.mark.asyncio
async def test_high_rate_limit_policy(abuse_detector):
    """Test: High rate limit policy (100 calls/min)"""
    high_limit_policy = {
        "policy_id": "pol-high-limit",
        "agent_id": "test-agent",
        "max_calls_per_minute": 100,
    }

    current_minute = int(time.time()) // 60

    session = {
        "session_id": "sess-test-789",
        "abuse_counters": {"calls_this_minute": 99, "last_minute_reset": current_minute},
    }

    # 100th request should pass
    result = await abuse_detector.check_rate_limit(session, high_limit_policy)
    assert result.decision == "ALLOW"
    assert session["abuse_counters"]["calls_this_minute"] == 100

    # 101st request should deny
    result = await abuse_detector.check_rate_limit(session, high_limit_policy)
    assert result.decision == "DENY"


@pytest.mark.asyncio
async def test_missing_max_calls_per_minute_uses_default(abuse_detector):
    """Test: Missing max_calls_per_minute uses default (100)"""
    policy_no_limit = {"policy_id": "pol-no-limit", "agent_id": "test-agent"}

    current_minute = int(time.time()) // 60

    session = {
        "session_id": "sess-test-789",
        "abuse_counters": {"calls_this_minute": 99, "last_minute_reset": current_minute},
    }

    result = await abuse_detector.check_rate_limit(session, policy_no_limit)
    assert result.decision == "ALLOW"


@pytest.mark.asyncio
async def test_error_handling_returns_deny(abuse_detector, sample_policy):
    """Test: Error handling returns DENY on exceptions (fail-secure)"""
    # Pass invalid session (None) to trigger exception
    session = None

    result = await abuse_detector.check_rate_limit(session, sample_policy)

    assert result.decision == "DENY"
    assert result.should_deny is True
    assert result.violation_type == "SYSTEM_ERROR"


@pytest.mark.asyncio
async def test_rapid_requests_in_same_minute(abuse_detector, sample_policy):
    """Test: Rapid requests in same minute increment counter correctly"""
    current_minute = int(time.time()) // 60

    session = {
        "session_id": "sess-test-789",
        "abuse_counters": {"calls_this_minute": 0, "last_minute_reset": current_minute},
    }

    # Make 10 rapid requests
    for i in range(10):
        result = await abuse_detector.check_rate_limit(session, sample_policy)
        assert result.decision == "ALLOW"
        assert session["abuse_counters"]["calls_this_minute"] == i + 1

    # 11th request should deny
    result = await abuse_detector.check_rate_limit(session, sample_policy)
    assert result.decision == "DENY"


@pytest.mark.asyncio
async def test_minute_boundary_edge_case(abuse_detector, sample_policy):
    """Test: Minute boundary edge case - counter resets exactly at boundary"""
    current_minute = int(time.time()) // 60

    # Session at limit in previous minute
    session = {
        "session_id": "sess-test-789",
        "abuse_counters": {
            "calls_this_minute": 10,
            "last_minute_reset": current_minute - 1,
        },
    }

    # New minute - should reset and allow
    result = await abuse_detector.check_rate_limit(session, sample_policy)
    assert result.decision == "ALLOW"
    assert session["abuse_counters"]["calls_this_minute"] == 1
    assert session["abuse_counters"]["last_minute_reset"] == current_minute
