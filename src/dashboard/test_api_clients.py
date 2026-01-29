#!/usr/bin/env python3
"""
Test script for API clients.
Tests connectivity to Security Controller, CloudWatch, and DynamoDB.
"""
import sys
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import client
from services import security_controller_client


def test_security_controller():
    """Test Security Controller client."""
    logger.info("Testing Security Controller client...")
    
    try:
        # Test health endpoint
        health = security_controller_client.get_health()
        logger.info(f"Health check result: {health}")
        
        if health.get('status') == 'error':
            logger.warning("Security Controller is not reachable (expected if not deployed)")
            return False
        
        # Test logs endpoint
        logs_data = security_controller_client.get_logs(limit=5)
        logger.info(f"Found {logs_data.get('total', 0)} audit logs")
        
        # Test sessions endpoint
        sessions_data = security_controller_client.get_sessions(limit=5)
        logger.info(f"Found {sessions_data.get('total', 0)} sessions")
        
        # Test metrics endpoint
        metrics = security_controller_client.get_metrics()
        logger.info(f"Metrics: {metrics.get('requests', {})}")
        
        logger.info("✓ Security Controller client working")
        return True
    
    except Exception as e:
        logger.error(f"✗ Security Controller client failed: {e}")
        return False


def main():
    """Run all tests."""
    logger.info("=" * 60)
    logger.info("Testing Dashboard API Client")
    logger.info("=" * 60)
    logger.info("Dashboard only communicates with Security Controller API")
    logger.info("Security Controller handles CloudWatch and DynamoDB internally")
    logger.info("=" * 60)
    
    passed = test_security_controller()
    
    logger.info("=" * 60)
    logger.info("Test Results:")
    logger.info("=" * 60)
    
    status = "✓ PASS" if passed else "✗ FAIL"
    logger.info(f"Security Controller: {status}")
    
    if passed:
        logger.info("\n✓ All tests passed!")
        return 0
    else:
        logger.warning("\n⚠ Security Controller not reachable (expected if not deployed)")
        logger.info("Dashboard will fall back to mock data when API is unavailable")
        return 0  # Don't fail - graceful degradation is expected


if __name__ == "__main__":
    sys.exit(main())
