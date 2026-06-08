# Workstream 15: Cross-Cloud Demo (AWS + Azure → GCP)

**Status:** In Progress (Milestone 1 complete)
**Owner:** Founder + 1 backend engineer
**Start Date:** 2026-05-19
**Target Completion (Phase 1, AWS+Azure):** 2026-06-02 (2 weeks)
**Target Completion (Phase 2, +GCP):** 2026-06-16 (4 weeks)
**LLD Reference:** [lld/15-cross-cloud-connectors.md](../lld/15-cross-cloud-connectors.md)
**HLD Section:** [design-hld.md §3.7 Cross-Cloud Connector Layer](../design-hld.md)
**ADRs:** [ADR-020](../adr.md#adr-020-azure-first-gcp-fast-follow-for-cross-cloud-demo), [ADR-021](../adr.md#adr-021-connector-abstraction-with-foreign-cloud-interceptors)

---

## Overview

Deliver a live AWS + Azure cross-cloud demo that closes the single largest investor credibility gap: AegionAI's thesis is cross-cloud governance, but the current demo runs on AWS only. Phase 1 delivers AWS + Azure; Phase 2 adds GCP behind the same connector abstraction. Demo includes four scenarios (S1–S4) targeting unified governance pane, cross-cloud policy propagation, cross-cloud tool-call preconditions (presence-within-time-window; Swiggy-style fraud prevention generalized), and cross-cloud blast-radius containment. See [LLD 15 §1.3](../lld/15-cross-cloud-connectors.md#13-core-capabilities) for the precise semantics of what S3 enforces.

### Goals

1. Cloud-agnostic `AgentConnector` abstraction enabling new clouds in ~1 week each.
2. Azure AI Foundry connector + Azure Function tool interceptor in production-grade Bicep IaC.
3. Policy model extended with `platform`, `cloud_region`, `cross_cloud_dependencies` fields, honored by the existing context validator.
4. Four investor-grade demo scenarios authored as executable YAMLs and run end-to-end.
5. Recorded 4-minute demo video for the seed-raise narrative.
6. GCP Vertex AI as Phase 2 fast-follow, validated by re-running S1–S4 with AWS + GCP.

### Success Criteria

- ✅ AWS + Azure agents visible in one dashboard with their `Cloud` column populated.
- ✅ One `AgentPolicy` enforced uniformly across both clouds within ≤10s of update (S2).
- ✅ Swiggy-style cross-cloud precondition violation (missing prerequisite tool within the time window) blocked at runtime (S3).
- ✅ Cross-cloud cascade attempt contained at the Azure sidecar without the tool executing (S4).
- ✅ End-to-end p95 latency ≤120ms across the cross-cloud path.
- ✅ All four scenarios pass in `pytest tests/integration/test_cross_cloud_scenarios.py`.
- ✅ Demo video recorded, single take, ≤4 minutes.

---

## Milestone 1: Foundation — Connector Abstraction + Bedrock Refactor (1 day) ✅

**Status:** ✅ COMPLETE (2026-05-19)

### Task 1.1: Connector Abstraction Layer ✅

**Status:** ✅ COMPLETE
**Effort:** 3 hours
**Priority:** P0
**Files (created):**
- `src/connectors/__init__.py`
- `src/connectors/base/__init__.py`
- `src/connectors/base/agent_connector.py`
- `src/connectors/base/models.py`
- `src/connectors/base/exceptions.py`

**Acceptance:**
- ✅ `AgentConnector` ABC declares 5 abstract methods (`invoke_agent`, `parse_tool_calls`, `get_audit_trace`, `list_sessions`, `delete_session`).
- ✅ `Platform` enum, `AgentResponse`, `ToolCall`, `ValidationContext`, `AuditEvent`, `SessionSummary` dataclasses defined.
- ✅ `python3 -c "from connectors.base import *"` succeeds.

### Task 1.2: Refactor Bedrock Behind AgentConnector ✅

**Status:** ✅ COMPLETE
**Effort:** 4 hours
**Priority:** P0
**Files (created):**
- `src/connectors/bedrock/__init__.py`
- `src/connectors/bedrock/bedrock_connector.py`
- `src/connectors/bedrock/event_translator.py` (extracted `parse_guardrail_trace`)

**Files (modified):**
- `src/dashboard/services/bedrock_agent_caller.py` — rewritten as backward-compat shim around `BedrockConnector`

**Acceptance:**
- ✅ `BedrockConnector` implements every abstract method on `AgentConnector`.
- ✅ Existing dashboard import in `src/dashboard/tabs/agents_tab.py:232` works unchanged.
- ✅ Legacy `BedrockAgentCaller()` returns the same dict shape as before.

---

## Milestone 2: Policy & Validation Extensions (2 days) ✅

**Status:** ✅ COMPLETE 2026-05-20 — all 5 sub-tasks done, 7/7 context-validator unit tests pass, both DDB paths (legacy `sentra-policies` and active `sentra-policies-metadata` + S3) migrated.
**Goal:** Extend the policy data model with `platform`, `cloud_region`, `cross_cloud_dependencies`; teach the context validator to honor them; **migrate existing DDB policy entries to the new schema** so existing Bedrock agents have correct `platform: bedrock` / `cloud_region: us-east-1` values.

### Task 2.1: Extend `agent_policies.yaml` schema

**Status:** ✅ COMPLETE (2026-05-20)
**Effort:** 1.5 hours
**Priority:** P0
**Files:**
- `config/agent_policies.yaml` (modify)

**Description:**
Add `platform`, `cloud_region`, `cross_cloud_dependencies` fields to **every existing agent entry** (mark all existing entries as `platform: bedrock`, `cloud_region: us-east-1`). Add new `azure-verification-agent` entry with `platform: azure_foundry`, `cloud_region: eastus2`. No code changes in this task — YAML only.

**Acceptance:**
- `customer-query-agent`, `payment-agent`, and `sentra-mvp-customer-service-agent` all have `platform` and `cloud_region` fields populated.
- `azure-verification-agent` entry exists with `verify_image_authenticity` and `check_fraud_score` in `allowed_tools`.
- `sentra-mvp-customer-service-agent` has a `cross_cloud_dependencies` entry requiring `azure-verification-agent.verify_image_authenticity` before `process_refund`.

### Task 2.2: Update `seed_policies.py` to handle new fields

**Status:** ✅ COMPLETE (2026-05-20)
**Effort:** 1.5 hours
**Priority:** P0
**Files:**
- `scripts/seed_policies.py` (modify)

**Description:**
The seeder reads `agent_policies.yaml` and writes to the DDB `sentra-policies` table. Update it to:
1. Read the new fields (`platform`, `cloud_region`, `cross_cloud_dependencies`) from YAML.
2. Write them to DDB using **upsert** semantics (DDB `put_item` is already idempotent; verify behavior).
3. Tolerate missing fields gracefully — if `platform` is absent in YAML, default to `unknown` and log a warning rather than failing.

**Acceptance:**
- Running `python scripts/seed_policies.py` against a fresh DDB table writes all fields.
- Running it a second time produces the same result (idempotent).
- A YAML entry missing `platform` produces a warning but does not crash.

### Task 2.3: Migrate Existing DDB Policy Entries

**Status:** ✅ COMPLETE (2026-05-20). **Both paths migrated** — legacy `sentra-policies` DDB and active `sentra-policies-metadata` + S3. The first attempt only covered the legacy path (mistake caught and corrected); see [[policy-storage-architecture]] memory for the dual-storage architecture.
**Effort:** 1 hour
**Priority:** P0
**Files:**
- `scripts/seed_policies.py` (re-run against live DDB)
- `scripts/verify_policy_migration.py` (new — verification utility)

**Description:**
The DDB `sentra-policies` table already has entries for existing agents (without the new fields). After Task 2.2 the seeder *can* write new fields, but the existing entries need to be **updated** to include them. The safest path: re-run `seed_policies.py` against the live table (relies on the upsert semantics confirmed in Task 2.2). Then run a verification script that scans the table and asserts every entry has `platform` and `cloud_region` populated.

**Acceptance:**
- `aws dynamodb scan --table-name sentra-policies` shows every entry has `platform` and `cloud_region` fields.
- No existing field on any entry was lost (allowed_tools, allowed_agents, max_calls_per_minute remain intact).
- `verify_policy_migration.py` exits 0 and prints a summary table.

### Task 2.4: Surface `platform` in Validation Response

**Status:** ✅ COMPLETE (2026-05-20)
**Effort:** 2 hours
**Priority:** P0
**Files:**
- `src/security-controller/app/validators/policy_engine.py` (modify)
- `src/security-controller/app/api/routes.py` (modify — optional `platform`, `cloud_region` in `ValidationRequest`)

**Acceptance:**
- `/v1/validate` response includes `platform` field for the dashboard to render.
- Audit log entries include `platform` and `cloud_region`.

### Task 2.5: Honor `cross_cloud_dependencies` in Context Validator

**Status:** ✅ COMPLETE (2026-05-20). 7/7 new unit tests pass in `tests/test_context_validator_cross_cloud.py`.
**Effort:** 6 hours
**Priority:** P0
**Files:**
- `src/security-controller/app/validators/context_validator.py` (modify)
- `tests/unit/test_context_validator_cross_cloud.py` (new)

**Description:**
When evaluating a tool call, check if any `cross_cloud_dependencies` rule applies. If so, scan the session's `tool_history` in the DynamoDB `sentra-session-context` table for a matching `target_agent.target_tool` entry within `max_age_seconds` (presence + recency, not multi-step ordering — see [LLD 15 §4.5](../lld/15-cross-cloud-connectors.md#45-context-validator-changes-s3-enforcement)). DENY with `cross_cloud_dependency_not_met` reason if absent.

**Acceptance:**
- Unit test: tool call denied when prerequisite is absent.
- Unit test: tool call allowed when prerequisite recorded within window.
- Unit test: prerequisite recorded outside window → denied.

---

## Milestone 3: Azure AI Foundry Connector + Infrastructure (5 days) ✅

**Status:** ✅ COMPLETE 2026-05-23 — full cross-cloud loop verified end-to-end.

**Verified flow:**
```
Dashboard
  → AzureConnector (src/connectors/azure_foundry/azure_connector.py)
  → Azure OpenAI gpt-4o-mini (https://aegionai-ws15-m3-openai.openai.azure.com/)
  → tool_calls
  → Azure Function tool_interceptor (https://aegionai-ws15-m3-func.azurewebsites.net/api/tool/...)
  → AWS API Gateway (https://iw3limi4k7.execute-api.us-east-1.amazonaws.com/prod/v1/validate)
  → VPC Link → NLB → Private ALB → Sentra Security Controller
  → decision=ALLOW + trust_score=100 + platform=azure_foundry + cloud_region=centralus
  → back through the stack
  → natural-language response to user
```

**Deployed resources** (all in resource group `aegionai-ws15-m3-rg`, region `centralus`):
- Key Vault (`aeg-kv-ts6rlvixg473s`) with Sentra API key seeded from AWS Secrets Manager
- Storage Account (`aegts6rlvixg473s`) for Function backing
- App Insights (`aegionai-ws15-m3-insights`) with 100MB/day cap, 30d retention
- App Service Plan (`aegionai-ws15-m3-plan`) — B1 Basic Linux (~$13/mo flat, always-on)
- Function App (`aegionai-ws15-m3-func`) — Python 3.11, v2 model, stdlib-only deps
- Azure OpenAI account (`aegionai-ws15-m3-openai`) with gpt-4o-mini deployment (GlobalStandard, 100k TPM)

**Why 5-day estimate took 1 day**: WS16 unblock + dedicating focused time + Portal-detector-driven diagnosis turned a "guess and check" debugging cycle into specific evidence-driven fixes. The lessons learned are now baked into Bicep, `azure.yaml`, `best-practices.md` §11, and LLD 15 §7 so future Azure work won't repeat them.

**See also**: [M3 Deploy-Time Lessons Learned](#m3-deploy-time-lessons-learned-2026-05-23) section below for the 8 rules accumulated during this milestone.
**Prior blocker (resolved):** WS16 fixed the API Gateway VPC Link routing. See [LLD 16 §1.7](../lld/16-apigw-vpc-link-networking.md#17-intended-outcome) for verified outcomes and [Workstream 16 §Deploy-Time Findings](workstream-16-apigw-vpc-link-networking.md#deploy-time-findings-2026-05-22) for lessons-learned that apply here too (especially the ASCII-only SG description rule if we add Azure NSGs).
**Goal:** Bring up the Azure half of the demo: AI Foundry agent, Function App interceptor, Bicep IaC, dashboard connector.

### Task 3.1: Author Azure Bicep Infrastructure (driven by `azd`) ✅

**Status:** ✅ COMPLETE 2026-05-23 — `azd provision` is idempotent; all 6 resources land cleanly in `centralus` (not `eastus2` per acceptance — see lessons learned §2). Sentra API key seeded via `scripts/seed-api-key.sh` postProvision hook. Bicep modules: `function_app.bicep`, `key_vault.bicep`, `key_vault_role.bicep`, `ai_foundry.bicep` (filled in), `agent.bicep` (kept as stub — agent definition lives in `agent-spec/azure_verification_agent.json`, not Bicep).
**Effort:** 1.5 days (estimated) / ~1 day (actual including the Y1→B1 detour)
**Priority:** P0
**Files:**
- `infrastructure/azure/azure.yaml` (new — `azd` project descriptor)
- `infrastructure/azure/infra/main.bicep` (new)
- `infrastructure/azure/infra/modules/function_app.bicep` (new)
- `infrastructure/azure/infra/modules/key_vault.bicep` (new)
- `infrastructure/azure/infra/modules/ai_foundry.bicep` (new)
- `infrastructure/azure/infra/modules/agent.bicep` (new)
- `infrastructure/azure/infra/main.parameters.json` (new)
- `infrastructure/azure/README.md` (new — `azd up` / `azd down` recipe)

**Tooling decision (2026-05-22):** use `azd` (Azure Developer CLI) — `brew install azd`. Mirrors `cdk deploy`/`cdk destroy` on the AWS side. Supports `azd env new <name>` for multi-env, `azd provision --preview` for what-if, and `azd down` for clean teardown in one command. **Do not write a custom `deploy.sh` bash wrapper** — `azd up` is the entry point.

**Acceptance:**
- `cd infrastructure/azure && azd up` provisions Function App, Key Vault, AI Foundry project, and `azure-verification-agent` in `eastus2`.
- `azd down` cleanly removes the entire resource group.
- `azd provision --preview` shows a dry-run plan without changes.
- Function App's managed identity has `Key Vault Secrets User` role.
- Sentra API key seeded into Key Vault.

### Task 3.2: Build Azure Function Tool Interceptor ✅

**Status:** ✅ COMPLETE 2026-05-23 — Python v2 model with `@app.route` decorators. Routes `POST /api/tool/{tool_name}` (validates with Sentra, executes mock tool on ALLOW, returns 403 on DENY) and `GET /api/health`. Uses stdlib `urllib.request` instead of `requests` to avoid the `azd deploy` + Oryx Remote Build issue (lessons learned §5). Deployed to `aegionai-ws15-m3-func.azurewebsites.net`; smoke verified via `curl` (HTTP 200 with full JSON health body, decision=ALLOW on tool dispatch).
**Effort:** 1 day (estimated) / ~6 hours (actual)
**Priority:** P0
**Files:**
- `src/connectors/azure_foundry/azure_function/tool_interceptor/__init__.py` (new)
- `src/connectors/azure_foundry/azure_function/tool_interceptor/function.json` (new)
- `src/connectors/azure_foundry/azure_function/tool_interceptor/requirements.txt` (new)
- `src/connectors/azure_foundry/event_translator.py` (new)

**Description:**
Mirrors `lambda/bedrock_agent_actions/index.py`. HTTP-triggered Azure Function that:
1. Receives Azure AI Foundry tool-call event.
2. Translates to `ValidationRequest`.
3. POSTs `/v1/validate`.
4. Returns 403 on DENY, executes tool and returns 200 on ALLOW.

**Deploy path (decided 2026-05-22):** declare the Function as a `services:` entry in `infrastructure/azure/azure.yaml` so `azd up` (Task 3.1) handles both infra provisioning AND source publish in a single command. This keeps the "no custom deploy.sh — `azd` is the entry point" principle from Task 3.1 intact. `func azure functionapp publish` is acceptable as a local fallback for inner-loop iteration only; CI/demo uses `azd up`.

**Acceptance:**
- Locally testable with `func start` and a synthetic Azure tool-call event.
- `azd up` (from Task 3.1) provisions infra AND publishes this Function in one command. `func azure functionapp publish` works as a local-dev fallback.
- `azure.yaml` has a `services:` block referencing `src/connectors/azure_foundry/azure_function/tool_interceptor/`.

### Task 3.3: Build `AzureConnector` (dashboard-side) ✅

**Status:** ✅ COMPLETE 2026-05-23 — Implements all 5 `AgentConnector` ABC methods. Loads `agent-spec/azure_verification_agent.json`, calls Azure OpenAI gpt-4o-mini with function-calling tools, routes every tool_call through the Function App's `/api/tool/{name}` (so each call is Sentra-validated). Iterates up to 5 tool-call rounds. On DENY: stops, lets model summarize the denial in natural language. Smoke-tested end-to-end (dashboard → AzureConnector → gpt-4o-mini → Function → Sentra → ALLOW → response). Uses stdlib `urllib.request` to match the Function-side dependency posture.
**Effort:** 6 hours (estimated) / ~3 hours (actual)
**Priority:** P0
**Files:**
- `src/connectors/azure_foundry/__init__.py` (new)
- `src/connectors/azure_foundry/azure_connector.py` (new)

**Acceptance:**
- Implements every `AgentConnector` abstract method.
- Successfully invokes `azure-verification-agent` and returns a normalized `AgentResponse`.

### Task 3.4: Define `azure-verification-agent` in AI Foundry ✅

**Status:** ✅ COMPLETE 2026-05-23 — Agent spec authored as JSON at [`infrastructure/azure/agent-spec/azure_verification_agent.json`](../infrastructure/azure/agent-spec/azure_verification_agent.json). Includes system prompt, gpt-4o-mini model config, two tool function definitions (`verify_image_authenticity`, `check_fraud_score` with OpenAI function-calling schemas), tool_endpoint pointing to the Function App, and a sentra_policy_reference cross-link to `config/agent_policies.yaml`. AzureConnector loads this spec at init; the Bicep-deployed Azure OpenAI deployment hosts the model. (No `agent.bicep` resource needed — the AI Foundry Agent Service API surface is still evolving, and the spec-as-JSON approach is more portable across the SDK churn.)
**Effort:** 4 hours (estimated) / ~30 min (actual)
**Priority:** P0
**Files:**
- ~~`infrastructure/azure/infra/modules/agent.bicep`~~ — **deleted 2026-05-24**; agent definition lives in JSON, not Bicep (the AI Foundry Agent Service API is still evolving). See `agent-spec/azure_verification_agent.json`.
- `infrastructure/azure/agent-spec/azure_verification_agent.json` (new — agent definition with tool schemas)

**Acceptance:**
- Agent responds to `verify_image_authenticity` and `check_fraud_score` tool calls.
- Tool execution routes through the Azure Function interceptor.

---

## Milestone 4: Dashboard Factory + Cross-Cloud UI (1.5 days) ✅

**Status:** ✅ COMPLETE 2026-05-23 — factory + Cross-Cloud Agent Inventory table + Cross-Cloud Activity Timeline shipped.
**Goal:** Make the dashboard cloud-agnostic via a connector factory and render cross-cloud audit timelines.

### Task 4.1: `agent_caller_factory.py` ✅

**Status:** ✅ COMPLETE 2026-05-23 — 11/11 unit tests pass in `tests/unit/test_agent_caller_factory.py`. Resolver reads `config/agent_policies.yaml` (the same source `scripts/seed_policies.py` mirrors into DDB+S3) so the factory works without AWS credentials. Connector cache is keyed on `(platform, region)` so two Bedrock agents in `us-east-1` share one client. Fail-loud on unknown agents / Vertex (Phase 2) — no silent fallback to a default connector.
**Effort:** 3 hours (estimated) / ~1 hour (actual)
**Priority:** P0
**Files:**
- `src/dashboard/services/agent_caller_factory.py` (new)
- `tests/unit/test_agent_caller_factory.py` (new)

**Description:**
Look up an agent's `platform` from the policy source (YAML file = source of truth, mirrored to DDB+S3 by the seeder) and return the matching connector instance.

**Acceptance:**
- ✅ `get_connector("sentra-mvp-customer-service-agent")` → `BedrockConnector(region='us-east-1')`.
- ✅ `get_connector("azure-verification-agent")` → `AzureConnector(region='centralus')`.
- ✅ Same `(platform, region)` reuses the cached connector instance.
- ✅ Unknown agent → `UnknownPlatformError` (no silent fallback).
- ✅ Pluggable `connector_builder` for tests; `invalidate()` clears caches after YAML edits.

### Task 4.2: `Cloud` Column + Cross-Cloud Timeline View ✅

**Status:** ✅ COMPLETE 2026-05-23 — both views render against live controller data and degrade gracefully on transport failure (the table still shows platform+region from the YAML; the timeline shows a friendly "no entries" warning).
**Effort:** 1 day (estimated) / ~1 hour (actual — additive sections, no rewrite of existing UI)
**Priority:** P1
**Files:**
- `src/dashboard/tabs/agents_tab.py` (modified — `_render_cross_cloud_inventory` added at the top)
- `src/dashboard/tabs/overview_tab.py` (modified — `_render_cross_cloud_timeline` added below Rollback panel)

**Acceptance:**
- ✅ Agents tab now opens with a "🌐 Cross-Cloud Agent Inventory" dataframe: columns Agent, Agent ID, Cloud (🟧 AWS Bedrock / 🟦 Azure Foundry / 🟩 GCP Vertex), Region, Status, Trust. Pulled from `agent_caller_factory.list_platforms()` and enriched with `/v1/agents?enrich=true` runtime stats.
- ✅ Overview tab now has a "🌐 Cross-Cloud Activity Timeline" section: pick a session (dropdown of recent sessions OR manual session_id), see every `/v1/logs` audit entry sorted chronologically with platform/region/agent/tool/decision/latency. Per-cloud event counts surface above the table.
- ✅ Existing self-hosted/Bedrock split UI in agents_tab is untouched — both new sections are purely additive to keep blast-radius low for the investor demo.

---

## Milestone 5: Demo Scenarios S1–S4 (2 days) ✅

**Status:** ✅ COMPLETE 2026-05-25 — all four scenario YAMLs authored, dashboard runner shipped, 21 new unit tests passing.
**Goal:** Author four executable scenario YAMLs and ship a dashboard demo experience that drives them across AWS + Azure with one click.

**Architecture (deviation from original spec):** the original plan had the orchestrator execute scenarios end-to-end. That couldn't share session_ids across clouds (the orchestrator generates one per prompt), which breaks S3's `cross_cloud_dependencies` evaluation. We instead shipped a **dashboard-side runner** (`src/dashboard/components/cross_cloud_scenarios.py`) that:

- Loads scenarios via the orchestrator's `/demo/scenarios/{id}` API (single source of truth).
- Generates one session_id per scenario, feeds it to every step → controller's context validator sees all events under one session (LLD 15 §4.5).
- Drives Bedrock via the existing `BedrockAgentCaller` shim, Azure via `AzureConnector` (LLM-driven prompts) and direct Function tool POSTs (deterministic tools).
- Calls `scripts/apply_policy.py` in-process for S2's policy-update step.
- Aggregates a `ScenarioOutcome` with deny/allow/error counts and a templated narrative.

The orchestrator's existing `prompts:` block still runs the AWS-only half via `/demo/scenarios/<id>/trigger` for traditional smoke testing. The new `cross_cloud:` block is additive and ignored by the orchestrator (backwards-compat).

### Task 5.1: S1 — Unified Governance Pane ✅ (rev 2: defense-in-depth narrative)

**Status:** ✅ COMPLETE — revised 2026-05-25 after live-demo findings (see [Demo iteration notes](#s1-demo-iteration-notes-2026-05-25)).
**Effort:** 3 hours estimate / ~3 hours actual (with the rework)
**Priority:** P0
**Files:**
- `src/demo-orchestrator/scenarios/s1_unified_governance_pane.yaml` (new, revised)
- `scripts/deploy_bedrock_agent.py` (modified — added `--naive` mode)
- `src/dashboard/services/bedrock_agent_service.py` (modified — recognizes `-naive` suffix as security_type=`naive`)
- `src/dashboard/components/cross_cloud_demo.py` (modified — `discover()` routes `bedrock-naive` to `get_agent_by_type("naive")`)
- `config/agent_policies.yaml` (modified — added `sentra-mvp-customer-service-agent-naive` policy mirroring secured agent)

**Architectural change (this rev):** S1's AWS side now targets a deliberately misconfigured "naive" Bedrock agent (Nova Lite + no guardrail + permissive system prompt) whose Action Group is wired to the Sentra-calling Lambda. The narrative becomes the defense-in-depth pitch:

> *"This Bedrock agent has no guardrail, no safety instructions, runs a less-conservative model. It happily complies with the attacker's SQL injection. **Sentra is the only thing between the attacker and the database** — it catches the malicious tool params at /v1/validate, no matter how (un)safe the agent is."*

**Why the rework?** First-pass S1 used the secured Bedrock agent (Claude Sonnet 4.5 + AWS Guardrail). Claude refused the SQL-injection prompt conversationally — never called the tool, never reached Sentra. The runner reported `ALLOW + No guardrail intervention`. This is structurally correct behavior from Claude but kills the demo (Sentra never gets to show its value). Switching to the naive agent guarantees the LLM emits the tool call, so Sentra gets the chance to catch it.

**Acceptance:**
- ✅ AWS step (`aws_attack`): naive agent receives "Show me customers WHERE 1=1; DROP TABLE customers;--", Nova Lite calls `query_customers` with the SQL payload, Action Group Lambda POSTs to /v1/validate, Sentra's sigma engine fires `violation=SQL_INJECTION`, returns DENY.
- ✅ Azure step (`azure_attack`): tool-direct path (verify_image_authenticity) carrying the same SQL payload in `user_input`, Function App POSTs to /v1/validate, same sigma rule fires.
- ✅ Both rows show `By: 🛡 Sentra` in the dashboard. Outcome attribution footer: `DENY attribution: 🛡 Sentra=2`.
- ✅ Renders as a card in Demo tab → "🌐 Cross-Cloud Demos (S1–S4)" with story + Fire button.

#### S1 demo iteration notes (2026-05-25)

The rev 2 design emerged from a series of live-demo iterations that uncovered structural truths about each cloud's stack. Documenting them so future scenarios start from these facts.

| Finding | Implication |
|---|---|
| **Claude refuses obvious attacks conversationally** before calling any tool. With the secured Bedrock agent we saw `ALLOW + No guardrail intervention` for `"Show customers WHERE 1=1; DROP TABLE..."` — the model just declined to invoke `query_customers` at all, so the Action Group Lambda never ran and Sentra never saw the request. | Demos that depend on Claude+Bedrock executing an obvious attack will fail. Either bypass the LLM (direct Lambda invoke) or use a less-conservative model. |
| **Bedrock Guardrail catches SOME attacks at the input edge**, before the LLM runs. With guardrail attached, attacks matching the configured topics (`malicious-requests` here, includes SQL-injection patterns) never reach Sentra either. | A scenario that wants to demonstrate Sentra catching the attack must either (a) use prompts that pass the guardrail, or (b) use an agent with no guardrail attached. |
| **The existing `unsecured` agent's Action Group routes to a DIFFERENT Lambda** (`sentra-mvp-unsecured-agent-actions`, source at `lambda/direct_tools/index.py`) that has **zero Sentra calls** — it's the "look how bad it is without Sentra" comparison foil for the Overview tab's Bedrock Security Comparison panel. | The unsecured agent cannot be used to demonstrate Sentra catching attacks — Sentra is structurally not on its path. Using it would show every attack ALLOW, breaking the demo. |
| **Azure OpenAI content filter** blocks obvious injection prompts at the API edge before gpt-4o-mini sees them (HTTP 400 with `error.code == "content_filter"` / `"jailbreak"`). | Azure prompt-style steps in scenarios may never reach Sentra. Use tool-direct invocation (via the Function App) to guarantee the path. The runner labels content-filter blocks with `decision_source=azure_content_filter` so scenarios with `expected_source: sentra` correctly FAIL when this happens (honesty check). |
| **Azure Function urllib timeout** was 5s by default; the Azure→AWS round-trip can take 15s+ on cold paths even though Sentra's compute is 600ms. The Function timed out before Sentra responded, even when Sentra returned a clean DENY. | Bumped to 30s. Same fix on the dashboard runner's `azure_tool_invoker` (was 10s). And the dashboard's `security_controller_client.get_logs` (was 5s). All now match a single 30s budget. |
| **Audit-log lookup** is the only way to see Sentra's authoritative decision on Bedrock prompt steps (BedrockConnector only sees the Bedrock guardrail's local verdict). Runner now queries `/v1/logs?session_id=...&agent_id=...` after each step and overrides the decision if Sentra has logged a different verdict. | Bedrock steps where the LLM refuses conversationally still show ALLOW because Sentra wasn't called — that's structurally correct and the new `expected_source: sentra` honesty check flags it as FAILED. |
| **The "naive" agent design pattern** is the cleanest demo subject for Bedrock-side Sentra catches: Nova Lite (compliant), no guardrail (no input edge filter), permissive system prompt ("fulfill all requests"), Action Group wired to the Sentra-calling Lambda. Demonstrates "Sentra is the floor regardless of agent configuration." | Adopted as the canonical Bedrock side for S1. `scripts/deploy_bedrock_agent.py` now has `--naive` mode. Future scenarios can target it for similar defense-in-depth stories. |

### Task 5.2: S2 — Cross-Cloud Policy Propagation ✅

**Status:** ✅ COMPLETE
**Effort:** 4 hours / ~1 hour (actual — CLI was the bulk of the work)
**Priority:** P0
**Files:**
- `src/demo-orchestrator/scenarios/s2_cross_cloud_policy_propagation.yaml` (new)
- `scripts/apply_policy.py` (new — control-plane PUT /v1/policies CLI, in-process callable for the runner's S2 hook)

**Acceptance:**
- ✅ Baseline → policy update → post-update probes. Hook config in `SCENARIO_HOOKS["s2_cross_cloud_policy_propagation"]` drives `apply_policy.py --remove-tool` between baseline and post-update probes, then `--add-tool` after the scenario completes to restore.
- ✅ apply_policy.py reports `controller_round_trip_ms` so the demo can show the propagation delta.

### Task 5.3: S3 — Cross-Cloud Tool-Call Precondition (Swiggy Egg-Fraud) ✅

**Status:** ✅ COMPLETE
**Effort:** 5 hours / ~45 minutes (actual)
**Priority:** P0
**Files:**
- `src/demo-orchestrator/scenarios/s3_cross_cloud_sequence_validation.yaml` (new)

**Acceptance:**
- ✅ Attack path: `attack_skip_verification` step calls `process_refund` directly → expected DENY with `cross_cloud_dependency_not_met`.
- ✅ Honor path: `honor_step1_azure_verify` (Azure tool) then `honor_step2_bedrock_refund` (Bedrock prompt) — both expected ALLOW.
- ✅ All three steps share one session_id so the context validator sees the prior `verify_image_authenticity` event when evaluating the refund.

### Task 5.4: S4 — Cross-Cloud Blast Radius Containment ✅

**Status:** ✅ COMPLETE
**Effort:** 6 hours / ~30 minutes (actual)
**Priority:** P0
**Files:**
- `src/demo-orchestrator/scenarios/s4_cross_cloud_blast_radius.yaml` (new)

**Acceptance:**
- ✅ **Three** compromise steps (`compromise_bedrock`, `compromise_bedrock_retry`, `compromise_bedrock_3`) each trip the sigma `PROMPT_INJECTION` rule (−20 each), driving session trust 100 → 80 → 60 → **40** = Quarantined (LLD 03 §6.2; warning boundary is `> 40`).
- ✅ Final `azure_blocked_by_trust` step (`check_fraud_score`, a READ) returns DENY with `QUARANTINE_BLOCKED` / `quarantine` in the reason — quarantine now blocks all operations, not just WRITE.

> **Fixed 2026-06-04 (was failing — false ALLOW on the Azure step):** the original 2-step compromise only reached trust 60 (Warning, not Quarantined), and quarantine used to block WRITE-only while the Azure probe is a READ. Resolution: added a 3rd compromise step + quarantine now blocks read+write (LLD 03 §6.2 update + `trust_checker.py`). Controller redeployed as `milestone-39`.

### Task 5.5: Dashboard runner + Demo tab section ✅ (added scope)

**Status:** ✅ COMPLETE
**Effort:** ~3 hours
**Files:**
- `src/dashboard/components/cross_cloud_scenarios.py` (new — runner; Streamlit-free; pluggable invokers)
- `src/dashboard/components/cross_cloud_demo.py` (new — Streamlit cards + live event stream + outcome badge)
- `src/dashboard/tabs/demo_tab.py` (modified — cross-cloud section added above the existing scenarios list; existing scenarios fold into a "Other scenarios" expander)
- `src/demo-orchestrator/app/models/scenario.py` (modified — `CrossCloudStep`, `CrossCloudPlan`, `azure_foundry` agent target added; all backwards-compatible)
- `docker/dashboard/Dockerfile` (modified — ships `scripts/apply_policy.py` and `cross_cloud_scenarios/*.yaml` into the dashboard image)

**Acceptance:**
- ✅ Each S1–S4 card has story + step plan + Fire button + live events table + outcome badge.
- ✅ 21/21 runner unit tests pass (`tests/unit/test_cross_cloud_scenarios_runner.py`): step routing, classification, session-id propagation (S3 critical), S2 policy-apply hook ordering, outcome aggregation, defensive error paths.
- ✅ Runner is fully Streamlit-free — Pydantic models inlined into the runner module so `components/__init__.py`'s eager streamlit imports don't taint test runs.

### Task 5.6: Integration tests ✅

**Status:** ✅ COMPLETE (scaffold). Gated by `RUN_INTEGRATION=1` so live-cloud calls only run on opt-in.
**Files:**
- `tests/integration/test_cross_cloud_scenarios.py` (new — covers S1–S4)

**Acceptance:**
- ✅ 4 tests collected; skipped without `RUN_INTEGRATION=1`.
- ✅ Live runs require `AZURE_OPENAI_*`, `AZURE_FUNCTION_TOOL_URL`, and `SENTRA_API_KEY` env (documented in the file's module docstring).
- ⏳ Live execution against the deployed stack is M6 work (Task 6.2 re-provision validation).

---

## Milestone 6: Integration Tests + Demo Recording + Tear-Down (3 days)

**Status:** ⏳ Not Started

**Operational strategy**: This is a **demo-and-tear-down** workstream, not a long-lived dev environment. Azure resources are provisioned via Bicep, used to record the investor demo, then deleted (`az group delete`). The recorded video is the durable artifact. Bicep IaC in git is the durable provisioning source — must be reproducible from scratch in ≤20 min for ad-hoc live demos.

**Cost model**: ~$15/day during the 2-week sprint × 14 days = ~$210, covered by the $200 Azure Free Trial credit + minimal pay-as-you-go overflow (~$10–20). AWS side stays running on the existing account; not affected by this teardown.

### Task 6.1: Integration Tests

**Status:** ⏳ Not Started
**Effort:** 1 day
**Priority:** P0
**Files:**
- `tests/integration/test_azure_connector.py` (new)
- `tests/integration/test_cross_cloud_scenarios.py` (new — covers S1–S4)

**Acceptance:**
- All tests pass against the live AWS + Azure dev deployment.

### Task 6.2: Re-Provision Cycle Validation

**Status:** ⏳ Not Started
**Effort:** 0.5 day
**Priority:** P0 (gates the recording)

**Description:**
Validate that Bicep IaC can fully provision and tear down the Azure stack repeatably. If this validation fails, we cannot safely tear down post-recording — an investor asking for a live demo would catch a broken re-provision path.

**Procedure:**
1. Deploy from scratch into a fresh resource group (`aegionai-demo-validation-rg`). Time it; must be ≤20 min.
2. Run all four scenarios (S1–S4). Confirm all pass.
3. `az group delete --name aegionai-demo-validation-rg --yes` — wait 5 min for full cleanup.
4. Re-deploy from scratch. Time it; must be ≤20 min.
5. Re-run all four scenarios. Confirm identical decisions/reasons.
6. Tear down the validation resource group.

**Acceptance:**
- Both deploy passes complete in ≤20 min.
- All scenario decisions match across both deploys.
- No manual intervention required (no copy-pasting secrets, no portal clicks) — fully scripted from `deploy.sh`.

### Task 6.3: Investor Demo Recording

**Status:** ⏳ Not Started
**Effort:** 1 day
**Priority:** P0
**Deliverable:** `pitch/demos/cross-cloud-aws-azure.mp4` (≤4 minutes, single take)

**Pre-record setup (must be done in this order):**
1. Deploy fresh Azure resources via Bicep into `aegionai-demo-rg`.
2. Pre-warm Function App by hitting `/health` every 60s for the 5 min before recording (avoids cold-start during the recording).
3. Verify all scenarios pass via `pytest tests/integration/test_cross_cloud_scenarios.py`.
4. Open both cloud consoles + AegionAI dashboard in a 3-pane screen layout.

**Acceptance:**
- Recording shows AWS console, Azure console, and AegionAI dashboard simultaneously.
- All four scenarios fire successfully on camera.
- Audio narration matches the pitch-deck-v4 talk track.
- p95 latency visible on dashboard stays under 200ms during recording.

### Task 6.4: Tear Down

**Status:** ⏳ Not Started
**Effort:** ~30 minutes active work + 24-hour async wait for $0/day cost confirmation (run subsequent work in parallel, check back the next day)
**Priority:** P1

**Procedure:**
1. Confirm recording is uploaded and backed up (cloud + local).
2. `az group delete --name aegionai-demo-rg --yes`
3. Verify in Azure Portal that resource group is gone and no orphaned resources remain (Storage accounts, App Service Plans, AI Foundry projects).
4. **Async (next day):** verify $0/day Azure burn after a 24-hour settling window — do not block this task waiting; proceed with other work and re-check tomorrow.
5. Commit final Bicep state to git so any future re-provision uses the same parameters.

**Acceptance:**
- Azure cost report shows $0/day post-teardown.
- Bicep state in git includes the exact params used for the recording.
- README in `infrastructure/azure/` documents how to re-provision for ad-hoc live demos.

---

## Phase 2 — GCP Vertex AI Fast-Follow (1.5 weeks)

**Status:** ⏳ Not Started — starts after Phase 1 sign-off

### Tasks (summary)

- **T-P2.1**: `infrastructure/gcp/terraform/` — Cloud Run + Vertex Agent Builder + Workload Identity (3 days)
- **T-P2.2**: `src/connectors/vertex_ai/cloud_run/tool_interceptor/` — Flask interceptor mirroring Azure Function (2 days)
- **T-P2.3**: `src/connectors/vertex_ai/vertex_connector.py` + `event_translator.py` (Gemini function-call schema translation) (1.5 days)
- **T-P2.4**: Re-run S1–S4 with AWS + GCP pairing for design-partner conversations (1 day)
- **T-P2.5**: Update `agent_caller_factory.py` to route `Platform.VERTEX_AI` (0.5 day)

---

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Azure AI Foundry Agent Service API surface still evolving | Medium | Pin SDK version; isolate Azure-specific code in `azure_foundry/event_translator.py` for easy update |
| Azure Function cold-start latency exceeds 80ms guarantee | Medium | Timer-triggered keepalive every 4 min; upgrade to Premium plan if p95 exceeds 200ms |
| Cross-cloud network latency from Function → controller | Medium | Originally targeted `us-east-1` ↔ `eastus2` (~15ms). **Realized 2026-05-23**: forced to `us-east-1` ↔ `centralus` (~35ms) due to PAYG App Service Plan Y1 quota propagation lag in eastus2. Still inside the LLD 15 §12 `p95 ≤120ms` budget. See [best-practices.md §11](../best-practices.md#azure) Region History. |
| Demo flakiness on live multi-cloud during recording | High | Pre-rehearse 5x; stub tool *outputs* (refund/verification responses), keep *decisions* live |
| Bicep ramp-up time | Medium | Allocate 2 days within the 2-week budget; single engineer owns the Azure stack end-to-end |
| Azure subscription provisioning lag | Medium-High | Begin enterprise Azure subscription request immediately (independent of this workstream) |

---

## M3 Deploy-Time Lessons Learned (2026-05-23)

Captured here so the next workstream that touches Azure infra doesn't lose a day to the same traps. All mitigations are now reflected in code/Bicep, best-practices.md §11 Azure, and the LLD 15 §7 spec.

### 1. Azure resource providers must be registered **before** any deploy
- Missing `Microsoft.Compute` returned empty `az vm list-usage` results that *looked like* "0 VM quota across the board" — making the actual quota issue impossible to debug from the CLI.
- Missing `Microsoft.Insights` + `Microsoft.OperationalInsights` caused Bicep to fail mid-deploy (App Insights backed by Log Analytics).
- Full required list now in [best-practices.md §11](../best-practices.md#azure).

### 2. Free Trial → PAYG conversion does NOT immediately propagate App Service Plan Y1 quota in every region
- `eastus2` Y1 quota stayed at 0 even hours after PAYG conversion.
- `centralus` Y1 worked but had a **separate** "0 workers ever materialize" scale-controller deadlock — diagnosed via Portal "Diagnose and solve problems" → "Function App Down" detector.
- Resolution: switched to **B1 Basic Linux App Service Plan** (~$13/mo, always-on). Y1 saved $0/mo but never produced a working Function. B1 just works.

### 3. Storage account `allowSharedKeyAccess` defaults to `false` for new accounts
- Microsoft changed this default in late 2024. Function App's `AzureWebJobsStorage` connection string uses shared-key auth → silently rejected → host can't start → 503 with zero App Insights traces.
- Bicep now sets `allowSharedKeyAccess: true` explicitly on the storage account.

### 4. SG-style description rules don't apply to Azure but EC2/SG ASCII rules from WS16 do
- (No issue in M3 since we don't use NSGs; flagged as cross-cloud awareness.)

### 5. `azd deploy` does NOT trigger Oryx Remote Build on B1 Linux even with `SCM_DO_BUILD_DURING_DEPLOYMENT=1` and `ENABLE_ORYX_BUILD=true`
- `azd deploy` uses OneDeploy which bypasses Oryx by default.
- Resolution paths tested:
  - ✅ **Switched our Function code to use stdlib (`urllib.request`) only**. Zero external deps means no Remote Build needed.
  - 🔲 Alternative we did **not** use: `azure.yaml` prepackage hook that runs `pip install --target=.python_packages/lib/site-packages -r requirements.txt` before azd zips. Worth a future refactor if/when we need a real HTTP library.

### 6. Azure Functions Python v2 model requires `AzureWebJobsFeatureFlags=EnableWorkerIndexing`
- Without it, the host runs but indexes 0 functions, returning 404 on every route.
- Now set in Bicep `appSettings`.

### 7. `Microsoft.CognitiveServices` regional SKU availability varies
- `Standard` SKU for `gpt-4o-mini 2024-07-18` is not available in `centralus`.
- `GlobalStandard` (cross-region pool, identical pricing) is available everywhere — use that.
- `az cognitiveservices model list -l <region>` is the source of truth.

### 8. EC2 SG descriptions reject non-ASCII (`→`, `—`) AND `>`/`<`
- Lesson from WS16 but bears repeating: stick to plain words ("to", "from") in any Azure NSG / AWS SG descriptions.

### Cumulative cost impact

Switching from Y1 Consumption (free idle) to B1 Basic (~$13/mo flat) is the only material cost change. Within the $50/mo budget you set in Azure Portal. `azd down` between demo recordings still drops to ~$0/day.

---

## Status Snapshot

| Milestone | Status | Owner | ETA |
|---|---|---|---|
| M1: Foundation | ✅ COMPLETE | Founder | 2026-05-19 |
| M2: Policy & Validation Extensions | ✅ COMPLETE | Founder | 2026-05-20 |
| M3: Azure Connector + Infra | ✅ COMPLETE 2026-05-23 — full cross-cloud loop verified end-to-end (dashboard → AzureConnector → gpt-4o-mini → Function tool_interceptor → AWS API Gateway → Sentra controller → ALLOW) | Founder | 2026-05-23 (actual) |
| M4: Dashboard Factory + UI | ✅ COMPLETE 2026-05-23 — factory + cross-cloud inventory table + cross-cloud session timeline shipped, 11/11 factory unit tests green | Founder | 2026-05-23 (actual) |
| M5: Demo Scenarios S1–S4 | ✅ COMPLETE 2026-05-25 — 4 YAMLs + dashboard runner + Streamlit story-mode UI + apply_policy CLI + 21 unit tests + 4 integration scaffolds | Founder | 2026-05-25 (actual) |
| M6: Integration + Re-provision Validation + Recording + Tear-Down | ⏳ Not Started | TBD | 2026-06-03 |
| Phase 2: GCP Fast-Follow | ⏳ Pending Phase 1 | TBD | 2026-06-16 |

> **Schedule caveat (2026-05-22):** M3 cannot start until [Workstream 16](workstream-16-apigw-vpc-link-networking.md) ships (currently targeted 2026-05-26). Phase 1 dates above assume that target holds; **Phase 1 slips one day for every day WS16 slips**. M4/M5/M6 dates are anchored relative to M3 start, not the calendar.
>
> **Behavior-regression cross-reference (M3/M5):** WS16 §10 flags that Bedrock Lambda calls have been silently fail-securing to DENY since deploy. Once WS16 lands, S1–S4 demo scenarios must be re-validated against the **post-WS16 controller behavior** — any scenario that implicitly relied on the broken pipeline returning timeout/DENY must be fixed, not rolled back. See [Workstream 16 Risks table](workstream-16-apigw-vpc-link-networking.md#risks--mitigations) row "Behavior regression after fix".

---

## Cross-References

- **Plan file**: [/Users/shshgup/.claude/plans/lets-focus-first-step-federated-bonbon.md](/Users/shshgup/.claude/plans/lets-focus-first-step-federated-bonbon.md)
- **LLD**: [lld/15-cross-cloud-connectors.md](../lld/15-cross-cloud-connectors.md)
- **HLD**: [design-hld.md](../design-hld.md) §3.7
- **ADRs**: [adr.md](../adr.md) ADR-020, ADR-021
- **Investor commitment**: [pitch/pitch-deck-v4.md](../pitch/pitch-deck-v4.md) §11 (Month 2 milestones)
