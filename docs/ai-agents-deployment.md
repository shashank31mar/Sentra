# AI Agents Deployment Guide

**Version:** 1.0  
**Last Updated:** November 2025  
**Component:** Customer Query Agent & Payment Agent

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Prerequisites](#2-prerequisites)
3. [Environment Variables](#3-environment-variables)
4. [Deployment Steps](#4-deployment-steps)
5. [Health Verification](#5-health-verification)
6. [Rollback Procedures](#6-rollback-procedures)
7. [Troubleshooting](#7-troubleshooting)

---

## 1. Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                    API Gateway (Cognito)                     │
│  /v1/agents/customer-query/*                                 │
│  /v1/agents/payment/*                                        │
└────────────┬─────────────────┬────────────────────────────────┘
             │                 │
             ▼                 ▼
   ┌────────────────┐  ┌────────────────┐
   │ Customer Query │  │ Payment Agent  │
   │     Agent      │  │                │
   │  (ECS:8080)    │  │  (ECS:8080)    │
   └────┬───────────┘  └────┬───────────┘
        │                   │
        │ @secured_tool     │ @secured_tool
        │ validation        │ validation
        │                   │
        ▼                   ▼
   ┌────────────────────────────────┐
   │   Security Controller          │
   │   POST /v1/validate            │
   │   (ECS:8080)                   │
   └────────────────────────────────┘
             │
             ▼
   ┌────────────────────────────────┐
   │   AWS Services                 │
   │   - DynamoDB (demo data)       │
   │   - Bedrock (Claude Sonnet)    │
   │   - CloudWatch (metrics/logs)  │
   └────────────────────────────────┘
```

### Components

| Component | Port | Image | Purpose |
|-----------|------|-------|---------|
| Customer Query Agent | 8080 | `sentra/customer-query-agent` | Customer/order queries |
| Payment Agent | 8080 | `sentra/payment-agent` | Refund processing |
| Security Controller | 8080 | `sentra/security-controller` | Tool call validation |

---

## 2. Prerequisites

### AWS Resources
- ECS Cluster: `sentra-mvp-cluster`
- ECR Repositories: `sentra/customer-query-agent`, `sentra/payment-agent`
- DynamoDB Tables: `sentra-demo-customers`, `sentra-demo-orders`
- Bedrock Model Access: `anthropic.claude-sonnet-4-5-20250929-v1:0`

### Tools Required
```bash
# Verify AWS CLI
aws --version  # >= 2.x

# Verify Docker
docker --version  # >= 20.x

# Verify Python
python3 --version  # >= 3.11
```

### AWS Credentials
```bash
# Refresh credentials
ada cred update --once

# Set profile
export AWS_PROFILE=sentra
export AWS_REGION=us-east-1

# Verify
aws sts get-caller-identity
```

---

## 3. Environment Variables

### Customer Query Agent

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8080` | Service port |
| `SERVICE_NAME` | `customer-query-agent` | Service identifier |
| `DEMO_CUSTOMERS_TABLE` | `sentra-demo-customers` | DynamoDB customers table |
| `DEMO_ORDERS_TABLE` | `sentra-demo-orders` | DynamoDB orders table |
| `SECURITY_CONTROLLER_URL` | `http://security-controller.sentra.internal:8080` | Security Controller endpoint |
| `BEDROCK_MODEL_ID` | `anthropic.claude-sonnet-4-5-20250929-v1:0` | Bedrock model |
| `AWS_REGION` | `us-east-1` | AWS region |
| `LOG_LEVEL` | `INFO` | Logging level |

### Payment Agent

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8080` | Service port |
| `SERVICE_NAME` | `payment-agent` | Service identifier |
| `DEMO_ORDERS_TABLE` | `sentra-demo-orders` | DynamoDB orders table |
| `SECURITY_CONTROLLER_URL` | `http://security-controller.sentra.internal:8080` | Security Controller endpoint |
| `BEDROCK_MODEL_ID` | `anthropic.claude-sonnet-4-5-20250929-v1:0` | Bedrock model |
| `AWS_REGION` | `us-east-1` | AWS region |
| `LOG_LEVEL` | `INFO` | Logging level |

---

## 4. Deployment Steps

### Step 1: Build and Push Images

```bash
# Customer Query Agent
python scripts/build_and_push_image.py \
  --service customer-query-agent \
  --milestone <N>

# Payment Agent
python scripts/build_and_push_image.py \
  --service payment-agent \
  --milestone <N>
```

### Step 2: Deploy CDK Stack

```bash
cd cdk
cdk deploy SentraComputeStack --profile sentra
```

### Step 3: Verify ECS Services

```bash
aws ecs describe-services \
  --cluster sentra-mvp-cluster \
  --services sentra-customer-query-agent sentra-payment-agent \
  --profile sentra \
  --query 'services[*].[serviceName,status,runningCount]' \
  --output table
```

### Step 4: Force New Deployment (if needed)

```bash
# Customer Query Agent
aws ecs update-service \
  --cluster sentra-mvp-cluster \
  --service sentra-customer-query-agent \
  --force-new-deployment \
  --profile sentra

# Payment Agent
aws ecs update-service \
  --cluster sentra-mvp-cluster \
  --service sentra-payment-agent \
  --force-new-deployment \
  --profile sentra
```

---

## 5. Health Verification

### Check Health Endpoints

```bash
# Via internal ALB (from within VPC)
curl http://internal-sentra-private-alb-xxx.us-east-1.elb.amazonaws.com/customer-query/v1/health
curl http://internal-sentra-private-alb-xxx.us-east-1.elb.amazonaws.com/payment/v1/health
```

### Expected Response

```json
{
  "status": "ok",
  "service": "customer-query-agent",
  "timestamp": "2025-11-25T10:00:00Z",
  "checks": {
    "dynamodb_customers": "ok",
    "dynamodb_orders": "ok",
    "security_controller": "ok",
    "bedrock": "ok"
  }
}
```

### Check CloudWatch Logs

```bash
# Customer Query Agent logs
aws logs tail /ecs/sentra/customer-query-agent --follow --profile sentra

# Payment Agent logs
aws logs tail /ecs/sentra/payment-agent --follow --profile sentra
```

---

## 6. Rollback Procedures

### Option 1: Rollback to Previous Milestone

```bash
# Re-deploy previous milestone image
python scripts/build_and_push_image.py \
  --service customer-query-agent \
  --milestone <previous-N> \
  --force

# Force ECS to pull new image
aws ecs update-service \
  --cluster sentra-mvp-cluster \
  --service sentra-customer-query-agent \
  --force-new-deployment \
  --profile sentra
```

### Option 2: Scale Down Service

```bash
# Scale to 0 (emergency stop)
aws ecs update-service \
  --cluster sentra-mvp-cluster \
  --service sentra-customer-query-agent \
  --desired-count 0 \
  --profile sentra
```

### Option 3: CDK Rollback

```bash
# Rollback entire compute stack
cd cdk
cdk deploy SentraComputeStack --profile sentra --rollback
```

---

## 7. Troubleshooting

### Issue: Service Not Starting

**Symptoms:** ECS task keeps restarting, runningCount = 0

**Check:**
```bash
# View task stopped reason
aws ecs describe-tasks \
  --cluster sentra-mvp-cluster \
  --tasks $(aws ecs list-tasks --cluster sentra-mvp-cluster --service-name sentra-customer-query-agent --query 'taskArns[0]' --output text --profile sentra) \
  --profile sentra \
  --query 'tasks[0].stoppedReason'
```

**Common Causes:**
- Missing IAM permissions for DynamoDB/Bedrock
- Invalid environment variables
- Health check failing

### Issue: Security Controller Connection Failed

**Symptoms:** `Security Controller unavailable` in logs

**Check:**
```bash
# Verify Security Controller is running
aws ecs describe-services \
  --cluster sentra-mvp-cluster \
  --services sentra-security-controller \
  --profile sentra
```

**Fix:** Ensure Security Controller is deployed and healthy before agents.

### Issue: Bedrock API Errors

**Symptoms:** `Bedrock API error` in logs

**Check:**
```bash
# Verify model access
aws bedrock list-foundation-models \
  --by-provider anthropic \
  --region us-east-1 \
  --profile sentra
```

**Fix:** Request model access in Bedrock console if not enabled.

### Issue: DynamoDB Access Denied

**Symptoms:** `AccessDeniedException` in logs

**Check:** Verify ECS task role has DynamoDB permissions:
```bash
aws iam get-role-policy \
  --role-name sentra-ecs-task-role \
  --policy-name DynamoDBAccess \
  --profile sentra
```

---

## Related Documentation

- [AI Agents API Reference](./ai-agents-api-reference.md)
- [AI Agents Operations Guide](./ai-agents-operations.md)
- [LLD 07: AI Agents](../lld/05-ai-agents.md)
