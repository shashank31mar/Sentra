# Bedrock Agent Architecture - Clarifications

**Document**: Architecture clarifications for Workstream 9, Milestone 3
**Date**: December 1, 2025
**Status**: Complete

---

## Key Questions Answered

### Q1: Why is Customer Query Agent code in Bedrock Action Group Lambda?

**Answer**: Two separate, independent agents with similar functionality:

#### Agent 1: Self-Hosted Customer Query Agent (ECS)
```
Location: ECS container on Sentra infrastructure
Endpoint: customer-query-agent.sentra.internal:8080/v1/query
Purpose: Internal Sentra agent for Dashboard
Validation: Internal (agent calls Security Controller itself)
Status: Already deployed and working ✅
```

#### Agent 2: AWS Bedrock Agent (External)
```
Location: AWS Bedrock managed service
Endpoint: Bedrock Agent ID via AWS SDK
Purpose: Demo external agent integration with Sentra
Validation: External (Lambda calls /validate API)
Status: In development (Milestone 3)
```

**Why similar code?**
- Bedrock Action Group Lambda **replaces** the ECS agent functionality in Scenario B
- It implements the SAME tools (query_customers, get_order_details, process_refund)
- But validates externally via public API (not internal)
- This demonstrates how third-party agents (Bedrock/Vertex/Azure) integrate with Sentra

**Key Difference**:
```
Self-Hosted Agent:  Agent → Internal Validation → Execute
Bedrock Agent:      Agent → Lambda → External /validate API → Execute
```

---

### Q2: How Does Bedrock Lambda Call /validate API?

**Answer**: Via public API Gateway endpoint with API key authentication.

#### Architecture

```
┌─────────────────────────────────────────┐
│ AWS Bedrock Service                     │
│ (AWS-managed infrastructure)            │
│                                         │
│  ┌────────────────────────────────┐    │
│  │ Action Group Lambda            │    │
│  │ (Your code)                    │    │
│  │                                │    │
│  │ 1. Fetch API key from Secrets  │    │
│  │    Manager (IAM auth)          │    │
│  │                                │    │
│  │ 2. Call /validate API          │    │
│  └────────┬───────────────────────┘    │
└───────────┼──────────────────────────────┘
            │
            ↓ HTTPS (public internet)
┌───────────────────────────────────────────┐
│ Sentra API Gateway (PUBLIC)               │
│ https://iw3limi4k7.execute-api...         │
│                                           │
│ Authentication: X-API-Key header          │
│ (NOT Cognito - that's for Dashboard ALB) │
└───────────────────────────────────────────┘
            ↓
┌───────────────────────────────────────────┐
│ Security Controller (ECS)                 │
│ Validates request, returns ALLOW/DENY     │
└───────────────────────────────────────────┘
```

#### Key Points

1. **No VPC Issue**:
   - API Gateway is PUBLIC (accessible from internet via HTTPS)
   - Bedrock Lambda has internet access by default
   - No VPC configuration or peering needed

2. **Authentication**:
   - API Gateway uses API Key authentication (X-API-Key header)
   - API key stored in AWS Secrets Manager
   - Lambda fetches key at runtime using IAM permissions
   - NOT behind Cognito (Dashboard ALB uses Cognito, not API Gateway)

3. **Security**:
   - API key not visible in Lambda code
   - Fetched securely via Secrets Manager API
   - Cached in Lambda container for performance
   - Can be rotated without redeploying Lambda

---

## What is Action Group Lambda?

**Short Answer**: The Lambda function that executes agent tools.

**AWS Bedrock Architecture**:
```
User Message
    ↓
Bedrock Agent (AWS-managed LLM)
    ↓ Decides: "User wants to query customers"
    ↓ Invokes: Action Group Lambda
    ↓
Action Group Lambda (YOUR CODE)
    ↓
    1. Extract tool name & parameters
    2. Call Sentra /validate API ← YOUR VALIDATION
    3. If ALLOW → Query DynamoDB
    4. Return result
    ↓
Bedrock Agent formats response naturally
    ↓
User sees: "I found 5 customers from California..."
```

**Think of it as**:
- **Bedrock Agent** = Brain (LLM decides what to do)
- **Action Group Lambda** = Hands (executes the actual work)

**Cannot skip Lambda**: Bedrock Agent doesn't call APIs directly - it always calls Lambda to execute tools.

---

## Secrets Manager Integration

### Why Use Secrets Manager?

**Problem**:
```python
# BAD: Hardcoded API key
headers = {"x-api-key": "OXu1KiE3Xia26QQBgmfHe2SLWcVaNGV16QxwkVKf"}  # ❌ Visible in code
```

**Solution**:
```python
# GOOD: Fetch from Secrets Manager
api_key = get_sentra_api_key()  # Fetched securely at runtime
headers = {"x-api-key": api_key}  # ✅ Not in code or logs
```

### How It Works

```
SETUP (One Time):
1. Store API key in Secrets Manager
   $ aws secretsmanager create-secret \
       --name sentra-api-key \
       --secret-string '{"key":"YOUR_API_KEY"}'

2. CDK grants Lambda permission to read secret
   sentra_api_key_secret.grant_read(lambda_role)

RUNTIME (Every Lambda Invocation):
1. Lambda code calls:
   secrets_client.get_secret_value(SecretId='sentra-api-key')

2. AWS checks: Does Lambda have IAM permission?
   (Yes - CDK granted it)

3. AWS returns:
   {"key":"OXu1KiE3Xia26QQBgmfHe2SLWcVaNGV16QxwkVKf"}

4. Lambda uses key in HTTP request to /validate API
```

### Benefits

- ✅ **Security**: Key not in code or logs
- ✅ **Rotation**: Update key without redeploying Lambda
- ✅ **Auditing**: Secrets Manager logs all access
- ✅ **Best Practice**: AWS-recommended pattern for credentials
- ✅ **Infrastructure as Code**: Managed via CDK

---

## CDK Integration

### Secrets Manager in CDK

```python
# bedrock_agent_stack.py

from aws_cdk import aws_secretsmanager as secretsmanager

# Import existing secret
sentra_api_key_secret = secretsmanager.Secret.from_secret_name_v2(
    self,
    "SentraApiKeySecret",
    secret_name="sentra-api-key"
)

# Grant Lambda permission to read
sentra_api_key_secret.grant_read(lambda_role)

# Lambda environment variable
environment={
    "SENTRA_API_ENDPOINT": "https://iw3limi4k7.execute-api.../v1/validate",
    "SENTRA_API_KEY_SECRET": "sentra-api-key"
}
```

### Lambda Code

```python
# lambda/bedrock_agent_actions/index.py

import boto3
import json

secrets_client = boto3.client('secretsmanager')
_api_key_cache = None  # Cache for performance

def get_sentra_api_key():
    """Fetch API key from Secrets Manager (cached)"""
    global _api_key_cache
    if _api_key_cache:
        return _api_key_cache

    secret_name = os.environ['SENTRA_API_KEY_SECRET']
    response = secrets_client.get_secret_value(SecretId=secret_name)
    secret = json.loads(response['SecretString'])
    _api_key_cache = secret['key']
    return _api_key_cache

def validate_with_sentra(tool_name, tool_params, user_input, session_id):
    """Call Sentra /validate API"""
    headers = {
        "Content-Type": "application/json",
        "x-api-key": get_sentra_api_key()  # ← Fetch from Secrets Manager
    }

    response = http.request(
        'POST',
        os.environ['SENTRA_API_ENDPOINT'],
        body=json.dumps(payload).encode('utf-8'),
        headers=headers,
        timeout=5.0
    )
    return response
```

---

## Complete Flow - End to End

```
USER (in Bedrock Console):
"Show me customers from California"

STEP 1: Bedrock Agent Processes
├─ Bedrock Agent (AWS LLM) understands intent
├─ Decides: query_customers(state="CA")
└─ Invokes Action Group Lambda

STEP 2: Lambda Executes (YOUR CODE)
├─ Extract: tool=query_customers, params={state:"CA"}
├─ Fetch API key from Secrets Manager
│   ├─ boto3.client('secretsmanager').get_secret_value()
│   └─ Returns: "OXu1KiE..."
├─ Call Sentra /validate API
│   POST https://iw3limi4k7.execute-api.../v1/validate
│   Headers: {"x-api-key": "OXu1KiE..."}
├─ Sentra responds: {"decision": "ALLOW"}
├─ Query DynamoDB: sentra-customers table
└─ Return: [John Doe, Jane Smith]

STEP 3: Bedrock Agent Formats
├─ Receives Lambda result
├─ Uses LLM to format naturally
└─ Returns to user

USER SEES:
"I found 2 customers from California: John Doe (john@example.com) and Jane Smith (jane@example.com)"
```

---

## Summary

1. **Two Separate Agents**: Self-hosted (ECS) and Bedrock (external) - both have similar tools but different validation flows

2. **No VPC Issues**: API Gateway is public, Bedrock Lambda has internet access, authentication via API key header

3. **Action Group Lambda**: Required by AWS Bedrock - it's the code that executes tools

4. **Secrets Manager**: Best practice for storing API key - secure, rotatable, auditable

5. **CDK Managed**: All infrastructure (Lambda, IAM, Secrets Manager permissions) in CDK for repeatability

---

## Files Modified

1. ✅ **Lambda Code**: `lambda/bedrock_agent_actions/index.py` (complete with Secrets Manager)
2. ✅ **CDK Stack**: `cdk/stacks/bedrock_agent_stack.py` (added Secrets Manager integration)
3. ✅ **Requirements**: `lambda/bedrock_agent_actions/requirements.txt` (urllib3 dependency)

---

## Next Steps

1. Deploy updated CDK stack (includes Secrets Manager permissions)
2. Test Bedrock Agent end-to-end
3. Verify validation API calls in CloudWatch Logs

---

**Reference**: LLD 09 Section 2.5, Workstream 9 Task 3.2
