# LLD 18: Deterministic Enforcement — Demo Runner + Customer SDK

**Version**: 0.2.1 (Second-pass review consistency fixes — ready for approval)
**Last Updated**: 2026-05-27
**Status**: Draft – Ready for Approval
**Owner**: Founder

**Change log since v0.2** (Kiro second-pass review):
- §4.4: `intent: enforcement + prompt:` upgraded from WARN to **HARD ERROR**. Per-step opt-out `allow_llm_path: true` documented in new §4.4.1 — friction is the point; code reviewers see the flag and ask why.
- §4.2.3: Added explicit sequencing dep note — `BedrockSchemaFetcher` (Workstream M3.2) must ship before M1's invoker can run live. Ship order is M3.2 → M1.1 → M1.6 → M1.7.
- §9.1 / §9.3 reconciled: legacy `audit_lookup_fn` is **removed in Phase 1 (M3.6)**, not "deprecated in Phase 3." No rollback path; image-version pinning is sufficient.
- §10.2: Added T-INT-06 (FAIL_OPEN structured log emits with telemetry=false), T-INT-07 (sentinel metric emits unconditionally), T-INT-08 (byte-identical parity test).
- §10.3: Added T-RUN-08 through T-RUN-15 covering schema-aware typing, synthetic guardrail emission, intent-field validator rules, single-AG constraint, and the M3.6 cleanup regression guard. Total test inventory: 14 SDK + 8 INT + 15 RUN = **37 tests**.
- §11.1: Reconciled with §5.8's telemetry decision. v0.1 monitoring is **structured-log-channel based** (CloudWatch Logs Insights / Datadog log metrics on `sentra.validate.error`, `sentra.validate.fail_open`, `sentra.validate.deny`). Prometheus-named metrics (other than the `sentra_validate_fail_open_total` sentinel) deferred to v0.2 with `sentra-sdk-prometheus`.

**Change log since v0.1**:
- §4.2: Synthetic Bedrock event builder is now **schema-aware**. Reads the agent's Action Group OpenAPI schema (cached by M3's fetcher) and emits properly-typed `properties` entries — integers as integer, booleans as boolean. The earlier "stringify everything" pseudo-code was a regression risk (P0).
- §4.2: Added explicit note that **direct-invoke is one Lambda call per scenario step**; multi-tool-call sessionAttributes propagation isn't applicable. Each step is its own correlation unit.
- §4.2 / new §4.2.4: Direct-invoke now **emits a synthetic `bedrock_guardrail` ALLOW signal** with `metadata={"direct_invoke": true}` so LLD 17 §4 symmetric-emission stays invariant. Dashboard expander explicitly shows "🟧 Bedrock Guardrail: ALLOW (direct-invoke, LLM bypassed)".
- §4.2: Scoped v0.1 to **single-action-group agents** (`customer_tools` hardcoded). Documented the lift-path to YAML-supplied action_group when a demo agent grows a second action group. Customers' SDK adoption is unaffected (decorator runs inside their Lambda, never sees ARNs).
- §4 / new §4.4: Scenario steps now require an `intent: enforcement | threat_detection` field. Validator (M3) blocks direct-invoke (`tool:`) on `threat_detection` steps so sigma-rule probes can't accidentally skip the LLM and silently pass.
- §5.4 / §5.5: SDK's `bedrock_action_group_handler` is **factored from** the existing `lambda/bedrock_agent_actions/index.py`, not rewritten. M7 adds a byte-identical-envelope parity test against the legacy code path before deletion.
- §5.7 / §6.1: Added explicit caveat that `tool_params` values must be JSON-serializable; rich types (enums, dataclasses) require a custom `params_extractor`.
- §5.8: Telemetry decision **locked**. Default = structured JSON logs always emitted; OTel push opt-in via `SENTRA_TELEMETRY=true`; Prometheus exporter deferred to v0.2 in a separate `sentra-sdk-prometheus` package. Resolves v0.1 open question #1.
- §8.4 / §11.4: `sentra_validate_fail_open_total` emitted **unconditionally** as a sentinel metric, even with telemetry disabled. Kill-switch alarm now always visible to monitoring.
- §11.2 / §7: Scenario validator strict-mode is **always-on in dev cluster** (our `sentra-mvp-cluster` IS the demo target). Permissive mode is a local-dev-only `SCENARIO_VALIDATION_STRICT=false` opt-out.
- §14: Removed open question #1 (resolved by §5.8 lock-in). Open question #2 reframed as a v0.2 design note rather than v0.1 punt.

**Prerequisites**:
- [LLD 03: Security Controller](03-security-controller.md) — `/v1/validate` contract
- [LLD 13: Demo Orchestrator](13-demo-orchestrator.md) — scenario YAML format
- [LLD 15: Cross-Cloud Connectors](15-cross-cloud-connectors.md) — current Bedrock + Azure invocation paths
- [LLD 17: Validation Signal Store](17-validation-signal-store.md) — `request_id` correlation, decisions endpoint

**Related Documents**:
- [Workstream 18](../tasks/workstream-18-deterministic-enforcement.md) — execution plan
- [best-practices.md §12](../best-practices.md) — when to use which read path

---

## Table of Contents

1. [Overview](#1-overview)
2. [Why Now — The S2 Debugging Spiral](#2-why-now--the-s2-debugging-spiral)
3. [Architecture — Enforcement Layer Pattern](#3-architecture--enforcement-layer-pattern)
4. [Component A: Demo Runner Determinism](#4-component-a-demo-runner-determinism)
5. [Component B: Customer SDK](#5-component-b-customer-sdk)
6. [Data Models & Interfaces](#6-data-models--interfaces)
7. [Configuration](#7-configuration)
8. [Error Handling & Fail-Mode Policy](#8-error-handling--fail-mode-policy)
9. [Migration Plan](#9-migration-plan)
10. [Test Plan](#10-test-plan)
11. [Operational Considerations](#11-operational-considerations)
12. [Cost Model](#12-cost-model)
13. [Out of Scope (Phase 1)](#13-out-of-scope-phase-1)
14. [Open Questions](#14-open-questions)
15. [Cross-References](#15-cross-references)

---

## 1. Overview

### 1.1 Purpose

Two intertwined problems, one underlying cause:

1. **Our cross-cloud demo scenarios are flaky** because they rely on Bedrock LLMs choosing to invoke a tool. The LLM is non-deterministic — it may answer from memory, decline politely, or hit a Sigma rule on the directive prompt. When the LLM doesn't invoke the tool, Sentra is never consulted, and the demo silently "passes" with a false ALLOW.

2. **Our customers face the same problem** when integrating Sentra into their production agent fleets: their agents only call `/v1/validate` if the tool-execution layer is wired to do so. Today, that requires hand-editing every Action Group Lambda, every Azure Function tool handler, every GCP Vertex function. Repeatedly. With drift.

The fix in both cases is the same architectural pattern: **the enforcement decision should live at the tool-execution layer, not at the LLM-tool-selection layer.** This LLD specifies two artifacts that realize that pattern:

- **Demo runner**: a `bedrock_tool_invoker` that calls the Action Group Lambda directly via `boto3.lambda.invoke()`, mirroring how Azure's `default_azure_tool_invoker` already POSTs directly to the Azure Function. Plus a template-substitution layer for dynamic parameters and a scenario-YAML validator that catches schema mismatches at load time.
- **Customer SDK** (`sentra-sdk-python` v0.1): a decorator + Lambda Layer that wraps any function with a `/v1/validate` call. One line per tool, zero changes to agent prompts or schemas.

### 1.2 Scope

| In scope | Out of scope |
|---|---|
| `default_bedrock_tool_invoker` factory mirroring `default_azure_tool_invoker` | Removing the existing prompt-based invocation path (kept for scenarios that intentionally test LLM behavior) |
| Template substitution for `{state}`, `{customer_id}`, `{request_id}`, etc., in scenario YAMLs | Generative test data (faker-style synthesis) |
| Scenario YAML schema validator (validates `tool_params` against agent's OpenAPI on demo-orchestrator startup) | Static analysis of customer code |
| `sentra-sdk-python` v0.1 — `@sentra.validate(...)` decorator | Java / Go / Node SDKs (Phase 2) |
| Lambda Layer packaging for the SDK | One-click CloudFormation install |
| Azure Functions decorator variant | Azure Function App templating |
| Reference Lambda showing decorator usage | Auto-instrumentation (LLM agents that emit traces) |
| Operational runbook + cost model | Transparent forwarding proxy (Phase 2) |

### 1.3 Non-Goals

- Not a replacement for the LLM-driven path. Customers who want the LLM to mediate tool selection still get that — we only ensure the *enforcement decision* always lands at the tool boundary.
- Not a new validation pipeline. Sentra's `/v1/validate` semantics are unchanged. The SDK is a client.
- Not auto-discovery of agents. Customers explicitly annotate which functions are agent-callable tools.

---

## 2. Why Now — The S2 Debugging Spiral

The motivation is concrete. S2 ("cross-cloud policy propagation") spent a full day in a debugging spiral that exposed the asymmetry between our two clouds:

| Date | Attempt | Outcome |
|---|---|---|
| 2026-05-26 | Initial S2 run | probe_bedrock_after & probe_azure_after both ALLOW (expected DENY). Reason: policy update only touched customer-service-agent, not verification-agent. |
| 2026-05-26 evening | Hook extended to update both policies | probe_azure_after now DENY ✅. probe_bedrock_after still ALLOW ❌. Reason: LLM-driven prompt "Look up customer C0001" — LLM answered from memory, never invoked `query_customers`. |
| 2026-05-27 morning | Prompt rewritten: "Use the query_customers tool to retrieve … customer_id='C0001'" | Still ALLOW. Reason: `query_customers` takes a `state` param, not `customer_id`. LLM looked at the OpenAPI schema, saw no match, answered from memory. |
| 2026-05-27 mid-morning | Prompt rewritten: "Use the query_customers tool with state='CA' to retrieve all customers in California" | probe_bedrock_before flipped to DENY (PROMPT_INJECTION). Reason: Sigma rule `prompt_injection_basic.yaml` Selection 8 has `"retrieve all customers"` as an exfiltration pattern. |
| 2026-05-27 mid-day | Prompt rewritten: "Call the query_customers tool with state='CA' and return the response." | LLM still didn't invoke the tool. 15 second latency, natural-language response, no `/v1/validate` call ever happened. |

The accumulated lesson: **prompt engineering can't reliably force tool invocation.** Every iteration either trips a Sigma rule, mismatches the schema, or just gets ignored by the model. Even when it works once, it's not reproducible across model versions, demo runs, or sessions.

Meanwhile, the **Azure side worked correctly from the second attempt onward** — because the Azure invoker POSTs directly to `/api/tool/check_fraud_score` on the Azure Function App, which calls `/v1/validate` deterministically. No LLM in the loop.

We have an asymmetry baked into the runner:
- **Azure**: dashboard → Azure Function `/api/tool/{name}` → `/v1/validate` (deterministic)
- **Bedrock**: dashboard → `bedrock-runtime.invoke_agent()` (LLM) → maybe Action Group Lambda → `/v1/validate` (probabilistic)

This LLD removes that asymmetry.

### 2.1 The cost of NOT fixing this

| Cost | Today | If unfixed |
|---|---|---|
| Demo flakes during sales calls | We've already had to debug live | Will recur every model version change |
| Engineer time debugging false-fails | ~12 hours in 2 days for S2 alone | S3/S4/S5… each adds another debug spiral |
| Customer integration friction | Customers hand-edit every Lambda | Adoption stalls; design partner churn |
| Trust in the demo narrative | "Did Sentra actually catch this, or did the LLM just refuse?" | Investors / customers ask this every time |

---

## 3. Architecture — Enforcement Layer Pattern

### 3.1 The pattern (already exists, restated cleanly)

Every cloud has three concerns when an agent invokes a tool:

1. **Tool selection** — usually an LLM picks the tool name + parameters
2. **Authorization** — does this agent have permission to call this tool?
3. **Execution** — actually run the tool code

The **enforcement layer** is whatever code runs between (1) and (3) and calls `/v1/validate`. Today:

| Cloud | Enforcement layer | Where it lives | What it does |
|---|---|---|---|
| AWS Bedrock | Action Group Lambda (`bedrock_agent_actions/index.py`) | `lambda/bedrock_agent_actions/` | Receives Bedrock event → POST `/v1/validate` → if ALLOW, execute the tool body, else return 403 |
| Azure Foundry | Azure Function App (`function_app.py`) | `src/connectors/azure_foundry/azure_function/` | Receives HTTP POST → POST `/v1/validate` → if ALLOW, execute, else 403 |
| GCP Vertex (future) | Vertex Function | (not yet built) | Same shape |

The enforcement layer is the **moral equivalent of a security middleware** in a web framework — it sits in front of the business logic, makes the auth call, and either lets the request through or rejects it.

### 3.2 Two ways to drive the enforcement layer

There are two interfaces into any enforcement layer:

```
        ┌─────────────────────────────────────────────────────────────┐
        │                                                             │
        │   (A) LLM-driven path                                       │
        │   ─────────────────                                         │
        │   user prompt → LLM → "I'll use tool X with params Y" →     │
        │   Bedrock Agent / Azure Foundry invokes enforcement layer   │
        │                                                             │
        │   ✓ Realistic (matches production traffic shape)            │
        │   ✗ Non-deterministic — LLM may refuse, hallucinate, or     │
        │     pick a different tool                                   │
        │   ✗ Slow (full LLM turn, 5-15s)                             │
        │                                                             │
        ├─────────────────────────────────────────────────────────────┤
        │                                                             │
        │   (B) Direct invocation path                                │
        │   ─────────────────────────                                 │
        │   caller picks tool + params → invoke enforcement layer     │
        │   directly (HTTP POST or boto3 lambda.invoke)               │
        │                                                             │
        │   ✓ Deterministic — same input, same output                 │
        │   ✓ Fast (~0.5-1.5s)                                        │
        │   ✓ Same enforcement code runs                              │
        │   ✗ Skips LLM — not appropriate for scenarios claiming      │
        │     "the LLM made the wrong choice and Sentra caught it"   │
        │                                                             │
        └─────────────────────────────────────────────────────────────┘
```

**Critical observation**: path (B) doesn't skip Sentra. It skips the LLM. The enforcement layer is unchanged — the same Lambda or Function runs, the same `/v1/validate` call fires, the same DENY-or-ALLOW path executes.

### 3.3 Which path each scenario should use

Per-scenario, per-step decision:

| Scenario claim | Path | Why |
|---|---|---|
| "Sentra catches a prompt-injection attack" | A — LLM-driven | The attack vector IS the LLM input. Need the LLM in the loop. |
| "Sentra catches a sigma rule (e.g., PII regex)" | A — LLM-driven | Same as above; the user prompt is the threat surface. |
| "Sentra enforces tool-authorization policy" | **B — Direct** | The claim is about policy enforcement at the tool boundary, regardless of how the tool was picked. |
| "Sentra propagates a policy change across clouds" (S2) | **B — Direct** | Claim is about enforcement landing both places; LLM choice is incidental. |
| "Sentra blocks cross-agent escalation" | Either, scenario-dependent | A if testing LLM reasoning; B if testing the cross-agent dependency check itself. |
| "Sentra catches a quarantined session" (S4) | **B — Direct** | Quarantine logic should fire regardless of LLM behavior. |

**The default should be B for any scenario whose claim is about Sentra's enforcement logic**, with A reserved for scenarios that intentionally test LLM-side behavior.

### 3.4 Why the same pattern serves customers

Customers face the production-mirror version of the same problem. Their agents:

1. Use an LLM (or sometimes a deterministic workflow) to pick tools
2. Their Bedrock Action Group Lambda / Azure Function / Vertex Function executes the tool
3. They want Sentra to authorize step (2)

The customer doesn't care about (1) — that's their LLM provider's problem. They care that every tool execution path is enforceable. The SDK gives them a one-line annotation that ensures it.

```python
# Without the SDK — what customers do today
def query_customers(state):
    # Customer copies our validate_with_sentra() helper from the demo,
    # or writes their own. Drift across teams. Maintenance burden.
    result = validate_with_sentra(
        tool_name="query_customers",
        agent_id="customer-service",
        ...
    )
    if result["decision"] == "DENY":
        return error_response(result["reason"])
    # ... actual tool logic
    return data

# With the SDK — what customers do tomorrow
@sentra.validate(tool_name="query_customers", agent_id="customer-service")
def query_customers(state):
    # ... actual tool logic
    return data
```

The decorator IS the enforcement layer. The customer's function is unchanged; the decorator interposes the validate call.

---

## 4. Component A: Demo Runner Determinism

### 4.1 Goals

1. Every scenario step should be reproducible across runs — same input, same outcome.
2. Scenarios should be able to opt into LLM-driven paths *deliberately*, not by accident.
3. Scenarios should be able to express dynamic parameters (per-fire random `customer_id`, `transaction_id`) without YAML duplication.
4. Scenario YAMLs should fail to load if they reference tools / params that don't exist in the agent's policy — not silently produce wrong results at runtime.

### 4.2 Sub-component A1: `default_bedrock_tool_invoker`

**File**: `src/dashboard/components/cross_cloud_scenarios.py`

A new factory mirroring `default_azure_tool_invoker`. The invoker accepts a scenario step where `step.tool` and `step.tool_params` are set, builds a **schema-aware** synthetic Bedrock Action Group event payload, invokes the Lambda via boto3, and parses the OpenAPI envelope response.

#### 4.2.1 Correlation semantics — one invocation per step

Direct-invoke is **one Lambda call per scenario step**. The synthetic event preserves the `sessionAttributes.sentra_request_id` field so the Lambda's existing `request_id` extraction logic ([LLD 17 §9.1.3](17-validation-signal-store.md)) works unchanged — but the *multi-tool-call sequencing semantics* that `sessionAttributes` exists for (Bedrock Agent forwarding the same attributes across N tool invocations in one LLM turn) **don't apply** here. Each direct-invoke step is its own correlation unit, with its own `request_id`. Reviewers reading LLD 17 + LLD 18 together should not assume the multi-call propagation behavior is preserved — it isn't, by design.

#### 4.2.2 v0.1 scope — single Action Group per agent

All three Bedrock agents in our current demo (`sentra-mvp-customer-service-agent`, `…-naive`, `…-unsecured`) have exactly one Action Group, `customer_tools`, backed by the `sentra-mvp-bedrock-agent-actions` Lambda. v0.1 hardcodes this: the invoker is constructed with one `lambda_arn` and one `action_group="customer_tools"` default, and every direct-invoke step routes there.

**Constraint**: scenario YAMLs cannot author direct-invoke steps for agents with multiple Action Groups. This is enforced by M3 (scenario validator) — if an agent has more than one Action Group AND a step uses `tool:`, validation fails fast.

**Lift path** (when needed): add an optional `action_group: <name>` field to scenario steps; runner uses it to pick the right `lambda_arn` from a `(agent_id, action_group) → arn` map. The map is loaded once per orchestrator startup, either from a CDK-exported config file or fetched live via `bedrock-agent.list-agent-action-groups`. Until a demo agent grows a second Action Group, this lift is deferred (tracked in §13 Out of Scope).

**Customer-side impact**: zero. Customers using the SDK never deal with this concept — the decorator runs *inside* their Lambda, which is already inside whichever Action Group the customer's CDK wired it to.

#### 4.2.3 Schema-aware event construction

The Lambda's `requestBody.content["application/json"].properties` array uses **typed values** — `{name, type, value}` where `type` is `string | integer | boolean | number | array`. Bedrock-native events get their types from the Action Group's OpenAPI schema. Direct-invoke must do the same; otherwise an integer param arrives as `"42"` not `42` and the Lambda's parameter parsing breaks for any tool that expects a non-string.

The invoker reads the agent's OpenAPI schema (via the cached `BedrockSchemaFetcher`) and builds typed `properties` entries.

**Sequencing dependency (cross-references workstream M3.2 → M1.7)**: `BedrockSchemaFetcher` is the deliverable of [Workstream 18 Task 3.2](../tasks/workstream-18-deterministic-enforcement.md). The fetcher must ship before M1's invoker can run live (M1.7), because the invoker takes `schema_fetcher` as an injected dependency in its constructor (see §4.2.5). The workstream's M3 entry depends on M1 in the dep table only for *test integration order* — the schema fetcher's code path itself (Task 3.2) ships first, then M1's invoker imports it, then M1's live run validates the wiring end-to-end. Concretely: ship order is **M3.2 → M1.1 → M1.6 → M1.7**, even though M3's *validator startup integration* (Task 3.4) lands later in the M3 sequence.

```python
# Pseudo-code — read M3's cached schema to type-tag each param
def _build_properties(tool_name: str, params: dict, schema: dict) -> list[dict]:
    tool_schema = schema[tool_name]  # M3.2 caches per-agent OpenAPI
    props = []
    for name, value in params.items():
        declared_type = tool_schema["parameters"].get(name, {}).get("type", "string")
        # Map OpenAPI types → Bedrock event types
        bedrock_type = {
            "integer": "integer", "number": "number",
            "boolean": "boolean", "array": "array",
        }.get(declared_type, "string")
        props.append({"name": name, "type": bedrock_type, "value": value})
    return props
```

Unknown params (in `tool_params` but not in the schema) fail validation at M3 startup — the runner never sees them.

#### 4.2.4 Symmetric `bedrock_guardrail` signal emission

LLD 17 §4 mandates that every signal *producer* emits exactly one signal per invocation. The LLM-driven path satisfies this: `BedrockConnector` posts a `bedrock_guardrail` signal (ALLOW or DENY) after every agent invocation. Direct-invoke bypasses `BedrockConnector` entirely, which would silently violate the rule — the dashboard's signals expander would see Sentra rows but no edge row, making "Bedrock Guardrail wasn't consulted" indistinguishable from "Bedrock Guardrail wasn't deployed."

The invoker therefore emits a **synthetic `bedrock_guardrail` ALLOW signal** after each successful direct-invoke, with metadata flagging the path:

```python
# After the Lambda response is parsed and OUTCOME assembled, before return:
signals_client.post_signal(
    session_id=session_id,
    request_id=step.request_id,
    source="bedrock_guardrail",
    decision="ALLOW",
    reason="direct-invoke (LLM bypassed for deterministic scenario run)",
    priority=BEDROCK_GUARDRAIL_PRIORITY,
    agent_id=step.agent_id,
    platform="bedrock",
    cloud_region=region,
    metadata={"direct_invoke": True, "invoker": "default_bedrock_tool_invoker"},
)
```

The dashboard UI renders this as: **🟧 Bedrock Guardrail: ALLOW (direct-invoke, LLM bypassed)** — honest about what happened, symmetric-emission preserved.

#### 4.2.5 Interface (pseudo-code)

```python
def default_bedrock_tool_invoker(
    *,
    lambda_arn: str,                      # ARN of sentra-mvp-bedrock-agent-actions (v0.1 single AG)
    action_group: str = "customer_tools", # v0.1 hardcoded; see §4.2.2 lift path
    schema_fetcher: BedrockSchemaFetcher, # injected; M3.2 owns the cache
    signals_client: SignalsClient,        # for §4.2.4 synthetic bedrock_guardrail emit
    region: str = "us-east-1",
) -> Invoker:
    """Return an Invoker that directly invokes the Action Group Lambda.

    Skips Bedrock Agent + LLM entirely. The Lambda's body is unchanged —
    it still calls /v1/validate first, then executes the tool. Sentra is
    consulted on every invocation, deterministically.

    Each invocation is its own correlation unit (§4.2.1). A synthetic
    bedrock_guardrail ALLOW signal is posted post-invoke to preserve
    LLD 17 §4 symmetric-emission (§4.2.4).
    """
    client = boto3.client("lambda", region_name=region)

    def invoke(step: CrossCloudStep, session_id: str) -> _InvocationOutcome:
        # Schema-aware type tagging — §4.2.3
        schema = schema_fetcher.get(step.agent_id)
        properties = _build_properties(step.tool, step.tool_params or {}, schema)

        event = {
            "messageVersion": "1.0",
            "agent": {"name": step.agent_id, "id": "direct-invoke", "alias": "direct"},
            "sessionId": session_id,
            "sessionAttributes": {"sentra_request_id": step.request_id},
            "promptSessionAttributes": {},
            "actionGroup": action_group,
            "apiPath": f"/{step.tool}",
            "httpMethod": "POST",
            "requestBody": {"content": {"application/json": {"properties": properties}}},
            "inputText": step.user_input or f"direct-invoke:{step.tool}",
        }

        t0 = time.perf_counter()
        try:
            resp = client.invoke(
                FunctionName=lambda_arn,
                InvocationType="RequestResponse",
                Payload=json.dumps(event).encode(),
            )
            payload = json.loads(resp["Payload"].read().decode())
        except Exception as exc:
            return _InvocationOutcome(
                decision="ERROR", reason=f"Lambda invoke failed: {exc}",
                latency_ms=int((time.perf_counter() - t0) * 1000),
                raw={}, error=str(exc),
                decision_source=DECISION_SOURCE_INVOKER_ERROR,
            )

        # Parse the OpenAPI envelope
        envelope = (payload or {}).get("response") or {}
        status_code = envelope.get("httpStatusCode") or 500
        body_str = ((envelope.get("responseBody") or {}).get("application/json") or {}).get("body") or "{}"
        try:
            body = json.loads(body_str)
        except ValueError:
            body = {"decision": "ERROR", "reason": "non-JSON body"}

        decision = body.get("decision") or ("ALLOW" if status_code == 200 else "DENY")
        reason = body.get("reason") or body.get("error")
        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        # Symmetric bedrock_guardrail emission — §4.2.4
        try:
            signals_client.post_signal(
                session_id=session_id,
                request_id=step.request_id,
                source="bedrock_guardrail",
                decision="ALLOW",
                reason="direct-invoke (LLM bypassed for deterministic scenario run)",
                priority=BEDROCK_GUARDRAIL_PRIORITY,
                agent_id=step.agent_id,
                platform="bedrock",
                cloud_region=region,
                metadata={"direct_invoke": True, "invoker": "default_bedrock_tool_invoker"},
            )
        except Exception as exc:
            logger.warning("synthetic bedrock_guardrail emit failed: %s", exc)

        return _InvocationOutcome(
            decision=decision,
            reason=reason,
            latency_ms=elapsed_ms,
            raw=payload,
            error=None,
            decision_source=DECISION_SOURCE_SENTRA,  # always — Sentra always consulted
        )

    return invoke
```

**Runner change** (`_pick_invoker`):

```python
def _pick_invoker(self, step: "CrossCloudStep") -> Invoker:
    if step.cloud == "bedrock":
        if step.tool:                            # NEW branch
            return self._bedrock_tool
        if step.prompt:
            return self._bedrock_prompt
        raise ValueError(f"Bedrock step {step.id} needs `tool` or `prompt`")
    if step.cloud == "azure_foundry":
        # ... unchanged ...
```

**YAML migration for S2** (illustrative — actual change happens in M-A1 of the workstream):

```yaml
# Before — prompt-based (LLM-driven, non-deterministic)
- id: probe_bedrock_after
  cloud: bedrock
  agent_id: sentra-mvp-customer-service-agent
  prompt: "Call the query_customers tool with state='CA' ..."
  expected_decision: DENY

# After — tool-based (direct invoke, deterministic)
- id: probe_bedrock_after
  cloud: bedrock
  agent_id: sentra-mvp-customer-service-agent
  tool: query_customers
  tool_params:
    state: CA
  user_input: "S2 cross-cloud propagation: probe after policy tightening"
  expected_decision: DENY
  expected_reason_contains: "not authorized"
```

### 4.3 Sub-component A2: Template substitution for dynamic params

**File**: `src/dashboard/components/cross_cloud_scenarios.py` (`_execute` method)

Scenario authors should be able to write:

```yaml
- id: probe_bedrock_after
  cloud: bedrock
  tool: query_customers
  tool_params:
    state: "{state.rand_us_state}"
  user_input: "Look up customers from {state.rand_us_state}"
```

The runner substitutes `{state.rand_us_state}` from a registry of named generators before invoking. Registry is module-level so scenarios can't add arbitrary code; we maintain a small allow-list of generators:

| Token | Generator | Example output |
|---|---|---|
| `{rand.uuid}` | `uuid.uuid4().hex[:8]` | `4f2a9b1c` |
| `{rand.us_state}` | random pick from 50 states | `CA` |
| `{rand.customer_id}` | `f"C{random.randint(1, 9999):04d}"` | `C0042` |
| `{rand.transaction_id}` | `f"tx-{uuid.uuid4().hex[:12]}"` | `tx-abc123def456` |
| `{rand.order_id}` | `f"ORD-{random.randint(10000, 99999)}"` | `ORD-83291` |
| `{request_id}` | the runner-generated `step.request_id` | `xc-probe_bedrock_after-4f2a9b1c` |
| `{session_id}` | the scenario's `session_id` | `xcloud-s2_...-1779849721-a69d0f` |

**Substitution happens in `_execute` before invoker dispatch**, on both `step.tool_params` (string values) and `step.user_input` / `step.prompt`. Non-token strings pass through unchanged. Unknown tokens warn and leave the placeholder in place (so a typo is visible, not silently broken).

**Why a registry, not free-form expressions**: prevents YAML authors from embedding arbitrary Python. Same security posture as a templating allow-list.

### 4.4 Sub-component A3: Scenario step `intent` field

§3.3's decision matrix says direct-invoke is for *enforcement-claim* scenarios and LLM-driven is for *threat-detection-claim* scenarios. But the runner today doesn't enforce the matrix — a scenario author who mistakenly writes `tool:` on a sigma-attack step would get a false ALLOW (LLM bypassed → no user_input → sigma rule never fires) with no error to point at the mistake.

To prevent this, every scenario step must declare its intent:

```yaml
- id: probe_bedrock_after
  cloud: bedrock
  agent_id: sentra-mvp-customer-service-agent
  intent: enforcement        # ← new required field
  tool: query_customers
  tool_params: {state: CA}
  expected_decision: DENY

- id: ssn_attack_probe
  cloud: bedrock
  agent_id: sentra-mvp-customer-service-agent-naive
  intent: threat_detection   # ← LLM-driven path required
  prompt: "What is customer C12345's social security number?"
  expected_decision: DENY
  expected_reason_contains: "PII_EXPOSURE"
```

**Allowed values**: `enforcement | threat_detection`

**Validator rules** (M3):
- `intent: enforcement` + `tool:` → ✓ direct-invoke path
- `intent: enforcement` + `prompt:` → ✗ HARD ERROR (enforcement claims must be deterministic; see §4.4.1 for opt-out)
- `intent: threat_detection` + `tool:` → ✗ HARD ERROR (sigma rule would never see the input; defeats the claim)
- `intent: threat_detection` + `prompt:` → ✓ LLM-driven path
- Missing `intent:` → ✗ HARD ERROR (every step must declare; no default to prevent silent drift)

**Why fail-fast rather than auto-route**: if the runner silently switched a `threat_detection` step to LLM-driven path when the author wrote `tool:`, that would mask the author's confused intent. Better to break loudly. Same logic in reverse for the `enforcement + prompt:` case — the S2 case study (§2) spent 12 hours debugging exactly this mistake; downgrading to "warn" would let the next scenario author repeat it.

#### 4.4.1 Explicit opt-out: `allow_llm_path: true`

The rare scenario that genuinely wants to test "the LLM is responsible for picking the right tool AND the policy then denies it" needs both LLM-driven invocation and an enforcement claim. For that step, the author opts in explicitly:

```yaml
- id: probe_llm_picks_unauthorized_tool
  cloud: bedrock
  agent_id: sentra-mvp-customer-service-agent
  intent: enforcement
  prompt: "Look up customer C0001."
  allow_llm_path: true   # ← required acknowledgement; default is false
  expected_decision: DENY
  expected_reason_contains: "not authorized"
```

Without `allow_llm_path: true`, the validator rejects `intent: enforcement + prompt:`. With it, the validator accepts (still warns at INFO, but proceeds). The opt-out is **per-step**, not per-scenario or per-file, so the author makes the decision visible in code review at the exact line where the LLM-driven path is sanctioned.

**Why an opt-out instead of just allowing it**: the friction is the point. If a scenario author has to type `allow_llm_path: true`, a code reviewer sees that flag and asks "is the LLM-driven path actually being tested here, or did you mean `tool:`?" That ten-second conversation is what prevents the next 12-hour debug spiral.

### 4.5 Sub-component A4: Scenario YAML schema validator


**File**: `src/demo-orchestrator/app/services/scenario_validator.py` (new)

When the demo-orchestrator loads scenarios at startup, every step's `agent_id` + `tool` + `tool_params` are cross-checked against the agent's policy (queried via Sentra's `/v1/policies/{policy_id}?include_content=true`):

| Check | Action on failure |
|---|---|
| `agent_id` matches an active policy | Fail orchestrator startup with explicit error |
| `tool` exists in the agent's OpenAPI schema (Bedrock) / tool registry (Azure) | Fail startup |
| Agent has exactly one Action Group when step uses `tool:` (v0.1 constraint, §4.2.2) | Fail startup |
| Required params in `tool_params` are all present | Fail startup |
| Param types match the OpenAPI schema's declared type | Fail startup |
| Templated tokens (e.g. `{rand.state}`) are in the allow-list | Fail startup |
| Every step has `intent:` set to `enforcement` or `threat_detection` | Fail startup |
| `intent: threat_detection` + `tool:` (sigma probe with bypassed LLM) | Fail startup (§4.4) |

The validator runs once per scenario file at demo-orchestrator boot. Output is logged at INFO level (per-file pass/fail). If any scenario fails, the orchestrator either:
- **Strict mode** (`SCENARIO_VALIDATION_STRICT=true`): refuses to start. **Default — including in our dev cluster** because `sentra-mvp-cluster` *is* the demo target; we never want unvalidated scenarios served.
- **Permissive mode** (`SCENARIO_VALIDATION_STRICT=false`): logs warnings, serves the scenario. Used only when running the orchestrator locally during scenario authoring.

**Why fail-fast at startup, not at run-time**: a scenario with a schema mismatch produces a useless result (LLM doesn't pick the tool, or Lambda 500s). Catching it 12 hours before the demo is the whole win.

### 4.6 Acceptance: what "deterministic" looks like

After A1+A2+A3+A4 land:

1. Running S2 twice in succession produces identical step outcomes (modulo timing and request_ids).
2. S2 takes <30s end-to-end (today's prompt-based runs are 60-90s due to LLM latency).
3. Scenario authors writing a new YAML get a meaningful error within 5 seconds of saving a bad file (demo-orchestrator startup).
4. Adding a new scenario requires zero runner code changes.

---

## 5. Component B: Customer SDK

### 5.1 Goals

1. Integrating Sentra into an existing tool function should be one line.
2. The SDK should work in the three runtime environments we care about for design partners: AWS Lambda (Python 3.11), Azure Functions (Python 3.11), generic Python apps.
3. Failure modes must be configurable — fail-secure (default), fail-open (explicit opt-in), or fail-with-fallback (custom handler).
4. The decorator should be transparent: `repr(decorated_fn) == repr(original_fn)`, `__wrapped__` exposed, signatures preserved (for FastAPI / type checkers).
5. Zero runtime overhead when validation is disabled (e.g., in unit tests).

### 5.2 Package shape

**Name**: `sentra-sdk` (PyPI), package `sentra`

**Module layout**:

```
sentra/
├── __init__.py            # re-exports: validate, validate_async, SentraClient, configure
├── client.py              # SentraClient — HTTP/auth/retry/timeout
├── decorator.py           # @validate sync + async variants
├── context.py             # session_id / request_id contextvar plumbing
├── lambda_handler.py      # @lambda_handler for Bedrock Action Group Lambdas
├── azure_handler.py       # @azure_function for Azure Functions
├── exceptions.py          # SentraDenied, SentraConfigError, SentraValidationError
├── fail_modes.py          # FAIL_SECURE | FAIL_OPEN | FAIL_WITH_FALLBACK
└── _internal/
    ├── retry.py
    ├── telemetry.py       # opt-in metrics + tracing
    └── config.py
```

### 5.3 The decorator — minimal contract

```python
from sentra import validate

@validate(
    agent_id="customer-service",     # required — the agent invoking this tool
    tool_name="query_customers",     # required — must match the policy's allowed_tools
)
def query_customers(state: str) -> list[dict]:
    return db.query(state)
```

What the decorator does at call time:

1. Extract `session_id` + `request_id` from contextvars (set by the host framework — Lambda handler, Azure handler, or manual `with sentra.context(...)`)
2. Serialize the function's bound arguments into a `tool_params` dict (Python introspection on the function signature)
3. POST `/v1/validate` with the assembled `ValidationRequest`
4. If DENY → raise `SentraDenied(reason, request_id, decision)` — caller's responsibility to translate to their framework's error response. Lambda + Azure handlers translate automatically.
5. If ALLOW → call the wrapped function with its original args, return its result
6. On client error (network, timeout, 5xx) → behavior controlled by `fail_mode` (default `FAIL_SECURE` → raise; opt-in `FAIL_OPEN` → call function anyway)

**Provenance — not a rewrite**: `bedrock_action_group_handler` and `sentra_function` (Azure) are **factored from** the existing `lambda/bedrock_agent_actions/index.py:handler` and `function_app.py:tool_call`. Same Bedrock event parsing, same `requestBody.content["application/json"].properties` type-coercion logic, same `sessionAttributes` extraction. M7 ([Workstream 18 M7.1](../tasks/workstream-18-deterministic-enforcement.md)) is the moment we extract this code into the SDK and replace the inline copies — gated by a byte-identical-envelope parity test against the legacy handler.

### 5.4 Lambda Layer packaging

**Lambda Layer artifact**: `sentra-sdk-python-vX.Y.Z.zip` published to a customer-accessible S3 bucket (or PyPI Lambda Layer for those who use SAR).

**Customer's CDK / SAM / serverless.yml**:

```python
# CDK example
layer = lambda_.LayerVersion.from_layer_version_arn(
    self,
    "SentraLayer",
    "arn:aws:lambda:us-east-1:531109575379:layer:sentra-sdk-python:5",
)

my_function = lambda_.Function(
    self, "MyToolLambda",
    code=lambda_.Code.from_asset("src"),
    layers=[layer],
    environment={
        "SENTRA_API_ENDPOINT": "https://api.sentra.example.com/prod/v1/validate",
        "SENTRA_API_KEY_SECRET": "sentra-api-key",
    }
)
```

**Customer's Lambda handler**:

```python
from sentra.lambda_handler import bedrock_action_group_handler
from sentra import validate

@validate(agent_id="customer-service", tool_name="query_customers")
def query_customers(state: str) -> list[dict]:
    return db.query(state)

@validate(agent_id="customer-service", tool_name="get_order_details")
def get_order_details(order_id: str) -> dict:
    return db.get_order(order_id)

# Bedrock Action Group handler wrapper — dispatches to the right @validate'd function
handler = bedrock_action_group_handler({
    "/query_customers": query_customers,
    "/get_order_details": get_order_details,
})
```

The `bedrock_action_group_handler` shim:
- Parses Bedrock Action Group event format
- Establishes the `session_id` + `request_id` context (reads from `sessionAttributes["sentra_request_id"]`)
- Dispatches to the right `@validate`'d function
- Translates `SentraDenied` to the proper OpenAPI 403 envelope
- Returns the OpenAPI 200 envelope on success

Total customer code per tool: **one line (the decorator)** plus the per-Lambda `handler = bedrock_action_group_handler({...})` line. That's it.

### 5.5 Azure Functions packaging

**Customer's `function_app.py`**:

```python
import azure.functions as func
from sentra import validate
from sentra.azure_handler import sentra_function

app = func.FunctionApp()

@validate(agent_id="verification-agent", tool_name="check_fraud_score")
def check_fraud_score(transaction_id: str) -> dict:
    return fraud_model.score(transaction_id)

@app.route(route="tool/check_fraud_score", methods=["POST"])
@sentra_function  # extracts session_id + request_id from body, sets context
def http_check_fraud_score(req: func.HttpRequest) -> func.HttpResponse:
    params = req.get_json().get("params", {})
    try:
        result = check_fraud_score(**params)
        return func.HttpResponse(json.dumps({"decision": "ALLOW", "result": result}), status_code=200)
    except SentraDenied as e:
        return func.HttpResponse(json.dumps({"decision": "DENY", "reason": e.reason}), status_code=403)
```

Same one-line decorator. The `@sentra_function` handler sets up the context from the HTTP body (mirroring what `function_app.py:validate_with_sentra()` does today).

### 5.6 Generic Python (non-Lambda, non-Functions)

For customers running self-hosted agents (LangChain on EC2, internal workflow orchestrators):

```python
from sentra import validate, SentraContext

@validate(agent_id="research-agent", tool_name="web_search")
def web_search(query: str, max_results: int = 10) -> list[dict]:
    return search_engine.run(query, max_results)

# Caller must establish context manually
with SentraContext(session_id="sess-123", request_id="req-456"):
    results = web_search("LLM security research", max_results=5)
```

### 5.7 What the decorator does NOT do

Be explicit about scope:

- ✗ Does not modify the agent's system prompt
- ✗ Does not modify tool schemas (OpenAPI / JSON Schema)
- ✗ Does not register tools with Bedrock / Azure / Vertex — that's still the customer's responsibility
- ✗ Does not implement retry of the tool body (Sentra is queried once per invocation)
- ✗ Does not cache `/v1/validate` results — every invocation hits Sentra fresh (caching breaks audit semantics)
- ✗ Does not handle rate-limiting client-side — that's `/v1/validate`'s job
- ✗ Does not auto-serialize rich Python types — `tool_params` values must be JSON-serializable. If the customer's function signature uses enums, dataclasses, or other non-JSON types, they must supply a `params_extractor` (§6.2) that maps to a `dict[str, JsonScalar]`. The default extractor will raise `SentraConfigError` at first call with the offending type, not silently corrupt the wire payload.

### 5.8 Telemetry & observability

Three telemetry channels, each with a different default and rationale:

| Channel | Default | Toggle | Why this default |
|---|---|---|---|
| **Structured JSON logs** | **Always on** | Cannot be disabled (only filtered by log level) | Customers' CloudWatch / Datadog / Splunk ingestion is the lowest-common-denominator observability — every customer has logs. Every `@validate` call emits one of `sentra.validate.allow`, `sentra.validate.deny`, `sentra.validate.error` at INFO. |
| **OpenTelemetry traces** | Off | `SENTRA_TELEMETRY=true` + `OTEL_EXPORTER_OTLP_ENDPOINT` set | Modern observability stacks (Datadog, Honeycomb, Tempo) ingest OTel push. Customers without OTel ignore this. |
| **Prometheus metrics** | Off in v0.1 | Deferred to v0.2 in a separate `sentra-sdk-prometheus` package | Prometheus pull requires the SDK to expose a metrics endpoint or to run an exporter — adds complexity that the small set of Prometheus customers can opt into later. |

The structured-log payload is the source of truth for everything that matters operationally:

```json
{
  "event": "sentra.validate.deny",
  "ts": "2026-05-27T07:30:00Z",
  "agent_id": "customer-service",
  "tool_name": "query_customers",
  "decision": "DENY",
  "reason": "Tool 'query_customers' not authorized for customer-service",
  "request_id": "req-123",
  "session_id": "sess-abc",
  "latency_ms": 47,
  "sdk_version": "0.1.0"
}
```

Customers who want metrics-shaped views can scrape these logs (CloudWatch Insights, Datadog log-based metrics) without paying for the OTel collector. Customers who want distributed tracing turn on OTel.

**Sentinel metric — emitted unconditionally**: `sentra_validate_fail_open_total` is the one exception to "Prometheus off in v0.1." Whenever the decorator falls back to FAIL_OPEN (i.e., Sentra was unreachable and the customer's tool ran un-enforced), the SDK emits a structured log AND, if any Prometheus-compatible registry is installed in the process, increments the counter. Customers can configure their monitoring to alarm on it regardless of whether they've opted into broader telemetry. See §11.4 for the kill-switch story.

---

## 6. Data Models & Interfaces

### 6.1 `ValidationRequest` shape (unchanged from `/v1/validate`)

The SDK does NOT introduce a new schema. It produces the same `ValidationRequest` the controller already accepts:

```json
{
  "request_id": "string (UUID or caller-supplied)",
  "session_id": "string",
  "agent_id": "string",
  "tool_name": "string",
  "tool_params": {"string": "any JSON-serializable"},
  "user_input": "string (optional)",
  "timestamp": "ISO 8601",
  "operation_type": "READ | WRITE",
  "platform": "bedrock | azure_foundry | gcp_vertex | self_hosted",
  "cloud_region": "string"
}
```

The SDK fills these from:

| Field | Source |
|---|---|
| `request_id` | Context, or generated UUID if absent |
| `session_id` | Context (required — raises `SentraConfigError` if missing) |
| `agent_id` | Decorator arg |
| `tool_name` | Decorator arg |
| `tool_params` | Bound function args (via `inspect.signature`). Values MUST be JSON-serializable (`str | int | float | bool | None | list | dict`). Rich types raise `SentraConfigError` on first call; supply a `params_extractor` (§6.2) to map them. |
| `user_input` | Context (optional) |
| `timestamp` | Generated at call time |
| `operation_type` | Decorator arg (defaults: heuristic on tool name — `WRITE` if contains "create"/"delete"/"refund"/"update"/"modify"; else `READ`) |
| `platform` | Env var `SENTRA_PLATFORM` (defaults: detect from runtime — `bedrock` if `AWS_LAMBDA_FUNCTION_NAME`+Action-Group-event, `azure_foundry` if Azure Functions runtime, else `self_hosted`) |
| `cloud_region` | Env var `SENTRA_CLOUD_REGION` (defaults: `AWS_REGION` or `AZURE_REGION`) |

### 6.2 Decorator parameters

```python
@validate(
    agent_id: str,                       # required
    tool_name: str,                      # required
    operation_type: Literal["READ", "WRITE"] | None = None,  # default: heuristic
    fail_mode: FailMode = FAIL_SECURE,   # FAIL_SECURE | FAIL_OPEN | FAIL_WITH_FALLBACK
    fallback_fn: Callable | None = None, # required if FAIL_WITH_FALLBACK
    timeout_seconds: float = 5.0,
    params_extractor: Callable[..., dict] | None = None,  # maps bound args -> JSON-serializable dict
)
def my_tool(...): ...
```

**`params_extractor` contract**: receives the same `(*args, **kwargs)` the wrapped function was called with, returns `dict[str, JsonScalar]`. Used to flatten enums, Pydantic models, dataclasses, etc., into the wire payload. The extractor should ONLY produce `tool_params` content — `operation_type` resolution stays on the decorator (see open question #2 in §14).

Example:

```python
from sentra import validate
from dataclasses import asdict

@validate(
    agent_id="customer-service",
    tool_name="process_refund",
    params_extractor=lambda order, amount_cents: {
        "order_id": order.id,             # extract attribute
        "amount": amount_cents / 100,      # convert units
        "currency": order.currency.value,  # unwrap enum
    },
)
def process_refund(order: Order, amount_cents: int): ...
```

### 6.3 Context API

```python
class SentraContext:
    def __init__(
        self,
        session_id: str,
        request_id: str | None = None,
        user_input: str | None = None,
    ): ...
    def __enter__(self) -> "SentraContext": ...
    def __exit__(self, *exc): ...

# Async variant:
async with sentra.AsyncContext(...): ...
```

The handlers (`bedrock_action_group_handler`, `sentra_function`) establish this context automatically from the platform's event payload. Manual use is for self-hosted agents.

### 6.4 Exceptions

```python
class SentraError(Exception): ...
class SentraDenied(SentraError):
    reason: str
    decision: Literal["DENY"]
    request_id: str
    violation_type: str | None  # from /v1/validate response

class SentraConfigError(SentraError): ...  # missing env var, no context, etc.
class SentraValidationError(SentraError): ...  # network / 5xx / timeout
```

---

## 7. Configuration

### 7.1 Environment variables

| Var | Purpose | Default | Required |
|---|---|---|---|
| `SENTRA_API_ENDPOINT` | Full URL to `/v1/validate` | — | Yes |
| `SENTRA_API_KEY` | API key for `x-api-key` header | — | Yes (production) |
| `SENTRA_API_KEY_SECRET` | AWS Secrets Manager secret name (alt to `SENTRA_API_KEY`) | — | No |
| `SENTRA_PLATFORM` | Platform identifier | auto-detect | No |
| `SENTRA_CLOUD_REGION` | Cloud region identifier | `AWS_REGION` / `AZURE_REGION` | No |
| `SENTRA_FAIL_MODE` | Global fail mode (decorator can override per-tool) | `FAIL_SECURE` | No |
| `SENTRA_TELEMETRY` | Enable Prometheus + OTel | `false` | No |
| `SENTRA_TIMEOUT_SECONDS` | HTTP timeout to `/v1/validate` | `5.0` | No |
| `SENTRA_RETRY_MAX` | Max retries on 5xx / network | `2` | No |

### 7.2 Programmatic configuration (alternative to env vars)

```python
from sentra import configure

configure(
    endpoint="https://api.sentra.example.com/prod/v1/validate",
    api_key=os.environ["SENTRA_API_KEY"],
    platform="self_hosted",
    fail_mode=FAIL_SECURE,
    telemetry=True,
)
```

Called once at process startup. Idempotent — subsequent calls override.

### 7.3 Runtime configuration source-of-truth precedence

1. Decorator argument (per-tool)
2. `configure(...)` call (per-process)
3. Environment variable (per-deployment)
4. SDK default (per-version)

---

## 8. Error Handling & Fail-Mode Policy

### 8.1 The three fail modes

| Mode | When Sentra is unreachable / errors | Use case |
|---|---|---|
| `FAIL_SECURE` (default) | Raise `SentraValidationError` → caller's framework returns 5xx / re-raises | Production paths where unavailability MUST block the tool call |
| `FAIL_OPEN` | Log the error + execute the tool body anyway | Non-critical analytics tools where availability beats authorization (rare; explicit opt-in) |
| `FAIL_WITH_FALLBACK` | Call `fallback_fn(*args, **kwargs)` instead of the tool body | Customer-defined fallback logic (e.g., enqueue for offline review) |

### 8.2 What "fail-secure" looks like at the framework boundary

- **Lambda (`bedrock_action_group_handler`)**: `SentraValidationError` → returns OpenAPI 503 envelope: `{"success": false, "error": "Sentra validation service temporarily unavailable", "decision": "DENY"}`
- **Azure Function (`sentra_function`)**: Same — 503 with the same body shape
- **Self-hosted**: `SentraValidationError` propagates to caller. Customer's app decides.

### 8.3 What's NOT configurable

- `DENY` is always terminal — there is no "soft DENY". If Sentra says DENY, the tool body must not execute. The decorator enforces this.
- Cached approvals — explicitly out of scope. Every invocation hits Sentra. (LLD 17 §3 audit semantics.)

### 8.4 Observability of failures

When `FAIL_OPEN` or `FAIL_WITH_FALLBACK` fires, the SDK emits **three signals**, in this order of guaranteed delivery:

1. **Structured JSON log** at WARN: `{event: "sentra.validate.fail_open", tool_name, agent_id, error_type, error_message, request_id, sdk_version}` — emitted UNCONDITIONALLY (structured logs are always-on per §5.8)
2. **Sentinel metric** `sentra_validate_fail_open_total{tool_name, agent_id}` — incremented if any Prometheus-compatible registry is detected in the process, regardless of `SENTRA_TELEMETRY` setting. This is the one metric that bypasses the v0.1 telemetry-off default because silent un-enforcement is too dangerous to be invisible.
3. **OTel span with `error=true`** — only if `SENTRA_TELEMETRY=true`

Customers should alarm on (1) or (2) — sustained fail-open means they're effectively un-enforced. The structured log is the lowest-common-denominator: every customer's log pipeline ingests it.

---

## 9. Migration Plan

### 9.1 Component A migration (demo runner)

**Phase 1 (this workstream)**: Add the `bedrock_tool_invoker` + template substitution + validator. Existing scenarios continue to work unchanged (the prompt-based path is not removed).

**Phase 2 (one-off per scenario)**: Each existing scenario's authors decide which steps should be direct-invoke vs LLM-driven. S2 migrates immediately (it's the motivating case). S1 keeps some prompt-based steps (the sigma/PII attack probes — that's the actual claim). S3 + S4 evaluated when authored.

**Phase 3 (within this workstream, M3.6)**: Remove the legacy `audit_lookup_fn` runner path. WS17's `audit_lookup_fn` was retained as rollback-safety for the W17 cutover; with direct-invoke now the canonical enforcement path, that argument is satisfied by milestone-based image versioning and the legacy code becomes dead weight. [Workstream 18 Task 3.6](../tasks/workstream-18-deterministic-enforcement.md) does the removal, deletes the two legacy regression tests, and updates the WS17 tracker to mark the WS18-candidate cleanup as DONE.

### 9.2 Component B migration (customer SDK)

**Phase 1 (this workstream, weeks 1-2)**:
- Publish `sentra-sdk-python` v0.1 to internal PyPI mirror
- Publish Lambda Layer to `arn:aws:lambda:us-east-1:531109575379:layer:sentra-sdk-python`
- Migrate `lambda/bedrock_agent_actions/index.py` to use the SDK internally (eats its own dogfood)
- Migrate `src/connectors/azure_foundry/azure_function/tool_interceptor/function_app.py` similarly

**Phase 2 (weeks 3-4)**:
- Onboard first design partner with the SDK in a sandbox account
- Document common integration patterns (`docs/sdk-integration-bedrock.md`, etc.)
- Add `@validate` to one design-partner agent in their staging environment

**Phase 3 (weeks 5-8, pending design-partner sign-off)**:
- Publish SDK to public PyPI as `sentra-sdk`
- Open-source the SDK repo (separate from main Sentra monorepo)
- Add Java + Go + Node language bindings (separate workstream — not in scope here)

### 9.3 Backwards compatibility

| Existing behavior | Preserved? |
|---|---|
| LLM-driven prompt steps in scenarios | Yes — `prompt:` field still works |
| Existing `audit_lookup_fn` runner path | **Removed in Phase 3 (M3.6 of this workstream)** — replaced by direct-invoke + `decisions_lookup_fn` path. No rollback path; image-version pinning is sufficient. |
| Existing `lambda/bedrock_agent_actions/index.py` API contract (event in, OpenAPI envelope out) | Yes — SDK adoption is internal refactor only |
| `validate_with_sentra()` function in Lambda + Function App | Removed in favor of SDK call (internal refactor; same wire shape) |

---

## 10. Test Plan

### 10.1 Unit tests (SDK)

| Test ID | Behavior | Tier |
|---|---|---|
| T-SDK-01 | `@validate` raises `SentraConfigError` if no context set | Critical |
| T-SDK-02 | `@validate` POSTs correct payload to `/v1/validate` | Critical |
| T-SDK-03 | `@validate` returns wrapped function's result on ALLOW | Critical |
| T-SDK-04 | `@validate` raises `SentraDenied` on DENY response | Critical |
| T-SDK-05 | `@validate` honors `fail_mode=FAIL_OPEN` on 5xx | Critical |
| T-SDK-06 | `@validate` honors `fail_mode=FAIL_WITH_FALLBACK` | Critical |
| T-SDK-07 | `tool_params` extracted from function signature correctly | Critical |
| T-SDK-08 | Custom `params_extractor` overrides default | High |
| T-SDK-09 | `operation_type` heuristic detects WRITE correctly | High |
| T-SDK-10 | Context propagates across `await` boundaries | High |
| T-SDK-11 | `__wrapped__`, `__name__`, `__signature__` preserved | Medium |
| T-SDK-12 | Telemetry emits metrics when enabled, silent when disabled | Medium |
| T-SDK-13 | Retry honors `SENTRA_RETRY_MAX` on transient errors | Medium |
| T-SDK-14 | Timeout honors `SENTRA_TIMEOUT_SECONDS` | Medium |

### 10.2 Integration tests (Lambda Layer)

| Test ID | Behavior | Tier |
|---|---|---|
| T-INT-01 | Layer + decorator together: Lambda invoke → Sentra ALLOW → tool runs | Critical |
| T-INT-02 | Layer + decorator together: Lambda invoke → Sentra DENY → 403 returned | Critical |
| T-INT-03 | `bedrock_action_group_handler` parses Bedrock event correctly | Critical |
| T-INT-04 | `bedrock_action_group_handler` extracts `request_id` from sessionAttributes | Critical |
| T-INT-05 | Concurrent invocations don't leak context between requests | Critical |
| T-INT-06 | FAIL_OPEN path emits `sentra.validate.fail_open` structured log even when `SENTRA_TELEMETRY=false` | Critical |
| T-INT-07 | FAIL_OPEN path increments `sentra_validate_fail_open_total` sentinel metric regardless of telemetry setting | Critical |
| T-INT-08 | **Byte-identical envelope parity** — same Bedrock event through legacy `index.py:handler` and new SDK handler produces `json.dumps(...)`-equal responses modulo timing fields (Workstream Task 7.4) | Critical |

### 10.3 Runner determinism tests (Component A)

| Test ID | Behavior | Tier |
|---|---|---|
| T-RUN-01 | `default_bedrock_tool_invoker` invokes Lambda with correct event shape | Critical |
| T-RUN-02 | `_pick_invoker` routes Bedrock + `tool:` to tool invoker | Critical |
| T-RUN-03 | Template `{rand.state}` substitutes a valid US state | High |
| T-RUN-04 | Unknown template token logs warning and leaves placeholder | Medium |
| T-RUN-05 | Scenario validator fails startup on unknown tool reference | Critical |
| T-RUN-06 | Scenario validator passes valid S2 YAML | Critical |
| T-RUN-07 | Two consecutive S2 runs produce identical step decision sequences | Critical |
| T-RUN-08 | Schema-aware event builder emits `integer` type for integer-declared OpenAPI params (not stringified) | Critical |
| T-RUN-09 | Synthetic `bedrock_guardrail` ALLOW signal posted with `metadata.direct_invoke=true` after each direct-invoke | Critical |
| T-RUN-10 | Validator HARD-ERRORs on `intent: enforcement + prompt:` without `allow_llm_path: true` | Critical |
| T-RUN-11 | Validator HARD-ERRORs on `intent: threat_detection + tool:` (sigma-bypass guard) | Critical |
| T-RUN-12 | Validator HARD-ERRORs on missing `intent:` field | High |
| T-RUN-13 | Validator HARD-ERRORs on `tool:` step when agent has >1 Action Group | High |
| T-RUN-14 | Validator HARD-ERRORs on OpenAPI int-typed param supplied as string | High |
| T-RUN-15 | `audit_lookup_fn` parameter removed from runner constructor (regression guard for M3.6 cleanup) | Medium |

### 10.4 End-to-end smoke

After deploy, the live demo run of S2 must show:
- All 4 probes complete in <30 seconds
- probe_bedrock_before: ALLOW, source `🛡 Sentra`, reason "All validation checks passed"
- probe_azure_before: ALLOW, source `🛡 Sentra`
- probe_bedrock_after: DENY, source `🛡 Sentra`, reason contains "not authorized"
- probe_azure_after: DENY, source `🛡 Sentra`, reason contains "not authorized"

---

## 11. Operational Considerations

### 11.1 What ops needs to monitor (customer-facing)

The signals to watch depend on what telemetry the customer has enabled (§5.8). Two views:

**v0.1 — structured-log channel (default, always-on)**

Every customer can monitor these because structured JSON logs are emitted unconditionally. Set up CloudWatch Logs Insights / Datadog / Splunk log-based metrics on:

| Log event | Alarm condition | What it means |
|---|---|---|
| `sentra.validate.error` | Spike above baseline | Sentra outage or network problem in customer's account |
| `sentra.validate.fail_open` | Any occurrence sustained for >5 minutes | Customers are silently bypassing enforcement |
| `sentra.validate.deny` p99 latency field | >500ms | Tool latency degraded |

**v0.1 sentinel — Prometheus-shaped (regardless of telemetry setting)**

- **`sentra_validate_fail_open_total`** — emitted unconditionally by the SDK (§8.4). This is the one Prometheus-named metric that exists in v0.1 because silent un-enforcement is too dangerous to be invisible. Customers running Prometheus / CloudWatch metrics can alarm on it without enabling broader telemetry.

**v0.2+ — full Prometheus channel (when `sentra-sdk-prometheus` ships)**

The other Prometheus metrics (`sentra_validate_total`, `sentra_validate_latency_seconds`, `sentra_validate_errors_total`) land in v0.2 via the separate `sentra-sdk-prometheus` package. Customers who want metrics-shaped views in v0.1 derive them from the structured logs.

**OTel channel (opt-in)**

Customers who set `SENTRA_TELEMETRY=true` + `OTEL_EXPORTER_OTLP_ENDPOINT` get distributed traces with `sentra.validate` spans tagged by `agent_id`, `tool_name`, `decision`, `request_id`. Their tracing backend (Honeycomb, Datadog APM, Tempo) provides the dashboards.

### 11.2 What ops needs to monitor (internal demo runner)

- Scenario validator pass/fail at orchestrator startup (in `/ecs/sentra/demo-orchestrator` logs)
- S2/S3/S4 success rate over 7-day window (target: >98%)
- p95 scenario duration (target: <30s for S2)

### 11.3 SDK version management

Customers pin `sentra-sdk==X.Y.Z` in their `requirements.txt`. Breaking changes follow semver:
- **MAJOR**: changes to `@validate` signature, behavior of fail modes, decorator API
- **MINOR**: new params, new fail modes, new telemetry hooks (backwards-compatible)
- **PATCH**: bug fixes only

Lambda Layer ARNs are version-pinned (`:layer:sentra-sdk-python:5`). Customers must explicitly bump.

### 11.4 SDK kill-switch

In case of catastrophic SDK bug, customers can set `SENTRA_FAIL_MODE=FAIL_OPEN` as a single env var change — keeps their agents working at the cost of temporarily un-enforced.

**Alarm visibility is unconditional** (§8.4): the `sentra.validate.fail_open` structured log is emitted on every fail-open invocation regardless of telemetry settings, and the `sentra_validate_fail_open_total` sentinel metric is incremented if any Prometheus-compatible registry exists in the process. Customers can alarm on either channel without enabling broader telemetry. The earlier v0.1 draft implied the alarm required telemetry to be enabled — that was wrong; corrected here.

---

## 12. Cost Model

### 12.1 Demo runner additions

| Component | Marginal cost | Notes |
|---|---|---|
| `default_bedrock_tool_invoker` | $0.0000002 per Lambda invoke + Lambda exec cost (already paid) | Replaces LLM call that was costing ~$0.003 per turn |
| Template substitution | $0 | Pure Python |
| Scenario validator | One-time per orchestrator boot — ~1s of Sentra `/v1/policies` reads | Negligible |

Net effect: each S2 run gets **cheaper** because we skip a Bedrock LLM turn (~$0.003 saved per probe × 2 Bedrock probes = $0.006 per run).

### 12.2 SDK runtime cost (customer-side)

Per `@validate` call:
- 1 HTTPS POST to `/v1/validate` — $0 (customer's outbound) + Sentra's per-call billing (TBD)
- ~50ms p99 latency (LLD 17 §6.2)
- ~1KB request body, ~500B response body

For a customer with 1M tool calls per day:
- 1M × ~$0.0001 (Sentra metered call price, hypothetical) = $100/day
- 1M × 50ms = ~14 hours of cumulative latency — split across thousands of concurrent invocations, individual user impact is the per-call 50ms

### 12.3 SDK telemetry overhead (when enabled)

| Telemetry feature | Cost | Notes |
|---|---|---|
| Prometheus counter increments | <1µs | Lock-free |
| OTel span emit | ~10-100µs | Async export |
| Structured log emit | ~10µs | JSON serialization |

Customers running 1M tool calls/day with telemetry on: ~1 minute of cumulative SDK overhead per day. Negligible.

---

## 13. Out of Scope (Phase 1)

The following are deferred to future LLDs / workstreams:

- **Transparent forwarding proxy** ("Sentra Proxy") — hosted endpoint that routes customer tool calls through Sentra without code changes. Big-customer feature; needs separate networking/auth design.
- **Auto-instrumentation** — Bedrock agent or Azure Foundry hooks that emit traces without customer code change. Requires platform partnerships.
- **Java / Go / Node language SDKs** — separate workstream once design-partner Python adoption is stable.
- **GCP Vertex SDK** — same shape, deferred until first GCP design partner.
- **SDK-side caching of policies** — would optimize p99 but break audit semantics. Re-evaluate after telemetry shows hotspots.
- **`@validate_batch`** — multiple tool calls in one validate request. Sentra's `/v1/validate` is single-request today; batching needs controller changes.
- **CI/CD integration** — Sentra GitHub Action that runs scenario validator on PRs. Nice-to-have.

---

## 14. Open Questions

1. ~~**SDK telemetry — push vs pull?**~~ **Resolved in §5.8** (v0.2). Structured logs always-on, OTel opt-in, Prometheus deferred to v0.2.

2. **Operation_type — dynamic per-call?** Today set on decorator. Some tools are dual-purpose (e.g., `set_status` is READ if status=null, WRITE otherwise). For v0.2, add a separate `operation_type_resolver: Callable[..., Literal["READ","WRITE"]]` decorator arg. **Do not overload `params_extractor`** — that's for content mapping; operation type is a distinct concern. Tracked as a v0.2 design note.

3. **Async tool functions** — SDK auto-detects via `inspect.iscoroutinefunction()`. One decorator name; two internal code paths. Decided.

4. **Lambda Layer size budget** — Layers cap at 250MB unzipped. Pure-Python SDK is <1MB. No issue but flagged.

5. **Scenario validator strictness in our cluster** — **Resolved in §4.5** (v0.2). Strict mode is always-on in our dev cluster because `sentra-mvp-cluster` IS the demo target. Permissive mode is for local-dev only.

6. **Should we publish the SDK pre-release on PyPI under `sentra-sdk-preview`?** Lets design partners install via standard pip flow without committing to the production package name. Lean yes; defer the final decision until M5 packaging.

---

## 15. Cross-References

| Document | Relationship |
|---|---|
| [LLD 03: Security Controller](03-security-controller.md) | Defines `/v1/validate` API the SDK calls |
| [LLD 13: Demo Orchestrator](13-demo-orchestrator.md) | Owns scenario YAML format the validator checks |
| [LLD 15: Cross-Cloud Connectors](15-cross-cloud-connectors.md) | Defines current Bedrock + Azure invocation paths the runner extends |
| [LLD 17: Validation Signal Store](17-validation-signal-store.md) | Owns `request_id` correlation + decisions endpoint the runner reads |
| [Workstream 18](../tasks/workstream-18-deterministic-enforcement.md) | Execution plan for this LLD |
| [best-practices.md §12](../best-practices.md) | Will gain a §13 covering SDK integration patterns |

---

## Appendix A: Why the decorator pattern beats alternatives

Three alternatives considered:

| Alternative | Customer effort | Drawbacks |
|---|---|---|
| **Manual `validate_with_sentra()` helper** (today) | Copy the helper into every Lambda + maintain | Drift; security-critical code copied with no central version |
| **Sidecar proxy** (Phase 2) | Change tool endpoint URL | Requires Sentra-hosted infra; routes customer traffic through us |
| **Middleware (e.g., Flask before_request)** | Per-framework integration | Doesn't fit Lambda / Azure Function shape; framework-specific |
| **Decorator** (chosen) | One line per tool | Trade: customer's tool function imports our SDK |

The decorator wins because:
- It's framework-agnostic (works in Flask, FastAPI, Lambda, Azure Functions, scripts)
- It's locally visible — the security boundary is right there in the code, not in a middleware config
- Code reviewers see at a glance "this tool is enforced"
- It composes with other decorators (logging, retry, etc.)
- It's the same shape across Python language ecosystems

## Appendix B: A worked example — what the customer's life looks like

A design partner has a Bedrock-based customer-support agent with three tools: `search_kb`, `create_ticket`, `escalate_to_human`. Today's integration:

**Before SDK**:

```python
# Each Lambda has ~40 lines of validate_with_sentra() helper (copied across 3 functions)
# Plus the dispatch boilerplate in the handler
# Plus the per-call boilerplate inside each tool
# Total: ~150 lines of integration code, 3-way duplication, drift-prone
```

**After SDK**:

```python
from sentra import validate
from sentra.lambda_handler import bedrock_action_group_handler

@validate(agent_id="support-agent", tool_name="search_kb")
def search_kb(query: str) -> list[dict]:
    return kb_client.search(query)

@validate(agent_id="support-agent", tool_name="create_ticket")
def create_ticket(subject: str, body: str, priority: str = "normal") -> dict:
    return ticket_client.create(subject, body, priority)

@validate(agent_id="support-agent", tool_name="escalate_to_human", operation_type="WRITE")
def escalate_to_human(ticket_id: str, reason: str) -> dict:
    return notify_oncall(ticket_id, reason)

handler = bedrock_action_group_handler({
    "/search_kb": search_kb,
    "/create_ticket": create_ticket,
    "/escalate_to_human": escalate_to_human,
})
```

Total: 12 lines for 3 tools. Adding a 4th tool: 4 more lines. The customer's code reviewer sees the enforcement boundary inline. Adding a new dev to the team — "everything decorated with `@validate` is Sentra-enforced; full stop."

---
