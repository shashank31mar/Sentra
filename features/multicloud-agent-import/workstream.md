# Workstream — Multi-Cloud Agent Import (build spec)

**Version**: 1.3 (polish pass 2: T09 deps include T04b explicitly; T07 delete-propagation note)
**Last Updated**: 2026-06-11
**Status**: IMPLEMENTED (M0a–M0d code complete; flag defaults OFF, awaiting the live write-freeze cutover)

> **Implementation status (2026-06-11).** All of M0a–M0d is built behind
> `TENANCY_V2_ENABLED` (default **off** → byte-identical v1 path). Gates met:
> controller `pytest` green flag-off **and** flag-on (new `tests/test_tenancy_v2.py`),
> CDK tests green, `cdk synth` shows exactly the four new `*-v2` tables. Live steps
> (bulk copy, write-freeze flip, prod verify) are the [cutover-runbook](./cutover-runbook.md).
>
> **Two deviations from this spec, made deliberately and verified:**
> 1. **validation-signals-v2 base PK is the composite `tenant_session_id`**
>    (`{tenant}#{session_id}`), **not** bare `tenant_id` as §1.3 states. §1.3 and
>    §0.1 contradicted each other; a `tenant_id`-only PK would break the hot
>    `Query(session_id, sk begins_with)` read path and create a tenant-wide hot
>    partition (`sk` already occupies the SK, so `session_id` can't be the SK).
>    The composite PK preserves the access pattern + the LLD 17 SK format and
>    still isolates tenants.
> 2. **`agent-updated-index` has ONE app reader, not zero** (T2/§0.1 claimed 0):
>    `session_manager.get_agent_session_stats` queries it. It was updated to the
>    composite `tenant_agent_id` key like the other agent-keyed GSIs.
>
> Central switchboard: [`app/utils/tenancy.py`](../../src/security-controller/app/utils/tenancy.py)
> (runtime) + [`scripts/_tenancy.py`](../../scripts/_tenancy.py) (seed/query tooling).
**Contract reference**: [`feature.md`](./feature.md) (the feature doc is the *decision record*; this doc is the *build spec* — exact tables, keys, code paths, and acceptance per task). Related: best-practices §11 (cloud accounts), §12 (LLD 17 signal store), LLD 21 (API inventory).

> **Scope of v1.0:** this spec covers **P0a — the tenancy migration only**, because the locked decision (feature §16) is *migrate first, before any new feature code*. Building inventory/governance on the flat schema and migrating afterwards doubles the work; doing tenancy first means every new table (`connections`, `discovery-cache`, `credentials`) is **born tenant-scoped**. P0b (AWS inventory) and P1 (governance + JWT identity) get their own spec once M0 lands. The forward map is §6.
>
> **The single most dangerous fact:** the validate hot path resolves an agent's policy through `policies-metadata.agent-index` (`policy_engine.get_agent_policy`). The instant that GSI's key changes to `tenant_id#agent_id`, **every caller that still queries by bare `agent_id` resolves no policy → `POLICY_NOT_FOUND` → fleet-wide DENY** (the same fail-secure trap as the policy-management workstream). M0 ships behind the `TENANCY_V2_ENABLED` flag with a write-freeze cutover so reads and writes flip together.

---

## 0. Critical callouts — verified against code

Verified against `cdk/stacks/storage_stack.py`, `cdk/cdk_constructs/signal_store_table_construct.py`, `src/security-controller`, `scripts`.

| # | Severity | Issue | Evidence | Action |
|---|----------|-------|----------|--------|
| **T1** | **Blocker** | **`agent-index` is on the validate hot path.** `get_agent_policy` queries `policies-metadata` GSI `agent-index` (PK `agent_id`) with a `status='active'` filter. Change the GSI key without updating the caller → `POLICY_NOT_FOUND` → DENY on every tool call. | `policy_engine.py:70` | Composite PK `tenant_id#agent_id`; update caller + flip behind flag (M0/T03,T05). |
| **T2** | **Blocker** | **Three GSIs change PK — every reader must compute the composite key.** (a) `agent-index` → `tenant_id#agent_id` (**×4**: `policy_engine:71`, `agent_service:350,631`, `policy_service.query_policies:118`; `create_policy` is **not** one — `get_item` by `policy_id`); (b) `decision-date-timestamp-index` → `tenant_id#decision_date` (**×1**: `decisions_service:271` → **`GET /v1/decisions` regresses to empty** if missed); (c) `agent-updated-index` → `tenant_id#agent_id` (**0 app readers** — sessions use `scan`+filter, see T8 — document, don't hunt for a caller). | grep `IndexName=`; `decisions_service.py:271` | Centralized composite-key builder; update readers across **all three** GSIs (T05). |
| **T3** | **Blocker** | **Session-context is agent-owned and currently un-tenanted.** PK `session_id`, GSI `agent-updated-index` (PK `agent_id`). Left flat, one tenant's sessions are queryable by another. §14.2 named only 3 tables; this is the **4th**. | `storage_stack.py:154-177` | Tenant-scope it in the same migration (T02/T04). |
| **T4** | **High** | **Signal store has a LLD 17-locked writer contract.** PK `session_id`, SK `sk` (`request_id#timestamp_ms#source`), GSIs `agent-timestamp` (PK `agent_id`) + `decision-date` (PK `decision_date`, a writer-populated attribute). Adding `tenant_id` touches `signal_store_writer` + both GSIs + the `_isoformat_ms_z`/`decision_date` logic. | best-practices §12; `signal_store_table_construct.py:50-90` | Tenant-scope deliberately; keep SK format byte-identical (T04/T06). |
| **T5** | **High** | **Base tables RETAIN; demo tables DESTROY.** `agent-registry`, `policies-metadata`, `validation-signals` are `RemovalPolicy.RETAIN`; `session-context` is `DESTROY`. `*-v2` tables inherit the same policy so rollback keeps the originals. | `storage_stack.py:97,409,526; :165` | New `*-v2` tables carry matching removal policy; **never** delete `*-v1` until cutover signed off (T01/T07). |
| **T6** | **Medium** | **Seed/maintenance scripts also hit these GSIs.** `seed_agents.py:344` (registry `status-index`), `seed_policies_metadata.py:390`, `query_helpers.py` (multiple). They write/read `*-v1` shapes. | grep `status-index`/`agent-index` | Scripts must target v2 + write `tenant_id` post-cutover, or re-seeding silently re-creates flat rows (T08). |
| **T7** | **High** | **Rolling deploy runs old-flag + new-flag tasks concurrently.** `desired_count=1` today (not ≥2), so the at-rest "stale flag on a sibling task" race doesn't occur — but `min_healthy_percent=50`/`max_healthy_percent=200` mean a `--force-new-deployment` flag flip runs **old and new tasks together** until the new deployment stabilizes → some requests hit v1, some v2, mid-rollout. | `compute_stack.py:1566-1568` | Read the flag per-request (no per-process latch) **and keep the write-freeze until the new deployment fully stabilizes** (old tasks drained), not just until the flag env is set (T09). |
| **T8** | **Blocker** | **Unscoped `scan()`s leak every tenant.** Base-table PK becomes `tenant_id`, but 8 scans return all rows regardless: `agent_service.list_agents` (:133,137 — `GET /v1/agents`, discovery read-model, cloud-KPI), `discovery_service._scan_all` (:69 — the whole discovery/import surface), `policy_service.list_policies` (:141 fallback), `session_manager` ×5 (:585,682,703,731,754 — session counts, trust aggregation). A GSI-only isolation test (naïve T10) **passes while these leak.** | grep `.scan(` | Each scan → tenant `Query` (or at minimum a `tenant_id` `FilterExpression`); enumerated in T04b; T10 exercises these endpoints. |
| **T9** | **Blocker** | **Base-table `get_item`s pass only the old single key → `ValidationException` post-migration.** PK becomes `tenant_id`+`<key>`, but every `get_item` passes one key: `policy_validator._agent_exists` (:80 `agent_id` — **breaks policy creation**; also hardcodes `Table('sentra-agent-registry')` in `__init__`, no resolver), `agent_service.get_agent/attach/detach` (:288,229,250 `agent_id`), `agent_service:232`/`policy_service.get_policy:196` (`policy_id`), `session_manager` (:83,115 `session_id`). | grep `get_item(` | Add `tenant_id` to every `get_item` Key + route through the table-resolver (T04b). |

### 0.1 Complete call-site inventory (the full isolation surface — verified by grep)

Every reader of the four migrated tables. **The PK change hits `scan`, `get_item`, *and* GSI queries — not just the GSI.** Each row is a checkbox for T04b/T05; the migration is not done until all are ✅.

**`sentra-agent-registry`** (PK `agent_id` → `tenant_id` + `agent_id`)
- `scan` — `agent_service.list_agents:133,137`; `discovery_service._scan_all:69` → tenant `Query`/filter
- `get_item({agent_id})` — `policy_validator._agent_exists:80` (⚠️ also hardcoded `Table(...)`); `agent_service.get_agent:288`, `attach_policy:229`, `detach_policy:250` → add `tenant_id`
- GSI `status-index` — **no app reader** (scripts only, T08)

**`sentra-policies-metadata`** (PK `policy_id` → `tenant_id` + `policy_id`)
- `scan` — `policy_service.list_policies:141` (filterless fallback) → tenant filter
- `get_item({policy_id})` — `agent_service:232`; `policy_service.get_policy:196` → add `tenant_id`
- GSI `agent-index` (→ `tenant_id#agent_id`) — `policy_engine.get_agent_policy:70`; `agent_service:349,630`; `policy_service.query_policies:117`
- GSI `status-index` (→ `tenant_id` + `status`) — `policy_service:129`

**`sentra-session-context`** (PK `session_id` → `tenant_id` + `session_id`)
- `scan` — `session_manager:585,682,703,731,754` (with `Attr('agent_id')`/quarantine filters) → tenant filter
- `get_item({session_id})` — `session_manager:83,115` → add `tenant_id`
- GSI `agent-updated-index` — **0 app readers** (document only)

**`sentra-validation-signals`** (PK `session_id` → `tenant_id` + `session_id`; SK `sk` unchanged)
- writes — `signal_store_writer` (T06)
- GSI `decision-date-timestamp-index` (→ `tenant_id#decision_date`) — `decisions_service:271` (`GET /v1/decisions`)
- GSI `agent-timestamp-index` (→ `tenant_id#agent_id`) — **0 app readers** (re-grep confirmed: `decisions_service.query(` only hits decision-date at `:284`/`:535`; `agent-timestamp` has zero matches app-wide). CDK still creates it with the composite key so **writes project correctly** (T01/§1.3) — but there is **no T05 reader to update**.

> **Out of this surface:** `sigma_rules_metadata` (`sigma_rules_service.py` scan `:244`, get_item `:309`) and `tool_registry` get_items (`policy_validator._tool_exists:89`, `agent_service.get_agent_tools:388`) — those tables aren't tenant-scoped in M0.

---

## 1. Shared conventions

### 1.1 Tenant key design (locked)
- **Base tables:** new PK `tenant_id` (S), SK = the current PK attribute (`agent_id` / `policy_id` / `session_id`). Gives natural `Query(tenant)` isolation and exact `get_item(tenant_id, entity_id)`.
- **Agent-keyed GSIs** (`agent-index`, `agent-updated-index`, signal `agent-timestamp`): PK becomes the **composite string** `tenant_id#agent_id` (exact-match lookups), SK unchanged.
- **Status GSIs:** PK `tenant_id`, SK `status`.
- **decision-date GSI** (compliance): PK becomes `tenant_id#decision_date` so audit queries are tenant-scoped; SK `timestamp_ms` unchanged.
- **Default tenant:** every migrated row gets `tenant_id = "default"`. Existing demo agents/sessions are grandfathered under `default`.

### 1.2 Cutover flag
`TENANCY_V2_ENABLED` (settings, env-driven). Off → all reads/writes hit `*-v1` (today). On → all hit `*-v2`. Read **per-request** (T7). One switch flips read+write together; no dual-path logic beyond the flag check.

### 1.3 Table inventory (this migration)
| v1 table | Removal | v2 table | New PK / SK | GSIs after |
|---|---|---|---|---|
| `sentra-agent-registry` | RETAIN | `sentra-agent-registry-v2` | `tenant_id` / `agent_id` | `status-index` (tenant_id / status) |
| `sentra-policies-metadata` | RETAIN | `sentra-policies-metadata-v2` | `tenant_id` / `policy_id` | `agent-index` (`tenant_id#agent_id`), `status-index` (tenant_id / status) |
| `sentra-session-context` | DESTROY | `sentra-session-context-v2` | `tenant_id` / `session_id` | `agent-updated-index` (`tenant_id#agent_id` / last_activity) |
| `sentra-validation-signals` | RETAIN | `sentra-validation-signals-v2` | `tenant_id` / `sk` (SK format unchanged) | `agent-timestamp-index` (`tenant_id#agent_id`), `decision-date-timestamp-index` (`tenant_id#decision_date`) |

> **Out of scope:** `sentra-sigma-rules-metadata` (platform-global rules), `sentra-tool-registry`, demo tables. The actual `sentra-policies` table (PK `policy_id`, GSI `agent-version-index`) is **confirmed legacy / not on the validate path** — `verify_policy_migration.py:122` ("LEGACY PATH … dashboard only, not validator"), `health_service.py:93` ("legacy"), and no security-controller app-code reads it. Skip it in M0. *Note:* its one live reader is the **dashboard** (`dashboard/config/settings.py:49`); tenant-scoping the dashboard is a separate later concern, not this migration.

---

## 2. Milestone map

| Milestone | Theme | Tasks | Gate before next | Status |
|---|---|---|---|---|
| **M0a** | v2 tables (CDK) + flag plumbing | T01–T02 | `cdk diff` = only the new `*-v2` tables; flag wired off | ☑ done (synth = 4 new tables; CDK tests green) |
| **M0b** | App-layer: tenant-aware stores (writes/get_items/**scans**) + all key-changed-GSI readers | T03–T06 (incl. **T04b**) | `pytest` green flag on **and** off; **§0.1 inventory fully ✅**; isolation holds through real endpoints | ☑ done (398 pass flag-off + `test_tenancy_v2.py` flag-on) |
| **M0c** | Migration script + scripts update | T07–T08 | dry-run plan correct; idempotent; seed scripts target v2 | ☑ code done (`migrate_tenancy.py` + `_tenancy.py`; live run pending) |
| **M0d** | Cutover + verify | T09–T10 | write-freeze cutover done; isolation + fail-secure asserted; signed off | ☑ tests + runbook done; ☐ live cutover (founder-gated) |

> **Type**: 🛑 blocker · 🔧 build · ❓ decision. **Status**: ☐ todo · ◐ in-progress · ☑ done.

---

## 3. M0a — v2 tables + flag

| ID | Task | Type | Pri | Ref | Status |
|----|------|------|-----|-----|--------|
| **T01** | Add 4 `*-v2` tables + GSIs in `storage_stack.py` (matching removal policies) | 🔧 | P0 | T5/§1.3 | ☐ |
| **T02** | `TENANCY_V2_ENABLED` flag + v2 table names in config/settings; IAM grants on v2 | 🔧 | P0 | T7 | ☐ |

**T01.** In [`storage_stack.py`](../../cdk/stacks/storage_stack.py) add the four `*-v2` tables per §1.3. `registry-v2`/`policies-metadata-v2`/`signals-v2` → `RemovalPolicy.RETAIN`; `session-context-v2` → `DESTROY`. Signal store: extend `ValidationSignalStoreTable` construct (or a v2 variant) keeping SK = `sk` byte-identical (T4). **Acceptance:** `cdk diff` shows **only** the 4 new tables + their GSIs, no change to v1 tables.

**T02.** Add v2 table names to `config/environments/*.yaml` and `settings`; add `tenancy_v2_enabled: bool` (default **false**). Extend the controller task role IAM in `compute_stack.py` to read/write the v2 tables + GSIs (mirror the v1 grants). **Acceptance:** flag defaults off; `aws iam` grants cover v2; settings expose both v1 and v2 names during transition.

---

## 4. M0b — App-layer tenant-aware stores

| ID | Task | Type | Pri | Ref | Depends | Status |
|----|------|------|-----|-----|---------|--------|
| **T03** | `tenant_ctx` helper + table-resolver (flag → v1/v2 name, composite-key builder) | 🔧 | P0 | T7/§1.1 | T02 | ☐ |
| **T04** | Base-table writes + **every `get_item`** carry `tenant_id` (per §0.1); fix `policy_validator` hardcoded-table + resolver | 🛑 | P0 | T9/§0.1 | T03 | ☐ |
| **T04b** | **Every `scan()` tenant-scoped** (Query or `tenant_id` filter) per §0.1 — closes the isolation leak | 🛑 | P0 | T8/§0.1 | T03 | ☐ |
| **T05** | Update **all key-changed GSI readers** (agent-index ×4 + decision-date ×1) to composite keys via the helper | 🛑 | P0 | T1/T2 | T03 | ☐ |
| **T06** | `signal_store_writer` writes `tenant_id` + composite GSI keys; SK format unchanged | 🔧 | P0 | T4 | T03 | ☐ |

**T03.** New helper (e.g. `app/common/tenancy.py`): `current_tenant()` (P0 returns `"default"`; later from the verified JWT `tid`, feature §14), `table_name(logical)` (flag → v1/v2), `agent_gsi_key(tenant, agent_id)` → `f"{tenant}#{agent_id}"`. Read the flag **per call** (T7). **Acceptance:** unit tests for name resolution under flag on/off and composite-key formatting.

**T04 (base-table reads/writes + every `get_item`).** Per §0.1, thread `tenant_id` through every registry/policies-metadata/session **write** and **`get_item`** → `Key={'tenant_id': t, '<sk>': v}` at all 8 get_item sites (incl. `policy_validator._agent_exists:80`, `agent_service` :229/:250/:288/:232, `policy_service.get_policy:196`, `session_manager` :83/:115). Fix `policy_validator.__init__` to use the table-resolver instead of the hardcoded `Table('sentra-agent-registry')` (T9). **Acceptance:** with flag on, writes land in v2 under `tenant_id='default'`; every get_item reads back by `(default, id)`; **policy creation works** (`_agent_exists` no longer throws `ValidationException`); flag off path byte-identical.

**T04b (scans — the isolation leak, per §0.1).** Every base-table `scan()` becomes tenant-scoped: prefer `Query(KeyConditionExpression='tenant_id = :t')`; where a genuine enumeration is needed, add `FilterExpression` `tenant_id = :t`. Covers `agent_service.list_agents:133,137`, `discovery_service._scan_all:69`, `policy_service.list_policies:141`, and the 5 `session_manager` scans. **Acceptance:** a tenant-B caller probing `GET /v1/agents`, the discovery/import list, and session-count/trust reads gets back **only** tenant-B rows; a seeded `tenant=other` row never appears in any response.

**T05 (load-bearing — all key-changed GSIs).** Route every reader of the **three** key-changed GSIs through the composite-key builder:
- **agent-index ×4** → `:a = tenant#agent_id`: [`policy_engine.get_agent_policy:70`](../../src/security-controller/app/validators/policy_engine.py#L70), [`agent_service:349`](../../src/security-controller/app/services/agent_service.py#L349), [`agent_service:630`](../../src/security-controller/app/services/agent_service.py#L630), [`policy_service.query_policies:117`](../../src/security-controller/app/services/policy_service.py#L117) (the `if agent_id:` branch — **not** `create_policy`, a `get_item` by `policy_id`).
- **decision-date ×1** → `decision_date = tenant#YYYY-MM-DD`: [`decisions_service:271`](../../src/security-controller/app/services/decisions_service.py#L271) (backs `GET /v1/decisions`).
- **agent-timestamp-index** & **agent-updated-index** → **0 app readers** (both confirmed) — no reader to change; the v2 GSIs must still be **created** with composite keys for write projection (T01).

**Acceptance:** flag on → all agent-index readers resolve the same v2 policy for `(default, agent)` **and `GET /v1/decisions` returns the tenant's rows** (regression guard); flag off → byte-identical; cross-tenant `(other, …)` returns nothing.

**T06.** [`signal_store_writer`](../../src/security-controller/app/utils/signal_store_writer.py) writes `tenant_id` (base PK) and the composite `tenant_id#agent_id` / `tenant_id#decision_date` GSI attributes; **SK (`request_id#timestamp_ms#source`) and `_isoformat_ms_z` unchanged** (T4). **Acceptance:** a signal write under flag-on lands in v2, groups correctly on both GSIs scoped to `default`; SK format assertion still passes.

---

## 5. M0c–M0d — migrate, cut over, verify

| ID | Task | Type | Pri | Ref | Depends | Status |
|----|------|------|-----|-----|---------|--------|
| **T07** | `scripts/migrate_tenancy.py` — copy v1→v2 under `tenant=default`, idempotent, dry-run | 🛑 | P0 | T5 | T01 | ☐ |
| **T08** | Update seed/query scripts to target v2 + write `tenant_id` | 🔧 | P0 | T6 | T03 | ☐ |
| **T09** | Write-freeze cutover: freeze → delta copy → flip flag → unfreeze | 🛑 | P0 | §1.2 | T04, **T04b**, T05, T06, T07 | ☐ |
| **T10** | Verify: tenant isolation + fail-secure + parity; sign off | 🛑 | P0 | T1/T3 | T09 | ☐ |

**T07.** New `scripts/migrate_tenancy.py`. For each v1 table: scan → for each row, set `tenant_id='default'` + composite GSI attrs → `put_item` into v2. **The migration's `scan` is intentionally *unscoped*** — it predates the data having tenants and must copy **every** v1 row; do **not** "consistency-fix" it to use the T04b tenant helper (that would copy only `tenant=default` once tenants exist). Idempotent (re-runnable; `put_item` overwrites identically). `--dry-run` prints counts/plan; `--table` to run one at a time. Signal store: preserve `sk`, `decision_date`, `timestamp_ms` **verbatim** (copy, never recompute); add `tenant_id` + `tenant_id#...` attrs. **Deletes are not propagated** — a `put_item` delta re-copies new/changed rows but never removes a row deleted in v1 after the bulk copy. Harmless for ephemeral sessions (the copied TTL attr cleans v2); for a policy deleted mid-window it would leave an orphan active policy in v2. The **T09 write-freeze** is what keeps the delta window closed; **T10b's parity check is the backstop** (it flags v2 ⊋ v1). Don't widen the window without re-checking this. **Acceptance:** dry-run prints per-table row counts; live run twice is a no-op the second time; v2 counts == v1 counts; **and the migrated signal `sk`/`decision_date`/`timestamp_ms` byte-match the source row** (not just counts — guards the LLD-17 `_isoformat_ms_z` canonical-format drift, best-practices §12).

**T08.** Point `seed_agents.py`, `seed_policies_metadata.py`, `query_helpers.py` (and any other `status-index`/`agent-index` callers from §0/T6) at the v2 tables when the flag is on, writing `tenant_id`. **Explicitly excluded:** `seed_policies.py` (uses `agent-version-index` on the **legacy** `sentra-policies` table, §1.3) — out of scope; do **not** re-point it. **Acceptance:** re-seeding under flag-on produces tenant-stamped v2 rows, never flat v1 rows; `seed_policies.py` untouched.

**T09 (cutover).** Low-traffic window: (1) freeze writes (scale validate to read-only or brief maintenance), (2) run `migrate_tenancy.py` final delta, (3) flip `TENANCY_V2_ENABLED=true` (env update + `--force-new-deployment`), **(3a) WAIT for the new ECS deployment to fully stabilize — all old-flag tasks drained — before unfreezing** (T7: `min/max-healthy 50/200` runs old+new concurrently mid-rollout; unfreezing early splits writes across v1/v2), (4) unfreeze. v1 tables **retained** (T5). **Acceptance:** during the rollout no request is served by a half-migrated mix; post-flip a live `/v1/validate` for a known agent ALLOWs via the v2 policy; **rollback (flag back off) is the same concurrent-rollout mechanism and therefore also freeze-gated** — rehearse it under the same write-freeze or in a non-traffic environment, never as a live unfrozen flip.

**T10 (verify).** Assert:
- (a) **isolation through real endpoints, not just GSI gets** — a tenant-B caller hitting `GET /v1/agents`, the discovery/import list, session-count/trust reads, `GET /v1/policies`, and `GET /v1/decisions` sees **zero** tenant-A rows. *This is the check that catches the scan leak (T8); a GSI-only test would pass while the scans leak.* Seed a `tenant=other` row in each table and assert it never surfaces.
- (b) **fail-secure parity** — every agent that resolved an active policy pre-migration still does post-flip (no new `POLICY_NOT_FOUND`). Parity report runs the resolver with the flag **toggled** (v1 set vs v2 set) against the same migrated data; the resolvable-agent sets must match. **Take the parity snapshot *inside* the T09 write-freeze window** — a write landing between the final delta copy and the flag flip would legitimately diverge v1/v2 and false-fail the check.
- (c) **all key-changed-GSI readers** (agent-index + decision-date) resolve the tenant's data — incl. a **`GET /v1/decisions` non-empty** regression check.
- (d) **signal `sk`/`decision_date` byte-match** the source (T07 fixture), not just format-unchanged.

**Acceptance:** all four pass; founder sign-off before any v1 deletion.

---

## 6. Forward map (next specs, after M0 lands)

- **P0b — AWS inventory:** `connections` + `discovery-cache` tables (**born tenant-scoped**, PK `tenant_id`), `connections_service`, AWS Bedrock scanner, discovery review UI. No runtime credential yet; `tenant_id` from the operator's connection.
- **P1 — Govern + identity:** import saga (registry→policy, §12), `credentials` table + asymmetric-JWT verify (feature §14), `enforcement_mode=monitor` honored at final verdict (feature §10.2, incl. trust-penalty suppression), `current_tenant()` switches from `"default"` to the verified JWT `tid` claim.
- **P2+ — Azure / GCP** scanners; connector/sidecar interception.

---

## 7. Out of scope (this spec)
- Any inventory/scan/credential code (P0b+).
- Tenanting `sigma-rules-metadata` (platform-global), `tool-registry`, demo tables.
- Deleting v1 tables (post-cutover, separate sign-off).

---

## 8. M1 — Detected-agents union + `NotImported/Imported/Managed` lifecycle (feature §8.1)

> **Why:** the Connect→Scan path is real (live `AssumeRole` + `ListAgents`), but the Detected-Agents list is still policy-derived — it does **not** reflect what the scan actually sees, and there's no "data flowing" status. This milestone makes the list the **union of imported (registry) + scanned (cloud) agents** deduped by the source's native id, and adds a **derived** lifecycle status where `Managed` means real `/v1/validate` traffic. Builds on the already-shipped connections domain (`connections_service`, `/v1/connections*`, scan).

**Locked decisions (feature §8.1):** dedupe by **`native_resource_id`** (per-source unique id; normalized-name fallback for pre-existing rows) · status **derived, never hand-set** · `Imported→Managed` flips **only** on observed validate traffic · `Managed` is **sticky + `last_active`** · list = union of **all** imported + **all** connection-scanned, deduped.

| ID | Task | Type | Pri | Status |
|----|------|------|-----|--------|
| **DA1** | Store `native_resource_id` on every agent record — registry write path (`discovery_service.import_agents`, `seed_agents.py`) + scanned records. Backfill existing registry rows (best-effort: derive from `agent_id`/source). | 🔧 | P0 | ☐ |
| **DA2** | `sentra-discovery-cache` table (**born tenant-scoped**, PK `tenant_id`, SK `native_resource_id`) — `storage_stack` + settings + controller IAM grant + env. RETAIN. | 🔧 | P0 | ☐ |
| **DA3** | `scan_connection` **persists** the live `ListAgents` results into `discovery-cache` (`native_resource_id`, name, cloud_provider, `last_scanned`); set `discovered_count` real. | 🛑 | P0 | ☐ |
| **DA4** | `GET /v1/discovery/agents` = **union** of registry (imported) ∪ discovery-cache (scanned), **deduped by `native_resource_id`** (normalized-name fallback). Replaces the policy-derived-only `_build_rows`. Honors the existing cloud/connection/status filters; `connection_id` becomes a real filter. | 🛑 | P0 | ☐ |
| **DA5** | **Status derivation** `NotImported/Imported/Managed`: NotImported = scanned ∧ ¬registry; Managed = registry ∧ recent validate signals (query the signal-store **agent index**, LLD 17 — first app reader of `agent-timestamp-index`); else Imported. Sticky + `last_active`. | 🛑 | P0 | ☐ |
| **DA6** | **Frontend** ([ImportAgentsPage], badges): three-state `NotImported/Imported/Managed` badge + `last_active`; Import action enabled only for `NotImported`; label account-connection state **separately** from per-agent lifecycle (resolves the 3-axes UX trap, §8.1). | 🔧 | P0 | ☐ |
| **DA8** | **Agent Inventory shows only `Managed`** (feature §8.1): `GET /v1/agents` + `AgentInventoryPage` filter to agents with observed validate traffic (same signal-derived status as DA5), surfacing `last_active`. Imported-but-silent agents stay in the Import tab, not Inventory. | 🛑 | P0 | ☐ |
| **DA7** | Tests: union+dedupe (incl. native-id match and name fallback, no duplicates); status from seeded validate signals (Imported↔Managed); scan persistence; `connection_id` filter; **inventory shows only Managed**; FE badges. | 🛑 | P0 | ☐ |

**Acceptance:** Connect & scan an AWS account → the **real** account agents (incl. ones with no Sentra policy) appear as `NotImported`; importing one flips it to `Imported`; emitting a `/v1/validate` for it flips it to `Managed` (data flowing) with a `last_active`; no agent appears twice; `pytest` green + `tsc -b`/`build` clean + `cdk diff` = only the new `discovery-cache` table.

> **Naming caveat (carry from P0a):** any net-new top-level `/v1/*` path (none expected here — reuses `/v1/discovery/*`) needs both an API Gateway method **and** an ALB listener-rule pattern (cap 5/rule). The discovery paths are already wired.
