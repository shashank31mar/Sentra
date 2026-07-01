# Serverless-Edition Go-Live Runbook — cutover / rollout / rollback

**Status:** Draft — rollout sequence + gates for the Serverless-edition build (WS-0…WS-K).
**Owner:** founder — Shashank Gupta (the named sign-off on every human-gated step below).
**Scope:** the **order** flips happen in, the **gate** that must be true before each flip, the shadow→enforce sequencing per flip, and the **rollback** per flip. Real config keys throughout: [cdk/config/prod.yaml](../../cdk/config/prod.yaml) `tenancy_v2_enabled` / `tenant_identity_mode` / `cedar_enabled` / `cedar_shadow_mode` (+ the appended tenancy-identity keys).

> **Two runbooks of record this extends — do not duplicate them:**
> - **First predecessor:** [ws-k-production-activation.md](ws-k-production-activation.md) — the TENANCY_V2 prod flip + tail tasks + Cedar verify-only. WS-K is **step 0** of this runbook; nothing else in the Serverless slice that touches a 2nd prod tenant proceeds until WS-K's predecessor gate is met.
> - **Runbook of record (dev go-live):** [tasks/26-multi-tenancy/99-go-live-runbook.md](../26-multi-tenancy/99-go-live-runbook.md) — the gated-cutover steps, the brownfield/B3 tail, and the rollback section. WS-K extends it for prod; this doc cross-links it and does not re-derive its steps.

---

## 0. The flip inventory (every irreversible/stateful flip, in order)

| # | Flip | Config key / action | Gate that must hold first | Reversible? |
|---|---|---|---|---|
| 0a | **WS-K** TENANCY_V2 prod (shadow) | `tenancy_v2_enabled: false→true`; add `tenant_identity_mode: shadow` | v2 tables exist + v1→v2 copy ran (WS-K K1.2); **founder sign-off** (K1.4) | yes — `tenancy_v2_enabled: false` + `cdk deploy` |
| 0b | **WS-K** per-tenant TENANCY_V2 enforce | `tenant_identity_mode: shadow→enforce` + `PATCH tenant {identity_mode: enforce}` | per-agent credential coverage **≈100%** for that tenant (LLD 26 §7) | yes — ceiling→`shadow` (≤30 s TTL) |
| 0c | **WS-K** Cedar prod | none — `cedar_enabled: true` / `cedar_shadow_mode: false` **already set** | VERIFY-ONLY; **never re-flipped here** (WS-K K3.3) | n/a |
| 0d | **WS-K** S3 `--delete-old` (B3) | `s3_explicit_tenant_prefix: true` → copy → `--delete-old` | all reads confirmed served from new prefix first | **point-of-no-return** for old prefix |
| 0e | **WS-K** `default` brownfield purge | `migrate_brownfield.py purge` | inventory = 0 + **founder sign-off** (irreversible) | **IRREVERSIBLE** |
| **GATE 1** | **WS-0 spike sign-off** | — | dated, founder-signed packet recorded in `00-index.md` | gate, no flip |
| 1 | **WS-I→WS-A** local-floor bundle | signed-bundle distribution; SDK floor enforce | WS-0 packet committed WS-A (AgentCore kill not triggered); bundle/grammar co-spec | per-flip below |
| 2 | **WS-F** prompt-signature enforce | Sigma rule-pack activation | shadow soak clean | rule-pack revert |
| 3 | **WS-B/WS-D/WS-C** multi-phase + scheduler + trail | `phase` contract growth (no global flag) | per-phase; WS-C/WS-D one execution model | phase-scoped revert |
| 4 | **WS-E Tier-1** edge redaction GA | redactor ships at GA (always-on edge) | — (redactor ships regardless) | rule-pack revert |
| **GATE 2** | **WS-E HIPAA GA claim** | — | redaction **recall ≥ Appendix-G target** (WS-0 recall-delta) **AND** counsel BAA sign-off (45 CFR 164.308/164.314) | gate, no flip |
| 5 | **WS-E Tier-2** server-side NER + feedback store | `feedback_store` opt-in (default OFF, per-DPA) | GATE 2 + redaction-quality eval + DSAR/deletion API | opt-in flag → OFF |

`tenancy_v2_enabled`, `tenant_identity_mode`, `cedar_enabled`, `cedar_shadow_mode` are the four real `prod.yaml` keys; the tenancy-identity keys (`identity_fallback_window_seconds`, `s3_explicit_tenant_prefix`, `quota_enforcement_enabled`, `platform_read_consent_enforced`) are **absent today and must be ADDED** (WS-K Model #3 — an absent key silently rides its conservative-off default).

---

## 1. Step 0 — WS-K Production Activation (the first predecessor)

**This whole runbook is blocked on WS-K's predecessor gate** (WS-K §1 "Blocks: everything else in the Serverless slice that touches a 2nd prod tenant"). Execute WS-K end-to-end first; the steps live in [ws-k-production-activation.md](ws-k-production-activation.md) and reuse [tasks/26-multi-tenancy/99-go-live-runbook.md](../26-multi-tenancy/99-go-live-runbook.md). Summary of its ordered flips (full detail + rollback in WS-K §2–§6):

1. **K1 — pre-flight + founder sign-off gate.** v2 tables (`sentra-tenants`, `sentra-tenant-members`, `sentra-agent-credentials` + `kid-index`, `tenant-members-index`, `sentra-identity-fallback`) exist via `describe-table`; v1→v2 copy under `tenant=default` ran; shadow-vs-direct decision recorded; **dated founder sign-off** captured. No sign-off → STOP.
2. **K2.1/K2.2 — TENANCY_V2 prod flip (shadow).** `prod.yaml:22` `tenancy_v2_enabled: false→true`; **append** `tenant_identity_mode: shadow`, `identity_fallback_window_seconds: 0`, `s3_explicit_tenant_prefix: false`, `quota_enforcement_enabled: true`, `platform_read_consent_enforced: true`. **Staging first, soak, then prod.**
3. **K2.3 — deploy + verify shadow.** `cdk deploy <ComputeStack> <StorageStack>`; controller logs `identity_state=verified` for signed agents; behavior unchanged; **no `IDENTITY_*` DENY storm in `/sentra/audit-logs`** (identity DENYs skip the Decisions metric — check audit logs, not the metric).
4. **K2.4 — per-tenant enforce flip** — gated, see §2 below.
5. **K3 — Cedar VERIFY-ONLY.** Confirm the deployed image evaluates the cutover branch True (`validation_service.py:301`), a prod validate trace shows Cedar as the deciding source, CT08 `.cedar` backfill ran, and the legacy-retired→fail-secure-DENY path holds (`:667`). **No PR under this runbook touches `cedar_enabled`/`cedar_shadow_mode`** — there is nothing to flip.
6. **K4/K5/K6 — tail tasks** (RPS-quota ceiling; S3 `--delete-old`; `default` purge) — flips 0d/0e, see §6.

**WS-K predecessor gate (must be GREEN before any of §3 onward):** a 2nd prod tenant can be onboarded end-to-end (registry/policies/sessions/signals tenant-scoped, console tenant-switched).

### Verified runs (K8.4 record)

> **Note on environment:** there is no separate `Sentra-PROD-*` CloudFormation env in account `531109575379`; the live system runs on the `Sentra-DEV-*` stacks, deployed from `cdk/config/dev.yaml`, which already carries WS-K's end-state (`tenancy_v2_enabled: true`, `tenant_identity_mode: enforce`, all 5 keys, Cedar cutover, real `*.aegionai.ai` cert). "Prod activation" = the live DEV stacks. Where the steps above say `prod.yaml` / `<env>.yaml`, read `dev.yaml` for this account.

| Date | Commit | Image | What was verified |
|---|---|---|---|
| 2026-06-30 | `fee2cb7` (+ WS-I working tree) | `security-controller:milestone-89` (digest `f198190…`), task def rev **55** | **WS-I Group 1 deployed** (`LEGACY_RETIRED=false`, `LOCAL_FLOOR_ENABLED=true` live in rev 55; no regression — unsigned validate still `IDENTITY_UNVERIFIED` DENY). **K8 post-cutover suite: 92 passed / 4 skipped / 0 failed** live against the API-Gateway front door (`iw3limi4k7…/prod`). 4 skips are environmental (operator ALB-OIDC writes + signed-JWT provisioning, not satisfiable headless). **Acceptance verified live:** K1.2 (8 tables ACTIVE + `kid-index`/`tenant-members-index`), K1.3 (v2 12 ≥ v1 9), K2.1/K2.2 (5 keys present + end-state), K2.4 (acme `enforce`, CRED==REG 3=3), K3 (cutover predicate True, 17,794 `sentra.policy` decision events/24h), K4 (quota enabled but fails open — no `QUOTA_EXCEEDED`), K7 (acme residual=0; both `acme-identity-func`/`acme-telecom-func` `alwaysOn=true`, Running). |

**K3.3 scope-guard (recorded):** no change under WS-K touched `cedar_enabled`/`cedar_shadow_mode` (both stay `true`/`false`). WS-I added `legacy_retired` (default `false`, NOT flipped) — the legacy-retirement flip is the founder-gated step in §4 Step 1b, gated on `translate_policies_to_cedar.py --verify` (passing on the live env: 0 residual non-cedar, generator-version parity).

**K5.3 / K6 tail steps — status 2026-06-30:**
- **K5.3 (S3 `--delete-old`): N/A.** `S3_EXPLICIT_TENANT_PREFIX=false` is live; the prefix migration was never started, so there are zero old objects to delete. Revisit only after K5.1/K5.2 are run.
- **K6 (`default` brownfield purge): DEFERRED — founder decision 2026-06-30, do NOT purge.** The read-only inventory (`migrate_brownfield.py inventory`) shows `default` still holds **9 live agents** (acme-payments/identity/telecom + the demo agents currently serving traffic) and their policies. `default` is the working tenant, not abandoned residue — purging it would erase in-use agents. Re-evaluate K6 only once a 2nd prod tenant fully owns the live traffic and `default` is genuinely empty of in-use agents.

---

## 2. The per-tenant TENANCY_V2 enforce flip (flip 0b) — gated on credential coverage

The one safety-critical flip in WS-K. **Two-latch model: effective mode = `min(env ceiling, tenant.identity_mode)`** — a tenant enforces only when BOTH the env ceiling AND its tenant row are `enforce`.

**GATE:** the onboarded prod tenant's **per-agent credential coverage ≈ 100%** (LLD 26 §7 bootstrap hazard). Raising the fleet ceiling to `enforce` before every agent signs JWTs would DENY all their tokenless traffic (`IDENTITY_UNVERIFIED`).

**Sequencing (shadow→enforce):**
1. Tenant onboarded at `identity_mode: shadow`; agents provisioned + signing (`aegion-guard[identity]`, ES256). Verify `identity_state=verified` in shadow — observes, never routes.
2. Drive credential coverage to ≈100%. During the flip, optionally raise `identity_fallback_window_seconds` (e.g. `86400`) as a grace window (alarmed `IdentityFallback`), then drive back to `0` as coverage → 100%.
3. **Flip:** `prod.yaml` `tenant_identity_mode: shadow→enforce` + redeploy (raises the fleet ceiling), **AND** `PATCH /v1/tenants/{tid} {identity_mode: enforce}` for that tenant.
4. **Verify:** signed calls route; an unsigned call from that tenant DENYs `IDENTITY_UNVERIFIED`, audited under `_unverified`. Other prod tenants stay capped by their own row.

**Rollback (tested at staging first):**
- Per-tenant: `PATCH /v1/tenants/{tid} {identity_mode: shadow|off}` — propagates ≤ 30 s (mode-cache TTL).
- Fleet kill-switch: `prod.yaml` `tenant_identity_mode: shadow|off` + redeploy — caps everyone.
- Full revert: `tenancy_v2_enabled: false` + `cdk deploy` → back to v1 tables.

---

## 3. GATE 1 — WS-0 measure-first spike sign-off (before A / C / D / E build)

**The teeth are sequencing, not a date.** Do **not** decompose or build **WS-A** (local floor), **WS-C** (DAG redactor/scheduler), **WS-D** (decision trail), or **WS-E** (deep tier) until a **dated, founder-signed result packet** exists and its gate date is recorded in [00-index.md](00-index.md) as the entry precondition (WS-0 §1, M0-6.3).

**The packet must contain** (WS-0 acceptance criteria):
- the §6.4 combined GA-gate table (escalation rate + escalated-path p99, measured against the **real** `aegionai-ml-classifier` profile — not mocked);
- the Cedar escalate-fraction (local-resolve vs escalate, residual #6);
- the masked-vs-unmasked **recall-delta** (residual #5 — feeds GATE 2 below);
- the AgentCore kill-checks **(d)** off-AWS interception scope (verified `[FACT]` from AWS docs / named SA, not a marketing page) + **(e)** not-behind-Gateway segment size;
- both kill adjudications + per-row disposition for WS-A/C/D/E.

**Two kills the packet decides:**
- **Numeric kill** (gates synchronous-deep): worst-quadrant high-escalation AND low masked-recall → re-scope.
- **AgentCore kill** (gates whether **WS-A is built at all**): if AgentCore governs customer-owned/off-AWS agents broadly AND the not-behind-Gateway segment is small → **WS-A is NOT committed**; fall back to connector/SDK-as-thin-PEP against the hosted PDP.

**Human sign-off:** single named sign-off — **founder (Shashank Gupta)**. **No date = no auto-pass**: if the founder cannot own the spike in the build window, the gate does **not** waive — A/C/D/E stay blocked (WS-0 §error model). There is no timeout auto-pass.

**"Rollback":** none needed — this is a gate, not a flip; WS-0 ships no product to `main`. If a row is killed, its LLD is never commissioned.

---

## 4. Local-floor + signature + multi-phase flips (steps 1–3)

These build **only after GATE 1**. Each ships shadow→enforce; rollback is a flag/rule-pack revert (no data migration).

**Step 1 — WS-I→WS-A local-floor bundle (only if WS-0 committed WS-A).**
- WS-I (hosted) emits the signed policy bundle + manifest; WS-A (SDK) interprets it. **They share one closed-subset grammar — co-specified in the LLD or they diverge into a silent fail-open.** Verify interpreter and emitter agree on every construct before enforce.
- **Shadow→enforce:** SDK floor runs in shadow (escalate-on-every-unrecognized-construct, fail-closed), compared against the hosted decision; flip to local-enforce only after the differential corpus shows 0 disagreements on the recognized subset.
- **Rollback:** disable local-floor enforce (revert to escalate-all-to-hosted PDP). The bundle is signed + staleness-bounded — a stale/absent bundle fails closed to hosted, never fails open.

**Step 1b — WS-I `legacy_retired` flip (founder-gated, FR-2.4 end state — I3.3).**
- **Precondition (HARD GATE, I3.2):** run `python scripts/translate_policies_to_cedar.py --verify` against the target env. It must exit 0 — **0 policies with `policy_format != cedar` AND every co-artifact at the current `GENERATOR_VERSION`.** A non-zero exit means the CT08 backfill is incomplete; do NOT proceed.
- **The flip:** set `legacy_retired: true` in the target env's `cdk/config/<env>.yaml` + `cdk deploy <env>-Compute-Stack`. After this, a Cedar ABSTAIN (missing `.cedar` co-artifact) fails **secure → DENY** (`POLICY_NOT_MIGRATED`, audit-only/not-metered) instead of falling back to the now-retired legacy engine.
- **FOOTGUN (E12):** flipping `true` *before* the backfill verify passes = a self-inflicted DENY storm on real agents. The flag defaults `false` precisely so this can never happen by omission.
- **Rollback:** set `legacy_retired: false` + redeploy — instantly restores the permissive legacy fallback (the rollout-era behavior, still tested and intact). No data migration.
- **Watch:** `CedarAbstainDenied` (should be ~0 post-backfill; any non-zero = a co-artifact defect to fix, not a flip to revert) vs `CedarAbstainFallback` (must be 0 once `legacy_retired:true`).

**Step 2 — WS-F prompt-signature enforce.**
- **Shadow→enforce:** new Sigma rule-pack runs in shadow against live traffic; promote to blocking only after the shadow FP rate is acceptable.
- **Rollback:** revert the rule-pack (Sigma rules are data, not a deploy) — deterministic, instant.

**Step 3 — WS-B multi-phase contract + WS-C scheduler + WS-D decision trail.**
- No global flag — growth is **per `phase`** on `ValidationRequest`. `request` is live today; `content`/`output`/`memory` light up per phase.
- **WS-C and WS-D define ONE execution model** (the HLD's single most important reconciliation): WS-C decides which layers run; WS-D records ran/not-ran/verdicts (coverage set). WS-D must consume WS-C's "layers that could run for this phase" — if WS-C is not yet built, WS-D hooks the current fixed-sequential pipeline (`validation_service.py:220`) and coverage = the static ordered list.
- **Shadow→enforce:** each new phase ships observe-only first; enforce per phase after its detectors are validated.
- **Rollback:** phase-scoped — drop the phase back to observe-only or remove it from the contract; the `request` path is unaffected.

---

## 5. GATE 2 — redaction recall-target + counsel-BAA gate (before HIPAA GA claim, WS-E)

The **Tier-1 edge redactor ships at GA regardless** (always-on at the SDK edge — structured PII masked inline, raw never leaves). **What is gated is the HIPAA/PHI GA *claim*** and the Tier-2 server-side path.

**GATE (both must hold before any "Serverless serves HIPAA/PHI" GA claim):**
1. **Redaction recall ≥ the Appendix-G target** — measured via the WS-0 masked-vs-unmasked recall-delta on the obfuscated/non-US corpus, reported **per attack class** (exfiltration + indirect-injection separately — averaging hides the worst quadrant). The structured-token redactor is **not declared the GA gate** until this delta is on paper (WS-E GATE / WS-0 residual #5).
2. **Counsel BAA sign-off** — BAA obligations (**45 CFR 164.308 / 164.314**) confirmed by counsel **before the HIPAA GA claim ships**. Release-gate dependency, not a code check.

**Step 5 — WS-E Tier-2 (after GATE 2):**
- Server-side semantic NER (free-text PHI, transient under BAA — never retained, never logged, no human access; **not** "machine-unreadable" — that needs the Nitro Enclave, later).
- Feedback store: **opt-in per-DPA, default OFF** — an accidental default-ON is a clause-(b) consent breach. Gated additionally on the redaction-quality eval + a DSAR/deletion API (GDPR).
- **Honest claim:** *"transient + not-retained + not-logged + no human access under a BAA"* — not "machine-unreadable by AegionAI."

**Rollback:** feedback-store opt-in flag → OFF (per tenant; stops all writes); Tier-2 NER can be disabled, falling back to Tier-1 edge masking + in-VPC routing for PHI segments. Retract the HIPAA GA claim if the recall target regresses on the feedback corpus re-score.

---

## 6. WS-K tail flips (steps 0d / 0e) — irreversible, sign-off-gated

Run these per WS-K K5/K6 (detail + footguns there); they are the two point-of-no-return steps.

**Flip 0d — S3 `--delete-old` prefix migration (WS-K K5):**
1. `s3_explicit_tenant_prefix: false→true` in `prod.yaml` + deploy — new writes go to `tenants/{tid}/policies/agents/…`; reads **dual-read** both layouts. No data deleted.
2. `python scripts/migrate_s3_policy_prefix.py` — copies legacy objects to the explicit prefix.
3. **Only after confirming all reads resolve from the new prefix**, `scripts/migrate_s3_policy_prefix.py --delete-old`. **Point of no return for the old prefix.** `--delete-old` before that confirmation → policies vanish → fail-secure deny-by-default. Never run "to clean up."

**Flip 0e — `default` brownfield purge (WS-K K6 — IRREVERSIBLE, human sign-off):**
1. `python scripts/migrate_brownfield.py inventory --out default_inventory.json` (read-only, safe). Dev showed **0 credentials under `default`** — re-run for prod.
2. **Founder sign-off** re-confirming no real customer data under `default` — separate, explicit, dated, written; attach `default_inventory.json`.
3. `python scripts/migrate_brownfield.py purge --confirm-no-customer-data` — **only on explicit go**. **If inventory shows ANY credential under `default`, STOP** — re-import under a real tenant first. Never run as part of an automated rollout.

---

## 7. Human-sign-off gates (consolidated — the irreversible/teeth list)

| Gate | What it blocks | Sign-off | Reversible after? |
|---|---|---|---|
| WS-K K1.4 founder sign-off | the prod TENANCY_V2 flip (0a) | founder (dated, written) | yes (flag revert) |
| **WS-0 spike packet** (GATE 1) | WS-A/C/D/E build | founder (the single named sign-off; **no date = no waiver**) | gate, no flip |
| **counsel BAA + recall target** (GATE 2) | the HIPAA/PHI GA **claim** + WS-E Tier-2 | counsel (BAA) + founder (recall packet) | claim retractable; feedback-store opt-in → OFF |
| WS-K K6.2 brownfield purge (0e) | the `default` purge | founder, re-confirming no customer data | **IRREVERSIBLE — no rollback** |

---

## 8. Cross-references

- **First predecessor (step 0):** [ws-k-production-activation.md](ws-k-production-activation.md) — TENANCY_V2 prod flip + Cedar verify-only + tail tasks; its predecessor gate blocks everything from §3 on.
- **Runbook of record (REUSE, do not duplicate):** [tasks/26-multi-tenancy/99-go-live-runbook.md](../26-multi-tenancy/99-go-live-runbook.md) — gated-cutover steps, brownfield/B3 tail, rollback section.
- **GATE 1 source:** [ws-0-measure-first-spike.md](ws-0-measure-first-spike.md) — the dated founder-signed packet; gate date recorded in [00-index.md](00-index.md).
- **GATE 2 source:** [ws-e-redaction.md](ws-e-redaction.md) — recall target (Appendix-G), counsel BAA (45 CFR 164.308/164.314), Tier-1/Tier-2 split, feedback-store opt-in.
- **Sibling WS docs sequenced here:** [ws-a-local-floor-bundle.md](ws-a-local-floor-bundle.md), [ws-b-multiphase-contract.md](ws-b-multiphase-contract.md), [ws-c-dag-scheduler.md](ws-c-dag-scheduler.md), [ws-d-decision-trail.md](ws-d-decision-trail.md), [ws-f-prompt-signatures.md](ws-f-prompt-signatures.md), [ws-i-cedar-engine.md](ws-i-cedar-engine.md), [ws-g-console.md](ws-g-console.md), [ws-h-metering.md](ws-h-metering.md), [ws-j-canary-tests.md](ws-j-canary-tests.md).
- **Config anchors:** [cdk/config/prod.yaml](../../cdk/config/prod.yaml) (`tenancy_v2_enabled:22`, `cedar_enabled:30`, `cedar_shadow_mode:31`; tenancy-identity keys to be appended), [cdk/config/dev.yaml](../../cdk/config/dev.yaml) (reference posture), [src/security-controller/app/config.py](../../src/security-controller/app/config.py) (conservative-off defaults).
- **Code anchors:** [src/security-controller/app/services/validation_service.py:220/301/667](../../src/security-controller/app/services/validation_service.py).
- **LLD:** [lld/26-multi-tenancy.md](../../lld/26-multi-tenancy.md) §7 (bootstrap hazard / coverage gate); parent HLD [hld/serverless-edition.md](../../hld/serverless-edition.md) §6.4 (GA-gate table), §6.2(e) (redaction), §8 (MEASURE-FIRST GATE + hand-off rows).
- **Ops memos:** identity-DENYs-not-metered (watch `/sentra/audit-logs` for `IDENTITY_*`, not the Decisions metric); API-GW-per-resource (new routes need explicit gateway + ALB rules).
