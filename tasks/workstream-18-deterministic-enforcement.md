# Workstream 18: Deterministic Enforcement — Demo Runner + Customer SDK

**Status**: Draft v0.2 — awaiting LLD v0.2 re-review
**Owner**: Founder + 1 backend engineer
**Start Date**: TBD (post-review)
**LLD Reference**: [lld/18-deterministic-enforcement.md](../lld/18-deterministic-enforcement.md) (v0.2)

**Change log since v0.1**:
- M1: synthetic event builder is now schema-aware (P0 fix). Tasks 1.1 + 1.5 grew to absorb the OpenAPI typing logic.
- M1: new Task 1.0 (pre-flight) verifies the deployed Bedrock agent's action_group name matches the hardcoded `customer_tools` default before M1.6 runs live.
- M1: new Task 1.7 — synthetic `bedrock_guardrail` ALLOW emission to satisfy LLD 17 §4 symmetric-emission rule.
- M3: scenario validator gains four new checks — single-action-group constraint, `intent` field required, intent ⇄ invoke-path consistency, OpenAPI-typed param matching.
- M3: new Task 3.6 — delete the legacy `audit_lookup_fn` runner path now that direct-invoke supersedes it (deferred cleanup from WS17).
- M7: Task 7.4 — byte-identical-envelope parity test against the legacy Lambda before we replace it with the SDK-based version. CI gate from 7.3 catches the symbol; the parity test catches behavioral drift.
- M8: re-scoped as "partner-gated, not engineering-gated." Engineering completion of WS18 = M1-M7. M8 tracks separately and may slip on partner availability.
- Effort estimate revised: 30h → **45h** (+50% buffer for cross-region Layer publish, design-partner coordination, parity test scaffolding). 4 days → **~6 days of focused effort**.

---

## Overview

Two intertwined problems, one architectural fix:

1. **Demo scenarios are flaky** because Bedrock LLM-driven invocation is non-deterministic (`probe_bedrock_after` ALLOW vs DENY depends on whether the LLM happens to invoke the tool). Replaced by direct Action Group Lambda invocation — same enforcement path the Azure side already uses.

2. **Customer integration is high-friction** because each Lambda / Function needs ~40 LOC of `validate_with_sentra()` boilerplate, copied with no central version. Replaced by a one-line `@validate` decorator shipped as `sentra-sdk-python` v0.1.

The same pattern serves both: **enforcement decision lives at the tool-execution layer, not at the LLM-tool-selection layer.**

### Why

Concrete evidence from the S2 debugging spiral (2026-05-26 → 2026-05-27):
- 4 attempts to engineer a Bedrock prompt that forced `query_customers` invocation; each failed for a different reason (schema mismatch, Sigma rule false-positive, LLM hallucination).
- Azure side worked from attempt 2 onward because it bypasses the LLM via direct POST to `/api/tool/check_fraud_score`.
- Pattern generalizes: every cross-cloud scenario whose claim is about Sentra's enforcement (not LLM intelligence) will hit this asymmetry.

See [LLD 18 §2](../lld/18-deterministic-enforcement.md#2-why-now--the-s2-debugging-spiral) for the timeline.

### Success Criteria

**Component A (demo runner)**:
- S2 passes deterministically twice in a row (zero flake across 10 consecutive runs)
- S2 total runtime <30 seconds (vs current 60-90s with LLM in the loop)
- Scenario YAML schema validator catches at least 3 typo categories at demo-orchestrator startup (unknown agent, unknown tool, missing required param)

**Component B (customer SDK)**:
- `sentra-sdk-python` v0.1 published to internal PyPI mirror
- Lambda Layer ARN published and reachable in `us-east-1`
- `lambda/bedrock_agent_actions/index.py` and `function_app.py` both use the SDK internally (dogfooding)
- One design partner integrates one tool via the SDK in their staging environment

**Cross-cutting**:
- All 37 test cases (LLD 18 §10) pass
- best-practices.md gains §13 covering SDK integration

---

## Milestone Map

| Milestone | Goal | Effort (v0.2) | Depends on |
|---|---|---|---|
| M1 | Bedrock direct-invoke runner pattern (schema-aware + symmetric emit) | 5h | — |
| M2 | Template substitution for dynamic params | 2h | M1 |
| M3 | Scenario YAML schema validator (+ intent checks, audit_lookup cleanup) | 5h | M1 |
| M4 | SDK core — `@validate` decorator | 6h | — (parallel to M1-M3) |
| M5 | SDK packaging — Lambda Layer + pip (cross-region publish) | 6h | M4 |
| M6 | SDK adoption guide + reference Lambda | 3h | M5 |
| M7 | Dogfood — migrate our own Lambda + Function (+ parity test) | 6h | M5 |
| M8 | Design partner pilot integration (gated on partner) | 4h | M7 |
| **Engineering total (M1–M7)** | | **~33h** | |
| **+ 30% buffer** | cross-region Layer publish, parity-test scaffolding, design-partner coordination overhead | **~10h** | |
| **Total with buffer** | | **~45h (~6 days focused effort)** | |
| **+ M8 (partner-gated)** | | 4h + 1 week elapsed | |

---

## Milestone 1: Bedrock Direct-Invoke Runner Pattern (5 hours)

**Goal**: Bedrock steps can use `tool:` invocation just like Azure does, bypassing the LLM. No customer-facing change yet — just the runner.

### Task 1.0: Pre-flight — verify Bedrock action_group name

**Acceptance**:
- Run `aws bedrock-agent list-agent-action-groups --agent-id <secured-agent-id> --region us-east-1` and confirm action group is named `customer_tools`
- Run for naive + unsecured agents too — all three must share the same action_group name (they do today)
- If divergent: file as a P0 blocker before proceeding; refactor M1 to support per-agent action_group from CDK output
- Capture the action_group name in `cdk/config/dev.yaml:bedrock.action_group_name` so the dashboard env wiring (Task 1.3) reads it from one source

### Task 1.1: Implement `default_bedrock_tool_invoker` (schema-aware)

**Files**:
- `src/dashboard/components/cross_cloud_scenarios.py` (modified — add factory at bottom of "Default invokers" section)

**Acceptance**:
- Function signature matches `default_azure_tool_invoker` shape (returns an `Invoker`)
- Takes `schema_fetcher: BedrockSchemaFetcher` and `signals_client: SignalsClient` as injected dependencies (per LLD 18 §4.2.5)
- **Schema-aware** event construction (LLD 18 §4.2.3): reads the agent's OpenAPI schema via `schema_fetcher`, maps each `tool_param` value to its OpenAPI-declared type (`integer | number | boolean | array | string`); raises clear error if the schema is unavailable at first use
- Builds synthetic Bedrock Action Group event with properly-typed `properties` entries (NOT all-strings)
- Calls `boto3.client('lambda').invoke(FunctionName=lambda_arn, ...)` with `InvocationType=RequestResponse`
- Parses OpenAPI envelope response → `_InvocationOutcome(decision, reason, latency_ms, raw, decision_source=SENTRA)`
- Returns ERROR outcome on Lambda invoke failure (network, permissions) — does NOT raise
- All HTTP statuses handled: 200 → ALLOW, 403 → DENY, others → ERROR

### Task 1.2: Extend `_pick_invoker` to route Bedrock + `tool:`

**Files**:
- `src/dashboard/components/cross_cloud_scenarios.py` (modified — `_pick_invoker` method)

**Acceptance**:
- New branch: `if step.cloud == "bedrock" and step.tool: return self._bedrock_tool`
- Existing `prompt:` branch preserved (no regression for S1's LLM-driven steps)
- `__init__` accepts new `bedrock_tool_invoker: Invoker` param (optional; falls back to prompt-only routing if not supplied)

### Task 1.3: Wire factory into `_build_runner`

**Files**:
- `src/dashboard/components/cross_cloud_demo.py` (modified — `_build_runner`)

**Acceptance**:
- `_build_runner` constructs `bedrock_tool_invoker = default_bedrock_tool_invoker(lambda_arn=os.environ["BEDROCK_ACTION_GROUP_LAMBDA_ARN"])`
- `BEDROCK_ACTION_GROUP_LAMBDA_ARN` added to dashboard ECS task definition env (via cdk/stacks/compute_stack.py)
- Dashboard task role gets `lambda:InvokeFunction` on the Action Group Lambda

### Task 1.4: Migrate S2 YAML to tool-based Bedrock steps + intent field

**Files**:
- `src/demo-orchestrator/scenarios/s2_cross_cloud_policy_propagation.yaml` (modified)

**Acceptance**:
- Every step gains `intent: enforcement` (per LLD 18 §4.4)
- `probe_bedrock_before` and `probe_bedrock_after` use `tool: query_customers` + `tool_params: {state: CA}` instead of `prompt:`
- `expected_reason_contains: "not authorized"` retained on after-probes
- Update YAML comment block to explain why direct-invoke + cross-ref LLD 18 §4.4

### Task 1.5: Unit tests for new invoker

**Files**:
- `tests/unit/test_cross_cloud_scenarios_runner.py` (modified)

**Acceptance**: 7 new test cases — T-RUN-01 through T-RUN-07 from [LLD 18 §10.3](../lld/18-deterministic-enforcement.md#103-runner-determinism-tests-component-a). Plus 2 new cases:
- T-RUN-08: schema-aware event builder emits `integer` type for integer-declared params
- T-RUN-09: synthetic `bedrock_guardrail` ALLOW signal posted to controller with `metadata.direct_invoke=true`

### Task 1.6: Synthetic `bedrock_guardrail` emission (LLD 17 §4 symmetric-emission)

**Files**:
- `src/dashboard/components/cross_cloud_scenarios.py` (extends Task 1.1 — same invoker function)

**Acceptance**:
- After each successful direct-invoke, the invoker posts a `bedrock_guardrail` signal to `/v1/sessions/{id}/signals` with `decision=ALLOW`, `reason="direct-invoke (LLM bypassed for deterministic scenario run)"`, `metadata={"direct_invoke": true, "invoker": "default_bedrock_tool_invoker"}`
- Emission failure logs WARN but doesn't fail the step (best-effort, mirrors `BedrockConnector._post_guardrail_signal`)
- New unit test: signals_client mock receives the expected POST per direct-invoke

### Task 1.7: Live S2 run

**Acceptance**:
- 10 consecutive S2 fires, all 4 probes pass each time
- Total runtime <30s
- Controller logs show `/v1/validate` for both Bedrock probes (proving Sentra was consulted)

---

## Milestone 2: Template Substitution for Dynamic Params (2 hours)

**Goal**: Scenario YAMLs can use `{rand.state}`, `{rand.customer_id}` etc. for per-fire randomization.

### Task 2.1: Token registry

**Files**:
- `src/dashboard/components/scenario_templates.py` (new)

**Acceptance**:
- Module exposes `SUBSTITUTION_REGISTRY: dict[str, Callable[[], str]]` with the 7 tokens from [LLD 18 §4.3](../lld/18-deterministic-enforcement.md#43-sub-component-a2-template-substitution-for-dynamic-params)
- Each generator is a pure function: no side effects, returns a string
- Module also exposes `substitute(text: str, *, request_id: str, session_id: str) -> str` that replaces tokens

### Task 2.2: Wire substitution into `_execute`

**Files**:
- `src/dashboard/components/cross_cloud_scenarios.py` (modified — `_execute`)

**Acceptance**:
- Before invoking, the runner substitutes tokens in `step.tool_params` values (string-typed only), `step.user_input`, and `step.prompt`
- Unknown tokens log WARN and leave the placeholder in place (not silently dropped)
- Substituted values are visible in `step.raw["template_resolved"]` for debugging

### Task 2.3: Tests

**Files**:
- `tests/unit/test_scenario_templates.py` (new)

**Acceptance**: T-RUN-03, T-RUN-04 from LLD 18 §10.3 plus boundary cases (token with no closing brace, two tokens in one string, recursive token → not supported, fails fast).

---

## Milestone 3: Scenario YAML Schema Validator (5 hours, with watch-item)

**Goal**: demo-orchestrator refuses to start if any scenario references a tool/param that doesn't exist in the agent's policy, OR has an inconsistent `intent` ↔ invoke-path combination.

**Effort risk (logged)**: The 5h estimate absorbs Tasks 3.1–3.6. Task 3.6 alone (removing legacy `audit_lookup_fn` — edits in 2 files + delete/replace 2 regression tests + WS17 tracker update) is ~1.5h on its own. If 3.1's validator becomes a more elaborate visitor pattern (Bedrock OpenAPI schema fetch caching, async semantics, retry on Bedrock throttling), M3 could land closer to 7h. Treat 5h as the floor, 7h as the ceiling; if 3.1 is approaching 3h alone, descope by deferring 3.6 to a separate PR.

### Task 3.1: Validator module

**Files**:
- `src/demo-orchestrator/app/services/scenario_validator.py` (new)

**Acceptance**:
- Class `ScenarioValidator(controller_client)` with method `validate_scenario(scenario_dict) -> list[ValidationError]`
- Checks:
  - (a) Every step's `agent_id` has an active policy
  - (b) Every step's `tool` is in the policy's `allowed_tools`
  - (c) `tool_params` keys are valid for the tool's OpenAPI/registered schema
  - (d) `tool_params` value types match the OpenAPI-declared types (string vs int vs bool)
  - (e) Template tokens are in `SUBSTITUTION_REGISTRY`
  - (f) **Every step has `intent: enforcement | threat_detection`** (LLD 18 §4.4)
  - (g) **`intent: threat_detection` + `tool:` = HARD ERROR** (sigma probe with bypassed LLM defeats the claim)
  - (h) **For `tool:` steps, the agent has exactly one Action Group** (LLD 18 §4.2.2 v0.1 constraint)
- Returns empty list on success; structured `ValidationError(scenario_id, step_id, error_type, message)` on failure

### Task 3.2: Bedrock OpenAPI fetch helper

**Files**:
- `src/demo-orchestrator/app/services/bedrock_schema_fetcher.py` (new)

**Acceptance**:
- Fetches the agent's Action Group OpenAPI schema via `bedrock-agent` boto3 client
- Caches per-agent for the orchestrator process lifetime
- Returns dict `{tool_name: {required_params: [...], optional_params: [...], types: {...}}}`

### Task 3.3: Azure tool registry fetch helper

**Files**:
- `src/demo-orchestrator/app/services/azure_tool_fetcher.py` (new)

**Acceptance**:
- Fetches Azure Function's `/api/health` (which lists `tools_registered`) and validates against that
- Same return shape as Bedrock helper (where param schema unknown, accepts any params and warns)

### Task 3.4: Wire validator into orchestrator startup

**Files**:
- `src/demo-orchestrator/app/main.py` (modified)

**Acceptance**:
- On startup, validator runs against every loaded scenario YAML
- Strict mode (`SCENARIO_VALIDATION_STRICT=true`, default in prod env): orchestrator exits 1 on any error
- Permissive mode (`SCENARIO_VALIDATION_STRICT=false`, dev default): logs WARN, serves the scenario anyway
- Validation results logged at INFO with one line per scenario: `✓ s2_cross_cloud_policy_propagation: validated` or `✗ s2_...: 2 errors`

### Task 3.5: Tests

**Files**:
- `tests/unit/test_scenario_validator.py` (new)

**Acceptance**: T-RUN-05, T-RUN-06 plus negative cases for each error type:
- unknown agent, unknown tool, missing required param, unknown template
- missing `intent:` field
- `intent: threat_detection` + `tool:` (must fail)
- step with `tool:` on agent that has >1 Action Group (must fail)
- OpenAPI int-typed param supplied as string (must fail)

### Task 3.6: Remove legacy `audit_lookup_fn` runner path

**Files**:
- `src/dashboard/components/cross_cloud_scenarios.py` (modified — `CrossCloudScenarioRunner.__init__`, `_execute`)
- `src/dashboard/components/cross_cloud_demo.py` (modified — `_build_runner` factory call)
- Two regression tests in `tests/unit/test_cross_cloud_scenarios_runner.py` (delete)

**Why this lives in WS18**: WS17 §M7.3 explicitly retained `audit_lookup_fn` for "rollback safety + existing regression tests" with a TODO to remove when WS17 was live everywhere. With direct-invoke landing as the canonical enforcement path (M1), the legacy CloudWatch-Insights audit lookup is no longer reachable for any new scenario — and the rollback-safety argument is satisfied by milestone-based image versioning. Removing the dead code now prevents future authors from being confused about which override path is active.

**Acceptance**:
- `audit_lookup_fn` parameter removed from `CrossCloudScenarioRunner.__init__`
- `elif self._audit_lookup is not None` branch in `_execute` deleted
- `default_audit_lookup` factory (if present) deleted
- The two legacy regression tests deleted (replaced by decisions_lookup-based equivalents)
- Workstream 17 tracker updated to mark the WS18-candidate cleanup as DONE

---

## Milestone 4: SDK Core — `@validate` Decorator (6 hours)

**Goal**: Pure-Python package, no infra deps, with the decorator + handlers + fail modes. Unit-tested in isolation.

### Task 4.1: Package skeleton

**Files** (all new):
- `sdk/python/sentra/__init__.py`
- `sdk/python/sentra/client.py`
- `sdk/python/sentra/decorator.py`
- `sdk/python/sentra/context.py`
- `sdk/python/sentra/exceptions.py`
- `sdk/python/sentra/fail_modes.py`
- `sdk/python/sentra/_internal/retry.py`
- `sdk/python/sentra/_internal/config.py`
- `sdk/python/pyproject.toml`

**Acceptance**:
- `pip install -e sdk/python/` works
- `from sentra import validate, SentraContext, SentraDenied` succeeds
- `pyproject.toml` declares Python 3.11+ requirement, zero runtime deps (stdlib only — `urllib.request`, not `requests`)

### Task 4.2: `@validate` decorator — sync path

**Files**:
- `sdk/python/sentra/decorator.py`

**Acceptance**:
- Signature matches [LLD 18 §6.2](../lld/18-deterministic-enforcement.md#62-decorator-parameters)
- Wraps function preserving `__name__`, `__doc__`, `__wrapped__`, `__signature__` (via `functools.wraps`)
- On call: extracts bound args via `inspect.signature.bind()`, calls client, raises `SentraDenied` on DENY, returns wrapped function's result on ALLOW
- Honors `fail_mode` for non-ALLOW non-DENY outcomes

### Task 4.3: `@validate` decorator — async path

**Files**:
- `sdk/python/sentra/decorator.py` (extended)

**Acceptance**:
- Auto-detects async functions via `inspect.iscoroutinefunction()`
- Returns a `functools.wraps`'d coroutine for async wrapped functions
- Async path uses `urllib.request` in a `loop.run_in_executor` thread (no aiohttp dep)

### Task 4.4: SentraContext + contextvars

**Files**:
- `sdk/python/sentra/context.py`

**Acceptance**:
- `SentraContext` is a context manager (sync + async)
- `__enter__` sets contextvars (`_session_id`, `_request_id`, `_user_input`); `__exit__` resets
- `validate()` reads contextvars; raises `SentraConfigError` if no session set
- Test: context propagates across `await asyncio.sleep(0)` boundaries (T-SDK-10)

### Task 4.5: HTTP client with retry + fail-secure

**Files**:
- `sdk/python/sentra/client.py`
- `sdk/python/sentra/_internal/retry.py`

**Acceptance**:
- `SentraClient.validate(request: dict) -> dict` returns the parsed `/v1/validate` JSON response
- Retries up to `SENTRA_RETRY_MAX` times on 5xx + network errors (with exponential backoff)
- Times out per `SENTRA_TIMEOUT_SECONDS` (per-attempt, not cumulative)
- Raises `SentraValidationError` on exhausted retries
- DENY responses parsed into `SentraDenied(reason, request_id, decision, violation_type)`

### Task 4.6: Fail-mode handling

**Files**:
- `sdk/python/sentra/fail_modes.py`

**Acceptance**:
- `FailMode` enum with three members
- `FAIL_SECURE`: re-raises `SentraValidationError`
- `FAIL_OPEN`: logs WARN with `tool_name`, `error`, calls wrapped function anyway
- `FAIL_WITH_FALLBACK`: requires `fallback_fn` param; calls `fallback_fn(*args, **kwargs)`
- Decorator validates `FAIL_WITH_FALLBACK` has a fallback at decoration time, not call time (fail fast)

### Task 4.7: Unit tests — T-SDK-01 through T-SDK-14

**Files**:
- `sdk/python/tests/test_decorator.py`
- `sdk/python/tests/test_client.py`
- `sdk/python/tests/test_context.py`
- `sdk/python/tests/test_fail_modes.py`

**Acceptance**: All 14 test cases from [LLD 18 §10.1](../lld/18-deterministic-enforcement.md#101-unit-tests-sdk) pass.

---

## Milestone 5: SDK Packaging — Lambda Layer + pip (4 hours)

**Goal**: One reproducible build artifact per environment customers care about.

### Task 5.1: Build script + CI

**Files**:
- `sdk/python/scripts/build_layer.sh` (new)
- `sdk/python/scripts/build_pypi.sh` (new)
- `.github/workflows/sdk-release.yml` (new — gated on `v*` tag)

**Acceptance**:
- `build_layer.sh` produces `sentra-sdk-python-vX.Y.Z.zip` matching AWS Lambda Layer structure (`python/sentra/...`)
- `build_pypi.sh` produces `dist/sentra_sdk-X.Y.Z-py3-none-any.whl` + `.tar.gz`
- GitHub Actions workflow on tag push: builds, signs, uploads to internal S3 (`s3://sentra-sdk-releases/`), uploads to internal PyPI

### Task 5.2: Lambda Layer publishing CDK

**Files**:
- `cdk/stacks/sdk_layer_stack.py` (new)

**Acceptance**:
- CDK stack that publishes the Layer zip from S3 to Lambda Layers in `us-east-1`, `eu-west-1`, `ap-south-1` (initial regions)
- Layer ARN format: `arn:aws:lambda:<region>:531109575379:layer:sentra-sdk-python:<version>`
- Stack outputs each region's Layer ARN

### Task 5.3: Layer integration test

**Files**:
- `sdk/python/tests/integration/test_layer.sh` (new)

**Acceptance**: Deploys a test Lambda using the Layer, invokes it with an event, asserts the decorator hits `/v1/validate` (mocked Sentra endpoint).

### Task 5.4: Internal PyPI publish

**Acceptance**:
- `sentra-sdk==0.1.0` installable from internal PyPI mirror
- README on the package page links to LLD 18 + adoption guide

---

## Milestone 6: SDK Adoption Guide + Reference Lambda (3 hours)

**Goal**: A design partner can copy/paste from working examples in <30 min.

### Task 6.1: Adoption guides

**Files** (all new):
- `docs/sdk/getting-started.md`
- `docs/sdk/bedrock-action-group.md`
- `docs/sdk/azure-function.md`
- `docs/sdk/self-hosted.md`

**Acceptance**:
- Each doc has a "Quick start" with copy-pasteable code
- Each doc covers: install, configure, decorate, deploy, test
- `bedrock-action-group.md` includes the full Lambda from [LLD 18 Appendix B](../lld/18-deterministic-enforcement.md#appendix-b-a-worked-example--what-the-customers-life-looks-like)

### Task 6.2: Reference Lambda repo

**Files**:
- `examples/sdk-bedrock-lambda/` (new)

**Acceptance**:
- Standalone repo (will eventually be its own GitHub repo): `samconfig.toml`, `template.yaml`, `src/handler.py`, `README.md`
- `sam deploy` works against a customer-provided Sentra endpoint
- 3 example tools, each with `@validate`

### Task 6.3: best-practices.md §13

**Files**:
- `best-practices.md` (modified)

**Acceptance**:
- New §13 covers: when to use the SDK vs manual integration, fail-mode selection, telemetry, common pitfalls (forgetting context, contextvars across threads, mixing sync/async)

---

## Milestone 7: Dogfood — Migrate Our Own Code (4 hours)

**Goal**: Both `lambda/bedrock_agent_actions/index.py` and `function_app.py` use the SDK internally. Validates the SDK against our own production-ish code.

### Task 7.1: Migrate Bedrock Action Group Lambda

**Files**:
- `lambda/bedrock_agent_actions/index.py` (rewritten using SDK)

**Acceptance**:
- All existing tests still pass
- No behavioral difference vs current implementation (verified by re-running S1, S2, S3, S4)
- LOC reduction: target -60% (from ~330 lines to ~120 lines)

### Task 7.2: Migrate Azure Function

**Files**:
- `src/connectors/azure_foundry/azure_function/tool_interceptor/function_app.py` (rewritten using SDK)

**Acceptance**: Same as 7.1 but for Azure.

### Task 7.3: CI ensures both stay SDK-based

**Files**:
- `.github/workflows/ci.yml` (modified)

**Acceptance**: New check that greps for `validate_with_sentra` (the old helper name) in `lambda/` + `src/connectors/`; PR blocks if found. Forces use of the SDK.

### Task 7.4: Byte-identical-envelope parity test (P2 fix)

**Files**:
- `tests/integration/test_sdk_lambda_parity.py` (new)
- `tests/fixtures/bedrock_events/*.json` (new — captured live Bedrock Agent events)

**Why**: The CI grep from 7.3 catches the *symbol*. It does NOT catch behavioral regression — e.g. if the SDK's `bedrock_action_group_handler` produces a slightly-different OpenAPI envelope from the legacy `index.py:handler`, Bedrock Agent might silently misroute a tool response. Need a positive test that runs the same input through both code paths and asserts byte-identical output.

**Acceptance**:
- Test captures 5+ representative Bedrock Agent events (ALLOW + DENY paths, multiple tools, with/without `sessionAttributes`)
- For each event, runs through (a) the legacy `lambda/bedrock_agent_actions/index.py:handler` (frozen as a test baseline before deletion) and (b) the new SDK-based handler
- Asserts `json.dumps(response_a, sort_keys=True) == json.dumps(response_b, sort_keys=True)` modulo timing fields
- Test runs on every CI build; failure blocks merge
- After 30 days of green CI passes, the frozen legacy handler is deleted (tracked in a follow-up issue)

---

## Milestone 8: Design Partner Pilot Integration (4 hours engineering + partner availability)

**Status framing**: M8 is **gated on partner availability**, not on engineering completion. WS18's engineering deliverable = M1–M7. M8 tracks separately because a design partner committing to a 1-week pilot is outside engineering's gating control.

**If M8 slips**: M1–M7 still ship as v0.1 of the deterministic-enforcement stack. WS18 closes as "engineering-complete; partner pilot in progress" and M8 graduates to its own mini-workstream.

**Goal**: One real design partner adopts the SDK in one of their staging agents.

### Task 8.1: Partner selection + scope

**Acceptance**:
- One of the 3 locked design partners (per [Market + GTM](../../.claude/projects/-Users-shshgup-code-security-mvp/memory/market_gtm.md) §Strategic decisions) commits to a 1-week pilot in their staging env
- Scope: one agent, one tool
- Success metric: SDK installed, agent's tool invocations show up in Sentra's audit log

### Task 8.2: Onboarding session

**Acceptance**:
- 90-min pair-programming session with design partner's engineer
- They write the `@validate` annotation themselves; we observe
- Capture friction points in `feedback/sdk-pilot-{date}.md`

### Task 8.3: Iterate

**Acceptance**:
- Top 3 friction points addressed via SDK PR (v0.1.1 → v0.1.2 etc.)
- Re-run pilot tool's invocations; verify Sentra logs them correctly
- Sign-off from partner: "we would adopt this in production once Sentra GAs"

---

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Lambda direct-invoke increases dashboard's IAM surface area | Medium | Scope `lambda:InvokeFunction` to one ARN; review with security |
| Scenario validator slows demo-orchestrator startup | Low | Cache policy fetches; budget 5s for validation phase |
| SDK ships a bug that breaks design partner's prod | Medium | Pilot is staging-only; SDK has built-in kill switch (`SENTRA_FAIL_MODE=FAIL_OPEN`) |
| Customers pin old SDK versions, miss security fixes | High (long-term) | Semver discipline; security advisories via the `sentra-sdk-security` mailing list |
| Decorator pattern doesn't fit a customer's framework | Low | Manual SDK client (`SentraClient` direct usage) always available; decorator is sugar |

---

## What this workstream is NOT

- Not a redesign of `/v1/validate` (LLD 03 owns that contract)
- Not changing the signal store (LLD 17 still owns the audit substrate)
- Not adding new validators
- Not building the transparent forwarding proxy (Phase 2 — separate workstream)
- Not multi-language SDKs (Python only here; Java/Go/Node deferred)

---

## Effort Summary

| Milestone | Effort | Status |
|---|---|---|
| M1 — Bedrock direct-invoke runner (schema-aware) | 5h | Pending |
| M2 — Template substitution | 2h | Pending |
| M3 — Scenario YAML validator (+ cleanup task 3.6) | 5h | Pending |
| M4 — SDK core decorator | 6h | Pending |
| M5 — SDK packaging (cross-region) | 6h | Pending |
| M6 — Adoption guide + ref Lambda | 3h | Pending |
| M7 — Dogfood migration (+ parity test) | 6h | Pending |
| **Engineering total** | **~33h + 30% buffer = ~45h** | |
| M8 — Design partner pilot (gated) | 4h + partner availability | Pending |

Calendar: ~6 days of focused engineering effort + ~1 week of design-partner pilot = **~3 weeks elapsed** end-to-end (was ~2 weeks in v0.1 — corrected for cross-region publish and design-partner coordination).

---

## Sequencing Notes

**Order within Component A (the critical S2 unblock path)**:

```
M3.2 (BedrockSchemaFetcher) ──┐
                              ▼
                       M1.1 (invoker uses fetcher)
                              ▼
                       M1.2 → M1.3 → M1.4 → M1.5 → M1.6
                              ▼
                       M1.7 (live S2 run)
```

M1.1's invoker takes `schema_fetcher` as an injected dependency (LLD 18 §4.2.5). M3.2 must ship first; the rest of M3 (Tasks 3.1, 3.3–3.6 — validator + cleanup) can land before, in parallel with, or after M1.7. The dep-table direction "M3 depends on M1" applies to *test integration* (M3's validator wants to see live scenario YAMLs that use direct-invoke), not to code dependencies — code-wise M1 depends on M3.2.

**Order within Component B**:

- M4 (SDK core) runs in parallel with M1-M3 since it has no overlapping files.
- M5 + M6 can run in parallel once M4 is feature-complete.
- M7 (dogfood) MUST land before M8 (partner pilot) — we should be running on our own SDK before asking a customer to.

**Cross-component**:

- M1's S2-unblock is the urgent thing — start with M3.2 + M1 today.
- M3's broader validator (Tasks 3.1, 3.3, 3.4, 3.5, 3.6) is the least-time-critical engineering work; can slip without affecting S2 demo reliability.
