# Aegion Guard (Python)

**Drop-in security validation for AI agent tool calls.** Aegion Guard routes every
tool call through the AegionAI security controller **before** it executes, and
blocks on `DENY` — so a prompt injection, policy violation, or unauthorized
cross-cloud action never reaches your bank API, identity provider, or telecom
backend.

```python
from aegion_guard import AegionGuard, ToolDenied

guard = AegionGuard(agent_id="acme-payments-agent")

@guard.tool(operation_type="WRITE")
def process_refund(account_id: str, amount: float) -> dict:
    return bank.refund(account_id, amount)        # runs ONLY if Sentra ALLOWs

with guard.session(session_id=sid, user_input=user_prompt):
    process_refund(account_id="A1", amount=50)    # raises ToolDenied on DENY
```

That's the whole integration: decorate your tools, wrap the request in a
`session(...)`, and the SDK assembles everything the controller needs
(`request_id`, `tool_name`, `tool_params`, `session_id`, `user_input`,
`operation_type`, `timestamp`) from the decorated function and the active session.

---

## Why it's built this way

- **Zero runtime dependencies** — stdlib `urllib` only. The same code vendors
  unchanged into an AWS Lambda zip *and* an Azure Function package (whose build
  doesn't reliably install pip deps).
- **Fail-secure by default** — if the controller is unreachable, times out, or
  returns garbage, the call is **denied**, not allowed. A control-plane outage
  must never silently let a risky tool run.
- **Sync *and* async** — decorate `def` or `async def`; the SDK does the right
  thing for each.
- **Server-side credentials** — the API key comes from the environment / your
  secret store and is never a function argument, never logged.

---

## Install

```bash
pip install aegion-guard          # from the package index
# or, for local development:
pip install -e demo-agents/sdk/aegion-guard-python
```

Requires Python 3.9+.

---

## Configure

Two values are required; both default to environment variables and can be
overridden in the constructor. The SDK validates them **at construction** and
raises a clear `ConfigError` if either is missing — you find out at startup, not
on the first tool call.

| Env var | Meaning | Required |
|---|---|---|
| `SENTRA_API_BASE` | API Gateway base **including the stage**, e.g. `https://<id>.execute-api.us-east-1.amazonaws.com/prod` | yes |
| `SENTRA_API_KEY` | usage-plan `x-api-key` (from Secrets Manager / Key Vault) | yes |
| `SENTRA_VALIDATE_TIMEOUT_S` | per-call timeout (default `10`) | no |
| `SENTRA_FAIL_SECURE` | `true` (default) ⇒ DENY on transport error | no |
| `SENTRA_CONNECT_RETRIES` | bounded retries on *connection* errors only (default `1`) | no |

```python
guard = AegionGuard(
    agent_id="acme-payments-agent",   # MUST be registered with the controller
    platform="bedrock",               # optional hint: bedrock | azure_foundry | vertex_ai
    cloud_region="us-east-1",         # optional hint
    timeout_s=30,                     # raise for cross-cloud cold paths (see below)
    on_decision=lambda d: log.info("decision", extra=d.__dict__),  # optional
)
```

> **`agent_id` must be pre-registered** with the controller. An unregistered id
> yields blanket denials (surfaced as `UnknownAgentError`, a subclass of
> `ToolDenied`).

---

## Runtime identity / request signing (opt-in)

Under a tenant in **`enforce`** mode the controller derives `(tenant_id, agent_id)`
from a **verified, agent-signed ES256 JWT** — not from the request body (LLD-26 §3 /
WS-A). To sign, install the extra and supply the agent's private key + `kid`:

```bash
pip install 'aegion-guard[identity]'
```

The extra is **kept out of the zero-dep core** so the validation path still vendors
unchanged into a Lambda zip / Azure Function (signing is impossible in pure stdlib).
When these env vars are all set, `AegionGuard(...)` signs **every** validate call —
**no code change**:

| Env var | Meaning |
|---|---|
| `SENTRA_TENANT_ID` | the agent's tenant (`tid` claim) |
| `SENTRA_AGENT_KID` | the `kid` the controller returned at registration |
| `SENTRA_AGENT_PRIVATE_KEY_FILE` | path to the agent's P-256 private key PEM (or `SENTRA_AGENT_PRIVATE_KEY` for the literal) |
| `SENTRA_TOKEN_TTL_S` | token lifetime, ≤ 900 (default 600) |

`agent_id` must be the canonical `{tenant}-{cloud}-{slug}-{hash}` and start with
`{tenant_id}-` — the SDK validates this at construction and fails fast.

**Provision an agent (operator):**

```bash
python -m aegion_guard.provision \
  --agent-id t_acme-aws-payments-ab12cd34 --tenant-id t_acme \
  --register --api-base https://<controller> --header 'x-amzn-oidc-data: <...>'
```

This generates the keypair (private key written `0600`), registers the **public** key
(returns the `kid`), and writes a `*.identity.env` scaffold to source. The private key
never leaves the agent host. Without identity env set, the SDK runs exactly as before
(unsigned) — appropriate for tenants in `off`/`shadow`.

---

## Usage

### Decorator (recommended)

```python
@guard.tool()                          # operation_type="auto" → inferred from name
def lookup_account(account_id): ...

@guard.tool(operation_type="WRITE")    # explicit — recommended for ALL writes
def transfer_funds(src, dst, amount): ...

with guard.session(session_id=sid, user_input=prompt):
    lookup_account("A1")
    transfer_funds("A1", "B2", 100)    # ToolDenied if the controller blocks it
```

### Async tools

```python
@guard.tool()
async def verify_identity(subscriber_id):
    return await idp.verify(subscriber_id)

with guard.session(session_id=sid, user_input=prompt):
    await verify_identity("SUB1")
```

### Explicit (no decorator)

```python
decision = guard.validate(
    tool_name="process_refund",
    tool_params={"account_id": "A1", "amount": 50},
    session_id=sid, user_input=prompt, operation_type="WRITE",
)
if decision.allowed:
    process_refund("A1", 50)
# async twin: await guard.avalidate(...)
```

### Cloud adapters

Turn a raw cloud event into the context the executor needs:

```python
from aegion_guard import from_bedrock_event, from_azure_request

# AWS Lambda (Bedrock action group)
def handler(event, _ctx):
    c = from_bedrock_event(event)
    try:
        with guard.session(c["session_id"], c["user_input"]):
            return ok(TOOLS[c["tool_name"]](**c["params"]))
    except ToolDenied as d:
        return blocked(d.reason)        # 403 → the model explains the denial

# Azure Function
async def tool_call(req):
    c = from_azure_request(req)
    with guard.session(c["session_id"], c["user_input"]):
        return await TOOLS[c["tool_name"]](**c["params"])
```

---

## `operation_type`: READ vs WRITE

`operation_type="auto"` infers WRITE from the tool name (`refund`, `transfer`,
`reset`, `port`, `change`, `create`, `update`, `modify`, `delete`, `write`).

**Auto is best-effort.** Substring matching can misfire — `get_update_history`
contains `update` and would be classified WRITE. **Pass `operation_type`
explicitly for every WRITE tool.** Explicit always wins.

---

## Errors

| Exception | When |
|---|---|
| `ToolDenied` | Controller returned `DENY`, or fail-secure tripped (`reason="validation_unavailable"`). The tool body did **not** run. |
| `UnknownAgentError` | `agent_id` is not registered (subclass of `ToolDenied`). |
| `SentraUnavailable` | Transport failed **and** `fail_secure=False` (you opted out of failing closed). |
| `ConfigError` | Missing/invalid config at construction (subclass of `ValueError`). |

`ToolDenied.decision` carries the full `Decision` (reason, threat_type,
matched_rule, severity, trust_score, latency_ms, request_id, raw) when one was
received.

---

## Timeouts & cross-cloud

The controller's own p95 is ~100–300ms, so the default `timeout_s=10` is
generous for same-cloud calls. **Cross-cloud** paths (e.g. an Azure Function
calling an AWS-hosted controller) can take **15s+ on cold starts** — raise
`timeout_s` to ~30 for those interceptors, or pre-warm the function.

`connect_retries` retries only *connection-establishment* failures (DNS,
refused). It never retries a read-timeout (that would just double the wait before
failing secure) and never retries a `DENY` (an authoritative decision).

---

## Development

```bash
pip install -e ".[dev]"
pytest                                  # unit + adapter tests (no network)
RUN_INTEGRATION=1 \
  SENTRA_API_BASE=… SENTRA_API_KEY=… AEGION_TEST_AGENT_ID=<registered> \
  pytest tests/test_contract_live.py    # live contract test (needs the stack)
```

---

## Security notes

- The API key is read from config/env and sent only on the server-side validate
  hop. It is never returned to a caller, included in `Decision`, or in the
  guard's `repr`.
- Anything that isn't a clean `ALLOW` — `DENY`, an unrecognized decision, a
  non-JSON body, a transport failure — results in the tool **not running**
  (under the default `fail_secure=True`).
- TLS certificate verification is always on.
