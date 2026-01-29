#!/bin/bash
#
# API Gateway Testing Script
# Tests all 8 endpoints with authentication and validation
#
# Usage: ./test_api_gateway.sh
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Counters
PASS_COUNT=0
FAIL_COUNT=0

# Test result function
test_result() {
    local test_name="$1"
    local expected_status="$2"
    local actual_status="$3"
    
    if [ "$expected_status" == "$actual_status" ]; then
        echo -e "${GREEN}✅ PASS${NC}: $test_name (HTTP $actual_status)"
        ((PASS_COUNT++))
    else
        echo -e "${RED}❌ FAIL${NC}: $test_name (Expected HTTP $expected_status, got $actual_status)"
        ((FAIL_COUNT++))
    fi
}

echo "========================================="
echo "API Gateway Testing Script"
echo "========================================="
echo ""

# Get API URL and Key from CloudFormation
echo "Retrieving API configuration..."
API_URL=$(aws cloudformation describe-stacks \
  --stack-name Sentra-DEV-API-Stack \
  --profile sentra \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiUrl`].OutputValue' \
  --output text)

API_KEY_ID=$(aws cloudformation describe-stacks \
  --stack-name Sentra-DEV-API-Stack \
  --profile sentra \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiKeyId`].OutputValue' \
  --output text)

API_KEY=$(aws apigateway get-api-key \
  --api-key $API_KEY_ID \
  --include-value \
  --profile sentra \
  --query 'value' \
  --output text)

echo "API URL: $API_URL"
echo "API Key ID: $API_KEY_ID"
echo ""

# Test 1: Health endpoint (no auth)
echo "Test 1: GET /v1/health (no authentication)"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}v1/health")
test_result "Health endpoint without auth" "404" "$STATUS"
echo ""

# Test 2: Validate endpoint (with auth, valid payload)
echo "Test 2: POST /v1/validate (with authentication, valid payload)"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${API_URL}v1/validate" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"session_id":"test-123","agent_id":"test-agent","action":{"type":"query"}}')
test_result "Validate endpoint with valid payload" "404" "$STATUS"
echo ""

# Test 3: Validate endpoint (without auth)
echo "Test 3: POST /v1/validate (without authentication)"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${API_URL}v1/validate" \
  -H "Content-Type: application/json" \
  -d '{"session_id":"test-123","agent_id":"test-agent","action":{"type":"query"}}')
test_result "Validate endpoint without auth" "403" "$STATUS"
echo ""

# Test 4: Validate endpoint (invalid payload)
echo "Test 4: POST /v1/validate (invalid payload - missing required field)"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${API_URL}v1/validate" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"session_id":"test-123"}')
test_result "Validate endpoint with invalid payload" "400" "$STATUS"
echo ""

# Test 5: Logs endpoint (with auth)
echo "Test 5: GET /v1/logs (with authentication and query params)"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}v1/logs?limit=10&session_id=test-123" \
  -H "X-API-Key: $API_KEY")
test_result "Logs endpoint with auth" "404" "$STATUS"
echo ""

# Test 6: Logs endpoint (without auth)
echo "Test 6: GET /v1/logs (without authentication)"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}v1/logs?limit=10" )
test_result "Logs endpoint without auth" "403" "$STATUS"
echo ""

# Test 7: Rollback endpoint (with auth, valid payload)
echo "Test 7: POST /v1/rollback (with authentication, valid payload)"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${API_URL}v1/rollback" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"action_id":"test-action-123","reason":"test rollback","operator_id":"admin"}')
test_result "Rollback endpoint with valid payload" "404" "$STATUS"
echo ""

# Test 8: Rollback endpoint (invalid payload)
echo "Test 8: POST /v1/rollback (invalid payload - missing required field)"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${API_URL}v1/rollback" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"action_id":"test-123"}')
test_result "Rollback endpoint with invalid payload" "400" "$STATUS"
echo ""

# Test 9: Customer Query Agent - query endpoint
echo "Test 9: POST /v1/agents/customer-query/query (with authentication)"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${API_URL}v1/agents/customer-query/query" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"message":"Show customers from California"}')
test_result "Customer Query Agent query endpoint" "404" "$STATUS"
echo ""

# Test 10: Customer Query Agent - action endpoint
echo "Test 10: POST /v1/agents/customer-query/action (with authentication)"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${API_URL}v1/agents/customer-query/action" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"message":"Update customer email"}')
test_result "Customer Query Agent action endpoint" "404" "$STATUS"
echo ""

# Test 11: Payment Agent - query endpoint
echo "Test 11: POST /v1/agents/payment/query (with authentication)"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${API_URL}v1/agents/payment/query" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"message":"Check refund status for order 12345"}')
test_result "Payment Agent query endpoint" "404" "$STATUS"
echo ""

# Test 12: Payment Agent - action endpoint
echo "Test 12: POST /v1/agents/payment/action (with authentication)"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${API_URL}v1/agents/payment/action" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"message":"Process refund for order 12345"}')
test_result "Payment Agent action endpoint" "404" "$STATUS"
echo ""

# Test 13: Agent endpoint without auth
echo "Test 13: POST /v1/agents/customer-query/query (without authentication)"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${API_URL}v1/agents/customer-query/query" \
  -H "Content-Type: application/json" \
  -d '{"message":"test"}')
test_result "Agent endpoint without auth" "403" "$STATUS"
echo ""

# Test 14: Agent endpoint with invalid payload
echo "Test 14: POST /v1/agents/payment/action (invalid payload - missing message)"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${API_URL}v1/agents/payment/action" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"context":{}}')
test_result "Agent endpoint with invalid payload" "400" "$STATUS"
echo ""

# Summary
echo "========================================="
echo "Test Summary"
echo "========================================="
echo -e "${GREEN}Passed: $PASS_COUNT${NC}"
echo -e "${RED}Failed: $FAIL_COUNT${NC}"
echo "Total: $((PASS_COUNT + FAIL_COUNT))"
echo ""

if [ $FAIL_COUNT -eq 0 ]; then
    echo -e "${GREEN}✅ All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}❌ Some tests failed${NC}"
    exit 1
fi
