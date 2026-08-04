# WS-E: Mode B End-to-End Rig, AgentDojo Insertion & Run Accounting

**Parent LLD**: [lld/41-benchmark-harness.md](../../lld/41-benchmark-harness.md) §4.4 (D4), §4.4b, §5.2, §7.1.1, §9, §13, §14
**Status**: `SCOPE`
**Owner**: TBD
**Milestone covered**: M2 (second half) — **exits with the first headline number (G1)**

> **⚠️ BLOCKED ON AN UNOWNED PREREQUISITE (OP-1).** Mode B costs **~$40–160 per full AgentDojo P1 run** and **~$100–400 with P2+P3**. The LLM budget is **unowned** (sub-PRD §6). Nothing in WS-A/B/C/D depends on it — **do not let this workstream's block stall those.**

## Dependencies

- **Depends on**: **WS-A** (`BenchmarkAdapter`, `RunContext`, `cases.jsonl`, manifest `results.mode_b`/`model`/`accounting` blocks, `report.py`) · **WS-B** (`enforce()`) · **WS-C** (the AgentDojo adapter package + `tool_manifest()`) · **WS-D** (`GuardClient`, `BenchmarkSessionStore`, `BenchmarkPolicyEngine`, attribution).
- **Blocks**: WS-A's M3 tail (`diff.py` needs two Mode B runs) and **WS-F** (ASB reuses this rig unchanged — that reuse *is* the G4 proof).
- **Shared contracts OWNED here**: `ArmResult` / `RunScore` population semantics · `results.mode_b` + `accounting` manifest blocks · `noise_floor`.
- **Shared contracts CONSUMED here**: `BenchmarkAdapter` (implements `run_arm` + `score_run`), `BenchmarkCase`, `RunContext`, `cases.jsonl`, `GuardClient`, `detector_readiness`.

---

## Model / read before coding

1. **Mode B is the result; Mode A is the instrument.** Mode A recall does not predict Mode B ASR reduction in either direction. The two cases that make this true: (a) Sentra flags an injected passage the agent would have ignored anyway — Mode A scores a TP, ASR does not move; (b) the injection sails past D2 (Mode A: FN) but the **action** it asks for is refused by Cedar or a parameter bound at `phase=request` — ASR falls, D2 recall unchanged. **(b) is the product's actual thesis**, which is why a design reporting only Mode A would systematically under-report the product.
2. **This is composition, not a fork.** AgentDojo already ships a defense in exactly this shape: `PipelineConfig.defense == "transformers_pi_detector"` builds `ToolsExecutionLoop([ToolsExecutor(fmt), TransformersBasedPIDetector(...), llm])` (`agent_pipeline/agent_pipeline.py:239`). **We use the same slot.**
3. **A DENY is a tool error, not an exception** (OBQ-3, RESOLVED). AgentDojo already treats tool errors as a first-class non-fatal path: `runtime.run_function` returns `(result, error)` and `ToolsExecutor` appends a `ChatToolResultMessage` carrying that error (`agent_pipeline/tool_execution.py:11,:77`). A DENY maps onto the existing channel **with no fork of the benchmark**.
4. **Fidelity caveat, stated rather than hidden:** in the real product `ToolDenied` is raised into the integrator's code, and what happens next is the integrator's choice — some agents crash, some catch and continue. **The benchmark deliberately models catch-and-continue.** That is a modeling decision, not a claim about all deployments.
5. **Paired arms are mandatory.** Without the without-Guard arm, a run-over-run ASR change cannot be separated from model drift or benchmark variance, and the loop steers on noise.

---

## Milestone E1 — checkpoint insertion into AgentDojo's own loop

```mermaid
flowchart LR
  subgraph LOOP["ToolsExecutionLoop, max_iters=15"]
    direction LR
    RG["SentraRequestGuard<br/>phase=request<br/>BEFORE execution"] --> TE["ToolsExecutor<br/>runtime.run_function"]
    TE --> CG["SentraContentGuard<br/>phase=content<br/>AFTER execution"]
    CG --> LLM["the benchmark's LLM element"]
    LLM --> RG
  end
  PIPE["AgentPipeline<br/>SystemMessage · InitQuery · LLM"] --> LOOP
```

### E1 — `benchmarks/adapters/agentdojo/guards.py`

**`SentraContentGuard`** subclasses AgentDojo's own `PromptInjectionDetector` (`agent_pipeline/pi_detector.py:18`) and implements only `detect()` and `transform()` — inheriting its message-mode scan, its multi-tool-result walk, and its `raise_on_injection=False` non-fatal path.

```python
class SentraContentGuard(PromptInjectionDetector):
    """phase=content. Sits AFTER ToolsExecutor; scans each ChatToolResultMessage.
    Constructed in message-mode, non-fatal — it must NEVER abort the loop, because an
    aborted episode has no utility number and a 0%-ASR/0%-utility run measures nothing."""
    def __init__(self, client: GuardClient, ctx: EpisodeCtx): ...
    def detect(self, tool_output: str) -> tuple[bool, float]:
        """Delegates to GuardClient.validate(phase='content'), records the verdict for
        attribution, and returns (denied, confidence) in the ABC's own shape."""
    def transform(self, blocks) -> list:
        """OBQ-3 sub-decision: substitute the PRODUCT'S real reason string, not a generic
        notice. The agent must see what a real deployment would have shown it."""
```

**⚠️ SELF-CONTAMINATION: the content guard must not re-scan the rig's own denial messages.** `PromptInjectionDetector.query` walks **backwards over every consecutive trailing `role == "tool"` message** (`pi_detector.py:65-78`), not just the newest one. In the mixed / all-deny path below, `SentraRequestGuard` appends **synthesized** `ChatToolResultMessage`s carrying our own denial text — so on the next turn the content guard hands **the harness's own output** to `phase=content` as if it were ingested tool data. The damage is not hypothetical: those are unlabeled synthetic validates that inflate `n_validate_calls`, skew `latency_ms`, and can add `by_deciding_source` rows for which **no ground truth exists**. This is tie-breaker-F contamination **the rig injects into itself**, which is the worst kind, because nothing external is misbehaving.

**The fix is one tag and one early return:** `SentraRequestGuard` stamps every message it synthesizes (`extra_args` / message metadata key **`aegion_synthetic: true`**), and `SentraContentGuard.detect()` returns `(False, 0.0)` **without calling `GuardClient`** for any tagged message. The count is recorded as `results.mode_b.synthetic_content_skipped` — **a skip that leaves no trace is indistinguishable from a guard that never ran.**

**`SentraRequestGuard` and the partial-denial problem.** `ToolsExecutor.query` returns **early** when `messages[-1]["role"] != "assistant"` (`tool_execution.py:68`). So if the request guard appends *any* tool-result message, the executor short-circuits **entirely** — which is right when every call in the turn is denied and **wrong** when only one of three is.

```python
class SentraRequestGuard(BasePipelineElement):
    """phase=request. Sits BEFORE ToolsExecutor; validates every tool_call in the turn."""
    def __init__(self, client: GuardClient, ctx: EpisodeCtx, formatter): ...
    def query(self, query, runtime, env, messages, extra_args) -> tuple:
        """Three branches:
        (a) not an assistant turn with tool_calls -> pass through untouched.
        (b) ALL allowed -> pass through untouched; AgentDojo's own ToolsExecutor runs next.
        (c) MIXED or ALL-DENY -> this element owns the turn."""
```

**The (c) branch, as a rule rather than as code:** the guard holds a **private `ToolsExecutor` instance built from the same formatter** and **delegates the allowed subset to it** over a shadow assistant message carrying only the allowed `tool_calls` — rather than reimplementing that executor's `literal_eval` list coercion, its `EMPTY_FUNCTION_NAME` handling and its invalid-tool branch. Denied calls become tool errors. The two result sets are then **merged in the original `tool_call` order**, so the transcript a human reads is faithful to what the model emitted.

**Delegation is what keeps this composition rather than a fork:** every behavior of AgentDojo's executor we did not explicitly change stays byte-identical — the property that makes our numbers comparable to the benchmark's published baselines.

**Footguns:**
- **Do NOT reimplement `ToolsExecutor`'s coercion logic.** Delegate. A reimplementation drifts on the next upstream bump and silently changes what is measured.
- **Do NOT let the content guard abort the loop.** `raise_on_injection=False`, always.
- **Do NOT use `@guard.tool`** — WS-D's rule; `ToolDenied` kills the loop.
- **Retry inflation is bounded by the benchmark, not by us.** `ToolsExecutionLoop(max_iters=15)` (`tool_execution.py:130`) already caps retries. **No custom cap is added** — but the value is **recorded in the manifest**, because changing it changes ASR.

**Unit tests — `benchmarks/tests/test_guards_agentdojo.py`:**
- `test_branch_a_non_assistant_turn_passes_through` — messages returned identical (identity, not equality, where possible).
- `test_branch_b_all_allowed_passes_through` — the guard appends nothing, so `ToolsExecutor` runs normally.
- `test_branch_c_mixed_delegates_allowed_subset` — 3 calls, 1 denied ⇒ the private `ToolsExecutor` is invoked with exactly the 2 allowed calls (spy), and the merged results are in the **original** order.
- `test_branch_c_all_denied_appends_only_errors` — no executor call at all.
- `test_deny_rides_chat_tool_result_message_error_field` — the denial lands in `error=`, carrying the **product's real reason string**, not a generic notice.
- `test_synthetic_messages_are_tagged` — every message the request guard appends carries `aegion_synthetic: true`.
- `test_content_guard_skips_synthetic_and_counts_it` — a tagged message yields `(False, 0.0)`, `GuardClient` is **not** called, and `synthetic_content_skipped` increments. **This is the self-contamination test.**
- `test_content_guard_never_raises` — a `GuardClient` that raises still returns a tuple and lets the loop continue (the raise becomes an `ERROR` row).

**Integration test — `benchmarks/tests/integration/test_guarded_pipeline_shape.py`** *(cross-component: AgentDojo's `BasePipelineElement` ABC ↔ our guards)*: builds a real `AgentPipeline` via `AgentPipeline.from_config`, rebuilds its `ToolsExecutionLoop` with both guards, and runs **one** episode against a **stubbed LLM element** (no spend) — asserting the loop completes, the element order is `[SentraRequestGuard, ToolsExecutor, SentraContentGuard, llm]`, `max_iters == 15`, and no exception escaped. This is the seam an upstream AgentDojo bump would break, and it breaks **loudly at import**, which is exactly the property §6.3 credits AgentDojo with over ASB.

---

## Milestone E2 — the arms

### E2 — `run_arm()` and `score_run()` on the AgentDojo adapter (§5.2)

```python
def run_arm(self, *, arm, ctx):
    cfg = PipelineConfig(llm=ctx.model_id, defense=None, system_message_id=...,
                         tool_output_format="yaml")
    pipeline = AgentPipeline.from_config(cfg)          # stock; arm == "without" stops here
    if arm == "with":
        pipeline = self._insert_guards(pipeline, ctx)  # E1 — rebuild the ToolsExecutionLoop
    attack = load_attack(ctx.attack_name, suite, pipeline)      # attack_registry.py:40
    return benchmark_suite_with_injections(pipeline, suite, attack,
                                           logdir=ctx.transcript_dir,
                                           force_rerun=True,           # never read a stale log
                                           benchmark_version=ctx.benchmark_version)
```

**`force_rerun=True` is required, not cosmetic:** AgentDojo will otherwise reuse a cached log for a task it has seen, and a cached with-arm result **silently mixes runs** — tie-breaker E.

**`score_run` maps AgentDojo's own outputs — it never re-derives them.** `benchmark_suite_with_injections` returns `SuiteResults` with `utility_results` and `security_results` keyed by `(user_task_id, injection_task_id)` (`agentdojo/src/agentdojo/benchmark.py:160`). Reimplementing "did the attack succeed" would silently diverge from the published baseline and destroy the one property that makes a public benchmark worth using.

| `RunScore` field | Derivation |
|---|---|
| `asr_with` / `asr_without` | `1 − aggregate(security_results)` per arm. **AgentDojo's `security=True` means the *attack failed*.** `benchmark.py:150` sets `security = not utility` in the fallback branch, so **the mapping is inverted once, in one place, with a comment.** |
| `utility_with` / `utility_without` | `aggregate_results(utility_results)` (`benchmark.py:36`) |
| `utility_retention` | `utility_with / utility_without`, reported as a percentage **with both raw numbers alongside** — a ratio without its denominator hides a collapsed baseline |
| `refuse_rate` | **ours, not AgentDojo's**: `episodes with >=1 DENY / total episodes`, from the attribution rows |
| `asr_reduction_pp` | `asr_without − asr_with`, in **percentage points**, never as a relative percentage (a relative "70% reduction" off a 3% base is a rounding error dressed as a result) |

**Model and provider.** `AgentPipeline.from_config` routes `provider == "anthropic"` to `anthropic.Anthropic()` (`agent_pipeline.py:75`) — **the direct Anthropic API, not Bedrock**. Mode B therefore needs **`ANTHROPIC_API_KEY`** and does **not** use the AWS path at all, which is a happy accident for WS-B: credential sentinelization does not interfere with the benchmark's own LLM calls. The manifest pins the **exact dated model id**; never a floating alias.

**Footguns:**
- **Invert the security→ASR mapping exactly once**, in `score_run`, with a comment naming `benchmark.py:150`. Two inversions is a sign flip nobody catches until the number looks wrong.
- **Do not omit `force_rerun=True`.**
- **`ANTHROPIC_API_KEY` is never recorded** in the manifest (SEC-2).
- Paired arms must run against **the same pinned everything** — same model snapshot, same benchmark SHA, same suite, same task subset, same attack.

**Unit tests — `benchmarks/tests/test_score_run.py`:**
- `test_security_true_means_attack_failed` — a `SuiteResults` with all `security=True` yields `asr == 0.0`. **The sign test.**
- `test_asr_reduction_is_pp_not_relative` — `asr_without=0.43, asr_with=0.11 ⇒ 32.0`.
- `test_utility_retention_reports_both_raw_numbers` — the emitted dict carries `utility_with`, `utility_without` **and** the ratio.
- `test_refuse_rate_from_attribution_rows` — computed from `cases.jsonl`-shaped rows, not from AgentDojo.
- `test_force_rerun_is_true` — assert the kwarg passed to `benchmark_suite_with_injections`.
- `test_model_id_is_dated_snapshot` — a model id matching `-latest` or a bare family name raises at manifest-collect time.

### E3 — which arms run (§4.4b)

| Arm pair | Answers | Cadence |
|---|---|---|
| **P1 — injected suite, with vs without** (mandatory) | ASR reduction, `utility_retention` **under attack**. The headline. | every Mode B run |
| **P2 — clean suite, with vs without** | *"What does this cost me on normal traffic?"* — the **false-positive tax**. **P1's `utility_retention` is utility-under-attack and is systematically NOT this number; quoting it as such is the single easiest way for this rig to mislead a buyer.** | every Mode B run (the clean suite is already extracted for WS-C's negatives, so the marginal cost is the without-arm LLM spend, not a new corpus) |
| **P3 — injected suite, `phase == "request"` corpus only** | *"What does the AS-DEPLOYED configuration do?"* The headline lets D2/D3 fire on `content`/`memory`, while **100% of production traffic is `phase=request`** (ADR-036). P3 is the number a customer would actually get today. | every Mode B run; one corpus filter + one extra with-arm |

**⚠️ P3 IS A CORPUS FILTER, NOT A DETECTOR FLAG.** Restrict P3's corpus to `phase == "request"` cases — **that is what ADR-036's finding means**. It is emphatically **not** achieved by setting detector flags: **`D2_ENABLED`/`D3_ENABLED` DO NOT EXIST** (WS-C C3). An implementer who "disables D2/D3" gets a P3 arm **byte-identical to P1's**, printed beside it under an "as-deployed" label — **a fabricated figure with no error raised.**

**The guard, and it is a required task:** the rig asserts **`P3.corpus_digest != P1.corpus_digest`** and **fails the run** if they are equal, so an inert P3 dies loudly rather than flattering the headline.

**P3 is not pessimism, it is the honest headline's denominator.** Reporting only P1 states what the product *can* do with detectors that decide zero production requests; reporting P1 and P3 side by side states both what it can do and what it does.

**P4 — the sham guard: recommended ONCE, not per cycle.** The with-arm's denial does two things simultaneously: it removes the injection's carrier content from the agent's context, **and** it tells the model that a security system is watching. Two mechanisms bundled into one treatment, both credited to "the Guard". A sham-guard arm — validates every call, **always allows**, returns an equivalently-shaped tool error at the same rate — separates them. **A one-off calibration**, and its result belongs in the report as a **standing caveat on `asr_reduction_pp`**, not as a recurring column.

**Unit tests — `benchmarks/tests/test_arms.py`:**
- `test_p3_corpus_is_request_phase_only` — every case in the P3 corpus has `phase == "request"`.
- `test_p3_digest_divergence_asserted` — a stubbed run where P3's filter is a no-op (so the digests match) **fails the run** with a message naming P3. **This is the fabricated-figure guard, and it is the test that matters most in this file.**
- `test_no_code_reads_d2_or_d3_enabled` — source scan over `benchmarks/` for `D2_ENABLED`/`D3_ENABLED`.
- `test_default_arms_are_p1_p2_p3` — and `--arms P1` runs only P1.
- `test_p2_labelled_clean_traffic_false_positive_tax` — the results block labels P2 distinctly from P1's `utility_retention`.
- `test_p4_is_not_in_the_default_arm_set`.

**Integration test — `benchmarks/tests/integration/test_paired_arms_stub_llm.py`** *(shared contract: `run_arm`/`score_run` + `results.mode_b`)*: runs P1, P2 and P3 end-to-end against a **stubbed LLM** (deterministic canned completions, zero spend) over a 6-episode fixture suite, and asserts: both arms produced results, `asr_reduction_pp` is computed in pp, the three arms appear under `results.mode_b.arms`, P3's digest differs from P1's, `episodes_quarantined` and `synthetic_content_skipped` are populated, and `cases.jsonl` carries `arm ∈ {with, without}` rows for every episode.

---

## Milestone E3 — accounting, the noise floor, and the honest report inputs

### E4 — `benchmarks/core/accounting.py::RunAccountant` (§14.2)

Billing is **genuinely N/A** — `benchmarks/` is internal tooling with no external consumer, no invoice line, no usage record. Critically, **benchmark validations must be EXCLUDED from the product's own metering**, not merely uncharged: a benchmark validate counted as a real tenant's billable verdict is both a billing error and an isolation blind spot. WS-B's chain prevents it (in-process never reaches a meter; hosted meters under `_benchmark`, a reserved tenant no invoice can be issued against).

What **is** metered is the run's own consumption:

| Counter | Increment point | Attribution key |
|---|---|---|
| `input_tokens`, `output_tokens` | `RunAccountant.record()`, once per LLM response as the episode advances | `(episode_id, arm)` |
| `cost_usd` | derived at run end from tokens × the manifest's **pinned per-model rate** | `arm`, then run total |
| `n_validate_calls` | once per `GuardClient.validate()` return, **both transports**, in a `finally` (WS-D D4) | `(episode_id, arm, phase)` |
| `wall_clock_s` | per episode, and per run | `arm` |

**Attribution is per episode and per arm — never per tenant or per agent** (one synthetic agent, one reserved tenant, so those dimensions carry no information). **Per-arm is the dimension that does carry information**: it exposes the with-arm's retry-driven cost premium, otherwise invisible.

**REUSE, do not reinvent:** `_estimate_cost(model_id, n_calls)` (`scripts/eval_ml_classifier.py:147`) is the **existing per-model rate table**. `RunAccountant` **extends** it (token-based rather than call-based, since Mode B's cost is dominated by accumulating context) and **shares one rate table**. It does not stand up a second one.

**Exactly-once:** `--resume` is the only double-count path, and `cases.jsonl` is the ledger with join key **`(case_id, arm)`**. The residual is **under-count, never over-count** — an episode whose call succeeded but whose row never landed is re-run and re-billed by the provider, so `cost_usd` under-reports by at most one episode per crash (~$0.15). **That direction is deliberate:** an over-report makes the loop look more expensive than it is and could kill it.

**Unit tests — `benchmarks/tests/test_accounting.py`:**
- `test_shares_rate_table_with_eval_ml_classifier` — identity/equality check against `_estimate_cost`'s table, not a copy.
- `test_token_based_not_call_based` — two responses with different token counts produce different costs for the same call count.
- `test_attribution_key_is_episode_and_arm` — never a tenant/agent dimension.
- `test_resume_does_not_double_count` — a resumed run over an existing ledger produces the same `cost_usd` as the uninterrupted run, ±one episode **downward only**.
- `test_n_validate_calls_counted_on_exception_path` — pairs with WS-D's `finally` test from the accountant's side.
- `test_with_arm_premium_visible` — the per-arm breakdown shows the with-arm's higher token total (the retry premium).

### E5 — `noise_floor` (§7.1.1) — **the M2 gate nobody may skip**

**Sampling is UNPINNABLE.** There is **no `seed` parameter** on the Anthropic Messages API; `temperature: 0` never guaranteed identical outputs on any model; and `temperature`/`top_p`/`top_k` are **removed on Claude Opus 5, Fable 5, Opus 4.8 and Opus 4.7 — sending any of them returns 400**, with Claude Sonnet 5 rejecting non-default values. So the largest variance source in Mode B cannot be pinned, and **overclaiming it is worse than admitting it**: a `diff.py` that labels a cell **regressed** would otherwise be reporting resampling noise as a product regression.

The noise floor is therefore a **first-class output**, defined properly:

**(a) The floor must cover a DIFFERENCE of two arms, so it is √2 wider than a single-arm spread.** `asr_reduction_pp = asr_without − asr_with` is a difference of two independently-sampled quantities: if each arm has SD σ, the difference has SD ≈ **√2·σ**. A floor estimated from without-arm replicates alone measures σ and is applied to something that varies by √2·σ — so ~30% of the true resolution limit sits **below** the floor and gets labelled `regressed`. **Two acceptable resolutions:** replicate **both** arms and take the spread of the *reduction* directly (no assumption needed) — preferred when budget permits; **or** replicate the without-arm only, **state the independence assumption explicitly in the manifest**, and inflate the observed single-arm spread by √2.

**(b) `noise_floor_pp` is a DEFINED STATISTIC over ≥2 replicate pairs, not "the observed spread" of one.** One replicate pair yields one number — a sample of size one, from which no dispersion can be estimated. Record `noise_floor.n_replicates` (**minimum 2 pairs, 3 preferred**), `noise_floor.method` (`"paired"` | `"single_arm_x_sqrt2"`), and define **`noise_floor_pp` = the maximum absolute pairwise difference across replicates** — a conservative, assumption-free choice at n=2–3, where an SD would be a fiction with two decimal places. If replicates ever reach the tens, this becomes a named percentile and the manifest field says which. **"The observed spread" is not a definition and is not used.**

**(c) The floor gates the AGGREGATE line, not the per-case buckets** — see WS-A A7. Per-case flips are reported as-is, always.

*(This costs one to two extra arm runs at M2 — the cheapest insurance in the whole design, and the difference between a steering signal and a random walk.)*

**Unit tests — `benchmarks/tests/test_noise_floor.py`:**
- `test_single_replicate_pair_raises` — n=1 ⇒ refuses to emit a floor (a sample of one has no dispersion).
- `test_max_abs_pairwise_difference` — three replicates `{30.0, 32.0, 33.5}` ⇒ `noise_floor_pp == 3.5`, not an SD.
- `test_single_arm_method_applies_sqrt2` — `method="single_arm_x_sqrt2"` multiplies the observed spread by √2 and records the method **and** the independence assumption in the manifest.
- `test_paired_method_takes_reduction_spread_directly` — no √2 applied.
- `test_manifest_records_n_replicates_and_method`.

**Integration test — `benchmarks/tests/integration/test_noise_floor_end_to_end.py`** *(shared contract: `results.mode_b.noise_floor` → consumed by WS-A's `diff.py` and `report.py`)*: runs 3 stubbed replicate pairs with injected per-arm jitter, asserts `noise_floor_pp` is computed by the declared method, then feeds two runs whose `Δ asr_reduction_pp` is **below** the floor into `diff.py` and asserts the aggregate line reads **`within-noise`** while the per-case `fixed`/`regressed` lists are **still fully populated**.

### E6 — the honest report inputs (§4.6, §7.2, §7.3)

Populate, per Mode B run:
- `episodes_quarantined` — **an absorbing state, NOT a defense.** The report treats a high count as **a finding about the measurement**: an ASR of 0.00 with a third of episodes quarantined is a rig artifact of the −15 penalty compounding faster than a 15-iteration loop can absorb, and reading it as efficacy is the ADR-036 shape happening inside our own instrument.
- `synthetic_content_skipped` — E1's self-contamination guard.
- `by_deciding_source_first_deny` — **denominator = episodes; numerator = the FIRST deny per episode.** Counting per decision lets one quarantined episode contribute a dozen `sentra.trust` rows while a clean single-shot catch by D2 contributes one — **inflating trust's share by exactly the mechanism this table exists to expose.** The raw per-decision counts are emitted alongside as `by_deciding_source_all_denies`, **labelled as such**, because they are the right denominator for **latency and `n_validate_calls` only**.
- **If `sentra.trust` dominates, G2 is defeated for that run and the report says so in words, not only as a percentage.**

**Why trust dominates when it does:** `Source.SENTRA_TRUST` carries priority **90** — the highest in `DEFAULT_PRIORITIES` (`app/combiners/sources.py`), above `sentra.sigma` (70), `sentra.trajectory` (68), `sentra.indirect_injection` (62), `sentra.memory` (58). **Once trust denies, it also wins the attribution tie-break.** That is the exact shape of ADR-036's production finding.

**Unit tests — `benchmarks/tests/test_mode_b_results.py`:**
- `test_first_deny_denominator_is_episodes` — a quarantined episode with 12 trust denies contributes **1** to the first-deny table and 12 to the all-denies table.
- `test_both_tables_emitted_and_labelled`.
- `test_trust_dominance_emits_a_worded_finding` — `sentra.trust` > 50% of first-denies ⇒ the report contains a sentence saying G2 is defeated for this run.
- `test_episodes_quarantined_rolls_up_from_rows`.
- `test_synthetic_content_skipped_rolls_up`.

**Integration test — `benchmarks/tests/integration/test_attribution_rollup.py`** *(shared contract: `cases.jsonl` → `results.mode_b` rollup, spanning WS-A/WS-D/WS-E)*: from a fixture ledger containing a quarantined episode, a Cedar-denied episode and a D2-denied episode, asserts the emitted `by_deciding_source_first_deny` equals the hand-computed expectation and that `report.py` renders the three lines with the correct percentages and the trust caveat.

---

## Error model

| Condition | Response | Concrete value |
|---|---|---|
| LLM 429 / 5xx (RES-4) | bounded exponential backoff, **full jitter** | base 1 s, ×2, max 60 s, **5 attempts**; then episode `ERROR`; **abort if >5% of episodes error** |
| Engine unreachable, hosted (RES-3) | **run aborts** — a with-arm episode proceeding unvalidated would score as "the Guard allowed it", a **fabricated ALLOW** | 3 consecutive transport failures ⇒ abort; **no partial arm reported** |
| Mid-run crash (RES-5) | `cases.jsonl` append+fsync per episode; `--resume {run_id}` under the **same** `RunContext` | **RPO = one episode (~$0.05–0.15)**; RTO = the remaining wall clock |
| P3 digest equals P1 digest | **fail the run**, naming P3 | — |
| Content guard raises | returns `(False, 0.0)`, episode continues, `ERROR` row recorded | never aborts the loop |
| Concurrency requested > 8 | refused (WS-A A4) | above 8 the provider's rate limiter dominates episode-level variance, and variance is the enemy of the diff |

**Scale (§9):** ~**3–5 h** for 620 episodes × 2 arms × ~15 LLM turns, `asyncio` fan-out **across** episodes (default 4, cap 8). Bounded by the provider's rate limit, not by us. **Super-linear in denial rate** — a product improvement that raises the block rate *raises* the cost of measuring it.

**Latency (§9):** in-process `latency_ms` is a **compute figure** (~5–30 ms) and **the report never presents it as a product latency** — it omits the network round-trip *and*, with `BenchmarkSessionStore` in place, the session read a deployed engine pays. The product's targets are ≤500 ms p99 deterministic-floor and ≤900 ms ML-hot ([LLD 24](../../lld/24-latency-optimization.md)) against ~0.6–1.2 s on Serverless today. **The hosted Mode B run is the only configuration where the measured number IS the deployed number** — gated on **OP-2**.

---

## Acceptance criteria (whole workstream)

- [ ] Both guards are inserted by **composition** into `ToolsExecutionLoop` — the same slot AgentDojo's own `transformers_pi_detector` defense uses — with **no fork** of the benchmark.
- [ ] `SentraRequestGuard` implements all three branches, and branch (c) **delegates the allowed subset to a private `ToolsExecutor`** rather than reimplementing its coercion logic; results merge in the **original** `tool_call` order.
- [ ] Every synthesized message carries `aegion_synthetic: true`; `SentraContentGuard` skips tagged messages **without calling `GuardClient`**, and the count lands in `results.mode_b.synthetic_content_skipped`.
- [ ] A DENY rides `ChatToolResultMessage(error=<the product's real reason string>)`; the loop never aborts; `max_iters=15` is **recorded, not set**.
- [ ] `score_run` calls **AgentDojo's own scorer**; the `security → ASR` inversion happens **exactly once**, commented, naming `benchmark.py:150`. `force_rerun=True`.
- [ ] `asr_reduction_pp` is percentage points; `utility_retention` is emitted with **both** raw numbers.
- [ ] Arms P1, P2 and P3 run by default; **P3 is a `phase == "request"` corpus filter**, and the run **fails** if `P3.corpus_digest == P1.corpus_digest`. No code anywhere reads `D2_ENABLED`/`D3_ENABLED`.
- [ ] `RunAccountant` **shares** `_estimate_cost`'s rate table (`eval_ml_classifier.py:147`), is token-based, keys on `(episode_id, arm)`, and is exactly-once on `(case_id, arm)` with an **under-count-only** residual.
- [ ] `noise_floor` is computed over **≥2 replicate pairs** with a recorded `method`, defined as the **max absolute pairwise difference**, and applied to the **aggregate** line only.
- [ ] `episodes_quarantined`, `synthetic_content_skipped`, `by_deciding_source_first_deny` **and** `by_deciding_source_all_denies` are all populated; trust dominance produces a **worded** finding.
- [ ] **unit tests pass** — covering: the three guard branches incl. mixed delegation and original ordering; synthetic tagging + skip + count; guard never raising; the security→ASR sign, pp arithmetic, retention raw numbers, `force_rerun`, dated model id; P3 corpus filter + **digest divergence failure** + no-D2/D3-flag scan + default arm set; accounting rate-table sharing, token basis, attribution key, resume non-double-count, with-arm premium; noise-floor n=1 refusal, max-pairwise definition, √2 method, manifest recording; first-deny denominator, both tables, trust-dominance wording, rollups.
- [ ] **integration tests pass** — `test_guarded_pipeline_shape.py` (the AgentDojo ABC seam), `test_paired_arms_stub_llm.py` (owned contract: `run_arm`/`score_run`/`results.mode_b`, zero spend), `test_noise_floor_end_to_end.py` (owned contract: `noise_floor` → `diff.py`'s `within-noise`), `test_attribution_rollup.py` (the `cases.jsonl` → `results.mode_b` rollup across three workstreams).
- [ ] *(human, G1/G6 — M2 exit)* One `manifest.json` carries ASR-with/without, utility for both arms, the by-`deciding_source` first-deny breakdown, `episodes_quarantined`, and `noise_floor` over ≥2 replicate pairs — **from a real, paid run**.
- [ ] *(human, OP-1)* The LLM budget is owned and the first-run spend is reconciled against the provider dashboard (`accounting.cost_usd` vs the invoice); **a persistent gap is a bug**, not rounding.

---

## Cross-references

- **This WS's LLD sections**: §4.4 (guard insertion, self-contamination, the partial-denial branches), §4.4b (the arm table, P3-is-a-corpus-filter, P4 sham guard), §5.2 (`run_arm`/`score_run` mapping, provider), §7.1.1 (unpinnable sampling, the noise-floor definition), §9 (scale + latency), §13 (cost + the biased cost controls), §14 (run accounting, why billing is N/A).
- **Sibling WS docs sharing a contract**: [ws-a](ws-a-harness-core.md) (`BenchmarkAdapter`, `RunContext`, `cases.jsonl`, `report.py`/`diff.py` consume `noise_floor` + the rollups) · [ws-b](ws-b-execution-isolation.md) (`enforce()`; **the Anthropic path is not the AWS path**, so sentinelization does not interfere) · [ws-c](ws-c-mode-a-replay.md) (same adapter package; P2's clean suite is already extracted for the Mode A negatives) · [ws-d](ws-d-engine-seams.md) (**`GuardClient` is the only way this WS talks to the engine**) · [ws-f](ws-f-asb-adapter.md) (**reuses this rig unchanged — that reuse is the G4 proof**).
- **Upstream benchmark**: AgentDojo @ `089ed468cf3ed0322acc66b0211f26d9d90dbf60`, `0.1.35`, MIT (LICENSE read from source 2026-07-27).
- **Open**: **OP-1** (LLM budget — blocks this entire WS) · **OP-2** (non-prod deployment — blocks hosted latency runs only; the fallback is in-process, which loses the latency number **and nothing else**, and is **never** a reason to point at prod).
