# Workstream 19: ML-Based Threat Classifier

**Status**: M1-M5 code shipped (2026-05-30); deploy + eval-harness baseline + design-partner pilot remain user-action steps
**Owner**: Founder + 1 backend engineer
**Start Date**: 2026-05-27 (LLD v0.2 review → implementation)
**LLD Reference**: [lld/19-ml-threat-classifier.md](../lld/19-ml-threat-classifier.md) (v0.3)

### Shipped artifacts (code-complete checkpoint, 2026-05-30)

Per-task status reconciliation (Kiro review M1-implementation pass identified that an earlier "all done" claim was over-broad — now corrected):

| Milestone | Task | Status | Artifact |
|---|---|---|---|
| M1 | 1.1 prompts + schema | ✅ shipped | `src/security-controller/app/validators/ml_classifier_prompts.py`, `ml_classifier_schema.py` |
| M1 | 1.2 validator class | ✅ shipped | `src/security-controller/app/validators/ml_classifier.py` |
| M1 | 1.3 `ValidationResult.abstain` | ✅ shipped | `src/security-controller/app/api/models.py` |
| M1 | 1.4 pipeline wiring + config | ✅ shipped | `validation_service.py` STEP 3.5, `config.py` ML_* settings |
| M1 | 1.5 CDK IAM + Application Inference Profile | ✅ shipped | `cdk/stacks/compute_stack.py` (CfnResource escape hatch; AIP resource verified in synth) |
| M1 | 1.6 unit tests T-ML-01..10 | ✅ 12/12 pass | `tests/test_ml_classifier.py` |
| M1 | 1.7 integration tests (gated) | ✅ shipped | `tests/test_ml_classifier_bedrock.py` — runs only when `RUN_INTEGRATION=1` (needs real Bedrock credentials + spend) |
| M1 | 1.8 pipeline tests T-PIPE-01..05 | ✅ 5/5 pass + shadow-mode test | `tests/test_validation_service.py` |
| M1 | 1.9 deploy controller image | ✅ shipped 2026-05-30 — controller `milestone-36` (digest `sha256:f4b7b01a...`) live in `sentra-mvp-cluster` after Kiro pass-1 + pass-2 fixes; dashboard `milestone-60` (digest `sha256:71cbd65a...`) live with M4.4 surface; ECS rollout COMPLETED on both; running-task digests match ECR `latest`; `Sentra-DEV-Compute-Stack` updated with AIP resource (`kv5jsfpwxnw5`), 9 `ML_*` env vars, IAM grants |
| M2 | 2.1 dataset extractor | ✅ shipped | `scripts/extract_ml_eval_dataset.py` |
| M2 | 2.2 adversarial generator | ✅ shipped | `scripts/generate_adversarial_dataset.py` (M2b: ~5h founder review of the produced CSV is on the critical path before eval) |
| M2 | 2.3 eval harness | ✅ shipped | `scripts/eval_ml_classifier.py` + `scripts/eval_thresholds.yaml` |
| M2 | 2.4 CI workflow | ✅ shipped | `.github/workflows/eval-ml-classifier.yml` — needs `AWS_OIDC_ROLE_ARN` repo secret before first PR run |
| M2 | 2.5 baseline eval run | 🚧 user-action — requires labeled dataset (M2b human review must complete first) and real Bedrock spend |
| M3 | 3.1 shadow-mode flag | ✅ shipped | `ML_CLASSIFIER_SHADOW_MODE` in config + validation_service + test |
| M3 | 3.2 enable shadow in dev | 🚧 user-action — flip the env var via task definition update + `cdk deploy` |
| M3 | 3.3 shadow comparison script | ✅ shipped | `scripts/compare_shadow_verdicts.py` |
| M4 | 4.1 flip shadow off in dev | 🚧 user-action — depends on M3 exit gate (≥50 novel inputs) |
| M4 | 4.2 staging enable | 🚧 user-action |
| M4 | 4.3 S1-S4 regression | 🚧 user-action — `tests/integration/test_cross_cloud_scenarios.py` needs new ML-enabled variants added when staging traffic is available |
| M4 | 4.4 dashboard surface (ML tier column + OTHER suppression) | ✅ shipped | `src/dashboard/components/cross_cloud_demo.py` |
| M5 | 5.1 user docs + best-practices §14 | ✅ shipped | `docs/sentra-ml-classifier.md`, `best-practices.md` §14 |
| M5 | 5.2 design-partner pilot | 🚧 user-action — depends on M4 active rollout being stable |
| M5 | 5.3 pitch deck + competitive memory | 🚧 marketing scope; engineering pre-condition (eval-harness precision ≥95%) tracked in M2.5 |

---

## Overview

Add a Sentra-side ML threat classifier to the `/v1/validate` pipeline. Runs on every validation call, independent of customer agent configuration, contributing one `Signal(source=sentra.ml_classifier)` per invocation to the existing combiner ([LLD 17 §4](../lld/17-validation-signal-store.md)).

### Why

Sigma rules catch known patterns. They miss semantic threats (paraphrased prompt injection, novel exfiltration framing, multi-step manipulation). Competitors (Lakera, CalypsoAI, HiddenLayer) all anchor on ML detection — Sentra needs the capability for market parity.

The classifier is layered defense, not replacement:
- Regex/sigma → fast, deterministic, explainable
- Policy engine → authorization (allowed_tools)
- ML classifier → semantic threat detection
- Combined via deny-overrides (LLD 17 §4)

### Why now

Three concrete triggers:

1. **Pre-seed pitch demands it.** "How do you catch novel attacks?" is the question every design partner asks. Today: "we don't, we rely on rule updates." After WS19: "two layers — sigma + ML."
2. **The signal substrate already exists.** LLD 17 declared `Source.SENTRA_ML_CLASSIFIER` and reserved the priority slot. The combiner handles deny-overrides. We're filling in a pre-engineered hole, not architecting from scratch.
3. **Bedrock latency is low enough.** Claude Haiku 3.5 p99 ~600ms; same provider we already use. No new infra dependencies.

### Success criteria

**M1 (validator shipped, feature-flagged off)**
- `MLClassifierValidator` class with hot + escalation tiers
- All unit + integration + pipeline tests pass (T-ML-01..10, T-MLI-01..04, T-PIPE-01..05)
- Validator emits `Signal(source=SENTRA_ML_CLASSIFIER)` per LLD 17 §4
- Feature flag `ML_CLASSIFIER_ENABLED` defaults `false`
- Controller image deployed; validator visible in logs (loaded but not invoked when disabled)

**M2 (eval harness)**
- Labeled dataset from existing audit log (≥5k rows)
- `scripts/eval_ml_classifier.py` produces precision/recall/latency/cost report
- Adversarial test set (≥500 synthetic examples) reviewed and labeled
- CI gate enforces precision ≥95% on held-out validation set

**M3 (shadow mode in dev)**
- ML classifier enabled in `sentra-mvp-cluster` with signals emitted but NOT participating in combiner verdict
- 7 days of shadow data collected
- Comparison report: ML-would-have-decided vs combined-actual-decision

**M4 (active in dev)**
- ML classifier participates in combiner
- All S1-S4 scenarios pass with classifier active
- Per-environment defaults set (dev=on, staging=on, prod=opt-in)

**M5 (production rollout)**
- Customer-prod opt-in mechanism documented
- First design partner enables in their staging
- Documentation in `docs/sentra-ml-classifier.md` + `best-practices.md §14`

---

## Milestone Map

| Milestone | Goal | Effort |
|---|---|---|
| M1 | MLClassifierValidator (hot + escalation tiers) + signal emission | 6h eng |
| M2a | Eval harness engineering (extract/eval/CI scripts) | 3h eng |
| M2b | Human labeling (founder review of ~500 adversarial examples) | 5h focused human time (NOT engineering) |
| M3 | Shadow mode rollout (dev cluster) | 3h eng |
| M4 | Active rollout (dev/staging defaults, S1-S4 regression) | 4h eng |
| M5 | Documentation + design partner pilot | 4h eng |
| **Total** | | **~20h eng + 5h human review + 25% buffer = ~31h** |

**M2 split rationale**: v0.1 estimated M2 at 8h flat, which hid the human-review component. Labeling 500 adversarial examples at ~30s each plus disagreement triage is ~5h of focused founder time and must not be interleaved with coding. M2b is on the critical path for M3 (CI gate needs human-confirmed ground truth); track it as a hard dependency.

Calendar: ~4 days focused engineering + 1 week eval + 1 week shadow observation = **~3 weeks elapsed end-to-end**.

---

## Milestone 1: MLClassifierValidator (6 hours)

**Goal**: Validator class + prompt + schema + signal emission. Shipped behind feature flag, default off.

### Task 1.1: Prompt + JSON schema files

**Files** (all new):
- `src/security-controller/app/validators/ml_classifier_prompts.py` — system prompt + 10-20 few-shot examples spanning the threat taxonomy
- `src/security-controller/app/validators/ml_classifier_schema.py` — JSON Schema for `emit_security_verdict` tool-use (per LLD 19 §7.1)

**Acceptance**:
- System prompt defines threat taxonomy aligned with sigma rules vocabulary (PROMPT_INJECTION, PII_EXPOSURE, etc.)
- Few-shot examples cover at least: prompt injection, PII exfiltration, data theft, privilege escalation, benign tool call, ambiguous case
- Schema enforces enum on `decision` and `threat_type`, range on `confidence`, maxLength on `reason`
- Reason field instruction: cite the indicator, do NOT quote the prompt verbatim (audit-log-as-attack-dictionary risk)

### Task 1.2: Validator class

**Files**:
- `src/security-controller/app/validators/ml_classifier.py` (new)

**Acceptance**:
- Class `MLClassifierValidator` with `@stamps(Source.SENTRA_ML_CLASSIFIER)` on `validate()`
- Implements tiered logic per LLD 19 §5.2 (hot → escalation → abstain)
- Uses Bedrock `converse` API with tool-use enforcement (no string-parsing of model output)
- Returns `ValidationResult` with `decision`, `reason`, `violation_type=threat_type`, `metadata` (model_used, model_id, confidence)
- ABSTAIN path returns `ValidationResult.abstain(reason)` (decision=None)
- Timeouts honored per-tier; both timeouts independent

### Task 1.3: ValidationResult.abstain helper

**Files**:
- `src/security-controller/app/api/models.py` (modified)

**Acceptance**:
- New classmethod `ValidationResult.abstain(reason: str)`
- Returns ValidationResult with `decision=None`, `metadata={"abstain": True}`
- `@stamps` decorator detects `decision=None` and emits NO signal (LLD 17 §4 absence semantics)

### Task 1.4: Wire into validation pipeline

**Files**:
- `src/security-controller/app/services/validation_service.py` (modified)
- `src/security-controller/app/config.py` (modified — settings injection)

**Acceptance**:
- `_run_validation_pipeline` adds `ml_classifier.validate(request)` to the parallel gather
- Validator is instantiated once at service startup (not per-request)
- New settings in `config.py`: `ml_classifier_enabled`, `ml_classifier_inference_profile_arn`, `ml_classifier_hot_model_id` (Haiku **4.5**, not 3.5 — see LLD 19 §2.4), `ml_classifier_escalation_model_id`, `ml_classifier_timeout_seconds`, `ml_classifier_total_budget_seconds`, `ml_confidence_trust_threshold`, `ml_confidence_abstain_threshold` — all with sane defaults per LLD 19 §8.1
- `Converse` calls pass `modelId=<inference_profile_arn>` (not the bare foundation-model ID) to route through the dedicated workload-isolated profile
- Feature flag check in `validate()`: returns abstain immediately if disabled, NO Bedrock call

### Task 1.5: CDK — IAM grant for Bedrock model invocation

**Files**:
- `cdk/stacks/compute_stack.py` (modified — controller_task_role)

**Acceptance**:
- New CDK construct creates the `aegionai-ml-classifier` Application Inference Profile (LLD 19 §8.4) with workload tags (`Workload=ml-classifier`, `Component=security-controller`)
- Controller task role granted `bedrock:InvokeModel`, `bedrock:Converse` scoped to:
  - `arn:aws:bedrock:{region}::foundation-model/anthropic.claude-haiku-4-5-*` (**NOT** haiku-3.5 — that's the existing agent's pin, must not be invocable from the validator)
  - `arn:aws:bedrock:{region}::foundation-model/anthropic.claude-sonnet-4-6-*`
  - `arn:aws:bedrock:{region}:{account}:application-inference-profile/aegionai-ml-classifier`
- IAM also grants `bedrock:GetInferenceProfile` on the profile ARN (for runtime sanity-check on startup)
- New env vars piped to controller task definition: `ML_CLASSIFIER_*` including `ML_CLASSIFIER_INFERENCE_PROFILE_ARN` and `ML_CLASSIFIER_TOTAL_BUDGET_SECONDS` (default values from §8.1)
- Verify post-deploy: `aws bedrock get-inference-profile --inference-profile-identifier aegionai-ml-classifier` returns the profile with the expected tags + model routing

### Task 1.6: Unit tests — T-ML-01..10

**Files**:
- `src/security-controller/tests/test_ml_classifier.py` (new)

**Acceptance**: 10 unit test cases from [LLD 19 §12.1](../lld/19-ml-threat-classifier.md#121-unit-tests) all pass. Bedrock client is mocked; tests don't need AWS access.

### Task 1.7: Integration tests — T-MLI-01..04

**Files**:
- `src/security-controller/tests/test_ml_classifier_bedrock.py` (new, gated on `RUN_INTEGRATION=1`)

**Acceptance**: Real Bedrock calls validate that Haiku reliably classifies known-benign and known-attack inputs correctly. Test failure = prompt regression.

### Task 1.8: Pipeline tests — T-PIPE-01..05

**Files**:
- `src/security-controller/tests/test_validation_service.py` (modified — add ML-classifier pipeline cases)

**Acceptance**: 5 new test cases verifying the combiner correctly handles ML signal alongside sigma + policy.

### Task 1.9: Deploy controller image milestone-N

**Acceptance**:
- New controller image built and pushed via `scripts/build_and_push_image.py`
- Task definition includes the new env vars (verify via `aws ecs describe-task-definition`)
- Running task picks up new image AND new env (verify the running task's env block, not just the image)
- Same verification discipline as WS18 M1.7 — don't trust "rollout COMPLETED" alone; check `aws ecs describe-tasks ... environment`

---

## Milestone 2: Eval Harness (3h engineering + 5h human labeling)

**Goal**: Measurable precision/recall/latency/cost. CI-gated.

**Important — M2 has two distinct effort components**:
- **M2a (engineering, ~3h)**: Tasks 2.1, 2.3, 2.4, 2.5 — scripting, CI setup, baseline run.
- **M2b (human review, ~5h focused calendar block)**: Task 2.2 — founder manually reviews ~500 Opus-generated adversarial examples (~30s each + disagreement triage). Schedule as a dedicated block; do not interleave with coding.

M3's CI gate depends on M2b ground-truth labels. If M2b slips, M3 stalls.

### Task 2.1: Dataset extraction script

**Files**:
- `scripts/extract_ml_eval_dataset.py` (new)

**Acceptance**:
- Queries the audit log (LLD 17 §7) for validation events from the last 90 days
- Labels per the rules in LLD 19 §10.2 (sigma DENY → positive with threat_type; trusted ALLOW → negative)
- Excludes policy_engine UNAUTHORIZED_TOOL DENYs (out of distribution)
- Writes labeled JSONL to S3: `s3://sentra-eval/ml-classifier/dataset-v1-YYYYMMDD.jsonl`
- 20% held-out validation split by `session_id` (NOT by row — prevents leakage)
- Reports dataset stats: total rows, label distribution, session count

### Task 2.2: Adversarial dataset

**Files**:
- `scripts/generate_adversarial_dataset.py` (new)

**Acceptance**:
- Uses Opus to generate ~500 synthetic attack examples per threat category in the taxonomy
- Each example reviewed by founder (Streamlit UI or CSV editing) — labels must be human-confirmed
- Written to `s3://sentra-eval/ml-classifier/adversarial-v1.jsonl`
- Includes deliberate edge cases: paraphrases of known patterns, novel framing, ambiguous benign-looking attacks

### Task 2.3: Eval harness

**Files**:
- `scripts/eval_ml_classifier.py` (new)

**Acceptance**:
- Loads dataset (validation split + adversarial)
- Runs each row through the MLClassifierValidator with specified model
- Reports per-threat-category precision, recall, F1; confusion matrix; latency p50/p99; cost
- Output: structured JSON to `./eval_results/<run_id>.json` + human-readable markdown summary
- Per-row predictions saved for failure analysis

### Task 2.4: CI gate

**Files**:
- `.github/workflows/eval-ml-classifier.yml` (new)

**Acceptance**:
- Runs eval harness on every PR touching `app/validators/ml_classifier*` or `ml_classifier_prompts.py`
- Reads thresholds from `eval_thresholds.yaml`: precision ≥95%, recall_high_categories ≥80%, latency_p99_hot ≤1000ms
- PR blocked if any threshold fails
- Output posted as PR comment with delta vs baseline

### Task 2.5: Baseline eval run

**Acceptance**:
- First eval run logged in `eval_results/baseline-{date}.json`
- Findings document in `docs/ml-classifier-baseline.md` with the v0.1 metrics
- Identifies the 3 weakest threat categories for prompt-engineering focus

---

## Milestone 3: Shadow Mode Rollout (3 hours)

**Goal**: ML signals emitted but NOT participating in combiner verdict. Measure real-world accuracy.

### Task 3.1: Shadow-mode flag

**Files**:
- `src/security-controller/app/services/validation_service.py` (modified)
- `src/security-controller/app/config.py` (modified)

**Acceptance**:
- New setting `ml_classifier_shadow_mode` (bool, default false)
- When `shadow_mode=true`, ML validator runs and emits signal as usual, BUT the combiner filter excludes ML signals from verdict
- ML signals still persist to signal store (LLD 17) for later analysis
- Audit log shows "shadow_verdict" metadata field on every entry

### Task 3.2: Enable shadow mode in dev

**Acceptance**:
- `sentra-mvp-cluster` env: `ML_CLASSIFIER_ENABLED=true`, `ML_CLASSIFIER_SHADOW_MODE=true`
- Deploy + verify via task env inspection
- Run S1-S4 scenarios — verify ML signals appear in signal store but don't influence combiner result
- **Exit gate (gates M4 — NOT a calendar duration)**: ≥50 inputs where ML emitted a verdict AND no sigma rule fired (true incremental coverage), OR 21 days elapsed, whichever comes first. Pure S1-S4 replay does NOT satisfy this — those hit sigma, so they reveal nothing about ML's incremental value. Acceptable acceleration: replay the M2b adversarial set into the dev controller to manufacture novel inputs faster.

### Task 3.3: Shadow-mode comparison script

**Files**:
- `scripts/compare_shadow_verdicts.py` (new)

**Acceptance**:
- Queries signal store for last N days
- Reports: ML-would-have-DENIED but combiner-ALLOWed count; ML-would-have-ALLOWed but combiner-DENIED count
- Surfaces top 20 disagreements for human review
- Identifies if ML is more aggressive (false positives) or more permissive (missed catches)

---

## Milestone 4: Active Rollout (4 hours)

**Goal**: ML participates in dev/staging combiner. S1-S4 regression-tested.

### Task 4.1: Flip shadow mode off in dev

**Acceptance**:
- `sentra-mvp-cluster` env: `ML_CLASSIFIER_SHADOW_MODE=false` (ML now affects verdict)
- Deploy + verify
- Re-run S1-S4 scenarios; all 4 still pass with expected outcomes
- Capture before/after latency comparison

### Task 4.2: Staging enable

**Acceptance**:
- Staging env (if separate from dev) gets ML enabled
- 48h burn-in period; monitor abstain_total, latency p99, decision rate

### Task 4.3: S1-S4 regression suite

**Files**:
- `tests/integration/test_cross_cloud_scenarios.py` (modified — add ML-enabled assertions)

**Acceptance**:
- New test variants run S1-S4 with `ML_CLASSIFIER_ENABLED=true`
- All scenarios pass with same `expected_decision` as before
- For S1 sigma-attack probes, verify ML *also* fires DENY (now two signals; sigma is winning_source per LLD 19 §6.1)
- **Migrate scenario assertions for ML-emitted signals from `expected_reason_contains` → `expected_threat_type`**. Reason text is model-generated and drifts across model versions; the `threat_type` enum is the stable contract (LLD 19 §2.3). Sigma-emitted reasons stay reason-text-asserted (deterministic rule strings). Audit all S1-S4 assertions and convert any that target ML signals.

### Task 4.4: Dashboard surface updates

**Files**:
- `src/dashboard/components/cross_cloud_demo.py` (modified)

**Acceptance**:
- New badge `🛡 Sentra ML` for winning_source = `sentra.ml_classifier`
- Signals expander shows ML signal with confidence + model_used + threat_type
- Tested with a scenario that triggers ML-only DENY (synthetic for testing)

---

## Milestone 5: Documentation + Design Partner Pilot (4 hours)

### Task 5.1: User-facing docs

**Files**:
- `docs/sentra-ml-classifier.md` (new) — what it does, what it catches, configuration knobs, opt-in/out
- `best-practices.md` (modified) — new §14 covering threshold tuning, escalation rate, abstain monitoring

### Task 5.2: Design partner enablement

**Acceptance**:
- One of the 3 locked design partners (per [Market + GTM](../../.claude/projects/-Users-shshgup-code-security-mvp/memory/market_gtm.md) §Strategic decisions) opts into ML classifier in their staging env
- 1-week burn-in
- Capture feedback in `feedback/ml-classifier-pilot-{date}.md`

### Task 5.3: Public-facing positioning

**Files**:
- `Sentra/pitch-deck-v3.md` (modified — capabilities section)
- Memory file: update [competitive_landscape.md](../../.claude/projects/-Users-shshgup-code-security-mvp/memory/competitive_landscape.md) to reflect ML capability

**Acceptance**:
- Pitch deck claims "two-layer threat detection: sigma + ML"
- Competitive memory notes Sentra-vs-Lakera positioning shift

---

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Bedrock latency degrades pipeline p99 | Medium | Feature flag + per-customer opt-out; circuit breaker auto-disables on sustained latency |
| ML false-positives block legitimate traffic | High | Shadow mode (M3) catches this before active rollout; precision ≥95% CI gate |
| Bedrock cost runs away | Low | AWS spend alarm at $500/day; circuit breaker at 100 calls/sec sustained |
| Prompt regressions ship | Medium | Eval harness CI gate blocks PRs below precision threshold |
| Customers don't want ML-based decisions | Low | Per-customer opt-in for prod (M5) |
| Bedrock SLA failure during a demo | Medium | ABSTAIN fail mode means sigma + policy still work; demo continues with reduced ML coverage |

---

## What this workstream is NOT

- Not fine-tuning a custom model (Phase 2)
- Not replacing sigma engine (both run in parallel)
- Not adding a new combiner algorithm (LLD 17 deny-overrides handles it)
- Not introducing a new API surface for customers
- Not multi-turn / session-history-aware classification (Phase 2)
- Not output filtering (response-side validation) — request-side only

---

## Effort Summary

| Milestone | Effort | Status |
|---|---|---|
| M1 — MLClassifierValidator + tests | 6h | Pending |
| M2 — Eval harness + dataset | 8h | Pending |
| M3 — Shadow mode rollout | 3h | Pending |
| M4 — Active rollout + regression | 4h | Pending |
| M5 — Docs + design partner pilot | 4h | Pending |
| **Engineering total** | **~25h** | |
| **+ 25% buffer** | parsing edge cases, dataset cleaning, prompt iteration | **~6h** | |
| **Total with buffer** | | **~31h (~4 days)** | |

---

## Sequencing Notes

**Order within Component (engineering)**:

```
M1 (validator + tests + deploy)
    ↓
M2 (eval harness needs M1's validator to call)
    ↓
M3 (shadow mode needs M1's signal emission + M2's metrics to evaluate against)
    ↓
M4 (active needs M3's shadow data showing acceptable accuracy)
    ↓
M5 (rollout + pilot)
```

**Sequencing vs WS18**:
- WS19 starts **after WS18 engineering completes** (M1-M7 of WS18). Reason: introducing a new validator while WS18 is mid-flight risks confusing the S2/S3/S4 debug loop. Keep one major change per workstream cycle.
- WS19 LLD can be reviewed in parallel with WS18 implementation.

---

## Open Questions Tracked

- Threshold values for confidence bands (locked after M2 eval)
- Shadow mode duration (default 7 days; tunable based on traffic volume)
- Per-customer model selection commercial design (Phase 2)
- Multi-turn context expansion (Phase 2)
- Caching ADR (Phase 2)
- Bedrock cross-region fallback (Phase 2)
