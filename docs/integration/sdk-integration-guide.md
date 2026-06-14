# AegionAI Guard — Python SDK Integration Guide

`aegion-guard` lets you govern an AI agent's tool calls with **one decorator per tool**. Each call is
validated by the AegionAI control plane *before* it runs — prompt-injection/jailbreak detection,
policy enforcement, rate limits, trust decay, and cross-cloud preconditions — and **fails secure**.

> **Two ways to integrate.** This SDK (recommended) for Python agents, or call `POST /v1/validate`
> directly from any language — see [`aegion-guard-api.openapi.yaml`](./aegion-guard-api.openapi.yaml).

---

## 1. Install

```bash
pip install aegion-guard
```

The SDK is **dependency-free (stdlib only)** so it drops cleanly into AWS Lambda / Azure Functions
without a build step.

## 2. Configure

Two required settings — the controller URL and your API key. Set them via **environment variables**
(recommended) or constructor args. The key is never logged.

```bash
export SENTRA_API_BASE="https://<host>/prod"      # required — no trailing /v1
export SENTRA_API_KEY="<your-tenant-api-key>"     # required — keep server-side, never in a browser
# optional:
export SENTRA_VALIDATE_TIMEOUT_S="2.0"            # per-call timeout (default 2s)
export SENTRA_FAIL_SECURE="true"                  # default true — see §6
```

```python
from aegion_guard import AegionGuard

guard = AegionGuard(
    agent_id="acme-payments-agent",   # must be registered + have a policy in AegionAI
    platform="bedrock",               # optional: bedrock | azure_foundry | vertex_ai
    cloud_region="us-east-1",         # optional
    # api_base / api_key / timeout_s / fail_secure can override the env here
)
```

Config is validated **at construction** — a missing key fails fast with a clear `ConfigError`, not at
the first tool call.

---

## 3. The two annotations — what, where, when

Integration is exactly two pieces:

### `@guard.tool(...)` — decorate every tool

```python
@guard.tool(operation_type="WRITE")
def process_refund(account_id: str, amount: float, txn_id: str | None = None) -> dict:
    ...   # body runs ONLY if AegionAI returns ALLOW
```

- **What it does:** before the function body runs, the SDK sends `{tool_name, tool_params, …}` to
  `/v1/validate`. On `ALLOW` the body runs; on `DENY` it raises `ToolDenied` and the body never runs.
- **Where:** on **every** tool function the agent can call — `tool_params` are taken automatically
  from the function's arguments (so name them meaningfully: `account_id`, `amount`, …).
- **When `operation_type`:** `"READ"` for data access, `"WRITE"` for state-changing actions
  (governs rollback eligibility). Default `"auto"` infers it from the tool name; set it explicitly
  for anything that moves money/data.
- Works on both `def` and `async def`.

### `guard.session(...)` — wrap each conversation turn

```python
with guard.session(session_id="sess-7f3a91", user_input="please refund my $120 order",
                   request_id="req-abc123"):
    process_refund(account_id="acct-1007", amount=120.0)
```

- **What it does:** binds the per-conversation context that every `@guard.tool` call inside the block
  needs — `session_id`, the end-user's `user_input` (what threat detection inspects), and a
  `request_id` for tracing. (Implemented with `contextvars`, so it's async- and thread-safe.)
- **Where/when:** open it once per **agent turn / conversation step**, around the tool calls that
  turn makes. Reuse the **same `session_id`** for the whole conversation so trust decay, quarantine,
  and cross-cloud preconditions accumulate correctly.

> **Rule of thumb:** `@guard.tool` answers *“is this action allowed?”*; `guard.session` supplies
> *“who's asking and what did they say?”*. A guarded tool called outside a session has no context to
> validate against — always wrap calls in a session.

### Which annotation when

| Situation | Use |
|---|---|
| A function that reads data or takes an action | `@guard.tool(operation_type="READ"|"WRITE")` on it |
| Starting to handle a user message / agent turn | `with guard.session(session_id, user_input, request_id=…):` |
| Same user, multiple turns | **Reuse the same `session_id`** across turns |
| You need to validate without a decorator (dynamic dispatch) | `guard.validate(tool_name=…, tool_params=…)` / `await guard.avalidate(…)` inside a session |

---

## 4. A complete example

```python
from aegion_guard import AegionGuard, ToolDenied

guard = AegionGuard(agent_id="acme-payments-agent", platform="bedrock")

@guard.tool(operation_type="READ")
def get_transactions(account_id: str, limit: int = 10) -> dict:
    return {"account_id": account_id, "transactions": db.recent(account_id, limit)}

@guard.tool(operation_type="WRITE")
def process_refund(account_id: str, amount: float) -> dict:
    return bank.refund(account_id, amount)

def handle_turn(session_id: str, user_text: str, request_id: str):
    with guard.session(session_id=session_id, user_input=user_text, request_id=request_id):
        try:
            txns = get_transactions(account_id="acct-1007", limit=5)   # validated → ALLOW → runs
            return process_refund(account_id="acct-1007", amount=120)   # validated before it runs
        except ToolDenied as denied:
            # Blocked by AegionAI — do NOT retry the raw action; surface the reason.
            return {"blocked": True, "reason": denied.reason, "threat_type": denied.threat_type}
```

---

## 5. Framework adapters

Agent frameworks deliver tool calls in their own request shapes. The adapters turn those into the
session/params the SDK expects, so you don't parse them by hand.

### AWS Bedrock Agents (Action Group Lambda)

```python
from aegion_guard import from_bedrock_event

def handler(event, context):
    ctx = from_bedrock_event(event)          # -> {session_id, user_input, request_id, tool_name, params}
    with guard.session(ctx["session_id"], ctx["user_input"], request_id=ctx["request_id"]):
        result = TOOLS[ctx["tool_name"]](**ctx["params"])
    return bedrock_response(event, result)
```

### Azure Functions (Python v2)

```python
from aegion_guard import from_azure_request

ctx = from_azure_request(req)                 # parses route param {tool_name} + JSON body
with guard.session(ctx["session_id"], ctx["user_input"], request_id=ctx["request_id"]):
    result = await TOOLS[ctx["tool_name"]](**ctx["params"])
```

### Any other framework

Build the context yourself and open a session — the decorators do the rest:

```python
with guard.session(session_id=sid, user_input=prompt, request_id=rid):
    my_tool(**params)
```

---

## 6. Fail-secure & latency

- **Fail secure (default):** if the controller is unreachable or times out, a guarded tool **raises
  `ToolDenied(reason="validation_unavailable")`** — the action is blocked, not silently allowed. Set
  `SENTRA_FAIL_SECURE=false` (or `fail_secure=False`) only if you explicitly prefer availability over
  safety for a given agent.
- **Timeout:** `SENTRA_VALIDATE_TIMEOUT_S` (default `2.0`s). Cross-cloud interceptors (e.g. Azure →
  AWS) should use a larger value (the SDK default for those agents is higher).
- **Latency budget:** validation adds ~tens of ms in-region; the ML classifier only adds model time
  on the borderline cases it escalates.

---

## 7. Errors you should handle

| Exception | When | What to do |
|---|---|---|
| `ToolDenied(reason, threat_type)` | AegionAI returned DENY, **or** fail-secure tripped | Don't run/retry the action; surface `reason` |
| `UnknownAgentError` *(subclass of ToolDenied)* | `agent_id` isn't registered / has no policy | Fix `agent_id` or register the agent |
| `SentraUnavailable` *(subclass of ToolDenied)* | Controller unreachable (fail-secure) | Alert ops; the call was safely blocked |
| `ConfigError` | Missing/invalid `api_base`/`api_key`/`agent_id` (at construction) | Fix configuration |

All inherit from `AegionGuardError`, so a single `except AegionGuardError` catches everything.

```python
from aegion_guard import ToolDenied, ConfigError, AegionGuardError
```

---

## 8. Testing without the live controller

Point the SDK at a stub or assert on `ToolDenied`. A typical pattern is a tiny in-process fake that
implements `POST /v1/validate` and wire it via `api_base`. For end-to-end checks, set
`RUN_INTEGRATION=1` and the real `SENTRA_API_BASE`/`SENTRA_API_KEY`. Because the SDK fails secure,
your tests should cover both the ALLOW path and the DENY/`ToolDenied` path.

---

## 9. Non-Python agents

Call `POST /v1/validate` directly — the request/response contract is in
[`aegion-guard-api.openapi.yaml`](./aegion-guard-api.openapi.yaml)
(render it with `npx @redocly/cli preview-docs`). Mirror the SDK's behavior: send the same
`session_id` across a conversation, thread `request_id`, validate **before** executing, and treat a
non-200 / timeout as **DENY** (fail secure).
