"""Per-request context via ``contextvars`` (LLD 23 §3.3, §4.1).

A guarded tool needs ``session_id`` / ``user_input`` / ``request_id`` to build a
validation request, but we don't want those polluting tool signatures. They flow
implicitly through a ``contextvars.ContextVar`` set by ``guard.session(...)``.

``contextvars`` propagate correctly across ``await`` (and into ``asyncio.to_thread``
via ``contextvars.copy_context``), so the same mechanism works for sync and async
tools.

Nesting is **inner-wins**: an inner ``session()`` shadows the outer for its
duration and the outer is restored on exit, using the ``Token`` returned by
``ContextVar.set`` — standard, exception-safe contextvar discipline.
"""
from __future__ import annotations

import contextvars
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class RequestContext:
    """The ambient context for the currently-executing guarded tool call."""

    session_id: str
    user_input: str
    # request_id may be fixed for the whole session (explicit) or None, in which
    # case the guard mints a fresh uuid per tool call.
    request_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None


_CURRENT: "contextvars.ContextVar[Optional[RequestContext]]" = contextvars.ContextVar(
    "aegion_guard_request_context", default=None
)


def current() -> Optional[RequestContext]:
    """Return the active ``RequestContext``, or ``None`` outside a session."""
    return _CURRENT.get()


def require_current() -> RequestContext:
    """Return the active context or raise a clear, actionable error.

    Raised when a guarded tool is invoked outside ``guard.session(...)`` — the
    single most common integration mistake.
    """
    ctx = _CURRENT.get()
    if ctx is None:
        raise RuntimeError(
            "No active Aegion session. A @guard.tool function must be called "
            "inside a `with guard.session(session_id=..., user_input=...):` "
            "block so the SDK can attach the session to the validation request."
        )
    return ctx


def set_current(ctx: RequestContext) -> "contextvars.Token":
    """Bind ``ctx`` as the active context; return the restore ``Token``."""
    return _CURRENT.set(ctx)


def reset_current(token: "contextvars.Token") -> None:
    """Restore the context that was active before the matching ``set_current``."""
    _CURRENT.reset(token)
