#!/bin/bash
# Integration Test Script for Milestone 9-1
# Tests /execute endpoint for both Customer Query and Payment agents
#
# Usage: ./scripts/test_milestone_9_1.sh

set -e

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
CUSTOMER_AGENT_URL="${CUSTOMER_AGENT_URL:-http://localhost:8080}"
PAYMENT_AGENT_URL="${PAYMENT_AGENT_URL:-http://localhost:8081}"

echo -e "${YELLOW}=== Milestone 9-1 Integration Tests ===${NC}\n"

# Test 1: Customer Query Agent - Health Check
echo -e "${YELLOW}Test 1: Customer Query Agent /execute/health${NC}"
RESPONSE=$(curl -s -w "\n%{http_code}" "${CUSTOMER_AGENT_URL}/v1/execute/health")
HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | head -n-1)

if [ "$HTTP_CODE" == "200" ]; then
    echo -e "${GREEN}✓ PASS${NC} - Health check successful"
    echo "$BODY" | jq '.' 2>/dev/null || echo "$BODY"
else
    echo -e "${RED}✗ FAIL${NC} - Health check failed (HTTP $HTTP_CODE)"
    echo "$BODY"
fi

echo ""

# Test 2: Customer Query Agent - Execute query_customers
echo -e "${YELLOW}Test 2: Customer Query Agent - Execute query_customers${NC}"
PAYLOAD='{
  "tool_name": "query_customers",
  "tool_params": {"filters": {"state": "CA", "limit": 5}},
  "user_query": "Show me customers from California"
}'

RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${CUSTOMER_AGENT_URL}/v1/execute" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | head -n-1)

if [ "$HTTP_CODE" == "200" ]; then
    echo -e "${GREEN}✓ PASS${NC} - Execute successful"
    echo "$BODY" | jq '.status, .tool_name, .execution_time_ms, .response' 2>/dev/null || echo "$BODY"
else
    echo -e "${RED}✗ FAIL${NC} - Execute failed (HTTP $HTTP_CODE)"
    echo "$BODY"
fi

echo ""

# Test 3: Customer Query Agent - Invalid tool
echo -e "${YELLOW}Test 3: Customer Query Agent - Invalid tool (should fail)${NC}"
PAYLOAD='{
  "tool_name": "invalid_tool",
  "tool_params": {},
  "user_query": "test"
}'

RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${CUSTOMER_AGENT_URL}/v1/execute" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | head -n-1)

if [ "$HTTP_CODE" == "400" ]; then
    echo -e "${GREEN}✓ PASS${NC} - Invalid tool correctly rejected"
    echo "$BODY" | jq '.detail.error_code' 2>/dev/null || echo "$BODY"
else
    echo -e "${RED}✗ FAIL${NC} - Expected 400, got HTTP $HTTP_CODE"
    echo "$BODY"
fi

echo ""

# Test 4: Payment Agent - Health Check
echo -e "${YELLOW}Test 4: Payment Agent /execute/health${NC}"
RESPONSE=$(curl -s -w "\n%{http_code}" "${PAYMENT_AGENT_URL}/v1/execute/health")
HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | head -n-1)

if [ "$HTTP_CODE" == "200" ]; then
    echo -e "${GREEN}✓ PASS${NC} - Health check successful"
    echo "$BODY" | jq '.' 2>/dev/null || echo "$BODY"
else
    echo -e "${RED}✗ FAIL${NC} - Health check failed (HTTP $HTTP_CODE)"
    echo "$BODY"
fi

echo ""

# Test 5: Payment Agent - Execute query_refund_status
echo -e "${YELLOW}Test 5: Payment Agent - Execute query_refund_status${NC}"
PAYLOAD='{
  "tool_name": "query_refund_status",
  "tool_params": {"order_id": "ORD-123"},
  "user_query": "Show refund status for order ORD-123"
}'

RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${PAYMENT_AGENT_URL}/v1/execute" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | head -n-1)

if [ "$HTTP_CODE" == "200" ]; then
    echo -e "${GREEN}✓ PASS${NC} - Execute successful"
    echo "$BODY" | jq '.status, .tool_name, .execution_time_ms, .response' 2>/dev/null || echo "$BODY"
else
    echo -e "${RED}✗ FAIL${NC} - Execute failed (HTTP $HTTP_CODE)"
    echo "$BODY"
fi

echo ""
echo -e "${YELLOW}=== All Tests Complete ===${NC}"
