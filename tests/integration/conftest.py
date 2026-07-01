"""
Integration Test Configuration
Sentra MVP - Workstream 7

Shared fixtures and configuration for integration tests.
"""

import os
import pytest


def pytest_configure(config):
    """Configure pytest markers"""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "requires_services: marks tests that require running services"
    )
    config.addinivalue_line(
        "markers", "integration: marks integration tests (run with '-m integration')"
    )


@pytest.fixture(scope="session")
def api_headers():
    """Common headers for control-plane (operator) API requests against the
    deployed controller (WS-K K8). The data-plane validate path additionally needs
    the gateway API key (X-Api-Key) — provided via SENTRA_API_KEY when present.

    Operator identity: the deployed front door verifies an ALB-OIDC operator JWT;
    against a locally-run controller (no ALB) the legacy X-Operator-Email shim is
    honored. Tests assert on STATUS CODES + reason codes, so both work."""
    headers = {
        "Content-Type": "application/json",
        "X-Operator-Email": os.environ.get("SENTRA_OPERATOR_EMAIL", "test-integration@sentra.com"),
    }
    bearer = os.environ.get("SENTRA_OPERATOR_TOKEN")
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    api_key = os.environ.get("SENTRA_API_KEY")
    if api_key:
        headers["X-Api-Key"] = api_key
    return headers


@pytest.fixture(scope="session")
def service_urls():
    """Return service URLs from environment or defaults"""
    return {
        "customer_query_agent": os.environ.get(
            'CUSTOMER_QUERY_AGENT_URL',
            'http://localhost:8080'
        ),
        "payment_agent": os.environ.get(
            'PAYMENT_AGENT_URL',
            'http://localhost:8081'
        ),
        "security_controller": os.environ.get(
            'SECURITY_CONTROLLER_URL',
            'http://localhost:8082'
        )
    }


@pytest.fixture(scope="session")
def aws_config():
    """Return AWS configuration"""
    return {
        "region": os.environ.get('AWS_REGION', 'us-east-1'),
        "profile": os.environ.get('AWS_PROFILE', 'sentra')
    }
