"""
Import Smoke Tests

Catches missing module imports that would cause runtime failures.
These tests ensure all modules can be imported successfully.
"""
import pytest


def test_main_app_imports():
    """Test that main.py can be imported (triggers all app imports)"""
    try:
        import app.main
        assert app.main.app is not None
    except ImportError as e:
        pytest.fail(f"Failed to import app.main: {e}")


def test_services_package_imports():
    """Test that services package can be imported"""
    try:
        from app import services
        # Verify expected services are available
        assert hasattr(services, 'ValidationService')
        assert hasattr(services, 'HealthService')
        assert hasattr(services, 'LogsService')
        assert hasattr(services, 'MetricsService')
    except ImportError as e:
        pytest.fail(f"Failed to import app.services: {e}")


def test_validators_package_imports():
    """Test that all validators can be imported"""
    try:
        from app.validators import policy_engine
        from app.validators import sigma_engine
        from app.validators import trust_checker
        from app.validators import context_validator
        from app.validators import abuse_detector
    except ImportError as e:
        pytest.fail(f"Failed to import validators: {e}")


def test_utils_package_imports():
    """Test that all utils can be imported"""
    try:
        from app.utils import session_manager
        from app.utils import audit_logger
        from app.utils import metrics_publisher
        from app.utils import rollback_coordinator
    except ImportError as e:
        pytest.fail(f"Failed to import utils: {e}")


def test_api_routes_imports():
    """Test that API routes can be imported"""
    try:
        from app.api import routes
        from app.api import models
        assert routes.router is not None
    except ImportError as e:
        pytest.fail(f"Failed to import API routes: {e}")


def test_no_circular_imports():
    """Test that importing main doesn't cause circular import errors"""
    try:
        # This will fail if there are circular imports
        import app.main
        import app.services
        import app.validators
        import app.utils
    except ImportError as e:
        pytest.fail(f"Circular import detected: {e}")
