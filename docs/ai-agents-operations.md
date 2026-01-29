# AI Agents Operations Guide

**Version:** 1.0  
**Last Updated:** November 2025

---

## Table of Contents

1. [Adding New Tools](#1-adding-new-tools)
2. [Updating Agent Policies](#2-updating-agent-policies)
3. [Monitoring Agent Health](#3-monitoring-agent-health)
4. [Troubleshooting Guide](#4-troubleshooting-guide)

---

## 1. Adding New Tools

### Step 1: Create Tool Implementation

Create a new file in `src/<agent>/app/tools/`:

```python
# src/customer-query-agent/app/tools/new_tool.py
"""
Tool: new_tool
Description of what this tool does
"""

import os
import logging
from typing import Dict

from app.security_integration import secured_tool

logger = logging.getLogger(__name__)


@secured_tool
def new_tool(param1: str, param2: int = 100) -> Dict:
    """
    Tool description

    Args:
        param1: Description
        param2: Description (default: 100)

    Returns:
        Result dictionary

    Security Validations:
    - List any security rules that apply
    """
    # Implementation
    logger.info(f"Executing new_tool with param1={param1}")
    
    result = {
        "status": "success",
        "data": {}
    }
    
    return result
```

### Step 2: Register Tool in Claude Processor

Update `app/claude_processor.py`:

```python
# Add import
from app.tools.new_tool import new_tool

# Add to TOOL_REGISTRY
TOOL_REGISTRY = {
    # ... existing tools
    "new_tool": new_tool
}

# Add to tool schemas
CUSTOMER_QUERY_TOOLS = [
    # ... existing tools
    {
        "name": "new_tool",
        "description": "Description for Claude to understand when to use this tool",
        "input_schema": {
            "type": "object",
            "properties": {
                "param1": {
                    "type": "string",
                    "description": "Parameter description"
                },
                "param2": {
                    "type": "integer",
                    "description": "Optional parameter",
                    "default": 100
                }
            },
            "required": ["param1"]
        }
    }
]
```

### Step 3: Update Agent Policy

Add the tool to the agent's policy in S3:

```yaml
# s3://sentra-mvp-artifacts/policies/customer-query-agent-policy.yaml
allowed_tools:
  - query_customers
  - query_orders
  - get_customer_by_id
  - call_payment_agent
  - new_tool  # Add new tool
```

### Step 4: Add Tests

Create tests in `tests/test_tools.py`:

```python
def test_new_tool_success():
    result = new_tool(param1="test", param2=50)
    assert result["status"] == "success"

def test_new_tool_validation():
    with pytest.raises(ValueError):
        new_tool(param1="")
```

### Step 5: Deploy

```bash
python scripts/build_and_push_image.py \
  --service customer-query-agent \
  --milestone <N+1>
```

---

## 2. Updating Agent Policies

### Policy Location

Policies are stored using hybrid DynamoDB + S3:
- **Metadata**: `sentra-policies-metadata` DynamoDB table
- **Content**: `s3://sentra-mvp-artifacts/policies/`

### Policy Structure

```yaml
# Policy YAML format
policy_id: customer-query-agent-policy-v1
agent_id: customer-query-agent
name: Customer Query Agent Policy
description: Defines allowed tools and agents for CQA
status: active
version: 1

allowed_tools:
  - query_customers
  - query_orders
  - get_customer_by_id
  - call_payment_agent

allowed_agents:
  - payment-agent

policies:
  - name: data-access-limit
    description: Limit data access to prevent exfiltration
    rule: "tool_params.limit <= 1000"
    action: DENY
    severity: high
```

### Updating a Policy

1. **Download current policy:**
```bash
aws s3 cp s3://sentra-mvp-artifacts/policies/customer-query-agent-policy.yaml ./policy.yaml --profile sentra
```

2. **Edit policy:**
```bash
vim policy.yaml
```

3. **Upload updated policy:**
```bash
aws s3 cp ./policy.yaml s3://sentra-mvp-artifacts/policies/customer-query-agent-policy.yaml --profile sentra
```

4. **Update metadata (if version changed):**
```bash
aws dynamodb put-item \
  --table-name sentra-policies-metadata \
  --item '{
    "policy_id": {"S": "customer-query-agent-policy-v2"},
    "agent_id": {"S": "customer-query-agent"},
    "status": {"S": "active"},
    "s3_bucket": {"S": "sentra-mvp-artifacts"},
    "s3_key": {"S": "policies/customer-query-agent-policy.yaml"},
    "version": {"N": "2"}
  }' \
  --profile sentra
```

5. **Invalidate cache (restart service or wait 5 min):**
```bash
aws ecs update-service \
  --cluster sentra-mvp-cluster \
  --service sentra-security-controller \
  --force-new-deployment \
  --profile sentra
```

---

## 3. Monitoring Agent Health

### CloudWatch Dashboard

Access the dashboard:
```
https://console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards:name=sentra-mvp-dashboard
```

### Key Metrics to Monitor

| Metric | Namespace | Threshold | Action |
|--------|-----------|-----------|--------|
| `RequestsReceived` | Sentra/Agents | - | Track volume |
| `RequestsFailed` | Sentra/Agents | > 5/min | Investigate |
| `SecurityDenials` | Sentra/Agents | > 30% | Check policies |
| `BedrockLatency` | Sentra/Agents | p95 > 3s | Check Bedrock |
| `ToolExecutionTime` | Sentra/Agents | p95 > 1s | Optimize tools |

### Health Check Commands

```bash
# Check ECS service status
aws ecs describe-services \
  --cluster sentra-mvp-cluster \
  --services sentra-customer-query-agent sentra-payment-agent \
  --profile sentra \
  --query 'services[*].[serviceName,status,runningCount,desiredCount]' \
  --output table

# Check recent logs
aws logs tail /ecs/sentra/customer-query-agent --since 10m --profile sentra

# Check CloudWatch alarms
aws cloudwatch describe-alarms \
  --alarm-name-prefix sentra-mvp \
  --state-value ALARM \
  --profile sentra
```

### Alarm Response Procedures

| Alarm | Severity | Response |
|-------|----------|----------|
| `cqa-health-check-failure` | P0 | Check ECS task, restart if needed |
| `pa-health-check-failure` | P0 | Check ECS task, restart if needed |
| `ai-agents-bedrock-errors` | P0 | Check Bedrock service status |
| `ai-agents-high-latency` | P1 | Check Bedrock latency, scale if needed |
| `ai-agents-high-denial-rate` | P1 | Review policies, check for attacks |
| `ai-agents-tool-errors` | P1 | Check DynamoDB, review tool code |

---

## 4. Troubleshooting Guide

### Problem: Agent Returns 403 for All Requests

**Symptoms:**
- All requests return `SECURITY_VALIDATION_FAILED`
- Logs show `Security Controller DENIED`

**Diagnosis:**
```bash
# Check Security Controller health
curl http://security-controller.sentra.internal:8080/v1/health

# Check agent policy exists
aws dynamodb query \
  --table-name sentra-policies-metadata \
  --index-name agent-index \
  --key-condition-expression "agent_id = :aid" \
  --expression-attribute-values '{":aid": {"S": "customer-query-agent"}}' \
  --profile sentra
```

**Resolution:**
1. Verify policy exists and is `active`
2. Check tool is in `allowed_tools` list
3. Restart Security Controller to refresh cache

### Problem: Bedrock Timeout Errors

**Symptoms:**
- Requests timeout after 30s
- Logs show `Bedrock API error`

**Diagnosis:**
```bash
# Check Bedrock service status
aws bedrock list-foundation-models --profile sentra --region us-east-1

# Check model access
aws bedrock get-foundation-model-availability \
  --model-id anthropic.claude-sonnet-4-5-20250929-v1:0 \
  --profile sentra
```

**Resolution:**
1. Check AWS Bedrock service health
2. Verify model access is enabled
3. Check for throttling (increase limits if needed)

### Problem: DynamoDB Access Denied

**Symptoms:**
- Tools fail with `AccessDeniedException`
- Health check shows `dynamodb_*: error`

**Diagnosis:**
```bash
# Check ECS task role
aws iam list-attached-role-policies \
  --role-name sentra-ecs-task-role \
  --profile sentra

# Test DynamoDB access
aws dynamodb describe-table \
  --table-name sentra-demo-customers \
  --profile sentra
```

**Resolution:**
1. Verify ECS task role has DynamoDB permissions
2. Check table names match environment variables
3. Redeploy CDK stack if IAM changes needed

### Problem: Inter-Agent Communication Failing

**Symptoms:**
- `call_payment_agent` tool fails
- Logs show `Failed to communicate with Payment Agent`

**Diagnosis:**
```bash
# Check Payment Agent is running
aws ecs describe-services \
  --cluster sentra-mvp-cluster \
  --services sentra-payment-agent \
  --profile sentra

# Check service discovery
aws servicediscovery list-services --profile sentra
```

**Resolution:**
1. Verify Payment Agent is running
2. Check service discovery DNS resolution
3. Verify security groups allow inter-service traffic

### Problem: High Latency

**Symptoms:**
- Response times > 5s
- Users complaining about slow responses

**Diagnosis:**
```bash
# Check Bedrock latency
aws cloudwatch get-metric-statistics \
  --namespace Sentra/Agents \
  --metric-name BedrockLatency \
  --start-time $(date -u -v-1H +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics p95 \
  --profile sentra

# Check tool execution time
aws cloudwatch get-metric-statistics \
  --namespace Sentra/Agents \
  --metric-name ToolExecutionTime \
  --start-time $(date -u -v-1H +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics p95 \
  --profile sentra
```

**Resolution:**
1. If Bedrock latency high: Check model, consider caching
2. If tool execution high: Optimize DynamoDB queries
3. If Security Controller high: Check validation pipeline

---

## Log Analysis

### Common Log Patterns

```bash
# Find security denials
aws logs filter-log-events \
  --log-group-name /ecs/sentra/customer-query-agent \
  --filter-pattern "Security Controller DENIED" \
  --profile sentra

# Find Bedrock errors
aws logs filter-log-events \
  --log-group-name /ecs/sentra/customer-query-agent \
  --filter-pattern "Bedrock API error" \
  --profile sentra

# Find tool execution errors
aws logs filter-log-events \
  --log-group-name /ecs/sentra/customer-query-agent \
  --filter-pattern "Tool execution failed" \
  --profile sentra
```

---

## Related Documentation

- [AI Agents Deployment Guide](./ai-agents-deployment.md)
- [AI Agents API Reference](./ai-agents-api-reference.md)
