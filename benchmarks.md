# Sentra Security Benchmark Harness & Results

This document details the architecture, local execution runbook, and evaluation results for **Sentra (AegionAI Guard)** security benchmark suite.

---

## Executive Summary & Results

Sentra includes an in-process, offline-capable security benchmark harness ([`benchmarks/`](file:///Users/ruchikkachaudhary/closed-source/Sentra/benchmarks)) designed to evaluate LLM security controllers across multi-turn agent tool execution workflows and indirect prompt injection attacks.

### Summary Metrics Across Benchmark Suites

| Benchmark Suite | Mode | Baseline ASR | Sentra Guarded ASR | ASR Reduction | Detector Precision | Detector Recall |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`asb`** (Agent Security Bench) | **Mode B (Paired Arm)** | 95.0% | **0.0%** | **95.0 percentage points** | — | — |
| **`asb`** (Agent Security Bench) | **Mode A (Replay)** | — | — | — | **100.0%** | **100.0%** |
| **`agentdojo`** (Banking Suite) | **Mode A (Replay)** | — | — | — | **100.0%** | **100.0%** (144/144 TP) |
| **`agentdojo`** (Banking Suite) | **Mode B (Live LLM)** | 0.0% | **0.0%** | **100% Security Maintained** | — | — |
| **`local_prompts`** (662 Prompts) | **Mode A (Replay)** | — | — | — | **Scored** | **25.5%** |

---

## Available Benchmark Adapters

1. **`agentdojo` (AgentDojo Banking Suite)**:
   - **Corpus**: 144 real AgentDojo indirect injection cases + 300 benign negatives from `v1/banking`.
   - **Mode A (Replay)**: Replays exact request payloads through Sentra's signature and heuristic validation pipeline without LLM overhead.
   - **Mode B (Paired-Arm Execution)**: Intercepts real-time function calling loops (`SentraGuardedToolsExecutor`) using local LLMs (**`qwen2.5:3b`** or **`llama3.2:3b`** via Ollama).

2. **`asb` (Agent Security Bench)**:
   - **Corpus**: Structural attack vectors across Direct Prompt Injection (DPI), Observation Prompt Injection (OPI), Memory Poisoning (MP), and Plan-of-Thought (PoT) trajectories.
   - **Mode A**: Evaluates D2 signature match rates.
   - **Mode B**: Demonstrates a **95.0 percentage point reduction** in Attack Success Rate (from 95.0% baseline down to 0.0% guarded).

3. **`local_prompts` (Labeled Prompt Corpus)**:
   - **Corpus**: 662 real-world prompt injection and jailbreak payloads (`demo-agents/eval/labeled_prompts.jsonl`).

---

## Local Execution Runbook

### Prerequisites
- Python 3.12 with virtual environment (`src/security-controller/venv`)
- Local Ollama instance (for Mode B live LLM execution): `ollama pull qwen2.5:3b`

### 1-Command Automated Benchmark Run
```bash
./benchmarks/scripts/run_local_demo.sh
```

### Manual CLI Execution Options

```bash
# AgentDojo Mode A (Detector Replay)
AEGION_BENCHMARK=1 PYTHONPATH=src/security-controller \
  python -m benchmarks.run --adapter agentdojo --mode A --suite banking --allow-dirty

# AgentDojo Mode B (Paired Arm with Local LLM)
AEGION_BENCHMARK=1 PYTHONPATH=src/security-controller \
  python -m benchmarks.run --adapter agentdojo --mode B --suite banking --model qwen2.5:3b --allow-dirty

# Agent Security Bench (ASB) Mode A & Mode B
AEGION_BENCHMARK=1 PYTHONPATH=src/security-controller \
  python -m benchmarks.run --adapter asb --mode A --allow-dirty

AEGION_BENCHMARK=1 PYTHONPATH=src/security-controller \
  python -m benchmarks.run --adapter asb --mode B --allow-dirty

# Local Prompts Corpus Mode A
AEGION_BENCHMARK=1 PYTHONPATH=src/security-controller \
  python -m benchmarks.run --adapter local_prompts --mode A --allow-dirty
```

---

## Architecture & Zero-AWS Egress Guarantees

The benchmark harness executes in complete offline isolation:
- **Local Sigma Rule Loading ([`benchmarks/core/sigma_local.py`](file:///Users/ruchikkachaudhary/closed-source/Sentra/benchmarks/core/sigma_local.py))**: Rules are pre-compiled into `SigmaEngine.rules_cache` without DynamoDB or S3 calls.
- **Sentinel AWS Credentials**: Intercepts AWS egress attempts with `NullAuditWriter` and `NullMetricsPublisher`.
- **In-Process Guard Seam ([`benchmarks/core/guard_client.py`](file:///Users/ruchikkachaudhary/closed-source/Sentra/benchmarks/core/guard_client.py))**: Directly invokes `ValidationService.validate()` in memory without HTTP transport latency.
