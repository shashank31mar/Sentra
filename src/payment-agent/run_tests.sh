#!/bin/bash
# Payment Agent Test Runner
# Sentra MVP - Workstream 7, Task 7 & 8

set -e

echo "=========================================="
echo "Payment Agent - Running Tests"
echo "=========================================="

# Set environment variables for testing
export AWS_REGION=us-east-1
export DEMO_ORDERS_TABLE=sentra-demo-orders
export SECURITY_CONTROLLER_URL=http://security-controller.sentra.internal:8080
export BEDROCK_MODEL_ID=anthropic.claude-sonnet-4-5-20250929-v1:0
export SERVICE_NAME=payment-agent
export PORT=8080
export LOG_LEVEL=INFO

# Check if pytest is installed
if ! command -v pytest &> /dev/null; then
    echo "❌ pytest not found. Installing..."
    pip install pytest pytest-asyncio httpx
fi

echo ""
echo "Running unit tests..."
echo "=========================================="

# Run tests with coverage
pytest tests/ -v --tb=short

echo ""
echo "=========================================="
echo "✅ All tests completed!"
echo "=========================================="
