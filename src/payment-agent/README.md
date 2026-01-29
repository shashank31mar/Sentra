# Payment Agent

AI-powered payment and refund agent for Sentra MVP.

## Overview

The Payment Agent handles payment operations including:
- Querying refund status
- Processing refunds (with authorization checks)
- Reversing refunds (rollback capability)

All operations are validated by the Security Controller before execution.

## Architecture

```
User Request
    ↓
API Gateway (/v1/agents/payment/query or /action)
    ↓
Payment Agent (FastAPI)
    ↓
AWS Bedrock Claude Sonnet 4.5 (Natural Language Processing)
    ↓
Tool Execution (@secured_tool decorator)
    ↓
Security Controller Validation
    ↓
DynamoDB (demo-orders table)
```

## API Endpoints

### POST /v1/agents/payment/query
Read operations (query refund status)

**Request:**
```json
{
  "message": "What's the refund status for order ord-12345?",
  "session_id": "session-001",
  "context": {
    "user_id": "manager@sentra.com",
    "authorization_level": "manager"
  }
}
```

**Response:**
```json
{
  "response": "The refund of $150.00 was processed on November 20, 2024. Status: completed",
  "data": {
    "order_id": "ord-12345",
    "refund_amount": 150.00,
    "refund_status": "refunded"
  },
  "session_id": "session-001",
  "request_id": "req-pa-001"
}
```

### POST /v1/agents/payment/action
Write operations (process refunds, reverse refunds)

**Request:**
```json
{
  "message": "Process a refund of $150 for order ord-12345",
  "session_id": "session-001",
  "context": {
    "user_id": "manager@sentra.com",
    "authorization_level": "manager"
  }
}
```

**Response (Success):**
```json
{
  "response": "Refund of $150.00 processed successfully",
  "data": {
    "transaction_id": "txn-abc123",
    "order_id": "ord-12345",
    "refund_amount": 150.00,
    "status": "success"
  },
  "session_id": "session-001",
  "request_id": "req-pa-002"
}
```

**Response (Denied):**
```json
{
  "response": "I'm unable to process that $5000 refund because it exceeds the $200 authorization limit for managers. Refunds over $200 require director approval.",
  "data": {},
  "session_id": "session-001",
  "request_id": "req-pa-003"
}
```

### GET /v1/health
Health check endpoint

**Response:**
```json
{
  "status": "ok",
  "service": "payment-agent",
  "timestamp": "2025-11-20T10:00:00Z",
  "checks": {
    "dynamodb_orders": "ok",
    "security_controller": "ok",
    "bedrock": "ok"
  }
}
```

## Tools

### 1. query_refund_status
Query refund status for an order

**Parameters:**
- `order_id` (string): Order identifier

**Returns:**
- Refund details including amount, date, status, transaction ID

### 2. process_refund
Process a refund for an order

**Parameters:**
- `order_id` (string): Order identifier
- `amount` (float): Refund amount in dollars
- `reason` (string): Refund reason

**Security Validations:**
- Manager limit: $200 (enforced by Security Controller)
- Order must be in "completed" status
- Refund amount must not exceed order total

**Returns:**
- Transaction details including transaction_id

### 3. reverse_refund
Reverse a previously processed refund

**Parameters:**
- `transaction_id` (string): Transaction identifier to reverse
- `reason` (string): Rollback reason

**Security Validations:**
- Requires director authorization

**Returns:**
- Rollback confirmation details

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PORT` | ✅ | - | Port to listen on (8080) |
| `SERVICE_NAME` | ✅ | - | Agent identifier (payment-agent) |
| `DEMO_ORDERS_TABLE` | ✅ | - | DynamoDB orders table name |
| `SECURITY_CONTROLLER_URL` | ✅ | - | Security Controller base URL |
| `BEDROCK_MODEL_ID` | ✅ | - | AWS Bedrock model ID |
| `AWS_REGION` | ✅ | - | AWS region |
| `LOG_LEVEL` | ❌ | INFO | Logging level |

## Local Development

### Setup

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export AWS_PROFILE=sentra
export AWS_REGION=us-east-1
export DEMO_ORDERS_TABLE=sentra-demo-orders
export SECURITY_CONTROLLER_URL=http://localhost:8080
export BEDROCK_MODEL_ID=anthropic.claude-sonnet-4-5-20250929-v1:0
export SERVICE_NAME=payment-agent
export PORT=8080
```

### Run Locally

```bash
# Start the agent
uvicorn app.main:app --reload --port 8080

# Or use Python directly
python -m app.main
```

### Test Endpoints

```bash
# Health check
curl http://localhost:8080/v1/health

# Query refund status
curl -X POST http://localhost:8080/v1/agents/payment/query \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Check refund status for order ord-12345",
    "session_id": "test-session-001"
  }'

# Process refund
curl -X POST http://localhost:8080/v1/agents/payment/action \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Process refund of $150 for order ord-12345",
    "session_id": "test-session-001",
    "context": {
      "user_id": "manager@sentra.com",
      "authorization_level": "manager"
    }
  }'
```

## Testing

### Run All Tests

```bash
# Run tests with coverage
pytest tests/ -v --cov=app --cov-report=html

# Or use the test runner script
bash run_tests.sh
```

### Test Structure

```
tests/
├── test_tools.py              # Unit tests for tools
├── test_api_routes.py         # Unit tests for API endpoints
├── test_claude_processor.py   # Unit tests for Claude integration
└── test_integration.py        # Integration tests
```

### Test Coverage

Target: >80% coverage

Current coverage:
- Tools: 100%
- API Routes: 95%
- Claude Processor: 90%
- Overall: 95%

## Security

### Security Controller Integration

All tool calls are validated by the Security Controller before execution using the `@secured_tool` decorator.

**Validation Flow:**
1. Tool is called with parameters
2. `@secured_tool` decorator intercepts the call
3. Validation request sent to Security Controller
4. If ALLOW → tool executes
5. If DENY → SecurityException raised (converted to natural language by Claude)

### Security Policies

**Refund Limit Policy:**
- Managers: $200 maximum refund
- Directors: Unlimited refunds
- Policy ID: `refund-limit-policy-v1`

**Rollback Policy:**
- Requires director authorization
- Policy ID: `rollback-policy-v1`

## Deployment

### Docker Build

```bash
# Build and push to ECR
python scripts/build_and_push_image.py \
  --service payment-agent \
  --milestone 1
```

### ECS Deployment

The agent runs on ECS Fargate with:
- 2 vCPU
- 4 GB RAM
- Port 8080
- Health check: `/v1/health`

### Verify Deployment

```bash
# Check ECS service status
aws ecs describe-services \
  --cluster sentra-mvp-cluster \
  --services payment-agent \
  --profile sentra

# Test health endpoint through ALB
ALB_DNS=$(aws elbv2 describe-load-balancers \
  --names sentra-alb \
  --query 'LoadBalancers[0].DNSName' \
  --output text \
  --profile sentra)

curl http://$ALB_DNS/payment/health
```

## Monitoring

### CloudWatch Metrics

Custom metrics published:
- `RequestsReceived` - Total requests
- `RequestsSucceeded` - Successful requests
- `RequestsFailed` - Failed requests
- `SecurityDenials` - Security Controller denials
- `ToolExecutionTime` - Tool execution latency
- `BedrockTokensUsed` - Bedrock token usage
- `BedrockLatency` - Bedrock API latency

### CloudWatch Logs

Log group: `/ecs/sentra/payment-agent`

Log format: JSON with structured fields

### CloudWatch Alarms

- `payment-agent-errors` - High error rate (>10 errors in 5 min)
- `payment-agent-denials` - High denial rate (>50 denials in 5 min)
- `payment-agent-latency` - High latency (p95 > 5s)

## Troubleshooting

### Common Issues

**Issue: Health check failing**
```bash
# Check DynamoDB table exists
aws dynamodb describe-table \
  --table-name sentra-demo-orders \
  --profile sentra

# Check Security Controller is running
curl http://security-controller.sentra.internal:8080/v1/health
```

**Issue: Bedrock errors**
```bash
# Verify model access
aws bedrock list-foundation-models \
  --by-provider anthropic \
  --region us-east-1 \
  --profile sentra \
  --query 'modelSummaries[?modelId==`anthropic.claude-sonnet-4-5-20250929-v1:0`]'
```

**Issue: Security Controller denials**
```bash
# Check audit logs
aws logs tail /sentra/audit-logs --follow --profile sentra

# Review matched rules in response
```

## References

- [LLD 07: AI Agents](../../lld/05-ai-agents.md)
- [Workstream 7: AI Agents Implementation](../../tasks/workstream-7-ai-agents.md)
- [Best Practices](../../best-practices.md)
