"""Exception hierarchy for Aegion Guard (LLD 23 §3, §8).

    AegionGuardError
    ├── ConfigError          (missing/invalid config at init — fail fast)
    ├── IdentityError        (the `identity` extra is missing, or a token couldn't be minted)
    ├── ToolDenied           (the controller returned DENY, or fail-secure tripped)
    │   └── UnknownAgentError(controller reports the agent_id is not registered)
    └── SentraUnavailable    (transport failure AND fail_secure=False)

`ToolDenied` is the normal "blocked" signal a caller catches. `SentraUnavailable`
only ever escapes when the integrator has explicitly opted out of fail-secure.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # avoid an import cycle; Decision lives in guard.py
    from .guard import Decision


class AegionGuardError(Exception):
    """Base class for every error raised by the SDK."""


class ConfigError(AegionGuardError, ValueError):
    """Raised at construction time when required configuration is missing.

    Subclasses ``ValueError`` so existing ``except ValueError`` handlers still
    catch it, while ``except AegionGuardError`` catches all SDK errors.
    """


class IdentityError(AegionGuardError):
    """Raised when agent data-plane identity cannot be established or minted.

    Distinct from ``ConfigError`` (static misconfiguration caught at init): this
    covers the runtime/dependency cases — the optional ``identity`` extra
    (``PyJWT[crypto]``) is not installed, or signing a token failed. Surfaced
    distinctly so the integrator gets the ``pip install 'aegion-guard[identity]'``
    hint instead of an opaque ``ImportError``.
    """


class ToolDenied(AegionGuardError):
    """Raised when a guarded tool call must NOT run.

    Covers two cases that are identical from the caller's perspective — the
    call did not execute:
      * the controller returned an authoritative ``DENY``; or
      * validation could not be completed and ``fail_secure`` is on (default),
        so the SDK fails closed (``reason="validation_unavailable"``).
    """

    def __init__(
        self,
        reason: str,
        *,
        threat_type: Optional[str] = None,
        decision: "Optional[Decision]" = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.threat_type = threat_type
        # The full Decision when one exists (real DENY). None on fail-secure
        # where no well-formed decision was received.
        self.decision = decision


class UnknownAgentError(ToolDenied):
    """The controller indicates ``agent_id`` is not registered.

    A subclass of ``ToolDenied`` (it is still a block), surfaced distinctly so
    integrators immediately see the real cause instead of a generic denial.

    NOTE (LLD 23 §12.1 caveat 3): detection is currently best-effort — the
    controller does not yet emit a stable machine code for this case, so the
    SDK matches on the denial ``reason`` text. A dedicated ``UNKNOWN_AGENT``
    ``error_code`` is filed as a WS-21 follow-up; when it lands, switch the
    mapping in ``guard._is_unknown_agent`` to the code.
    """


class SentraUnavailable(AegionGuardError):
    """Raised only when validation fails AND ``fail_secure=False``.

    The integrator has opted out of failing closed, so transport problems
    surface as this error for them to handle (degrade vs. block).
    """

    def __init__(self, message: str, *, cause: Optional[BaseException] = None) -> None:
        super().__init__(message)
        self.cause = cause
