# Workstream 7: AI Agents Implementation

**Component**: Customer Query Agent & Payment Agent (LLD 07)
**Timeline**: Week 4-5 (10-12 days)
**Owner**: Backend Team
**Prerequisites**: Workstream 3 (Security Controller), Workstream 6 (Data Model v2)

---

## AWS Configuration

**Critical**: All tasks use:
- **Account ID**: `531109575379`
- **Profile**: `sentra`
- **Region**: `us-east-1`

```bash
# Refresh credentials daily
ada cred update --once

# Verify
export AWS_PROFILE=sentra AWS_REGION=us-east-1
aws sts get-caller-identity
```

---

## Project Structure

```
src/
├── customer-query-agent/
│   ├── app/
│   │   ├── main.py                    # FastAPI app
│   │   ├── api/routes.py              # /query, /action endpoints
│   │   ├── tools/                     # Tool implementations
│   │   │   ├── query_customers.py
│   │   │   ├── query_orders.py
│   │   │   ├── get_customer_by_id.py
│   │   │   └── call_payment_agent.py
│   │   ├── claude_processor.py        # Bedrock integration
│   │   └── security_integration.py    # @secured_tool decorator
│   ├── requirements.txt
│   ├── Dockerfile
│   └── tests/
│
└── payment-agent/
    ├── app/
    │   ├── main.py
    │   ├── api/routes.py
    │   ├── tools/
    │   │   ├── query_refund_status.py
    │   │   ├── process_refund.py
    │   │   └── reverse_refund.py
    │   ├── claude_processor.py
    │   └── security_integration.py
    ├── requirements.txt
    ├── Dockerfile
    └── tests/
```

---

## Milestone 0: Prerequisites and Demo Data (Day 0 - 1 day) ✅ COMPLETE

### Task 0: Verify Infrastructure and Seed Demo Data ✅ COMPLETE

**Part A: Verify Prerequisites**
- DynamoDB tables exist: `sentra-demo-customers`, `sentra-demo-orders`
- Security Controller deployed and healthy at `http://security-controller.sentra.internal:8080`
- ECR repos exist: `sentra/customer-query-agent`, `sentra/payment-agent`
- Bedrock model access: `anthropic.claude-sonnet-4-5-20250929-v1:0` (Claude Sonnet 4.5) enabled in us-east-1
  - **Note**: LLD originally specified `anthropic.claude-3-sonnet-20240229-v1:0` (LEGACY). Use Claude Sonnet 4.5 (ACTIVE) instead.
  - If model access not granted, request via [Bedrock Console](https://console.aws.amazon.com/bedrock/) → Model access → Modify model access

**Part B: Seed Demo Data**
- Create `scripts/seed_demo_data.py`
- Generate 500 customers with fake SSNs (XXX-XX-XXXX format)
- State distribution: CA(150), NY(100), TX(80), FL(70), others(100)
- Generate 500 orders linked to customers ($100-$50k)
- Order statuses: completed(80%), shipped(10%), processing(5%), cancelled(5%)
- Add GSI indexes: `customer-index` on demo-orders, `transaction-index` for rollback

```bash
# Verify Bedrock model access
aws bedrock list-foundation-models \
  --by-provider anthropic \
  --region us-east-1 \
  --profile sentra \
  --query 'modelSummaries[?modelId==`anthropic.claude-sonnet-4-5-20250929-v1:0`]'

# Test model invocation
echo '{"anthropic_version":"bedrock-2023-05-31","max_tokens":100,"messages":[{"role":"user","content":"test"}]}' > /tmp/bedrock_test.json
aws bedrock-runtime invoke-model \
  --model-id anthropic.claude-sonnet-4-5-20250929-v1:0 \
  --body fileb:///tmp/bedrock_test.json \
  --region us-east-1 \
  --profile sentra \
  /tmp/bedrock_response.json
cat /tmp/bedrock_response.json

# Run seeding
python scripts/seed_demo_data.py --customers 500 --orders 500

# Verify DynamoDB data
aws dynamodb scan --table-name sentra-demo-customers --select COUNT --profile sentra
aws dynamodb scan --table-name sentra-demo-orders --select COUNT --profile sentra
```

**Testing**:
- Verify 500 customers, 500 orders in DynamoDB
- Test GSI query: `aws dynamodb query --table-name sentra-demo-orders --index-name customer-index --key-condition-expression "customer_id = :cid"`
- _Requirements: LLD 07 Section 7.2_

---

## Milestone 1: Customer Query Agent - Core Implementation (Days 1-4) ✅ COMPLETE

### Task 1: FastAPI Project Setup and Health Endpoint ✅ COMPLETE

- Create `src/customer-query-agent/` structure
- Create `requirements.txt`: `fastapi==0.109.0`, `uvicorn[standard]==0.27.0`, `boto3==1.34.20`, `pydantic==2.5.3`
- Create `app/main.py` with FastAPI initialization
- Implement `GET /v1/health` endpoint
- Health check verifies: DynamoDB (demo-customers, demo-orders), Security Controller, Bedrock
- Add structured JSON logging
- Test: `uvicorn app.main:app --reload --port 8080`
- Test: `curl http://localhost:8080/v1/health` returns 200
- _Requirements: LLD 07 Section 3.3_

---

### Task 2: Security Controller Integration (@secured_tool Decorator) ✅ COMPLETE

- Create `app/security_integration.py` with `@secured_tool` decorator
- Decorator intercepts tool calls before execution
- Build validation request: `request_id`, `session_id`, `agent_id`, `tool_name`, `tool_params`, `user_input`, `context`
- POST to Security Controller `/v1/validate` with 5s timeout
- If `decision=DENY`, raise `SecurityException` with matched rules
- If `decision=ALLOW`, execute tool function
- Implement retry with exponential backoff (3 attempts)
- Test: Mock Security Controller responses (ALLOW/DENY)
- Test: Verify exception raised on DENY
- _Requirements: LLD 07 Section 5.1, 5.2_

---

### Task 3: Tool Implementations (Customer Query Agent) ✅ COMPLETE

**Tool 1: query_customers**
- Create `app/tools/query_customers.py`
- Add `@secured_tool` decorator
- Accept filters: `state`, `name_contains`, `email_contains`, `limit` (default 100, max 1000)
- Query DynamoDB `sentra-demo-customers` table with scan + filter
- Return list of customer records
- Test: Query with `{"state": "CA"}` returns CA customers only

**Tool 2: query_orders**
- Create `app/tools/query_orders.py`
- Add `@secured_tool` decorator
- Accept filters: `customer_id`, `status`, `min_amount`, `max_amount`, `limit`
- Use GSI `customer-index` for customer_id queries
- Test: Query orders for specific customer

**Tool 3: get_customer_by_id**
- Create `app/tools/get_customer_by_id.py`
- Add `@secured_tool` decorator
- DynamoDB get_item by `customer_id`
- Return customer record or None
- Test: Get customer "C001" returns record

**Tool 4: call_payment_agent** (Inter-Agent Communication)
- Create `app/tools/call_payment_agent.py`
- Add `@secured_tool` decorator
- POST to `http://payment-agent.sentra.internal:8080/v1/agents/payment/action`
- Pass through `session_id`, add `parent_request_id` to context
- Test: Mock payment agent response

**Testing**:
- Unit tests for each tool with mocked DynamoDB
- Integration tests with real DynamoDB (dev environment)
- Coverage target: >80%
- _Requirements: LLD 07 Section 3.5_

---

### Task 4: Bedrock Claude Integration ✅ COMPLETE

- Create `app/claude_processor.py` with `process_with_claude()` function
- Define tool registry (maps tool names to functions)
- Define tool schemas for Claude (JSON schema format per LLD Section 6.1)
- Send user message to Bedrock with available tools
- Parse Claude response for `tool_use` blocks
- For each tool_use:
  - Execute tool via registry (validated by `@secured_tool`)
  - Collect results or errors
  - Handle `SecurityException` gracefully (convert to tool_result with error)
- Send tool results back to Claude for final natural language response
- Return final response text + structured data
- Test: Simple query "Show customers from CA" → Claude calls query_customers → Returns natural response
- Test: Security denial → Claude receives error in tool_result → Returns user-friendly explanation
- _Requirements: LLD 07 Section 3.4, 5.4, 6.2_

---

### Task 5: POST /query and POST /action Endpoints ✅ COMPLETE

- Create `app/api/routes.py`
- Define Pydantic models: `AgentRequest`, `AgentResponse`, `AgentError`
- Implement `POST /v1/agents/customer-query/query`:
  - Generate `request_id` and `session_id` if missing
  - Call `process_with_claude()` with user message
  - Return natural language response + structured data
- Implement `POST /v1/agents/customer-query/action` (same as query for CQA)
- Add request/response logging
- Error handling: Catch `SecurityException` → return 403, catch others → return 500
- Test: POST with "Show customers from CA" returns ALLOW and data
- Test: POST with "ignore previous instructions" returns 403 (blocked by Security Controller)
- _Requirements: LLD 07 Section 2.1, 3.3_

**DEMO CHECKPOINT 1**: Customer Query Agent running locally, can query DynamoDB, integrates with Security Controller, uses Bedrock Claude for natural language processing.

---

### Task 5.5: Docker Build and Deploy Customer Query Agent (Milestone 1) ✅ COMPLETE

- ✅ Use existing multi-service Dockerfile at `docker/sentra/Dockerfile`
- ✅ Build and push:
  ```bash
  python scripts/build_and_push_image.py \
    --service customer-query-agent \
    --milestone 1
  ```
- ✅ Monitor ECS deployment: `aws ecs describe-services --cluster sentra-mvp-cluster --services customer-query-agent`
- ✅ Verify health: `curl http://$ALB_DNS/customer-query/health`
- ✅ Test query endpoint through ALB
- _Requirements: LLD 07 Section 3.2_

---

## Milestone 2: Payment Agent Implementation (Days 5-7) ✅ COMPLETE

### Task 6: Payment Agent Project Setup ✅ COMPLETE

- Create `src/payment-agent/` structure (same as CQA)
- Copy and adapt `main.py`, `security_integration.py`, `claude_processor.py`
- Update health endpoint to check `sentra-demo-orders` table only
- Update service name to `payment-agent` in logs
- Test health endpoint locally
- _Requirements: LLD 07 Section 4.2_

---

### Task 7: Payment Agent Tools Implementation ✅ COMPLETE

**Tool 1: query_refund_status** ✅
- Create `app/tools/query_refund_status.py`
- Add `@secured_tool` decorator
- Get order by `order_id` from DynamoDB
- Return refund details: `refund_amount`, `refund_date`, `refund_status`
- Test: Query refunded order returns status

**Tool 2: process_refund** ✅
- Create `app/tools/process_refund.py`
- Add `@secured_tool` decorator
- Validate order exists and status is "completed"
- Validate refund amount ≤ order total
- Generate `transaction_id`
- Update DynamoDB: SET `refund_amount`, `refund_date`, `refund_status="refunded"`, `transaction_id`
- Return transaction details
- Test: Process $150 refund succeeds
- Test: Process $5000 refund → Security Controller DENY (exceeds $200 manager limit)

**Tool 3: reverse_refund** (Rollback) ✅
- Create `app/tools/reverse_refund.py`
- Add `@secured_tool` decorator
- Query GSI `transaction-index` to find order by `transaction_id`
- Update order: REMOVE refund fields, SET `refund_status="refund_reversed"`, add `rollback_reason`, `rollback_date`
- Test: Reverse refund updates order status

**Testing**:
- Unit tests for all tools
- Integration tests with Security Controller
- Test manager limit policy ($200 refund limit)
- Coverage target: >80%
- _Requirements: LLD 07 Section 4.4_

---

### Task 8: Payment Agent API Endpoints ✅ COMPLETE

- ✅ Implement `POST /v1/agents/payment/query` (read operations)
- ✅ Implement `POST /v1/agents/payment/action` (write operations like refunds)
- ✅ Both endpoints use same Claude processing pipeline
- ✅ Test: Query refund status
- ✅ Test: Process refund under limit (succeeds)
- ✅ Test: Process refund over limit (denied by Security Controller)
- ✅ Test: Verify natural language denial explanation from Claude
- _Requirements: LLD 07 Section 4.3_

**DEMO CHECKPOINT 2**: Payment Agent running locally, can process refunds, validates with Security Controller, enforces $200 manager limit policy.

---

### Task 8.5: Docker Build and Deploy Payment Agent (Milestone 2) ✅ COMPLETE

- ✅ Build and push:
  ```bash
  python scripts/build_and_push_image.py \
    --service payment-agent \
    --milestone 1
  ```
- Monitor ECS deployment
- Verify health through ALB
- Test refund processing through ALB
- Test policy enforcement (refund limit)
- _Requirements: LLD 07 Section 4.2_

---

## Milestone 3: Multi-Agent Workflow & Testing (Days 8-10)

### Task 9: Multi-Agent Workflow Testing ✅ COMPLETE

**Test Files Created**:
- `tests/integration/test_multi_agent_workflow.py` - Pytest integration tests
- `scripts/test_multi_agent_workflow.sh` - Shell script for manual testing

**Test Inter-Agent Communication**:
- Customer Query Agent calls Payment Agent via `call_payment_agent` tool
- Test flow:
  1. User asks CQA: "Process refund of $150 for order ORD-12345"
  2. CQA calls `call_payment_agent` tool
  3. Security Controller validates CQA → Payment Agent call (checks `allowed_agents`)
  4. Payment Agent processes refund
  5. Payment Agent validates with Security Controller (checks refund limit)
  6. Response flows back to CQA → User

**Acceptance Criteria**:
- ✅ CQA successfully invokes Payment Agent
- ✅ Both agents validate with Security Controller independently
- ✅ Refund under $200 succeeds
- ✅ Refund over $200 denied
- ✅ Session context passed through agents
- ✅ Audit logs show both agent calls

- _Requirements: LLD 07 Section 3.5 (Tool 4), Section 4_

---

### Task 10: Natural Language Error Handling ✅ COMPLETE

**Already Implemented in claude_processor.py**:
- ✅ Security Controller denials sent as `tool_result` with `is_error: True`
- ✅ Claude receives denial details (reason, matched_rules, user_friendly_hint)
- ✅ Claude generates natural language explanation
- Test cases:
  - Prompt injection → "I cannot process that request as it appears to contain instructions that could compromise security."
  - Unauthorized tool → "I don't have permission to perform that action."
  - Refund over limit → "I'm unable to process that $5000 refund because it exceeds the $200 authorization limit for managers. Refunds over $200 require director approval. Would you like me to create an approval request?"

**Acceptance Criteria**:
- ✅ No technical error messages shown to users
- ✅ Claude provides helpful alternative suggestions
- ✅ Security policies remain enforced
- ✅ Audit logs still capture denial details

- _Requirements: LLD 07 Section 5.4_

---

### Task 11: End-to-End Integration Testing ✅ COMPLETE

**Test File Created**: `tests/integration/test_e2e_agents.py`

**Test Suite 1: Customer Query Agent**
- Test all 4 tools independently
- Test natural language queries (various phrasings)
- Test tool sequence validation (if required)
- Test rate limiting (max_calls_per_minute)
- Test trust score updates
- Test Sigma rule detection (prompt injection)

**Test Suite 2: Payment Agent**
- Test all 3 tools independently
- Test refund limit policy enforcement
- Test rollback capability
- Test natural language refund requests
- Test denial explanations

**Test Suite 3: Multi-Agent**
- Test CQA → Payment Agent communication
- Test session context propagation
- Test cascading denials
- Test audit trail across agents

**Test Suite 4: Error Scenarios**
- DynamoDB unavailable
- Security Controller timeout
- Bedrock API errors
- Invalid tool parameters

**Performance Tests**:
- Agent response latency < 3s (p95)
- Bedrock call latency < 1.5s (p95)
- Concurrent requests (10 req/sec for 60s)

**Acceptance Criteria**:
- ✅ All tests pass with >80% coverage
- ✅ No security policy bypasses
- ✅ Performance targets met
- ✅ Error handling graceful
- ✅ Audit logs complete

- _Requirements: LLD 07 All Sections_

**DEMO CHECKPOINT 3 (FINAL)**: Both agents deployed to ECS, accessible through ALB, multi-agent workflow functional, security policies enforced, audit logs complete.

---

## Milestone 4: Documentation and Handoff (Days 11-12)

### Task 12: Agent Configuration and Deployment Guide ✅ COMPLETE

**Documentation Created:**
- ✅ `docs/ai-agents-deployment.md` - Architecture, env vars, deployment steps, rollback
- ✅ `docs/ai-agents-api-reference.md` - API contract, schemas, error codes, tool schemas
- ✅ `docs/ai-agents-operations.md` - Adding tools, updating policies, monitoring, troubleshooting

- _Requirements: LLD 07 All Sections_

---

### Task 13: CloudWatch Alarms and Metrics ✅ COMPLETE

**CDK Updates in `cdk/stacks/monitoring_stack.py`:**

**Dashboard Widgets Added (6 new widgets):**
- ✅ AI Agents - Request Volume (CQA + Payment Agent)
- ✅ AI Agents - Security Denials
- ✅ AI Agents - Bedrock Latency (p50/p95)
- ✅ AI Agents - Tool Execution Time (p95)
- ✅ AI Agents - Bedrock Token Usage
- ✅ AI Agents - Average Trust Score

**Alarms Created (8 new alarms):**
- ✅ `cqa-health-check-failure` (P0) - CQA health endpoint fails
- ✅ `pa-health-check-failure` (P0) - Payment Agent health fails
- ✅ `ai-agents-high-latency` (P1) - Response time > 5s (p95)
- ✅ `ai-agents-bedrock-errors` (P0) - Bedrock API errors > 5/min
- ✅ `ai-agents-high-denial-rate` (P1) - Denial rate > 30%
- ✅ `ai-agents-tool-errors` (P1) - Tool failures > 10/min
- ✅ `cqa-request-failures` (P1) - CQA request failures > 5/min
- ✅ `pa-request-failures` (P1) - Payment Agent failures > 5/min

**Custom Metrics Namespace:** `Sentra/Agents`
- `RequestsReceived`, `RequestsSucceeded`, `RequestsFailed`
- `SecurityDenials`, `SecurityDenialRate`
- `ToolExecutionTime`, `ToolExecutionErrors`
- `BedrockLatency`, `BedrockErrors`, `BedrockInputTokens`, `BedrockOutputTokens`
- `TrustScoreAverage`, `HealthCheckStatus`, `ResponseLatency`

- _Requirements: LLD 07 Section 10_

---

## Dependencies and Parallel Work

**Prerequisites**:
- Workstream 3 (Security Controller) completed
- Workstream 6 (Data Model v2) completed
- Demo data tables created and seeded

**Can Run in Parallel**:
- Task 6-8 (Payment Agent) after Task 3 completes (independent agents)

**Must Run Sequentially**:
- Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 5.5
- Task 6 → Task 7 → Task 8 → Task 8.5
- Task 9 → Task 10 → Task 11 (testing after both agents deployed)

---

## Estimated Timeline

| Task | Duration | Cumulative |
|------|----------|------------|
| **Milestone 0** | | |
| Task 0 | 1 day | Day 1 |
| **Milestone 1** | | |
| Task 1 | 1 day | Day 2 |
| Task 2 | 1 day | Day 3 |
| Task 3 | 1.5 days | Day 4.5 |
| Task 4 | 1.5 days | Day 6 |
| Task 5 | 1 day | Day 7 |
| Task 5.5 | 0.5 day | Day 7.5 |
| **Checkpoint 1 + Deploy** | - | Day 7.5 |
| **Milestone 2** | | |
| Task 6 | 0.5 day | Day 8 |
| Task 7 | 1.5 days | Day 9.5 |
| Task 8 | 1 day | Day 10.5 |
| Task 8.5 | 0.5 day | Day 11 |
| **Checkpoint 2 + Deploy** | - | Day 11 |
| **Milestone 3** | | |
| Task 9 | 1 day | Day 12 |
| Task 10 | 0.5 day | Day 12.5 |
| Task 11 | 1.5 days | Day 14 |
| **Checkpoint 3 (Final)** | - | Day 14 |
| **Milestone 4** | | |
| Task 12 | 1 day | Day 15 |
| Task 13 | 0.5 day | Day 15.5 |

**Total: ~15.5 days (≈3 weeks)**

---

## Post-Deployment Verification Checklist

```bash
export AWS_PROFILE=sentra AWS_REGION=us-east-1

# 1. Verify both agents running
aws ecs describe-services --cluster sentra-mvp-cluster --services customer-query-agent payment-agent

# 2. Test health endpoints
ALB_DNS=$(aws elbv2 describe-load-balancers --names sentra-alb --query 'LoadBalancers[0].DNSName' --output text)
curl http://$ALB_DNS/customer-query/health
curl http://$ALB_DNS/payment/health

# 3. Test Customer Query Agent
curl -X POST http://$ALB_DNS/v1/agents/customer-query/query \
  -H "Content-Type: application/json" \
  -d '{"message":"Show customers from California","session_id":"test-sess-001"}'

# 4. Test Payment Agent
curl -X POST http://$ALB_DNS/v1/agents/payment/action \
  -H "Content-Type: application/json" \
  -d '{"message":"Check refund status for order ORD-001","session_id":"test-sess-002"}'

# 5. Verify audit logs
aws logs tail /sentra/audit-logs --follow

# 6. Check CloudWatch Metrics
aws cloudwatch get-metric-statistics \
  --namespace Sentra/Agents \
  --metric-name RequestsReceived \
  --dimensions Name=ServiceName,Value=customer-query-agent \
  --start-time $(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Sum
```

---

**Next Workstream**: Dashboard Integration (Workstream 4) - Connect chat interface to agents

**Integration Point**: Dashboard chat tab will call agent `/query` and `/action` endpoints via API Gateway
