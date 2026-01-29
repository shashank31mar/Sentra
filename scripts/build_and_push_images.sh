#!/bin/bash
# Build and Push Docker Images to ECR
# This script builds placeholder Docker images for all 4 Sentra services
# and pushes them to ECR repositories

set -e  # Exit on error

# Configuration
export AWS_PROFILE=sentra
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=531109575379

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Sentra MVP - Build and Push Docker Images${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Verify AWS credentials
echo -e "${BLUE}[1/6] Verifying AWS credentials...${NC}"
aws sts get-caller-identity --profile $AWS_PROFILE > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ AWS credentials verified${NC}"
else
    echo -e "${RED}✗ AWS credentials invalid. Please run: ada cred update${NC}"
    exit 1
fi

# Get ECR login
echo -e "${BLUE}[2/6] Logging into ECR...${NC}"
aws ecr get-login-password --region $AWS_REGION --profile $AWS_PROFILE | \
    docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com
echo -e "${GREEN}✓ ECR login successful${NC}"
echo ""

# Define services
SERVICES=("security-controller" "dashboard" "customer-query-agent" "payment-agent")

# Build and push each service
for SERVICE in "${SERVICES[@]}"; do
    echo -e "${BLUE}[3/6] Building image for: ${SERVICE}${NC}"
    
    # ECR repository URI
    ECR_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/sentra/${SERVICE}"
    
    # Build Docker image for linux/amd64 (ECS Fargate requirement)
    docker build -t sentra/${SERVICE}:latest \
        --platform linux/amd64 \
        --build-arg SERVICE_NAME=${SERVICE} \
        -f docker-dummy/Dockerfile \
        docker-dummy/
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ Built: sentra/${SERVICE}:latest${NC}"
    else
        echo -e "${RED}✗ Failed to build ${SERVICE}${NC}"
        exit 1
    fi
    
    # Tag for ECR
    echo -e "${BLUE}[4/6] Tagging image: ${SERVICE}${NC}"
    docker tag sentra/${SERVICE}:latest ${ECR_URI}:latest
    echo -e "${GREEN}✓ Tagged: ${ECR_URI}:latest${NC}"
    
    # Push to ECR
    echo -e "${BLUE}[5/6] Pushing image to ECR: ${SERVICE}${NC}"
    docker push ${ECR_URI}:latest
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ Pushed: ${ECR_URI}:latest${NC}"
    else
        echo -e "${RED}✗ Failed to push ${SERVICE}${NC}"
        exit 1
    fi
    
    echo ""
done

# Verify all images in ECR
echo -e "${BLUE}[6/6] Verifying images in ECR...${NC}"
echo ""
for SERVICE in "${SERVICES[@]}"; do
    REPO_NAME="sentra/${SERVICE}"
    IMAGE_COUNT=$(aws ecr describe-images \
        --repository-name ${REPO_NAME} \
        --region ${AWS_REGION} \
        --profile ${AWS_PROFILE} \
        --query 'length(imageDetails)' \
        --output text 2>/dev/null || echo "0")
    
    if [ "$IMAGE_COUNT" -gt 0 ]; then
        echo -e "${GREEN}✓ ${REPO_NAME}: ${IMAGE_COUNT} image(s) found${NC}"
    else
        echo -e "${RED}✗ ${REPO_NAME}: No images found${NC}"
    fi
done

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}✓ All images built and pushed successfully!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Next steps:"
echo "  1. Deploy Compute Stack: cd cdk && cdk deploy Sentra-DEV-Compute-Stack"
echo "  2. Verify ECS services are running"
echo ""
