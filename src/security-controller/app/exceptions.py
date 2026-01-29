"""
Custom Exception Classes for Security Controller API

Defines HTTP exception classes for policy CRUD operations and general API errors.
Reference: LLD 11 Section 6.1
"""
from typing import Optional, List, Dict, Any
from datetime import datetime


class SecurityControllerException(Exception):
    """Base exception for all Security Controller errors."""
    status_code: int = 500
    error_type: str = "INTERNAL_ERROR"

    def __init__(self, message: str, details: Optional[Any] = None):
        self.message = message
        self.details = details
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to JSON-serializable dict."""
        response = {
            "success": False,
            "error": self.message,
            "error_type": self.error_type,
            "timestamp": datetime.utcnow().isoformat() + 'Z'
        }
        if self.details:
            response["details"] = self.details
        return response


class ValidationException(SecurityControllerException):
    """
    Raised when request validation fails.

    HTTP Status: 400 Bad Request
    Use Case: Invalid schema, missing required fields, invalid policy rules

    Example:
        raise ValidationException(
            "Policy validation failed",
            details=[
                {"field": "allowed_tools[0]", "error": "Tool 'invalid_tool' not found"},
                {"field": "policies[1].rule", "error": "Invalid Python expression"}
            ]
        )
    """
    status_code = 400
    error_type = "VALIDATION_ERROR"


class NotFoundException(SecurityControllerException):
    """
    Raised when a requested resource is not found.

    HTTP Status: 404 Not Found
    Use Case: Policy not found, agent not found, resource doesn't exist

    Example:
        raise NotFoundException(f"Policy {policy_id} not found")
    """
    status_code = 404
    error_type = "NOT_FOUND"


class ConflictException(SecurityControllerException):
    """
    Raised when a resource already exists or conflicts with existing state.

    HTTP Status: 409 Conflict
    Use Case: Policy already exists, duplicate resource creation

    Example:
        raise ConflictException(
            f"Policy {policy_id} already exists",
            details={"existing_version": "1.0.0"}
        )
    """
    status_code = 409
    error_type = "CONFLICT"


class ForbiddenException(SecurityControllerException):
    """
    Raised when an operation is not allowed.

    HTTP Status: 403 Forbidden
    Use Case: Cannot delete system policies, cannot update disabled policies

    Example:
        raise ForbiddenException("Cannot delete system policies")
    """
    status_code = 403
    error_type = "FORBIDDEN"


class UnauthorizedException(SecurityControllerException):
    """
    Raised when authentication or authorization fails.

    HTTP Status: 401 Unauthorized
    Use Case: Missing API key, invalid credentials

    Example:
        raise UnauthorizedException("Missing or invalid API key")
    """
    status_code = 401
    error_type = "UNAUTHORIZED"


class ServiceUnavailableException(SecurityControllerException):
    """
    Raised when a dependent service is unavailable.

    HTTP Status: 503 Service Unavailable
    Use Case: DynamoDB unavailable, S3 unavailable, external service down

    Example:
        raise ServiceUnavailableException("DynamoDB service unavailable")
    """
    status_code = 503
    error_type = "SERVICE_UNAVAILABLE"


class RateLimitException(SecurityControllerException):
    """
    Raised when rate limit is exceeded.

    HTTP Status: 429 Too Many Requests
    Use Case: Too many requests from same source

    Example:
        raise RateLimitException("Rate limit exceeded. Try again later.")
    """
    status_code = 429
    error_type = "RATE_LIMIT_EXCEEDED"
