"""
Custom exceptions for multi-agent workflows

Related: BUG-001 - Multi-Agent Status Propagation Issue
"""


class ToolDeniedError(Exception):
    """
    Raised when a tool call is denied by security validation or downstream agent.

    This exception propagates child agent denials to parent agents in multi-agent
    workflows, ensuring correct HTTP status codes are returned to users.

    Attributes:
        status_code: HTTP status code (403, 429, etc.)
        detail: Error details dict
        agent_id: Agent that denied the request (for multi-agent tracking)

    Example:
        >>> raise ToolDeniedError(
        ...     message="Payment Agent denied refund request",
        ...     status_code=403,
        ...     detail={"reason": "Exceeds max_refund_amount"},
        ...     agent_id="payment-agent"
        ... )
    """

    def __init__(
        self,
        message: str,
        status_code: int = 403,
        detail: dict = None,
        agent_id: str = None
    ):
        """
        Initialize ToolDeniedError

        Args:
            message: Human-readable error message
            status_code: HTTP status code to propagate (default: 403)
            detail: Additional error context
            agent_id: Identifier of agent that denied request
        """
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail or {}
        self.agent_id = agent_id

    def __str__(self):
        """String representation including agent context"""
        if self.agent_id:
            return f"[{self.agent_id}] {super().__str__()}"
        return super().__str__()
