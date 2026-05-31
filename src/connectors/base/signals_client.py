"""Thin HTTP client for POST /v1/sessions/{id}/signals — Workstream 17 / LLD 17.

Used by connectors (Bedrock, Azure, future GCP) to report their edge-layer
signal observations to the Sentra controller. Stdlib-only by design so the
Azure Function tool_interceptor can import this without adding dependencies
(see WS15 M3 lessons — `azd deploy` doesn't run Oryx Remote Build on B1 Linux).

Failure semantics
-----------------
Every method is best-effort. Failures log a warning + return False. They
NEVER raise into the connector's invoke path — a missed signal is a UX
regression (missing badge in the expander), not a correctness failure.
The Sentra signals already landed during /v1/validate; this is just the
edge supplement.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 5.0


class SignalsClient:
    """POST signals to the Sentra controller.

    Constructed with a base URL; callers should reuse one instance per
    connector lifecycle so the timeout / base URL are configured once.
    """

    def __init__(self, base_url: Optional[str] = None, timeout: float = DEFAULT_TIMEOUT_S):
        # Reuse the same env var the rest of the connector code uses for the
        # controller endpoint so there's one configuration knob.
        self.base_url = (
            base_url
            or os.environ.get("SENTRA_API_ENDPOINT", "")
            or os.environ.get("SECURITY_CONTROLLER_URL", "")
        ).rstrip("/")
        # Strip a trailing /v1/validate if the env var was set to the
        # validate URL — we want the controller root.
        if self.base_url.endswith("/v1/validate"):
            self.base_url = self.base_url[: -len("/v1/validate")]
        if self.base_url.endswith("/v1"):
            self.base_url = self.base_url[: -len("/v1")]
        self.timeout = timeout
        # API Gateway requires this header; the private ALB doesn't care
        # but accepts it. Default to env if set.
        self._api_key = os.environ.get("SENTRA_API_KEY")

    def post_signal(
        self,
        session_id: str,
        request_id: str,
        source: str,
        decision: str,
        *,
        reason: Optional[str] = None,
        priority: Optional[int] = None,
        agent_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        platform: Optional[str] = None,
        cloud_region: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> bool:
        """POST a single signal. Returns True on success, False on any failure."""
        if not self.base_url:
            logger.debug(
                "SignalsClient: no base URL configured, skipping post_signal "
                "(set SENTRA_API_ENDPOINT or SECURITY_CONTROLLER_URL)"
            )
            return False

        url = f"{self.base_url}/v1/sessions/{session_id}/signals"
        body = {
            "request_id": request_id,
            "source": source,
            "decision": decision,
        }
        if reason is not None:
            body["reason"] = reason
        if priority is not None:
            body["priority"] = priority
        if agent_id is not None:
            body["agent_id"] = agent_id
        if tool_name is not None:
            body["tool_name"] = tool_name
        if platform is not None:
            body["platform"] = platform
        if cloud_region is not None:
            body["cloud_region"] = cloud_region
        if metadata is not None:
            body["metadata"] = metadata

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["x-api-key"] = self._api_key

        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers=headers,
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if 200 <= resp.status < 300:
                    return True
                logger.warning(
                    "post_signal: controller returned HTTP %s for %s/%s/%s",
                    resp.status, session_id, request_id, source,
                )
                return False
        except urllib.error.HTTPError as exc:
            logger.warning(
                "post_signal HTTPError %s for %s/%s/%s: %s",
                exc.code, session_id, request_id, source, exc,
            )
            return False
        except (urllib.error.URLError, TimeoutError) as exc:
            logger.warning(
                "post_signal URLError for %s/%s/%s: %s",
                session_id, request_id, source, exc,
            )
            return False
        except Exception as exc:  # noqa: BLE001 — best-effort by design
            logger.warning(
                "post_signal unexpected error for %s/%s/%s: %s",
                session_id, request_id, source, exc,
            )
            return False
