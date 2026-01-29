"""
Services package for dashboard API clients.

The dashboard only communicates with the Security Controller API.
Security Controller handles all interactions with CloudWatch and DynamoDB.
"""
from .security_controller_client import security_controller_client

__all__ = [
    'security_controller_client',
]
