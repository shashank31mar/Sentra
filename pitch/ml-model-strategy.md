# AegionAI — ML Detection Layer Strategy

**Internal technical document | March 2026**

---

## The Problem With Regex (and Why Investors Notice)

The current detection layer matches tool calls and prompts against known bad patterns — SQL injection strings, PII keywords, known jailbreak phrases. This works for known attacks. It fails for semantic variations ("drop the thing that holds user data"), paraphrased injection chains, multi-turn attacks where no single message looks malicious, and novel zero-day adversarial inputs. Any investor with a security infrastructure background will identify this in a 10-minute demo. Replacing regex with a two-layer ML architecture is the single highest-leverage technical improvement before the raise.

Critically: **no customer data is required.** This is the right design — both for compliance and for investor credibility.

---

## Architecture: Two Independent Detection Layers

```
Incoming agent tool call / prompt
         │
         ▼
┌─────────────────────────────────────┐
│  LAYER 1: Content Classifier         │
│  Fine-tuned transformer model        │
│  Trained on public adversarial data  │
│  Detects: injection, jailbreak, PII  │
│  Output: BLOCK / ALLOW + confidence  │
└──────────────┬──────────────────────┘
               │ (if ALLOW)
               ▼
┌─────────────────────────────────────┐
│  LAYER 2: Behavioral Anomaly         │
│  Unsupervised model on metadata only │
│  No content inspection               │
│  Detects: novel attack patterns,     │
│  sequence anomalies, unusual timing  │
│  Output: ANOMALY SCORE + alert       │
└──────────────┬──────────────────────┘
               │
               ▼
         ENFORCE POLICY
         (OPA Rego / sequence validation)
```

A call must pass both layers before reaching the downstream system. Attackers who craft prompts that evade the content classifier are still caught by behavioral anomaly detection — and vice versa.

---

## Layer 1: Content Classifier

**What it detects:** Prompt injection, jailbreaks, PII exfiltration attempts, harmful content, known adversarial patterns.

**Training data — all public, no customer data required:**

| Dataset | Contents | Size | Why It Matters |
|---|---|---|---|
| **HackAPrompt** | Prompt injection competition entries, 7 injection techniques | 600K+ samples | Largest public injection dataset; covers direct, indirect, multi-turn attacks |
| **JailbreakBench** | Curated jailbreaks across 10 harm categories | 100 high-quality behaviors | Standardized benchmark; ensures coverage of known jailbreak families |
| **HarmBench** | Adversarial prompts, 510 harmful behaviors across 7 categories | ~3K samples | Evaluates robustness against diverse attack types |
| **PromptBench** | Adversarial perturbations across 8 attack types (BERT-Attack, TextFooler, etc.) | 4,788 samples | Tests robustness to semantic-preserving adversarial edits |
| **WildGuard** | Safety classifier training data — Anthropic / Allen AI | 92K labeled samples | Covers refusal, harmful intent, and safe response classification |
| **OpenAI moderation fine-tune dataset** | Publicly released moderation training samples | ~3K samples | Covers harassment, violence, self-harm, sexual content categories |

**For PII specifically:** Use **Microsoft Presidio** (open-source, production-grade) as the PII detection component rather than building from scratch. It covers 50+ PII entity types across 30+ languages. No training needed — drop in as a pre-processor.

**Model architecture:** Fine-tune **DeBERTa-v3-base** (or DistilBERT for lower latency). These models are small enough to run with <10ms inference on CPU, which keeps AegionAI's total latency under the 80ms threshold. The classification head outputs a probability for each threat class: injection, jailbreak, PII, harmful content.

**Expected performance improvement over regex:**
- Regex catches exact pattern matches. The trained classifier catches semantic variations, paraphrased attacks, and multi-step injections where no single turn is obviously malicious.
- The HackAPrompt competition showed that even simple fine-tuned classifiers significantly outperform keyword matching on adversarial inputs.
- Estimated: 94% → 98%+ precision on the public benchmark, with meaningful reduction in false positives that currently generate alert fatigue.

**Training cost and time:** 2–3 weeks of ML engineering, roughly $500–$800 in GPU compute on Lambda Labs or AWS SageMaker spot instances. This is a solved engineering problem, not research.

---

## Layer 2: Behavioral Anomaly Detection

**What it detects:** Novel attacks not in any training set, tool call sequences that deviate from a deployment's established baseline, timing anomalies (e.g., agent calling 50 tools in 2 seconds), unusual cross-agent communication patterns, privilege escalation attempts through chained tool calls.

**Why this layer is architecturally distinct:**
- Layer 1 inspects content. Layer 2 inspects behavior.
- Layer 2 operates only on tool call **metadata**: tool name, timestamp, sequence position, call frequency, parameter structure (not parameter values), calling agent identity, target system.
- No content ever leaves the cluster. No PII is processed. No compliance implications.

**How it works:**

Each deployment automatically builds a behavioral baseline during the first 7 days of operation. The model learns what "normal" looks like for that specific agent fleet:
- Normal tool call sequences for this agent type
- Normal call rates and timing distributions
- Normal cross-agent communication patterns
- Normal parameter structure distributions (field names, data types — not values)

After baseline establishment, incoming tool calls are scored against the baseline using an **Isolation Forest** model (or autoencoder for higher-dimensional metadata). Calls that deviate significantly from the baseline receive a high anomaly score and trigger an alert or block depending on policy configuration.

**Why unsupervised learning is the right choice here:**
- You don't know what the next attack looks like by definition. Supervised models trained on known attacks will miss novel zero-days.
- Unsupervised anomaly detection finds anything unusual — including attacks that have never been seen before.
- Each deployment's model is customer-specific without sharing data between customers: Razorpay's baseline looks nothing like Abridge's baseline.

**No shared data between deployments.** Each customer's behavioral model runs inside their own Kubernetes cluster. AegionAI's control plane never receives the raw baseline data. This is a feature, not a limitation — it means regulated customers (healthcare, finance) can deploy without compliance concerns.

---

## What This Enables in the Pitch

With both layers deployed, the investor narrative becomes:

> "Layer 1 is a fine-tuned transformer trained on the four largest public adversarial LLM datasets — it catches known injection and jailbreak techniques that regex will never catch. Layer 2 is an unsupervised anomaly detection model running on tool call metadata inside each customer's own cluster — it catches novel attacks by detecting behavioral deviation from that deployment's baseline, with zero content inspection and zero compliance exposure. The two layers are complementary: an attacker who evades one gets caught by the other."

This is a fundamentally different story than "we detect attacks" — it's a layered, architecturally sound detection system with clear reasoning for each design choice. It directly addresses the investor concern about regex being table stakes.

---

## Build Timeline

| Milestone | Timeline | Who | Cost |
|---|---|---|---|
| Compile and preprocess training datasets (HackAPrompt, JailbreakBench, HarmBench, WildGuard) | Week 1 | ML Engineer | $0 (all public) |
| Fine-tune DeBERTa-v3-base content classifier, evaluate on held-out benchmark | Week 2–3 | ML Engineer | ~$400 GPU compute |
| Integrate Presidio for PII, test combined pipeline at <80ms latency | Week 3 | ML Engineer + Backend | $0 |
| Build behavioral metadata pipeline (tool call event stream → feature extraction) | Week 2–3 (parallel) | Backend Engineer | $0 |
| Implement Isolation Forest baseline model, per-deployment training loop | Week 3–4 | ML Engineer | $0 |
| Integration testing: both layers in K8s sidecar, full pipeline end-to-end | Week 4–5 | ML + Backend | — |
| **Both layers live in demo environment** | **Week 5** | | **~$800 total** |

This is entirely parallelizable with Azure connector work. **No customer data required at any stage.**

---

## Long-Term: Federated Improvement (Post-Seed)

After gaining 10+ deployments, introduce an optional federated learning loop:
- Each deployment's Layer 2 anomaly model shares only **gradient updates** (not data) with a global meta-model
- The global model learns cross-deployment attack patterns without any customer data leaving their cluster
- Customers who opt into federation get a model that improves from collective intelligence; those who don't continue with their local baseline

This is a standard federated learning architecture (same pattern as Google Keyboard's next-word prediction). It becomes the long-term defensible moat: the more deployments AegionAI has, the better every deployment's anomaly detection gets. No competitor without deployment scale can replicate this.

---

*AegionAI — The AI Security Control Plane*
