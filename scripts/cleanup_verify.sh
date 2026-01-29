#!/bin/bash
# Sentra MVP - Cleanup Verification Script
# Verifies that all AWS resources have been properly cleaned up

set -e

echo "======================================"
echo "Sentra MVP - Cleanup Verification"
echo "======================================"

# Ensure AWS profile is set
if [ -z "$AWS_PROFILE" ]; then
    echo "ERROR: AWS_PROFILE not set"
    echo "Run: export AWS_PROFILE=sentra"
    exit 1
fi

if [ -z "$AWS_REGION" ]; then
    export AWS_REGION=us-east-1
fi

echo ""
echo "AWS Profile: $AWS_PROFILE"
echo "AWS Region: $AWS_REGION"
echo ""

ISSUES_FOUND=0

# Check for CloudFormation stacks
echo "1. Checking for CloudFormation stacks..."
STACKS=$(aws cloudformation list-stacks \
    --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE \
    --query 'StackSummaries[?contains(StackName, `Sentra`)].StackName' \
    --output text)

if [ -n "$STACKS" ]; then
    echo "   ❌ FOUND: CloudFormation stacks still exist:"
    echo "$STACKS" | tr '\t' '\n' | sed 's/^/      - /'
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
else
    echo "   ✅ No Sentra CloudFormation stacks found"
fi

# Check for VPCs
echo ""
echo "2. Checking for VPCs..."
VPCS=$(aws ec2 describe-vpcs \
    --filters "Name=tag:Project,Values=Sentra" \
    --query 'Vpcs[].VpcId' \
    --output text)

if [ -n "$VPCS" ]; then
    echo "   ❌ FOUND: VPCs still exist:"
    echo "$VPCS" | tr '\t' '\n' | sed 's/^/      - /'
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
else
    echo "   ✅ No Sentra VPCs found"
fi

# Check for NAT Gateways (COST!)
echo ""
echo "3. Checking for NAT Gateways (💰 COST)..."
NAT_GWS=$(aws ec2 describe-nat-gateways \
    --filter "Name=state,Values=available" \
    --query 'NatGateways[].NatGatewayId' \
    --output text)

if [ -n "$NAT_GWS" ]; then
    echo "   ❌ FOUND: NAT Gateways still exist (💰 ~$32/month each):"
    echo "$NAT_GWS" | tr '\t' '\n' | sed 's/^/      - /'
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
else
    echo "   ✅ No NAT Gateways found"
fi

# Check for unattached Elastic IPs (COST!)
echo ""
echo "4. Checking for unattached Elastic IPs (💰 COST)..."
EIPS=$(aws ec2 describe-addresses \
    --query 'Addresses[?AssociationId==null].AllocationId' \
    --output text)

if [ -n "$EIPS" ]; then
    echo "   ❌ FOUND: Unattached Elastic IPs (💰 $0.005/hour each):"
    echo "$EIPS" | tr '\t' '\n' | sed 's/^/      - /'
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
else
    echo "   ✅ No unattached Elastic IPs found"
fi

# Check for S3 buckets
echo ""
echo "5. Checking for S3 buckets..."
BUCKETS=$(aws s3 ls | grep -i sentra | awk '{print $3}' || true)

if [ -n "$BUCKETS" ]; then
    echo "   ❌ FOUND: S3 buckets still exist:"
    echo "$BUCKETS" | sed 's/^/      - /'
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
else
    echo "   ✅ No Sentra S3 buckets found"
fi

# Check for DynamoDB tables
echo ""
echo "6. Checking for DynamoDB tables..."
TABLES=$(aws dynamodb list-tables \
    --query 'TableNames[?contains(@, `sentra`)]' \
    --output text)

if [ -n "$TABLES" ]; then
    echo "   ❌ FOUND: DynamoDB tables still exist:"
    echo "$TABLES" | tr '\t' '\n' | sed 's/^/      - /'
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
else
    echo "   ✅ No Sentra DynamoDB tables found"
fi

# Check for ECR repositories
echo ""
echo "7. Checking for ECR repositories..."
REPOS=$(aws ecr describe-repositories \
    --query 'repositories[?contains(repositoryName, `sentra`)].repositoryName' \
    --output text 2>/dev/null || true)

if [ -n "$REPOS" ]; then
    echo "   ❌ FOUND: ECR repositories still exist:"
    echo "$REPOS" | tr '\t' '\n' | sed 's/^/      - /'
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
else
    echo "   ✅ No Sentra ECR repositories found"
fi

# Check for CloudWatch Log Groups
echo ""
echo "8. Checking for CloudWatch Log Groups..."
LOG_GROUPS=$(aws logs describe-log-groups \
    --query 'logGroups[?contains(logGroupName, `sentra`)].logGroupName' \
    --output text 2>/dev/null || true)

if [ -n "$LOG_GROUPS" ]; then
    echo "   ⚠️  WARNING: CloudWatch Log Groups still exist:"
    echo "$LOG_GROUPS" | tr '\t' '\n' | sed 's/^/      - /'
    echo "   (These are usually safe to keep for audit purposes)"
else
    echo "   ✅ No Sentra CloudWatch Log Groups found"
fi

# Check for ECS Clusters
echo ""
echo "9. Checking for ECS Clusters..."
CLUSTERS=$(aws ecs list-clusters \
    --query 'clusterArns[?contains(@, `sentra`)]' \
    --output text 2>/dev/null || true)

if [ -n "$CLUSTERS" ]; then
    echo "   ❌ FOUND: ECS clusters still exist:"
    echo "$CLUSTERS" | tr '\t' '\n' | sed 's/^/      - /'
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
else
    echo "   ✅ No Sentra ECS clusters found"
fi

# Summary
echo ""
echo "======================================"
echo "Cleanup Verification Summary"
echo "======================================"

if [ $ISSUES_FOUND -eq 0 ]; then
    echo "✅ SUCCESS: All resources cleaned up!"
    echo ""
    echo "No dangling resources found."
    exit 0
else
    echo "❌ ISSUES FOUND: $ISSUES_FOUND resource type(s) still exist"
    echo ""
    echo "Please manually clean up the resources listed above."
    echo ""
    echo "Estimated monthly cost of remaining resources:"
    echo "  - NAT Gateways: ~$32/month each"
    echo "  - Elastic IPs (unattached): ~$3.60/month each"
    echo ""
    exit 1
fi
