# Sentra ML Threat Classifier — Operator Guide

**Audience**: Sentra operators, design-partner DevSecOps, and customers evaluating whether to enable ML threat classification on their `/v1/validate` traffic.

**References**: [LLD 19](../lld/19-ml-threat-classifier.md), [Workstream 19](../tasks/workstream-19-ml-threat-classifier.md), [LLD 17 §4](../lld/17-validation-signal-store.md).

---

## 1. What it does

The ML Threat Classifier is a Sentra-side validator that runs on every `/v1/validate` call (when enabled) and contributes one `Signal(source=sentra.ml_classifier)` per invocation. It catches **semantic threats that the deterministic sigma rule engine misses**:

- Paraphrased prompt injection ("forget what the system told you")
- Indirect data exfiltration framed as a routine query
- Novel jailbreaks the rule library has not been updated for
- Borderline-benign requests that the rule engine alone would miss

It is **defense-in-depth**, not a replacement for sigma. Both run on every call; deny-overrides combines them. Sigma's deterministic match is preferred for audit (cited as `winning_source`); ML supplements it.

## 2. What it does NOT do

- It does not block authorization gaps — that's `policy_engine`'s job.
- It does not enforce rate limits — that's `abuse_detector`'s job.
- It does not see session history — single-request context only (multi-turn is Phase 2).
- It does not classify response content — request-side only.

## 3. The three knobs (most operators only touch the first)

| Setting | Default | When to flip |
|---|---|---|
| `ML_CLASSIFIER_ENABLED` | `false` | Turn on after WS19 M2 eval-harness sign-off (precision ≥ 95% on your traffic). |
| `ML_CLASSIFIER_SHADOW_MODE` | `false` | Set to `true` first, before flipping `_ENABLED`. ML runs and emits signals to the audit log but does NOT influence the live verdict. Lets you measure incremental value risk-free. |
| `ML_CLASSIFIER_INFERENCE_PROFILE_ARN` | (CDK-provisioned) | Leave alone. The default points at the workload-isolated `aegionai-ml-classifier` Application Inference Profile (LLD 19 §2.4); changing it merges your validator's quota/cost with whatever you point it at. |

Advanced (rarely touched — see §6):

- `ML_CLASSIFIER_HOT_MODEL_ID` (default Haiku 4.5)
- `ML_CLASSIFIER_ESCALATION_MODEL_ID` (default Sonnet 4.6)
- `ML_CLASSIFIER_TIMEOUT_SECONDS` (per-tier, 2.0)
- `ML_CLASSIFIER_TOTAL_BUDGET_SECONDS` (aggregate ceiling, 2.5)
- `ML_CONFIDENCE_TRUST_THRESHOLD` (0.9 — below this, escalate)
- `ML_CONFIDENCE_ABSTAIN_THRESHOLD` (0.5 — below this, abstain)

## 4. Rollout sequence (do not skip)

Stages map to the LLD 19 §11.1 phased rollout. Skipping `shadow` and flipping `enabled` straight to `true` in customer traffic is unsupported.

1. **Stage 0 — disabled** (default).
   `ML_CLASSIFIER_ENABLED=false`. Validator class is loaded but never invoked. Zero Bedrock cost.

2. **Stage 1 — dev cluster, flag on, shadow off**.
   `ML_CLASSIFIER_ENABLED=true, ML_CLASSIFIER_SHADOW_MODE=false`. Run S1-S4 cross-cloud scenarios. Verify no regressions on the deterministic path.

3. **Stage 2 — shadow mode**.
   `ML_CLASSIFIER_ENABLED=true, ML_CLASSIFIER_SHADOW_MODE=true`. ML emits signals to the audit log + signal store but the customer-facing verdict comes from sigma + policy alone. Run for at least the time it takes to observe **≥50 novel inputs** (requests where ML emitted a verdict and no sigma rule matched). This is the M3 exit gate per workstream-19 Task 3.2 — `scripts/compare_shadow_verdicts.py` reports the count.

4. **Stage 3 — active in dev**.
   Flip `ML_CLASSIFIER_SHADOW_MODE=false`. ML's DENY now influences the verdict. Re-run S1-S4 + monitor latency p99 and abstain rate for 48h.

5. **Stage 4 — opt-in for customer prod**.
   Per-customer; configured via their policy file. Customers acknowledge the relaxed `/v1/validate` p99 SLA (LLD 19 §3.2.1) in writing before enabling.

## 5. Monitoring

| Metric | Threshold | Where it surfaces |
|---|---|---|
| `sentra_ml_classifier_abstain_total{reason="bedrock_timeout"}` | spike >10× baseline | CloudWatch — pageable; Bedrock region likely degraded |
| `sentra_ml_classifier_abstain_total{reason="bedrock_4xx"}` | sustained >1/min | CloudWatch — pageable; config / quota regression |
| `sentra_ml_classifier_latency_seconds{tier="hot"}` p99 | >1.5s | Slack — Haiku slow; tune escalation thresholds |
| `sentra_ml_classifier_decision_total{decision="DENY"}` | spike >5× baseline | Slack — possible attack wave OR false-positive regression |
| `sentra_ml_classifier_escalation_rate` | sustained >30% | Slack — Haiku consistently uncertain |
| `OTHER` share of ML DENYs | >5% sustained 24h | Slack — taxonomy hole; needs eval-harness review |

## 6. Tuning the thresholds

Default values come from LLD 19 §4.4. They were chosen as intuitive starting points, not measured optima. After every eval-harness run (M2 Task 2.5), compare precision/recall against `scripts/eval_thresholds.yaml`. If recall on `PROMPT_INJECTION` or `PII_EXPOSURE` is consistently below 0.80 on the holdout set:

1. First try lowering `ML_CONFIDENCE_TRUST_THRESHOLD` from 0.9 → 0.85. This sends more borderline calls to Sonnet (cost goes up a bit, recall usually improves).
2. If that's not enough, iterate on `ml_classifier_prompts.py`. Add a few-shot example that demonstrates the missed pattern. Re-run eval. CI gate must still pass.
3. Last resort: bump the hot model from Haiku 4.5 → Sonnet 4.6. Pipeline p99 rises from ~600ms → ~1500ms; verify against your SLA before flipping.

Don't tune `ML_CONFIDENCE_ABSTAIN_THRESHOLD` without measurement — it's the floor below which ML declines to vote at all. Lowering it inflates the share of abstain-only decisions; raising it means ABSTAIN never happens (which is bad — it implies you trust the model on inputs it itself doesn't understand).

## 7. Cost expectations

At 1M validations/day with Haiku 4.5 on the hot path and ~10% escalation to Sonnet:

| Workload | Daily Bedrock spend (rough) |
|---|---|
| 100k validations | $0.08 |
| 1M validations | $0.83 |
| 10M validations | $8.30 |

Cost is dominated by Sonnet escalations, not Haiku hot-path calls. If you see escalation rate sustained above 20%, the prompt or thresholds need attention.

## 8. Disabling in an emergency

Flip `ML_CLASSIFIER_ENABLED=false` via SSM Parameter Store or task definition update. The validator stops being invoked; the pipeline falls back to sigma + policy alone. No customer impact, no redeploy needed.

A circuit-breaker auto-disables the validator if `sentra_ml_classifier_call_total > 100/sec sustained for 5 minutes` (cost runaway protection — LLD 19 §14.2). On-call gets paged via PagerDuty.

## 9. What to read next

- [LLD 19](../lld/19-ml-threat-classifier.md) — architecture + rationale (§2.4 workload isolation, §3.2 sequential pipeline, §9 fail mode)
- [best-practices.md §14](../best-practices.md) — operator runbook (this doc's runbook excerpts)
- [Workstream 19](../tasks/workstream-19-ml-threat-classifier.md) — milestone tracker; lists open follow-up items (parallel-gather refactor, fine-tuning, multi-turn context)
