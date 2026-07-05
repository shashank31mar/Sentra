<!-- Generated 2026-07-05 by the wsl-detection-corpus-research workflow (26 agents, 22 datasets adversarially verified: fetch primary source → read actual LICENSE → separate training-vs-eval → judge threat-class fit). Research-integrity discipline per rules/common/research-evidence.md. Companion to lld/32 §8 (synthetic-corpus loop). -->

Confirmed: local corpus dir has agentdojo/BIPIA/InjecAgent. Report follows.

---

# WS-L Detection-Depth Corpus Assessment — D1 / D2 / D3
**Lead researcher synthesis · 22 datasets adversarially verified · 2026-07-05**

Every claim is labeled `[FACT]` (read from a primary source: license file, dataset card, API, or parsed data) or `[INFERENCE]` (concluded from the facts). Licenses were read from the **actual LICENSE file / card metadata**, not the GitHub/HF tag or the paper's claim. **Training is the gated act**; held-out eval is usually permitted where training is not. Absent license = all-rights-reserved.

---

## 1. Executive Summary

- **D2 (content/indirect injection) is well-covered and trainable.** `[FACT]` Two net-new **MIT / CC-BY** attack corpora clear training — **Meta CyberSecEval prompt_injection** (MIT, 275 labeled indirect cases + direct/multilingual split) and **NVIDIA Nemotron-RL-Agentic-Indirect** (CC-BY-4.0, 1,272 tool-output-poisoning positives, strongest fit). Both are **attack-only** — they complement the already-local InjecAgent/BIPIA/AgentDojo but do **not** solve D2's real gap.
- **D2's real gap is BENIGN NEGATIVES for FP-rate, not attack positives.** `[INFERENCE]` Every D2 attack set (local + new) is positives-only. FP-rate needs domain-matched benign *ingested content* (clean tool outputs / RAG passages). The best labeled-benign options — **SEP** (CC-BY-4.0, 9,160 rows w/ built-in clean negatives) and **NotInject** (MIT, 339 benign) — are **proxies** (user-prompt-shaped, not fetched-doc-shaped), so they measure a proxy FP-rate, not a real-ingested-content one.
- **D1 (multi-turn) is a license minefield: strong-fit sets are eval-only, and the one trainable option is a contradiction.** `[FACT]` The best-fit multi-turn corpora (MHJ, SafeMTData, XGuard-Train, CoSafe, SafeDialBench) are **CC-BY-NC / research-only / no-license** → **training-forbidden**. The single set with any training claim, **tom-gibbs**, has an **MIT tag contradicted by a README "research purposes only" clause** → treat eval-only until resolved. `[INFERENCE]` **D1's trainable corpus must be generated on the §8 offline loop**; the licensed sets are held-out recall benchmarks only.
- **D3 (memory-poisoning) is the sparsest class, and it splits into two: one trainable corpus exists, most are AVOID.** `[FACT]` Exactly **two** D3 sets are USE-grade: **memshield-bench** (CC-BY-SA-4.0, 1,178 labeled clean/poison, but carries an EHR/MIMIC DUA risk → eval-only until healthcare rows dropped) and **Agent Security Bench / ASB** (MIT, ships a prebuilt poisoned-memory ChromaDB + benign tools — the only clean trainable D3 artifact). The rest (AgentPoison, PoisonedRAG, MINJA, RSB, rag-memory-poisoning-benchmark) are **no-license, PHI-encumbered, paper-only, or toy generators** → AVOID as data, mine only as design patterns for a synthetic build.
- **The one hard truth:** `[INFERENCE]` **No detector can be trained from acquired corpora alone.** D2 has trainable positives but no real-ingested benign negatives; D1's trainable positives don't exist (licenses block them); D3 has one clean trainable set (ASB) plus one encumbered one (memshield). **A §8 synthetic-generation loop is mandatory for D1 (both classes) and for D3's benign-memory-write negatives** — the acquired corpora are held-out eval anchors and generator seeds, not the training set.

---

## 2. Per-Detector Assessment

Legend: **Train?** = does the license permit training a shipped commercial detector. **Fit** = threat-class match to the detector. **Verdict** = the verified per-dataset recommendation.

### D2 — Content / Indirect (Second-Order) Prompt Injection

Malicious instruction hidden in **ingested/retrieved content** (fetched doc, tool output, RAG passage) — not the user's own prompt. Needs attack + **benign** content (FP-rate needs negatives).

| Dataset | Link | License | Train? | Eval? | Fit | Benign? | Size | Verdict |
|---|---|---|---|---|---|---|---|---|
| **NVIDIA Nemotron-RL-Agentic-Indirect** | [1] | CC-BY-4.0 | ✅ yes | ✅ | **strong** | no | 1,272 attack | **USE** |
| **Meta CyberSecEval prompt_injection** | [2] | MIT | ✅ yes | ✅ | partial | no | 275 indirect (of 1,255) | **USE** |
| **SEP** (Executed-or-Processed) | [3] | CC-BY-4.0 (data) / MIT (code) | ✅ yes | ✅ | partial | **yes** | 9,160 | **USE** (as clean-negative pool) |
| **NotInject** (InjecGuard) | [4] | MIT | ✅ yes | ✅ | partial | **yes (only)** | 339 benign | **USE** (FP spot-probe) |
| **Greshake llm-security** | [5] | MIT | ✅ yes | ✅ | partial (seeds) | no | ~5–10 payloads | **USE** (generator seeds) |
| **deepset/prompt-injections** | [6] | Apache-2.0 / CC-BY-4.0 (conflict; both permissive) | ✅ yes | ✅ | **weak** (direct only) | **yes** | 662 | **EVAL-ONLY** (direct-contrast + negatives) |
| **WASP** (Meta FAIR) | [7] | CC-BY-**NC**-4.0 | ❌ no | unclear | partial | no | 22 configs × 4 templates | **EVAL-ONLY** (NC — legal grey even for eval) |
| **TensorTrust** | [8] | **absent** (all-rights-reserved) | ❌ no | unclear | **wrong** (direct hijack) | yes | ~126k raw | **AVOID** |

**D2 RECOMMENDATION:**
1. `[FACT]` **Acquire now, trainable: NVIDIA Nemotron (CC-BY) + Meta CyberSecEval (MIT).** Both are direct-download, ungated. Nemotron is the strongest-fit new positive (tool-output poisoning across 9 domains, `write-tool-call = attack-followed` signal); CyberSecEval adds a labeled **direct-vs-indirect** split + multilingual coverage. `[INFERENCE]` Together these deepen the local InjecAgent/BIPIA/AgentDojo positives — value is the labeled split and domain breadth, not raw volume (the local sets are the stronger *literal* indirect-injection corpora).
2. `[INFERENCE]` **The FP-rate problem is not solved by any of these.** All D2 attack sets (local + new) are positives-only. Use **SEP's clean channel** (`system_prompt_clean` / `prompt_clean`, 9,160 rows, CC-BY, trainable) as the large clean-negative pool, and **NotInject** (339, MIT) as a trigger-word over-defense spot-probe. **Caveat `[FACT]`:** both are *user-prompt-shaped* benign, not *fetched-doc / tool-output-shaped* — a clean score on them is a **proxy** for low ingested-content FP, not proof. `[REC]` The real benign-content negatives should come from **AgentDojo/BIPIA clean passages** (already local) plus **§8-generated clean tool outputs** in Sentra's own domains.
3. `[FACT]` **deepset** is trainable and licensed but **WEAK fit** — 25/25 sampled attack rows are *direct* injection, zero indirect. Use only as a direct-injection contrast set + labeled negatives; do **not** conflate with indirect signal.
4. `[FACT]` **WASP is NC → training-forbidden** for a commercial product, and eval-by-a-for-profit is legally grey under NC; **TensorTrust is wrong-threat-class (direct hijack) AND no-license** → AVOID.

---

### D1 — Multi-Turn / Conversation-Trajectory Attacks

Slow-build across turns (Crescendo / ActorAttack) where each single turn looks benign. Needs multi-turn transcripts with **per-conversation** attack/benign labels.

| Dataset | Link | License | Train? | Eval? | Fit | Benign? | Size | Verdict |
|---|---|---|---|---|---|---|---|---|
| **tom-gibbs multi-turn** | [9] | **CONFLICT**: MIT tag vs README "research-only" | ⚠️ unclear→no | ✅ | **strong** | **yes** (2,400 control) | ~6,900 rows | **INVESTIGATE** (eval-only until resolved) |
| **MHJ** (ScaleAI) | [10] | CC-BY-**NC**-4.0 | ❌ no | ✅ | **strong** | no | 537 convs / 2,912 prompts | **EVAL-ONLY** (gated) |
| **SafeMTData** (ActorAttack) | [11] | **CONFLICT**: MIT tag, no file, authors "research-only" | ❌ (unclear→no) | ✅ | **strong** | yes (refusal, not benign) | 2,280 | **EVAL-ONLY** |
| **HarmfulQA** (declare-lab) | [12] | Apache-2.0 (+ OpenAI-distill ToS) | ⚠️ unclear | ✅ | partial | **mis-sold** (see note) | 16,892 convs | **EVAL-ONLY** |
| **XGuard-Train** | [13] | **absent** (all-rights-reserved) | ❌ no | unclear | **strong** | no | ~30,695 convs | **AVOID** (license only blocker) |
| **CoSafe** | [14] | **absent** | ❌ no | ❌ no | **strong** | no | 1,400 | **AVOID** (contact authors) |
| **SafeDialBench** | [15] | **absent** | ❌ no | unclear | partial | no | ~4,000 | **AVOID** |

**D1 RECOMMENDATION:**
1. `[INFERENCE]` **There is no clean trainable multi-turn corpus.** The strongest-fit sets are all NC / research-only / no-license. **D1's training corpus must be §8-generated** on the offline loop from MIT-licensed single-turn seeds (AdvBench goals are MIT — `[FACT]` from prior memory, no GCG suffixes shipped), with an **explicit seed-dedup step** to avoid inflating held-out numbers via HarmBench-seed overlap (MHJ attacks HarmBench behaviors).
2. `[FACT]` **Held-out eval anchors (acquire, eval-only): MHJ (CC-BY-NC, gated auto-form) and SafeMTData (research-only).** Both are strong-fit Crescendo/ActorAttack transcripts. MHJ is >70% ASR, 537 convs — a spot-check recall slice, not comprehensive. Neither ships genuine benign negatives (SafeMTData's "benign" is *refusal* dialogues — a harder/narrower negative class, not innocuous traffic).
3. `[FACT]` **tom-gibbs is the one to escalate for legal review** — it is the *only* multi-turn set that (a) claims MIT and (b) ships **2,400 benign + semi-benign control conversations** (the rare FP-rate negatives D1 needs) plus a 382-row hand-labeled gold subset. But the README's "use solely for research purposes" clause contradicts the MIT tag. `[REC]` **Fail-secure: treat as eval-only until the authors clarify or grant written permission.** If they confirm MIT, this becomes the single best D1 acquisition.
4. `[FACT]` **XGuard-Train (30,695 convs — 20× the next-largest) is the biggest prize and is blocked ONLY by an absent license.** `[REC]` Worth a written eval-use request to the authors (marslabucla / Saadia Gabriel); re-check if they attach a license. **CoSafe** (strong coreference fit) and **SafeDialBench** are likewise no-license → contact-authors-or-AVOID.
5. `[FACT]` **HarmfulQA's "benign split" is mis-sold** — per the paper's Fig-4/§2.2.1, its "blue" (benign) and "red" (harmful) conversations share the **same adversarial escalating user turns**; they differ only in whether the assistant *complied*. So "blue" is *attack-was-asked-model-refused*, **not** genuine benign multi-turn traffic. Using it as D1 negatives teaches the detector to fire on refused-attacks — wrong negative distribution. Plus OpenAI-distilled → training ToS-encumbered. **EVAL-ONLY, and not for FP calibration.**

---

### D3 — Poisoned Memory (Memory-Write Integrity)

A memory-WRITE that poisons the long-term store (hidden directive, self-promotion of an untrusted source, provenance violation) — a **different threat class** from prompt injection. Needs poisoning write payloads + benign memory writes + per-write labels.

| Dataset | Link | License | Train? | Eval? | Fit | Benign? | Size | Verdict |
|---|---|---|---|---|---|---|---|---|
| **Agent Security Bench (ASB)** | [16] | MIT | ✅ yes | ✅ | **strong** | **yes** | prebuilt ChromaDB + jsonl; MP count unstated | **USE** (only clean trainable D3 set) |
| **memshield-bench** | [17] | CC-BY-SA-4.0 (data) | ✅ (license) | ✅ | **strong** | **yes** (856 clean / 322 poison) | 1,178 labeled | **EVAL-ONLY** (EHR/MIMIC DUA risk; too small to train alone) |
| **AgentPoison** | [18] | MIT (code); data NC/DUA-gated | ⚠️ unclear | ✅ | partial (trigger backdoor) | yes (baseline) | trigger *optimizer*, no fixed corpus | **INVESTIGATE** (StrategyQA slice only clean) |
| **PoisonedRAG** | [19] | MIT | ✅ yes | ✅ | partial (retrieval, not write) | yes (BEIR, mismatched) | ~hundreds ×5 | **EVAL-ONLY** |
| **MINJA** | [20] | **absent** + MIMIC/eICU PHI DUA | ❌ no | ❌ no | partial | no | template + ~9 seeds | **AVOID** (PHI risk) |
| **RSB** (arXiv 2505.18543) | [21] | **absent** (paper-only, no artifact) | ❌ no | ❌ no | **wrong** (RAG-corpus, not memory) | unknown | unreleased | **AVOID** (nothing to acquire) |
| **rag-memory-poisoning-benchmark** | [22] | **absent** | ❌ no | ❌ no | strong | yes | ~60 toy tasks | **AVOID** (toy generator; mine ideas only) |

**D3 RECOMMENDATION:**
1. `[FACT]` **ASB (MIT) is the anchor and the only clean trainable D3 artifact** — it ships a **prebuilt poisoned-memory ChromaDB store** (`memory_db/chroma_db/chroma.sqlite3`), a `MP.yml` (memory-poisoning, retrieval-based) config, a `clean.yml` benign config, and `all_normal_tools.jsonl` benign negatives. `[INFERENCE]` Caveats: clone the **agiresearch/ASB** canonical MIT repo (README points at a personal fork); the distinct poisoned-record count must be **measured after building** (part is runtime-assembled); ASR was low (1.85–25.65%) so treat labels as *attempt vs benign*; and verify its AIOS-plan-memory model maps to Sentra's real write seams (Anthropic memory-tool / Letta / LangGraph / mem0) before trusting recall numbers.
2. `[FACT]` **memshield-bench (CC-BY-SA) is the best labeled eval set** — 1,178 entries, 856 clean / 322 poison, 10 attack types, OWASP + MITRE-ATLAS tagged, with per-entry `label` / `attack_type` / `paired_id`. `[REC]` **EVAL-ONLY for now** because (a) the author's own card says 1,178 is "too small as sole training data," and (b) a **healthcare slice embeds de-identified EHR IDs from EHRAgent → MIMIC-III (PhysioNet DUA, no-redistribution)** which CC-BY-SA re-licensing does **not** cure. **Quarantine/drop the EHR rows**, honor ShareAlike + attribution, and it becomes trainable on the remaining (AgentPoison-Wikipedia/StrategyQA, MIT) slice.
3. `[INFERENCE]` **Everything else is AVOID as data.** AgentPoison is a trigger-*optimizer* needing GPU + a target embedder (StrategyQA is its one clean slice; Agent-Driver=nuScenes-NC, EHRAgent=MIMIC-DUA); PoisonedRAG is **retrieval-corpus** poisoning with *declarative factoid* payloads, not *imperative directive* memory-writes (wrong sub-class, EVAL-ONLY at best); **MINJA carries improperly-redistributed MIMIC/eICU PHI** (AVOID outright); **RSB has no released artifact and is wrong-class anyway**; **rag-memory-poisoning-benchmark is a self-described "toy" ~200-line generator** (0 stars, no license). `[REC]` Mine MINJA's *bridging-step + progressive-shortening* mechanism and rag-memory-poisoning-benchmark's *trust-weighting + contradiction-quarantine* metric design as **§8 generator inputs — re-implemented independently, no code/data copied.**

---

## 3. The Honest Gaps

**D3 is the sparsest class — and it forces a synthetic build.** `[INFERENCE]` Only **one** clean trainable D3 corpus exists (ASB, MIT), and it is a specific AIOS-plan-memory flavor whose recall may not transfer to Sentra's real write seams. memshield is small + EHR-encumbered. **No acquired corpus covers the full D3 threat surface** (hidden-directive writes + untrusted-source self-promotion + provenance violations across Anthropic-memory-tool / Letta / LangGraph / mem0). A **§8 synthetic build is mandatory for D3**, and it needs three things it cannot buy:
- **Attack templates** — mine ASB (k-v plan poisoning), MINJA (bridging + progressive-shortening indication prompt), memshield's 10 attack types (instruction-override / data-exfil / backdoor-trigger / experience / recommendation / config / C2 / persistence). These are *design patterns*, re-authored independently.
- **Benign memory-writes** — `[FACT]` **nothing acquired supplies real benign memory-write negatives** (ASB's `all_normal_tools`, memshield's 856 clean, and rag-mem's 3-clean-per-task are all synthetic/toy). Sentra must generate benign writes in its own domains (the payment/identity/telecom agents' real memory traffic) or the FP-rate is measured against the wrong distribution.
- **Per-write labels** — attach `label`, `attack_type`, `source_trust`, `provenance` per write at generation time (memshield's schema is the template to copy).

**D2's real gap is BENIGN NEGATIVES, not positives.** `[FACT]` Attack positives are abundant and now trainable (local InjecAgent/BIPIA/AgentDojo + new Nemotron/CyberSecEval). But **every one is positives-only**; the only labeled-benign options (SEP, NotInject, deepset) are **user-prompt-shaped**, not fetched-doc/tool-output-shaped. `[REC]` FP-rate must be measured on **clean ingested content** — AgentDojo/BIPIA clean passages + §8-generated clean tool outputs — with SEP/NotInject as a proxy floor only.

**The multi-turn license landscape (D1) — trainable vs eval-only:** `[FACT]`
- **Training-forbidden (NC / research-only / no-license):** MHJ (CC-BY-NC), SafeMTData (research-only), CoSafe (no-license), XGuard-Train (no-license), SafeDialBench (no-license), HarmfulQA (OpenAI-distill ToS).
- **Contested (could be trainable if authors confirm):** tom-gibbs (MIT tag vs research-only README) — **the only one worth a legal review**.
- **Net:** `[INFERENCE]` D1 has **zero** confirmed-trainable corpora today. Training data is §8-generated; the licensed sets are held-out recall anchors. **Benign multi-turn negatives are the second gap** — no acquired set gives genuine innocuous multi-turn traffic (tom-gibbs's 2,400 controls are the closest, but they're license-blocked; the "benign" splits in SafeMTData/HarmfulQA are refused-attacks, the wrong negative distribution). The LLD flagged **MT-Bench-101** (Apache-2.0 **UNVERIFIED**) as a benign-multi-turn candidate — `[REC]` verify its actual LICENSE before relying on it.

---

## 4. Licensing & Acquisition Plan

**Read the LICENSE, not the tag. Training is the gated act. Absent license = all-rights-reserved.**

### Tier 1 — Download now, TRAINABLE (clean license, direct/ungated)
| Dataset | Detector | License | Obligation |
|---|---|---|---|
| NVIDIA Nemotron-RL-Agentic-Indirect [1] | D2 | CC-BY-4.0 | Attribute NVIDIA in derived artifact; re-check README for a future governing-terms wrapper before training |
| Meta CyberSecEval prompt_injection [2] | D2 | MIT | Vendor `CybersecurityBenchmarks/LICENSE` (not top-level Llama license); curl to disk (payloads trip WebFetch filters) |
| SEP [3] | D2 (clean negatives) | CC-BY-4.0 (data) | Attribute + vendor a CC-BY notice; data lives in `SEP_dataset/`+`datasets/`, not `data/` |
| NotInject [4] | D2 (FP probe) | MIT | Vendor the GitHub `InjecGuard/LICENSE` alongside the HF parquet (no LICENSE file on HF) |
| Greshake llm-security [5] | D2 (seeds) | MIT | Hand-extract ~5–10 payloads from `scenarios/gpt4/*.py`; generator seeds only |
| Agent Security Bench (ASB) [16] | D3 | MIT | Clone **agiresearch/ASB** (not the fork); build the ChromaDB, then count MP records |

### Tier 2 — Download now, EVAL-ONLY (training forbidden or too small)
- **deepset/prompt-injections [6]** (D2) — permissive but weak/direct fit; resolve dual-license by picking CC-BY-4.0 + attributing.
- **MHJ [10]** (D1) — CC-BY-NC; **gated** auto-accept form (Name/Affiliation/Email/Country/Purpose). Held-out recall only.
- **SafeMTData [11]** (D1) — research-only intent; ungated download; eval only.
- **HarmfulQA [12]** (D1) — Apache tag but OpenAI-distill ToS; do **not** use its "benign" split for FP.
- **memshield-bench [17]** (D3) — CC-BY-SA; **quarantine the EHR/healthcare rows** (MIMIC DUA) before any use; honor ShareAlike. Trainable only after EHR rows dropped.
- **PoisonedRAG [19]** (D3) — MIT but retrieval-not-write class; store-integrity eval sub-signal only.
- **WASP [7]** (D2) — CC-BY-NC; even eval is legally grey for a for-profit — get counsel before any GA claim.

### Tier 3 — Legal review / author request required
- **tom-gibbs multi-turn [9]** (D1) — **highest-value legal ask**: MIT tag vs "research-only" README. Get written clarification; if MIT confirmed, it's the best D1 acquisition (2,400 benign controls + 382 gold labels).
- **XGuard-Train [13]** (D1) — no-license, 30,695 convs (20× largest). Request written eval-use grant from marslabucla / Saadia Gabriel; re-check for an attached license.
- **CoSafe [14]** (D1) — no-license, strong coreference fit. Contact Erxin Yu (PolyU) for eval grant.
- **AgentPoison [18]** (D3) — MIT code; only the StrategyQA slice is cleanly usable (Agent-Driver=nuScenes-NC, EHRAgent=MIMIC-DUA). Trigger-optimizer, not a corpus — needs GPU build.

### Tier 4 — AVOID (do not ingest)
- **TensorTrust [8]** (D2) — no data license **and** wrong threat class (direct hijack).
- **SafeDialBench [15]** (D1) — no-license, label-less, model-safety not detector data.
- **MINJA [20]** (D3) — no-license **and** redistributes MIMIC/eICU PHI under a no-redistribution DUA. Cite the mechanism only; never ingest the repo.
- **RSB [21]** (D3) — no released artifact + wrong class (RAG-corpus not memory-write). Re-check post-publication for D2 only.
- **rag-memory-poisoning-benchmark [22]** (D3) — no-license self-described "toy" generator. Re-implement the trust-weight/contradiction-quarantine ideas independently.

### Cross-cutting build actions `[REC]`
1. **Build the §8 synthetic loop first** — it is the training source for D1 (both classes), D3 benign-memory-writes, and D2 clean-tool-output negatives. Acquired corpora are held-out eval anchors + generator seeds.
2. **Seed-dedup gate** — dedupe §8-generated D1 training data against MHJ/HarmBench seeds so held-out recall isn't inflated.
3. **PHI quarantine gate** — a hard exclusion filter for any EHR/MIMIC-derived rows (memshield healthcare slice; never MINJA/AgentPoison-EHRAgent).
4. **Attribution/ShareAlike ledger** — CC-BY (Nemotron, SEP, deepset) needs attribution; CC-BY-SA (memshield) needs attribution **+ ShareAlike** on any derived corpus/artifact that embeds it.

---

## 5. Sources

Every URL below was read directly in the verification pass (license file, dataset card, HF/GitHub API, or parsed data), per the input assessments.

1. NVIDIA Nemotron-RL-Agentic-Indirect-Prompt-Injection-v1 — https://huggingface.co/datasets/nvidia/Nemotron-RL-Agentic-Indirect-Prompt-Injection-v1
2. Meta CyberSecEval prompt_injection (PurpleLlama) — https://github.com/meta-llama/PurpleLlama/tree/main/CybersecurityBenchmarks/datasets/prompt_injection
3. SEP (Should-It-Be-Executed-Or-Processed) — https://github.com/egozverev/Should-It-Be-Executed-Or-Processed
4. NotInject (InjecGuard/PIGuard) — https://huggingface.co/datasets/leolee99/NotInject · repo https://github.com/SaFoLab-WISC/InjecGuard
5. Greshake et al. llm-security — https://github.com/greshake/llm-security (paper arXiv:2302.12173)
6. deepset/prompt-injections — https://huggingface.co/datasets/deepset/prompt-injections
7. WASP (Meta FAIR) — https://github.com/facebookresearch/wasp (paper arXiv:2504.18575)
8. TensorTrust (tensor-trust-data) — https://github.com/HumanCompatibleAI/tensor-trust-data · mirror https://huggingface.co/datasets/qxcv/tensor-trust (paper arXiv:2311.01011)
9. tom-gibbs multi-turn jailbreak datasets — https://huggingface.co/datasets/tom-gibbs/multi-turn_jailbreak_attack_datasets (paper arXiv:2409.00137)
10. MHJ (ScaleAI/mhj) — https://huggingface.co/datasets/ScaleAI/mhj (paper arXiv:2408.15221)
11. SafeMTData (ActorAttack) — https://huggingface.co/datasets/SafeMTData/SafeMTData · repo https://github.com/AI45Lab/ActorAttack (paper arXiv:2410.10700)
12. HarmfulQA (declare-lab) — https://huggingface.co/datasets/declare-lab/HarmfulQA (paper arXiv:2308.09662)
13. XGuard-Train (X-Teaming) — https://huggingface.co/datasets/marslabucla/XGuard-Train · repo https://github.com/salman-lui/x-teaming (paper arXiv:2504.13203)
14. CoSafe-Dataset — https://github.com/ErxinYu/CoSafe-Dataset (paper https://aclanthology.org/2024.emnlp-main.968/)
15. SafeDialBench — https://github.com/drivetosouth/SafeDialBench-Dataset (paper arXiv:2502.11090)
16. Agent Security Bench (ASB) — https://github.com/agiresearch/ASB (paper arXiv:2410.02644)
17. memshield-bench — https://huggingface.co/datasets/npow/memshield-bench · code https://github.com/npow/memshield (paper arXiv:2512.16962)
18. AgentPoison — https://github.com/AI-secure/AgentPoison (NeurIPS 2024)
19. PoisonedRAG — https://github.com/sleeepeer/PoisonedRAG (USENIX Security 2025)
20. MINJA (Memory INJection Attack) — https://github.com/dsh3n77/MINJA (paper arXiv:2503.03704)
21. RAG Security Bench (RSB) — https://arxiv.org/abs/2505.18543 (paper-only; no artifact released as of 2026-07-05)
22. rag-memory-poisoning-benchmark — https://github.com/zhou-zhichao/rag-memory-poisoning-benchmark

**Provenance-integrity note `[FACT]`:** ALREADY-LOCAL and license-verified at `/Users/shshgup/code/security-mvp/Sentra/harness/ws0/corpus_src/` — **AgentDojo, BIPIA, InjecAgent** (confirmed on disk). WS-L LLD of record: `/Users/shshgup/code/security-mvp/Sentra/lld/32-detection-depth.md` (its §8 is the synthetic-corpus generation loop this plan feeds).