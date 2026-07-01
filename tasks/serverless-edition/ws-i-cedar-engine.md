# WS-I — Cedar policy engine (abstain→DENY fail-secure + bundle-emit + differential conformance)

**Workstream:** WS-I (Serverless edition) — Cedar policy engine. *(This is the single canonical workstream doc: scope + granular tasks; the design lives in the LLD below.)*
**Derived from:** [lld/28-cedar-policy-engine.md](../../lld/28-cedar-policy-engine.md) (APPROVED, owner-reviewed, 15 sections). **The LLD is the source of truth** — when this breakdown and the LLD disagree, the LLD wins; fix this file.
**Status:** Group 1 — **✅ DONE** (built + deployed to the live system 2026-06-30, image `milestone-89`/task-def rev 55; unit suite 569 green; see acceptance checklist below — one docs-propagate follow-up open on I1/AD-2). Group 2 — **GATED on WS-0 spike (not started; do not code).**
**Owner:** TBD.

## Dependencies
- **Depends on:** the existing Cedar engine — DONE & authoritative/enforcing on dev (LLD 28 §1.2a, §2; `app/validators/cedar/*`, [validation_service.py:301](../../src/security-controller/app/services/validation_service.py#L301)). Group 1 needs only this. Group 2 (I6–I8) additionally depends on **WS-0's signed spike packet** (HLD §8 measure-first gate).
- **Blocks:** **WS-A (in-process local floor + signed-bundle distribution)** — WS-A's stdlib-only SDK interpreter reads the bundle this WS **emits** (I6). The **bundle wire schema** (LLD §5.2) is the shared contract; WS-A cannot finalize its interpreter until it's fixed. The **differential corpus** (I7) is co-owned with WS-A.
- **Shared files / contracts:** `app/validators/cedar/` (engine/generator/evaluator/loader/artifact); [validation_service.py:301-311](../../src/security-controller/app/services/validation_service.py#L301) (cutover branch + the §4 abstain→DENY change); the signed **bundle wire schema** (LLD §5.2, shared with WS-A); `tests/integration/` (the live e2e Cedar test, LLD §14.6). Pairs: WS-A (bundle consumer), WS-F (prompt-signature dialect in the closed subset), WS-K (Cedar prod verify-only).

---



---

## Read before coding (the invariants the LLD makes load-bearing — hold these or you fail OPEN)

1. **Cedar is DONE + authoritative + enforcing on dev — do NOT rebuild it.** The engine/evaluator/generator/loader/baseline/schema all exist and enforce on dev (LLD §1.2a, §1.3 status tables). `cedar_enabled` does **not** gate Cedar's *existence*; the cutover predicate is exactly `cutover = cedar is not None and settings.cedar_enabled and not settings.cedar_shadow_mode` ([validation_service.py:301](../../src/security-controller/app/services/validation_service.py#L301), LLD §2.3). I1/I2 are documentation + verify; the net-new code is I2 (the abstain→DENY change), I5 (metrics + kill-switch), and Group 2 (emit/corpus).

2. **The abstain→DENY change is gated behind a NEW conservative-off flag `legacy_retired` (default false).** While `legacy_retired=false` (rollout), abstain → permissive legacy fallback — **unchanged**. Only `legacy_retired=true` (end state) makes abstain → fail-secure DENY `POLICY_NOT_MIGRATED`/−15 (LLD §4.2–§4.3). Do **not** edit the existing `test_cutover_abstain_falls_back_to_legacy` — it pins the rollout-era permissive behavior and is correct for `legacy_retired=false` (LLD §14.1 FOOTGUN).

3. **The CT08 `.cedar` backfill is a hard prerequisite gate on flipping `legacy_retired: true`.** Flipping it before every prod policy carries a `.cedar` co-artifact turns every un-backfilled policy's abstain into a hard DENY = self-inflicted DENY storm (LLD §4.4 FOOTGUN, E12). Sequence: backfill → verify `policy_format != cedar` count == 0 (and every co-artifact's `generator_version` == current) → only then flip (founder-gated).

4. **The `POLICY_NOT_MIGRATED` DENY is audit-only, NOT metered to the victim quota.** It is a fail-secure system-defect DENY, like identity-gate DENYs (LLD §12, E2). It must not inflate the tenant's metered `Decisions`/quota series — surfaced via the `CedarAbstainDenied` metric + `/sentra/audit-logs`, not charged. A flat console "decisions" panel is therefore NOT proof Cedar is clean (LLD §12 footgun).

5. **The local-floor kill-switch falls back to the HOSTED PDP, NOT deny-all.** `local_floor_enabled=false` for a scope routes every call to the hosted `/v1/validate` (the production network path) — enforcement is unbroken, only *where* it runs changes (LLD §1.2 tenet 5, §5.6). The off-state MUST set the SDK to network-required (existing `fail_secure=true` transport); reading it as "skip validation" is the catastrophe (LLD §5.6 FOOTGUN). Does not violate ADR-034.

6. *(Group 2 only)* **The emitter is an ALLOWLIST and the escalate unit is the WHOLE POLICY, never a single rule.** One out-of-subset rule ⇒ emit NO bundle for the entire policy (LLD §5.3). A per-rule emit that shipped allowlisted rules and held back only the out-of-subset rule re-opens ALLOW-by-omission (the §5.3 "why whole-policy" fail-open). `param_bounds` is integer `max_cents`, `deny_on_missing` carried; the worst bug is edge-ALLOW-where-server-DENY (LLD §5.2, §6.3 footguns).

---

# ████ GROUP 1 — CODEABLE NOW ████

> **Banner:** These milestones depend only on the existing (DONE) Cedar engine. They are **not** spike-gated and may proceed immediately. Cedar is already authoritative on dev; I1 documents it, I2 adds the flag-gated abstain→DENY, I3 is the backfill prerequisite, I4 is the new fail-secure test, I5 is metrics + kill-switch.

## Milestone I1 — Document/confirm the Cedar engine component (LLD §2; mostly verification — code is DONE)

This milestone produces **no engine code** — it is the LLD-anchored verification + the doc-propagation. The LLD §2 already documents the component; I1 confirms the cited `file:line` anchors are accurate and lands the AD-2 join-key tighten.

### I1.1 — Verify the documented symbols exist at the cited anchors (read-only)
- **Files (read-only verify):** [src/security-controller/app/validators/cedar/engine.py](../../src/security-controller/app/validators/cedar/engine.py), [evaluator.py](../../src/security-controller/app/validators/cedar/evaluator.py), [generator.py](../../src/security-controller/app/validators/cedar/generator.py), [schema.py](../../src/security-controller/app/validators/cedar/schema.py), [baseline-v1.cedar](../../src/security-controller/app/validators/cedar/baseline-v1.cedar), [entities.py](../../src/security-controller/app/validators/cedar/entities.py), [context.py](../../src/security-controller/app/validators/cedar/context.py), [policy_artifact.py](../../src/security-controller/app/validators/cedar/policy_artifact.py), [policy_loader.py](../../src/security-controller/app/validators/cedar/policy_loader.py).
- **Confirm (LLD §2.2 table):** `CedarPolicyEngine` ([engine.py:71](../../src/security-controller/app/validators/cedar/engine.py#L71)), `async validate(request) -> ValidationResult` ([:89](../../src/security-controller/app/validators/cedar/engine.py#L89)), `_validate_invoke_agent` ([:155](../../src/security-controller/app/validators/cedar/engine.py#L155)) — two AND-ed `is_authorized` calls (call-1 wins), `_map_use_tool_deny` ([:200](../../src/security-controller/app/validators/cedar/engine.py#L200)); `CedarEvaluator.is_authorized` ([evaluator.py:91](../../src/security-controller/app/validators/cedar/evaluator.py#L91)), `validate_policy_set` ([:114](../../src/security-controller/app/validators/cedar/evaluator.py#L114)); `generate_cedar` / `GENERATOR_VERSION="v1"`; `CEDAR_SCHEMA_VERSION="v1"`; the baseline `@id` rules `permit_use_tool`, `forbid_refund_over_cap`, `forbid_refund_missing_amount`, `forbid_high_fraud_identity`, `permit_invoke_agent`.
- **Implements:** LLD §2.2.
- **FOOTGUN (AD-2 boundary, LLD §2.1):** `cedarpy==4.8.4` is native-wheel-only (no `py3-none-any` fallback) — it **cannot** ride the stdlib-only SDK (`dependencies = []`). AD-2's "embeddable" holds for the **server host only**. The edge interpreter executes the decision Cedar already made expressed as data; it does not re-run the policy language. Do not document the SDK as embedding Cedar.

### I1.2 — Land the AD-2 join-key tighten + FR status edits (one propagate-change pass)
- **File:** [lld/ARCHITECTURE.md](../../lld/ARCHITECTURE.md) (AD-2 at line 327).
- **Change:** tighten the AD-2 text to read "embeddable on the server host; the SDK local tier interprets a derived signed bundle, not the native engine" (LLD §2.1, §15 Decisions).
- Land the FR-2.4 (Cedar dev-authoritative / prod-config-set) + FR-2.9 (egress = grown local-floor primitive, NOT-FOUND→GROW branch) status edits in the **same** `propagate-change` pass, not piecemeal (LLD §15; scope-doc acceptance "Propagation").
- **Implements:** LLD §2.1, §15.
- **FOOTGUN:** this is one pass across ARCHITECTURE + the sibling docs that cite AD-2 — a prose-only edit that leaves a sibling citing the old "Cedar is embeddable [everywhere]" text fails the propagation gate.

---

## Milestone I2 — abstain→DENY fail-secure under the NEW `legacy_retired` flag (LLD §4)

The one Group-1 behavior change. Adds a conservative-off flag and the fail-secure branch; the rollout path is untouched.

### I2.1 — Add the `legacy_retired` config flag (conservative-off)
- **Files:** the settings module that defines `cedar_enabled`/`cedar_shadow_mode` (the `settings` object read at [validation_service.py:300-301](../../src/security-controller/app/services/validation_service.py#L300)); the CDK config files [cdk/config/dev.yaml](../../cdk/config/dev.yaml), [cdk/config/prod.yaml](../../cdk/config/prod.yaml).
- **Change:** add `legacy_retired: bool`, **default `false`** (mirrors LLD 27's absent-key trap → conservative-off). Add the key to dev.yaml and prod.yaml with value `false` for now (the flip to `true` is founder-gated, post-backfill — NOT in this task; see I3).
- **Implements:** LLD §4.2.
- **FOOTGUN:** default must be `false`. An absent/true-by-default flag would turn every rollout-era abstain into a DENY before the backfill (E12).

### I2.2 — Add the `POLICY_NOT_MIGRATED` violation type + `_fail_secure_deny` helper
- **Files:** [src/security-controller/app/services/validation_service.py](../../src/security-controller/app/services/validation_service.py); the violation-type/penalty constants the pipeline uses (alongside `POLICY_NOT_FOUND`/`POLICY_DISABLED`); reuse the engine's `_deny` shape ([engine.py:238](../../src/security-controller/app/validators/cedar/engine.py#L238)).
- **Change:** add `POLICY_NOT_MIGRATED` as a **new fail-secure violation type, penalty −15** (dangerous-tier, matching `POLICY_NOT_FOUND`/`POLICY_DISABLED`). It is **distinct from `POLICY_ERROR`** so the audit trail separates "Cedar errored" from "no co-artifact under retired-legacy" (LLD §4.3). Add a `_fail_secure_deny(violation_type, penalty, reason)` helper that returns the engine `_deny` shape.
- **Implements:** LLD §4.3.

### I2.3 — Branch the abstain handling on `legacy_retired`
- **File:** [src/security-controller/app/services/validation_service.py:303-311](../../src/security-controller/app/services/validation_service.py#L303) (the cutover abstain branch).
- **Change:** after `policy_result = cedar.validate(request)`, when `policy_result.is_abstain`, branch on `settings.legacy_retired`:
```python
if cutover:
    policy_result = _capture(await _timed("policy", cedar.validate(request)))
    if policy_result.is_abstain:
        if settings.legacy_retired:
            # End state (FR-2.4): legacy retired. An abstain here is a missing
            # .cedar co-artifact on a policy that should carry one — a DEFECT.
            metrics.incr("CedarAbstainDenied", tags={"agent_id": request.agent_id})
            logger.error("Cedar abstained under legacy_retired for %s; fail-secure DENY",
                         request.agent_id)
            policy_result = _fail_secure_deny(
                violation_type="POLICY_NOT_MIGRATED", penalty=-15,
                reason="Policy not Cedar-migrated; legacy engine retired (fail-secure)")
        else:
            # Rollout era (legacy_retired=false): keep the existing permissive
            # fallback so there is no un-enforced window during migration.
            metrics.incr("CedarAbstainFallback", tags={"agent_id": request.agent_id})
            policy_result = _capture(await _timed("policy_fallback",
                                                  self.policy_engine.validate(request)))
```
- **Implements:** LLD §4.3 (pseudo-code), E1/E2.
- **FOOTGUN:** the `legacy_retired=false` branch MUST stay byte-for-byte the existing permissive `self.policy_engine.validate(request)` fallback — do not "simplify" it away (LLD §14.1; the existing test pins it).

### I2.4 — Ensure the `POLICY_NOT_MIGRATED` DENY is audit-only, not metered to quota
- **Files:** the metering/rollup path (where `Decisions`/`ValidationsTotal` increment, post-combiner); the audit writer (`/sentra/audit-logs`).
- **Change:** mirror the identity-gate-DENY-not-metered pattern (LLD §12; the `identity-deny-not-metered` memo) — a `POLICY_NOT_MIGRATED` DENY is surfaced in the audit view + `CedarAbstainDenied` metric but **excluded from the metered `Decisions`/quota series** so it cannot exhaust a victim tenant's budget.
- **Implements:** LLD §12, E2 (audit-only), §13 "denials that escape metering."
- **FOOTGUN:** do not route this through the normal verdict-meter point. A console "decisions" panel staying flat is the *expected* outcome, not a regression.

---

## Milestone I3 — CT08 `.cedar`-backfill prerequisite (LLD §4.4 — the gate on flipping `legacy_retired`)

The flag from I2 is only safe to flip once every prod policy carries a `.cedar` co-artifact. This milestone is the backfill + verify, NOT the flip (the flip is founder-gated, operational).

### I3.1 — Backfill: write the `.cedar` co-artifact for every prod policy
- **File:** `scripts/translate_policies_to_cedar.py` (the CT08 translator referenced [generator.py:6](../../src/security-controller/app/validators/cedar/generator.py#L6)).
- **Change:** for every structured policy: `generate_cedar` → `put_compiled_policies` → flip the metadata row `policy_format` to `cedar`. `put_compiled_policies` **never touches the structured source** ([policy_artifact.py:84](../../src/security-controller/app/validators/cedar/policy_artifact.py#L84)) — non-destructive, re-runnable, forward-only/additive-first (LLD §4.4 step 1, §10).
- **Implements:** LLD §4.4.
- **FOOTGUN (order, LLD §4.4 / E12):** the backfill MUST complete and verify **before** anyone flips `legacy_retired: true`. Flipping first = self-inflicted DENY storm on real agents.

### I3.2 — Verify residual-abstain count == 0 (the hard gate)
- **Change:** add the verification query — assert **0 policies with `policy_format != cedar`** (the residual-abstain count; §6.3 reuses the same query) **and** every co-artifact's `generator_version` == current `GENERATOR_VERSION` (LLD §4.4 step 2 + the `generator_version`-bump footgun, §3.3, E11).
- **Implements:** LLD §4.4 (steps 2–3), E11.
- **FOOTGUN (LLD §4.4):** `policy_format != cedar` count == 0 is necessary but **not sufficient** — a `GENERATOR_VERSION` bump without re-running the backfill leaves stale `.cedar` whose `policy_format` is still `cedar` (Cedar won't abstain but evaluates stale rules). The verify must also assert generator-version parity.

### I3.3 — Document the flip as founder-gated runbook step (no flip task here)
- **Change:** record in the WS-I go-live runbook that flipping `legacy_retired: true` in [cdk/config/prod.yaml](../../cdk/config/prod.yaml) is **founder-gated, alongside/after the §6.2(g) prod activation**, and is conditional on I3.2 passing. **Do NOT add a task that flips a prod flag** — that would be an out-of-band production change (production-safety rules; scope-doc I2.2 FOOTGUN).
- **Implements:** LLD §4.4 step 3.

---

## Milestone I4 — New test `test_cedar_abstain_fail_secure.py` (LLD §14.2)

The LLD 27 K3.2 "test to write." A NEW test file — do NOT edit the existing rollout-era test.

### I4.1 — New end-state fail-secure test
- **File (new):** `src/security-controller/tests/test_cedar_abstain_fail_secure.py` (or add to `test_cedar_cutover.py`); mirror the fixture shape at [test_cedar_cutover.py:39-60](../../src/security-controller/tests/test_cedar_cutover.py#L39).
- **Change:** add `test_cutover_abstain_denies_when_legacy_retired`:
```python
@pytest.mark.asyncio
async def test_cutover_abstain_denies_when_legacy_retired():
    session = _session()
    svc = _pipeline_service(session)
    svc.cedar_engine = Mock()
    svc.cedar_engine.validate = AsyncMock(return_value=ValidationResult.abstain("not migrated"))
    settings.cedar_enabled = True
    settings.cedar_shadow_mode = False
    settings.legacy_retired = True            # the end state

    result, _signals = await svc._run_validation_pipeline(_request(), session)

    svc.cedar_engine.validate.assert_awaited_once()
    svc.policy_engine.validate.assert_not_called()   # legacy is RETIRED — not consulted
    assert result.should_deny is True                # fail-secure, NOT permissive
    assert result.violation_type == "POLICY_NOT_MIGRATED"
```
- **Implements:** LLD §14.2, E2.

### I4.2 — Extend the `_reset_flags` autouse fixture to save/restore `legacy_retired`
- **File:** [src/security-controller/tests/test_cedar_cutover.py:39-43](../../src/security-controller/tests/test_cedar_cutover.py#L39) (`_reset_flags`).
- **Change:** save/restore `legacy_retired` so the new test's `legacy_retired=True` does not leak into other tests. Optionally add an explicit `assert settings.legacy_retired is False` precondition to the existing `test_cutover_abstain_falls_back_to_legacy` (LLD §14.2).
- **Implements:** LLD §14.2.
- **FOOTGUN (LLD §14.1):** do **NOT** rewrite `test_cutover_abstain_falls_back_to_legacy` to assert DENY. It pins the rollout-era permissive fallback (`should_deny is False`) and is correct for `legacy_retired=false`. Editing it conflates the two states and erases the proof the rollout path still works.

---

## Milestone I5 — §5.6 metrics + the `local_floor_enabled` kill-switch (LLD §5.6)

Net-new operational metrics (off the response path) + the incident escape hatch that falls back to the hosted PDP (not deny-all).

### I5.1 — Add the net-new metrics (fire-and-forget, off the response path)
- **File:** [src/security-controller/app/utils/metrics_publisher.py](../../src/security-controller/app/utils/metrics_publisher.py) (today only `CedarShadowDiscrepancy`/`CedarShadowEvaluated` exist, [:176](../../src/security-controller/app/utils/metrics_publisher.py#L176)).
- **Change:** add publishers for the LLD §5.6 table — `BundleEmitTotal`/`BundleEmitFailures` (dims `tenant_id`, `generator_version`), `CedarEscalateFraction` (`tenant_id`, `policy_id`), `EdgeResolveTotal`/`EscalatedToHostedTotal` (`tenant_id`), `CedarEvalLatencyMs` (`tenant_id`, `cache_hit`), `BundleStaleFailClosed` (`tenant_id`). Plus `CedarAbstainDenied`/`CedarAbstainFallback` already wired in I2.3.
  - **Note:** `BundleEmitTotal`/`BundleEmitFailures`/`CedarEscalateFraction` are *emitted by* the Group-2 emit step; in Group 1 add only the publisher plumbing + the ones I2/I5 own (`CedarAbstainDenied`, `CedarAbstainFallback`, `CedarEvalLatencyMs`, `EdgeResolveTotal`/`EscalatedToHostedTotal`, `BundleStaleFailClosed`). The emit-side metrics are populated when Group 2 lands.
- **Implements:** LLD §5.6 (metrics table).
- **FOOTGUN:** emit off the response path (fire-and-forget, like existing publishers) — a metric failure never blocks a verdict. These are OPS/dashboard signals, NOT the billing ledger (that is WS-H's durable pipeline).

### I5.2 — Add `CedarEvalLatencyMs{cache_hit}` at the hosted eval point
- **File:** [src/security-controller/app/validators/cedar/policy_loader.py](../../src/security-controller/app/validators/cedar/policy_loader.py) (`_load_compiled_cached`, [:87](../../src/security-controller/app/validators/cedar/policy_loader.py#L87)) / the engine eval call.
- **Change:** emit `CedarEvalLatencyMs` tagged `cache_hit=true|false` — proves §8 (eval ~1–5 ms on an LRU hit; a spike of `cache_hit=false` flags a cold/thrashing cache).
- **Implements:** LLD §5.6, §8.
- **FOOTGUN (LLD §8):** never move the compiled-text load onto the per-request path (e.g. an "always re-fetch latest" that defeats the immutable-key `_compiled_cache` LRU at [policy_loader.py:30-34](../../src/security-controller/app/validators/cedar/policy_loader.py#L30)). That re-introduces per-request S3 latency. The cache key `(schema_version, content_hash, generator_version)` is immutable → no TTL is correct.

### I5.3 — Add the `local_floor_enabled` kill-switch flag (per-tenant override)
- **Files:** the settings module; the `sentra-tenants` DynamoDB row (per-tenant override).
- **Change:** add `local_floor_enabled`, **default `true`**, with per-tenant override via the `sentra-tenants` row (so one bad bundle doesn't force a fleet-wide fallback — the granular option, LLD §5.6).
- **Implements:** LLD §5.6.

### I5.4 — Wire the kill-switch to fall back to the hosted path (NOT deny-all)
- **File:** the SDK guard transport (`guard.py` network POST path) — coordinate with WS-A; this WS owns the *flag semantics* and the hosted-side contract.
- **Change:** when `local_floor_enabled=false` for a scope, the SDK **stops evaluating the cached bundle locally and routes every call to the hosted `/v1/validate`** (the production network path) — enforcement is unbroken; only the eval location moves (LLD §5.6, §1.2 tenet 5).
- **Implements:** LLD §5.6, ADR-034 (does not disable enforcement).
- **FOOTGUN (the catastrophe, LLD §5.6):** the off-state MUST set the SDK to **network-required** (existing `fail_secure=true` transport, LLD 27 N2 — money-movement tenants cannot flip `fail_secure` off). A bug that reads `local_floor_enabled=false` as "skip validation" instead of "validate on the server" is fail-open. Fail to the hosted path, never to allow-local-without-checking.

---

# ⚠️⚠️ GROUP 2 — SPIKE-GATED — BLOCKED ON WS-0 ⚠️⚠️

> **BLOCKED ON WS-0 SPIKE. DO NOT CODE these milestones until WS-0's dated signed packet exists.** (HLD §8 measure-first gate.) These consume §6.2(a)(ii) — the measured fraction of real Cedar policies that force escalate — and the egress-subset differential cost. The **second kill-check may cancel the local floor entirely** (and route egress to the hosted tier + re-cut FR-1.7), in which case I6–I8 change shape or are cancelled. `plan-workstreams` must not decompose these before WS-0's packet. Cross-ref: [ws-0-measure-first-spike.md](ws-0-measure-first-spike.md), LLD §5.4–§5.5, §6.

## Milestone I6 — Hosted bundle-emit allowlist compiler (LLD §5) — BLOCKED ON WS-0

### I6.1 — Define the bundle wire schema (the shared contract with WS-A)
- **File (new):** `src/security-controller/app/validators/cedar/bundle_emit.py` + the signed bundle written to the bundle-distribution store (S3, alongside `put_compiled_policies`).
- **Change:** fix the bundle wire schema exactly per LLD §5.2 — keys `bundle_version` (monotonic, inside signed payload), `iat`, `nbf`, `schema_version` (== `CEDAR_SCHEMA_VERSION`), `generator_version` (== `GENERATOR_VERSION`), `tenant_id`, `agent_id`, `tool_allow`, `tool_deny`, `param_bounds[{tool,field,max_cents:int,deny_on_missing:bool}]`, `agent_allow`, `sequence`, `egress[{host,path_prefix,port,verdict}]`, `prompt_signatures[{id,pattern,verdict}]`. **NO `escalate_fraction` field** (under whole-policy escalate a bundle's fraction is always 0.0 — it's a control-plane metric, not a wire field). WS-A cannot finalize its interpreter until this is fixed (LLD §5.2).
- **Implements:** LLD §5.2.
- **FOOTGUN (LLD §5.2):** `param_bounds.max_cents` is integer `int(round(dollars*100))` (the exact `coerce_amount_to_cents` coercion, [context.py:60](../../src/security-controller/app/validators/cedar/context.py#L60)), never float — a float bound diverges from `cedarpy` on rounding and breaks the differential test. And `deny_on_missing` MUST be carried for dangerous-tool bounds (encodes `forbid_refund_missing_amount`).

### I6.2 — The allowlist compiler: two passes, whole-policy escalate
- **File:** `src/security-controller/app/validators/cedar/bundle_emit.py`.
- **Change:** implement `emit_bundle(resolved_cedar_policy, entities) -> dict | None` with the explicit `SUPPORTED_CONSTRUCTS` allowlist mapping each `@id` rule to its emit fn (`permit_use_tool`→`_emit_tool_allow`, `forbid_refund_over_cap`→`_emit_param_bound`, `forbid_refund_missing_amount`→`_emit_param_deny_missing`, `forbid_high_fraud_identity`→`_emit_tool_deny_identity`, `permit_invoke_agent`→`_emit_agent_allow`, egress→`_emit_egress`, prompt-signature→`_emit_signature`). **Two passes:** (1) classify EVERY rule; (2) emit only if **every** rule is on-allowlist — if ANY is out-of-subset, `return None` (NO bundle; whole policy stays server-side). Validate up front with `validate_policy_set` (cedarpy doesn't raise) → `BundleEmitError` on errors.
```python
def emit_bundle(resolved_cedar_policy, entities) -> dict | None:
    errors = validate_policy_set(resolved_cedar_policy)   # cedarpy doesn't raise — validate first
    if errors:
        raise BundleEmitError(errors)
    rules = resolved_cedar_policy.rules
    emit_fns = [SUPPORTED_CONSTRUCTS.get(classify_construct(r)) for r in rules]
    if any(fn is None for fn in emit_fns):                # ANY out-of-subset → whole policy escalates
        record_escalate(resolved_cedar_policy, escalated=True)   # CedarEscalateFraction = 1.0
        return None                                       # NO bundle emitted
    bundle = _new_bundle(entities)
    for rule, emit_fn in zip(rules, emit_fns):
        emit_fn(bundle, rule, entities)
    record_escalate(resolved_cedar_policy, escalated=False)      # CedarEscalateFraction = 0.0
    return sign(bundle)                                   # WS-A owns the signing-key lifecycle (ADR-029)
```
- **Implements:** LLD §5.3, E6/E7.
- **FOOTGUN (the single worst bug, LLD §5.3, tenet 4):** the escalate unit is the **WHOLE POLICY, never a single rule**. A per-rule emit (ship allowlisted rules, hold back only the out-of-subset rule) lets the edge resolve the request locally and never reach the server, so the server-side `forbid` never fires = silent fail-open. `return None` for the whole policy is what guarantees the request escalates to the server. And `record_escalate`/escalate-only must **never remove anything from the SERVER policy** — the hosted PDP still enforces the full `.cedar` via `cedarpy`; emit only *reads* it.
- **FOOTGUN (LLD §5.3):** NEVER infer "probably allow" for an unrecognized construct. Unrecognized ⇒ not in `SUPPORTED_CONSTRUCTS` ⇒ escalate. No best-effort interpretation, no denylist. Allowlist makes "unanticipated" ≡ "escalate."

### I6.3 — Emit `CedarEscalateFraction` (per-policy 0/1) + run off the action path
- **Change:** `record_escalate` surfaces the per-policy binary (`1.0` escalated / `0.0` emitted) as the `CedarEscalateFraction` metric (tagged policy/tenant); WS-0 aggregates the fleet fraction (LLD §5.5). Emit runs on policy create/update (alongside `put_compiled_policies`), **never on `/v1/validate`** (tenet 2).
- **Implements:** LLD §5.5, §5.1.
- **FOOTGUN (LLD §5.5):** a high escalate-fraction is a finding, not a bug to hide. Do NOT expand the `SUPPORTED_CONSTRUCTS` allowlist to "look better" without a passing §6 differential case for each added construct — an un-conformance-tested construct on the allowlist re-opens the silent-divergence hole.

### I6.4 — Egress GROW branch (`_emit_egress`) — default grow; drop only with a re-cut
- **Change:** `_emit_egress` emits `{host, path_prefix, port, verdict}` entries (finite match-table, FR-2.9 / LLD §5.4). Default is GROW (egress in the closed subset).
- **Implements:** LLD §5.4, FR-1.7/FR-2.9.
- **FOOTGUN (LLD §5.4):** route egress to the hosted deep tier **only** if WS-0's differential-test cost proves prohibitive — and in that case it MUST **re-cut sub-PRD FR-1.7 to remove "egress"** via `propagate-change`. Neither direction (grow/drop) may drift silently.

### I6.5 — Sign the bundle with anti-rollback fields
- **Change:** the whole bundle object is JWT-signed (detached-signature manifest of per-file SHA-256); `bundle_version` (monotonic), `iat`, `nbf` live **inside the signed payload** (LLD §5.2, §7). Per-tenant signing key (Appendix D) — distinct from the per-agent-identity `kid`-LRU (LLD 26 §3.6). WS-A owns key rotation/lifecycle (ADR-029); this WS emits the signed bundle + names the anti-rollback fields.
- **Implements:** LLD §7 (anti-rollback/replay, per-tenant signing).
- **FOOTGUN (LLD §7):** do not conflate the bundle-signing keypair with the per-agent-identity `kid`-LRU.

---

## Milestone I7 — interpreter↔cedarpy differential-conformance corpus (LLD §6) — BLOCKED ON WS-0

### I7.1 — Corpus schema + cases (incl. the MANDATORY mixed-policy case)
- **File (new):** `src/security-controller/tests/corpus/cedar_differential.jsonl` (co-owned with WS-A — this WS owns the corpus + the `cedarpy` side; WS-A runs its interpreter against it).
- **Change:** one JSONL case per line per LLD §6.2 — `{id, policy_ref, entities, request, expected, subset}` (+ `server_expected` for mixed cases). Cover **every closed-subset primitive**: tool allow/deny; param-bounds **at cap (==max → ALLOW)**, **over cap (> → DENY)**, **under cap**, **missing-amount → DENY** (deny-on-missing); sequence; **egress host/path/port** matches (GROW); prompt-signature. Plus out-of-subset cases whose expected verdict is **ESCALATE**.
- **The MANDATORY mixed-policy case (LLD §6.2):**
```jsonl
{"id": "mixed_allowlisted_permit_plus_out_of_subset_forbid", "policy_ref": "mixed-permit-oos-forbid",
 "entities": {"allowed_tools": ["process_refund"]},
 "request": {"tool_name": "process_refund", "tool_params": {"amount": 100}},
 "expected": "ESCALATE", "server_expected": "DENY", "subset": "out_of_subset",
 "_note": "permit_use_tool (allowlisted → tool_allow) + an out-of-subset forbid on the SAME process_refund. Whole-policy escalate MUST emit NO bundle → edge ESCALATEs → server forbid DENYs. A per-rule emit would ship tool_allow and ALLOW locally — the catastrophe."}
```
- **Implements:** LLD §6.2, §14.4.
- **FOOTGUN (LLD §6.2):** the corpus MUST include the fail-secure edge cases the baseline bakes in — refund exactly at cap (`==` ALLOW, `>` strict DENY at [baseline-v1.cedar:30](../../src/security-controller/app/validators/cedar/baseline-v1.cedar#L30)), over cap, missing-amount→DENY, dangerous tool with missing principal attr. Reuse the exact `coerce_amount_to_cents` coercion ([context.py:45](../../src/security-controller/app/validators/cedar/context.py#L45)) so a parity diff is a real policy diff, not a parsing diff. **Without the mixed case the gate is blind to the §5.3 fail-open** (a single-rule out-of-subset policy emits an empty bundle and already escalates).

### I7.2 — The differential runner + assertion direction
- **File (new):** `src/security-controller/tests/test_cedar_differential.py`.
- **Change:** run each case through `cedarpy` (oracle, via `CedarEvaluator.is_authorized`) and through WS-A's interpreter; assert verdicts identical for `subset != out_of_subset`; for `out_of_subset` assert `emit_bundle` returns **`None`** (no bundle → edge escalates). For a mixed case assert specifically: `emit_bundle` returns `None` AND the `cedarpy` server verdict == `server_expected`. Include an **injected-divergence** test (a deliberately-wrong interpreter stub that ALLOWs an over-cap refund) that must make the runner report a **CRITICAL edge-fail-open** (proves the runner isn't vacuously green).
- **Implements:** LLD §6.3, §14.4, E8/E9/E10.
- **FOOTGUN (LLD §6.3):** the asymmetry that matters is **edge-ALLOW-where-server-DENY** = silent fail-OPEN = CRITICAL, distinct from edge-DENY/escalate-where-server-ALLOW (over-block, latency loss). Do NOT collapse them into one pass/fail count. Out-of-subset expected verdict is **ESCALATE**, not a guessed allow/deny.

### I7.3 — CI gate (hermetic, per-PR)
- **Change:** wire the differential test into the PR-gating scenario suite (the same `tests/integration/` harness LLD 27 §7 reuses). **Hermetic** — `cedarpy` + interpreter over fixtures, **no live DDB/S3**. Gate thresholds (LLD §6.4): edge-ALLOW-where-server-DENY = **0, fails PR (CRITICAL)**; edge-DENY/escalate-where-server-ALLOW = 0, fails PR (distinct latency-loss class); out-of-subset construct that does NOT escalate the whole policy (emit returns a bundle, incl. partial) = fails PR (mixed-policy case mandatory); `escalate_fraction` reported per policy (no threshold — honest measurement, feeds WS-0).
- **Implements:** LLD §6.4, §14.4.
- **FOOTGUN:** this hermetic test is the per-PR gate; the live e2e test (I8) is NOT — do not let live infra-flakiness gate every PR (LLD §14.6).

---

## Milestone I8 — Live e2e Cedar integration test — bundle half (LLD §14.6 item 3) — BLOCKED ON WS-0

> Only the **bundle half** (item 3) is in WS-I Group 2. Items 1/2/4 of `test_cedar_e2e.py` (author→compile→evaluate, cold-then-hot, abstain→DENY-on-live) exercise Group-1 / existing behavior and may be written once a deployed env exists; item 3 depends on I6/I7 landing.

### I8.1 — Bundle-emit round-trip against live-emitted artifacts
- **File:** `tests/integration/test_cedar_e2e.py`, marked `@pytest.mark.integration` + `@pytest.mark.requires_services` (existing markers + `service_urls`/`api_headers` fixtures, [tests/integration/conftest.py](../../tests/integration/conftest.py)); run against a deployed env (real ALB → controller → DynamoDB metadata → S3 `.cedar`), profile `sentra`, `us-east-1`.
- **Change (item 3):** emit a signed bundle for a fully-allowlisted policy → fetch it via the refresh endpoint → run the **differential corpus against the LIVE-emitted bundle** (not just a fixture). Assert an escalated (out-of-subset) policy emits **no bundle** and the live `/v1/validate` **escalates to the hosted engine and still DENYs** the forbidden action.
- **Implements:** LLD §14.6 item 3.
- **FOOTGUN (LLD §14.6):** runs in the **post-deploy / pre-promote** integration stage (with LLD 27 §7's post-cutover suite + WS-J), NOT the hermetic per-PR gate — it needs live infra. A failure blocks the promote; do not gate every PR on it.

---

## Acceptance criteria

### Group 1 — checkable now

- [x] **I1:** the LLD §2.2 symbols verified present at their cited anchors (`CedarPolicyEngine`/`validate`/`_validate_invoke_agent`/`_map_use_tool_deny`, `CedarEvaluator.is_authorized`/`validate_policy_set`, `generate_cedar`, the 5 baseline `@id` rules); LLD 19 confirmed NOT folding in Cedar.
- [ ] **I1:** [lld/ARCHITECTURE.md](../../lld/ARCHITECTURE.md) AD-2 (line 327) tightened to "embeddable on the server host; the SDK local tier interprets a derived signed bundle, not the native engine"; the FR-2.4 + FR-2.9 status edits land in the **same** `propagate-change` pass (no sibling left citing the old AD-2 text). — **NOT DONE: docs-propagate pass not run this session (code-only scope); tracked as a follow-up.**
- [x] **I2:** `legacy_retired: bool` flag added, **default `false`**, present in dev.yaml + prod.yaml (value `false`).
- [x] **I2:** `POLICY_NOT_MIGRATED` violation type exists, penalty −15, **distinct from `POLICY_ERROR`**; `_fail_secure_deny` helper reuses the engine `_deny` shape.
- [x] **I2:** at [validation_service.py:303-311](../../src/security-controller/app/services/validation_service.py#L303), `is_abstain` branches on `settings.legacy_retired` — `true` → fail-secure DENY `POLICY_NOT_MIGRATED` + `CedarAbstainDenied`; `false` → unchanged permissive legacy fallback + `CedarAbstainFallback`.
- [x] **I2:** a `POLICY_NOT_MIGRATED` DENY is **audit-only** — surfaced via `CedarAbstainDenied` + `/sentra/audit-logs`, **excluded** from the metered `Decisions`/quota series. *(tested: `test_policy_not_migrated_deny_is_audit_only_not_metered`)*
- [x] **I3:** `scripts/translate_policies_to_cedar.py` backfills the `.cedar` co-artifact for every prod policy non-destructively (`put_compiled_policies` never touches the structured source) and is re-runnable.
- [x] **I3:** the verify asserts **0 policies with `policy_format != cedar`** AND every co-artifact's `generator_version` == current `GENERATOR_VERSION`; the `legacy_retired: true` flip is documented as founder-gated/runbook (NO prod-flip task in WS-I). *(added `--verify` mode; passes live: 0 residual, gen-version parity; runbook §4 Step 1b)*
- [x] **I4:** `test_cedar_abstain_fail_secure.py` (`test_cutover_abstain_denies_when_legacy_retired`) asserts `should_deny is True`, `violation_type == "POLICY_NOT_MIGRATED"`, and `policy_engine.validate.assert_not_called()`. *(added to `test_cedar_cutover.py` — the task's permitted alternative location; green)*
- [x] **I4:** the `_reset_flags` autouse fixture saves/restores `legacy_retired`; the existing `test_cutover_abstain_falls_back_to_legacy` is **NOT** edited to assert DENY (still pins `should_deny is False`).
- [~] **I5:** the §5.6 metric publishers exist (`CedarEvalLatencyMs{cache_hit}`, `EdgeResolveTotal`/`EscalatedToHostedTotal`, `BundleStaleFailClosed`, `CedarAbstainDenied`/`CedarAbstainFallback`), emitted off the response path (a metric failure never blocks a verdict). — **PARTIAL: the I2/I5-owned publishers are done; `BundleEmitTotal`/`BundleEmitFailures`/`CedarEscalateFraction` are Group-2 emit-side (added when I6 lands), per I5.1's own scope note.**
- [x] **I5:** `local_floor_enabled` flag added, **default `true`**, per-tenant override via the `sentra-tenants` row (`Tenant.local_floor_enabled` + `tenancy.effective_local_floor_enabled`); off-state semantics = route to the **hosted `/v1/validate`**, **never** "skip validation." *(flag semantics + server helper own here; the SDK transport that consumes it is WS-A's — local-floor SDK path doesn't exist pre-Group-2; documented in the SDK README + I5.4)*
- [x] **I5:** no path moves the compiled-`.cedar` load onto the per-request hot path (the immutable-key `_compiled_cache` LRU, no-TTL, is preserved; latency timing added around it without changing the load path).
- [x] **Floor invariant (ADR-034):** nothing in Group 1 introduces a path that disables the Cedar deterministic floor in any mode/edition; the kill-switch changes *where* enforcement runs, never *whether* (tested: `test_local_floor_killswitch.py`).

### Group 2 — BLOCKED ON WS-0 SPIKE (do not check until WS-0's signed packet exists)

- [ ] 🔒 **I6:** the bundle wire schema (LLD §5.2, closed subset only, NO `escalate_fraction` field) is fixed and shared with WS-A; `param_bounds.max_cents` is integer (`int(round(dollars*100))`), `deny_on_missing` carried for dangerous tools, never float.
- [ ] 🔒 **I6:** `emit_bundle(...) -> dict | None` is a two-pass **allowlist** (`SUPPORTED_CONSTRUCTS`); ANY out-of-subset rule ⇒ `return None` (whole-policy escalate, no edge bundle) — verified by a test feeding an out-of-subset construct asserting `None`, NOT emit/drop.
- [ ] 🔒 **I6:** escalate-only removes a rule from the **edge bundle only**; the hosted PDP still enforces the full `.cedar` via `cedarpy` (verified the resolved `.cedar` is unchanged by emit).
- [ ] 🔒 **I6:** `CedarEscalateFraction` reported per policy (binary 0/1); emit runs on policy create/update, never on `/v1/validate`; bundle signed with `bundle_version`(monotonic)/`iat`/`nbf` inside the signed payload, per-tenant key.
- [ ] 🔒 **Egress branch:** closed subset **includes** literal egress host/path/port matching (GROW, default) **OR** — only if WS-0's differential cost proves prohibitive — egress routed to the hosted tier **and** sub-PRD FR-1.7 re-cut to drop "egress" (propagate). No silent drift.
- [ ] 🔒 **I7:** `corpus/cedar_differential.jsonl` covers every closed-subset primitive + the fail-secure edge cases (refund at/over/under cap, missing-amount→DENY, egress matches, prompt-signature) + out-of-subset ESCALATE cases + the **MANDATORY mixed-policy case** (allowlisted `permit` + out-of-subset `forbid` on the same `process_refund`).
- [ ] 🔒 **I7:** the differential runner asserts identical verdicts on the closed subset; flags **edge-ALLOW-where-server-DENY as CRITICAL** distinct from over-escalation; an injected-divergence test proves the runner is not vacuously green.
- [ ] 🔒 **I7:** the CI gate is **hermetic** (no live DDB/S3), runs per-PR, and **fails the PR** on any divergence (edge-fail-open = CRITICAL; out-of-subset-not-escalating-whole-policy = fail; `escalate_fraction` reported, no threshold).
- [ ] 🔒 **I8:** `tests/integration/test_cedar_e2e.py` item 3 (bundle-emit round-trip) runs the differential corpus against a **live-emitted** bundle, asserts an escalated policy emits no bundle and the live validate escalates-to-hosted-and-still-DENYs; runs in the **post-deploy/pre-promote** stage, NOT the per-PR gate.

---

## Cross-references

- **LLD sections:** §2 (component architecture — I1) · §4 (abstain→DENY + CT08 backfill — I2/I3/I4) · §5 (bundle-emit allowlist — I6) · §5.6 (metrics + kill-switch — I5) · §6 (differential corpus — I7) · §7 (security/anti-rollback — I6.5) · §8 (LRU latency — I5.2) · §12 (metering: abstain-DENY audit-only — I2.4) · §13 (error model E1–E12) · §14.2 (abstain test — I4) · §14.3/§14.4 (emit + differential tests — I6/I7) · §14.6 (live e2e — I8).
- **Sibling workstreams:** [ws-a-local-floor-bundle.md](ws-a-local-floor-bundle.md) (consumes the `bundle`; co-owns `corpus/cedar_differential.jsonl` interpreter side; owns signing-key lifecycle + kill-switch SDK transport) · [ws-0-measure-first-spike.md](ws-0-measure-first-spike.md) (**gates Group 2** — escalate-fraction + egress-subset cost) · [ws-f-prompt-signatures.md](ws-f-prompt-signatures.md) (prompt-signature bundle primitive, stdlib-`re`-expressible).
- **Decisions:** AD-2 (Cedar engine, confirmed) · ADR-029 (signed bundle + anti-rollback) · ADR-034 (non-disableable deterministic floor) · AD-3 (`/v1/validate` `phase`).
- **Related LLDs:** [LLD 27](../../lld/27-serverless-production-activation.md) §7.1 (the abstain gap; CT08 prereq) · [LLD 23](../../lld/23-sentra-guard-sdk.md) (stdlib-only SDK — no native dep) · [LLD 24](../../lld/24-latency-optimization.md) (escalate-fraction caps the local-floor win) · [LLD 19](../../lld/19-ml-threat-classifier.md) (ML — explicitly NOT Cedar).
- **Skills:** `sentra:cedar-policy-patterns` (forbid-wins / has-guard / deny-on-missing invariants, DENY reason-code taxonomy, identity-gate-vs-policy-DENY split).
