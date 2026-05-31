"""Unit tests for cross-cloud dependency validation in ContextValidator.

Workstream 15 Task 2.5 — acceptance criteria:
  - Tool call denied when prerequisite is absent.
  - Tool call allowed when prerequisite recorded within window.
  - Prerequisite recorded outside window → denied.

These tests stub out the policy_engine; we verify only the cross-cloud logic
inside context_validator._check_cross_cloud_dependencies. Live policy + DDB +
S3 integration is covered in tests/integration/test_cross_cloud_scenarios.py
(see Workstream 15 Milestone 6).
"""
import time
from unittest.mock import AsyncMock

import pytest

from app.api.models import ValidationRequest
from app.validators.context_validator import ContextValidator


def _request(tool_name: str = "process_refund", agent_id: str = "sentra-mvp-customer-service-agent") -> ValidationRequest:
    return ValidationRequest(
        request_id="req-test-1",
        session_id="sess-test-1",
        agent_id=agent_id,
        tool_name=tool_name,
        tool_params={"order_id": "ORD-1", "amount": 100},
        user_input="Refund for cracked eggs",
        timestamp="2026-05-20T00:00:00Z",
        operation_type="WRITE",
    )


def _policy_with_dep(max_age_seconds: int = 300) -> dict:
    """Policy that requires azure-verification-agent.verify_image_authenticity
    before process_refund."""
    return {
        "agent_id": "sentra-mvp-customer-service-agent",
        "platform": "bedrock",
        "cloud_region": "us-east-1",
        "allowed_tools": ["process_refund", "invoke_agent"],
        "cross_cloud_dependencies": [
            {
                "target_agent": "azure-verification-agent",
                "target_tool": "verify_image_authenticity",
                "required_before": ["process_refund"],
                "max_age_seconds": max_age_seconds,
            }
        ],
    }


def _mock_engine(policy: dict):
    engine = AsyncMock()
    engine.get_agent_policy = AsyncMock(return_value=policy)
    return engine


def _validator_with_engine(policy: dict) -> ContextValidator:
    # Force empty single-cloud requirements so we test only the cross-cloud path
    v = ContextValidator(config_path="/nonexistent/path-to-empty-config.yaml",
                         policy_engine=_mock_engine(policy))
    return v


@pytest.mark.asyncio
async def test_cross_cloud_dependency_missing_denies():
    """Prerequisite absent → DENY with CROSS_CLOUD_SEQUENCE_VIOLATION."""
    validator = _validator_with_engine(_policy_with_dep(max_age_seconds=300))
    session = {"tool_history": []}  # nothing in history
    request = _request()

    result = await validator.validate_sequence(session, request)

    assert result.should_deny is True
    assert result.violation_type == "CROSS_CLOUD_SEQUENCE_VIOLATION"
    assert "cross_cloud_dependency_not_met" in result.reason
    assert "azure-verification-agent" in result.reason
    assert "verify_image_authenticity" in result.reason


@pytest.mark.asyncio
async def test_cross_cloud_dependency_within_window_allows():
    """Prerequisite recorded within max_age_seconds → ALLOW."""
    validator = _validator_with_engine(_policy_with_dep(max_age_seconds=300))
    # Prerequisite called 60 seconds ago
    sixty_seconds_ago_ms = int(time.time() * 1000) - 60_000
    session = {
        "tool_history": [
            {
                "tool_name": "verify_image_authenticity",
                "agent_id": "azure-verification-agent",
                "timestamp": sixty_seconds_ago_ms,
            }
        ]
    }
    request = _request()

    result = await validator.validate_sequence(session, request)

    assert result.should_deny is False
    assert result.decision == "ALLOW"


@pytest.mark.asyncio
async def test_cross_cloud_dependency_outside_window_denies():
    """Prerequisite recorded outside max_age_seconds → DENY."""
    validator = _validator_with_engine(_policy_with_dep(max_age_seconds=60))
    # Prerequisite called 5 minutes ago (300s); window is only 60s
    five_min_ago_ms = int(time.time() * 1000) - 300_000
    session = {
        "tool_history": [
            {
                "tool_name": "verify_image_authenticity",
                "agent_id": "azure-verification-agent",
                "timestamp": five_min_ago_ms,
            }
        ]
    }
    request = _request()

    result = await validator.validate_sequence(session, request)

    assert result.should_deny is True
    assert result.violation_type == "CROSS_CLOUD_SEQUENCE_VIOLATION"


@pytest.mark.asyncio
async def test_cross_cloud_wrong_agent_denies():
    """Prerequisite tool called by a DIFFERENT agent → DENY.

    This is the cross-cloud provenance check: even if some agent called
    verify_image_authenticity, the policy specifically requires
    azure-verification-agent. Other agents don't satisfy the dep.
    """
    validator = _validator_with_engine(_policy_with_dep(max_age_seconds=300))
    now_ms = int(time.time() * 1000)
    session = {
        "tool_history": [
            {
                "tool_name": "verify_image_authenticity",
                "agent_id": "some-other-agent",  # wrong agent
                "timestamp": now_ms - 10_000,
            }
        ]
    }
    request = _request()

    result = await validator.validate_sequence(session, request)

    assert result.should_deny is True
    assert "azure-verification-agent" in result.reason


@pytest.mark.asyncio
async def test_no_cross_cloud_deps_allows():
    """When the policy has no cross_cloud_dependencies, ALLOW (no-op)."""
    policy = {
        "agent_id": "sentra-mvp-customer-service-agent",
        "platform": "bedrock",
        "cloud_region": "us-east-1",
        "allowed_tools": ["process_refund"],
        "cross_cloud_dependencies": [],
    }
    validator = _validator_with_engine(policy)
    session = {"tool_history": []}

    result = await validator.validate_sequence(session, _request())

    assert result.should_deny is False
    assert result.decision == "ALLOW"


@pytest.mark.asyncio
async def test_tool_not_in_required_before_allows():
    """Cross-cloud dep applies only to tools in `required_before`. Other tools pass."""
    validator = _validator_with_engine(_policy_with_dep(max_age_seconds=300))
    session = {"tool_history": []}
    # query_customers is NOT in required_before — should not trigger the dep
    request = _request(tool_name="query_customers")

    result = await validator.validate_sequence(session, request)

    assert result.should_deny is False


@pytest.mark.asyncio
async def test_no_policy_engine_skips_cross_cloud_check():
    """When no policy_engine is injected, cross-cloud checks are silently skipped
    (degrades to single-cloud behavior). This is the legacy compatibility path.
    """
    v = ContextValidator(config_path="/nonexistent.yaml", policy_engine=None)
    session = {"tool_history": []}

    result = await v.validate_sequence(session, _request())

    # Should ALLOW because no single-cloud reqs and no cross-cloud engine to check
    assert result.should_deny is False
