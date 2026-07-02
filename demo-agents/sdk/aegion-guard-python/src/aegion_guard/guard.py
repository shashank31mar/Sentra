"""The public face of the SDK: ``AegionGuard``, ``@guard.tool``, ``guard.session``.

Decorated-call algorithm (LLD 23 §4.1):
 1. resolve the active session context (or raise a clear error);
 2. build the ``ValidationRequest`` (fresh request_id per call unless pinned);
 3. POST to /v1/validate;
 4. ALLOW -> run the wrapped function; DENY/unknown -> raise ``ToolDenied``;
 5. transport failure -> fail-secure DENY (or ``SentraUnavailable``);
 6. fire the optional ``on_decision`` hook (its own errors are swallowed).

Works for sync and async tools — the decorator inspects the wrapped function and
returns the matching wrapper. The async path runs the blocking client in a worker
thread (``asyncio.to_thread``) so it never blocks the event loop, preserving the
ambient contextvars via ``contextvars.copy_context``.
"""
from __future__ import annotations

import asyncio
import contextvars
import functools
import inspect
import json
import logging
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Iterator, Optional, TypeVar

from . import context as _ctx
from . import redaction as _redaction
from ._time import isoformat_ms_z
from .client import TransportError, ValidateClient
from .config import GuardConfig
from .exceptions import (
    BadRequest,
    RedactionError,
    SentraUnavailable,
    ToolDenied,
    UnknownAgentError,
)

logger = logging.getLogger("aegion_guard")

F = TypeVar("F", bound=Callable[..., Any])

# WRITE if the tool name matches any of these (case-insensitive substring) — a
# deliberate widening of the narrower interceptor heuristics (LLD 23 §3.1).
# Best-effort ONLY: substring matching misfires (e.g. "update" in
# "get_update_history"). Pass operation_type explicitly for every WRITE tool.
_WRITE_HINTS = (
    "refund", "transfer", "reset", "port", "change",
    "create", "update", "modify", "delete", "write",
)

# Best-effort substrings that mark a denial as "agent not registered" until the
# controller emits a stable UNKNOWN_AGENT error_code (LLD 23 §12.1 caveat 3).
_UNKNOWN_AGENT_HINTS = ("not registered", "unknown agent", "agent not found")


def infer_operation_type(tool_name: str) -> str:
    """Best-effort READ/WRITE inference from a tool name (LLD 23 §3.1)."""
    lowered = tool_name.lower()
    return "WRITE" if any(hint in lowered for hint in _WRITE_HINTS) else "READ"


@dataclass
class Decision:
    """Parsed result of a validation call (LLD 23 §3)."""

    decision: str                       # "ALLOW" | "DENY" (anything else => DENY)
    request_id: str
    raw: Dict[str, Any] = field(default_factory=dict)
    reason: Optional[str] = None
    trust_score: Optional[float] = None
    threat_type: Optional[str] = None
    matched_rule: Optional[str] = None
    severity: Optional[str] = None
    latency_ms: Optional[float] = None

    @property
    def allowed(self) -> bool:
        return self.decision == "ALLOW"


class AegionGuard:
    """Routes guarded tool calls through the AegionAI controller before they run."""

    def __init__(
        self,
        agent_id: str,
        *,
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_s: Optional[float] = None,
        fail_secure: Optional[bool] = None,
        connect_retries: Optional[int] = None,
        tenant_id: Optional[str] = None,
        kid: Optional[str] = None,
        private_key: Optional[str] = None,
        private_key_file: Optional[str] = None,
        token_ttl_s: Optional[float] = None,
        platform: Optional[str] = None,
        cloud_region: Optional[str] = None,
        on_decision: Optional[Callable[[Decision], None]] = None,
    ) -> None:
        if not agent_id or not str(agent_id).strip():
            from .exceptions import ConfigError

            raise ConfigError("agent_id is required and must be non-empty")
        self.agent_id = agent_id
        self.platform = platform
        self.cloud_region = cloud_region
        self._on_decision = on_decision
        # Resolve + validate config now (fail fast), not at first tool call.
        self._config: GuardConfig = GuardConfig.resolve(
            api_base=api_base,
            api_key=api_key,
            timeout_s=timeout_s,
            fail_secure=fail_secure,
            connect_retries=connect_retries,
            tenant_id=tenant_id,
            kid=kid,
            private_key=private_key,
            private_key_file=private_key_file,
            token_ttl_s=token_ttl_s,
        )

        # Data-plane identity (WS-A): when configured, sign every validate request
        # with a short-lived ES256 JWT the controller verifies. The `identity`
        # extra (PyJWT[crypto]) is imported lazily and ONLY here — the zero-dep
        # core never touches it. AgentIdentity validates the key + tenant prefix
        # at construction, so a misconfigured agent fails now, not at first call.
        self._signer = None
        token_provider = None
        if self._config.identity_enabled:
            from .identity import AgentIdentity, JwtSigner

            self._signer = JwtSigner(
                AgentIdentity(
                    agent_id=self.agent_id,
                    tenant_id=self._config.tenant_id,
                    kid=self._config.kid,
                    private_key=self._config.private_key,
                    token_ttl_s=self._config.token_ttl_s,
                )
            )
            token_provider = self._signer.token

        from . import __version__

        self._client = ValidateClient(
            validate_url=self._config.validate_url,
            api_key=self._config.api_key,
            timeout_s=self._config.timeout_s,
            connect_retries=self._config.connect_retries,
            user_agent=f"aegion-guard/{__version__}",
            token_provider=token_provider,
        )

    # -- configuration accessors (read-only; never expose the api_key) -------
    @property
    def fail_secure(self) -> bool:
        return self._config.fail_secure

    @property
    def timeout_s(self) -> float:
        return self._config.timeout_s

    @property
    def identity_enabled(self) -> bool:
        """True when this guard signs requests with an agent JWT (WS-A)."""
        return self._signer is not None

    def __repr__(self) -> str:
        # Never include api_key or any private key material. Show only
        # non-sensitive identity/config (kid is a public reference, safe to show).
        return (
            f"AegionGuard(agent_id={self.agent_id!r}, "
            f"validate_url={self._config.validate_url!r}, "
            f"fail_secure={self._config.fail_secure}, "
            f"timeout_s={self._config.timeout_s}, "
            f"identity_enabled={self.identity_enabled})"
        )

    # -- per-request context -------------------------------------------------
    @contextmanager
    def session(
        self,
        session_id: str,
        user_input: str,
        *,
        request_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Iterator[None]:
        """Bind session context for the guarded tool calls made inside the block.

        Nesting is inner-wins: an inner session shadows the outer for its
        duration; the outer is restored on exit.
        """
        if not session_id or not user_input:
            from .exceptions import ConfigError

            raise ConfigError("session() requires non-empty session_id and user_input")
        token = _ctx.set_current(
            _ctx.RequestContext(
                session_id=session_id,
                user_input=user_input,
                request_id=request_id,
                context=context,
            )
        )
        try:
            yield
        finally:
            _ctx.reset_current(token)

    # -- decorators ----------------------------------------------------------
    def tool(
        self,
        name: Optional[str] = None,
        operation_type: str = "auto",
    ) -> Callable[[F], F]:
        """Decorate a tool so every call is validated before the body runs.

        This is the ``request`` phase — the action-validation surface (LLD 30
        §4.1). Its public signature is unchanged; the payload carries no ``phase``
        or ``content_text`` key (byte-identical to pre-WS-B). Works on both ``def``
        and ``async def`` functions.
        """
        return self._phase_decorator("request", name, operation_type)

    def content(
        self,
        name: Optional[str] = None,
        operation_type: str = "READ",
    ) -> Callable[[F], F]:
        """Decorate a function whose argument is untrusted data the agent INGESTS
        (the ``content`` phase — second-order injection surface, D2; LLD 30 §4).

        NOTE (§4.4): the controller has no live ``content`` handler yet, so a call
        today fails secure — the server DENYs (``phase_handler_not_implemented``)
        and this decorator raises ``ToolDenied`` via the same path as ``@guard.tool``.
        When WS-L lands the D2 handler, the SAME decorator starts returning real
        verdicts — no SDK change.
        """
        return self._phase_decorator("content", name, operation_type)

    def output(
        self,
        name: Optional[str] = None,
        operation_type: str = "READ",
    ) -> Callable[[F], F]:
        """Decorate a function whose value is data the agent EMITS (the ``output``
        phase — egress/DLP surface, D5; LLD 30 §4).

        NOTE (§4.4): no live ``output`` handler yet → fail-secure ``ToolDenied``
        today (server DENYs ``phase_handler_not_implemented``); WS-L's D5 handler
        flips it to a real verdict with no SDK change.
        """
        return self._phase_decorator("output", name, operation_type)

    def memory(
        self,
        name: Optional[str] = None,
        operation_type: str = "WRITE",
    ) -> Callable[[F], F]:
        """Decorate a function that performs a WRITE to the agent's memory store
        (the ``memory`` phase — memory-integrity surface, D3; LLD 30 §4).

        NOTE (§4.4): no live ``memory`` handler yet → fail-secure ``ToolDenied``
        today (server DENYs ``phase_handler_not_implemented``); WS-L's D3 handler
        flips it to a real verdict with no SDK change.
        """
        return self._phase_decorator("memory", name, operation_type)

    def _phase_decorator(
        self,
        phase: str,
        name: Optional[str] = None,
        operation_type: str = "auto",
    ) -> Callable[[F], F]:
        """Shared decorator machinery for all four phase surfaces (LLD 30 §4.1).

        The ONLY new thing threaded through vs. the pre-WS-B ``tool()`` body is the
        ``phase`` string — it flows to ``_build_request`` (NOT via ``RequestContext``,
        §4.2). Everything else (``_bind_params``, sync/async selection,
        ``_validate_or_raise``/``_avalidate_or_raise``) is reused unchanged, so no
        new dependency and no behavior change to the ``request`` path.
        """

        def decorator(fn: F) -> F:
            tool_name = name or fn.__name__

            if inspect.iscoroutinefunction(fn):

                @functools.wraps(fn)
                async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                    params = self._bind_params(fn, args, kwargs)
                    await self._avalidate_or_raise(
                        tool_name=tool_name,
                        tool_params=params,
                        operation_type=operation_type,
                        phase=phase,
                    )
                    return await fn(*args, **kwargs)

                return async_wrapper  # type: ignore[return-value]

            @functools.wraps(fn)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                params = self._bind_params(fn, args, kwargs)
                self._validate_or_raise(
                    tool_name=tool_name,
                    tool_params=params,
                    operation_type=operation_type,
                    phase=phase,
                )
                return fn(*args, **kwargs)

            return sync_wrapper  # type: ignore[return-value]

        return decorator

    # -- explicit (non-decorator) API ---------------------------------------
    def validate(
        self,
        *,
        tool_name: str,
        tool_params: Dict[str, Any],
        session_id: Optional[str] = None,
        user_input: Optional[str] = None,
        operation_type: str = "auto",
        request_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        phase: str = "request",
    ) -> Decision:
        """Validate a tool call explicitly and return the ``Decision``.

        Does NOT raise on DENY — the caller inspects ``decision.allowed``. Session
        fields may come from an active ``guard.session(...)`` or be passed here.
        ``phase`` defaults to ``"request"`` (LLD 30 §4) — keeping existing call
        sites unchanged; only the per-phase decorators pass a non-request phase.
        """
        try:
            payload = self._build_request(
                tool_name=tool_name,
                tool_params=tool_params,
                operation_type=operation_type,
                session_id=session_id,
                user_input=user_input,
                request_id=request_id,
                context=context,
                phase=phase,
            )
        except RedactionError as exc:
            return self._redaction_denied(request_id, exc)
        return self._send(payload)

    async def avalidate(
        self,
        *,
        tool_name: str,
        tool_params: Dict[str, Any],
        session_id: Optional[str] = None,
        user_input: Optional[str] = None,
        operation_type: str = "auto",
        request_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        phase: str = "request",
    ) -> Decision:
        """Async twin of :meth:`validate` — runs the blocking client off-loop."""
        try:
            payload = self._build_request(
                tool_name=tool_name,
                tool_params=tool_params,
                operation_type=operation_type,
                session_id=session_id,
                user_input=user_input,
                request_id=request_id,
                context=context,
                phase=phase,
            )
        except RedactionError as exc:
            return self._redaction_denied(request_id, exc)
        # Preserve the ambient contextvars into the worker thread.
        ctx = contextvars.copy_context()
        return await asyncio.to_thread(ctx.run, self._send, payload)

    # -- internals -----------------------------------------------------------
    def _validate_or_raise(
        self,
        *,
        tool_name: str,
        tool_params: Dict[str, Any],
        operation_type: str,
        phase: str = "request",
    ) -> Decision:
        decision = self.validate(
            tool_name=tool_name,
            tool_params=tool_params,
            operation_type=operation_type,
            phase=phase,
        )
        self._raise_if_blocked(decision)
        return decision

    async def _avalidate_or_raise(
        self,
        *,
        tool_name: str,
        tool_params: Dict[str, Any],
        operation_type: str,
        phase: str = "request",
    ) -> Decision:
        decision = await self.avalidate(
            tool_name=tool_name,
            tool_params=tool_params,
            operation_type=operation_type,
            phase=phase,
        )
        self._raise_if_blocked(decision)
        return decision

    def _build_request(
        self,
        *,
        tool_name: str,
        tool_params: Dict[str, Any],
        operation_type: str,
        session_id: Optional[str],
        user_input: Optional[str],
        request_id: Optional[str],
        context: Optional[Dict[str, Any]],
        phase: str = "request",
    ) -> Dict[str, Any]:
        # Session fields: explicit args win; otherwise the active session().
        active = _ctx.current()
        resolved_session = session_id or (active.session_id if active else None)
        resolved_input = user_input if user_input is not None else (
            active.user_input if active else None
        )
        if not resolved_session or resolved_input is None:
            raise RuntimeError(
                "No session context. Call inside `with guard.session(session_id=..., "
                "user_input=...):` or pass session_id and user_input explicitly."
            )
        resolved_context = context if context is not None else (
            active.context if active else None
        )
        # request_id precedence: explicit arg > pinned session id > fresh uuid.
        resolved_request_id = (
            request_id
            or (active.request_id if active else None)
            or f"req-{uuid.uuid4().hex[:16]}"
        )

        op = operation_type
        if op == "auto":
            op = infer_operation_type(tool_name)
        op = op.upper()
        if op not in ("READ", "WRITE"):
            from .exceptions import ConfigError

            raise ConfigError(
                f"operation_type must be READ, WRITE, or auto (got {operation_type!r})"
            )

        # Guard against non-JSON-serializable params *before* sending — surface a
        # clear usage error, never a silent allow (LLD 23 §8). datetime is coerced
        # for convenience; anything else unserializable is a usage error.
        safe_params = _ensure_json_serializable(tool_params)

        # WS-E1 (FR-3.13; LLD 29 §3): Tier-1 edge redaction. Every field that
        # egresses to the hosted PDP carries structured PII/PCI risk — mask it here,
        # BEFORE the payload leaves the customer boundary on the Serverless edition
        # (NFR-7 clause (a): no raw structured identifier egresses on any edition).
        # ONE per-egress nonce (secrets.token_hex(8)) is minted and threaded through
        # EVERY redacted field so all genuine markers in this payload share the
        # single `redaction_nonce` the PDP checks — an attacker cannot forge a marker
        # bearing this call's nonce (M-4). A redactor failure raises RedactionError,
        # which `validate`/`avalidate` turn into a fail-secure DENY — the raw payload
        # is NEVER sent, on any fail_secure setting (failing open here is a clause-(a)
        # breach). `redaction_nonce` is minted here so tool_params/user_input/context
        # and (for egressing phases) content_text all bind to it.
        nonce = _redaction.new_nonce()
        safe_params = _redaction.redact_params(safe_params, nonce=nonce)
        redacted_input = _redaction.redact(resolved_input, nonce=nonce)
        redacted_context = (
            _redaction.redact_params(resolved_context, nonce=nonce)
            if resolved_context
            else resolved_context
        )

        payload: Dict[str, Any] = {
            "request_id": resolved_request_id,
            "session_id": resolved_session,
            "agent_id": self.agent_id,
            "tool_name": tool_name,
            "tool_params": safe_params,
            "user_input": redacted_input,
            "timestamp": isoformat_ms_z(datetime.now(timezone.utc)),
            "operation_type": op,
            # Provenance (LLD 29 §3.3/§3.5): declare the payload was edge-redacted and
            # publish the single per-egress nonce so the PDP recognizes genuine markers.
            "redacted": True,
            "redaction_nonce": nonce,
        }
        if self.platform:
            payload["platform"] = self.platform
        if self.cloud_region:
            payload["cloud_region"] = self.cloud_region
        if redacted_context:
            payload["context"] = redacted_context
        # WS-B (LLD 30 §4.2): emit `phase` (and `content_text` for the egressing
        # phases) ONLY when not "request". The `request` path stays byte-identical
        # on the wire (aside from the redaction provenance stamped on every payload)
        # — the server defaults the absent `phase` to "request". Do NOT always emit
        # "phase": "request" (it would perturb every existing caller's payload — the
        # no-op guarantee, §1.4).
        if phase != "request":
            payload["phase"] = phase
            # content/output/memory carry their content in the single `content_text`
            # field (WS-B's _CONTENT_FIELD map, disambiguated by `phase`). WS-E
            # (lld/29 §3.5) redacts it with the SAME per-egress nonce before _send;
            # WS-B only PLACES it, sourced from the resolved input the decorator
            # already has. A richer per-phase capture arg is WS-L's concern — WS-B
            # guarantees the field EXISTS and is populated, not its richest source.
            #
            # `content_text` is `resolved_input` disambiguated by phase, and
            # `resolved_input` was ALREADY redacted into `redacted_input` above with
            # this call's nonce — reuse it rather than redacting the same value a
            # second time (R5-L1). A second redact() would mint the same tokens but
            # burns CPU and, worse, invites the two copies to drift if one call site
            # is later changed; one redaction, one source of truth.
            payload["content_text"] = redacted_input
        return payload

    def _redaction_denied(
        self, request_id: Optional[str], exc: RedactionError
    ) -> Decision:
        """Fail-secure DENY when Tier-1 edge redaction could not complete (WS-E1).

        A redactor failure must NEVER egress the raw/partially-redacted payload —
        this returns a DENY on ANY ``fail_secure`` setting (``fail_secure=False`` is
        an opt-out of failing closed on TRANSPORT loss, NOT a license to leak raw
        PII/PCI; NFR-7 clause (a)). ``_send`` is never reached, so nothing is sent.
        The DENY reason is the fixed ``redaction_failed`` code; the exception message
        (carrying only the error *type*, never the raw value) is kept in ``raw`` for
        debugging. The ``on_decision`` hook fires as it would for any decision.
        """
        decision = Decision(
            decision="DENY",
            request_id=request_id or f"req-{uuid.uuid4().hex[:16]}",
            reason="redaction_failed",
            raw={"error": str(exc)},
        )
        self._fire_hook(decision)
        return decision

    def _send(self, payload: Dict[str, Any]) -> Decision:
        request_id = payload["request_id"]
        try:
            body = self._client.post(payload)
        except TransportError as exc:
            # WS-B (LLD 30 §3.6): a 422 is a MALFORMED REQUEST (e.g. a bad `phase`),
            # not an outage — surface a developer-actionable, NON-recoverable raise
            # that halts the wrapper BEFORE `fn` runs. ONLY `== 422` takes this
            # branch; a None (timeout/connection) or a 5xx/403 MUST stay on the
            # fail-secure DENY path below — a truthiness/coercion refactor here that
            # let a 5xx skip fail-secure would fail OPEN on an outage (the footgun).
            if exc.status_code == 422:
                raise BadRequest(str(exc)) from exc
            if self._config.fail_secure:
                decision = Decision(
                    decision="DENY",
                    request_id=request_id,
                    reason="validation_unavailable",
                    raw={"error": str(exc)},
                )
                self._fire_hook(decision)
                return decision
            raise SentraUnavailable(str(exc), cause=exc.cause or exc) from exc

        decision = self._parse_decision(body, fallback_request_id=request_id)
        self._fire_hook(decision)
        return decision

    @staticmethod
    def _parse_decision(body: Dict[str, Any], *, fallback_request_id: str) -> Decision:
        raw_decision = body.get("decision")
        # Default-DENY on anything that isn't a clean ALLOW/DENY (LLD 23 §8):
        # contract drift or a proxy-injected body must never read as allow.
        decision_value = raw_decision if raw_decision in ("ALLOW", "DENY") else "DENY"
        reason = body.get("reason")
        if raw_decision not in ("ALLOW", "DENY"):
            reason = reason or f"unrecognized decision {raw_decision!r}; failing closed"
        return Decision(
            decision=decision_value,
            request_id=body.get("request_id") or fallback_request_id,
            raw=body,
            reason=reason,
            trust_score=_as_float(body.get("trust_score")),
            threat_type=body.get("threat_type"),
            matched_rule=body.get("matched_rule"),
            severity=body.get("severity"),
            latency_ms=_as_float(body.get("latency_ms")),
        )

    def _raise_if_blocked(self, decision: Decision) -> None:
        if decision.allowed:
            return
        reason = decision.reason or "Blocked by Sentra security policy"
        if _is_unknown_agent(reason):
            raise UnknownAgentError(
                reason, threat_type=decision.threat_type, decision=decision
            )
        raise ToolDenied(reason, threat_type=decision.threat_type, decision=decision)

    def _fire_hook(self, decision: Decision) -> None:
        # NOTE: on the async path (`avalidate`) this runs inside the
        # `asyncio.to_thread` worker, i.e. off the event-loop thread. Keep an
        # `on_decision` hook thread-safe if you use the SDK asynchronously.
        if self._on_decision is None:
            return
        try:
            self._on_decision(decision)
        except Exception:  # noqa: BLE001 — the hook must never break the tool path
            logger.exception("aegion_guard on_decision hook raised; ignoring")

    def _bind_params(self, fn: Callable[..., Any], args: tuple, kwargs: dict) -> Dict[str, Any]:
        """Map *args/**kwargs to a {param_name: value} dict for tool_params."""
        try:
            bound = inspect.signature(fn).bind_partial(*args, **kwargs)
            bound.apply_defaults()
            params = dict(bound.arguments)
        except TypeError:
            # Signature couldn't be bound (e.g. *args/**kwargs only); fall back.
            params = dict(kwargs)
        # Drop conventional self/cls so method tools don't leak the instance.
        params.pop("self", None)
        params.pop("cls", None)
        return params


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_unknown_agent(reason: str) -> bool:
    lowered = reason.lower()
    return any(hint in lowered for hint in _UNKNOWN_AGENT_HINTS)


def _ensure_json_serializable(params: Dict[str, Any]) -> Dict[str, Any]:
    """Return params verified JSON-encodable; raise a clear error otherwise.

    ``datetime`` values are coerced to canonical ms-Z strings for convenience
    (a very common tool param). Anything else non-encodable is a usage error —
    we never silently drop it or let it fail later as a confusing transport error.
    """

    def _default(obj: Any) -> Any:
        if isinstance(obj, datetime):
            return isoformat_ms_z(obj)
        raise TypeError(
            f"tool param of type {type(obj).__name__} is not JSON-serializable; "
            f"convert it to a primitive before the guarded call"
        )

    try:
        # Round-trip through the encoder we'll actually use, applying the same
        # default coercion, so what we validate is exactly what we send.
        encoded = json.dumps(params, default=_default)
    except TypeError as exc:
        from .exceptions import ConfigError

        raise ConfigError(str(exc)) from exc
    return json.loads(encoded)
