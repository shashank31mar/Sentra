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
