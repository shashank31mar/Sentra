"""HTTP client for POST /v1/validate (LLD 23 §4, §8, §12.1).

stdlib ``urllib`` only — no ``requests`` — so the SDK vendors unchanged into a
Lambda zip and an Azure Function package (Oryx build constraint).

Key behaviors:
- TLS verification stays ON (we never build an unverified ``ssl`` context).
- ``x-api-key`` is sent server-side from resolved config; it is never logged.
- A DENY comes back as **HTTP 200** with the decision in the body, so a non-2xx
  status is always a transport/availability problem, not a denial.
- ``connect_retries`` retries **connection-establishment failures only**
  (ECONNREFUSED / DNS). It deliberately does NOT retry read-timeouts: retrying a
  validation that already burned the full timeout just doubles the wait before
  fail-secure trips (LLD 23 §12.1 caveat 1).
"""
from __future__ import annotations

import json
import socket
import ssl
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Optional


class TransportError(Exception):
    """Any failure to obtain a well-formed JSON response from /v1/validate.

    Raised for timeouts, connection errors, non-2xx status, and non-JSON/oversized
    bodies. The guard layer turns this into fail-secure DENY (or SentraUnavailable
    when ``fail_secure=False``). It never escapes the SDK's public API directly.
    """

    def __init__(self, message: str, *, retryable: bool, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.cause = cause


# Cap the response body we will read/parse. A validate response is small
# (a few hundred bytes); anything massive is a misconfigured proxy, not Sentra.
_MAX_RESPONSE_BYTES = 256 * 1024


class ValidateClient:
    """Thin POST client for the validate endpoint."""

    def __init__(
        self,
        *,
        validate_url: str,
        api_key: str,
        timeout_s: float,
        connect_retries: int,
        user_agent: str,
        token_provider: Optional[Callable[[], Optional[str]]] = None,
    ) -> None:
        self._url = validate_url
        self._api_key = api_key
        self._timeout_s = timeout_s
        self._connect_retries = connect_retries
        self._user_agent = user_agent
        # When set, called once per POST to mint the agent's Bearer JWT (WS-A).
        # A signer caches/refreshes internally, so this is cheap per call.
        self._token_provider = token_provider
        # Verified TLS context. Explicit (rather than relying on the default) so
        # the intent — certificate verification ON — is unmistakable and can't be
        # silently weakened by a global default override.
        self._ssl_ctx = ssl.create_default_context()

    def post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """POST the validation request; return the parsed JSON body.

        Raises ``TransportError`` on any failure to get a 2xx JSON response.
        Retries connection-establishment errors up to ``connect_retries`` times.
        """
        body = json.dumps(payload).encode("utf-8")
        # Mint the identity token ONCE per POST (before the retry loop) so all
        # connection retries reuse the same token and a sign failure surfaces
        # immediately as fail-secure, never as an unsigned (→ denied) request.
        auth_header = self._auth_header()
        attempts = self._connect_retries + 1
        last_exc: TransportError | None = None

        for attempt in range(attempts):
            try:
                return self._post_once(body, auth_header)
            except TransportError as exc:
                last_exc = exc
                # Only connection-establishment failures are retryable; a
                # read-timeout or a non-2xx status is not (§12.1 caveat 1).
                if not exc.retryable or attempt == attempts - 1:
                    raise
                # Tiny linear backoff; this is the cold-connection case, not a
                # thundering-herd retry storm.
                time.sleep(0.05 * (attempt + 1))

        # Unreachable (loop either returns or raises), but keeps type-checkers happy.
        assert last_exc is not None
        raise last_exc

    def _auth_header(self) -> Optional[str]:
        """Resolve the ``Authorization: Bearer`` value for this POST, or None.

        A signing failure is fail-secure: we raise a non-retryable
        ``TransportError`` so the guard denies the call locally rather than
        sending an unsigned request that the controller would reject anyway.
        """
        if self._token_provider is None:
            return None
        try:
            token = self._token_provider()
        except Exception as exc:  # noqa: BLE001 — any sign failure → fail-secure
            raise TransportError(
                f"could not mint agent identity token: {exc}",
                retryable=False,
                cause=exc,
            ) from exc
        return f"Bearer {token}" if token else None

    def _post_once(self, body: bytes, auth_header: Optional[str] = None) -> Dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "x-api-key": self._api_key,
            "User-Agent": self._user_agent,
        }
        if auth_header:
            # The verified agent JWT (WS-A). Carried alongside x-api-key:
            # x-api-key is the API-Gateway edge key; this is the per-agent,
            # per-tenant identity the controller verifies. Never logged.
            headers["Authorization"] = auth_header
        req = urllib.request.Request(
            self._url,
            data=body,
            method="POST",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(
                req, timeout=self._timeout_s, context=self._ssl_ctx
            ) as resp:
                raw = resp.read(_MAX_RESPONSE_BYTES + 1)
                if len(raw) > _MAX_RESPONSE_BYTES:
                    raise TransportError(
                        "validate response exceeded maximum size",
                        retryable=False,
                    )
                return self._parse(raw)
        except urllib.error.HTTPError as exc:
            # A response with a non-2xx status. DENY is 200, so this is a real
            # server/gateway error (403 missing key, 5xx, etc.) — not retryable
            # here; fail-secure handles it upstream.
            raise TransportError(
                f"validate returned HTTP {exc.code}",
                retryable=False,
                cause=exc,
            ) from exc
        except socket.timeout as exc:
            # Read-timeout: the request was sent but no/late response. NOT
            # retryable — retrying just doubles the wall-clock before fail-secure.
            raise TransportError(
                f"validate timed out after {self._timeout_s}s",
                retryable=False,
                cause=exc,
            ) from exc
        except urllib.error.URLError as exc:
            # Connection-level failure (DNS, refused, reset, TLS). urllib wraps
            # a read-timeout as URLError(reason=socket.timeout) too, so we must
            # disambiguate to avoid retrying a timeout.
            reason = getattr(exc, "reason", None)
            if isinstance(reason, socket.timeout):
                raise TransportError(
                    f"validate timed out after {self._timeout_s}s",
                    retryable=False,
                    cause=exc,
                ) from exc
            raise TransportError(
                f"could not reach validate endpoint: {reason or exc}",
                retryable=True,
                cause=exc,
            ) from exc
        except (OSError, ssl.SSLError) as exc:
            # Catch-all for lower-level socket/TLS errors not surfaced as URLError.
            raise TransportError(
                f"transport error calling validate: {exc}",
                retryable=False,
                cause=exc,
            ) from exc

    @staticmethod
    def _parse(raw: bytes) -> Dict[str, Any]:
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise TransportError("validate response was not UTF-8", retryable=False, cause=exc) from exc
        try:
            parsed = json.loads(decoded)
        except json.JSONDecodeError as exc:
            raise TransportError("validate response was not valid JSON", retryable=False, cause=exc) from exc
        if not isinstance(parsed, dict):
            raise TransportError(
                f"validate response was not a JSON object (got {type(parsed).__name__})",
                retryable=False,
            )
        return parsed
