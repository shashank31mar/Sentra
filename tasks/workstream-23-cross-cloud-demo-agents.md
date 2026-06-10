# Workstream 23: Cross-Cloud Demo Agents (AWS + Azure) + Aegion Guard SDK

**Status:** ✅ **DEPLOYED LIVE (2026-06-09)** — all 3 agents deployed across AWS + Azure, registered, policied, and producing **continuous cross-cloud decisions in the console** (EventBridge every 3 min). All scenarios verified end-to-end through real deployed compute. See **Live Deployment** below.
**Owner:** Founder
**Start Date:** 2026-06-08
**LLD References:** [lld/22-cross-cloud-demo-agents.md](../lld/22-cross-cloud-demo-agents.md) (agents), [lld/23-sentra-guard-sdk.md](../lld/23-sentra-guard-sdk.md) (SDK)
**Depends on:** WS-15 (cross-cloud connector pattern, proven), WS-16 (API GW `/v1/*` public), WS-21/22 (console live at `console.aegionai.ai`)

---

## Overview

Stand up *business-realistic* AI agents on two clouds, integrate them with the AegionAI security
controller via a **published client SDK (`aegion-guard`)**, drive **real open-source data** through
them on a **continuous schedule**, and watch ALLOW/DENY decisions flow end-to-end into the SOC
console. The point is to **discover and document the customer integration touchpoints firsthand**.

**Two parallel tracks** (LLD 23 §10 — the SDK depends only on the `/v1/validate` contract, not on the
agents):
- **Track 1 — `aegion-guard` SDK** (product artifact, PyPI). Built/tested against a mock validate endpoint.
- **Track 2 — demo agents** (AWS payments, Azure identity, Azure telecom). Consume the SDK like a real customer.

They meet at **M4** (registration + first end-to-end validation), which needs the SDK + ≥1 registered agent.

### Locked decisions (from LLD 22/23 review)
1. **3 agents:** `acme-payments-agent` (AWS Bedrock), `acme-identity-agent` + `acme-telecom-agent` (Azure OpenAI).
2. **2 cross-cloud scenarios:** A (finance+identity, positive precondition, reuses core); B1 (finance+telecom SIM-swap, positive precondition). B2 (block-transfer-after-SIM-swap, negative precondition) **deferred** — needs a small core `context_validator` extension.
3. **Input/tool-call validation only** — output/DLP deferred (`/v1/validate` is input-only).
4. **Permissive agents** — AWS Nova Lite + **no guardrail** + permissive prompt; Azure gpt-4o-mini + content filter dialed down (WS-15 lesson: strong models/guardrails block before Sentra sees the attack).
5. **SDK = `aegion-guard`** (import `aegion_guard`, class `AegionGuard`), standalone PyPI package, **not** under `demo-agents/`. Sync+async, fail-secure, stdlib-only HTTP.
6. **Separation:** all demo code under top-level `demo-agents/`; **no edits to `src/`, `lambda/`, `cdk/`, core `scripts/`, or `config/agent_policies.yaml`.**
7. **Customer self-registration deferred** — no `POST /v1/agents` yet; `seed_demo.py` writes the registry DDB directly (fast-follow API unlocks it).

### Open items to verify at build
- **`/v1/metrics/overview` metrics** — **resolved (G7):** `publish_validation_metrics` IS called in the validation path (`validation_service.py:341/435`, WS-21 T01 landed), so metrics are emitted. LLD 21 §10.2b's "never invoked" note is stale. No action; Overview KPIs populate as traffic flows.
- **AWS creds:** `ada cred update --profile sentra` before Bedrock/DDB work.
- **Azure re-provision:** `azd up` per-agent infra; ~$13–15/mo if kept live for demos.

### Success Criteria
- [ ] `aegion-guard` published (PyPI or internal index), ≥80% test coverage, sync+async, fail-secure verified against a mock.
- [ ] 3 agents registered with correct `platform` + `cloud_provider` → console Clouds KPI = 2.
- [ ] Scenario A: refund without prior Azure `verify_identity` (same session) → DENY; with it → ALLOW.
- [ ] Scenario B1: unauthenticated `reset_sim`/`port_out_number` → DENY.
- [ ] Injection prompt (Lakera/garak) → sigma DENY; refund > $5000 (hardcoded engine default, not policy-configurable) → DENY.
- [ ] Continuous traffic shows a steady ALLOW/DENY mix across aws+azure in the console.
- [ ] `RUN_INTEGRATION=1 pytest demo-agents/tests/` green.

---

## Live Deployment (2026-06-09)

Everything is deployed to the live AWS (`531109575379`) + Azure (`cb2512df-…`) accounts and verified
end-to-end through real compute. The console shows all 3 agents, **Clouds KPI = 2**, and a continuous
ALLOW/DENY stream.

| Component | Live resource | Verified |
|---|---|---|
| AWS Payments agent | Bedrock agent `JGECQEHF9N` / alias `Y4AE29ARBL` (Nova Lite, no guardrail) + Lambda `acme-payments-agent-tools` + DDB `acme-bank-accounts`/`-transactions` (200 acct / 1568 txn) | native `InvokeAgent` works; **$9000 refund spoken by model but BLOCKED by Sentra — balance unchanged $674.02** |
| Azure Identity agent | Function `acme-identity-func` (rg `rg-acme-identity-demo`, B1, centralus) | `verify_identity` → ALLOW via live Sentra |
| Azure Telecom agent | Function `acme-telecom-func` (rg `rg-acme-telecom-demo`, B1, centralus) | `lookup_subscriber` ALLOW; SIM-swap DENY/ALLOW (B1) |
| Registration + policies | `seed_demo.py` → `sentra-agent-registry` + S3/`sentra-policies-metadata` (direct write) | 3 agents in `/v1/agents`, policies enforce |
| Traffic generator | Lambda `acme-demo-traffic` + EventBridge `acme-demo-traffic-schedule` (`rate(3 minutes)`) | batch = 7 ALLOW / 4 DENY / 0 error / 0 mismatch |

**Cross-cloud proven through real compute:** Azure identity Function `verify_identity` → then AWS
Lambda `process_refund` in the same session → **ALLOW** (refund executed); without the verify → **DENY
`cross_cloud_dependency_not_met`**. Same for telecom SIM-swap (Scenario B1).

### Deploy-time findings (worked around; some are upstream bugs to file)
1. **`POST /v1/policies` was broken — ✅ FIXED (controller milestone-44, 2026-06-09).** The route validated `request.dict(exclude_none=True)` (a `PolicyCreateRequest`, lacking `policy_id/status/created_at/created_by`) against `AgentPolicyDocument` (which requires them); the service generated those *after* validation, **and** it used a hardcoded nonexistent S3 bucket (`sentra-mvp-artifacts`). Fixed in `policy_service.create_policy`: enrich the envelope fields **before** validation + use `settings.s3_bucket`. Verified: `POST /v1/policies` now returns 201. (`seed_demo.py` still writes directly, which also works; it can switch to the API now.)
2. **`/v1/decisions` (Live Activity) returned nothing — ✅ FIXED (milestone-44).** `decisions_service.scan_decisions` did a DynamoDB **`Scan` with `Limit` applied before the timestamp `FilterExpression`**, so on a multi-date table it read the first N (old) rows and filtered to ~0 — Live Activity looked empty despite hundreds of signals/day. Fixed: `decision_date` is the GSI partition key, so **Query each day in the window** newest-first. Verified: `/v1/decisions` now returns the live ALLOW/DENY stream.
3. **`/v1/decisions` rows didn't match the console's `DecisionItem` — ✅ FIXED (milestone-45).** The endpoint returned a nested `combined`/`signals` shape, but the SOC console's Threat Explorer / approved-queries views render flat fields (`agent_id, cloud_provider, decision, threat_type, tool_name, trust_score, timestamp`) — so every column was blank once rows appeared. Fixed: `scan_decisions` now emits the flat `DecisionItem` fields per row (derived from the signal items + `resolve_cloud_provider`), keeping `combined`/`signals` for drill-down back-compat. The metrics KPIs (`/v1/metrics/overview`) were already publishing correctly (`threats_blocked`, `trust_score`, `clouds`, `active_agents`) — one gap: `requests_total=0` (the `ValidationsTotal` counter isn't emitted; minor).

### Console-completeness fixes + cross-cloud scenarios (2026-06-09, second pass)
- **Agent↔policy attachment** — the attach API (`POST /v1/agents/{id}/policies`) existed but the demo agents were never attached. `seed_demo.py` now **attaches each policy** → Agent Detail shows `attached_policy_ids`.
- **Tools per agent** — `/v1/agents/{id}/tools` reads `policy.allowed_tools` then enriches against `sentra-tool-registry` and **drops unregistered tools**; the demo tools weren't registered. `seed_demo.py --tools-only` now **registers all 10 demo tools** → Agent Detail shows full tool lists.
- **Live Activity skew** — payments dominated (most tool steps) + my eval flooded it. Rebalanced `traffic/generator.py` with standalone identity/telecom sequences → `/v1/decisions` now ~balanced across all 3 agents.
- **`/v1/decisions` `agent_id` filter — ✅ FIXED (milestone-46).** Filter-after-`Limit` meant per-agent filtering returned ~0 for the Azure agents; now **paginates within each day** until enough filtered rows. Verified per-agent counts non-zero.
- **Cross-cloud scenarios (`demo-agents/scenarios/run_scenarios.py`):**
  - **S2 — policy propagation:** remove a tool from the telecom policy via `PUT /v1/policies` → the **Azure** `change_plan` call is DENIED within **~5s** ("not authorized") → restore. A control-plane change governing the Azure agent across clouds in seconds.
  - **S4 — blast-radius/quarantine:** 3 injections drive session trust 100→80→60→40 → **QUARANTINED** → a subsequent benign `lookup_account` in that session is **DENIED** ("blocked while quarantined"). Compromised-session containment.

### Real data + measurement (deepset/prompt-injections)
- **`demo-agents/eval/fetch_dataset.py`** pulls the real **`deepset/prompt-injections`** corpus (662 labeled prompts) from HuggingFace → the traffic loop's attack corpus is now **263 real injection prompts** (subtle/role-play/multilingual, not hand-written), and `eval/labeled_prompts.jsonl` is the ground truth.
- **`demo-agents/eval/measure.py`** runs the labeled set through `/v1/validate` → confusion matrix + precision/recall/F1/F2 + latency. **First result (n=100): precision 1.00, recall 0.52, F1 0.68, accuracy 0.76, p95 ~4.5s.** Perfect precision (no false-positives), but it misses ~half the *subtle* injections — the actionable gap (pattern-based sigma catches the obvious ones; the subtle ones need the ML classifier or broader rules). p95 ~4.5s is the full-pipeline (incl. ML) latency.
2. **SDK live contract test was unrunnable** — the unit-test `conftest` autouse fixture clobbered `SENTRA_API_BASE` with a dummy host for *every* test incl. the live one. **Fixed:** skip the override when `RUN_INTEGRATION=1`. The SDK now passes against the real `/v1/validate`.
3. **azd: Function App needs `tags: { 'azd-service-name': <svc> }`** in bicep, and a **`functionapp restart` after `azd deploy`** before the v2 host indexes routes (else 404). Both baked into the bicep / documented.
4. **Traffic Lambda must not use a named AWS profile** — `boto3.Session(profile_name='sentra')` fails inside Lambda. **Fixed:** default credential chain (role in Lambda, `AWS_PROFILE` locally).

### Cost & teardown
- Ongoing: 2× Azure B1 plans (~$26/mo) + Bedrock/validate per traffic tick (small). **Pause traffic:** `aws events disable-rule --name acme-demo-traffic-schedule --profile sentra`.
- **Azure teardown:** `azd down` in each agent dir (or `az group delete -n rg-acme-identity-demo`/`rg-acme-telecom-demo`).
- **AWS teardown:** delete Bedrock agent `JGECQEHF9N`, Lambdas `acme-payments-agent-tools`/`acme-demo-traffic`, the EventBridge rule, IAM roles `acme-*`, and DDB `acme-bank-*` (RemovalPolicy not set — manual).

---

## Build Status (2026-06-08)

All code is built under `demo-agents/` and **runs/tests offline** (no cloud). The only thing left is
deploying to live AWS/Azure (needs `ada cred update` + `azd up`) and running the gated live tests.

| Milestone | Built | Where | Verified offline |
|---|---|---|---|
| M1 — `aegion-guard` SDK | ✅ | `demo-agents/sdk/aegion-guard-python/` | 75 pass, 92% cov |
| M1.5 — data layer | ✅ | `common/{datagen,store,ddb_admin}.py` + per-agent `data/` loaders | datagen+store tests pass |
| M2 — AWS Payments agent | ✅ | `aws-payments-agent/{tools,agent_spec,deploy}/` (Nova Lite, **no guardrail**) | handler ALLOW/DENY/unknown + zip packaging |
| M3 — Azure Identity agent | ✅ | `azure-identity-agent/{tools,agent_spec,infra}/` (gpt-4o-mini, async) | async dispatch ALLOW/DENY |
| M5 — Azure Telecom agent | ✅ | `azure-telecom-agent/{tools,agent_spec,infra}/` (Scenario B1) | SIM-swap precondition |
| M4 — Registration + policies | ✅ | `registration/{agents.demo.yaml,policies.demo.yaml,seed_demo.py}` (full envelope; **no rule-string limits**, §6.5) | seed dry-run |
| M6 — Traffic generator | ✅ | `traffic/{generator,lambda_handler,deploy_traffic}.py` + `attack_prompts/` | dry plan |
| M7 — Tests + local demo | ✅ | `tests/` (9 pass, 3 gated-live) + `run_local_demo.py` | **full offline e2e: 7 ALLOW / 4 DENY, 0 mismatch** |

**`python demo-agents/run_local_demo.py`** drives the whole cross-cloud demo offline against a
`FakeController` (emulates sigma + refund>$5000 + cross-cloud preconditions) — proving Scenario A,
Scenario B1, injection, and the refund limit all enforce correctly before any cloud spend.

**Remaining (live, needs creds):**
1. `ada cred update --profile sentra`; `python aws-payments-agent/data/load_bank_data.py`; `python aws-payments-agent/deploy/deploy_payments_agent.py --create`.
2. `azd up` in `azure-identity-agent/` and `azure-telecom-agent/` (telecom data is synthetic-at-runtime — no loader).
3. `python registration/seed_demo.py` (registers 3 agents → console Clouds KPI = 2; creates policies). Re-running skips existing policies; pass `--force` to update changed ones (PUT).
4. `python traffic/deploy_traffic.py --create` (EventBridge schedule).
5. Run the gated tests: `RUN_INTEGRATION=1 pytest demo-agents/tests/test_integration_live.py` — and the SDK's own contract test (23.7b), now unblocked once an agent is registered.

---

## Milestone 1 — `aegion-guard` SDK (Track 1, parallel) — LLD 23 — ✅ COMPLETE

**Status:** ✅ Built at `demo-agents/sdk/aegion-guard-python/`. 75 tests pass (+2 gated live), **92% coverage** (≥80% target met). `pip install -e` + import verified; README usage examples run.

| Task | Status | Notes |
|---|---|---|
| 23.1 skeleton | ✅ | `pyproject.toml` (stdlib-only runtime), `src/aegion_guard/{__init__,guard,client,context,config,exceptions,adapters,_time}.py`, `__version__`/`__contract__` |
| 23.2 core + explicit validate (G1)/hook (G3)/nested session (G4) | ✅ | `AegionGuard`, `@tool`, `session()`, `validate()`/`avalidate()`; ms-Z timestamp reimplemented; auto op-type |
| 23.3 client + config fail-fast (G2) | ✅ | stdlib urllib, TLS-on, timeout 10s, connect-retry (connection errors only, NOT read-timeout); `ConfigError` at init |
| 23.4 decision parse + fail-secure + hook/contract (G3/G5) | ✅ | default-DENY on unknown; `UnknownAgentError`; `SentraUnavailable`; non-serializable → clear error |
| 23.5 async | ✅ | coroutine detection + `asyncio.to_thread` w/ contextvar copy |
| 23.6 adapters | ✅ | `from_bedrock_event`/`from_azure_request` faithful to real interceptors |
| 23.7 tests (mock) | ✅ | run/block/default-DENY/fail-secure/op-misfires/async/serialization/config-fail-fast/hook/nested/api-key-privacy(G9) |
| 23.7b live contract (G6) | ✅ | `tests/test_contract_live.py`, gated `RUN_INTEGRATION=1` |
| 23.8 package + publish (gated, G8) | ◐ | README done; build/publish to internal index/TestPyPI pending a release decision (public PyPI = explicit product call) |

<details><summary>Original task detail</summary>

**Task 23.1 — Package skeleton.** `aegion-guard-python/` repo-ready dir: `pyproject.toml`, `aegion_guard/{__init__,guard,client,context,config,exceptions,adapters}.py`, semver `__version__` + `__contract__`. stdlib-only runtime deps.
**Task 23.2 — Core: `AegionGuard` + `@guard.tool` + `guard.session()` + explicit `validate()`/`avalidate()`.** contextvars for `session_id`/`user_input`/`request_id`; build `ValidationRequest`; ms-Z timestamp (reimplemented, 3 lines); `auto` op-type (best-effort, explicit-wins). **Includes (G1)** the first-class non-decorator `validate()`/`avalidate()` public methods (LLD 23 §3); **(G3)** the `on_decision` observability hook wired into the call path (LLD 23 §4.1 step 7); **(G4)** nested `session()` = inner-wins via `contextvars.Token` restore-on-exit (LLD 23 §3.3).
**Task 23.3 — `client.py` (stdlib urllib) + `config.py` fail-fast.** POST `/v1/validate`, `x-api-key`, `timeout_s` (default 10), bounded `connect_retries` (**connection-establishment errors only — NOT read-timeouts**, LLD 23 §12.1). TLS verification ON. Defensive JSON. **(G2)** `config.py` resolves env and **raises `ValueError` at init listing missing `api_base`/`api_key`** (fail-fast, not first-call — LLD 23 §7).
**Task 23.4 — Decision parsing + fail-secure + hook/contract handling.** DENY → `ToolDenied`; unknown/missing decision → **default-DENY**; unregistered agent → `UnknownAgentError` (best-effort, §12.1 G3-caveat); transport error → `ToolDenied` (or `SentraUnavailable` if `fail_secure=False`); non-serializable params → clear error. **(G3)** invoke `on_decision(Decision)` and **swallow its exceptions** (never break the tool path). **(G5)** `__contract__` is **informational** — no active version-matching (the controller advertises none); drift handled defensively (additive fields via `raw`, non-ALLOW/DENY bodies fail closed). See LLD 23 §5.
**Task 23.5 — Async support.** `iscoroutinefunction` detection → async wrapper awaiting `avalidate` (blocking client via `asyncio.to_thread`). Verify contextvars across `await`.
**Task 23.6 — Cloud adapters.** `from_bedrock_event`, `from_azure_request`.
**Task 23.7 — Tests (vs mock).** Unit (run/block/default-DENY/fail-secure/op-inference incl. substring misfires/async/serialization), adapter tests, **plus:** explicit `validate()`/`avalidate()` (G1), `config` fail-fast at init (G2), **throwing `on_decision` does not break the tool path** (G3), nested `session()` inner-wins (G4), `__contract__` mismatch warn-and-continue (G5), and **`x-api-key` never appears in `on_decision` payloads or `Decision.raw`** (G9). ≥80% coverage.
**Task 23.7b — SDK contract test (live, gated).** `RUN_INTEGRATION=1` test that POSTs a known-safe and a known-injection payload to the **real `/v1/validate`** using **any already-registered agent**, asserting ALLOW/DENY (LLD 23 §10 / G6). Distinct from the demo Scenario tests (23.23); this exercises the SDK against the real controller so it never ships (23.8) un-validated end to end.
**Task 23.8 — Package + publish (gated).** README (integration guide), build sdist/wheel. **Default distribution = internal index / TestPyPI + `pip install -e`** for the demo; **public PyPI is an explicit product decision (one-way door: name squat, public versioning/security expectations), NOT a build step** (G8).

> **Acceptance:** `pip install -e aegion-guard-python` (or internal index); the §11 usage examples run; all unit tests green without any agent deployed; 23.7b passes when the stack is reachable.

</details>

## Milestone 2 — AWS Payments agent (Track 2) — LLD 22

**Task 23.9 — Bank data backend.** `demo-agents/aws-payments-agent/data/load_bank_data.py`: load **PaySim** (Kaggle `ealaxi/paysim1`) + **Faker** PII into DDB `acme-bank-accounts` / `acme-bank-transactions` (idempotent `--dry-run`/`--force`). Self-contained table creation (not core `storage_stack.py`).
**Task 23.10 — Tools via SDK.** `tools/lambda_handler.py`: `lookup_account` (R), `get_transactions` (R), `process_refund` (W), `transfer_funds` (W), each `@guard.tool`; `from_bedrock_event` + `guard.session(...)`.
**Task 23.11 — Deploy agent (permissive).** `deploy/deploy_payments_agent.py`: Bedrock agent on **Nova Lite, NO guardrail, permissive prompt**, action group → the Lambda, alias.

## Milestone 3 — Azure Identity agent (Track 2) — LLD 22

**Task 23.12 — Fraud-score backend.** `azure-identity-agent/data/fraud_lookup.py` from **IEEE-CIS Fraud** (Kaggle `ieee-fraud-detection`), rule-based/deterministic score.
**Task 23.13 — Tools via SDK.** `tools/function_app.py`: `verify_identity` (R), `check_fraud_score` (R), each `@guard.tool` (async); `from_azure_request` + `guard.session(...)`; `timeout_s=30` (cross-cloud cold path).
**Task 23.14 — Deploy (filter down).** Self-contained `azd up` infra; gpt-4o-mini deployment with content filter dialed down; publish the Function.

## Milestone 4 — Registration + Policies + first end-to-end (meets both tracks)

**Task 23.15 — `seed_demo.py`.** `demo-agents/registration/`: registers 3 agents (direct registry DDB write) + creates policies via `POST /v1/policies`. Idempotent. **Honor the LLD 22 v1.3 core-enforcement reality (do NOT re-encode rule-string limits):**
- **Registry items (LLD 22 §10.3):** write the **full `seed_agents.py` envelope** — `agent_id, name, type, platform, cloud_provider, status, security_type, visibility, allowed_tools` **+ `version, description, created_at, created_by, tags, runtime_config`** — or the console renders `None` for those fields.
- **Policies (LLD 22 §10.4):** POST the **full `PolicyCreateRequest`** (`schema_version, name, version` semver, `allowed_tools`, **one inert padding `policies[]` rule** since rules are not engine-evaluated, `cross_cloud_dependencies`, `max_calls_per_minute`). **No rule-string amount limits** — the refund DENY is the **hardcoded $5000 default** (§6.5); `transfer_funds` has no limit. Scenario A/B1 cross-cloud deps are the real enforcement.
- **Idempotency:** `import` skips already-`managed`; re-running is safe.
**Task 23.16 — Scenario A verification.** refund without prior Azure `verify_identity` → DENY `cross_cloud_dependency_not_met`; verify→refund (same session) → ALLOW. Confirm in `/v1/logs` + console Audit Trail.

## Milestone 5 — Azure Telecom agent + Scenario B1 — LLD 22 §6.4

**Task 23.17 — Subscriber data.** **As-built (Kiro #3): synthetic-at-runtime, no DDB table.** `telecom_core.py` derives subscriber profiles deterministically from the msisdn so the Azure package stays stdlib-only and avoids cross-cloud DDB access. The `linked_msisdn` on `acme-bank-accounts` (from `datagen`, IBM-Telco-shaped) keeps the account↔subscriber bridge for the narrative + future Scenario B2. A real `acme-subscribers` table is the B2 fast-follow.
**Task 23.18 — Tools + deploy.** `lookup_subscriber` (R), `change_plan` (W), `reset_sim` (W), `port_out_number` (W) via SDK; `azd` deploy. Register + policy with **B1 cross_cloud_dependency** (`reset_sim`/`port_out_number` require `verify_identity`).
**Task 23.19 — Scenario B1 verification.** unauthenticated SIM-swap/port-out → DENY; identity-verified → ALLOW.

## Milestone 6 — Continuous Traffic Generator — LLD 22 §9

**Task 23.20 — Generator.** `demo-agents/traffic/generator.py`: per tick, pick legit dataset rows → realistic prompts, inject attack prompts from **Lakera Gandalf/PINT, HackAPrompt, garak, JailbreakBench/AdvBench**, fire cross-cloud sequences (verify→refund happy + refund-without-verify attack). Rate-limited under usage plan.
**Task 23.21 — Schedule.** Self-contained EventBridge rule (every 2–5 min) → Lambda under `traffic/infra/`. Pauseable by disabling the rule.

## Milestone 7 — End-to-end verification

**Task 23.22 — Console verification.** Inventory shows all 3 agents (aws+azure, Clouds KPI=2); Decisions/Threats feed shows live mix; Audit Trail traces a cross-cloud session.
**Task 23.23 — Integration tests.** `demo-agents/tests/test_cross_cloud_demo.py` (`RUN_INTEGRATION=1`): Scenario A, B1, injection DENY, over-limit DENY.

---

## Deferred (explicit fast-follows)
- **Scenario B2** — block transfer after a recent SIM-swap (negative cross-cloud precondition = small core `context_validator` extension).
- **Output / DLP validation** — `/v1/validate` output direction + DLP validator (REDACT).
- **`POST /v1/agents`** — customer self-registration API; replaces the demo seeder's direct registry write.
- **`UNKNOWN_AGENT` `error_code` (WS-21 controller follow-up)** — give `/v1/validate` a stable machine code when an `agent_id` isn't registered, so `aegion-guard`'s `UnknownAgentError` maps on a contract instead of best-effort `reason` string-matching (LLD 23 §3.4 / §12.1 caveat 3).
- **TS/Go SDK ports.**

## Risks
| Risk | Likelihood | Mitigation |
|---|---|---|
| Strong model/guardrail blocks attack before Sentra sees it | High (known WS-15 trap) | Nova Lite + no guardrail (AWS); content filter dialed down + tool-direct fallback (Azure); label `decision_source` honestly |
| Azure→AWS cold-path > timeout → false fail-secure DENY | Medium | `timeout_s=30` for cross-cloud interceptors (LLD 23 §7); pre-warm Function for demos |
| Accidental core edit breaks separation | Medium | All demo code under `demo-agents/`; SDK in its own package; review diff before commit |
| Dataset PII committed | Low | Commit only Faker/derived synthetic rows |
| Continuous traffic exceeds usage-plan throttle | Low | Rate-limit generator; tune EventBridge interval |

## Cross-References
- [LLD 22](../lld/22-cross-cloud-demo-agents.md) · [LLD 23](../lld/23-sentra-guard-sdk.md) · [LLD 21](../lld/21-api-inventory-for-ux.md) · [WS-15](workstream-15-cross-cloud-demo.md) · [WS-22](workstream-22-soc-console-frontend.md)
- Plan: `/Users/shshgup/.claude/plans/so-here-is-what-groovy-pelican.md`
