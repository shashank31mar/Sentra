#!/bin/bash
# Sentra MVP - Cleanup Destroy Script
# Safely destroys all CDK stacks in the correct order

set -e

echo "======================================"
echo "Sentra MVP - Stack Destruction"
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

if [ -z "$AWS_ACCOUNT_ID" ]; then
    echo "ERROR: AWS_ACCOUNT_ID not set"
    echo "Run: export AWS_ACCOUNT_ID=531109575379"
    exit 1
fi

ENVIRONMENT=${ENVIRONMENT:-dev}

echo ""
echo "AWS Profile: $AWS_PROFILE"
echo "AWS Region: $AWS_REGION"
echo "AWS Account: $AWS_ACCOUNT_ID"
echo "Environment: $ENVIRONMENT"
echo ""

# Warning
echo "⚠️  WARNING: This will destroy ALL Sentra stacks in $ENVIRONMENT environment"
echo ""
read -p "Are you sure you want to continue? (type 'yes' to confirm): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

echo ""
echo "======================================"
echo "Destroying stacks (reverse order)..."
echo "======================================"

# Stack names (reverse order of creation)
STACK_PREFIX="Sentra-${ENVIRONMENT^^}"
STACKS=(
    "${STACK_PREFIX}-Monitoring-Stack"
    "${STACK_PREFIX}-API-Stack"
    "${STACK_PREFIX}-Compute-Stack"
    "${STACK_PREFIX}-Storage-Stack"
    "${STACK_PREFIX}-Network-Stack"
)

for STACK in "${STACKS[@]}"; do
    echo ""
    echo "Checking if stack exists: $STACK"

    # Check if stack exists
    if aws cloudformation describe-stacks --stack-name "$STACK" &>/dev/null; then
        echo "  ✓ Stack exists, destroying..."
        cdk destroy "$STACK" --force
        echo "  ✓ Stack $STACK destroyed"
    else
        echo "  ℹ Stack does not exist, skipping"
    fi
done

echo ""
echo "======================================"
echo "Manual Cleanup Required"
echo "======================================"
echo ""
echo "The following resources may require manual cleanup:"
echo ""

# Check for S3 buckets
echo "1. S3 Buckets:"
BUCKETS=$(aws s3 ls | grep -i sentra || true)
if [ -n "$BUCKETS" ]; then
    echo "$BUCKETS" | sed 's/^/   /'
    echo ""
    echo "   To delete:"
    echo "$BUCKETS" | awk '{print $3}' | while read BUCKET; do
        echo "   aws s3 rm s3://$BUCKET --recursive"
        echo "   aws s3 rb s3://$BUCKET"
    done
else
    echo "   ✓ No S3 buckets found"
fi

echo ""

# Check for ECR repositories
echo "2. ECR Repositories:"
REPOS=$(aws ecr describe-repositories \
    --query 'repositories[?contains(repositoryName, `sentra`)].repositoryName' \
    --output text 2>/dev/null || true)
if [ -n "$REPOS" ]; then
    echo "$REPOS" | tr '\t' '\n' | sed 's/^/   /'
    echo ""
    echo "   To delete:"
    echo "$REPOS" | tr '\t' '\n' | while read REPO; do
        echo "   aws ecr delete-repository --repository-name $REPO --force"
    done
else
    echo "   ✓ No ECR repositories found"
fi

echo ""

# Check for CloudWatch Log Groups
echo "3. CloudWatch Log Groups:"
LOG_GROUPS=$(aws logs describe-log-groups \
    --query 'logGroups[?contains(logGroupName, `sentra`)].logGroupName' \
    --output text 2>/dev/null || true)
if [ -n "$LOG_GROUPS" ]; then
    echo "$LOG_GROUPS" | tr '\t' '\n' | sed 's/^/   /'
    echo ""
    echo "   To delete (if needed for complete cleanup):"
    echo "$LOG_GROUPS" | tr '\t' '\n' | while read LOG_GROUP; do
        echo "   aws logs delete-log-group --log-group-name $LOG_GROUP"
    done
else
    echo "   ✓ No CloudWatch Log Groups found"
fi

echo ""
echo "======================================"
echo "Verification"
echo "======================================"
echo ""
echo "Run the cleanup verification script:"
echo "  ./scripts/cleanup_verify.sh"
echo ""
