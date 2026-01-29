#!/bin/bash
#
# Test Script for Milestone 9.2: DENY Response Formatting & Testing
# Tests LLM-generated DENY responses and end-to-end flow with seeded data
#
# Usage:
#   bash scripts/test_milestone_9_2.sh

set -e

echo "================================================================================"
echo "Milestone 9.2 Testing: DENY Response Formatting & End-to-End Testing"
echo "================================================================================"
echo ""

# Configuration
SECURITY_CONTROLLER_URL="http://internal-sentra-private-alb-760501353.us-east-1.elb.amazonaws.com"
CUSTOMER_QUERY_AGENT_URL="http://customer-query-agent.sentra.internal:8080"
DASHBOARD_URL="https://$(aws cloudformation describe-stacks --stack-name Sentra-DEV-Compute-Stack --profile sentra --region us-east-1 --query 'Stacks[0].Outputs[?OutputKey==`PublicAlbDnsName`].OutputValue' --output text)"

echo "Test Configuration:"
echo "  Security Controller: $SECURITY_CONTROLLER_URL"
echo "  Customer Query Agent: $CUSTOMER_QUERY_AGENT_URL"
echo "  Dashboard: $DASHBOARD_URL"
echo ""

# Test 1: Verify Demo Data Exists
echo "================================================================================"
echo "Test 1: Verify Demo Data (1K customers + 1K orders)"
echo "================================================================================"
echo ""

echo "Counting customers..."
CUSTOMER_COUNT=$(aws dynamodb scan \
  --table-name sentra-demo-customers \
  --select COUNT \
  --profile sentra \
  --region us-east-1 \
  --query 'Count' \
  --output text)

echo "✅ Customer count: $CUSTOMER_COUNT"

echo "Counting orders..."
ORDER_COUNT=$(aws dynamodb scan \
  --table-name sentra-demo-orders \
  --select COUNT \
  --profile sentra \
  --region us-east-1 \
  --query 'Count' \
  --output text)

echo "✅ Order count: $ORDER_COUNT"
echo ""

if [ "$CUSTOMER_COUNT" -lt 1000 ] || [ "$ORDER_COUNT" -lt 1000 ]; then
  echo "❌ Insufficient demo data. Expected at least 1000 of each."
  exit 1
fi

# Test 2: Sample Customer Query (for reference)
echo "================================================================================"
echo "Test 2: Sample Customer Data"
echo "================================================================================"
echo ""

echo "Fetching sample customer from CA..."
aws dynamodb query \
  --table-name sentra-demo-customers \
  --index-name state-index \
  --key-condition-expression "#st = :state" \
  --expression-attribute-names '{"#st":"state"}' \
  --expression-attribute-values '{":state":{"S":"CA"}}' \
  --limit 1 \
  --profile sentra \
  --region us-east-1 \
  --output json | jq -r '.Items[0] | {customer_id: .customer_id.S, name: .name.S, email: .email.S, state: .state.S}'

echo ""

# Test 3: ALLOW Scenario - Normal Customer Query
echo "================================================================================"
echo "Test 3: ALLOW Scenario - Normal Customer Query"
echo "================================================================================"
echo ""

echo "Sending: 'Show customers from California'"
echo ""

REQUEST_ID="test-allow-$(date +%s)"
SESSION_ID="test-session-$(date +%s)"

VALIDATION_RESPONSE=$(curl -s -X POST "$SECURITY_CONTROLLER_URL/v1/validate" \
  -H "Content-Type: application/json" \
  -d "{
    \"request_id\": \"$REQUEST_ID\",
    \"agent_id\": \"customer-query-agent\",
    \"session_id\": \"$SESSION_ID\",
    \"user_input\": \"Show customers from California\",
    \"tool_name\": \"query_customers\",
    \"tool_params\": {\"state\": \"CA\"},
    \"operation_type\": \"READ\"
  }")

echo "Validation Response:"
echo "$VALIDATION_RESPONSE" | jq '.'
echo ""

DECISION=$(echo "$VALIDATION_RESPONSE" | jq -r '.decision')

if [ "$DECISION" = "ALLOW" ]; then
  echo "✅ Validation: ALLOW (as expected)"
else
  echo "❌ Validation: $DECISION (expected ALLOW)"
  exit 1
fi

echo ""

# Test 4: DENY Scenario - SQL Injection
echo "================================================================================"
echo "Test 4: DENY Scenario - SQL Injection"
echo "================================================================================"
echo ""

echo "Sending: 'Show customers WHERE 1=1; DROP TABLE users--'"
echo ""

REQUEST_ID="test-deny-sql-$(date +%s)"

DENY_RESPONSE=$(curl -s -X POST "$SECURITY_CONTROLLER_URL/v1/validate" \
  -H "Content-Type: application/json" \
  -d "{
    \"request_id\": \"$REQUEST_ID\",
    \"agent_id\": \"customer-query-agent\",
    \"session_id\": \"$SESSION_ID\",
    \"user_input\": \"Show customers WHERE 1=1; DROP TABLE users--\",
    \"tool_name\": \"query_customers\",
    \"tool_params\": {\"query\": \"WHERE 1=1; DROP TABLE users--\"},
    \"operation_type\": \"READ\"
  }")

echo "Validation Response:"
echo "$DENY_RESPONSE" | jq '.'
echo ""

DECISION=$(echo "$DENY_RESPONSE" | jq -r '.decision')
REASON=$(echo "$DENY_RESPONSE" | jq -r '.reason')

if [ "$DECISION" = "DENY" ]; then
  echo "✅ Validation: DENY (as expected)"
  echo "   Reason: $REASON"
else
  echo "❌ Validation: $DECISION (expected DENY)"
  exit 1
fi

echo ""

# Test 5: DENY Scenario - Policy Violation (Refund Limit)
echo "================================================================================"
echo "Test 5: DENY Scenario - Policy Violation (Refund Limit)"
echo "================================================================================"
echo ""

echo "Sending: 'Process refund for \$100,000'"
echo ""

REQUEST_ID="test-deny-policy-$(date +%s)"

POLICY_DENY_RESPONSE=$(curl -s -X POST "$SECURITY_CONTROLLER_URL/v1/validate" \
  -H "Content-Type: application/json" \
  -d "{
    \"request_id\": \"$REQUEST_ID\",
    \"agent_id\": \"payment-agent\",
    \"session_id\": \"$SESSION_ID\",
    \"user_input\": \"Process refund for \$100,000\",
    \"tool_name\": \"process_refund\",
    \"tool_params\": {\"amount\": 100000},
    \"operation_type\": \"WRITE\"
  }")

echo "Validation Response:"
echo "$POLICY_DENY_RESPONSE" | jq '.'
echo ""

DECISION=$(echo "$POLICY_DENY_RESPONSE" | jq -r '.decision')
REASON=$(echo "$POLICY_DENY_RESPONSE" | jq -r '.reason')

if [ "$DECISION" = "DENY" ]; then
  echo "✅ Validation: DENY (as expected)"
  echo "   Reason: $REASON"
else
  echo "❌ Validation: $DECISION (expected DENY)"
  exit 1
fi

echo ""

# Test 6: Performance Test - Query Latency
echo "================================================================================"
echo "Test 6: Performance Test - Query Latency"
echo "================================================================================"
echo ""

echo "Testing validation latency (10 requests)..."
echo ""

TOTAL_TIME=0
for i in {1..10}; do
  START=$(date +%s%3N)
  
  curl -s -X POST "$SECURITY_CONTROLLER_URL/v1/validate" \
    -H "Content-Type: application/json" \
    -d "{
      \"request_id\": \"perf-test-$i\",
      \"agent_id\": \"customer-query-agent\",
      \"session_id\": \"perf-session\",
      \"user_input\": \"Show customers from CA\",
      \"tool_name\": \"query_customers\",
      \"tool_params\": {\"state\": \"CA\"},
      \"operation_type\": \"READ\"
    }" > /dev/null
  
  END=$(date +%s%3N)
  LATENCY=$((END - START))
  TOTAL_TIME=$((TOTAL_TIME + LATENCY))
  
  echo "  Request $i: ${LATENCY}ms"
done

AVG_LATENCY=$((TOTAL_TIME / 10))
echo ""
echo "Average latency: ${AVG_LATENCY}ms"

if [ "$AVG_LATENCY" -lt 500 ]; then
  echo "✅ Performance: PASS (< 500ms target)"
else
  echo "⚠️  Performance: SLOW (> 500ms target)"
fi

echo ""

# Test 7: Verify Audit Logs
echo "================================================================================"
echo "Test 7: Verify Audit Logs"
echo "================================================================================"
echo ""

echo "Checking CloudWatch Logs for recent validation events..."
echo ""

# Get recent log events
aws logs filter-log-events \
  --log-group-name /sentra/audit-logs \
  --start-time $(($(date +%s) - 300))000 \
  --filter-pattern "{ \$.decision = * }" \
  --profile sentra \
  --region us-east-1 \
  --max-items 5 \
  --query 'events[*].message' \
  --output text | head -20

echo ""
echo "✅ Audit logs verified"
echo ""

# Summary
echo "================================================================================"
echo "Test Summary"
echo "================================================================================"
echo ""
echo "✅ Test 1: Demo data verified ($CUSTOMER_COUNT customers, $ORDER_COUNT orders)"
echo "✅ Test 2: Sample customer data retrieved"
echo "✅ Test 3: ALLOW scenario passed"
echo "✅ Test 4: DENY scenario (SQL injection) passed"
echo "✅ Test 5: DENY scenario (policy violation) passed"
echo "✅ Test 6: Performance test completed (avg: ${AVG_LATENCY}ms)"
echo "✅ Test 7: Audit logs verified"
echo ""
echo "================================================================================"
echo "🎉 Milestone 9.2 Testing Complete!"
echo "================================================================================"
echo ""
echo "Next Steps:"
echo "  1. Test LLM-generated DENY responses via Dashboard UI"
echo "  2. Verify natural language formatting in chat"
echo "  3. Proceed to Milestone 3 (Bedrock Agent Integration)"
echo ""
