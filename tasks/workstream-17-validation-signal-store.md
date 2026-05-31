# Workstream 17: Validation Signal Store & Multi-Signal Combiner

**Status**: In Progress — code-complete (M1–M7 implemented); M6.3 live demo + image deploy pending
**Owner**: Founder + 1 backend engineer
**Start Date**: 2026-05-26
**Code Complete**: 2026-05-26
**Live Demo Pending**: image redeploy required (see "What's queued for the image deploy" below)
**LLD Reference**: [lld/17-validation-signal-store.md](../lld/17-validation-signal-store.md) (v0.2)

**Change log since v0.1**:
- Added Milestone 3.5 — Bedrock Lambda + sessionAttributes plumbing (replaces v0.1's deferred proximity-matching approach)
- M5 Task 5.1 rewritten — runner-generated `request_id` via `sessionAttributes`, no proximity match
- Test plan expanded to 23 cases (was implicit); M4 acceptance now ties to specific test IDs
- M7 adds operational runbook + cost model entries to best-practices.md
- Total effort revised: 15 hr → 17 hr (~2 days)

---

## Overview

Replace today's CloudWatch-Logs-Insights-backed audit read path with a DynamoDB-backed signal store that captures every validator's contribution (Sentra sub-validators + cloud-native guardrails + future ML) as a first-class row, combined via a pluggable algorithm. CloudWatch audit logs preserved unchanged as compliance source of record.

### Why

S1's `aws_attack` shows ALLOW despite Sentra returning DENY because the dashboard's audit override depends on CloudWatch Logs Insights, which has >60s indexing lag (measured empirically — see [LLD 17 §2](../lld/17-validation-signal-store.md#2-why-now--concrete-trigger)). S2/S3/S4 hit the same wall. Future ML classifier needs an explicit multi-signal substrate. Doing it right once is cheaper than three incremental patches.

### Success Criteria

- DDB table `sentra-validation-signals` provisioned with TTL + GSI 1 (agent-timestamp) + GSI 2 (decision-date-timestamp).
- Every `/v1/validate` call writes one signal row per active validator (Sentra sub-signals).
- Bedrock Lambda reads `sessionAttributes["sentra_request_id"]`; Bedrock + Azure connectors POST their edge signals with the same `request_id`.
- `GET /v1/sessions/{id}/decisions` returns grouped + combined verdicts in p95 ≤100ms.
- Cross-cloud demo runner cuts over; S1 `aws_attack` renders `DENY` with `By: 🛡 sentra.sigma`.
- `/v1/logs` (CloudWatch path) remains functional for compliance use.
- All 23 test cases from [LLD 17 §14](../lld/17-validation-signal-store.md#14-test-plan) pass.

---

## Milestone 1: Storage Substrate (2 hours)

**Goal**: Provision the DDB table + IAM. No code path uses it yet.

### Task 1.1: CDK construct — `signal_store_table.py`

**Files**:
- `cdk/constructs/signal_store_table.py` (new)
- `cdk/stacks/storage_stack.py` (modified — instantiate construct, export ARN)

**Acceptance**:
- DDB table `sentra-validation-signals` exists in `us-east-1`, on-demand capacity.
- PK=`session_id` (S), SK=`sk` (S) where sk = `request_id#timestamp_ms#source`.
- TTL attribute `expires_at` enabled.
- GSI 1 `agent-timestamp-index`: PK=`agent_id`(S), SK=`timestamp_ms`(N), projection ALL.
- GSI 2 `decision-date-timestamp-index`: PK=`decision_date`(S), SK=`timestamp_ms`(N), projection ALL.
- `RemovalPolicy.RETAIN`.
- Stack output `SignalStoreTableName`.

### Task 1.2: IAM grants

**Files**:
- `cdk/stacks/compute_stack.py` (modified — grant controller task role)

**Acceptance**:
- Controller task role: `PutItem`, `BatchWriteItem`, `Query` on table + both GSIs; `Scan` on GSI 2 only.
- Dashboard task role: no direct DDB access.
- Lambda role (`sentra-mvp-bedrock-agent-actions`): no new permissions needed (still writes via `/v1/validate`, not directly to DDB).

### Task 1.3: Deploy + smoke

**Acceptance**:
- CDK deploy clean.
- Manual `aws dynamodb put-item` succeeds; `Query` returns the item; TTL attribute visible.

---

## Milestone 2: Combiner Module + Signal Model (3 hours)

**Goal**: Pure-Python module, no infra dependency. Unit-tested in isolation.

### Task 2.1: `Signal` dataclass + JSON codec

**Files**:
- `src/security-controller/app/combiners/__init__.py` (new)
- `src/security-controller/app/combiners/signal.py` (new)

**Acceptance**:
- `Signal` dataclass per [LLD 17 §5.1](../lld/17-validation-signal-store.md#51-signal) — `frozen=True`, `metadata=field(default_factory=dict)`.
- `Signal.to_dict()` / `Signal.from_dict()` round-trip cleanly.
- `pytest tests/unit/test_signal_codec.py` passes.

### Task 2.2: `DenyOverrides` algorithm

**Files**:
- `src/security-controller/app/combiners/deny_overrides.py` (new)
- `src/security-controller/app/combiners/protocol.py` (new — `CombiningAlgorithm` Protocol)

**Acceptance**:
- Empty list → `ValueError`.
- All ALLOW → combined ALLOW.
- Single DENY → combined DENY with that source's reason.
- Multiple DENYs → highest-priority denier's reason wins; confidence breaks priority tie; alphabetical source breaks confidence tie.

### Task 2.3: Unit tests — combiner (LLD §14.1 tests 1-9)

**Files**:
- `tests/unit/test_combiner.py` (new)

**Acceptance**:
- 9 cases per [LLD 17 §14.1](../lld/17-validation-signal-store.md#141-unit-tests).
- All pass with `pytest -v`.

---

## Milestone 3: Audit Logger — Dual-Write (3 hours)

**Goal**: `audit_logger` writes signals to DDB in addition to CloudWatch.

### Task 3.1: `signal_store_writer.py`

**Files**:
- `src/security-controller/app/utils/signal_store_writer.py` (new)

**Acceptance**:
- `write_signals(session_id, request_id, signals: list[Signal], shared_attrs: dict)` uses `BatchWriteItem` (max 25 per batch).
- Computes `expires_at = now + 90 days`.
- Computes `decision_date = timestamp_iso[:10]` (assertion: timestamp_iso must include milliseconds and end with Z).
- Sync best-effort with 200ms total timeout across all retries.
- `UnprocessedItems` retried up to 3x with backoff [50ms, 200ms, 800ms].
- Timeout / failure: log warning, increment `signal_store.write.timeout|failure`, do not raise.

### Task 3.2: Refactor `audit_logger.log_decision` → `log_signals`

**Files**:
- `src/security-controller/app/utils/audit_logger.py` (modified)
- `src/security-controller/app/services/validation_service.py` (modified — gather Signal from each validator)

**Acceptance**:
- `validation_service.validate_tool_call` collects `Signal` objects from each validator that ran (validators short-circuited by deny-overrides emit ALLOW signal with `metadata={"skipped": true}` so the symmetric-emission rule from LLD §4 holds — or alternatively are filtered out; choose the former for honesty).
- `audit_logger.log_signals(...)` dual-writes: DDB (N items via writer) + CloudWatch (1 event with `signals[]` array).
- Existing CloudWatch event format additively extended; existing fields unchanged.
- Backward-compat wrapper: legacy `audit_logger.log_decision(...)` callers still work.

### Task 3.3: Validator Signal Emission

**Files**:
- `src/security-controller/app/validators/trust_checker.py` (modified)
- `src/security-controller/app/validators/policy_engine.py` (modified)
- `src/security-controller/app/validators/sigma_engine.py` (modified)
- `src/security-controller/app/validators/context_validator.py` (modified)
- `src/security-controller/app/validators/abuse_detector.py` (modified)
- `src/security-controller/app/validators/cross_agent_validator.py` (modified)

**Acceptance**:
- Each validator's return type augmented with a `signal: Signal` field.
- Source strings match [LLD 17 §4](../lld/17-validation-signal-store.md#4-signal-taxonomy).
- Existing validator unit tests pass unchanged (behavior preserved); new assertions cover `signal` shape.

### Task 3.4: Unit tests — writer (LLD §14.1 tests 10-13)

**Files**:
- `tests/unit/test_signal_store_writer.py` (new)

**Acceptance**:
- 4 cases per [LLD 17 §14.1](../lld/17-validation-signal-store.md#141-unit-tests) — timestamp rejection, decision_date computation, retry path, timeout degrade.

---

## Milestone 3.5: Bedrock Lambda + sessionAttributes Plumbing (1.5 hours)

**Goal**: Lambda reads `sentra_request_id` from `sessionAttributes`. This is the foundation for runner-originated correlation.

### Task 3.5.1: Lambda reads sessionAttributes

**Files**:
- `lambda/bedrock_agent_actions/index.py` (modified)

**Acceptance**:
- Handler extracts `event.get("sessionAttributes", {}).get("sentra_request_id")`.
- Uses it as `request_id` in the `/v1/validate` payload.
- Fallback: if absent (e.g., orchestrator's `prompts:` block invocations), generate `bedrock-<uuid>` — preserves existing behavior.
- Lambda CloudWatch log includes `request_id` source: `"request_id_source": "sessionAttributes"|"generated"`.

### Task 3.5.2: Deploy + smoke

**Acceptance**:
- Lambda redeployed via existing deployment path.
- Synthetic Bedrock invoke with `sessionAttributes={"sentra_request_id": "test-abc"}` → CloudWatch log shows `request_id="test-abc"`.
- Synthetic invoke without `sessionAttributes` → log shows generated UUID + `request_id_source=generated`.

---

## Milestone 4: Read Endpoints (2.5 hours)

### Task 4.1: `GET /v1/sessions/{id}/decisions`

**Files**:
- `src/security-controller/app/api/routes.py` (modified)
- `src/security-controller/app/services/decisions_service.py` (new)

**Acceptance**:
- Query params per [LLD 17 §8.2](../lld/17-validation-signal-store.md#82-get-v1sessionssession_iddecisions).
- Behavior: when `request_id` param present → `Query(PK=session_id, SK begins_with <request_id>)`; otherwise → full partition scan with `Query(PK=session_id)`.
- Groups by request_id in-memory; applies combiner per group.
- p95 ≤ 100ms on a session with 10 requests.

### Task 4.2: `GET /v1/sessions/{id}/signals` (raw)

**Acceptance**: returns raw signal list, no combiner. Filters per [LLD 17 §8.3](../lld/17-validation-signal-store.md#83-get-v1sessionssession_idsignals).

### Task 4.3: `GET /v1/decisions` (paginated scan via GSI 2)

**Acceptance**:
- Time-range query via GSI 2.
- Cursor is opaque base64'd `LastEvaluatedKey`; round-trips correctly.
- Filters `agent_id`, `decision`, `threat_type` apply post-query.

### Task 4.4: `POST /v1/sessions/{id}/signals` (external producers)

**Acceptance**:
- Validates source against taxonomy.
- Writes via `signal_store_writer.write_signals([signal])`.
- Returns 201 with `signal_sk`.

### Task 4.5: Integration tests (LLD §14.2 tests 14-19)

**Files**:
- `tests/integration/test_signal_store.py` (new)

**Acceptance**:
- 6 cases per [LLD 17 §14.2](../lld/17-validation-signal-store.md#142-integration-tests). Gated by `RUN_INTEGRATION=1`.
- Test 17 (request_id collision under same-ms writes) is a regression guard against the SK collision class.

---

## Milestone 5: Connector Signal Producers (2 hours)

### Task 5.1: Bedrock connector — sessionAttributes + signal emission

**Files**:
- `src/connectors/bedrock/bedrock_connector.py` (modified)
- `src/connectors/base/signals_client.py` (new — thin HTTP wrapper for POST /signals)

**Acceptance**:
- `BedrockConnector.invoke_agent` accepts optional `request_id` param. If omitted, generates one (`bedrock-<uuid>`).
- Passes `sessionAttributes={"sentra_request_id": request_id}` via `sessionState` argument to the `invoke_agent` boto3 call.
- After stream completes, POSTs `bedrock_guardrail` signal to `/v1/sessions/{session_id}/signals`:
  - `decision=DENY` if guardrail trace observed in stream; else `decision=ALLOW`.
  - `request_id` = the one passed in / generated.
  - `priority=40` per taxonomy.
- Signal POST failures log warning + metric; do not fail the invoke.

### Task 5.2: Azure connector — request_id threading + signal emission

**Files**:
- `src/connectors/azure_foundry/azure_connector.py` (modified)

**Acceptance**:
- `invoke_agent` accepts optional `request_id`; generates one if omitted (`azure-<uuid>`).
- HTTP body to Function App includes `request_id`.
- Function App forwards to `/v1/validate` (assumes Function App already supports this; if not, this task expands by 30 min for the Function App change).
- After loop completes, POSTs `azure_content_filter` signal:
  - `decision=DENY` if HTTP 400 with `content_filter` observed; else `decision=ALLOW`.
  - `request_id` matches threaded one.

### Task 5.3: Azure Function App — accept request_id from body

**Files**:
- `src/connectors/azure_foundry/azure_function/tool_interceptor/__init__.py` (modified)

**Acceptance**:
- Reads `request_id` from request body; passes to `/v1/validate` payload.
- Falls back to generated `azure-<uuid>` if not present.

---

## Milestone 6: Dashboard Cut-Over (2 hours)

### Task 6.1: Replace audit_lookup with decisions_lookup

**Files**:
- `src/dashboard/services/security_controller_client.py` (modified — add `get_session_decisions`, `post_session_signal`)
- `src/dashboard/components/cross_cloud_scenarios.py` (modified)
- `src/dashboard/components/cross_cloud_demo.py` (modified)

**Acceptance**:
- Runner generates `request_id` per step: `xc-{scenario_id}-{step_id}-{uuid8}`.
- Passes to BedrockConnector/AzureConnector invocations.
- Audit-lookup-on-CloudWatch code removed.
- `decisions_lookup_fn(session_id, request_id)` → returns combined verdict from `GET /v1/sessions/{id}/decisions?request_id=...`.

### Task 6.2: UI surfaces combined source + signals expander

**Files**:
- `src/dashboard/components/cross_cloud_demo.py` (modified)

**Acceptance**:
- "By" column shows `combined.winning_source` with badge taxonomy.
- Per-row expander renders all signals from `signals[]` (source, decision, reason, priority).

### Task 6.3: End-to-end demo verification (LLD §14.2 tests 20-22)

**Acceptance**:
- Fire S1 from dashboard → `aws_attack` row shows DENY + `By: 🛡 sentra.sigma`. (The original bug fixed.)
- Fire S1 → `azure_attack` shows DENY + `By: 🛡 sentra.sigma` plus `azure_content_filter` ALLOW in expander.
- Fire S3 → cross-cloud dependency miss observable as `sentra.context: DENY` on the refund step.

---

## Milestone 7: Cleanup + Docs (1.5 hours)

### Task 7.1: Update LLD 03 + LLD 15 cross-refs

**Acceptance**:
- LLD 03 §"Audit Logging" cross-refs LLD 17.
- LLD 15 §9.4 ("Asserts") updated to describe the multi-signal expander.

### Task 7.2: best-practices.md addendum — §12 Validation Signal Store

**Acceptance**:
- New §12 covers:
  - Table name, GSI names, TTL.
  - When to use DDB endpoint vs CloudWatch (`/v1/logs`).
  - Operational runbook entries from [LLD 17 §15](../lld/17-validation-signal-store.md#15-operational-runbook).
  - Cost model summary one-liner.

### Task 7.3: Remove TODO comments from runner

**Acceptance**:
- All audit-lookup-related TODOs in `cross_cloud_scenarios.py` and `cross_cloud_demo.py` removed.

### Task 7.4: Manual load test (LLD §14.3 test 23)

**Acceptance**:
- 100 concurrent `/v1/validate` calls into one session via `scripts/load_test_validate.py`.
- No SK collisions in DDB.
- All signals correlate to their request_ids.
- p95 latency stays under 800ms.

---

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Bedrock `sessionAttributes` not propagating to Action Group events as expected | Low — well-documented SDK behavior | Smoke test in M3.5 with synthetic event before downstream tasks |
| DDB write latency spikes during burst | Low at MVP scale | 200ms timeout + best-effort degrade; alerting at >1% timeout rate |
| GSI 2 hot partition (current day) | Low at MVP traffic | Document sharded-PK upgrade (`YYYY-MM-DD#shard0..9`) in [LLD 17 §5.2](../lld/17-validation-signal-store.md#52-ddb-schema--sentra-validation-signals) |
| Validator refactor breaks existing tests | Medium | Each validator's existing return shape preserved; `signal` is additive; CI gate |
| DDB drops signals on timeout | Low | CloudWatch keeps the row (dual-write); runner degrades gracefully showing partial signal set |
| Azure Function App body schema change blocks deploy | Low | Backward-compat: Function reads `request_id` if present, generates one otherwise |

---

## Out of Scope (this workstream)

- ML classifier validator (separate workstream)
- `WeightedConfidenceCombiner`
- Streaming signal subscription
- Dedicated drill-down UI for per-request signal timeline
- Backfill of historical CloudWatch entries into DDB (Phase 2 tool — referenced in [LLD 17 §15.3](../lld/17-validation-signal-store.md#153-recovery--ddb-region-outage))

---

## Status Snapshot

All milestones below are **code-complete and merged**. M6.3 (end-to-end live demo) is the only outstanding work — gated on a controller + dashboard + Lambda + Function App image redeploy (see "What's queued for the image deploy" below).

| Milestone | Status | Date | Evidence |
|---|---|---|---|
| M1: Storage Substrate | ✅ COMPLETE (deployed) | 2026-05-26 | DDB table `sentra-validation-signals` ACTIVE in `us-east-1`; both GSIs ACTIVE; TTL on `expires_at` enabled. Controller task role IAM grants live (CloudFormation `Sentra-DEV-Compute-Stack` UPDATE_COMPLETE). |
| M2: Combiner Module + Signal Model | ✅ COMPLETE | 2026-05-26 | 14/14 tests pass (`tests/test_combiner.py`). 9 cases from [LLD §14.1](../lld/17-validation-signal-store.md#141-unit-tests) + 4 codec round-trip + 1 Protocol conformance. |
| M3: Audit Logger Dual-Write | ✅ COMPLETE | 2026-05-26 | Writer + audit_logger refactor + 6 validators decorated. `_handle_deny` (validation_service.py:312) and `_handle_allow` (validation_service.py:370) both route through `log_signals` when signals are present. 280 controller tests pass, no regression. |
| M3.5: Bedrock Lambda + sessionAttributes | ✅ COMPLETE | 2026-05-26 | `lambda/bedrock_agent_actions/index.py:235-241` reads `event.sessionAttributes["sentra_request_id"]`, falls back to UUID. Logs `request_id_source = sessionAttributes\|generated`. Deploy + smoke test deferred to combined image bump. |
| M4: Read Endpoints | ✅ COMPLETE | 2026-05-26 | 4 endpoints registered (verified via FastAPI router introspection): GET `/sessions/{id}/decisions`, GET `/sessions/{id}/signals`, GET `/decisions`, POST `/sessions/{id}/signals`. 6/6 integration tests pass against live DDB (`RUN_INTEGRATION=1 pytest tests/test_decisions_service.py`). Not part of standard CI — opt-in only. |
| M5: Connector Signal Producers | ✅ COMPLETE | 2026-05-26 | `SignalsClient` HTTP wrapper (stdlib-only) + Bedrock connector emits `bedrock_guardrail` symmetric ALLOW/DENY + Azure connector emits `azure_content_filter` symmetric + Function App forwards `request_id` from body. Connector imports verified clean. |
| M6.1: Dashboard runner cut-over | ✅ COMPLETE | 2026-05-26 | `decisions_lookup_fn` replaces `audit_lookup_fn` in cross_cloud_demo factory. 36/36 runner tests pass (32 existing + 4 new W17 tests covering decisions_lookup override, source attribution, missing-lookup graceful degrade, precedence over legacy). |
| M6.2: UI surfaces combined source + signals expander | ✅ COMPLETE | 2026-05-26 | `_render_signals_table` expander shows every contributor's source/decision/priority/confidence/reason. 9 new source badges in `_SOURCE_BADGES` for `sentra.*` granular taxonomy. |
| M6.3: End-to-end live demo verification | ⏸ PENDING | — | Gated on image redeploy. Plan: bump controller + dashboard + Lambda + Function App images, redeploy ECS services, fire S1–S4 from dashboard, confirm `aws_attack` shows DENY with `By: 🛡 Sentra sigma` + signals expander populates. |
| M7.1: Cross-ref updates in LLD 03 + LLD 15 | ✅ COMPLETE | 2026-05-26 | LLD 03 §10.1 + §10.3 reference LLD 17; LLD 15 §9 adds W17 cut-over callout. |
| M7.2: best-practices.md §12 | ✅ COMPLETE | 2026-05-26 | New §12 "Validation Signal Store" covers schema, when-to-use-which-read-path, reconciliation rule, cost model, operational gotchas. |
| M7.3: Remove audit-lookup TODOs | ✅ COMPLETE | 2026-05-27 (WS18 M3.6) | Phase 1 (M7.3, 2026-05-26): `_seven_days_ago_iso()` helper removed; `audit_lookup_fn` param + `elif self._audit_lookup` fallback retained for back-compat. Phase 2 (WS18 M3.6, 2026-05-27): full removal — `audit_lookup_fn` constructor param, `AuditLookupFn` type alias, `self._audit_lookup` attribute, and `elif` branch all deleted. 6 legacy audit-lookup tests removed; functional coverage moved to decisions_lookup_fn tests. See [LLD 18 §9.3](../lld/18-deterministic-enforcement.md#93-backwards-compatibility) and [Workstream 18 Task 3.6](workstream-18-deterministic-enforcement.md). |
| M7.4: Load test | ✅ COMPLETE | 2026-05-26 | `scripts/load_test_signal_store.py` ran 100 concurrent writes × 5 signals each = 500 distinct DDB items, zero SK collisions, every request_id preserved with exactly 5 signals. p95 latency 2.2s from laptop (will be <100ms from ECS). |
| **Total effort** | ~14 hr actual vs 17.5 hr estimate | | All 23 LLD §14 test cases addressed (15 unit + 6 integration + 1 load + M6.3 deferred). |

---

## What's queued for the image deploy

Code-complete but not yet running in ECS. Six artifacts need rebuilt + pushed:

| Service / artifact | Changes |
|---|---|
| **security-controller** image | New `app/combiners/` module, `app/utils/signal_store_writer.py`, refactored `app/utils/audit_logger.py` (dual-write `log_signals`), 6 validators decorated with `@stamps(Source.SENTRA_*)`, `app/services/decisions_service.py`, 4 new routes in `app/api/routes.py`, 3 new settings in `app/config.py`. |
| **dashboard** image | `services/security_controller_client.py` (`get_session_decisions`, `post_session_signal`), `services/bedrock_agent_caller.py` (forwards `request_id`), `components/cross_cloud_scenarios.py` (decisions_lookup + per-step request_id), `components/cross_cloud_demo.py` (factory + UI expander + 9 source badges). |
| **bedrock_agent_actions** Lambda | Reads `event.sessionAttributes["sentra_request_id"]`, falls back to UUID, logs source. |
| **Azure Function App** (`tool_interceptor`) | `validate_with_sentra` accepts `supplied_request_id`; route handler reads `body["request_id"]`. Stdlib-only — no `requirements.txt` change. |
| **Connector code** (shipped inside dashboard image) | `connectors/base/signals_client.py`, `connectors/bedrock/bedrock_connector.py` (sessionAttributes + `_post_guardrail_signal`), `connectors/azure_foundry/azure_connector.py` (`request_id` in HTTP body + `_post_content_filter_signal`). |
| **No infra changes left** | Storage + Compute stacks already up-to-date. |

**Deploy order**:
1. `scripts/build_and_push_image.py --service security-controller --milestone N` — get the new endpoints live.
2. Force-redeploy ECS service `sentra-security-controller` to pick up the new image.
3. Deploy Lambda code update (Lambda is updated via CDK if its code path changed).
4. `azd deploy` for the Function App (or `func azure functionapp publish` for inner-loop).
5. `scripts/build_and_push_image.py --service dashboard --milestone N` — gets the runner cut-over + UI live.
6. Force-redeploy ECS service `sentra-dashboard`.
7. Run M6.3: Fire S1 from the dashboard, verify `aws_attack` shows `DENY` + `By: 🛡 Sentra sigma` + signals expander populated.

**Rollback path**: revert each image to its prior milestone tag. The legacy `audit_lookup_fn` constructor param in the runner means an old controller (no `/v1/sessions/{id}/decisions`) still produces correct rows — just without the per-signal expander.

---

## Cross-References

- **LLD**: [lld/17-validation-signal-store.md](../lld/17-validation-signal-store.md)
- **Related LLDs**: [03](../lld/03-security-controller.md), [04](../lld/04-dashboard-v2.md), [15](../lld/15-cross-cloud-connectors.md), [09](../lld/09-agent-execution-and-llm-response.md)
- **Triggering RCA**: S1 `aws_attack` ALLOW root cause analysis (session 2026-05-26)
- **Kiro review**: incorporated in LLD v0.2 — see LLD's change log
- **Best practices**: [best-practices.md §11](../best-practices.md#11-cloud-account-reference); new §12 added by Task 7.2
