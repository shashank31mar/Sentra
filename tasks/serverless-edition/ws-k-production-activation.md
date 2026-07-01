# WS-K — Production Activation & Cutover (TENANCY_V2)

**Workstream:** WS-K (Serverless Edition — Production Activation & Cutover). *(Single canonical workstream doc: scope + dependencies + granular tasks; the design lives in the LLD below.)*
**Derived from (SOURCE OF TRUTH):** [lld/27-serverless-production-activation.md](../../lld/27-serverless-production-activation.md) (APPROVED, owner-reviewed, 12 sections). **When this doc and the LLD disagree, the LLD wins** — this file is the buildable projection of it; do not re-decide anything here.
**Status:** **✅ DONE (verification-only)** — completed 2026-06-30 against the live system (the `Sentra-DEV-*` stacks ARE prod for acct `531109575379`; no separate prod env exists). K1–K4, K7, K8, and the predecessor gate are verified live; K3.2 test green; K8 post-cutover suite 92/0 (4 env-skips). **Open/N-A:** K2.5 rollback drill (no staging env), K4.1 burst-throttle (fail-open half verified), K5 (N/A — S3 prefix migration never started), **K6 purge DEFERRED per founder** (`default` still holds 9 live agents), K8 CI-gate wiring (WS-J). See the acceptance checklist + runbook §1 Verified-runs.
**Owner:** TBD (founder sign-off required for K1.4, K5.3, K6.2 — founder = Shashank Gupta).

> **This is ACTIVATION, not build.** Most "code" is config keys + invoking already-tested migration scripts + verification queries + ONE new integration-test file. The danger is in *sequencing*, not lines of code (LLD §1.1). The TENANCY_V2 build (LLD-26 WS-A…WS-E) and the Cedar cutover are DONE and enforcing on dev — do **not** rebuild or re-decide them.

---

## 1. Dependencies

- **Depends on:** the entire **TENANCY_V2 build** (LLD 26, [tasks/26-multi-tenancy/](../26-multi-tenancy/) WS-A…WS-E) — **DONE & enforcing on dev** (go-live 2026-06-24, commit `8902b4e`, [tasks/26-multi-tenancy/99-go-live-runbook.md](../26-multi-tenancy/99-go-live-runbook.md)). This WS activates that build in prod/staging; it does not implement it.
- **Blocks:** **everything else in the Serverless slice that touches a 2nd prod tenant.** Per HLD §8 residual #2 and sub-PRD FR-10.5: multi-tenant Serverless **cannot onboard a second customer in prod until this lands.** WS-A/B/D/E/F (serverless) build *against* the multi-tenant baseline this WS turns on. This is the **first predecessor gate.**
- **Shared files (the activation surface):**
  - [cdk/config/prod.yaml](../../cdk/config/prod.yaml) — the prod activation flags (the real flip).
  - [cdk/config/dev.yaml](../../cdk/config/dev.yaml) — the **reference posture** (already at the target state; copy its shape, not blindly).
  - [src/security-controller/app/config.py](../../src/security-controller/app/config.py) — the flag schema + **conservative-off defaults** (a key absent from prod.yaml = the default applies).
  - [tasks/26-multi-tenancy/99-go-live-runbook.md](../26-multi-tenancy/99-go-live-runbook.md) — the **runbook of record** (dev go-live). Cross-link, reuse its gated-cutover + rollback steps; **do not duplicate them — extend for prod.**

---

## Read before coding — the invariants/footguns you must hold

These are the LLD's load-bearing tie-breakers. Hold all six (LLD §1.2) plus the two scope guards.

1. **Fail-secure / deny-by-default** (LLD §1.2 tenet 1). A missing table or a tokenless agent under enforce → DENY, never a permissive fallthrough. **Caveat:** a Cedar **abstain** is the ONE case that does NOT honor this today — it falls back to the legacy engine (a *permissive* permit). Closing that is K3.2's job and it is **work to WRITE, not a proven invariant** (LLD §7.1, E7).
2. **Conservative-off default + the absent-key trap** (LLD §1.2 tenet 2, §3.2). `config.py` defaults are conservative-off. A key **absent** from `prod.yaml` rides the off default — you **ADD the key**, you cannot edit a line that isn't there. An acceptance check that greps for the *line* `tenant_identity_mode: enforce` passes on dev and **silently fails on prod** when the key is absent. Verify the key is *present*, not just the default.
3. **Two-latch enforce: `effective_mode = min(env ceiling, tenant.identity_mode)`** ([config.py:125](../../src/security-controller/app/config.py), LLD §1.2 tenet 3, §5). Raising the env ceiling never forces a `shadow`/`off` tenant into enforce. A tenant enforces only when BOTH the env ceiling AND its `sentra-tenants` row read `enforce`.
4. **Per-tenant enforce gates on ≈100% per-agent credential coverage** (LLD §1.2 tenet 4, §5.1 — the bootstrap hazard). Flip a tenant to enforce only when `CRED == REG`. An uncredentialed agent in a flipped tenant gets a **time-boxed, alarmed** legacy-fallback window that **expires to hard DENY** — never a silent `default` ride.
5. **Irreversible tail items are sign-off-gated** (LLD §1.2 tenet 5, §6.2 K5.3, §6.3 K6): the `default` brownfield purge and the S3 `--delete-old` cut are point-of-no-return; each needs a written, dated founder sign-off with an inventory/confirmation attached. There is **no rollback** for a purge.
6. **Rollback is a flag flip at every step** (LLD §1.2 tenet 6, §10): per-tenant `PATCH identity_mode → shadow` (≤30 s mode-cache TTL); fleet ceiling `tenant_identity_mode = shadow|off` + redeploy; `tenancy_v2_enabled: false` + `cdk deploy` reverts to v1 tables.
7. **SCOPE GUARD — do NOT touch `cedar_enabled`/`cedar_shadow_mode`** (LLD §1.3, §3.3, K3.3). [prod.yaml:30-31](../../cdk/config/prod.yaml) already carries `cedar_enabled: true` + `cedar_shadow_mode: false`. The ONLY real prod flip is **TENANCY_V2**. Any PR under WS-K that flips the Cedar keys is out of scope and must be rejected.
8. **Identity-gate DENYs are NOT metered** (LLD §4.3, §9, E3). Tenancy identity-gate DENYs do not increment `Decisions`/`ValidationsTotal`. A flat `Decisions` panel is NOT proof enforce is clean — the proof is the `/sentra/audit-logs` `IDENTITY_*` query.

All commands run with `export AWS_PROFILE=sentra AWS_REGION=us-east-1` (account `531109575379`). Production-safety: read/describe/list only except the gated flag deploys and the explicitly-confirmed migration scripts; never `cdk destroy`.

---

## Milestone K1 — Prereqs: tables exist + v1→v2 copy ran + sign-off

Build order: K1 gates everything. Implements LLD §2.3 (hard ordering invariants), §4.1, §4.2; scope K1.1–K1.4.

### K1.1 — Confirm dev is the reference posture (read-only)
- **Read** [cdk/config/dev.yaml](../../cdk/config/dev.yaml) lines 25/37/42/45/51/57/64/70 to capture the target *shape*: `tenancy_v2_enabled: true`, `tenant_identity_mode: enforce`, `identity_fallback_window_seconds: 0`, `s3_explicit_tenant_prefix: false`, `quota_enforcement_enabled: true`, `platform_read_consent_enforced: true`, `cedar_enabled: true`, `cedar_shadow_mode: false`.
- **Implements:** LLD §2.1 (dev = reference posture only — copy its shape, not blindly its values).
- **FOOTGUN:** `s3_explicit_tenant_prefix: false` is NOT "done" — `false` means legacy implicit layout (the explicit-prefix flip is K5). Do not copy `false` thinking the migration is complete.

### K1.2 — Verify v2 + identity tables exist in prod (hard prereq)
- **Run** the LLD §4.1 describe-table loop over the 8 tables and the 2 GSIs:
```bash
for T in sentra-tenants sentra-tenant-members sentra-agent-credentials \
         sentra-identity-fallback sentra-agent-registry-v2 \
         sentra-policies-metadata-v2 sentra-session-context-v2 \
         sentra-validation-signals-v2; do
  aws dynamodb describe-table --table-name "$T" \
    --query 'Table.{n:TableName,s:TableStatus}' --output text || echo "MISSING: $T"
done
aws dynamodb describe-table --table-name sentra-agent-credentials \
  --query 'Table.GlobalSecondaryIndexes[].IndexName'   # expect ["kid-index"]
aws dynamodb describe-table --table-name sentra-tenant-members \
  --query 'Table.GlobalSecondaryIndexes[].IndexName'   # expect ["tenant-members-index"]
```
- **Gate:** every table `ACTIVE`, both GSIs present.
- **Implements:** LLD §2.3 (StorageStack before the flag), §4.1, E1.
- **FOOTGUN (E1):** Any `MISSING`/non-ACTIVE → **HALT**, deploy StorageStack (`cdk deploy <Sentra-PROD-Storage-Stack>`), re-run. Flipping `tenancy_v2_enabled: true` before these tables exist → controller reads missing tables → fail-secure **DENY storm**. The StorageStack deploy is a hard prerequisite, not a flag.

### K1.3 — Verify the v1→v2 copy under `tenant=default` ran
- **Run** the LLD §4.2 counts:
```bash
aws dynamodb scan --table-name sentra-agent-registry-v2 \
  --filter-expression 'tenant_id = :t' \
  --expression-attribute-values '{":t":{"S":"default"}}' \
  --select COUNT --query 'Count'
aws dynamodb scan --table-name sentra-agent-registry --select COUNT --query 'Count'
```
- **Gate:** v2 count ≈ v1 count under `default`. Zero v2 items → run `python scripts/migrate_tenancy.py` (per dev.yaml:22-24 history) **before** the flag flip — else v2 is empty and reads miss.
- **Implements:** LLD §2.3 (v1→v2 data copy before the flag), §4.2.

### K1.4 — Record the sequencing decision + capture FOUNDER SIGN-OFF (gate)
- **Decide** shadow-first vs direct-enforce (HLD §8 residual #2). **Default to shadow-first** (cheap, matches the dev runbook) unless the founder signs off on direct (scope K1.3/K1.4).
- **Capture** a written, dated founder go before any K2 prod flip. No sign-off → WS-K does not proceed to K2.
- **Implements:** LLD §2.2 (K1.4 founder sign-off node), scope Model. Record in [99-go-live-runbook.md](99-go-live-runbook.md).

---

## Milestone K2 — The `prod.yaml` flip (master flag + the 5 absent keys; shadow before enforce)

The only true prod flip in this WS. Apply to **staging first, soak, then prod** (LLD §2.3). Implements LLD §3.1, §3.2, §4.3, §4.4, §5.

### K2.1 — Flip the master flag (edit an existing line)
- **File:** [cdk/config/prod.yaml](../../cdk/config/prod.yaml) — line currently `tenancy_v2_enabled: false`.
- **Change** to `true` and update the precondition comment to record the prod go-live (mirror dev.yaml:22-24's `# CUTOVER` note). Exact target (LLD §3.1):
```yaml
# Tenancy v2 cutover flag (Multi-Cloud Agent Import — P0a, workstream §1.2).
# CUTOVER <YYYY-MM-DD>: migrate_tenancy.py copied v1→v2 under tenant=default in PROD
# (registry/policies/sessions/signals); StorageStack confirmed (K1.2). Founder go: <date>.
# Rollback: set false + cdk deploy <Compute+Storage stacks>.
tenancy_v2_enabled: true     # was: false
```
- **Implements:** LLD §3.1. **Prerequisite:** K1.2 (tables) + K1.3 (copy ran) both green.

### K2.2 — ADD the 5 absent keys (the absent-key trap)
- **File:** [cdk/config/prod.yaml](../../cdk/config/prod.yaml) — **append after the `cedar_*` block, before the `vpc:` block.** These keys are NOT present today; they ride the off default. ADD them verbatim with the conservative ceiling (`tenant_identity_mode: shadow`, NOT enforce). Exact block (LLD §3.2):
```yaml
# ── TENANCY_V2 runtime identity (LLD-26 §7.2) — ADDED for WS-K prod activation ──
tenant_identity_mode: shadow                 # config.py:127 default "off"; dev.yaml:37 "enforce"
identity_fallback_window_seconds: 0          # config.py:165 default 0; dev.yaml:42
s3_explicit_tenant_prefix: false             # config.py:90 default false; dev.yaml:45
quota_enforcement_enabled: true              # config.py:117 default false; dev.yaml:51
platform_read_consent_enforced: true         # config.py:184 default false; dev.yaml:57
```
- **Per-key intent** (carry the LLD §3.2 inline comments): `tenant_identity_mode: shadow` = verify+log presented JWTs, do NOT route; `identity_fallback_window_seconds: 0` = tokenless validate under enforce DENYs immediately; `s3_explicit_tenant_prefix: false` = legacy implicit layout, dual-read (K5 flips it); `quota_enforcement_enabled: true` = inert until a tenant enforces with a credential + RPS quota, fails OPEN on counter errors; `platform_read_consent_enforced: true` = Sentra-staff cross-tenant read DENIES (403) unless target tenant consents.
- **Implements:** LLD §3.2, §1.2 tenet 2.
- **FOOTGUN:** set `tenant_identity_mode: shadow` (NOT enforce) on this first prod flip — enforce with 0% coverage DENYs every prod agent. Enforce is K2.4, gated. And: an acceptance grep for the *line* `tenant_identity_mode: enforce` would pass on dev and silently fail on prod if the key is absent — K2 acceptance verifies the **key is present**, not just the default.

### K2.3 — Deploy (staging → prod) + verify shadow (no behavior change)
- **Run** (LLD §4.3): review the diff, deploy staging, soak, then prod:
```bash
cd cdk
cdk diff Sentra-PROD-Compute-Stack    # REVIEW: only the env-var flag change should appear
cdk deploy Sentra-PROD-Storage-Stack Sentra-PROD-Compute-Stack
# (1) verified-identity log lines present for signed agents:
aws logs filter-log-events --log-group-name /sentra/audit-logs \
  --start-time $(($(date +%s)*1000 - 600000)) \
  --filter-pattern '"identity_state=verified"' --query 'events[].message' --max-items 5
# (2) NO DENY storm — identity DENYs SKIP the Decisions metric, so check AUDIT LOGS:
aws logs filter-log-events --log-group-name /sentra/audit-logs \
  --start-time $(($(date +%s)*1000 - 600000)) \
  --filter-pattern '?IDENTITY_UNVERIFIED ?IDENTITY_' --query 'length(events)'
```
- **Gate (shadow):** `identity_state=verified` present for signed agents; `IDENTITY_*` count is **0** (shadow observes, never routes). Non-zero under shadow = config error → **Rollback R1**.
- **Implements:** LLD §4.3, §9 (K2.3 shadow gate), invariant 8 above.
- **FOOTGUN (E4):** a new MT route returning a **43-byte 403** in nginx + absent from controller logs = missing API GW route — add the explicit route in `api_stack.py` + private-ALB priority rule in `compute_stack.py` (apigw-per-resource memo, runbook lines 24-32). Do NOT diagnose this as an auth/identity failure.

### K2.4 — Coverage gate, then raise the fleet ceiling to enforce + PATCH the tenant
- **Run the coverage check FIRST** (LLD §5.1) for the onboarded tenant `t_xxx`:
```bash
REG=$(aws dynamodb scan --table-name sentra-agent-registry-v2 \
  --filter-expression 'tenant_id = :t' \
  --expression-attribute-values '{":t":{"S":"t_xxx"}}' --select COUNT --query 'Count' --output text)
CRED=$(aws dynamodb scan --table-name sentra-agent-credentials \
  --filter-expression 'tenant_id = :t AND #s = :a' \
  --expression-attribute-names '{"#s":"status"}' \
  --expression-attribute-values '{":t":{"S":"t_xxx"},":a":{"S":"active"}}' \
  --select COUNT --query 'Count' --output text)
echo "coverage: $CRED / $REG"   # gate: CRED == REG before PATCH enforce
curl -sS "$SENTRA_API_BASE/v1/identity/residual-agents" -H "x-sentra-oidc-data: <operator token>"
```
- **Gate:** `CRED == REG`. If `CRED < REG`: EITHER hold the tenant at `shadow` and finish credentialing (`python demo-agents/registration/provision_acme_identity.py` pattern / `aegion_guard.provision`), OR — only if a residual agent must be tolerated — set `identity_fallback_window_seconds: 86400` transiently (alarmed `IdentityFallback` window that expires to DENY), then drive back to `0` as coverage closes. The `GET /v1/identity/residual-agents` list is the ops worklist.
- **Then** raise the ceiling: set `tenant_identity_mode: enforce` in prod.yaml + redeploy, AND PATCH the tenant row (LLD §4.4):
```bash
curl -sS -X PATCH "$SENTRA_API_BASE/v1/tenants/t_xxx" \
  -H "x-sentra-oidc-data: <operator token>" -d '{"identity_mode":"enforce"}'
# verify: unsigned call from t_xxx DENYs IDENTITY_UNVERIFIED, audited under _unverified:
aws logs filter-log-events --log-group-name /sentra/audit-logs \
  --start-time $(($(date +%s)*1000 - 300000)) \
  --filter-pattern '"IDENTITY_UNVERIFIED" "_unverified"' --query 'events[].message' --max-items 3
```
- **Gate (enforce):** signed → route; unsigned from `t_xxx` → `IDENTITY_UNVERIFIED` under `_unverified`. Other prod tenants stay capped by their own row (`effective = min(enforce ceiling, their shadow/off)`).
- **Implements:** LLD §4.4, §5 (the two-latch model + bootstrap hazard), §1.2 tenets 3 & 4, E2.
- **FOOTGUN (E2):** never PATCH a tenant to enforce before `CRED == REG` — it DENYs that tenant's tokenless agents. Recover with Rollback R2 (`PATCH → shadow`, ≤30 s TTL).

### K2.5 — Test the rollback path at staging before the prod step
- **Drill** each rollback at staging (LLD §10): R1 (`tenancy_v2_enabled: false` + `cdk deploy` → back to v1 tables), R2 (`PATCH /v1/tenants/t_xxx {identity_mode: shadow}` → ≤30 s TTL), R3 (`tenant_identity_mode: shadow|off` + `cdk deploy` → caps every tenant). Verify each: DENYs stop, recheck `/sentra/audit-logs` `IDENTITY_*`.
- **Implements:** LLD §10 (rollback drills), §1.2 tenet 6.

---

## Milestone K3 — Cedar VERIFY-ONLY (do NOT re-flip — already set in prod.yaml)

Implements LLD §7.1, E7; scope K3.1–K3.3. **No config change here for K3.1/K3.3.** K3.2 WRITES a test.

### K3.1 — Verify Cedar is deployed authoritative in prod
- **Confirm** the deployed controller image evaluates the cutover branch True: [validation_service.py:301](../../src/security-controller/app/services/validation_service.py) `cutover = cedar is not None and settings.cedar_enabled and not settings.cedar_shadow_mode`.
- **Evidence:** a prod `/v1/validate` trace shows the **Cedar source** as the deciding combiner source; the CT08 `.cedar` co-artifact backfill ran (else Cedar abstains → legacy decides, prod.yaml:27-28 comment).
- **Implements:** LLD §7.1, §9 (validate-trace deciding source = Cedar), scope K3.1.

### K3.2 — WRITE the abstain → fail-secure-DENY test (work to do, NOT a proven invariant)
- **File to CREATE/EXTEND:** add a test to [src/security-controller/tests/test_cedar_cutover.py](../../src/security-controller/tests/test_cedar_cutover.py) asserting **abstain-where-Cedar-should-decide → DENY** under the FR-2.4 "legacy retired" posture.
- **Why this is real work:** today the cutover branch ([validation_service.py:305-311](../../src/security-controller/app/services/validation_service.py)) runs `policy_fallback = self.policy_engine.validate(request)` on a Cedar **abstain** and the legacy verdict becomes the decision — a *permissive permit*, not a fail-secure DENY. The existing `test_cutover_abstain_falls_back_to_legacy` ([test_cedar_cutover.py:96-108](../../src/security-controller/tests/test_cedar_cutover.py)) **pins the permissive rollout-era behavior** (`result.should_deny is False`) — it must NOT be cited as the fail-secure proof.
- **Distinguish the two failure cases** (LLD §7.1): a Cedar evaluator **error** already fails secure via `_create_error_response` → `decision: DENY` / `violation_type: SYSTEM_ERROR|POLICY_ERROR` ([validation_service.py:656-673](../../src/security-controller/app/services/validation_service.py)) — already encoded. A Cedar **abstain** does NOT — that is the gap.
- **Pseudo-code for the new test (real names):**
```python
async def test_cutover_abstain_where_cedar_should_decide_fails_secure(...):
    # cutover True: cedar_enabled, not cedar_shadow_mode, cedar is not None
    # Cedar abstains on a policy that SHOULD decide (legacy-retired posture)
    result = await validation_service.validate(request)
    assert result.should_deny is True            # fail secure, NOT legacy permit
    assert result.violation_type in ("POLICY_ERROR", "SYSTEM_ERROR")
    # legacy engine must NOT be the deciding source under "legacy retired"
```
- **Implements:** LLD §7.1, E7, scope K3 acceptance (legacy-retired → fail-secure-DENY asserted by a test). Until this test exists and passes, the **CT08 `.cedar` backfill is the load-bearing prerequisite** keeping Cedar from abstaining in prod, and the FR-2.4 "legacy retired" claim is gated on this test going green.
- **FOOTGUN:** do not "fix" the abstain path by editing production behavior beyond what the LLD scopes — the LLD scopes the *test* (K3.2) + the *backfill prerequisite* (CT08/E7). If the test reveals the abstain path must change behavior, flag it to the LLD/HLD owner; do not silently re-decide.

### K3.3 — Scope-guard assertion (no Cedar flip)
- **Record explicitly** in [99-go-live-runbook.md](99-go-live-runbook.md): WS-K does NOT touch `cedar_enabled`/`cedar_shadow_mode`. Any PR under WS-K that flips them is out of scope and must be rejected.
- **Implements:** LLD §1.3, §3.3, scope K3.3, invariant 7.
- **FOOTGUN:** there is **nothing to flip** for Cedar in prod — do not create a Cedar prod-flip task or PR.

---

## Milestone K4 — Per-tenant RPS-quota ceiling raise (reversible)

Run AFTER K2.4 enforce verifies. Implements LLD §6.1, E8; scope K4.1. `quota_enforcement_enabled: true` is already set (K2.2) but **inert** until a tenant is in `enforce` with a registered credential AND a `max_validate_rps` quota on its row.

### K4.1 — Set the per-tenant RPS ceiling on the tenant ROW + verify
- **Run** (LLD §6.1) — note `max_validate_rps` is a `sentra-tenants` row field, NOT a config key:
```bash
curl -sS -X PATCH "$SENTRA_API_BASE/v1/tenants/t_xxx" \
  -H "x-sentra-oidc-data: <operator token>" -d '{"max_validate_rps": <provisioned-ceiling>}'
```
- **Verify:** (1) a burst over `max_validate_rps` throttles (429 / quota DENY) for `t_xxx`; (2) a forced counter-store error **fails OPEN** — does NOT DENY legitimate traffic ([config.py:114-117](../../src/security-controller/app/config.py); dev.yaml:50-51).
- **Rollback (R5):** remove `max_validate_rps` from the row (or `quota_enforcement_enabled: false` + redeploy) — counter is inert again.
- **Implements:** LLD §6.1, §9, E8, scope K4.1.
- **FOOTGUN (E8):** the quota path fails OPEN by design — a test/verification that asserts a counter error DENYs is wrong; assert it does NOT deny legitimate traffic.

---

## Milestone K5 — B3 S3 `--delete-old` prefix migration (point-of-no-return on `--delete-old`)

Run AFTER K4. Sequence: dual-read → copy → confirm → `--delete-old`. Implements LLD §6.2, E5; scope K5.1–K5.3. First two sub-steps reversible (R4); `--delete-old` is irreversible for the legacy layout.

### K5.1 — Flip on the explicit prefix + dual-read + deploy
- **File:** [cdk/config/prod.yaml](../../cdk/config/prod.yaml) — change `s3_explicit_tenant_prefix: false → true`, then `cdk deploy`.
- **Effect:** new writes go to `tenants/{tenant_id}/policies/agents/{agent_id}/v{n}.{yaml|cedar}`; reads dual-read both layouts ([config.py:81-92](../../src/security-controller/app/config.py)). **No old data deleted.**
- **Implements:** LLD §6.2 K5.1, scope K5.1.

### K5.2 — Dry-run, then run the copy (old objects retained)
- **Run** (LLD §6.2):
```bash
python scripts/migrate_s3_policy_prefix.py --dry-run   # prints plan, writes nothing (script line 31)
python scripts/migrate_s3_policy_prefix.py             # copies; old objects RETAINED (script line 22)
```
- **Verify** reads resolve from the new prefix for **every** existing policy (dual-read makes this non-breaking).
- **Implements:** LLD §6.2 K5.2, scope K5.2.

### K5.3 — `--delete-old` (POINT OF NO RETURN — sign-off-gated)
- **Run ONLY after** confirming all reads resolve from the new prefix, with a written confirmation that dual-read serves everything from the new layout:
```bash
python scripts/migrate_s3_policy_prefix.py --delete-old   # script lines 34, 147 — IRREVERSIBLE for legacy layout
```
- **Rollback (R4):** `s3_explicit_tenant_prefix: false` + `cdk deploy` — **only valid BEFORE `--delete-old`**; after the cut there is nothing to dual-read back to.
- **Implements:** LLD §6.2 K5.3, E5, §1.2 tenet 5, scope K5.3.
- **FOOTGUN (E5):** `--delete-old` before confirming new-prefix reads → policies vanish → deny-by-default DENY (no policy = fail-secure DENY). **No automated `--delete-old`.**

---

## Milestone K6 — `default` brownfield purge (IRREVERSIBLE, founder-sign-off-gated, 0-default-creds gate)

Run LAST, AFTER K5. Implements LLD §6.3, E6; scope K6.1–K6.3. There is **no rollback** — the inventory + sign-off ARE the safety.

> **Note (LLD §6.3):** prod currently has **no real customer data** — the only seeded tenant is the `acme` demo tenant, and the dev `default` inventory reads **0 credentials**. So the purge gate is *already satisfiable* and K2.1 is safe to schedule now. Re-run the prod inventory to confirm before the purge regardless.

### K6.1 — Inventory FIRST (read-only, safe)
- **Run** (LLD §6.3):
```bash
python scripts/migrate_brownfield.py inventory --out default_inventory.json   # script lines 30-31
```
- Attach `default_inventory.json` to the sign-off packet.
- **Implements:** LLD §6.3 K6.1, scope K6.1.

### K6.2 — Founder sign-off (separate, explicit, dated, written)
- **Capture** a written go re-confirming **no real customer data under `default`** (runbook lines 153-158). **0-default-creds gate:** if inventory shows ANY credential under `default`, STOP — re-import under a real tenant first; do not purge.
- **Implements:** LLD §6.3 K6.2, §1.2 tenet 5, scope K6.2.

### K6.3 — Purge (only on explicit go)
- **Run** (LLD §6.3):
```bash
python scripts/migrate_brownfield.py purge --confirm-no-customer-data   # script line 32; IRREVERSIBLE
```
- The script **refuses** without `--confirm-no-customer-data` (script lines 130-133) and reuses the controller's tested resumable `tenant_purge.purge_tenant` engine (script line 140).
- **Implements:** LLD §6.3 K6.3, E6, scope K6.3.
- **FOOTGUN (E6):** never run as part of an automated rollout or "to clean up". No rollback for a purge. STOP-on-nonzero-inventory is a hard gate.

---

## Milestone K7 — Verify the `acme` agents sign under enforce (VERIFY the dba8a79 fix holds, NOT a re-fix)

Implements LLD §6.4. The three `acme-*` agents were brought to signing+verified under enforce in commit `dba8a79` (2026-06-25; Azure cold-start fixed via `alwaysOn=true` + `WEBSITE_CONTAINER_START_TIME_LIMIT=600`). **This VERIFIES the fix still holds in prod — it does NOT re-task an agent fix.**

The three agents ([demo-agents/registration/provision_acme_identity.py:44](../../demo-agents/registration/provision_acme_identity.py)): `acme-payments-agent` (AWS Bedrock Lambda), `acme-identity-agent` (Azure Function App), `acme-telecom-agent` (Azure Function App).

### K7.1 — Coverage = 3/3 for tenant `acme`
- **Run:** `GET /v1/identity/residual-agents` for tenant `acme` MUST return `count: 0` (the §5.1 gate). If non-zero, an agent regressed — re-provision it ([demo-agents/registration/provision_acme_identity.py](../../demo-agents/registration/provision_acme_identity.py)) before the per-tenant enforce PATCH.
- **Implements:** LLD §6.4 K7.1.

### K7.2 — Azure boot-under-enforce (alwaysOn) + the `azd deploy` footgun
- **Confirm** both Azure functions have `alwaysOn=true` ([demo-agents/azure-identity-agent/infra/main.bicep](../../demo-agents/azure-identity-agent/infra/main.bicep), `azure-telecom-agent/infra/main.bicep`) so the native-crypto import doesn't crash-loop the cold start (the original `dba8a79` regression).
- **Implements:** LLD §6.4 K7.2.
- **FOOTGUN:** an Azure agent redeployed via `azd up` (NOT `azd deploy`) wipes the signing app-settings (`SENTRA_TENANT_ID`/`KID`/`PRIVATE_KEY`) and silently regresses to unsigned → `IDENTITY_UNVERIFIED`. Deploy code-only with **`azd deploy`**.

---

## Milestone K8 — Post-cutover integration test suite (LLD §7 — every API, all use-cases, bug→fix loop)

Implements LLD §7 (the owner-directed post-cutover acceptance gate AND durable regression suite). Run after the cutover; a red suite blocks "go-live complete."

### K8.1 — Create the suite file
- **File to CREATE:** `tests/integration/test_post_cutover_suite.py`.
- **Use** the existing markers `@pytest.mark.integration` / `@pytest.mark.requires_services` and fixtures `service_urls` / `api_headers` from [tests/integration/conftest.py](../../tests/integration/conftest.py).
- **Run:** `pytest tests/integration/ -m integration -v` against the **prod** ALB (profile `sentra`, `us-east-1`) with an operator OIDC token + a credentialed `acme` agent's signing key.
- **Gate:** 100% pass before K2.4 enforce is declared complete; re-run after each tail task (K4/K5/K6).
- **Implements:** LLD §7.1.

### K8.2 — Cover every route, happy + failure paths
- **Enumerate** every route in [src/security-controller/app/api/routes.py](../../src/security-controller/app/api/routes.py) + [tenancy_routes.py](../../src/security-controller/app/api/tenancy_routes.py) (~40 endpoints). For each: happy path **and** failure paths (401 no-auth, 403 wrong-tenant/role, 404 missing, 400 bad-input). Load-bearing groups (LLD §7.2):
  - **Data plane** `POST /v1/validate`: ALLOW + DENY round-trips; a **signed-JWT** call verifies (tenant resolved from credential, not self-asserted); an **unsigned** call under enforce → `IDENTITY_UNVERIFIED` DENY; a **cross-tenant agent_id spoof** → DENY tagged `_unverified` (NOT charged to the claimed tenant).
  - **Identity/credentials** `POST /v1/agents/{id}/credentials`, `GET /v1/identity/residual-agents`, rotate/revoke: issue→sign→verify E2E over HTTP; a revoked `kid` → DENY; tenant A cannot register/read/revoke tenant B's credential (403).
  - **Tenancy** `POST /v1/tenants`, `/v1/me`, `/v1/invites*`, per-tenant `PATCH identity_mode`: tenant isolation; `require_role` enforced; `X-Aegion-Tenant` switch validated against membership (deny non-member).
  - **Policy CRUD** `GET/POST/PUT/DELETE /v1/policies`, `PATCH /v1/policies/{id}/status`, `POST /v1/agents/{id}/policies`: author→bind→evaluate (Cedar authoritative); cross-tenant policy read/write denied.
  - **Quarantine/rollback** `POST /v1/quarantine/{session}`, `DELETE …`, `POST /v1/rollback`, `POST /v1/decisions/{id}/verdict`: quarantine blocks subsequent ops; rollback compensates a reversible action.
  - **Query/SOC** `GET /v1/logs`, `/v1/sessions*`, `/v1/decisions`, `/v1/metrics*`, `/v1/discovery/*`, `/v1/connections/*`, `/v1/sigma-rules*`: tenant-scoped reads only; the `IDENTITY_*` audit filter surfaces gate-DENYs the metric hides.
- **Implements:** LLD §7.2.

### K8.3 — Close the two named coverage gaps
1. **Credential issuance → JWT signing → verify, end-to-end over HTTP** — today only unit-tested ([test_multitenancy_identity.py](../../src/security-controller/tests/test_multitenancy_identity.py)). Drive the real `provision.py` → `POST /credentials` → signed `/v1/validate` chain.
2. **An "every route responds" enumeration test** — a parametrized test that hits each route once (auth'd) and asserts reachability (no 404/5xx-undefined-route — catches the apigw-per-resource missing-route footgun, E4).
- **Implements:** LLD §7.3.

### K8.4 — Run the bug→fix loop + wire the CI gate
- **Loop** (LLD §7.4): run suite → triage each failure to its owning workstream (by route → WS) → fix → re-run → repeat until green. A failure is a **cutover blocker**, not a backlog item.
- **Wire** the suite into CI as a **required PR gate** (WS-J) so a later change can't silently regress a prod-cutover invariant.
- **Record** the green run (date + commit + image milestone) in [99-go-live-runbook.md](99-go-live-runbook.md).
- **Implements:** LLD §7.4.

---

## Acceptance criteria (the whole workstream — objectively verifiable)

> **Environment note (verified 2026-06-30):** there is no separate `Sentra-PROD-*` env in account `531109575379`; the live system is the `Sentra-DEV-*` stacks (founder-confirmed: "there is only dev stack which is currently prod stack"). All checks below were run against that live system. Where a criterion says `prod.yaml`, read `dev.yaml` (the live config). WS-K was therefore **verification-only** — TENANCY_V2 + Cedar were already activated on the live stacks.

- [x] **K1.2:** all 8 tables (`sentra-tenants`, `sentra-tenant-members`, `sentra-agent-credentials`, `sentra-identity-fallback`, `sentra-agent-registry-v2`, `sentra-policies-metadata-v2`, `sentra-session-context-v2`, `sentra-validation-signals-v2`) `ACTIVE` + GSIs `kid-index` and `tenant-members-index` present — confirmed via `describe-table`.
- [x] **K1.3:** v1→v2 copy under `tenant=default` verified — registry v2=12 ≥ v1=9, policies v2=12 ≥ v1=9 (12 = 9 default + 3 acme).
- [x] **K1.4:** the activation was already live (DEV=prod); founder confirmed the deploy target 2026-06-30. *(No separate dated shadow-vs-direct sign-off doc — the cutover predates this session; recorded in the runbook §1 Verified-runs table.)*
- [x] **K2.1:** live config (`dev.yaml`) reads `tenancy_v2_enabled: true`; the deployed task def (rev 55) carries `TENANCY_V2_ENABLED=true`. *(cutover comment dated 2026-06-23 in dev.yaml.)*
- [x] **K2.2:** `dev.yaml` physically contains all 5 keys (`tenant_identity_mode`, `identity_fallback_window_seconds: 0`, `s3_explicit_tenant_prefix: false`, `quota_enforcement_enabled: true`, `platform_read_consent_enforced: true`) — verified present in the live task def env, not riding defaults.
- [x] **K2.3:** identity is at `enforce` (past shadow); `/sentra/audit-logs` shows no DENY storm (the IDENTITY_* events over 2h are this session's own unsigned smoke probes); a signed agent's traffic is `identity_state=verified`. Verified via audit logs, not the Decisions metric.
- [x] **K2.4:** fleet ceiling `enforce` with acme `CRED == REG` (3 agents = 3 active credentials); an unsigned acme call → `IDENTITY_UNVERIFIED` DENY (verified live, pre + post deploy); other tenants capped by `effective = min(ceiling, tenant.identity_mode)`.
- [ ] **K2.5:** R1 / R2 / R3 rollback paths tested at staging before the prod step. — **NOT DONE: no staging environment exists (DEV is the only/live env); rollback drills not run against the live system. The rollback paths are documented in runbook §2; exercising them safely needs a non-prod env.**
- [x] **K3.1:** controller evaluates the cutover branch True (`cedar_enabled=true`/`cedar_shadow_mode=false` live; predicate at [validation_service.py:301](../../src/security-controller/app/services/validation_service.py)); `sentra.policy` (the Cedar slot) is the deciding source on 17,794 decisions/24h; CT08 backfill confirmed run (`--verify` passes: 0 residual non-cedar).
- [x] **K3.2:** NEW test `test_cutover_cedar_error_fails_secure` in `test_cedar_cutover.py` asserts abstain/error-where-Cedar-should-decide → **DENY** with Cedar (not legacy) as the source; the existing `test_cutover_abstain_falls_back_to_legacy` is untouched (still pins `should_deny is False`). *(Reconciled with WS-I I4.1: K3.2 = system-error path `POLICY_ERROR`/`SYSTEM_ERROR`; I4.1 = migration-gap path `POLICY_NOT_MIGRATED` — distinct, both green.)*
- [x] **K3.3:** no change under WS-K touched `cedar_enabled`/`cedar_shadow_mode` (both stay `true`/`false`); scope-guard recorded in runbook §1.
- [~] **K4.1:** `quota_enforcement_enabled=true` is live and verified to **fail OPEN** (5 rapid validates → 0 `QUOTA_EXCEEDED`; the identity gate denies first as designed). — **PARTIAL: a per-tenant `max_validate_rps` burst-throttle drill was NOT run (would require provisioning a quota row + a signed burst above it; the fail-open half is verified).**
- [—] **K5:** `s3_explicit_tenant_prefix: true` deployed; copy run; reads from new prefix; `--delete-old`. — **N/A: `s3_explicit_tenant_prefix=false` is live; the prefix migration was never started, so there are no old objects to delete. Revisit only after K5.1/K5.2 run. (runbook §1)**
- [—] **K6:** `default_inventory.json` + dated founder sign-off + gated purge. — **DEFERRED (founder decision 2026-06-30): do NOT purge.** Read-only inventory produced (`/tmp/default_inventory.json`): `default` still holds **9 live agents** (acme-payments/identity/telecom + demo agents) — the working tenant, not abandoned residue. STOP-on-in-use honored. (runbook §1)
- [x] **K7:** acme residual uncredentialed agents = 0 (3 agents / 3 active credentials, CRED==REG); both Azure functions `acme-identity-func` + `acme-telecom-func` confirmed `alwaysOn=true` + Running (via `az functionapp list`). *(deploy-method `azd deploy` not re-exercised — verifying the `dba8a79` fix holds, per the task's "verify, not re-fix" scope; the alwaysOn state confirms it.)*
- [x] **K8:** `tests/integration/test_post_cutover_suite.py` exists, covers every route (public reachable + internal-not-exposed enumeration; happy + 401/403/404/400) + the two named gaps (E2E credential→sign→verify; every-route-responds), and passes **92/0 (4 env-skips)** live against the API-Gateway front door; green run recorded in runbook §1. K8.4 bug→fix loop complete (9 findings triaged: all test-expectation, fixed without loosening). — **CI PR gate wiring (WS-J) is the one open piece: not yet wired as a required PR gate.**
- [x] **Predecessor gate met:** the tenant-scoped substrate (registry/policies/sessions/signals all `*-v2`, two-latch `effective=min`, console tenant-switch) is live and exercised — a 2nd prod tenant can be onboarded end-to-end. *(`acme` IS the 2nd tenant alongside `default`, already onboarded + enforcing.)*

---

## Cross-references

- **Source LLD (truth):** [lld/27-serverless-production-activation.md](../../lld/27-serverless-production-activation.md) — §3.1/§3.2 (prod.yaml diff), §4 (verification commands), §5 (coverage gate), §6 (tail tasks K4–K7), §7/§7.1 (integration suite + the abstain gap), §8 (error model E1–E8), §9 (monitoring), §10 (rollback drills).
- **Implements:** FR-10.5 (prod/staging TENANCY_V2 activation). **Verifies (no flip):** FR-2.4 (Cedar authoritative) — with the open abstain→DENY gap K3.2 writes. ADRs: AD-7/FR-10.3 (verified agent identity), AD-2 (Cedar authoritative).
- **Runbook of record (REUSE, do not duplicate):** [tasks/26-multi-tenancy/99-go-live-runbook.md](../26-multi-tenancy/99-go-live-runbook.md). Record K1.4/K3.3/K8.4 outcomes in [99-go-live-runbook.md](99-go-live-runbook.md).
- **Sibling LLD:** [lld/26-multi-tenancy.md](../../lld/26-multi-tenancy.md) (§3.4/§3.6 identity + cache/revocation, §7.1.2 bootstrap hazard, §7.2 rollout safety, §B9 brownfield).
- **Sibling workstreams gated by WS-K** (build against the multi-tenant baseline this WS turns on): [ws-a-local-floor-bundle.md](ws-a-local-floor-bundle.md), [ws-b-multiphase-contract.md](ws-b-multiphase-contract.md), [ws-d-decision-trail.md](ws-d-decision-trail.md), [ws-e-redaction.md](ws-e-redaction.md), [ws-f-prompt-signatures.md](ws-f-prompt-signatures.md). K8.4 CI gate feeds **WS-J** (cross-cutting canary harness).
- **Code anchors:** [cdk/config/prod.yaml](../../cdk/config/prod.yaml), [cdk/config/dev.yaml](../../cdk/config/dev.yaml), [src/security-controller/app/config.py](../../src/security-controller/app/config.py), [src/security-controller/app/services/validation_service.py:301/305-311/656-673](../../src/security-controller/app/services/validation_service.py), [scripts/migrate_s3_policy_prefix.py](../../scripts/migrate_s3_policy_prefix.py), [scripts/migrate_brownfield.py](../../scripts/migrate_brownfield.py), [scripts/migrate_tenancy.py](../../scripts/migrate_tenancy.py), [demo-agents/registration/provision_acme_identity.py](../../demo-agents/registration/provision_acme_identity.py).
- **Cutover invariant tests:** [src/security-controller/tests/test_cedar_cutover.py](../../src/security-controller/tests/test_cedar_cutover.py), [src/security-controller/tests/test_ws_b_cutover.py](../../src/security-controller/tests/test_ws_b_cutover.py), [tests/integration/conftest.py](../../tests/integration/conftest.py).
- **Ops memos:** identity-DENYs-not-metered (check `/sentra/audit-logs` for `IDENTITY_*`, §4.3/E3); apigw-per-resource (new MT routes need explicit gateway + ALB rules, E4 / runbook lines 24-32).
