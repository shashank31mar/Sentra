#!/bin/bash
# Local E2E Benchmarking Script for Sentra with 4B Model (LLD 41 / Local E2E)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SENTRA_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$SENTRA_DIR"

echo "=========================================================="
echo "      Sentra Local E2E Security Benchmark Runner          "
echo "=========================================================="
echo ""

# 1. Check Python environment
VENV_PYTHON="src/security-controller/venv/bin/python"
if [ ! -f "$VENV_PYTHON" ]; then
    echo "Error: Python venv not found at $VENV_PYTHON"
    exit 1
fi

# 2. Check Ollama server & model
if ! command -v ollama >/dev/null 2>&1; then
    echo "Error: Ollama CLI not found. Please install Ollama (brew install ollama)."
    exit 1
fi

MODEL_NAME="qwen2.5:3b"
if ! ollama list | grep -q "qwen2.5:3b"; then
    echo "Pulling local model $MODEL_NAME..."
    ollama pull "$MODEL_NAME"
fi

echo "✅ Environment & Local LLM ($MODEL_NAME) Ready"
echo ""

# 3. Run Mode A (Replay Detection Benchmark)
echo "----------------------------------------------------------"
echo "1. Running Mode A: Detector Replay & Signature Matching..."
echo "----------------------------------------------------------"

AEGION_BENCHMARK=1 \
PYTHONPATH=src/security-controller \
"$VENV_PYTHON" -m benchmarks.run \
  --adapter agentdojo \
  --mode A \
  --suite banking \
  --allow-dirty

echo ""

# 4. Run Mode B (Paired Arm Defense Benchmark)
echo "----------------------------------------------------------"
echo "2. Running Mode B: Paired Arm Defense Effectiveness..."
echo "----------------------------------------------------------"

AEGION_BENCHMARK=1 \
PYTHONPATH=src/security-controller \
"$VENV_PYTHON" -m benchmarks.run \
  --adapter agentdojo \
  --mode B \
  --suite banking \
  --model "$MODEL_NAME" \
  --allow-dirty

echo ""
echo "=========================================================="
echo "🎉 Benchmark execution complete!"
echo "Latest run report available in benchmarks/runs/"
echo "=========================================================="
