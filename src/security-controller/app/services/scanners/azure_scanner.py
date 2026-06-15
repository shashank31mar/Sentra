"""Azure read-only discovery adapter (feature §7, §12).

Lists the AI "agents" running in a connected Azure subscription using a
customer-provided **service principal with Reader** (feature §7 Azure row). The
SP's secret lives in a vault (AWS Secrets Manager here, since the control plane
runs on AWS); the connection record stores only a **reference** to it
(``secret_ref``) plus the subscription / tenant / client ids — never the secret
itself (feature §6 group F, §14).

Two notions of an "Azure agent" — discovered together
-----------------------------------------------------
Azure has no single native "agent" resource like AWS ``bedrock:ListAgents``, so
``AzureScanner`` is an **orchestrator** that runs one read-only sub-scanner per
surface and merges (deduped by ``native_resource_id``):

1. **Cognitive Services deployments** (``_CognitiveDeploymentScanner``) —
   ``Microsoft.CognitiveServices/accounts`` + ``.../deployments``. Each model
   *deployment* (e.g. gpt-4o-mini) is one agent candidate. Reader-scoped,
   universally available. Exposes no tool schema → tools operator-supplied
   (§7/§15 fallback).
2. **Azure AI Foundry Agent Service** (``_FoundryAgentScanner``) — the agents
   defined inside an AI Foundry / AI Services *project* (data-plane, OpenAI
   "assistants"-compatible). These DO carry a model + a tool list, so they
   import with real ``allowed_tools``.

A sub-scanner that finds nothing (or whose SDK/endpoint is unavailable) degrades
quietly; the orchestrator returns ``ok=True`` if **any** sub-scanner succeeded,
so a subscription with only Azure OpenAI (no Foundry) still connects.

Contract
--------
``discover(creds) -> (ok, agents | None, message)`` — mirrors the AWS
``_assume_and_probe`` tuple so ``connections_service`` treats both clouds
uniformly. It **never raises**: a bad SP, an insufficient scope, or a missing
SDK is a normal, reportable outcome (``ok=False``), exactly like a rejected IAM
role.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ARM account id → resource group, e.g.
# /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<name>
_RG_RE = re.compile(r"/resourceGroups/([^/]+)/", re.IGNORECASE)

# Cognitive Services account kinds that host generative AI workloads.
_DEPLOYMENT_KINDS = {"OpenAI", "AIServices"}
# Account kinds that can host an AI Foundry project (and thus Agent Service).
_FOUNDRY_KINDS = {"AIServices"}

# Data-plane scope + api-version for the Agent Service (OpenAI-assistants shape).
_FOUNDRY_TOKEN_SCOPE = "https://ai.azure.com/.default"
_FOUNDRY_API_VERSION = os.environ.get("AZURE_FOUNDRY_API_VERSION", "2025-05-01")

DiscoveredAgent = Dict[str, Any]
ProbeResult = Tuple[bool, Optional[List[DiscoveredAgent]], str]


class AzureDiscoveryError(Exception):
    """Raised internally when an Azure call fails in a way the caller should
    treat as a connection error (not a crash)."""


class _AzureContext:
    """Built once per ``discover()`` and shared by every sub-scanner: a single
    secret read, a single credential, and a single ``accounts.list()`` — so a
    probe isn't 3× vault reads + 2× account listings (review nit #2)."""

    __slots__ = ("creds", "credential", "mgmt_client", "accounts")

    def __init__(self, creds, credential, mgmt_client, accounts):
        self.creds = creds
        self.credential = credential
        self.mgmt_client = mgmt_client
        self.accounts = accounts


# ---------------------------------------------------------------- orchestrator
class AzureScanner:
    """Runs every Azure sub-scanner over one shared context and merges (feature §7).

    Args:
        secret_resolver: ``(secret_ref) -> client_secret`` — fetches the SP
            secret from the vault. Defaults to AWS Secrets Manager. Injectable so
            tests need neither a live vault nor the Azure SDK.
        credential_factory / client_factory: seams to inject fakes for the
            credential + Cognitive Services mgmt client in tests.
        sub_scanners: override the default sub-scanner list (tests / future
            surfaces). Each must expose ``discover(ctx) -> ProbeResult``.
    """

    def __init__(
        self,
        secret_resolver: Optional[Callable[[str], str]] = None,
        credential_factory: Optional[Callable[..., Any]] = None,
        client_factory: Optional[Callable[..., Any]] = None,
        sub_scanners: Optional[List[Any]] = None,
    ) -> None:
        self._secret_resolver = secret_resolver or _secrets_manager_resolver
        self._credential_factory = credential_factory
        self._client_factory = client_factory
        self._sub_scanners = sub_scanners or [
            _CognitiveDeploymentScanner(),
            _FoundryAgentScanner(),
        ]

    def discover(self, creds: Dict[str, Any]) -> ProbeResult:
        missing = _missing_creds(creds)
        if missing:
            return False, None, f"Azure credentials incomplete — missing {', '.join(missing)}"

        # Resolve secret + credential + account list ONCE, shared across scanners.
        try:
            ctx = self._build_context(creds)
        except AzureDiscoveryError as exc:
            return False, None, str(exc)
        except Exception as exc:  # noqa: BLE001 — any SDK/transport error is reportable
            logger.warning("azure context build failed: %s", exc)
            return False, None, f"Azure discovery failed: {exc}"

        merged: Dict[str, DiscoveredAgent] = {}
        notes: List[str] = []
        skipped: List[str] = []
        any_ok = False
        last_error = "Azure discovery failed"
        for scanner in self._sub_scanners:
            ok, agents, message = scanner.discover(ctx)
            if ok:
                any_ok = True
                for a in agents or []:
                    native = a.get("native_resource_id")
                    if native and native not in merged:
                        merged[native] = a
                if agents:
                    notes.append(message)
            else:
                last_error = message
                skipped.append(message)
                logger.info("azure sub-scanner skipped: %s", message)

        if not any_ok:
            return False, None, last_error

        summary = f"Service principal OK · {len(merged)} agents visible"
        if notes:
            summary += " (" + "; ".join(notes) + ")"
        if skipped:
            # Surface a partially-failed surface honestly — otherwise a Foundry
            # data-plane misconfig silently yields zero agents (review nit #1).
            summary += " · skipped: " + "; ".join(skipped)
        return True, list(merged.values()), summary

    def _build_context(self, creds: Dict[str, Any]) -> _AzureContext:
        secret = self._secret_resolver(creds["secret_ref"])
        if not secret:
            raise AzureDiscoveryError(f"vault returned no secret for ref {creds['secret_ref']!r}")
        credential, mgmt = self._build_credential_and_client(creds, secret)
        accounts = list(mgmt.accounts.list())
        return _AzureContext(creds, credential, mgmt, accounts)

    def _build_credential_and_client(self, creds: Dict[str, Any], secret: str):
        if self._credential_factory and self._client_factory:
            credential = self._credential_factory(
                tenant_id=creds["tenant_id"], client_id=creds["client_id"], client_secret=secret
            )
            return credential, self._client_factory(credential, creds["subscription_id"])
        try:
            from azure.identity import ClientSecretCredential
            from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient
        except ImportError as exc:  # azure SDK not installed in this image
            raise AzureDiscoveryError(
                "Azure SDK not available (install azure-identity + azure-mgmt-cognitiveservices)"
            ) from exc
        credential = ClientSecretCredential(
            tenant_id=creds["tenant_id"], client_id=creds["client_id"], client_secret=secret
        )
        return credential, CognitiveServicesManagementClient(credential, creds["subscription_id"])


# ------------------------------------------------- sub-scanner: deployments
class _CognitiveDeploymentScanner:
    """Azure OpenAI / Cognitive Services account + model-deployment discovery.
    Reads the shared account list from the context; only ``deployments.list`` is
    per-account."""

    def discover(self, ctx: "_AzureContext") -> ProbeResult:
        try:
            agents = _list_deployments(ctx.mgmt_client, ctx.accounts)
        except Exception as exc:  # noqa: BLE001 — any SDK/transport error is reportable
            logger.warning("azure deployment discovery failed: %s", exc)
            return False, None, f"deployment discovery failed: {exc}"
        return True, agents, f"{len(agents)} model deployments"


# ------------------------------------------------- sub-scanner: foundry agents
class _FoundryAgentScanner:
    """Azure AI Foundry Agent Service discovery (feature §7).

    Derives AI Foundry projects (AIServices accounts) from the shared context's
    account list, then lists the agents defined in each via the data-plane Agent
    Service API (OpenAI-assistants-compatible). Agents carry a model + tools, so
    they import with real ``allowed_tools``.

    Seams (``endpoint_lister`` / ``agent_lister``) keep this unit-testable
    without the Azure SDK or a live project. The default ``agent_lister`` hits
    the data-plane REST endpoint and **needs live validation against a real
    Foundry project** — the exact route/api-version may need tuning per service
    GA; the seam makes that a one-line change. When every project fails to list,
    the scanner reports a skip (surfaced by the orchestrator) rather than a
    silent zero.
    """

    def __init__(self, endpoint_lister=None, agent_lister=None):
        self._endpoint_lister = endpoint_lister
        self._agent_lister = agent_lister

    def discover(self, ctx: "_AzureContext") -> ProbeResult:
        endpoints = (
            self._endpoint_lister(ctx) if self._endpoint_lister
            else _foundry_endpoints(ctx.accounts)
        )
        if not endpoints:
            # No Foundry projects in this subscription — not an error, just empty.
            return True, [], "0 foundry agents"

        agents: List[DiscoveredAgent] = []
        errors = 0
        for proj in endpoints:
            try:
                for a in self._list_agents(proj, ctx):
                    agents.append(_foundry_agent_record(proj, a))
            except Exception as exc:  # noqa: BLE001 — one bad project shouldn't sink the rest
                errors += 1
                logger.warning("foundry agent list failed for %s: %s", proj.get("endpoint"), exc)
        if errors and not agents:
            # Every project's data-plane list failed — report it, don't hide a zero.
            return False, None, f"foundry agent-list failed for {errors} project(s)"
        return True, agents, f"{len(agents)} foundry agents"

    def _list_agents(self, proj: Dict[str, Any], ctx: "_AzureContext") -> List[Any]:
        if self._agent_lister:
            return self._agent_lister(proj, ctx)
        token = ctx.credential.get_token(_FOUNDRY_TOKEN_SCOPE).token
        return _http_list_assistants(proj["endpoint"], token)


# --------------------------------------------------------------------- shared
def _missing_creds(creds: Dict[str, Any]) -> List[str]:
    return [
        k for k in ("subscription_id", "tenant_id", "client_id", "secret_ref")
        if not creds.get(k)
    ]


def _foundry_endpoints(accounts: List[Any]) -> List[Dict[str, Any]]:
    """AI Foundry project endpoints derived from the shared account list."""
    out: List[Dict[str, Any]] = []
    for account in accounts:
        if getattr(account, "kind", None) not in _FOUNDRY_KINDS:
            continue
        props = getattr(account, "properties", None)
        endpoint = getattr(props, "endpoint", None) if props else None
        if not endpoint:
            continue
        out.append({
            "account_id": getattr(account, "id", None),
            "account_name": getattr(account, "name", None),
            "endpoint": endpoint,
            "region": getattr(account, "location", None),
        })
    return out


def _list_deployments(client: Any, accounts: List[Any]) -> List[DiscoveredAgent]:
    agents: List[DiscoveredAgent] = []
    for account in accounts:
        # Skip non-AI accounts (SpeechServices, ComputerVision, …) AND accounts
        # with no kind — only OpenAI/AIServices host generative deployments.
        if getattr(account, "kind", None) not in _DEPLOYMENT_KINDS:
            continue
        rg = _resource_group_of(getattr(account, "id", "") or "")
        account_name = getattr(account, "name", None)
        if not rg or not account_name:
            continue
        region = getattr(account, "location", None)
        for dep in client.deployments.list(rg, account_name):
            native = getattr(dep, "id", None)
            if not native:
                continue
            agents.append({
                "native_resource_id": native,
                "name": getattr(dep, "name", None) or native,
                "status": _deployment_state(dep),
                "cloud_provider": "azure",
                "platform": "azure_foundry",
                "framework": "azure_openai",
                "region": region,
                "model": _deployment_model(dep),
                "tools": [],  # no tool manifest at this layer (feature §7/§15)
            })
    return agents


def _foundry_agent_record(proj: Dict[str, Any], agent: Any) -> DiscoveredAgent:
    """Normalize one Foundry/assistant agent (dict or SDK object) to the Import
    Record shape. native id = ``{account_arm_id}/agents/{agent_id}`` so it's
    stable and never collides with a deployment id."""
    aid = _get(agent, "id")
    return {
        "native_resource_id": f"{proj.get('account_id')}/agents/{aid}",
        "name": _get(agent, "name") or aid,
        "status": "active",
        "cloud_provider": "azure",
        "platform": "azure_foundry",
        "framework": "azure_ai_foundry",
        "region": proj.get("region"),
        "model": _get(agent, "model"),
        "tools": _foundry_tools(agent),
    }


def _foundry_tools(agent: Any) -> List[str]:
    """Tool names from a Foundry/assistant agent definition."""
    raw = _get(agent, "tools") or []
    names: List[str] = []
    for t in raw:
        name = _get(t, "function", default=None)
        if isinstance(name, dict):
            name = name.get("name")
        names.append(name or _get(t, "type") or "tool")
    return names


def _http_list_assistants(endpoint: str, token: str) -> List[Dict[str, Any]]:
    """Default data-plane lister: GET {endpoint}/assistants (OpenAI-compatible).

    NOTE: needs live validation against a GA Foundry project (route/api-version
    may differ); injected ``agent_lister`` overrides this in tests and can patch
    it in one place if the contract shifts.
    """
    import urllib.request

    url = f"{endpoint.rstrip('/')}/assistants?api-version={_FOUNDRY_API_VERSION}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body.get("data", body if isinstance(body, list) else [])


# ------------------------------------------------------------- small helpers
def _get(obj: Any, attr: str, default: Any = None) -> Any:
    """Attr/key access that works for both SDK objects and plain dicts."""
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return getattr(obj, attr, default)


def _resource_group_of(arm_id: str) -> Optional[str]:
    m = _RG_RE.search(arm_id or "")
    return m.group(1) if m else None


def _deployment_model(dep: Any) -> Optional[str]:
    props = getattr(dep, "properties", None)
    model = getattr(props, "model", None) if props else None
    return getattr(model, "name", None) if model else None


def _deployment_state(dep: Any) -> str:
    props = getattr(dep, "properties", None)
    state = getattr(props, "provisioning_state", None) if props else None
    return state or "unknown"


def _secrets_manager_resolver(secret_ref: str) -> str:
    """Resolve an SP client-secret from AWS Secrets Manager by name/ARN.

    The stored ``secret_ref`` is a reference only (feature §14); the secret
    value is fetched at scan time and never persisted on the connection. The
    secret may be a raw string or a JSON object with a ``client_secret`` key.
    """
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    from app.config import settings

    client = boto3.client("secretsmanager", region_name=settings.aws_region)
    try:
        value = client.get_secret_value(SecretId=secret_ref).get("SecretString", "")
    except (ClientError, BotoCoreError) as exc:
        # Don't leak the raw boto message (it can echo the secret name/ARN + IAM
        # detail) up to the UI toast — return a clean, generic failure.
        logger.warning("secrets manager read failed for discovery SP: %s", exc)
        raise AzureDiscoveryError("vault reference unreadable (check secret name + IAM)") from exc
    if not value:
        return ""
    try:
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed.get("client_secret") or parsed.get("clientSecret") or ""
    except (ValueError, TypeError):
        pass
    return value
