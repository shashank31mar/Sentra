# Feature — Agent Policy Management + Policy Library CRUD + Enable/Disable

**Status:** **Build-ready** — all decisions made. (R1–R8 + N1–N4 folded in; N1 decided §2.8 = enable/disable/edit allowed on `system` policies, delete protected, propagated to §4.3/§6.2/§6.3/§8/§10 — C1–C4 resolved.)
**Owner:** Console (web/console) + Security Controller (src/security-controller)
**Last updated:** 2026-06-10
**Related LLDs:** LLD 21 (API inventory §13), LLD 11 (Policy CRUD), LLD 03 (policy engine)

---

## 1. Summary

Two capability areas, split cleanly across two console tabs:

1. **Agent Inventory → Attach / Detach policy (per-agent binding).**
   Each agent is governed by **at most one** policy, expressed as a **binding** on the agent. Attaching sets the binding; detaching clears it. These affect **only that one agent** — never the policy itself or any other agent. A convenience **Update** deep-link to the policy editor is surfaced on the bound agent, but **editing changes the shared policy globally** (all bound agents) and is treated as a lifecycle action with a blast-radius warning (§2.1, §6.1 Flow C).

2. **Policies tab → Create / Update / Delete + Enable / Disable (policy lifecycle).**
   Lifecycle actions on the policy document itself. Update (edit), Enable/Disable, and Delete all act on the policy **globally** — every agent bound to it is affected (by design).

> **Operator-facing truth (fail-secure):** an agent whose bound policy is missing or disabled has **every tool call DENYed**. Detach (one agent) and Disable (all bound agents) are therefore **halt-the-agent** actions, not permissive ones. All confirm copy states this and the blast radius.

---

## 2. Enforcement model — the binding (read this first)

### 2.1 The two axes (kept strictly separate)
| Axis | Where | Actions | Scope |
|---|---|---|---|
| **Binding** (which policy governs an agent) | Agent Inventory | attach, detach | **one agent** |
| **Lifecycle** (the policy's content + on/off state) | Policies tab (Update also deep-linked from Inventory) | create, **update**, delete, enable, disable | **the policy → all agents bound to it** |

- **Detach ≠ Disable.** Detach removes *one agent's* link (one agent blocked). Disable turns the *policy* off everywhere (all bound agents blocked).
- **Update is a lifecycle action, not a per-agent one.** Editing the policy document changes the single shared policy → **every bound agent** is affected. Agent Inventory offers an *Update* deep-link for convenience, but its effect is global and carries the same bound-agent blast-radius warning as Disable (§2.5).

### 2.2 How the engine resolves a policy (the change we are making)
- **Today (to be replaced):** `PolicyEngine.get_agent_policy(agent_id)` queries the `agent-index` GSI for `agent_id == X AND status == 'active'`, `Limit=1`. It does **not** read any binding. This makes attach/detach cosmetic and forbids sharing.
- **Target:** the engine reads the agent's **binding** (`attached_policy_id`), loads *that* policy by id, and requires it to be lifecycle-`active`. No binding, or bound policy `disabled` → fail-secure DENY (`POLICY_NOT_FOUND` / `POLICY_DISABLED`).

This decouples the policy from the agent, which is what makes policies **shareable** (one policy bound to many agents) and **multi-bindable later** (binding becomes a list + a deny-wins combine rule) without rework.

### 2.3 Cloud identity must move from the policy to the agent (the correctness fix that makes binding safe)
**Verified hole:** a policy document today embeds the *original* agent's `agent_id`, `platform`, and `cloud_region`, and the pipeline reads cloud identity **from the loaded policy**:
- `policy_engine.validate` sets `platform = policy.get("platform")`, `cloud_region = policy.get("cloud_region")` (`:151-152`), stamped onto every result → response + audit log.
- `context_validator._check_cross_cloud_dependencies` loads `get_agent_policy(agent_id)` and enforces the **policy's** `cross_cloud_dependencies`.
- `allowed_tools` and `max_refund_amount` are likewise the policy's (i.e. the original agent's).

So if payments-agent's policy (`bedrock`/`us-east-1`) is bound to telecom-agent (`azure_foundry`/`centralus`), the engine resolves the **wrong cloud** and the **wrong allowed-tools/cross-cloud rules** for telecom — silently mis-governing across clouds. Decoupling the *binding* without decoupling *cloud identity* is only half a fix.

**Resolution (decided): resolve cloud identity from the AGENT record, not the policy.**
- `platform` and `cloud_region` become the **agent's** attributes; the engine reads them from the agent registry, not from the policy.
- The agent registry **already stores `platform` and `cloud_provider`** (`seed_agents.py`), but **does NOT store `cloud_region`** today. So this fix requires **adding `cloud_region` to the agent record** (seed + registry write path) and migrating the existing few agents (trivial at ~5 agents).
- `allowed_tools` and tool-specific limits stay in the policy (they *are* the policy's job) — sharing a policy means "same allowed tools," which is the intended semantics of a shared policy. The thing that must NOT be shared is **cloud identity**, which is per-agent → moved to the agent.
- `get_agent_policy` keeps returning the policy doc; the **caller stops reading `platform`/`cloud_region` from it** and reads them from the agent instead. (Keep the policy fields for backward-compat/audit, but they are no longer authoritative.)
- **The `validation_result.platform`/`cloud_region` carrier is currently *policy*-derived (C2 — verified):** `validation_service.py:350-356,452-455` set the response/audit cloud fields from `validation_result.platform/cloud_region or request.*`, and the in-code comments say "policy-derived values stashed on validation_result." Under cloud-from-agent these must be **re-sourced from the agent** (stamped in `get_agent_policy`/before the trust-DENY, §4.1 R4). Downstream consumers — `audit_logger.py:226,329` and the stored signal in `decisions_service.py:416` — read cloud identity off the request/validation_result/signal, so once the carrier is agent-sourced they inherit the correct value **automatically** (no separate change). Update the "policy-derived" comments so the source of truth is unambiguous.

> **Without this, "shareable" is unsafe across clouds.** With it, a policy is genuinely agent-agnostic for cloud purposes, and binding any policy to any agent resolves that agent's own cloud correctly. This is the change that makes the binding model's headline benefit real.

### 2.4 Single binding per agent (MVP)
- `attached_policy_id` is a **scalar string** on the agent (`null` = unbound). At most one binding.
- Future multi-policy = change scalar → list + add combine rule. No conceptual rework, no data migration of the idea.
- The vestigial String-Set `attached_policy_ids` is left in the table untouched (no migration); the scalar `attached_policy_id` is the source of truth.

### 2.5 Confirm copy (verbatim, fail-secure-accurate)
- **Detach:** "Detach `<policy>` from `<agent>`? **This agent's tool calls will all be blocked (fail-secure) until a policy is attached.** Other agents using this policy are unaffected. **Re-attach from this row at any time to restore governance** (R6)."
- **Update (shared policy, shown when bound count > 1):** "Editing `<policy>` changes it for **all `<n>` agents bound to it**, not just `<agent>`. Continue?"
- **Disable (Policies tab):** "Disable `<policy>`? **Every agent bound to this policy will have all tool calls blocked** until it is re-enabled. (`<n>` agents bound.)"
- **Delete:** "Delete `<policy>`? It is soft-disabled — same blocking effect as Disable, and it stops appearing as active."
- **Attach success:** "`<agent>` is now governed by `<policy>`."

### 2.6 Migration & cutover — backfill the binding FIRST (R1, blocking)
**Verified hole:** no agent has `attached_policy_id` today (`seed_agents.py` sets none; the agent→policy link is *only* the policy's `agent_id` field + the GSI). So the instant the engine starts reading the binding, **every existing agent resolves `null` → `POLICY_NOT_FOUND` → every tool call DENYed** — a fleet-wide outage on deploy. The cutover MUST be ordered and no-outage:

1. **Backfill (before any engine change):** for each agent **that has a policy**, set `attached_policy_id` = its current governing policy id — resolved the way the engine resolves it *today*: the **`agent-index` GSI on the `sentra-policies-metadata` table** (`agent_id`+`status=active` → that policy's stored id; **never reconstructed**, §2.7; **N4:** this is the *policies* table's GSI, not the registry's `status-index`). One-time, idempotent.
2. **Handle the non-1:1 reality (N2 — verified):** the agent and policy sets do **not** map 1:1. Today, some **agents have no policy** (e.g. `security-controller`, the `*-unsecured` demo agent) and some **policies have no agent** (orphan, e.g. `azure-verification-agent`). So:
   - **Agent with no policy → leave `attached_policy_id` null (expected unbound).** It will DENY post-cutover — which is *intended* for the unsecured demo agent, but must be **listed explicitly** as an accepted unbound set, not treated as a failure.
   - **Orphan policy → nothing to bind;** leave as-is. It still appears in the attach picker for future binding.
3. **Verify (corrected):** assert every agent that **had** a resolvable active policy now has a matching `attached_policy_id`; **do not** assert "every agent is bound" (the unbound set above is expected). Log the unbound agents and orphan policies for sign-off.
4. **Cutover behind a fallback:** the engine reads `attached_policy_id`; **if absent, fall back to the legacy `agent-index` GSI lookup** during the transition. Safe even if backfill missed a row; lets the engine roll out independent of the backfill. Remove the fallback once verified. (A flag `BINDING_RESOLUTION_ENABLED` is acceptable but the GSI fallback alone suffices.)

### 2.7 `policy_id` is NOT derivable from `agent_id` — always resolve it (R2, blocking)
**Verified:** `policy_id` is **not** `agent-config-{agent_id}`. `apply_policy.py:116-121` exists precisely because "the stored policy_id format is not deterministic from agent_id alone" (legacy ids carry suffixes like `-policy-v1`; `seed_policies.py` uses `pol-{agent_id}-001`). Hardcoding `agent-config-<id>` "bites every time."

**Rule for this feature:** anywhere we need an agent's policy, **resolve it** via `GET /v1/policies?agent_id={id}&status=active` (or the binding's stored `policy_id`), and **compare by the policy's `agent_id` field** — never by reconstructing the id. This corrects four places that currently assume the derived id:
- the create-409 copy (§6.3) — detect "exists" from the server's 409, not from a reconstructed id;
- the attach-picker "matching agent_id" pre-select (§6.1) — compare `policy.agent_id`, not the id string;
- §8 duplicate-create row;
- §12 naming note.

> **Exception — create *assigns* a derived id; that is not a "resolve" violation (C1 — verified).** `create_policy` (`policy_service.py:350`) mints `policy_id = agent-config-{agent_id}` for **new** policies. This is id **assignment** (and the basis of 409-duplicate detection — a second create for the same agent collides on that PK), distinct from id **resolution** of an arbitrary/legacy policy, which is *not* derivable. So: **newly-created** policies have derivable ids; **legacy/seeded** ones do not — which is exactly why every *read/resolve* path must resolve, never reconstruct. Do not "fix" `:350` to stop deriving; do not assume `:350`'s format when resolving an existing agent's policy.

### 2.8 Seeded policies are `created_by='system'` (N1 — **DECIDED**: enable/disable/edit allowed, delete protected)
**Verified:** `seed_policies_metadata.py:207` sets `created_by = policy.get("created_by", "system")`, and the seed YAMLs are system-authored — so **every policy that exists today is `created_by='system'`**. Both `delete_policy` and the new `set_policy_status` **403 on `created_by=='system'`** (`policy_service.py:588`). Net effect *before this decision*: on the **real deployed data**, **Disable, Enable, and Delete would 403 on every existing policy** — half the Policies tab non-functional. Resolved below.

**DECIDED — (b)-compromise, extended to Edit (C4).** On `created_by='system'` policies:
| Action | On a `system` policy | Mechanism |
|---|---|---|
| **Enable / Disable** | ✅ **Allowed** | **Remove** the `created_by=='system'` 403 from `set_policy_status` |
| **Edit (PUT)** | ✅ **Allowed** | **No change** — `update_policy` already 403s only on `status=='disabled'`, never on `system` (verified). UI exposes Edit on system rows. |
| **Delete** | 🚫 **Protected (403)** | **Keep** the `created_by=='system'` 403 in `delete_policy`. UI disables Delete on system rows with tooltip "System policies can't be deleted — disable instead." |

Rationale: operators can **manage** seeded policies (toggle on/off, fix content) but cannot **destroy** them. This is the only divergence between system and operator-created policies. Every section below (§4.3, §6.2, §6.3, §8, §10) is reconciled to this single rule — the doc speaks with one voice (C1–C3 resolved).

---

## 3. Goals & Non-Goals

### Goals
- Attach / detach / update an agent's policy from **Agent Inventory**, bound to **real enforcement state** (the binding the engine reads).
- Create / update / delete / **enable / disable** policies from **Policies tab**.
- At most one binding per agent (atomic).
- Correct, fail-secure-accurate operator copy with explicit blast radius.
- Operator identity on all writes; correct cache invalidation; accessible UI; mock-mode parity.

### Non-Goals
- **Cedar / OPA support** — explicitly a **separate future workstream** (engine support first, then editor). This feature edits the format the engine actually enforces (structured YAML, with a JSON view).
- No multi-policy-per-agent yet (architecture is ready for it; cap is 1).
- No bulk operations.

---

## 4. Backend changes

### 4.1 Engine reads the binding + resolves cloud from the agent (§2.2, §2.3)
**Centralize the change in `PolicyEngine.get_agent_policy(agent_id)`** so all callers stay consistent (R3):
- **Add an agent-registry table handle to `PolicyEngine` (N3):** it currently holds only `metadata_table` (policies) + `s3_client` — it has **no** registry handle. Add `self.agent_registry = self.dynamodb.Table(settings.dynamodb_agent_registry_table)`. **No CDK/IAM change:** the controller task role already has read on the registry (verified) — state this so no one looks for a permissions change.
- Read the agent record once (registry `get_item`): gives `attached_policy_id`, `platform`, `cloud_region`, `cloud_provider`.
- `attached_policy_id` null → **fall back to the legacy GSI lookup during migration** (§2.6); once backfill is verified, null → `PolicyNotFoundError` → DENY (`POLICY_NOT_FOUND`).
- Load that policy by the bound `policy_id` (direct `get_item` on `sentra-policies-metadata`, then S3) — **the stored id, never a reconstructed `agent-config-{id}`** (§2.7). If `status != 'active'` → DENY with **new** `violation_type="POLICY_DISABLED"`; else return it.
- **Resolve `platform`/`cloud_region` from the AGENT record**, not the policy (§2.3). **Fallback (R7):** if the agent has no `cloud_region` (new/unmigrated agents), fall back to the policy's `cloud_region`, then to a `cloud_provider`-derived default — never break on a missing field.
- **All four *enforcement* callers go through this method (R3):** `validation_service.py:264`, `policy_engine.py:136`, `context_validator.py:185`, `cross_agent_validator.py:110`. Because resolution (binding + cloud-from-agent) lives in `get_agent_policy`, every caller — policy engine, cross-cloud context check, rate-limit/abuse path, cross-agent check — reads the **same** bound policy and the **same** agent cloud identity. Verify each call site after the change.
- **A FIFTH, *display* resolution site exists and must also honor the binding (G1 — verified):** `AgentService.get_agent_tools(agent_id)` (`agent_service.py:316`, powering **Agent Detail → Tools tab**) resolves the policy via the **legacy `agent-index` GSI** (`agent_id`+`status=active`, `Limit=1`) **independently** of `get_agent_policy`. It is not an enforcement path, so it doesn't mis-govern — but after a different policy is bound to the agent, the Tools tab would show the **GSI-authored** policy's tools, **not the bound** policy's → the UI contradicts what is actually enforced. **Fix:** `get_agent_tools` must resolve via the agent's binding (`attached_policy_id`) with the **same GSI fallback** as `get_agent_policy` during migration (§2.6), so the displayed tools always match the enforced policy. (Its in-process cache is per-task and short-lived — same K7/R5 caveat; no cross-task invalidation claimed.)
- **Early cloud stamp (R4):** `validation_service` has a known gap — a **trust-check DENY returns before the policy is loaded**, so `platform`/`cloud_region` are `null` unless the interceptor stamped them. Under cloud-from-agent we already read the agent up front, so resolve and stamp `platform`/`cloud_region` from the agent record **before** the trust check, fixing that gap as a side-benefit. Don't assume the policy path is the only place cloud identity is set.
- **New DENY reason wiring (F):** add `POLICY_DISABLED` to the violation taxonomy with a trust penalty (proposed `-15`, same as `POLICY_NOT_FOUND`) and to the console threat-type enum so the dashboard renders it.
- **Hot-path cost + caching (B, R5):** this replaces one GSI query with one registry `get_item` + one policy `get_item` (by primary key) + the existing S3 load — all cheap. **Do NOT rely on an in-process invalidatable cache:** the controller runs as a **multi-task ECS service**, so a cache on task A is not invalidated by a write hitting task B (the exact Sigma-rule cache problem). **(decided)** keep the binding→policy resolution **uncached** (two PK `get_item`s are inexpensive), or, if cached, use a **short fixed TTL** and accept TTL-bounded cross-task staleness — state which. No cross-task "invalidate on write" is claimed.

### 4.2 Binding endpoints (attach / detach) — reuse existing routes, change semantics, atomic
- `POST /v1/agents/{agent_id}/policies` body `{policy_id}` → **set** `attached_policy_id = policy_id` (scalar).
  - Validate agent exists (404) and policy exists (404).
  - **Rebind-as-replace (E):** if the agent is already bound, **replace** the binding in a single atomic write (no forced detach-first). The UI normally shows Detach when bound, but Attach-when-bound is a safe atomic swap, not a 409.
  - **Atomicity (G):** single `update_item` with a `ConditionExpression` so concurrent attaches can't interleave (e.g. condition on `attribute_exists(agent_id)`; the scalar `SET` is item-level atomic — no read-modify-write race like the old String-Set had).
  - Returns `{agent_id, policy_id, status:"attached", attached_at}`.
- `DELETE /v1/agents/{agent_id}/policies/{policy_id}` → **clear** `attached_policy_id` if it equals `policy_id` (`ConditionExpression` on the current value). 404 if agent missing or not currently bound to that policy. Returns `{agent_id, policy_id, status:"detached"}`.

> These endpoints already exist (they wrote the vestigial set). We repurpose them to write the scalar binding the engine now reads — they are **load-bearing**, not vestigial.

### 4.3 NEW — Lifecycle status endpoint (enable / disable)
`PATCH /v1/policies/{policy_id}/status` body `{status: "active" | "disabled"}` (mirrors the existing `PATCH /v1/sigma-rules/{rule_id}`).
- `active` = enable (the missing re-enable capability); `disabled` = disable (alias of soft-delete).
- `PolicyService.set_policy_status(policy_id, status, operator_email)`: update `status`, `updated_at`, `last_updated_by`; audit-log `ENABLE_POLICY`/`DISABLE_POLICY`; clear cache.
- 404 missing. **No `created_by=='system'` 403** — per §2.8, Enable/Disable are allowed on system policies (do **not** mirror delete here). Accepts `X-Operator-Email`.
- Returns `{success, policy_id, status, updated_at}`.

### 4.4 Agent record carries cloud_region + `active_policy_id` on the response
- **Add `cloud_region` to the agent registry** (§2.3): extend `seed_agents.py` (real region per agent — sentra/bedrock = `us-east-1`, azure_foundry = `centralus`) and any agent-create/registry write path. Migrate the existing ~5 agents.
- **`active_policy_id` on the enrich path:** add `active_policy_id` = the agent's `attached_policy_id` **iff** that policy is lifecycle-`active`, else `null`. Added to `GET /v1/agents` and `GET /v1/agents/{id}`.
  - **Batch (D):** for the list endpoint, load the referenced policies' statuses **once** (single batch/scan of the small policy set) and map by id — do **not** issue one policy lookup per agent (N+1).
  - `null` → UI shows **Attach**; non-null → **Detach** + **Update**.

### 4.5 API Gateway wiring
All `/policies` (POST/PUT/DELETE) and `/agents/{id}/policies` (POST/DELETE) are already wired. **Add one method:** `PATCH /v1/policies/{policy_id}/status` in `api_stack.py` (mirror the sigma-rule PATCH). Re-confirm with `cdk diff`.

### 4.6 Tests
- Engine: bound+active → loads & resolves agent's cloud; unbound (post-migration) → `POLICY_NOT_FOUND` DENY; bound+disabled → `POLICY_DISABLED` DENY.
- **Migration/fallback (R1, §2.6):** agent with **no** `attached_policy_id` but a legacy GSI policy → engine **still loads via fallback** (no spurious DENY); after backfill, the binding path loads the same policy.
- **All-callers consistency (R3):** `context_validator`, abuse/rate-limit (`validation_service`), and `cross_agent_validator` all see the **same** bound policy as `policy_engine`.
- **Display-path consistency (G1):** after binding policy-A to agent-B, `get_agent_tools(B)` returns **A's** `allowed_tools` (the bound policy), not B's GSI-authored policy's; pre-backfill it falls back to the GSI (no empty list).
- **Cloud-from-agent (§2.3):** binding agent-A's policy to agent-B resolves **B's** `platform`/`cloud_region` (not the policy's), and B's cross-cloud deps come out correct. **Region fallback (R7):** agent missing `cloud_region` → falls back to policy value/default, never errors.
- Binding: attach sets scalar; attach-when-bound replaces atomically; detach clears; 404 not-bound; `ConditionExpression` prevents concurrent double-write.
- Lifecycle: enable a disabled policy → active; disable → disabled; 404 missing.
- **Seeded-policy mutability (N1, §2.8 — decided):** on a `created_by='system'` policy, **Enable/Disable succeed**, **Edit (PUT) succeeds**, **Delete 403s**. Assert all three.
- **Non-1:1 migration (N2):** backfill leaves a no-policy agent **unbound** (no error) and ignores an orphan policy; verify step does **not** fail on the expected-unbound set.
- `active_policy_id` enrichment reflects binding × status; list path batch-loads (no N+1).

---

## 5. Frontend — routes

`routes.ts`: add `policyNew: '/policies/new'`, `policyEdit: '/policies/:policyId/edit'` + helpers `policyNewPath()`, `policyEditPath(id)`. In `router.tsx`, register `/policies/new` before `/policies/:policyId`.

---

## 6. Frontend — flows

> **Migrate ALL consumers off the vestigial `attached_policy_ids` Set (G2 — verified).** Three FE surfaces still read the old String-Set array `attached_policy_ids`, which the scalar binding (§2.4) **no longer writes** — so post-cutover they show stale/empty policy info:
> - `AgentInventoryPage.tsx:68,72` — rebound to `active_policy_id` by this section (✓ in scope below).
> - **`AgentDetailPage.tsx:42`** and **`AgentFlowTab.tsx:27`** — **must also** switch from `attached_policy_ids` to the scalar `active_policy_id` (single binding). Update `types/api.ts:242,247` (the `attached_policy_ids?: string[]` field) and `mocks/mockRouter.ts:87` accordingly. Leave the DDB attribute in place (no data migration, §2.4); just stop the **frontend** reading it.

### 6.1 Agent Inventory — Actions column
Per row, `activePolicyId = a.active_policy_id ?? null`. Add a right-aligned **Actions** cell; all action buttons call `e.stopPropagation()` (row click still → agent detail).
- `activePolicyId === null` → **Attach Policy**.
- else → **Update Policy** (→ editor) + **Detach Policy** (danger).

#### Flow A — Attach (set the agent's binding)
1. **Attach Policy** → `AttachPolicyModal`.
2. Modal lists policies (`usePolicies`, active first). The operator picks one.
   - **Helper hint (not a block):** if the chosen policy's `agent_id` differs from this agent, show "Authored for `<other agent>` — its allowed tools may not match `<this agent>`." The policy whose `agent_id` matches is shown first/pre-selected.
   - **No policy yet for this agent?** Offer "Create a policy for this agent" → `policyNew` prefilled `agent_id` **and flagged to auto-attach**. On successful create the console **immediately attaches** the new policy to this agent (sets the binding), so the agent is governed without a second manual step. (Plain create — from the Policies tab — does **not** bind; see §6.3/§12.)
3. Confirm → `useAttachPolicy(agentId).mutate(policyId)` → `POST /agents/{id}/policies` (sets the binding; **replaces** any existing binding atomically — §4.2).
4. Success: toast "`<agent>` is now governed by `<policy>`."; invalidate `agents.list`, `agents.detail(agentId)`, `policies.detail(policyId)`. Row flips to Detach/Update.
5. Errors: 404 / generic → toast; modal stays open.

> The picker is intentional and safe: attach only writes **this agent's** binding. It never changes the policy's status or any other agent. (This is why the binding model was chosen over a status-flip model.)

#### Flow B — Detach (clear the agent's binding)
1. **Detach Policy** → `ConfirmDialog` with the §2.5 detach copy (this agent blocked; others unaffected).
2. Confirm → `useDetachPolicy(agentId).mutate(activePolicyId)` → `DELETE /agents/{id}/policies/{policyId}`.
3. Success: toast; invalidate `agents.list` + `agents.detail` + `policies.detail`. Row flips to Attach.
4. Errors: 404 / generic. Dialog closes on success only.

#### Flow C — Update (from inventory) — a **global** edit, surfaced here for convenience
**Update Policy** → `navigate(policyEditPath(activePolicyId))` → editor (edit mode). **This is a lifecycle action, not a per-agent one:** editing changes the *shared* policy, so **every agent bound to it is affected**. The editor shows the bound-agent count and, when >1, requires the §2.5 *Update (shared policy)* confirm before save. On save it invalidates `policies.*` **and** `agents.list`/`agents.detail` (the content changed for all bound agents).

### 6.2 Policies tab — list actions + status
- Header gains **New Policy** → `policyNew`.
- Each row gains an **Actions** cell: **Edit** (→ `policyEditPath`), **Enable/Disable** toggle, **Delete** (danger). Row click → detail; actions `stopPropagation`.
- **System policies (§2.8):** Edit and Enable/Disable are **available**; **Delete is disabled** with tooltip "System policies can't be deleted — disable instead." (All seeded policies are `created_by='system'` today, so this is the common case.)
- `status` shown with the existing color map; a `disabled` policy renders muted and its toggle reads "Enable".

#### Flow D — Enable / Disable
- Toggle → `useSetPolicyStatus().mutate({policyId, status: next})` → `PATCH /policies/{id}/status`.
- **Disable** shows a confirm with the §2.5 disable copy including **how many agents are bound** (blast radius). **Enable** is direct.
- Invalidate `policies.list` + `policies.detail` + `agents.list` + `agents.detail` (status change flips every bound agent's `active_policy_id`).

#### Flow E — Delete (soft)
- **Delete** → `ConfirmDialog` (§2.5 delete copy) → `useDeletePolicy().mutate(id)` → `DELETE /policies/{id}`.
- Success: toast; invalidate list + detail + agents. Row stays, shows `disabled`.
- **`created_by='system'` (§2.8): Delete is the one protected action** — the button is disabled in the UI; if reached, backend 403 → "System policies can't be deleted — disable instead." (Enable/Disable/Edit on system policies are allowed.)

### 6.3 Policy Editor (create + edit) — `PolicyEditorPage`
One component, mode from route. **Fix the api client** to send the structured document (current `{name,content}`/`{content}` bodies are wrong vs the backend `PolicyCreateRequest`/`PolicyUpdateRequest`).

**Structured inputs (one source of truth per field):**
- `name` (req)
- `agent_id` (req; **read-only in edit**)
- `version`:
  - **Create:** required, semver (default `1.0.0`).
  - **Edit:** **omit `version` from the PUT** so the backend auto-increments (it only auto-bumps when version is absent; sending the prefilled value would overwrite the same S3 version and break audit/rollback). Show it read-only: "current `1.0.0` → bumps on save."

**Document editor:** monospace `<textarea>` (JSON) for `allowed_tools` (≥1), `policies[]` (≥1 rule), optional `platform`/`cloud_region`/`max_calls_per_minute`/`cross_cloud_dependencies`. Live JSON-validity indicator + **read-only YAML preview** via `renderContent`. Side "field help" panel documents required shapes (JSON has no comments).

**Create:** editor seeded with a valid skeleton. Submit assembles `{schema_version:"v1", agent_id, name, version, ...parsedBody}` → light client validation → `POST /policies` with `X-Operator-Email`. On success → `policyDetailPath(returned policy_id)`. 409 dup (**server-detected** — do not pre-check by reconstructing an id, §2.7) → banner "A policy for this agent already exists. Edit it instead." + link to that policy resolved via `GET /v1/policies?agent_id=&status=active`.
> **Create does NOT bind under the binding model.** A created policy governs **nothing** until it is **attached** to an agent (Agent Inventory). When create is launched from the Attach modal's "create for this agent" path (§6.1), the console **auto-attaches** on success; a plain create from the Policies tab leaves the operator to attach it from Agent Inventory.

**Edit:** prefill from `usePolicyDetail` (the flat `PolicyDetailView`). Seed the editor with the document body, **stripping server-owned envelope** (`policy_id, status, created_at, updated_at, created_by, content_hash, s3_key`) and the `metadata`/nested-schema fields. **Edit is global** — show the **bound-agent count**; when >1, require the §2.5 *Update (shared policy)* confirm before save. Save → `PUT /policies/{id}` (version omitted; + operator header), then invalidate `policies.*` **and** `agents.list`/`agents.detail` (content changed for every bound agent). **`created_by='system'` policies ARE editable** (§2.8 / C4 — `update_policy` only 403s on `disabled`, never on `system`); no special-casing needed. 403 disabled → banner "This policy is disabled. Enable it first." with an Enable shortcut.

**Client validation (light — server is source of truth):** JSON parses; `name`/`agent_id` non-empty; `version` semver (create); `allowed_tools` non-empty string array; `policies` non-empty with unique `policy_id` + valid `severity`. Server 400 `VALIDATION_ERROR` surfaced verbatim as a banner.

### 6.4 PolicyDetailPage — Edit button
Add **Edit** in the header → `policyEditPath(policyId)`. Disabled with tooltip "Enable to edit" when `status=disabled`.

---

## 7. API contract reference (as the console calls them)

```
# Binding (Agent Inventory) — engine reads what these write
POST   /v1/agents/{agent_id}/policies        body { policy_id }      → 200 { agent_id, policy_id, status:"attached", attached_at }   (404; replaces existing binding atomically)
DELETE /v1/agents/{agent_id}/policies/{policy_id}                    → 200 { agent_id, policy_id, status:"detached" }                (404 not bound)

# Lifecycle (Policies tab)
PATCH  /v1/policies/{policy_id}/status  (NEW)  body { status }       → 200 { success, policy_id, status, updated_at }                (404; NO system-403 — §2.8)
POST   /v1/policies        (X-Operator-Email)  body PolicyCreateRequest → 201 { policy_id, version, s3_key }                         (400 / 409 dup)
PUT    /v1/policies/{id}    (X-Operator-Email)  body PolicyUpdateRequest (OMIT version → auto-bump) → 200                            (400 / 403 disabled / 404)
DELETE /v1/policies/{id}                                             → 200 { success, status:"disabled", disabled_at }               (404 / 403 system)

# Agent response gains:
GET /v1/agents , /v1/agents/{id}  → each agent includes active_policy_id: string | null
```

`PolicyCreateRequest`: `{schema_version:"v1", agent_id, name, version:"1.0.0", allowed_tools:[≥1], policies:[PolicyRule ≥1], description?, platform?, cloud_region?, allowed_agents?, cross_cloud_dependencies?, max_calls_per_minute?}`. `PolicyRule`: `{policy_id, name, severity, action?, rule?, description?, enabled?, ...}`.

---

## 8. Edge cases

| Case | Handling |
|---|---|
| Detach the agent's policy | Only **this agent** blocked next validation. Confirm copy states it; others unaffected. |
| Disable a shared policy | **All bound agents** blocked. Confirm copy shows bound-agent count (blast radius). |
| Update (edit) a shared policy | **All bound agents** get the new content. Editor shows bound-agent count; §2.5 confirm when >1. Edit is a lifecycle action even when reached from Agent Inventory (Flow C). |
| Create a policy | Governs **nothing** until attached (binding model). "Create for this agent" (§6.1) auto-attaches; plain create does not. |
| Agent has no `attached_policy_id` (pre/mid-migration) | Engine **falls back to the legacy GSI** lookup (§2.6) → no outage. Post-backfill, null → `POLICY_NOT_FOUND` DENY. |
| Agent missing `cloud_region` (new/unmigrated) | Engine falls back to the policy's region, then a `cloud_provider`-derived default (R7) — never breaks. |
| Attach a policy authored for another agent | Allowed (binding is generic; **cloud identity resolves from the target agent**, §2.3, so no cross-cloud mis-governance); helper hint warns *allowed-tools* may differ; matching policy pre-selected. |
| Agent has no policy yet | Attach modal offers "Create a policy for this agent" → editor prefilled. |
| Attach when already bound | UI shows Detach when bound; a direct re-attach **replaces** the binding atomically (no 409). |
| Edit a disabled policy | 403 → banner + Enable shortcut. |
| Edit version unchanged | Handled: edit omits `version` → backend auto-bumps. Never same-version overwrite. |
| Create duplicate (server 409 — an active policy for this agent already exists) | 409 → banner + "Edit it instead", linking to the existing policy resolved via `GET /v1/policies?agent_id=&status=active` (never a reconstructed id, §2.7). |
| Enable/Disable/Edit a `created_by='system'` policy | **Allowed** (§2.8): `set_policy_status` loses its system-403; `update_policy` already allows it. Works on all seeded policies (which are all `system` today). |
| Delete a `created_by='system'` policy | **Protected** (§2.8): UI disables Delete on system rows; backend 403 → "System policies can't be deleted — disable instead." |
| Invalid JSON in editor | Client blocks submit; inline parse error. |
| Concurrent writes | Buttons disabled while `isPending`; `http.ts` handles 401 re-auth. |

---

## 9. Files to build / change

**New shared UI** (`components/ui/`): `Modal.tsx` (focus-trap, ESC, backdrop, `role=dialog`/`aria-modal`), `ConfirmDialog.tsx` (danger/primary), `Toast.tsx` + `ToastProvider` (mounted in `AppLayout`).

**New feature files:** `features/agents/AttachPolicyModal.tsx`, `features/policies/PolicyEditorPage.tsx`.

**Changed frontend:**
- `AgentInventoryPage.tsx` — Actions column bound to `active_policy_id`; attach/detach/update; drop `attached_policy_ids` read (G2).
- **`AgentDetailPage.tsx` + `AgentFlowTab.tsx` — migrate off `attached_policy_ids` (Set) to scalar `active_policy_id` (G2, §6.1).**
- `PolicyLibraryPage.tsx` — New Policy + per-row Edit / Enable-Disable / Delete.
- `PolicyDetailPage.tsx` — Edit button.
- `lib/api/policies.ts` — fix `create`/`update` bodies (structured); add `setStatus`; confirm `remove` type.
- `lib/query/usePolicies.ts` — add `useCreatePolicy`, `useUpdatePolicy`, `useDeletePolicy`, `useSetPolicyStatus`.
- `lib/query/useAgents.ts` — attach/detach hooks invalidate `agents.list` (not just detail).
- `lib/api/agents.ts` — operator-email header helper for writes.
- `app/routes.ts` + `router.tsx` — new routes.
- `types/api.ts` — `PolicyCreateRequest`/`PolicyRule` request types; `active_policy_id` on agent types; align create/update/delete return types.
- `mocks/mockRouter.ts` + `fixtures.ts` — attach/detach (scalar binding), PATCH status, create/update/delete, `active_policy_id`.

**Changed backend:**
- **Migration/backfill script (R1, do FIRST):** set `attached_policy_id` per agent from its `agent-index`-GSI-resolved active policy; **skip agents with no policy (expected unbound) and orphan policies** (N2, §2.6); verify (don't assert all-bound); idempotent.
- **`PolicyEngine` gains an agent-registry table handle (N3)** — `settings.dynamodb_agent_registry_table`; no CDK/IAM change (task role already reads it).
- **Seeded-policy mutability (N1, §2.8 — decided):** **remove** the `created_by=='system'` 403 from `policy_service.set_policy_status` (enable/disable allowed); **keep** it in `delete_policy` (delete protected); `update_policy` unchanged (system edit already allowed). UI disables only **Delete** on system rows.
- `app/validators/policy_engine.py` — `get_agent_policy` resolves via the agent's binding with **GSI fallback during migration** (§2.6); loads by the **stored** `policy_id` (§2.7); **reads `platform`/`cloud_region` from the agent record with policy→default fallback** (§2.3/R7); stamps cloud identity **before the trust check** (R4); adds `POLICY_DISABLED` DENY.
- **All four `get_agent_policy` callers go through the updated method (R3)** — `validation_service.py:264`, `policy_engine.py:136`, `context_validator.py:185`, `cross_agent_validator.py:110`. Verify each reads the bound policy + agent cloud identity consistently (cross-cloud deps, rate-limit, cross-agent).
- `app/services/agent_service.py` — write scalar binding on attach/detach with `ConditionExpression` (§4.2), **replacing the existing String-Set `attached_policy_ids` write at `:224-258`**; add `active_policy_id` (batch-loaded) to enrich (§4.4); **`get_agent_tools` (`:316`) resolves via the binding + GSI fallback, not the bare GSI (G1, §4.1).**
- `app/services/policy_service.py` — `set_policy_status` (§4.3).
- `app/api/routes.py` — `PATCH /policies/{id}/status`; ensure attach/detach + status carry `X-Operator-Email`.
- `scripts/seed_agents.py` + registry write path — add `cloud_region` per agent (§4.4); migrate existing agents.
- Violation taxonomy + console threat-type enum — add `POLICY_DISABLED` (§4.1 / F).
- `cdk/stacks/api_stack.py` — wire the new PATCH-status method.
- Tests per §4.6.

**Operator identity:** create/update/delete/status send `X-Operator-Email` from `useCurrentUser().email` (omit when null).

---

## 10. Testing plan

**Frontend (extended mock router):** inventory action states from `active_policy_id`; attach picker + helper hint + create-for-agent branch; detach/disable confirm copy + blast-radius count + invalidation; editor create/edit (structured body, version-omit on edit, 409/403 banners); enable/disable toggle; delete soft-disable.
**Backend:** engine binding resolution (bound+active / unbound→GSI-fallback / bound+disabled); migration backfill incl. non-1:1 (N2); all-4-callers consistency (R3); attach **replaces** (no 409) + detach 404; `set_policy_status` 404 + **no system-403** (§2.8); `delete_policy` **keeps** system-403; `update_policy` allows system edit (C4); `active_policy_id` enrichment; regressions on create/update/delete.
**Gates:** `tsc -b` + `npm run build` clean; controller `pytest` green; `cdk diff` reviewed (expect only the new PATCH-status method).

---

## 11. Implementation order

0. **Backfill FIRST (R1):** populate `attached_policy_id` on all agents (GSI-resolved) + verify — *before* the engine reads the binding. Engine ships with GSI fallback (§2.6) so order is safe either way.
1. **Backend:** engine binding resolution (all 4 callers, cloud-from-agent + fallback, `POLICY_DISABLED`) + attach/detach scalar binding + `set_policy_status` endpoint + `active_policy_id` enrich + tests; wire APIGW PATCH-status.
2. **FE plumbing:** routes, fix policy api bodies, mutation hooks (incl. `useSetPolicyStatus`), invalidation fixes, operator header, mock router.
3. **Shared UI:** Modal, ConfirmDialog, Toast.
4. **Agent Inventory:** actions + AttachPolicyModal + detach.
5. **Policies tab:** New / Edit / Delete / Enable-Disable + PolicyEditorPage.
6. **PolicyDetailPage:** Edit button.
7. Verify (tsc/build/pytest), build+push console + security-controller, deploy the PATCH-status method (`cdk diff`/deploy).

---

## 12. Known limitations (documented, not bugs)

- **Sharing is architecture-ready, not fully realized in MVP.** With cloud identity resolved from the agent (§2.3), binding one policy to multiple agents is now **safe across clouds**. The remaining limit is naming: the stored `policy_id` is **not** derivable from `agent_id` (legacy/varied formats — §2.7), so we always **resolve** an agent's policy rather than reconstruct it, and a policy created for an agent is still scoped/named per that agent. True many-agents-one-policy (shared catalog policies with neutral ids) is a small fast-follow. **Frame to operators:** the binding mechanics ship now; broad reuse of a single named policy is the follow-on.
- **A shared policy's embedded `agent_id` is authoring-origin, not governance attribution (R8).** If policy P (`agent_id=A`) is bound to agent B, P's document still reads `agent_id=A`. Governance is the **binding**, not `policy.agent_id`. Treat `policy.agent_id` as display/origin only; note `verify_data_model.py` asserts `policy.agent_id ∈ agents`, and any audit/attribution consumer reading `policy.agent_id` will be misleading under sharing — attribute governance via the agent/binding, not the policy field.
- **Create → attach to govern (then interception):** under the binding model, creating a policy governs **nothing** until it is **attached** to an agent. A bound+active policy then only governs *in practice* once the agent's runtime actually calls `/v1/validate` — true for already-integrated agents; for newly imported agents it depends on the interception/import path.
- **Multi-policy per agent:** architecture is ready (scalar → list + deny-wins combine), but the MVP cap is one binding per agent.
- **Cedar / OPA:** separate future workstream (engine support, then editor). This feature edits the enforced YAML/JSON format only.
- **`§5.2`-style single-active guard is not needed** under the binding model — governance is the *binding*, not "the one active policy for an agent," so there are no sibling active policies to reconcile.
