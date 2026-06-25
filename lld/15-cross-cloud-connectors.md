# LLD 15: Cross-Cloud Agent Connectors

**Version**: 1.1
**Last Updated**: 2026-05-22
**Status**: Draft – Ready for Review
**Prerequisites**:
- [LLD 03: Security Controller](03-security-controller.md)
- [LLD 09: Agent Execution & LLM Response](09-agent-execution-and-llm-response.md) (Bedrock integration)
- [LLD 12: Multi-Agent Workflow](12-multi-agent-workflow.md)
- [LLD 13: Demo Orchestrator](13-demo-orchestrator.md)

**Related Documents**:
- [LLD 04: Dashboard](04-dashboard-v2.md) – consumes the new `AgentConnector` interface via the factory
- [LLD 11: Agent Policy CRUD](11-agent-policy-crud.md) – policy model extensions live alongside this
- [Workstream 15](../tasks/workstream-15-cross-cloud-demo.md) – execution tracking
- [ADR-020, ADR-021](../adr.md) – architectural decisions captured

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Connector Abstraction (Component Design)](#3-connector-abstraction-component-design)
4. [Cross-Cloud Policy Model](#4-cross-cloud-policy-model)
5. [Data Models](#5-data-models)
6. [Foreign-Cloud Interceptor Contract](#6-foreign-cloud-interceptor-contract)
7. [Azure AI Foundry Implementation](#7-azure-ai-foundry-implementation)
8. [Phase 2 — GCP Vertex AI Implementation](#8-phase-2--gcp-vertex-ai-implementation)
9. [Demo Scenarios S1–S4](#9-demo-scenarios-s1s4)
10. [Configuration](#10-configuration)
11. [Error Handling](#11-error-handling)
12. [Monitoring & Observability](#12-monitoring--observability)
13. [Cross-References](#13-cross-references)

---

## 1. Overview

### 1.1 Purpose

Provide a cloud-agnostic abstraction that lets the Sentra security controller govern AI agents running on any major cloud (AWS Bedrock, Azure AI Foundry, GCP Vertex AI) from a single control plane. This LLD covers:

- The `AgentConnector` Python ABC (control-plane side) that the dashboard and demo orchestrator consume.
- The "foreign-cloud interceptor" pattern (Lambda / Azure Function / Cloud Run) that intercepts native tool calls and forwards them to `/v1/validate`.
- The cross-cloud policy model (extends `AgentPolicy` with `platform`, `cloud_region`, `cross_cloud_dependencies`).
- Phase 1 (AWS + Azure) and Phase 2 (GCP) implementations.
- Four investor-grade demo scenarios that exercise the full cross-cloud governance surface.

### 1.2 Why Now

Investor feedback (Travis Priest, Mar 2026) named cross-cloud governance as the single largest credibility gap: AegionAI's thesis is multi-cloud, but the demo runs on AWS only. Pitch deck v4 commits to a live AWS + Azure demo as the Month 2 milestone gating the seed raise. This workstream delivers exactly that, with GCP as a fast-follow once the connector pattern is proven.

### 1.3 Core Capabilities

1. **Single-pane governance** — one dashboard, one policy engine, agents on N clouds.
2. **Cross-cloud policy propagation** — one `AgentPolicy` resource enforced uniformly across clouds within seconds.
3. **Cross-cloud tool-call preconditions** — when a prerequisite tool runs on a different cloud, the dependent tool is denied unless that prerequisite was observed in the same session within `max_age_seconds` (presence-within-time-window; see §4.5). Generalizes Swiggy-style fraud prevention.
4. **Cross-cloud blast-radius containment** — when an agent on cloud A is compromised, agents on cloud B that it calls are blocked at the sidecar before execution.
5. **Uniform audit trail** — the security controller's audit log already records validation decisions cloud-agnostically; the connector layer surfaces them in chronological cross-cloud timelines.

### 1.4 Existing Infrastructure (No Changes Needed)

- ✅ **Security Controller** (`src/security-controller/`) — `/v1/validate` is platform-agnostic; accepts `agent_id`, `tool_name`, `tool_params`, `session_id` with no AWS coupling. ([routes.py:56](../src/security-controller/app/api/routes.py))
- ✅ **Bedrock Action Group Lambda** (`lambda/bedrock_agent_actions/index.py`) — reference implementation of the interceptor pattern. The Azure Function and Cloud Run interceptors mirror its `validate_with_sentra()` flow line-for-line, with different SDK clients.
- ✅ **Policy Engine** (`src/security-controller/app/validators/policy_engine.py`) — YAML + DynamoDB hybrid; reads the new `platform` field without logic changes.
- ✅ **Sigma Engine, Trust Checker, Abuse Detector** — entirely platform-agnostic; no changes for Phase 1. Trust scores live in DynamoDB and are visible to any cloud's interceptor on its next `/v1/validate` call — this is what makes S4 (cross-cloud blast-radius containment) work without any new code.
- ✅ **Demo Orchestrator framework** (`src/demo-orchestrator/`) — YAML-driven; new scenario files plug in without touching the executor.

### 1.5 New Components Required

- ❌ `src/connectors/base/` — cloud-agnostic `AgentConnector` ABC + dataclasses
- ❌ `src/connectors/bedrock/` — refactor of `bedrock_agent_caller.py` behind the new interface
- ❌ `src/connectors/azure_foundry/` — Azure connector + Function source
- ❌ `src/connectors/vertex_ai/` — Phase 2
- ❌ `src/dashboard/services/agent_caller_factory.py` — platform-routing factory
- ❌ `infrastructure/azure/` — Bicep modules for Function App, Key Vault, AI Foundry project, AI Foundry agent
- ❌ Extension to `config/agent_policies.yaml` — `platform`, `cloud_region`, `cross_cloud_dependencies` fields
- ❌ Extension to `context_validator.py` — recognize `cross_cloud_dependencies`
- ❌ Four new scenario YAMLs under `src/demo-orchestrator/scenarios/`

### 1.6 Key Design Decisions

**Decision 1**: Single Python ABC (`AgentConnector`) for the dashboard-side, separate concrete interceptor code per cloud.
- ✅ Dashboard, demo orchestrator, and tests stay cloud-agnostic.
- ✅ Each cloud's interceptor can use its native idioms (Lambda handlers, Azure Function bindings, Flask on Cloud Run) without forcing a common runtime.

**Decision 2**: Azure first, GCP fast-follow.
- ✅ Matches pitch deck v4 commitment (AWS + Azure as Month 2 milestone).
- ✅ Azure's tool-calling is OpenAI-compatible — minimum translation overhead.
- ✅ Once the connector pattern is validated for Azure, GCP is ~60% the effort.
- See [ADR-020](../adr.md#adr-020-azure-first-gcp-fast-follow-for-cross-cloud-demo).

**Decision 3**: Backward-compatible refactor of Bedrock — keep `BedrockAgentCaller` as a shim.
- ✅ Existing dashboard imports (`src/dashboard/tabs/agents_tab.py`) continue to work without modification.
- ✅ Migration to the new `BedrockConnector` happens at the consumer's pace.

**Decision 4**: Bicep (not Terraform) for Azure IaC.
- ✅ First-party, mature, faster ramp for the Azure-only stack.
- ✅ CDK remains for AWS; Bicep for Azure; Terraform deferred to Phase 3 if multi-cloud IaC unification becomes valuable.

---

## 2. Architecture

### 2.1 System Diagram

```
                        ┌──────────────────────────────────────┐
                        │   Sentra Security Controller        │
                        │   (FastAPI, /v1/validate, OPA-style) │
                        │                                      │
                        │   Validators: Trust → Policy →       │
                        │   Sigma → Context → Abuse            │
                        │                                      │
                        │   Audit log (CloudWatch + DDB)       │
                        └──────────────────────────────────────┘
                                  ▲                ▲
                       POST /validate         POST /validate
                                  │                │
                ┌─────────────────┴────┐   ┌──────┴───────────────┐
                │  AWS Bedrock Action  │   │  Azure Function       │
                │  Group Lambda        │   │  tool_interceptor     │
                │  (lambda/bedrock_    │   │  (src/connectors/     │
                │   agent_actions/)    │   │   azure_foundry/      │
                │                      │   │   azure_function/)    │
                └─────────────────┬────┘   └──────┬───────────────┘
                                  │                │
                       intercepts tool calls       │
                                  ▼                ▼
                        ┌─────────────────────────────────────────┐
                        │ Customer Agent (Bedrock)  │ Verification │
                        │ sentra-mvp-customer-svc   │ Agent        │
                        │                           │ (Azure AI    │
                        │                           │  Foundry)    │
                        └───────────────────────────┴──────────────┘

                        ▲                                    ▲
                        │   Dashboard invokes via factory    │
                        │                                    │
              ┌─────────┴──────────────────────────┐
              │   src/dashboard/services/          │
              │   agent_caller_factory.py          │
              │   → BedrockConnector               │
              │   → AzureConnector                 │
              │   → VertexConnector (Phase 2)      │
              └────────────────────────────────────┘
```

### 2.2 Request Flow — Cross-Cloud Tool Call

A request from a Bedrock agent invoking a tool that requires a prior step on the Azure agent (Scenario S3, generalized):

```
1.  User → Dashboard:  "Issue refund for order #ORD-9981 (photo attached)"
2.  Dashboard → AgentCallerFactory.get(bedrock).invoke_agent(...)
3.  Bedrock agent decides to call tool: process_refund(order_id, amount, photo_url)
4.  Bedrock Action Group Lambda receives the tool call
5.  Lambda → POST /v1/validate  (agent_id=sentra-mvp-customer-service-agent,
                                  tool_name=process_refund, tool_params={...})
6.  Security Controller validators run:
      - Trust Checker:  AWS agent is in good standing
      - Policy Engine:  process_refund is in allowed_tools
      - Context Validator:  evaluates cross_cloud_dependencies
            → requires azure-verification-agent.verify_image_authenticity
              completed within last 300s in this session
            → NOT FOUND in session-context store (DynamoDB `sentra-session-context`)
      - Decision:  DENY with reason
        "cross_cloud_dependency_not_met:
         azure-verification-agent.verify_image_authenticity required first"
7.  Lambda returns 403 to Bedrock with the reason
8.  Bedrock agent surfaces the denial in its response stream
9.  Dashboard renders the cross-cloud audit trace showing both clouds in one timeline
```

### 2.3 Architectural Boundaries

| Boundary | Owned by | Notes |
|---|---|---|
| Control plane (`/v1/validate`, policy engine, audit) | Sentra security controller | One deployment, one URL, ingress reachable from all foreign clouds |
| Foreign-cloud interceptor | Per-cloud (Lambda / Function / Run) | Lives inside the customer/demo cloud account; outbound HTTPS only |
| Dashboard `AgentConnector` | Sentra (Python) | Invokes native agent APIs to *trigger* demos; not in the security path |
| Native agent runtime | Cloud provider | Bedrock Agents, Azure AI Foundry agents, Vertex Agent Engine — unmodified |

The security path goes **only** through the interceptor → `/v1/validate`. The `AgentConnector` Python class is a dashboard/orchestration convenience and is not load-bearing for security.

---

## 3. Connector Abstraction (Component Design)

### 3.1 Directory Layout

```
src/connectors/
├── __init__.py
├── base/
│   ├── __init__.py
│   ├── agent_connector.py       # AgentConnector ABC
│   ├── models.py                # Platform, AgentResponse, ToolCall, etc.
│   └── exceptions.py
├── bedrock/
│   ├── __init__.py
│   ├── bedrock_connector.py     # BedrockConnector(AgentConnector)
│   └── event_translator.py      # parse_guardrail_trace()
├── azure_foundry/
│   ├── __init__.py
│   ├── azure_connector.py       # AzureConnector(AgentConnector)
│   ├── event_translator.py      # Azure tool-event → ValidationRequest
│   └── azure_function/
│       └── tool_interceptor/
│           ├── __init__.py      # HTTP-triggered handler
│           ├── function.json
│           └── requirements.txt
└── vertex_ai/                   # Phase 2
    ├── __init__.py
    ├── vertex_connector.py
    ├── event_translator.py
    └── cloud_run/
        └── tool_interceptor/
            ├── app.py           # Flask
            ├── Dockerfile
            └── requirements.txt
```

### 3.2 `AgentConnector` Contract

```python
class AgentConnector(ABC):
    platform: ClassVar[Platform]      # bedrock | azure_foundry | vertex_ai
    cloud_region: ClassVar[str]

    @abstractmethod
    def invoke_agent(
        self,
        agent_id: str,
        session_id: str,
        user_message: str,
        enable_trace: bool = True,
        **cloud_specific_kwargs,
    ) -> AgentResponse: ...

    @abstractmethod
    def parse_tool_calls(self, raw_response) -> list[ToolCall]: ...

    @abstractmethod
    def get_audit_trace(self, session_id: str) -> list[AuditEvent]: ...

    @abstractmethod
    def list_sessions(self, agent_id: str, **kwargs) -> list[SessionSummary]: ...

    @abstractmethod
    def delete_session(self, agent_id: str, session_id: str, **kwargs) -> bool: ...
```

Cloud-specific arguments (e.g., Bedrock's `agent_alias_id`) flow through `**cloud_specific_kwargs` without polluting the cross-cloud contract.

### 3.3 Backward-Compatibility Strategy (Bedrock)

The existing `src/dashboard/services/bedrock_agent_caller.py` is rewritten as a thin shim:

```python
class BedrockAgentCaller:
    def __init__(self, region_name="us-east-1"):
        self._connector = BedrockConnector(region_name)

    def invoke_agent(self, agent_id, agent_alias_id, session_id,
                     user_message, enable_trace=True):
        result = self._connector.invoke_agent(
            agent_id=agent_id, session_id=session_id,
            user_message=user_message, enable_trace=enable_trace,
            agent_alias_id=agent_alias_id,
        )
        # Override platform: asdict() preserves the Platform Enum object;
        # downstream JSON serializers need the string value. Do not "tighten".
        return asdict(result) | {"platform": result.platform.value}
```

All existing imports (`from services.bedrock_agent_caller import BedrockAgentCaller`) keep working unchanged.

---

## 4. Cross-Cloud Policy Model

### 4.1 Extended `agent_policies.yaml`

```yaml
sentra-mvp-customer-service-agent:
  platform: bedrock                  # NEW — connector that governs this agent
  cloud_region: us-east-1            # NEW — for audit display
  allowed_tools:
    - query_customers
    - get_order_details
    - process_refund
  allowed_agents:
    - azure-verification-agent       # NEW — cross-cloud dependency
  cross_cloud_dependencies:          # NEW — for S3 sequence validation
    - target_agent: azure-verification-agent
      target_tool: verify_image_authenticity
      required_before: [process_refund]
      max_age_seconds: 300
  max_calls_per_minute: 30

azure-verification-agent:            # NEW agent
  platform: azure_foundry
  cloud_region: centralus          # was eastus2 until 2026-05-23; moved due to PAYG App Service Plan Y1 quota issues in eastus2 (see best-practices.md §11 Azure region history)
  allowed_tools:
    - verify_image_authenticity
    - check_fraud_score
  allowed_agents: []
  max_calls_per_minute: 30
```

### 4.2 Schema Additions

| Field | Type | Default | Meaning |
|---|---|---|---|
| `platform` | `bedrock \| azure_foundry \| vertex_ai` | required | Which connector governs this agent. Surfaced in `/v1/validate` response for dashboard rendering. |
| `cloud_region` | string | required | Native cloud region identifier. Display-only in policy evaluation; recorded in audit log. |
| `cross_cloud_dependencies` | list[Dependency] | `[]` | Tool-sequence preconditions that may execute on a different cloud. Honored by `context_validator`. |

`Dependency` schema:

```yaml
- target_agent:    <agent_id>          # required
  target_tool:     <tool_name>         # required
  required_before: [<tool_names>]      # required — list of dependent tools on the source agent
  max_age_seconds: <int>               # required — sliding window
```

### 4.3 Storage

- **DynamoDB table**: existing `sentra-policies` table, no schema migration. New fields are JSON-stored alongside existing fields.
- **Seeding**: `scripts/seed_policies.py` reads `config/agent_policies.yaml` and writes to DDB. Update needed: load `platform` and `cross_cloud_dependencies` if present.

### 4.4 Policy Engine Changes

`src/security-controller/app/validators/policy_engine.py`:
- Read new fields from DDB.
- Include `platform` and `cloud_region` in the validation response payload (consumed by dashboard).
- **No evaluation logic change** — `allowed_tools` and `allowed_agents` checks remain identical.

### 4.5 Context Validator Changes (S3 Enforcement)

`src/security-controller/app/validators/context_validator.py`:
- Existing implementation tracks tool calls in the **DynamoDB `sentra-session-context` table** (`tool_history` attribute, appended via `list_append` on each validation). There is no Redis in the controller — see [config.py:20](../src/security-controller/app/config.py).
- **What the validator actually enforces (presence + recency, not ordering)**: when the requested tool appears in any cross-cloud dependency's `required_before` list, scan the session's `tool_history` for a matching `target_agent.target_tool` that occurred within `max_age_seconds`. The check is "did the prerequisite happen recently enough", not "did A happen before B before C". Calling this *strict sequence validation* would overpromise — the implementation is **presence-within-time-window**. See [context_validator.py:160-207](../src/security-controller/app/validators/context_validator.py#L160).
- Cross-cloud observations land in the same DynamoDB row because the security controller is the single source of truth — all `/v1/validate` calls (from any cloud's interceptor) append to the same `session_id` partition.

---

## 5. Data Models

### 5.1 `Platform` enum

```python
class Platform(str, Enum):
    BEDROCK = "bedrock"
    AZURE_FOUNDRY = "azure_foundry"
    VERTEX_AI = "vertex_ai"
```

### 5.2 `AgentResponse`

```python
@dataclass
class AgentResponse:
    response: str
    decision: str  # ALLOW | DENY | ERROR
    validation_result: dict | None
    latency_ms: int
    trace: dict
    error: str | None
    platform: Platform
    cloud_region: str
```

### 5.3 `ToolCall`, `ValidationContext`, `AuditEvent`, `SessionSummary`

Defined in [src/connectors/base/models.py](../src/connectors/base/models.py). All consumers (dashboard, demo orchestrator, integration tests) depend on these — never on cloud-specific shapes.

### 5.4 `ValidationRequest` (controller-side, unchanged shape)

The interceptor POSTs this payload to `/v1/validate`. Schema is already platform-agnostic. The only addition: `platform` and `cloud_region` optional fields used by the audit log for display, not evaluation.

**Status (2026-05-22)**: both fields are **already implemented** in [`src/security-controller/app/api/models.py:37-38`](../src/security-controller/app/api/models.py#L37) (`ValidationRequest`) and in [`src/connectors/base/models.py:33-34`](../src/connectors/base/models.py#L33) (`AgentResponse`). No model migration required for cross-cloud rollout.

```json
{
  "request_id": "azure-9f3e2a1b",
  "session_id": "session-123",
  "agent_id": "azure-verification-agent",
  "tool_name": "verify_image_authenticity",
  "tool_params": {"image_url": "...", "expected_subject": "cracked_eggs"},
  "user_input": "...",
  "timestamp": "2026-05-19T14:21:03.221Z",
  "operation_type": "READ",
  "platform": "azure_foundry",
  "cloud_region": "centralus"
}
```

---

## 6. Foreign-Cloud Interceptor Contract

Every interceptor (Lambda / Function / Run) implements the **same five steps**:

1. **Receive native tool-call event** (Bedrock Action Group event, Azure Function HTTP trigger, Cloud Run Flask request).
2. **Translate** to `ValidationRequest` via the cloud's `event_translator.py`.
3. **POST `/v1/validate`** with `x-api-key` header (key from Secrets Manager / Key Vault / Secret Manager).
4. **On DENY**: return native cloud error format (Bedrock 403 response body, Azure Function 403 HTTP, Cloud Run 403 JSON) with the reason.
5. **On ALLOW**: execute the native tool and return success in the cloud's native format.

The Bedrock implementation at [lambda/bedrock_agent_actions/index.py:50-118](../lambda/bedrock_agent_actions/index.py) is the canonical reference. Azure and GCP interceptors mirror its `validate_with_sentra()` function line-for-line.

---

## 7. Azure AI Foundry Implementation

> **⛔ BLOCKING dependency (2026-05-22)**: M3 (Azure Function) **cannot start** until [LLD 16](16-apigw-vpc-link-networking.md) and [Workstream 16](../tasks/workstream-16-apigw-vpc-link-networking.md) are deployed and verified. Concretely:
>
> 1. `curl -H "x-api-key: $KEY" https://iw3limi4k7.execute-api.us-east-1.amazonaws.com/prod/v1/health` returns **HTTP 200** (today it returns 500 — [LLD 16 §1.2](16-apigw-vpc-link-networking.md#12-what-was-actually-built-the-bug)).
> 2. Bedrock Lambda CloudWatch logs show real ALLOW/DENY decisions on subsequent invocations (the Lambda has been silently fail-securing since deploy — see [LLD 16 §1.4](16-apigw-vpc-link-networking.md#14-who-else-this-affects-beyond-cross-cloud)).
>
> The Azure Function targets the same API Gateway URL the Bedrock Lambda already uses; no new AWS-side networking is required for cross-cloud once LLD 16 ships.

### 7.1 Components

```
infrastructure/azure/
├── azure.yaml                      # azd project descriptor (services, hooks, env)
├── infra/
│   ├── main.bicep                  # Top-level deployment (entry for `azd up`)
│   ├── modules/
│   │   ├── function_app.bicep      # Function App + plan + storage
│   │   ├── key_vault.bicep         # Sentra API key + Function MI access
│   │   ├── ai_foundry.bicep        # AI Foundry project + connection
│   │   └── agent.bicep             # azure-verification-agent definition
│   └── main.parameters.json        # azd-managed env params
└── README.md                       # `azd up` / `azd down` recipe
```

**IaC tool: `azd` (Azure Developer CLI)** — not a bash wrapper. `azd up` provisions, `azd down` tears down cleanly, `azd env new <name>` supports parallel envs. This matches the `cdk deploy`/`cdk destroy` pattern on the AWS side and supports the demo-and-tear-down workflow ([Workstream 15 M6](../tasks/workstream-15-cross-cloud-demo.md)) without custom scripting. See [best-practices.md §11](../best-practices.md).

### 7.2 Azure Function — `tool_interceptor`

- **Runtime**: Python 3.11, HTTP trigger, anonymous auth at function level (gated by Function App-level access policy).
- **Hosting plan (as deployed 2026-05-23)**: **B1 Basic Linux App Service Plan** (~$13/mo flat, always-on). Originally specced as Y1 Consumption but switched after Y1 in centralus had a Function App data-plane that never scaled past 0 workers — see [Workstream 15 M3 Lessons Learned](../tasks/workstream-15-cross-cloud-demo.md#m3-deploy-time-lessons-learned-2026-05-23). B1 has guaranteed always-on workers so cold-start is not a concern, and `azd down` between demo recordings still drops cost to ~$0/day.
- **Secrets**: API key fetched from Azure Key Vault via Managed Identity on first request, cached in-memory per instance (mirrors the Lambda's `_api_key_cache`).
- **Outbound**: HTTPS to the **API Gateway public URL** (`https://iw3limi4k7.execute-api.us-east-1.amazonaws.com/prod/v1/validate`), with the `x-api-key` header set from the Sentra API key stored in Key Vault. The controller path through AWS is: API Gateway → VPC Link → Private ALB → ECS. No new AWS infrastructure is required for cross-cloud — the endpoint is already deployed. **Region pairing (as deployed 2026-05-23)**: Azure `centralus` ↔ AWS `us-east-1`, p95 cross-cloud latency ~30-40ms (was targeted as `eastus2` ↔ `us-east-1` at ~10-20ms but moved due to PAYG quota propagation lag — see [Workstream 15 M3 Lessons Learned](../tasks/workstream-15-cross-cloud-demo.md#m3-deploy-time-lessons-learned-2026-05-23)). Still well inside the §12 `p95 ≤120ms` budget.

### 7.3 Azure AI Foundry Agent — `azure-verification-agent`

- **Model**: `gpt-4o-mini` or `o3-mini` (cost-effective for verification tasks).
- **Tools** (function calling, OpenAI schema):
  - `verify_image_authenticity(image_url, expected_subject) -> {authentic: bool, confidence: float}`
  - `check_fraud_score(transaction_id) -> {score: int, factors: list}`
- **Tool execution**: routed through the Azure Function `tool_interceptor` (the Foundry agent calls the Function URL as the tool endpoint).

### 7.4 `AzureConnector` (dashboard-side)

- Uses `azure-ai-projects` SDK (or `azure-ai-agents` once GA-stable) to invoke the agent and stream the response.
- Translates the response into `AgentResponse` for the dashboard.
- The actual security decisions are made by the Function → `/v1/validate` pipeline; this class is dashboard-only.

---

## 8. Phase 2 — GCP Vertex AI Implementation

### 8.1 Architectural Parity

GCP Phase 2 mirrors the Azure pattern with one difference: Gemini's function-call schema requires more translation work than Azure's OpenAI-compatible schema.

- **Interceptor**: Cloud Run service (Python + Flask) replaces Azure Function.
- **Agent**: Vertex AI Agent Builder agent with `gemini-2.0-flash` and function-calling tools.
- **IaC**: Terraform under `infrastructure/gcp/` (no GCP-native equivalent to CDK/Bicep at parity).
- **Auth**: Service Account JSON or Workload Identity Federation.

### 8.2 Effort Estimate

~1.5 weeks once Phase 1 is complete and the connector abstraction is proven.

---

## 9. Demo Scenarios S1–S4

Each scenario is a YAML file in `src/demo-orchestrator/scenarios/` and executes against the live deployment.

> **Workstream 17 update** (2026-05-26): the dashboard's per-step "By" column is now driven by the combiner output from `GET /v1/sessions/{id}/decisions` (LLD 17 §8.2), not the legacy CloudWatch-Insights audit_lookup. Each step's row also expands to a signal-by-signal breakdown showing every contributor (`sentra.sigma`, `sentra.trust`, `bedrock_guardrail`, etc.). The runner originates one `request_id` per step and threads it via Bedrock `sessionAttributes` / Azure HTTP body so every signal Sentra and the connectors emit correlates to one row. See LLD 17 §9.1 for the plumbing.

### S1 — Unified Governance Pane (`s1_unified_governance_pane.yaml`)

**Setup**: Two independent agents — `sentra-mvp-customer-service-agent` (Bedrock) and `azure-hr-assistant-agent` (Azure Foundry). Same `AgentPolicy` schema, different platforms.

**Demo flow**: Run an identical attack prompt against both. Dashboard shows both blocks side-by-side in one view.

**Asserts**: Both `validation_result.decision == "DENY"`; dashboard renders both rows with their `Cloud` column populated.

### S2 — Cross-Cloud Policy Propagation (`s2_cross_cloud_policy_propagation.yaml`)

**Setup**: Same two agents from S1. Initially, both allow `query_customers`.

**Demo flow**: Apply an updated policy via control-plane CLI that removes `query_customers` from `allowed_tools`. Run `query_customers` against both agents within 10 seconds.

**Asserts**: Within ≤10s of policy update, both clouds enforce the new rule (DENY). Dashboard timestamps the propagation delta.

### S3 — Cross-Cloud Tool-Call Precondition (Presence-Within-Window) — Swiggy Egg-Fraud, Cross-Cloud (`s3_cross_cloud_sequence_validation.yaml`)

**What this enforces (precise)**: `process_refund` on the Bedrock agent will be denied unless `azure-verification-agent.verify_image_authenticity` has been observed in the same session's `tool_history` within the last `max_age_seconds`. This is a **presence + recency** check against the DynamoDB session-context store — not a multi-step ordering proof (§4.5).

**Setup**: `sentra-mvp-customer-service-agent` (Bedrock) has a `cross_cloud_dependencies` rule requiring `azure-verification-agent.verify_image_authenticity` before `process_refund` within 300 seconds.

**Demo flow**:
- *Attack path*: User submits refund with fake cracked-eggs photo; agent skips verification and calls `process_refund` directly.
- *Expected*: AegionAI blocks because no matching prior `verify_image_authenticity` was observed in this session's `tool_history` within the window.

**Asserts**: `validation_result.reason` contains `cross_cloud_dependency_not_met`; dashboard renders both clouds in one timeline showing the missing verification step.

### S4 — Session-Scoped Cross-Cloud Containment (`s4_cross_cloud_blast_radius.yaml`)

**What this is (and is not)**: containment is tracked per **session** (`session_id`), not per agent, and S4 does **not** perform a real agent-to-agent invocation. All steps share one `session_id`; once that session is quarantined by the Bedrock-side injections, the subsequent Azure call in the *same session* is denied. There is no Bedrock→Azure `invoke_agent`. A genuine cross-agent invocation (one agent calling another, denied at the boundary) is **S5** (§9 S5).

**Setup**: A single attack session issues repeated prompt injections at the Bedrock agent.

**Demo flow**:
- The compromised Bedrock agent receives repeated prompt-injection inputs. Each is denied by the sigma engine and drops the **session** trust score by 20 (`PROMPT_INJECTION` penalty). **Three** such denials drive trust 100 → 80 → 60 → **40**, which falls into the **Quarantined** band (LLD 03 §6.2; the warning boundary is `> 40`).
- A quarantined session is treated as compromised and is blocked from **all** operations — read and write (LLD 03 §6.2, updated 2026-06-04). This is the containment lever: the session cannot pivot to another agent/cloud.
- When the Azure-side `/v1/validate` call (`check_fraud_score`, a READ) arrives in that same session, the trust checker sees `quarantine_status=quarantined` and returns DENY before the Azure tool runs.

**Asserts**: The Azure-side call returns DENY with `violation_type=QUARANTINE_BLOCKED` and `quarantine` in the reason; the Azure tool never executes.

> **Note (2026-06-04)**: an earlier version of this scenario assumed *two* injections quarantined the agent and that quarantine blocked the Azure call. Neither held: `PROMPT_INJECTION` is −20 so two denials only reach trust 60 (Warning), and quarantine previously blocked WRITE only (the Azure probe is a READ). Fixed by (a) a third compromise step to reach 40, and (b) quarantine now blocking all operations. See [Workstream 15 Task 5.4](../tasks/workstream-15-cross-cloud-demo.md).

---

## 10. Configuration

### 10.1 Environment Variables (Azure Function)

| Variable | Source | Purpose |
|---|---|---|
| `SENTRA_API_ENDPOINT` | Bicep parameter | `https://iw3limi4k7.execute-api.us-east-1.amazonaws.com/prod/v1/validate` (the live API Gateway URL fixed by [LLD 16](16-apigw-vpc-link-networking.md); custom domain is a Phase 2 polish item, not committed) |
| `SENTRA_API_KEY_VAULT_NAME` | Bicep parameter | Key Vault name holding the API key |
| `SENTRA_API_KEY_SECRET_NAME` | Bicep parameter | Secret name inside the Key Vault |
| `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT` | Bicep output | For audit logging back-reference |

### 10.2 Policy Seeding

`scripts/seed_policies.py` updated to load `platform`, `cloud_region`, and `cross_cloud_dependencies` fields from `config/agent_policies.yaml` into the `sentra-policies` DDB table.

---

## 11. Error Handling

- **Fail secure**: All interceptors deny on any error (network, parse, controller 5xx). Matches the existing Bedrock Lambda pattern.
- **Timeout**: 5s on `/v1/validate` call from any cloud. Tunable per interceptor environment variable.
- **Connector class errors**: `AgentInvocationError` raised on native-cloud-agent failures; surfaced in `AgentResponse.decision = "ERROR"`, never silent.

---

## 12. Monitoring & Observability

- **Latency**: Each interceptor records its end-to-end latency (tool-call receipt → controller response → native return). Cross-cloud latency target: p95 ≤120ms (vs. 80ms single-cloud).
- **Audit log**: Controller writes one entry per `/v1/validate` call regardless of source cloud, with `platform` and `cloud_region` columns for filtering.
- **Dashboard**: New cross-cloud timeline view stitches audit log entries by `session_id`, sorted chronologically — irrespective of source cloud.

---

## 13. Cross-References

| Document | Purpose |
|---|---|
| [Workstream 15](../tasks/workstream-15-cross-cloud-demo.md) | Execution tracking — milestones, tasks, status |
| [LLD 03: Security Controller](03-security-controller.md) | `/v1/validate` contract |
| [LLD 09: Bedrock Agent Execution](09-agent-execution-and-llm-response.md) | Reference interceptor pattern |
| [LLD 11: Agent Policy CRUD](11-agent-policy-crud.md) | Policy data model touched by §4 |
| [LLD 13: Demo Orchestrator](13-demo-orchestrator.md) | YAML scenario framework re-used by §9 |
| [ADR-020](../adr.md#adr-020-azure-first-gcp-fast-follow-for-cross-cloud-demo) | Cloud sequencing decision |
| [ADR-021](../adr.md#adr-021-connector-abstraction-with-foreign-cloud-interceptors) | Connector architecture decision |
| [LLD 16: API Gateway VPC Link Networking](16-apigw-vpc-link-networking.md) | **Hard prerequisite for M3** — fixes the API Gateway URL the Azure Function targets. See §7 BLOCKING callout. |
| [Workstream 16](../tasks/workstream-16-apigw-vpc-link-networking.md) | Execution tracking for the LLD 16 fix |
| [LLD 17: Validation Signal Store](17-validation-signal-store.md) | Multi-signal substrate that powers the dashboard's "By" column and signal expander. Replaces the CloudWatch-Insights-backed audit_lookup (which had 60s+ indexing lag — see LLD 17 §2) with a DDB-backed `/v1/sessions/{id}/decisions` query. Bedrock + Azure connectors thread `request_id` via sessionAttributes / HTTP body and emit `bedrock_guardrail` / `azure_content_filter` edge signals (LLD 17 §9.1, §9.3). |
| [Workstream 17](../tasks/workstream-17-validation-signal-store.md) | Execution tracking for the LLD 17 substrate rollout |
| [pitch/pitch-deck-v4.md](../pitch/archive/pitch-deck-v4.md) | Investor commitment this workstream delivers |
