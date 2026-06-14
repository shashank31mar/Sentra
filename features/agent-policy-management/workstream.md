# Workstream — Agent Policy Management + Policy Library CRUD + Enable/Disable (build spec)

**Version**: 1.0
**Last Updated**: 2026-06-10
**Status**: Ready for Review
**Contract reference**: [`feature.md`](./feature.md) (the feature doc is the *decision record*; this doc is the *build spec* — exact files, logic, wiring, and acceptance per task so implementation does not have to second-guess). Related: LLD 21 (API inventory §13), LLD 11 (Policy CRUD), LLD 03 (policy engine).

> Scope: ship the **binding model** end-to-end. The engine resolves an agent's policy from a **binding** (`attached_policy_id`) it reads off the agent record (not a GSI scan of "the one active policy"), cloud identity resolves **from the agent** (not the policy), and the console exposes **attach/detach** (per-agent, Agent Inventory) split cleanly from **create/update/delete/enable/disable** (policy lifecycle, Policies tab). Each task states its **Type**, exact backend handler/service/store or frontend file, the change, **API Gateway wiring** where relevant, **acceptance**, and dependencies.
>
> **The single most dangerous task is M0 (backfill).** The instant the engine reads the binding, any agent without `attached_policy_id` fails-secure to DENY on *every* tool call. M0 + the GSI fallback (T11) make the cutover no-outage. Do M0 first; ship the engine with the fallback.

---

## 0. Critical callouts — verified against code, must-honor invariants

These are real, verified against the current code (`src/security-controller`, `web/console`, `scripts`, `cdk`). They are the traps the feature doc's R/N/C review surfaced; every one maps to a task below.

| # | Severity | Issue | Evidence | Action |
|---|----------|-------|----------|--------|
| K1 | **Blocker** | **No agent has `attached_policy_id` today.** The agent→policy link is *only* the policy's `agent_id` field + the `agent-index` GSI; `seed_agents.py` sets no binding. The moment the engine reads the binding, every existing agent resolves `null` → `POLICY_NOT_FOUND` → **fleet-wide DENY outage**. | [`seed_agents.py`](../../scripts/seed_agents.py); feature §2.6 | **M0 first**: backfill `attached_policy_id` from the GSI-resolved active policy (T10), and ship the engine with a **legacy-GSI fallback** (T11) so order is safe either way. |
| K2 | **Blocker** | **`policy_id` is NOT `agent-config-{agent_id}`** *for resolution*. `apply_policy.py:116-121` exists precisely because the stored id is **not** deterministic from `agent_id` (legacy suffixes `-policy-v1`, `pol-{agent_id}-001`). Reconstructing it to **resolve** "bites every time." **C1 nuance:** `create_policy` (`policy_service.py:350`) **does** mint `agent-config-{agent_id}` — but that is id **assignment** for a *new* policy (and the basis of 409-dup detection), not resolution. So new policies have derivable ids; legacy/seeded ones don't. | [`apply_policy.py:116-121`](../../scripts/apply_policy.py#L116); [`policy_service.py:350`](../../src/security-controller/app/services/policy_service.py#L350) | **Always resolve, never reconstruct** on read paths (T10, T12, T15, T31, T35). Compare by the policy's `agent_id` field; load by the **stored** `policy_id`. **Do not** "fix" `create_policy:350` to stop deriving, and **do not** assume its format when resolving. |
| K3 | **Blocker** | **Cloud identity is read from the POLICY, not the agent.** `policy_engine.validate` sets `platform = policy.get("platform")`, `cloud_region = policy.get("cloud_region")` (`:151-152`); `context_validator` enforces the *policy's* `cross_cloud_dependencies`. Bind payments-agent's policy (bedrock/us-east-1) to telecom-agent (azure/centralus) → engine resolves the **wrong cloud** and **wrong cross-cloud rules**. Binding without this fix is **unsafe across clouds**. | [`policy_engine.py:151-152`](../../src/security-controller/app/validators/policy_engine.py#L151); `context_validator.py` | **Resolve `platform`/`cloud_region` from the AGENT record** (T12). Requires adding `cloud_region` to the agent registry (T03). Keep policy fields for audit but non-authoritative. |
| K4 | **High** | **All seeded policies are `created_by='system'`.** `seed_policies_metadata.py:207` defaults `created_by='system'`; seed YAMLs are system-authored. Both `delete_policy` and the new `set_policy_status` would 403 on `system` → on real data, **Disable/Enable/Delete 403 on every policy** → half the Policies tab dead. | [`seed_policies_metadata.py:207`](../../scripts/seed_policies_metadata.py#L207); [`policy_service.py:588`](../../src/security-controller/app/services/policy_service.py#L588) | **§2.8 decision**: Enable/Disable **allowed** (remove the system-403 from `set_policy_status` — T20), Edit **allowed** (no change — `update_policy` 403s only on `disabled`), Delete **protected** (keep the system-403 in `delete_policy`). UI disables only Delete on system rows (T44). |
| K5 | **High** | **`PolicyEngine` has no agent-registry handle.** `__init__` holds only `metadata_table` (policies) + `s3_client`. To read the binding + agent cloud identity it needs `dynamodb_agent_registry_table`. **No CDK/IAM change** — the controller task role already has read on the registry (verified). | [`policy_engine.py` `__init__`](../../src/security-controller/app/validators/policy_engine.py) | Add `self.agent_registry` handle (T12). State explicitly: **no permissions change** so no one hunts for one. |
| K6 | **High** | **Four callers resolve the agent's policy** — the change must be centralized in `get_agent_policy` or they diverge. `validation_service.py:264`, `policy_engine.py:136`, `context_validator.py:185`, `cross_agent_validator.py:110`. If only the policy-engine path changes, cross-cloud deps / rate-limit / cross-agent see a *different* policy. | grep `get_agent_policy` | Centralize binding + cloud-from-agent resolution **inside** `get_agent_policy`; verify each of the 4 call sites (T12, T13). |
| K7 | **High** | **No invalidatable in-process cache is safe.** Steady-state is **1 Fargate task** (`compute_stack.py:1566` default 1; `dev/staging/prod.yaml` all `desired_count: 1`) — but deploys **transiently run 2** (`max_healthy_percent=200`, `compute_stack.py:1568`) and horizontal scale-out is expected. A write on task B does **not** invalidate a cache on task A (the exact Sigma-rule cache bug). | [`compute_stack.py:1566-1568`](../../cdk/stacks/compute_stack.py#L1566); `cdk/config/*.yaml` | Keep binding→policy resolution **uncached** (two PK `get_item`s are cheap), or short fixed-TTL with TTL-bounded staleness — **no** cross-task "invalidate on write" claim (T12). |
| K8 | **Medium** | **Agent↔policy is not 1:1.** Some agents have **no** policy (`security-controller`, the `*-unsecured` demo agent); some policies have **no** agent (orphan, e.g. `azure-verification-agent`). A naive "every agent must be bound" verify step fails. The expected-unbound set splits two ways vs the inventory filter (K11): `security-controller` is `visibility='internal'` → **never shown** in inventory; the `*-unsecured` demo agent is external → **shown, with an Attach button** (intentionally-unsecured but prompts for attach — accepted, not a bug). | `seed_agents.py` / `seed_policies*`; [`agent_service.py:152`](../../src/security-controller/app/services/agent_service.py#L152) | Backfill **skips** no-policy agents (expected-unbound, listed for sign-off) and orphan policies; verify asserts "every agent that *had* a resolvable active policy is now bound," **not** "all bound" (T10). |
| K11 | **Medium** | **`list_agents` hides `visibility='internal'` agents** (`agent_service.py:152`, kept as a defense-in-depth safety net per WS-21 D4). So the inventory + attach UI only ever see **external** agents. The expected-unbound set (K8) must be classified internal-vs-external so the operator experience is documented, not discovered as a surprise. | [`agent_service.py:152`](../../src/security-controller/app/services/agent_service.py#L152) | T22/T41: `active_policy_id` enrich + attach UI operate only on external agents; internal unbound agents (e.g. `security-controller`) never surface; external unbound agents (e.g. `*-unsecured` demo) show **Attach** by design. |
| K12 | **High** | **A FIFTH policy-resolution site (`get_agent_tools`) bypasses `get_agent_policy`.** `AgentService.get_agent_tools` (`agent_service.py:316`, powers **Agent Detail → Tools tab**) resolves the policy via the **legacy `agent-index` GSI**, independent of the engine. Not an enforcement path — but after a different policy is bound, the Tools tab shows the **GSI-authored** tools, not the **bound** tools → UI contradicts what's enforced. The "4 callers" claim (K6) is true only for enforcement. | [`agent_service.py:316`](../../src/security-controller/app/services/agent_service.py#L316) | **T15** — `get_agent_tools` resolves via the binding + same GSI fallback as `get_agent_policy` (§2.6); displayed tools = enforced tools. |
| K13 | **High** | **3 frontend surfaces still read the vestigial String-Set `attached_policy_ids`** — which the scalar binding (§2.4) **no longer writes**, so they go stale/empty post-cutover. `AgentInventoryPage.tsx:68,72` (rebound by T41), plus **`AgentDetailPage.tsx:42`** and **`AgentFlowTab.tsx:27`** (not in the original FE task list). `types/api.ts:242,247` + `mockRouter.ts:87` carry the old field. | [`AgentDetailPage.tsx:42`](../../web/console/src/features/agents/AgentDetailPage.tsx#L42); [`AgentFlowTab.tsx:27`](../../web/console/src/features/agents/AgentFlowTab.tsx#L27) | **T47** — migrate `AgentDetailPage` + `AgentFlowTab` (+ types/mock) from `attached_policy_ids` (Set) to scalar `active_policy_id`. DDB attribute stays (no data migration); FE stops reading it. |
| K9 | **Medium** | **Early trust-DENY returns before the policy loads** → `platform`/`cloud_region` come back `null` unless the interceptor stamped them. | `validation_service` trust-check path | Under cloud-from-agent we read the agent up front; **stamp cloud identity before the trust check** (T13) — fixes the gap as a side-benefit. |
| K10 | **Medium** | **Console api bodies are wrong vs backend.** `lib/api/policies.ts` sends `{name,content}`/`{content}`; backend expects `PolicyCreateRequest`/`PolicyUpdateRequest` (structured). Edit must **omit `version`** (backend auto-bumps only when absent; sending the prefilled value overwrites the same S3 version → breaks audit/rollback). | `lib/api/policies.ts`; `policy_service.update_policy:493-494` | Fix create/update bodies; omit version on edit (T35, T41). |

### 0.1 Verification notes (feature-doc R/N/C review — all confirmed against code)

The feature doc folded in an external review (Kiro) escalating through R1–R8, N1–N4, C1–C4. Each was independently re-verified against code before acceptance. Mapping into this build spec:

- **R1 → K1/M0/T10/T11.** Backfill is blocking and must precede (or ship behind a fallback alongside) the engine change.
- **R2 → K2.** `policy_id` not derivable; always resolve.
- **R3 → K6/T12/T13.** All four `get_agent_policy` callers go through the centralized method.
- **R4 → K9/T13.** Stamp cloud before the trust-DENY return.
- **R5 → K7/T12.** No cross-task invalidatable cache.
- **R6** — detach copy says "re-attach from this row at any time" (T42 copy).
- **R7 → T12.** `cloud_region` fallback chain: agent → policy → `cloud_provider`-derived default; never error on a missing field.
- **R8** — `policy.agent_id` is **authoring origin, not governance attribution** under sharing; documented as a known limitation (§7), `verify_data_model.py` note carried.
- **N1 → K4/§2.8/T20/T44.** System-policy: enable/disable/edit allowed, delete protected — propagated to every section (C1–C3 resolved).
- **N2 → K8/T10.** Non-1:1 backfill.
- **N3 → K5/T12.** Add registry handle, no IAM change.
- **N4 → T10.** Backfill resolves via the **policies table's** `agent-index` GSI, **not** the registry's `status-index`.
- **C4 → T35/T44.** Edit allowed on system policies (`update_policy` only 403s on `disabled`); UI exposes Edit on system rows.

**Impact-analysis findings (post-review code sweep — all verified against source):**
- **G1 → K12/T15.** `get_agent_tools` is a fifth policy-resolution site (display path) that must honor the binding.
- **G2 → K13/T47.** `AgentDetailPage`/`AgentFlowTab` (+ types/mock) still read the vestigial `attached_policy_ids` Set; migrate to scalar `active_policy_id`.
- **C1 → K2.** `create_policy:350` *assigns* a derived id (not a resolve violation); read paths still must resolve.
- **C2 → T13.** `validation_result.platform/cloud_region` is currently *policy*-derived (`validation_service.py:350-356,452-455`); re-source from the agent. Downstream `audit_logger:226/329` + `decisions_service:416` inherit it automatically.

---

## 1. Shared conventions (read once)

### 1.1 Request path
Public REST API Gateway (`/v1/*`, `prod`) → VPC Link → NLB → private ALB → `security-controller` FastAPI. Routes in [`routes.py`](../../src/security-controller/app/api/routes.py).

### 1.2 API Gateway wiring
**Exactly one CDK change** ships in this workstream — the new method `PATCH /v1/policies/{policy_id}/status` (T24). Everything else is **no CDK change**:
- **Needs CDK (the one change):** `PATCH /v1/policies/{policy_id}/status`. The `policies` resource and `{policy_id}` child already exist (`api_stack.py:481,512`, GET/PUT/DELETE). Add a **`status` sub-resource** under `{policy_id}` (`status_res = policy_id_resource.add_resource("status")`) and a PATCH method on it — the contract path is `/{policy_id}/status`, **not** a bare PATCH on `{policy_id}`. Reuse the **mechanism** of the existing `PATCH /v1/sigma-rules/{rule_id}` (`api_stack.py:585`): `add_method("PATCH", create_http_integration(... "/v1/policies/{policy_id}/status", "PATCH" ...), request_parameters={"method.request.path.policy_id": True})`.
- **No CDK (already wired):** attach `POST /v1/agents/{id}/policies` and detach `DELETE /v1/agents/{id}/policies/{policy_id}` are already in `api_stack.py` (`:847-864`, they wrote the vestigial String-Set) — we only change their **backend semantics** (scalar binding), not the gateway.

Re-confirm with `cdk diff` (expect **only** the new PATCH-status method).

### 1.3 Stores touched
| Setting attr | Table | Used by this feature |
|---|---|---|
| `dynamodb_agent_registry_table` | `sentra-agent-registry` | binding (`attached_policy_id` scalar), `cloud_region`, `active_policy_id` enrich |
| `dynamodb_policies_metadata_table` | `sentra-policies-metadata` (GSI `agent-index`, `status-index`) | policy load-by-id, lifecycle status, backfill resolution, S3 content |

### 1.4 Operator identity
All writes (attach/detach/create/update/delete/status) send `X-Operator-Email` from `useCurrentUser().email` (omit when null). Backend records it on `last_updated_by` / audit logs.

### 1.5 Fail-secure invariant (the through-line)
An agent whose bound policy is **missing** or **disabled** has **every tool call DENYed**. Detach (one agent) and Disable (all bound agents) are **halt-the-agent** actions. All confirm copy states this + the blast radius. New DENY reason: `POLICY_DISABLED` (distinct from `POLICY_NOT_FOUND`).

---

## 2. Milestone map

| Milestone | Theme | Tasks | Gate before next |
|---|---|---|---|
| **M0** | Backfill / migration (no-outage cutover) | T10 | Backfill verified; unbound set signed off |
| **M1** | Backend engine — binding + cloud-from-agent | T11–T15 | `pytest` green incl. all-callers + tools-display consistency |
| **M2** | Backend lifecycle + enrich + APIGW | T20–T24 | `set_policy_status`, `active_policy_id`, PATCH wired; `cdk diff` clean |
| **M3** | FE plumbing | T30–T34 | `tsc -b` clean; mock router parity |
| **M4** | Shared UI | T40 | Modal/ConfirmDialog/Toast mounted |
| **M5** | Agent Inventory (attach/detach/update) | T41–T42 | Inventory action states from `active_policy_id` |
| **M6** | Policies tab + editor + detail + FE Set→scalar migration | T43–T47 | create/edit/enable/disable/delete flows; no stale `attached_policy_ids` reads |
| **M7** | Verify / build / deploy | T50–T53 | suites green; deployed; smoke-tested |

> **Type**: 🛑 blocker · 🐞 bug · 🔧 build · ❓ decision · ⏩ deferred. **Status**: ☐ todo · ◐ in-progress · ☑ done.

---

## 3. M0 — Backfill / migration (DO FIRST)

| ID | Task | Type | Pri | Ref | Depends on | Status |
|----|------|------|-----|-----|-----------|--------|
| **T10** | **Backfill `attached_policy_id`** (script, idempotent, no-outage) | 🛑 | P0 | K1/K2/K8 | — | ☐ |

**T10 — detail.** New script `scripts/backfill_agent_bindings.py`.
- **For each agent** in `sentra-agent-registry`: resolve its current governing policy **exactly as the engine resolves it today** — query the **`agent-index` GSI on `sentra-policies-metadata`** for `agent_id == X AND status == 'active'`, `Limit=1` (**N4:** the *policies* table's GSI, not the registry's `status-index`). Take **that policy's stored `policy_id`** — **never** reconstruct `agent-config-{id}` (K2).
- If found → `update_item` SET `attached_policy_id = <stored policy_id>` on the agent. Idempotent (re-runnable; SET is item-level).
- **Non-1:1 handling (K8):**
  - **Agent with no active policy → leave `attached_policy_id` unset** (expected-unbound). Collect into an explicit list. These DENY post-cutover *by design* (e.g. the `*-unsecured` demo agent) — that is **accepted**, not a failure.
  - **Orphan policy (no agent) → ignore.** Still appears in the attach picker for future binding.
- **Verify step:** assert every agent that **had** a resolvable active policy now has a matching `attached_policy_id`; **do NOT** assert "all agents bound." Print the unbound-agent list + orphan-policy list for sign-off.
- **Acceptance:** dry-run prints the plan; live run is idempotent (second run is a no-op); the verify step passes; the unbound set matches the known no-policy agents exactly.

---

## 4. M1 — Backend engine (binding + cloud-from-agent)

| ID | Task | Type | Pri | Ref | Depends on | Status |
|----|------|------|-----|-----|-----------|--------|
| **T11** | Add `cloud_region` to agent registry + seed + migrate | 🔧 | P0 | K3/§4.4 | — | ☐ |
| **T12** | Rewrite `get_agent_policy` — binding resolution + GSI fallback + cloud-from-agent + `POLICY_DISABLED` | 🛑 | P0 | K2/K3/K5/K6/K7 | T10,T11 | ☐ |
| **T13** | Verify all **4 callers** + early cloud stamp before trust-DENY; re-source `validation_result` cloud from agent (C2) | 🛑 | P0 | K6/K9/C2 | T12 | ☐ |
| **T14** | Add `POLICY_DISABLED` to violation taxonomy (+ trust penalty, console enum) | 🔧 | P0 | §4.1-F | T12 | ☐ |
| **T15** | `get_agent_tools` resolves via the **binding** (+ GSI fallback), not the bare GSI (G1) | 🔧 | P0 | K12/§4.1 | T10,T12 | ☐ |

**T11 — `cloud_region` on the agent.**
- Extend `scripts/seed_agents.py` to set `cloud_region` per agent: `sentra`/`bedrock` → `us-east-1`, `azure_foundry` → `centralus` (real region per agent). Add to any agent-create/registry write path.
- Migrate the existing ~5 agents (trivial; a small `update_item` loop or a re-seed).
- **Cross-ref K8:** the seeded agents are all AWS (`sentra`/`bedrock`, us-east-1); the `azure_foundry` branch exists for correctness but **no Azure agent is registered today** (`azure-verification-agent` is an *orphan policy*, not a seeded agent — K8). So in practice this migration sets `us-east-1` on the existing fleet; don't expect an Azure agent row to migrate until one is imported.
- **Acceptance:** every registered agent record has `cloud_region`; `seed_agents.py` is the source of truth.

**T12 — `get_agent_policy(agent_id)` rewrite** in [`policy_engine.py`](../../src/security-controller/app/validators/policy_engine.py). This is the load-bearing change; all four callers go through it.
- **Add registry handle (K5):** in `__init__`, `self.agent_registry = self.dynamodb.Table(settings.dynamodb_agent_registry_table)`. **No CDK/IAM change** (task role already reads the registry — verified; state this in the code comment so no one looks for a permission change).
- **Read the agent once** (`get_item` on the registry): yields `attached_policy_id`, `platform`, `cloud_region`, `cloud_provider`.
- **Resolve the policy:**
  - `attached_policy_id` present → `get_item` the policy by that **stored id** on `sentra-policies-metadata` (K2 — never reconstruct), then S3 content.
  - `attached_policy_id` absent → **fall back to the legacy `agent-index` GSI lookup** (`agent_id`+`status=active`, `Limit=1`) during migration (K1/§2.6). Once backfill is verified, absent → `PolicyNotFoundError` → DENY `POLICY_NOT_FOUND`. (A `BINDING_RESOLUTION_ENABLED` flag is acceptable but the GSI fallback alone suffices.)
  - Policy `status != 'active'` → raise → DENY with **new** `violation_type="POLICY_DISABLED"`.
- **Cloud-from-agent (K3):** the **caller stops reading `platform`/`cloud_region` from the policy**; resolve from the agent record. **Fallback chain (R7):** agent `cloud_region` → policy `cloud_region` → `cloud_provider`-derived default. Never break on a missing field. Keep the policy's cloud fields for audit but treat as non-authoritative.
- **No cross-task cache (K7):** keep resolution **uncached** (registry `get_item` + policy `get_item` by PK + existing S3 load — all cheap). Steady-state is 1 task, but deploys transiently run 2 (`max_healthy_percent=200`) and scale-out is expected — so do **not** build single-process invalidation. If cached, **short fixed TTL** with documented TTL-bounded cross-task staleness — **no** "invalidate on write." State which in a comment.
- **Acceptance (unit):** bound+active → loads policy, resolves the **agent's** cloud; unbound w/ legacy GSI policy → loads via fallback (no spurious DENY); unbound post-backfill → `POLICY_NOT_FOUND`; bound+disabled → `POLICY_DISABLED`; agent missing `cloud_region` → falls back, never errors; binding A's policy to B resolves **B's** cloud + B's cross-cloud deps.

**T13 — callers + early stamp.**
- **All four callers** read the bound policy + agent cloud identity consistently: `validation_service.py:264` (rate-limit/abuse), `policy_engine.py:136` (policy decision), `context_validator.py:185` (cross-cloud deps), `cross_agent_validator.py:110` (cross-agent). Verify each post-change.
- **Early cloud stamp (K9):** `validation_service` returns on a trust-check DENY **before** the policy loads — `platform`/`cloud_region` were `null`. Now that we read the agent up front, **stamp `platform`/`cloud_region` from the agent record before the trust check** so trust-DENY responses + audit logs carry correct cloud identity.
- **Re-source the cloud carrier (C2):** `validation_service.py:350-356,452-455` currently set the response/audit cloud fields from `validation_result.platform/cloud_region` (in-code comments say "policy-derived"). Re-source these from the **agent** and **update the comments**. Downstream `audit_logger.py:226,329` and the stored signal in `decisions_service.py:416` read the carrier, so they inherit the correct value **with no separate change** — but assert it (audit/signal cloud == agent's).
- **Acceptance:** test asserts `context_validator`, `validation_service` (abuse), and `cross_agent_validator` all see the **same** bound policy as `policy_engine`; a trust-DENY response carries non-null **agent-sourced** cloud identity; the persisted audit/signal cloud matches the agent (not the policy).

**T14 — `POLICY_DISABLED` taxonomy.** Add to the backend violation taxonomy with a trust penalty (`-15`, same as `POLICY_NOT_FOUND`) **and** to the console threat-type enum — `ThreatType` in [`web/console/src/types/enums.ts:47`](../../web/console/src/types/enums.ts#L47) (open union; add `'POLICY_DISABLED'` as a surfaced value) so the dashboard labels it instead of falling through to the generic string case. **Acceptance:** a `POLICY_DISABLED` DENY applies the penalty (backend) and renders as a named threat type (FE).

**T15 — `get_agent_tools` honors the binding (K12/G1).** [`agent_service.py:316`](../../src/security-controller/app/services/agent_service.py#L316) (Agent Detail → Tools tab) today queries the `agent-index` GSI directly. Change it to resolve the agent's **bound** `policy_id` (from the registry record), load that policy's `allowed_tools`, and **fall back to the legacy GSI** when `attached_policy_id` is absent (same migration fallback as `get_agent_policy`, §2.6). Keep its existing per-task short-lived cache (K7 caveat — no cross-task invalidation claim). **Acceptance:** bind policy-A to agent-B → `get_agent_tools(B)` returns **A's** `allowed_tools` (the bound policy), not B's GSI-authored policy's; unbound/pre-backfill → GSI fallback (non-empty), no regression.

---

## 5. M2 — Backend lifecycle + enrich + APIGW

| ID | Task | Type | Pri | Ref | Depends on | Status |
|----|------|------|-----|-----|-----------|--------|
| **T20** | `set_policy_status` (enable/disable) — **remove system-403** | 🔧 | P0 | K4/§2.8/§4.3 | — | ☐ |
| **T21** | Attach/detach write the **scalar** binding atomically (`ConditionExpression`) | 🔧 | P0 | §4.2 | T10 | ☐ |
| **T22** | `active_policy_id` enrichment (batch-loaded, no N+1) on `GET /v1/agents[/{id}]` | 🔧 | P0 | §4.4/D | T11 | ☐ |
| **T23** | Keep system-403 in `delete_policy`; confirm `update_policy` allows system edit | 🔧 | P0 | K4/§2.8/C4 | — | ☐ |
| **T24** | Wire `PATCH /v1/policies/{policy_id}/status` in `api_stack.py` | 🔧 | P0 | §4.5 | T20 | ☐ |

**T20 — `set_policy_status`** in [`policy_service.py`](../../src/security-controller/app/services/policy_service.py). New `set_policy_status(policy_id, status, operator_email)`:
- `status ∈ {active, disabled}`; update `status`, `updated_at`, `last_updated_by`; audit-log `ENABLE_POLICY`/`DISABLE_POLICY`.
- **404** on missing policy. **NO `created_by=='system'` 403** (§2.8 — enable/disable allowed on system policies; do **not** mirror delete's guard here).
- Returns `{success, policy_id, status, updated_at}`. New route `PATCH /v1/policies/{policy_id}/status` body `{status}` (mirrors `PATCH /v1/sigma-rules/{rule_id}`), accepts `X-Operator-Email`.
- **Acceptance:** disable→`disabled`, enable→`active`, 404 missing, **no system-403** (assert a `created_by='system'` policy toggles successfully).

**T21 — scalar binding.** In [`agent_service.py`](../../src/security-controller/app/services/agent_service.py):
- `POST /v1/agents/{agent_id}/policies` body `{policy_id}` → validate agent exists (404) + policy exists (404) → single `update_item` SET `attached_policy_id = policy_id` with `ConditionExpression=attribute_exists(agent_id)`. **Rebind-as-replace (E):** already-bound → atomic swap, **not** a 409. Returns `{agent_id, policy_id, status:"attached", attached_at}`.
- `DELETE /v1/agents/{agent_id}/policies/{policy_id}` → `update_item` REMOVE `attached_policy_id` with `ConditionExpression` that the current value **equals** `policy_id`; 404 if agent missing or not bound to that policy. Returns `{agent_id, policy_id, status:"detached"}`.
- The vestigial String-Set `attached_policy_ids` is **left untouched** (no migration); scalar is the source of truth.
- **Acceptance:** attach sets scalar; attach-when-bound **replaces** atomically (no 409); detach clears; detach of a non-bound policy → 404; concurrent double-attach can't interleave (ConditionExpression).

**T22 — `active_policy_id` enrich.** Add `active_policy_id` to `GET /v1/agents` and `GET /v1/agents/{id}` = the agent's `attached_policy_id` **iff** that policy is lifecycle-`active`, else `null`. Operates only on the external agents `list_agents` already returns (K11).
- **Batch (D) — concrete access pattern:** for the list endpoint, do **one `Scan` of `sentra-policies-metadata` with `ProjectionExpression="policy_id, #s"` (`#s`=`status`)** → build a `{policy_id: status}` dict once, then map each agent's `attached_policy_id` through it (`active` → keep, else `null`). **No per-agent `get_item`** (N+1). A `Scan` is the **conscious choice** here (~4 policies, trivial); it is **wrong at scale** — note it for the future GSI/`BatchGetItem` swap. For the single-agent endpoint, one `get_item` on the bound `policy_id` is fine.
- `null` → UI shows **Attach**; non-null → **Detach** + **Update**.
- **Acceptance:** enrichment reflects binding × status; disabling a bound policy flips `active_policy_id` to `null`; list path issues one policy-status load, not N.

**T23 — delete stays protected.** Keep the `created_by=='system'` 403 in `delete_policy` (`policy_service.py:588`). Confirm `update_policy` already allows system edit (it 403s only on `status=='disabled'`, never on `system` — C4); no change needed. **Acceptance:** on a `created_by='system'` policy, **Delete 403s**, **Edit (PUT) succeeds**, **Enable/Disable succeed** (the one divergence: delete protected).

**T24 — APIGW.** Add `PATCH /v1/policies/{policy_id}/status` in [`api_stack.py`](../../cdk/stacks/api_stack.py): create a **`status` sub-resource** under the existing `policy_id_resource` (`:512`) and add the PATCH method on it (not on `{policy_id}` itself — §1.2), reusing the `PATCH /v1/sigma-rules/{rule_id}` mechanism (`:585`) — `create_http_integration` + path param `policy_id: True`. **Acceptance:** `cdk diff` shows **only** this new `status` resource + PATCH method; through-APIGW PATCH reaches the handler.

---

## 6. M3 — Frontend plumbing

| ID | Task | Type | Pri | Ref | Depends on | Status |
|----|------|------|-----|-----|-----------|--------|
| **T30** | Routes: `policyNew` `/policies/new`, `policyEdit` `/policies/:policyId/edit` + helpers; register `/new` before `/:policyId` | 🔧 | P0 | §5 | — | ☐ |
| **T31** | `lib/api/policies.ts` — fix create/update bodies (structured); add `setStatus`; confirm `remove` type | 🐞 | P0 | K10 | — | ☐ |
| **T32** | `lib/query/usePolicies.ts` — add `useCreatePolicy`/`useUpdatePolicy`/`useDeletePolicy`/`useSetPolicyStatus` | 🔧 | P0 | §9 | T31 | ☐ |
| **T33** | `lib/query/useAgents.ts` attach/detach hooks invalidate `agents.list` (not just detail); `lib/api/agents.ts` operator-email header | 🔧 | P0 | §9 | — | ☐ |
| **T34** | `types/api.ts` request types + `active_policy_id` on agent types; mock router/fixtures parity | 🔧 | P0 | §9/§10 | T31 | ☐ |

**T30 — routes.** `routes.ts`: add `policyNew: '/policies/new'`, `policyEdit: '/policies/:policyId/edit'` + helpers `policyNewPath()`, `policyEditPath(id)`. In `router.tsx`, register `/policies/new` **before** `/policies/:policyId` (static before param). **Acceptance:** `/policies/new` and `/policies/x/edit` resolve to the editor; `/policies/x` still resolves to detail.

**T31 — api bodies (K10).** Fix `create`/`update` to send the structured `PolicyCreateRequest`/`PolicyUpdateRequest` (current `{name,content}`/`{content}` is wrong). `update` **omits `version`** (backend auto-bumps only when absent). Add `setStatus(policyId, status)` → `PATCH /policies/{id}/status`. Confirm `remove` return type matches `{success, status:"disabled", disabled_at}`. **Acceptance:** create posts `{schema_version, agent_id, name, version, allowed_tools, policies, ...}`; edit PUT has **no** `version`; `setStatus` hits the new route.

**T32–T34 — hooks/types/mocks.** Mutation hooks with correct invalidation (see flows §7). `types/api.ts`: `PolicyCreateRequest`/`PolicyRule` request types, `active_policy_id: string | null` on agent types, align create/update/delete return types. Mock router + `fixtures.ts`: scalar-binding attach/detach, PATCH status, create/update/delete, `active_policy_id`. **Acceptance:** `tsc -b` clean; mock mode exercises every flow with the same shapes as live.

---

## 7. M4–M6 — UI (shared, Agent Inventory, Policies tab)

| ID | Task | Type | Pri | Ref | Depends on | Status |
|----|------|------|-----|-----|-----------|--------|
| **T40** | Shared UI: `Modal`, `ConfirmDialog`, `Toast` + `ToastProvider` (mounted in `AppLayout`) | 🔧 | P0 | §9 | — | ☐ |
| **T41** | Agent Inventory — Actions column bound to `active_policy_id`; `AttachPolicyModal`; attach/detach/update | 🔧 | P0 | §6.1 | T33,T34,T40 | ☐ |
| **T42** | Confirm copy (verbatim §2.5) + blast-radius bound-agent counts + invalidation | 🔧 | P0 | §2.5 | T41 | ☐ |
| **T43** | Policies tab — New + per-row Edit / Enable-Disable / Delete; system-row gating | 🔧 | P0 | §6.2 | T32,T40 | ☐ |
| **T44** | System-policy UI gating: Delete **disabled** w/ tooltip; Edit + Enable/Disable available | 🔧 | P0 | K4/§2.8 | T43 | ☐ |
| **T45** | `PolicyEditorPage` (create + edit): structured inputs, JSON body + YAML preview, version-omit on edit, 409/403 banners | 🔧 | P0 | §6.3 | T32 | ☐ |
| **T46** | `PolicyDetailPage` — Edit button (disabled w/ "Enable to edit" when disabled) | 🔧 | P0 | §6.4 | T30 | ☐ |
| **T47** | Migrate `AgentDetailPage` + `AgentFlowTab` (+ types/mock) off vestigial `attached_policy_ids` Set → scalar `active_policy_id` (G2) | 🐞 | P0 | K13/§6.1 | T22,T34 | ☐ |

**T40 — shared UI.** `components/ui/`: `Modal.tsx` (focus-trap, ESC, backdrop, `role=dialog`/`aria-modal`), `ConfirmDialog.tsx` (danger/primary variants), `Toast.tsx` + `ToastProvider` mounted in `AppLayout`. **Acceptance:** keyboard-accessible (ESC closes, focus trapped); toasts stack and auto-dismiss.

**T41 — Agent Inventory actions.** Per row `activePolicyId = a.active_policy_id ?? null`; right-aligned **Actions** cell; all buttons `e.stopPropagation()` (row click → detail).
- `null` → **Attach Policy** → `AttachPolicyModal` (lists `usePolicies`, active first). Helper hint (not a block) when chosen policy's `agent_id` differs: "Authored for `<other>` — its allowed tools may not match `<this>`"; matching policy pre-selected (compare `policy.agent_id`, **not** a reconstructed id — K2). "No policy yet? Create for this agent" → `policyNew` prefilled `agent_id` + **auto-attach flag** (on create success the console immediately attaches).
- non-null → **Update Policy** (→ `policyEditPath`, a **global** edit, Flow C) + **Detach Policy** (danger).
- Mutations: `useAttachPolicy` → `POST` (replaces atomically); `useDetachPolicy` → `DELETE`. Invalidate `agents.list` + `agents.detail` + `policies.detail`.
- **Acceptance:** action set matches `active_policy_id`; attach picker behaves; auto-attach-on-create works; row flips after each action.

**T42 — copy + blast radius.** Wire the **verbatim §2.5** copy: Detach (this agent blocked, others unaffected, "re-attach from this row at any time" — R6), Update-shared (when bound count >1), Disable (bound-agent count), Delete (soft, same effect as Disable), Attach success. Editor/Disable confirms show the **bound-agent count**. **Acceptance:** each confirm renders the exact copy with the correct `<agent>`/`<policy>`/`<n>` substitutions.

**T43–T44 — Policies tab.** Header **New Policy** → `policyNew`. Per-row **Actions**: **Edit** (→ `policyEditPath`), **Enable/Disable** toggle, **Delete** (danger); row click → detail, actions `stopPropagation`. `status` color map; disabled rows muted, toggle reads "Enable". **System policies (§2.8):** Edit + Enable/Disable **available**; **Delete disabled** with tooltip "System policies can't be deleted — disable instead" (all seeded policies are `system` today → common case). Disable shows §2.5 confirm with bound-agent count; Enable is direct. Invalidate `policies.list` + `policies.detail` + `agents.list` + `agents.detail` (status flips every bound agent's `active_policy_id`). **Acceptance:** toggle/delete/edit behave; system rows disable only Delete; disable confirm shows blast radius.

**T45 — `PolicyEditorPage`** (one component, mode from route).
- **Structured inputs:** `name` (req); `agent_id` (req, **read-only in edit**); `version` — create: required semver (default `1.0.0`); **edit: omit from PUT** (backend auto-bumps; show read-only "current `1.0.0` → bumps on save").
- **Document editor:** monospace JSON `<textarea>` for `allowed_tools` (≥1), `policies[]` (≥1 rule), optional `platform`/`cloud_region`/`max_calls_per_minute`/`cross_cloud_dependencies`. Live JSON-validity indicator + **read-only YAML preview** via `renderContent`. Side field-help panel (JSON has no comments).
- **Create:** seeded valid skeleton → assemble `{schema_version:"v1", agent_id, name, version, ...parsedBody}` → light client validation → `POST /policies` + `X-Operator-Email` → on success `policyDetailPath(returned id)`. **409 dup** = **server-detected** (do not pre-check by reconstructing an id — K2) → banner "A policy for this agent already exists. Edit it instead." linking to the policy resolved via `GET /v1/policies?agent_id=&status=active`. **Create does NOT bind** (binding model) — unless launched from the Attach modal's "create for this agent" path (then auto-attach).
- **Edit:** prefill from `usePolicyDetail` (flat `PolicyDetailView`), **strip server envelope** (`policy_id, status, created_at, updated_at, created_by, content_hash, s3_key`) + `metadata`/nested-schema. **Edit is global** — show bound-agent count; when >1, require the §2.5 *Update (shared policy)* confirm before save. Save → `PUT /policies/{id}` (version omitted + operator header) → invalidate `policies.*` **and** `agents.list`/`agents.detail`. **System policies ARE editable** (C4 — no special-casing). **403 disabled** → banner "This policy is disabled. Enable it first." + Enable shortcut.
- **Client validation (light — server is source of truth):** JSON parses; `name`/`agent_id` non-empty; `version` semver (create); `allowed_tools` non-empty string array; `policies` non-empty, unique `policy_id` + valid `severity`. Server 400 `VALIDATION_ERROR` surfaced verbatim.
- **Acceptance:** create round-trips to detail; edit omits version (S3 version bumps); 409/403 banners render; system policy edits succeed; invalid JSON blocks submit.

**T46 — `PolicyDetailPage` Edit.** Add **Edit** in the header → `policyEditPath(policyId)`; disabled with tooltip "Enable to edit" when `status=disabled`. **Acceptance:** Edit navigates; disabled when policy disabled.

**T47 — FE off the vestigial Set (K13/G2).** The scalar binding (T21) stops writing `attached_policy_ids`, so every FE consumer of that array goes stale. `AgentInventoryPage.tsx:68,72` is already rebound by T41; **also migrate**:
- [`AgentDetailPage.tsx:42`](../../web/console/src/features/agents/AgentDetailPage.tsx#L42) (`const policyIds = a.attached_policy_ids ?? []`) and [`AgentFlowTab.tsx:27`](../../web/console/src/features/agents/AgentFlowTab.tsx#L27) → read scalar `active_policy_id` (single binding; render 0-or-1 policy, not an array).
- `types/api.ts:242,247` — replace the `attached_policy_ids?: string[]` agent field with `active_policy_id: string | null` (or keep the old field optional/deprecated but stop reading it). `mocks/mockRouter.ts:87` — return `active_policy_id` instead of the hardcoded `attached_policy_ids: ['pol-101']`.
- **DDB attribute stays** (no data migration, §2.4) — this is a **frontend-only** read migration.
- **Acceptance:** after attach/detach, Agent Detail + Flow tabs reflect the **current binding** (not a stale/empty Set); `tsc -b` clean with the type change; mock mode parity.

---

## 8. M7 — Verify / build / deploy

| ID | Task | Type | Pri | Ref | Depends on | Status |
|----|------|------|-----|-----|-----------|--------|
| **T50** | Backend tests (§4.6) — engine, migration/fallback, all-callers, cloud-from-agent, binding, lifecycle, system-policy matrix, enrich | 🔧 | P0 | §4.6/§10 | M1,M2 | ☐ |
| **T51** | Frontend tests (extended mock router, §10) | 🔧 | P0 | §10 | M3–M6 | ☐ |
| **T52** | Gates: `tsc -b` + `npm run build`; controller `pytest`; `cdk diff` (only PATCH-status) | 🔧 | P0 | §10 | T50,T51 | ☐ |
| **T53** | Build+push console + security-controller; deploy PATCH-status method; smoke-test live | 🔧 | P0 | §11 | T52 | ☐ |

**T50 — backend test matrix (§4.6):**
- Engine: bound+active → loads + resolves agent cloud; unbound (post-migration) → `POLICY_NOT_FOUND`; bound+disabled → `POLICY_DISABLED`.
- Migration/fallback (K1): no-`attached_policy_id` but legacy GSI policy → loads via fallback (no spurious DENY); post-backfill, binding path loads the same policy.
- All-callers consistency (K6): `context_validator`, abuse/rate-limit, `cross_agent_validator` see the **same** bound policy as `policy_engine`.
- **Display-path (K12/G1):** `get_agent_tools(B)` after binding A→B returns **A's** `allowed_tools`; pre-backfill falls back to GSI (non-empty).
- **Cloud carrier re-source (C2):** persisted audit log + stored signal carry the **agent's** cloud_region, not the policy's.
- Cloud-from-agent (K3): binding A's policy to B resolves **B's** cloud + B's cross-cloud deps; region fallback (R7) → agent missing `cloud_region` falls back, never errors.
- Binding: attach sets scalar; attach-when-bound replaces atomically; detach clears; 404 not-bound; ConditionExpression prevents concurrent double-write.
- Lifecycle: enable disabled→active; disable→disabled; 404 missing.
- **System-policy matrix (K4/§2.8):** on `created_by='system'` → Enable/Disable **succeed**, Edit (PUT) **succeeds**, Delete **403s** (assert all three).
- Non-1:1 migration (K8): backfill leaves no-policy agent unbound (no error), ignores orphan policy; verify doesn't fail on expected-unbound.
- `active_policy_id` enrichment reflects binding × status; list path batch-loads (no N+1).

**T51 — frontend (extended mock router):** inventory action states from `active_policy_id`; attach picker + helper hint + create-for-agent (auto-attach) branch; detach/disable confirm copy + blast-radius count + invalidation; editor create/edit (structured body, version-omit on edit, 409/403 banners); enable/disable toggle; delete soft-disable; **Agent Detail + Flow tabs read scalar `active_policy_id` (no stale `attached_policy_ids` — K13/G2)**; Tools tab reflects the bound policy (G1).

**T52 — gates:** `tsc -b` + `npm run build` clean; controller `pytest` green; `cdk diff` reviewed (**only** the new PATCH-status method).

**T53 — deploy:** `scripts/build_and_push_image.py` for console + security-controller (`:latest`), `aws ecs update-service --force-new-deployment`; `cdk deploy` the api_stack PATCH-status method; smoke-test: attach→agent governed, disable→bound agents DENY (`POLICY_DISABLED`), enable→restored, system policy delete blocked + edit/toggle work.

---

## 9. Implementation order (recap)

0. **M0 backfill FIRST (K1)** — populate `attached_policy_id` (GSI-resolved) + verify, before the engine reads the binding. Engine ships with GSI fallback so order is safe either way.
1. **M1 engine** — binding resolution (4 callers), cloud-from-agent + fallback + C2 carrier re-source, `POLICY_DISABLED`, early cloud stamp, **`get_agent_tools` honors binding (T15/G1)**.
2. **M2 lifecycle** — `set_policy_status` (no system-403), scalar attach/detach, `active_policy_id` enrich, delete stays protected, wire PATCH-status.
3. **M3 FE plumbing** — routes, fix api bodies, hooks, types, mock router.
4. **M4 shared UI** — Modal/ConfirmDialog/Toast.
5. **M5 Agent Inventory** — actions + AttachPolicyModal + detach + copy.
6. **M6 Policies tab** — New/Edit/Delete/Enable-Disable + PolicyEditorPage + PolicyDetail Edit + **FE Set→scalar migration (T47/G2)**.
7. **M7 verify/build/deploy.**

---

## 10. Known limitations carried from the feature doc (documented, not bugs)

- **Sharing is architecture-ready, not fully realized in MVP.** Cloud identity from the agent (K3) makes one-policy-many-agents safe across clouds; the remaining limit is naming — `policy_id` isn't derivable from `agent_id` (K2), so we always **resolve**, and a created policy is still scoped/named per its agent. True shared-catalog policies = small fast-follow.
- **`policy.agent_id` is authoring origin, not governance attribution (R8).** Under sharing, attribute governance via the **binding**, not `policy.agent_id`; `verify_data_model.py` asserts `policy.agent_id ∈ agents` and any consumer reading `policy.agent_id` for attribution is misleading.
- **Create → attach to govern (then interception).** A created policy governs nothing until attached; a bound+active policy governs *in practice* only once the agent's runtime calls `/v1/validate`.
- **Multi-policy per agent:** scalar→list + deny-wins combine is ready; MVP cap is one binding.
- **Cedar / OPA:** separate future workstream (engine support, then editor). This feature edits the enforced YAML/JSON format only.

---

## 11. Out of scope (tracked elsewhere)
- Cedar/OPA policy support — separate workstream.
- Multi-policy-per-agent binding — fast-follow (architecture ready).
- Bulk attach/detach/enable/disable — not in MVP.
- Shared-catalog neutral-id policies — fast-follow.
