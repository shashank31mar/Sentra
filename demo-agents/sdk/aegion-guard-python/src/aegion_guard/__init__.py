"""Aegion Guard — security validation for AI agent tool calls.

Route every tool call through the AegionAI security controller *before* it runs,
and block on DENY. The integration is a decorator + context manager:

    from aegion_guard import AegionGuard

    guard = AegionGuard(agent_id="acme-payments-agent")

    @guard.tool(operation_type="WRITE")
    def process_refund(account_id: str, amount: float) -> dict:
        return bank.refund(account_id, amount)   # runs ONLY if Sentra ALLOWs

    with guard.session(session_id=sid, user_input=prompt):
        process_refund(account_id="A1", amount=50)   # raises ToolDenied on DENY

Design contract (LLD 23):
- stdlib-only at runtime (vendors into Lambda + Azure Functions unchanged).
- fail-secure by default (transport/garbage/unknown-decision => DENY).
- sync AND async tools (the decorator detects coroutine functions).
"""
from .adapters import from_azure_request, from_bedrock_event
from .config import GuardConfig
from .exceptions import (
    AegionGuardError,
    BadRequest,
    ConfigError,
    IdentityError,
    SentraUnavailable,
    ToolDenied,
    UnknownAgentError,
)
from .guard import AegionGuard, Decision, infer_operation_type

# Identity (signing) helpers live behind the optional `identity` extra. Importing
# the names is safe (lazy crypto/JWT imports inside); using them requires the extra.
from .identity import AgentIdentity, JwtSigner, generate_keypair

# Distribution/import name is `aegion_guard`; the market brand is AegionAI.
# "Sentra" remains the internal control-plane codename.
__version__ = "0.1.0"

# The /v1/validate contract version this SDK targets (LLD 23 §5). Informational
# only: the controller does not advertise a contract version on the response
# today, so there is nothing to actively compare against. Contract drift is
# handled *defensively at parse time*, not by version matching — additive /v1
# fields are tolerated via Decision.raw, and any body that isn't a clean
# ALLOW/DENY fails closed (default-DENY, see guard.AegionGuard._parse_decision).
__contract__ = "v1"

__all__ = [
    "AegionGuard",
    "Decision",
    "GuardConfig",
    "ToolDenied",
    "UnknownAgentError",
    "SentraUnavailable",
    "BadRequest",
    "ConfigError",
    "IdentityError",
    "AegionGuardError",
    "AgentIdentity",
    "JwtSigner",
    "generate_keypair",
    "from_bedrock_event",
    "from_azure_request",
    "infer_operation_type",
    "__version__",
    "__contract__",
]
