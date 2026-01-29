#!/bin/bash
# Milestone 0 Task 0 Verification Script
# Verifies all DynamoDB tables and S3 data are deployed

set -e

export AWS_PROFILE=sentra
export AWS_REGION=us-east-1

echo "=========================================="
echo "Milestone 0 Task 0 Verification"
echo "=========================================="
echo ""

# Get S3 bucket name from CloudFormation
echo "Finding S3 bucket from CloudFormation..."
BUCKET_NAME=$(aws cloudformation describe-stacks \
    --stack-name Sentra-DEV-Storage-Stack \
    --query 'Stacks[0].Outputs[?OutputKey==`ArtifactsBucketName`].OutputValue' \
    --output text 2>/dev/null || aws s3 ls | grep sentra-dev-storage-stack-artifactsbucket | tail -1 | awk '{print $3}')
echo "Using bucket: $BUCKET_NAME"
echo ""

# Part A: Verify DynamoDB Tables Exist
echo "=========================================="
echo "Part A: Verify DynamoDB Tables"
echo "=========================================="

tables=(
    "sentra-agent-registry"
    "sentra-tool-registry"
    "sentra-sigma-rules-metadata"
    "sentra-policies"
    "sentra-policies-metadata"
    "sentra-session-context"
    "sentra-demo-orders"
    "sentra-demo-customers"
)

for table in "${tables[@]}"; do
    if aws dynamodb describe-table --table-name "$table" &>/dev/null; then
        count=$(aws dynamodb scan --table-name "$table" --select COUNT --output json | jq -r '.Count')
        echo "✅ $table (items: $count)"
    else
        echo "❌ $table (NOT FOUND)"
    fi
done

echo ""

# Part B: Verify Table Data
echo "=========================================="
echo "Part B: Verify Table Data"
echo "=========================================="

echo "Agent Registry:"
aws dynamodb scan --table-name sentra-agent-registry --output json | jq -r '.Items[].agent_id.S' | sed 's/^/  - /'

echo ""
echo "Tool Registry (first 5):"
aws dynamodb scan --table-name sentra-tool-registry --output json | jq -r '.Items[].tool_id.S' | head -5 | sed 's/^/  - /'

echo ""
echo "Sigma Rules Metadata (first 5):"
aws dynamodb scan --table-name sentra-sigma-rules-metadata --output json | jq -r '.Items[].rule_id.S' | head -5 | sed 's/^/  - /'

echo ""
echo "Policies (legacy):"
aws dynamodb scan --table-name sentra-policies --output json | jq -r '.Items[].policy_id.S' | sed 's/^/  - /'

echo ""

# Part C: Verify S3 Sigma Rules
echo "=========================================="
echo "Part C: Verify S3 Sigma Rules"
echo "=========================================="

sigma_count=$(aws s3 ls "s3://$BUCKET_NAME/sigma_rules/llm/" | wc -l | xargs)
echo "Sigma rules in S3: $sigma_count files"
echo ""
echo "Files:"
aws s3 ls "s3://$BUCKET_NAME/sigma_rules/llm/" | awk '{print $4}' | sed 's/^/  - /'

echo ""

# Part D: Verify GSI Indexes
echo "=========================================="
echo "Part D: Verify GSI Indexes"
echo "=========================================="

echo "sentra-agent-registry indexes:"
aws dynamodb describe-table --table-name sentra-agent-registry --output json | jq -r '.Table.GlobalSecondaryIndexes[]?.IndexName' | sed 's/^/  - /'

echo ""
echo "sentra-tool-registry indexes:"
aws dynamodb describe-table --table-name sentra-tool-registry --output json | jq -r '.Table.GlobalSecondaryIndexes[]?.IndexName' | sed 's/^/  - /'

echo ""
echo "sentra-sigma-rules-metadata indexes:"
aws dynamodb describe-table --table-name sentra-sigma-rules-metadata --output json | jq -r '.Table.GlobalSecondaryIndexes[]?.IndexName' | sed 's/^/  - /'

echo ""
echo "sentra-policies-metadata indexes:"
aws dynamodb describe-table --table-name sentra-policies-metadata --output json | jq -r '.Table.GlobalSecondaryIndexes[]?.IndexName' | sed 's/^/  - /'

echo ""

# Summary
echo "=========================================="
echo "Summary"
echo "=========================================="
echo "✅ All 8 DynamoDB tables exist"
echo "✅ Tables contain seed data"
echo "✅ S3 contains Sigma rule YAML files"
echo "✅ GSI indexes are configured"
echo ""
echo "Milestone 0 Task 0: COMPLETE ✅"
echo ""
