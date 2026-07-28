# 99 — Benchmark Harness: First-Run Runbook, Gates & Rollback

**Parent LLD**: [lld/41-benchmark-harness.md](../../lld/41-benchmark-harness.md) §17 (sequencing + prerequisites), §4.7 (isolation), §7.1.1 (noise floor), §10 (resiliency)
**Index**: [00-index.md](00-index.md)
**Last Updated**: 2026-07-27
**Status**: not started — no workstream has left `SCOPE`

> **What "go live" means here.** This rig ships **nothing to a customer**. There is no traffic flip, no shadow→enforce ladder, no deployment. "Go live" means: *the first run produces a number we are willing to act on.* The gates below exist to stop us acting on a number that is contaminated, unpinned, or produced by a detector that never fired.
>
> **External publication is DEFERRED and is a SEPARATE DECISION** (sub-PRD, 2026-07-27). Nothing in this runbook authorizes publishing a number outside the company. The manifest captures what a future publication would need, so deferring costs nothing later.

---

## 0. Prerequisites — verify ALL of these before step 1

| # | Prerequisite | How to verify | If unmet |
|---|---|---|---|
| **P1** | **Python ≥ 3.10, via `uv`.** The **system interpreter is 3.9.6 and TOO OLD** — AgentDojo declares `requires-python >= 3.10` and the codebase uses `X \| Y` unions. | `uv --version` (expect ≥ 0.11.32, present). Verified-working interpreters: `src/security-controller/venv` (**3.12.13**, has `cedarpy`), `agentdojo/.venv` (**3.12.2**, built from its `uv.lock`), repo-root `venv/` (docs tooling). | `uv python install 3.12` and create the benchmark venv from it. **Do not run against `/usr/bin/python3`.** |
| **P2** | **AgentDojo checkout pinned and clean.** `/Users/ruchikkachaudhary/closed-source/agentdojo` @ `089ed468cf3ed0322acc66b0211f26d9d90dbf60`, `0.1.35`, MIT. | `git -C /Users/ruchikkachaudhary/closed-source/agentdojo rev-parse HEAD` and `git status --porcelain` (**must be empty**). Installed **editable** from the checkout. | A dirty checkout **aborts the run** (tie-breaker E). `--allow-dirty` is exploration only and stamps the artifact permanently. |
| **P3** | **Sentra repo clean.** | `git status --porcelain` empty. | Same as P2. |
| **P4** | **`AEGION_BENCHMARK=1`** exported in the shell. | `echo $AEGION_BENCHMARK` | Every entry point exits **2**. That is working as designed. |
| **P5** | **NO live AWS credentials resolvable.** I3 asserts this **before** I2 mutates anything, so a live `sentra` profile is caught. | `unset AWS_PROFILE AWS_SESSION_TOKEN` and confirm `python -c "import botocore.session as s; print(s.Session().get_credentials())"` prints `None`. | `enforce()` exits **2** with "live AWS credentials present". **Do not work around it.** |
| **P6** | **Sigma ruleset fixture pinned** and non-empty; **ML classifier fake client** pinned. | The preflight banner prints `detector_readiness` with `sigma_rule_count > 0` and an `ml_leg.artifact` id. | **Zero rules or no model id ABORTS the run** — an unpinned artifact is an unpinned variable. |
| **P7** | **Mode B only — `ANTHROPIC_API_KEY`** for AgentDojo (direct Anthropic API, **not Bedrock** — `agent_pipeline.py:75`). | `[ -n "$ANTHROPIC_API_KEY" ]`. **Never recorded in any artifact** (SEC-2). | Mode B cannot run. **Mode A is unaffected** and still closes G2. |
| **P8** | **Mode B, ASB only — `OPENAI_API_KEY`** for ASB's default `gpt-4o-mini`. | `[ -n "$OPENAI_API_KEY" ]`. Never recorded. | M4's Mode B cannot run; M4's Mode A can. |
| **P9** | **⚠️ LLM budget OWNER named (OP-1 — currently UNOWNED).** ~$40–160 per full AgentDojo P1 run; ~$100–400 with P2+P3; the **with-arm is systematically dearer** (denials trigger retries to `max_iters=15`), so paired arms cost **more than 2×**. ASB adds an OpenAI line item on top. | A named person has accepted the spend, in writing, before the first paid run. | **M2/M3/M4 do not start.** M1 (Mode A) proceeds regardless and is free. |
| **P10** | **⚠️ Non-prod engine deployment (OP-2 — currently UNOWNED).** Needed **only** for hosted Mode B latency runs, plus SEC-1's **two** credentials (a data-plane agent credential for `POST /v1/validate` **and** a separate non-prod **operator** credential for the `/trail` join, because ADR-038 made `/trail` an operator-lane read). | A non-prod base URL exists and is **not** in `PROD_HOSTS`; account ≠ `531109575379`. | **Fallback is in-process only**, which loses the **latency number and nothing else**. **NEVER a workaround-by-using-prod** — FR-14.9 bars it and I5 enforces it. Without the operator credential, runs proceed with `attribution: "degraded"` rather than being granted a broader one. |
| **P11** | **`_benchmark` in `RESERVED_TENANT_IDS`** (`app/utils/tenancy.py:67`) — the **one and only** `app/` source edit — **and its LLD 26 §3.7 sync (OP-4)**. | `python -c "from app.utils.tenancy import is_reserved_tenant; print(is_reserved_tenant('_benchmark'))"` → `True`; [lld/26](../../lld/26-multi-tenancy.md) §3.7 lists `_benchmark`. | Merge is blocked on the sibling-doc edit; the frozenset is owned by LLD 26, not by this build. |

---

## 1. Ordered first-run steps

### Step 1 — prove the refusals BEFORE anything else runs (the one gating rule)

```bash
export AEGION_BENCHMARK=1
cd /Users/ruchikkachaudhary/closed-source/Sentra
uv run pytest benchmarks/tests/test_isolation.py -v
```

**All three subprocess cases must exit `2`:** unbadged · **live-credential** · prod base-url.

> **The live-credential case is the canary.** It is passable **only** because I3 snapshots `botocore.Session().get_credentials()` **before** I2 writes the sentinel. If someone "simplified" `enforce()` to sentinelize first, botocore's `EnvProvider` resolves the sentinel and the check passes unconditionally — the test becomes **unpassable** and M1 cannot exit. **If this test is failing, fix `enforce()`'s ordering; do not relax the test.**

Then:

```bash
uv run pytest benchmarks/tests/integration/test_no_aws_egress.py -v
```

Zero attempted AWS connections across all seven enumerated stores. **Do not proceed past this step on a red result.** This is the guarantee that stops a benchmark run publishing synthetic attack metrics into the production account — an **observed live path today**.

### Step 2 — Mode A, dry, on one suite (M1) — free, hermetic, ~2 minutes

```bash
uv run python -m benchmarks.run --adapter agentdojo --mode A --suite banking
```

**Read the preflight banner before walking away.** It prints, *before the first case*:
- `detector_readiness` per detector **and per leg** for composites,
- corpus size against **both** §5.1 floors (n≥30 to run; n≥300 to gate at a 1% budget),
- projected wall clock and cost.

**Stop and fix if the banner shows:**
- any `inert` detector → it never fired; a score from it would be fiction, and `fp_budget_gate` would pass it **by construction** (`FP=0 ⇒ fp_rate=0.0 ⇒ passes any budget`);
- any `partial` detector → **name the dead leg**. The most likely culprit is D2's **ML leg**: `MLClassifier.__init__` builds `boto3.client("bedrock-runtime")` directly (`ml_classifier.py:83`), so under I2 every call fails, is **swallowed at `:231`**, and returns `abstain` — **byte-identical to `ML_CLASSIFIER_ENABLED=false`**. Sigma + heuristics keep firing, so a per-detector check sees nothing wrong;
- `n_benign < 30` → the run refuses; `30 ≤ n < 300` → it runs but the **gate verdict is suppressed** and `fp_rate` carries a `resolution: 1/n` annotation.

**M1 exit gate:** a real **D2 and D3** recall number from an **armed, artifact-loaded** run (`detector_readiness.verdict == "scored"`), plus `test_isolation.py` and `test_extensibility.py` green. This closes **G2** — a number now exists where [ADR-036](../../adr.md) records "unmeasured".

### Step 3 — the engine seams, offline (M2 first half) — still free

```bash
uv run pytest benchmarks/tests/test_session_store_parity.py -v
uv run pytest benchmarks/tests/integration/test_in_process_validate_seam.py -v
```

The parity test drives the **same DENY/ALLOW sequence** through `BenchmarkSessionStore` and a **`moto`-mocked `SessionManager`** and asserts identical trust trajectories and quarantine transitions. **When it fails, the store is wrong — not the test.** M2 cannot exit without it green.

### Step 4 — Mode B smoke, stubbed LLM (M2) — zero spend

```bash
uv run pytest benchmarks/tests/integration/test_paired_arms_stub_llm.py -v
```

Proves the guards insert, the arms pair, `cases.jsonl` fills, and P3's `corpus_digest` **differs** from P1's — **before** spending a dollar.

### Step 5 — **the M2 noise-floor replicate. DO THIS BEFORE QUOTING ANY HEADLINE NUMBER.**

```bash
# Preferred: replicate BOTH arms, take the spread of the reduction directly.
uv run python -m benchmarks.run --adapter agentdojo --mode B --suite banking --arms P1 --replicates 3
```

- **Minimum 2 replicate pairs; 3 preferred.**
- `noise_floor_pp` ≡ **the maximum absolute pairwise difference across replicates**. *"The observed spread"* is not a definition and is not used.
- If budget forces the cheaper path (`method: "single_arm_x_sqrt2"`), **inflate the observed single-arm spread by √2** and record the independence assumption in the manifest — `asr_reduction_pp` is a **difference of two independently-sampled quantities**, so it varies by ≈√2·σ. A floor built from single-arm replicates alone leaves ~30% of the true resolution limit **below** the floor, where it gets labelled `regressed`.

> **⚠️ HARD RULE: no `asr_reduction_pp` is quoted — in a doc, a deck, a Slack message or a PR — without `noise_floor_pp` beside it.** Model sampling is **UNPINNABLE**: there is **no `seed` parameter** on the Anthropic Messages API; `temperature: 0` never guaranteed identical outputs; and `temperature`/`top_p`/`top_k` are **removed on Claude Opus 5, Fable 5, Opus 4.8 and Opus 4.7 (400 on send)**, with Claude Sonnet 5 rejecting non-default values. Reporting `32.0` to a tenth of a point without the floor is a precision claim the rig cannot support, and it turns `diff.py` into a machine that reports resampling noise as a product regression.

### Step 6 — the first paid Mode B run (M2) — **requires P9**

```bash
uv run python -m benchmarks.run --adapter agentdojo --mode B --suite banking --arms P1,P2,P3
```

Watch the structured stdout (one JSON object per line): running ASR + utility per arm, running confusion counts, cumulative `cost_usd`. **A 4-hour run must be readable at a glance at minute 30, or it gets killed and restarted blind.**

**Read the result in this order, and read all of it:**
1. **P1** — the headline. ASR with/without, `asr_reduction_pp` **with the floor**.
2. **P3 — "as-deployed (request-phase only)"**. P3 is a **corpus filter to `phase == "request"`**, because **100% of production traffic is `phase=request`** (ADR-036) and D2/D3 decide zero production requests. **P3 is the number a customer would actually get today.** *(If P3 ever looks byte-identical to P1, the run fails on the digest-divergence assertion — an implementer who tried to build P3 by setting `D2_ENABLED`/`D3_ENABLED` would get exactly that, since **those flags do not exist**.)*
3. **P2 — "clean traffic — the false-positive tax"**. **P1's `utility_retention` is utility-under-attack and is systematically NOT this number.** Quoting P1's retention as "what it costs on normal traffic" is the single easiest way for this rig to mislead a buyer.
4. **`episodes_quarantined`** — an **absorbing state, not a defense**. Four DENYs at −15 from 100 lands on **exactly 40**, inside the 10–40 band where everything denies; with retries to `max_iters=15`, **four denials in one episode is the expected case, not the tail**. An ASR of 0.00 with a third of episodes quarantined is **a rig artifact, not efficacy** — it is the ADR-036 shape happening inside our own instrument.
5. **`by_deciding_source_first_deny`** — denominator **episodes**, numerator the **first** deny per episode. If `sentra.trust` dominates, **G2 is defeated for that run** and the report says so in words.

Then reconcile: `accounting.cost_usd` vs the provider dashboard. **A persistent gap is a bug**, not rounding.

### Step 7 — the regression loop (M3)

```bash
uv run python -m benchmarks.core.diff --baseline <run_id_N-1> --candidate <run_id_N>
```

Two consecutive runs must diff cleanly on `case_id` (**G5**), and the CI gate must block a deliberately-regressed PR (**G3**). `diff.py` **refuses** a baseline whose `manifest.exit != "complete"` and refuses to join across `schema_version`.

### Step 8 — ASB (M4)

```bash
git diff --stat <m3-merge-sha> HEAD -- benchmarks/core/ benchmarks/rigs/   # REQUIRED: empty
uv run pytest benchmarks/tests/test_extensibility.py -v                    # unchanged and green
uv run python -m benchmarks.run --adapter asb --mode A --suite OPI,MP,clean
```

**G4 is proven by the empty diff, not by the lint.** If the diff is non-empty, move the change into `benchmarks/adapters/asb/`; if it genuinely belongs in core, land it and **record the partial result honestly** ("one adapter plus N core lines"). **Never weaken `test_extensibility.py` to make the diff pass.**

---

## 2. Rollback

| Scope | Procedure | Cost |
|---|---|---|
| **A bad run** | `rm -rf benchmarks/runs/{run_id}/`. **The rig writes nothing else, anywhere** (RES-7, SEC-9). | Instant. **No product state to unwind.** |
| **A crashed multi-hour run** | Do **not** delete it. `--resume {run_id}` re-reads `cases.jsonl`, skips `(case_id, arm)` pairs already present, and continues **under the same `RunContext`**. | **RPO = one episode (~$0.05–0.15)**. RTO = the remaining wall clock — resume is a **filter**, not a recovery. |
| **The `_benchmark` tenant edit** | Revert the one-line `app/utils/tenancy.py` hunk **and** the LLD 26 §3.7 sync together. | The only `app/` revert in the build. |
| **A hosted run that reached the wrong target** | Should be impossible (I5). If it happened, the `_benchmark` partition-key prefix makes every leaked row **identifiable and deletable as a unit** — that is what the reserved tenant buys after the fact. **File it as an I5 defect**, not as an operational mistake. | — |
| **Transcripts** | 90-day local retention, git-ignored, **regenerable from the manifest**. Delete freely. | — |
| **`cases.jsonl`** | **DO NOT DELETE.** It is committed for a reason: it is the diff join source, the resume ledger **and** the accounting ledger, and it is **the one file that cannot be regenerated without re-spending the Mode B LLM budget**. Git is its backup **only because it is committed**. | Losing it breaks G5 and costs real money. |

---

## 3. Human sign-off gates

These are **not** machine-verifiable and stay unchecked until a person checks them. `code-loop` will not tick them.

- [ ] **G-1 — Isolation accepted.** A human has run `test_isolation.py` and read the three exit-2 messages, and has confirmed the live-credential case is genuinely reachable (i.e. I3 precedes I2). *Gate for: any execution at all.*
- [ ] **G-2 — LLM budget owned (OP-1).** A named person has accepted the ~$100–400/cycle spend in writing. *Gate for: M2, M3, M4.*
- [ ] **G-3 — Noise floor exists before any number is quoted.** ≥2 replicate pairs, a recorded `method`, and `noise_floor_pp` printed beside every `asr_reduction_pp`. *Gate for: quoting a headline anywhere.*
- [ ] **G-4 — Readiness reviewed.** No detector reported `inert` or `partial` in the run being cited; the Sigma ruleset and ML artifact ids are pinned and recorded. *Gate for: citing a Mode A number.*
- [ ] **G-5 — Mode A is never presented as efficacy.** Whoever writes the summary confirms the §2.3 interstitial sentence survived, and that no Mode A recall figure is being used as a defense-effectiveness claim. *Gate for: any writeup.*
- [ ] **G-6 — Quarantine artifact ruled out.** `episodes_quarantined` reviewed; a high count is treated as **a finding about the measurement**, not as a result. *Gate for: citing an ASR.*
- [ ] **G-7 — LLD 26 §3.7 synced (OP-4).** `_benchmark` listed in the frozenset's owning doc, signed off by that LLD's owner. *Gate for: merging the one `app/` edit.*
- [ ] **G-8 — ADRs logged (OP-5).** LLD 41 §18.1 (gate reconciliation) and §18.2 (attribution absent from both return surfaces) recorded — next free number is **ADR-040** (`adr.md` tops at ADR-039, `:1608`). *Gate for: closing M3.*
- [ ] **G-9 — FR-14.7 re-affirmed at M4.** ASB is the only clean MIT source of D3-shaped material; the M4 PR states **evaluation only** and makes no training determination. *Gate for: merging M4.*
- [ ] **G-10 — PUBLICATION IS A SEPARATE DECISION, DEFERRED.** Nothing in this runbook authorizes an external claim. If publication is ever taken up, sub-PRD OBQ-1's residual becomes live again: **AgentDojo and ASB are tuned-against development targets**, so a rising score may reflect fitting rather than robustness. *Gate for: anything leaving the company.*

---

## 4. Cost controls — and the bias each one introduces

**A cost control that quietly flatters the number is not a cost control.** In reach-for order:

1. **`--suite banking`** — ~1/4 the cost, the right inner loop. **But suite choice is a free lever**: suites differ in how much of their surface Cedar can bound, so an inner loop pinned to the most favourable suite drifts away from the full-suite headline. `--suite` and `attack` are recorded in the manifest, and the report prints **"single-suite inner loop — not comparable to a full-suite headline"** whenever the corpus is a subset. **The same caution applies to `--attack`**: `important_instructions` is AgentDojo's standard strong attack, which is why it is the default — but **selecting *among* attacks by result is the same lever wearing a different hat.**
2. **`--user-tasks` / `--injection-tasks`** subsets for targeted re-runs.
3. **A cheaper model for iteration** — **the model is a pinned variable; changing it invalidates the diff.** A cheap-model run is a **smoke test, not a data point**.
4. **Full-suite runs weekly, not per commit.** Mode A is the per-commit gate; Mode B runs on a cadence.

---

## 5. Cross-references

- **Sequencing + prerequisites**: [LLD 41](../../lld/41-benchmark-harness.md) §17. **Isolation**: §4.7. **Noise floor**: §7.1.1. **Resiliency/rollback**: §10. **Cost**: §13.
- **Workstream docs**: [ws-a](ws-a-harness-core.md) · [ws-b](ws-b-execution-isolation.md) · [ws-c](ws-c-mode-a-replay.md) · [ws-d](ws-d-engine-seams.md) · [ws-e](ws-e-mode-b-agentdojo.md) · [ws-f](ws-f-asb-adapter.md).
- **Open items OP-1 … OP-5**: [00-index.md](00-index.md) § *Known-open prerequisites and risks*.
