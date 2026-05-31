"""Azure Function tool-registry fetcher — Workstream 18 M3.3.

The Azure Function App at AZURE_FUNCTION_TOOL_URL exposes `/api/health` which
returns the list of registered tools. The scenario validator uses this to
cross-check `tool:` steps on `cloud: azure_foundry` — catching scenarios
that reference a tool the Function hasn't deployed.

We do NOT have per-param schema for Azure tools (the Function dispatch
table is a Python dict of callables; the schema lives in the Python code,
not in a JSON document). Validator can only check tool *names*, not
param types. That's a known v0.1 gap; flagged in the validator output.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)


class AzureToolsUnavailable(Exception):
    """Raised when the Azure Function's /api/health doesn't respond or
    doesn't include a tools list. The validator surfaces this as a
    deploy-time error so demo authors fix the Function App, not the YAML.
    """


class AzureToolFetcher:
    """Fetch + cache the Azure Function's registered tools at orchestrator boot.

    One instance per orchestrator process. Cache is process-lifetime (Function
    redeploys are explicit; orchestrator restarts pick up the new state).
    """

    def __init__(
        self,
        *,
        function_tool_url: Optional[str] = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        # function_tool_url should be the BASE (e.g.
        # https://aegionai-ws15-m3-func.azurewebsites.net/api/tool). /api/health
        # is a sibling endpoint on the same Function App.
        import os
        url = function_tool_url or os.environ.get("AZURE_FUNCTION_TOOL_URL", "")
        self._base_url = url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._cache: Optional[set[str]] = None
        self._lock = threading.Lock()

    def get_tools(self) -> set[str]:
        """Return the set of tool names registered on the Function App."""
        with self._lock:
            if self._cache is not None:
                return self._cache
        tools = self._fetch()
        with self._lock:
            self._cache = tools
        return tools

    def invalidate(self) -> None:
        with self._lock:
            self._cache = None

    def _fetch(self) -> set[str]:
        if not self._base_url:
            raise AzureToolsUnavailable(
                "AZURE_FUNCTION_TOOL_URL not set; cannot validate Azure tool steps. "
                "Set the env var in the orchestrator's task definition."
            )
        # /api/tool/<name> → /api/health is the sibling path
        # The base URL today is .../api/tool — strip that to get the host root.
        if self._base_url.endswith("/api/tool"):
            health_url = self._base_url[: -len("/api/tool")] + "/api/health"
        else:
            health_url = self._base_url + "/api/health"

        req = urllib.request.Request(health_url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout_seconds) as resp:
                if resp.status != 200:
                    raise AzureToolsUnavailable(
                        f"Azure Function /api/health returned HTTP {resp.status}"
                    )
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise AzureToolsUnavailable(
                f"Azure Function /api/health unreachable: {exc}"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise AzureToolsUnavailable(
                f"Azure Function /api/health returned non-JSON body: {exc}"
            ) from exc

        tools = body.get("tools_registered")
        if not isinstance(tools, list):
            raise AzureToolsUnavailable(
                f"Azure Function /api/health missing tools_registered list: {body}"
            )
        logger.info(
            "AzureToolFetcher: cached %d tools from Function App: %s",
            len(tools), tools,
        )
        return set(tools)
