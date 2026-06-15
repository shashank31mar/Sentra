"""AzureScanner — orchestrator + Cognitive Services / AI Foundry sub-scanners.

All Azure SDK and vault access is stubbed via the scanner's injection seams
(secret_resolver / credential_factory / client_factory / endpoint_lister /
agent_lister) and a fake shared context, so these run with no azure-* packages
and no live subscription.
"""
from app.services.scanners.azure_scanner import (
    AzureScanner,
    _AzureContext,
    _CognitiveDeploymentScanner,
    _FoundryAgentScanner,
)

_CREDS = {"subscription_id": "sub", "tenant_id": "ten", "client_id": "cli", "secret_ref": "ref"}


# --- fakes mirroring azure-mgmt-cognitiveservices shapes --------------------
class _Model:
    def __init__(self, name): self.name = name


class _DepProps:
    def __init__(self, model): self.model = _Model(model); self.provisioning_state = "Succeeded"


class _Dep:
    def __init__(self, name, model):
        self.id = ("/subscriptions/sub/resourceGroups/rg/providers/"
                   f"Microsoft.CognitiveServices/accounts/acct/deployments/{name}")
        self.name = name
        self.properties = _DepProps(model)


class _AcctProps:
    def __init__(self, endpoint): self.endpoint = endpoint


class _Acct:
    def __init__(self, kind="OpenAI", endpoint="https://acct.services.ai.azure.com"):
        self.id = ("/subscriptions/sub/resourceGroups/rg/providers/"
                   "Microsoft.CognitiveServices/accounts/acct")
        self.name = "acct"; self.kind = kind; self.location = "centralus"
        self.properties = _AcctProps(endpoint)


class _FakeMgmtClient:
    def __init__(self, accounts, deployments):
        class _Accounts:
            def list(_self): return accounts

        class _Deployments:
            def list(_self, rg, acct): return deployments
        self.accounts = _Accounts()
        self.deployments = _Deployments()


def _ctx(accounts=None, deployments=None, credential="cred"):
    """A fake shared context — the sub-scanners read accounts/mgmt_client/credential off it."""
    accounts = accounts or []
    mgmt = _FakeMgmtClient(accounts, deployments or [])
    return _AzureContext(_CREDS, credential, mgmt, accounts)


# --- deployment sub-scanner --------------------------------------------------
def test_deployment_scanner_lists_deployments():
    ctx = _ctx(accounts=[_Acct(kind="OpenAI")], deployments=[_Dep("gpt4o", "gpt-4o-mini")])
    ok, agents, _ = _CognitiveDeploymentScanner().discover(ctx)
    assert ok and len(agents) == 1
    a = agents[0]
    assert a["platform"] == "azure_foundry" and a["framework"] == "azure_openai"
    assert a["model"] == "gpt-4o-mini" and a["tools"] == []


def test_deployment_scanner_skips_non_ai_kinds():
    ctx = _ctx(accounts=[_Acct(kind="SpeechServices")], deployments=[_Dep("x", "m")])
    ok, agents, _ = _CognitiveDeploymentScanner().discover(ctx)
    assert ok and agents == []


# --- foundry sub-scanner (injected endpoint + agent listers) ----------------
def test_foundry_scanner_maps_agents_with_tools():
    endpoints = [{"account_id": "/subscriptions/sub/.../accounts/acct",
                  "account_name": "acct", "endpoint": "https://acct.ai.azure.com",
                  "region": "centralus"}]
    fake_agents = [{
        "id": "asst_123", "name": "acme-identity-agent", "model": "gpt-4o-mini",
        "tools": [{"type": "function", "function": {"name": "verify_identity"}},
                  {"type": "code_interpreter"}],
    }]
    sub = _FoundryAgentScanner(
        endpoint_lister=lambda ctx: endpoints,
        agent_lister=lambda proj, ctx: fake_agents,
    )
    ok, agents, _ = sub.discover(_ctx())
    assert ok and len(agents) == 1
    a = agents[0]
    assert a["framework"] == "azure_ai_foundry"
    assert a["native_resource_id"].endswith("/agents/asst_123")
    assert a["model"] == "gpt-4o-mini"
    assert a["tools"] == ["verify_identity", "code_interpreter"]


def test_foundry_scanner_empty_when_no_projects():
    sub = _FoundryAgentScanner(endpoint_lister=lambda ctx: [])
    ok, agents, msg = sub.discover(_ctx())
    assert ok and agents == [] and "0 foundry agents" in msg


def test_foundry_scanner_reports_skip_when_all_projects_fail():
    def boom(proj, ctx):
        raise RuntimeError("404 Not Found")
    sub = _FoundryAgentScanner(
        endpoint_lister=lambda ctx: [{"endpoint": "https://x", "account_id": "a"}],
        agent_lister=boom,
    )
    ok, agents, msg = sub.discover(_ctx())
    assert not ok and agents is None and "foundry agent-list failed" in msg


def test_foundry_scanner_derives_endpoints_from_context():
    """Default endpoint discovery reads AIServices accounts off the shared ctx."""
    ctx = _ctx(accounts=[_Acct(kind="AIServices", endpoint="https://proj.ai.azure.com")])
    sub = _FoundryAgentScanner(agent_lister=lambda proj, ctx: [])  # no agents, but endpoint found
    ok, agents, msg = sub.discover(ctx)
    assert ok and agents == [] and "0 foundry agents" in msg  # AIServices acct → project found, 0 agents


# --- orchestrator ------------------------------------------------------------
class _StubSub:
    def __init__(self, result): self._result = result
    def discover(self, ctx): return self._result


def _orch(sub_scanners, secret_resolver=None, accounts=None):
    """Orchestrator wired with trivial factories so _build_context succeeds."""
    return AzureScanner(
        secret_resolver=secret_resolver or (lambda ref: "s"),
        credential_factory=lambda **kw: "cred",
        client_factory=lambda cred, sub: _FakeMgmtClient(accounts or [], []),
        sub_scanners=sub_scanners,
    )


def test_orchestrator_merges_and_dedupes():
    dep = {"native_resource_id": "dep-1", "name": "gpt4o", "tools": []}
    foundry = {"native_resource_id": "agent-1", "name": "acme", "tools": ["verify_identity"]}
    scanner = _orch([
        _StubSub((True, [dep], "1 model deployments")),
        _StubSub((True, [foundry], "1 foundry agents")),
    ])
    ok, agents, msg = scanner.discover(_CREDS)
    assert ok and len(agents) == 2
    assert "2 agents visible" in msg


def test_orchestrator_ok_if_any_subscanner_ok_and_surfaces_skip():
    foundry = {"native_resource_id": "agent-1", "name": "acme"}
    scanner = _orch([
        _StubSub((False, None, "deployment discovery failed: boom")),
        _StubSub((True, [foundry], "1 foundry agents")),
    ])
    ok, agents, msg = scanner.discover(_CREDS)
    assert ok and len(agents) == 1
    assert "skipped:" in msg and "boom" in msg  # partial failure surfaced (nit #1)


def test_orchestrator_fails_when_all_fail():
    scanner = _orch([
        _StubSub((False, None, "deployment discovery failed: boom")),
        _StubSub((False, None, "foundry project discovery failed: nope")),
    ])
    ok, agents, msg = scanner.discover(_CREDS)
    assert not ok and agents is None and "discovery" in msg


def test_orchestrator_resolves_secret_once():
    """One secret read per discover(), shared across both sub-scanners (nit #2)."""
    calls = []
    scanner = _orch(
        [_StubSub((True, [{"native_resource_id": "a"}], "x")), _StubSub((True, [], "y"))],
        secret_resolver=lambda ref: (calls.append(ref) or "s"),
    )
    scanner.discover(_CREDS)
    assert len(calls) == 1


def test_orchestrator_missing_creds():
    scanner = _orch([_StubSub((True, [], "x"))])
    ok, agents, msg = scanner.discover({"subscription_id": "sub"})
    assert not ok and "missing" in msg
