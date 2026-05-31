class ConnectorError(Exception):
    """Base exception for any connector failure."""


class AgentInvocationError(ConnectorError):
    """Raised when invoking the underlying cloud agent fails."""


class ValidationServiceError(ConnectorError):
    """Raised when the Sentra security controller is unreachable or returns an unexpected response."""
