# Workstream 3: Security Controller Implementation

**Component**: Security Controller (LLD 03)
**Timeline**: Week 2-3 (10-12 days)
**Owner**: Backend Team
**Prerequisites**: Workstream 1 (Infrastructure) completed

---

## AWS Configuration

**Critical**: All tasks must use these AWS settings:

- **AWS Account ID**: `531109575379`
- **AWS Profile**: `sentra` (credentials configured in `~/.aws/credentials`)
- **Region**: `us-east-1` (IAD - Northern Virginia)

**Environment Setup**:
```bash
# Refresh AWS credentials (run this daily or when credentials expire)
ada cred update --once

# Verify AWS profile configuration
export AWS_PROFILE=sentra
aws sts get-caller-identity  # Should show account 531109575379

# Verify region
export AWS_REGION=us-east-1
```

---

## Project Structure

All Security Controller code goes in:
```
src/security-controller/
├── app/
│   ├── main.py                     # FastAPI app entry point
│   ├── api/
│   │   ├── routes.py               # REST API endpoints (HTTP layer only)
│   │   └── models.py               # Pydantic schemas
│   ├── services/                   # Business logic orchestrators
│   │   ├── validation_service.py   # Validation pipeline orchestrator
│   │   ├── health_service.py       # Health check logic
│   │   └── __init__.py
│   ├── validators/                 # Individual validation components
│   │   ├── trust_checker.py        # Task 4 - Trust score validation
│   │   ├── policy_engine.py        # Task 5 - Policy evaluation
│   │   ├── sigma_engine.py         # Task 6 - Threat detection
│   │   ├── context_validator.py    # Task 7 - Tool sequence validation
│   │   ├── abuse_detector.py       # Task 8 - Rate limiting
│   │   └── __init__.py
│   └── utils/
│       ├── session_manager.py      # DynamoDB session CRUD
│       ├── rollback_coordinator.py # Manual rollback logic
│       ├── audit_logger.py         # CloudWatch logging
│       └── helpers.py              # Utility functions
├── requirements.txt
├── requirements-test.txt
├── Dockerfile
└── tests/
    ├── unit/                       # Unit tests for each component
    └── integration/                # Integration tests
```

---

## Milestone 0: Prerequisites and Configuration Setup (Day 0 - 0.5 day) ✅ COMPLETED

### Task 0: Configuration Files and Sigma Rules Setup ✅ COMPLETED

**Purpose**: Create configuration files required by Security Controller and upload Sigma rules to S3

**Part A: Create Configuration Files**
- Create `config/` directory in project root
- Create `config/agent_policies.yaml` with simple format per LLD Section 7.3:
  ```yaml
  customer-query-agent:
    allowed_tools:
      - query_customers
      - query_orders
      - query_with_limit
    allowed_agents:
      - payment-agent
    max_calls_per_minute: 30

  payment-agent:
    allowed_tools:
      - check_order
      - process_refund
      - reverse_refund
    allowed_agents: []
    max_calls_per_minute: 15
  ```
- Create `config/tool_requirements.yaml` per LLD Section 7.2:
  ```yaml
  process_refund:
    requires:
      - check_order

  reverse_refund:
    requires:
      - process_refund
  ```

**Part B: Upload Sigma Rules to S3**
- Verify Sigma rule exists: `sample-artifacts/sigma_rules/llm/prompt_injection_basic.yaml`
- Upload to S3 bucket:
  ```bash
  export AWS_PROFILE=sentra
  aws s3 cp sample-artifacts/sigma_rules/ \
    s3://sentra-mvp-artifacts/sigma_rules/ \
    --recursive \
    --region us-east-1
  ```
- Verify upload:
  ```bash
  aws s3 ls s3://sentra-mvp-artifacts/sigma_rules/llm/ --region us-east-1
  ```

**Part C: Verify Prerequisites from Workstream 1**
- Verify DynamoDB tables exist:
  - `sentra-session-context`
  - `sentra-policies`
  - `sentra-demo-orders`
- Verify S3 bucket exists: `sentra-mvp-artifacts`
- Verify ECR repository exists: `sentra/security-controller`
- Verify ECS cluster exists: `sentra-mvp-cluster`

**Testing**:
- Test: Read config files with Python: `yaml.safe_load(open('config/agent_policies.yaml'))`
- Test: Verify S3 Sigma rule accessible: `aws s3 cp s3://sentra-mvp-artifacts/sigma_rules/llm/prompt_injection_basic.yaml -`
- Verify: All DynamoDB tables accessible
- _Requirements: LLD 03 Section 7_

**Note**: The `sample-artifacts/policies/refund-limit-policy-v1.yaml` is a Phase 2 advanced policy format and NOT used in MVP. MVP uses simple agent-level policies in `config/agent_policies.yaml`.

---

## Milestone 1: Core API and Session Management (Days 1-3)

### Task 1: FastAPI Project Setup and Health Endpoint ✅ COMPLETED

- Create `src/security-controller/` directory structure
- Initialize Python virtual environment with Python 3.11+
- Create `requirements.txt` with dependencies: `fastapi==0.109.0`, `uvicorn[standard]==0.27.0`, `pydantic==2.5.3`, `boto3==1.34.20`, `pyyaml==6.0.1`
- Install dependencies: `pip install -r requirements.txt`
- Create `app/main.py` with FastAPI app initialization
- Implement `GET /health` endpoint with dependency checks (DynamoDB, S3, CloudWatch)
- Health check should verify connectivity to: `sentra-session-context` table, `sentra-policies` table, S3 bucket `sentra-mvp-artifacts`
- Return health status: `{"status": "healthy", "dependencies": {...}, "uptime_seconds": ...}`
- Configure CORS middleware for API Gateway integration
- Add structured JSON logging with `python-json-logger`
- **Error Handling**: Implement fail-secure error handling per LLD Section 8 (catch all exceptions, return appropriate status codes)
- Test: Run locally with `uvicorn app.main:app --reload --port 8080`
- Test: Curl `http://localhost:8080/v1/health` returns 200 OK
- Verify: Health check correctly identifies when DynamoDB is unreachable
- _Requirements: LLD 03 Section 2.1, 4.2, 8.1_

---

### Task 1.5: Configuration Seeding Script ✅ COMPLETED

- Create `scripts/seed_policies.py` to load agent policies from YAML into DynamoDB
- Read `config/agent_policies.yaml` (git-versioned policy definitions)
- Parse YAML and transform into DynamoDB items with schema:
  - `policy_id`: Generated (e.g., "pol-customer-query-agent-001")
  - `agent_id`: From YAML key
  - `allowed_tools`: List of tool names
  - `allowed_agents`: List of agent IDs
  - `max_calls_per_minute`: Rate limit
  - `is_active`: true
  - `created_at`, `updated_at`: Current timestamp
- Batch write to DynamoDB `sentra-policies` table
- Add `--force` flag to overwrite existing policies
- Add `--dry-run` flag to preview changes without writing
- **Error Handling**: Validate YAML schema before writing, rollback on partial failure
- Test: Run `python scripts/seed_policies.py` and verify policies in DynamoDB
- Test: Run with `--dry-run` and verify no changes made
- Verify: Query DynamoDB using GSI `agent_id-index` returns correct policy
- _Requirements: LLD 03 Section 3.3, 7.3_

---

### Task 2: Session Manager with Atomic Updates ✅ COMPLETED

- Create `utils/session_manager.py` with `SessionManager` class
- Implement `get_or_create_session(session_id, user_id, agent_id)` method
- Query DynamoDB `sentra-session-context` table for existing session
- If not found, create new session with: `trust_score=100.0`, `quarantine_status="active"`, `total_requests=0`, TTL=24 hours
- Implement `update_trust_score_deny(session_id, penalty, violation_type)` method
- Use DynamoDB atomic UpdateExpression: `SET trust_score = trust_score + :penalty` (penalty is negative)
- Reset `consecutive_allows = 0` and increment `deny_count`
- Update `quarantine_status` based on new trust_score: <10="suspended", 10-39="quarantined", 40-69="warning", ≥70="active"
- Implement `update_trust_score_allow(session_id, tool_name)` method
- Atomic increment: `consecutive_allows = consecutive_allows + 1`
- Check if threshold reached (10, 12, or 15 based on trust_score) for trust score increment
- If threshold reached, increment trust_score by amount (2, 3, or 5) and reset consecutive_allows
- Cap trust_score at 100
- **Tool History Management**: Use Python list slicing to keep only last 10 tools in `tool_history` (append new tool, then `tool_history = tool_history[-10:]`)
- Implement `manual_quarantine(session_id, reason, operator_id)` method
- Update quarantine_status to "quarantined" with reason and operator_id
- Add helper methods: `_get_consecutive_allows_required()`, `_get_increment_amount()`, `_update_quarantine_status()`
- **Error Handling**: Wrap all DynamoDB operations in try-except, log errors, raise custom exceptions (SessionNotFoundError, SessionUpdateError)
- Test: Create unit tests for all methods with mocked DynamoDB
- Test: Verify atomic updates work correctly (no race conditions)
- Test: Verify trust score asymmetric recovery (harder to recover at lower scores)
- Test: Verify tool_history truncation works (keeps only last 10)
- _Requirements: LLD 03 Section 12, 6.1, 8.1_

---

### Task 3: POST /validate Endpoint (Basic Structure) ✅ COMPLETED

- Create `api/routes.py` with `/validate` endpoint
- Define Pydantic request model `ValidationRequest` with fields: `request_id`, `session_id`, `agent_id`, `tool_name`, `tool_params`, `user_input`, `timestamp`, `operation_type`
- Define Pydantic response models: `ValidationResponse` (ALLOW), `ValidationDenyResponse` (DENY)
- Implement basic validation pipeline structure (5 steps):
  1. Trust Score Check (placeholder - returns PASS)
  2. Policy Engine (placeholder - returns PASS)
  3. Sigma Rule Engine (placeholder - returns PASS)
  4. Context Validator (placeholder - returns PASS)
  5. Abuse Detector (placeholder - returns PASS)
- Return ALLOW response with trust_score and latency_ms
- **Action ID Generation**: For reversible actions (operation_type="WRITE" and tool_name in ["process_refund"]), generate action_id: `act-{tool_name}-{timestamp}-{random_hex}`
- Include action_id in response for reversible actions
- Add request/response logging
- **Error Handling**: Wrap entire pipeline in try-except, return DENY on unexpected errors per LLD Section 8.1
- Test: POST to `/validate` with sample request returns ALLOW
- Test: Verify request_id is logged for traceability
- Test: Verify action_id is generated for process_refund tool
- Verify: Response includes trust_score from session
- _Requirements: LLD 03 Section 3, 4.1, 8.1, 11.2_

**DEMO CHECKPOINT 1**: Basic Security Controller running with health check and skeleton validation endpoint. Can create sessions and track trust scores.

---

### Task 3.5: Docker Build and Deploy Milestone 1 ✅ COMPLETED

**Purpose**: Deploy Milestone 1 code to ECS for incremental testing

**Note**: Dockerfile already exists at `docker/sentra/Dockerfile` (multi-service Dockerfile). The build script `scripts/build_and_push_image.py` handles all build and deployment steps automatically.

**Build and Push**

- Build and push using the script:
  ```bash
  # Build, tag, and push milestone 1 (also updates :latest)
  python scripts/build_and_push_image.py \
    --service security-controller \
    --milestone 1
  ```

- Test image locally (optional):
  ```bash
  # Build without pushing
  python scripts/build_and_push_image.py \
    --service security-controller \
    --milestone 1 \
    --no-push
  
  # Run locally
  docker run -p 8080:8080 \
    -e AWS_REGION=us-east-1 \
    -e AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID \
    -e AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY \
    sentra/security-controller:milestone-1
  
  # Note: Image tag is milestone-1 (generated from --milestone 1)
  
  # Test health endpoint
  curl http://localhost:8080/v1/health
  ```

**Monitor ECS Deployment**

- ECS service automatically detects new `:latest` tag and performs rolling update
- Monitor deployment:
  ```bash
  aws ecs describe-services \
    --cluster sentra-mvp-cluster \
    --services security-controller \
    --region us-east-1 \
    --profile sentra \
    --query 'services[0].deployments' \
    --output table
  ```
- Wait for PRIMARY deployment to reach RUNNING status (~2-3 minutes)

**Verify Deployment**

- Get ALB DNS and test:
  ```bash
  ALB_DNS=$(aws elbv2 describe-load-balancers \
    --names sentra-alb \
    --query 'LoadBalancers[0].DNSName' \
    --output text \
    --region us-east-1 \
    --profile sentra)
  
  curl http://$ALB_DNS/v1/health
  # Should return: {"status": "healthy", "dependencies": {...}}
  ```

- Check CloudWatch Logs:
  ```bash
  aws logs tail /ecs/sentra/security-controller --follow --region us-east-1 --profile sentra
  ```

**Rollback Plan**

- If deployment fails, rollback to previous milestone:
  ```bash
  # Rollback to milestone 1 (force push to update :latest)
  python scripts/build_and_push_image.py \
    --service security-controller \
    --milestone 1 \
    --force
  ```

- Test: Verify ECS task is running and healthy
- Test: Verify CloudWatch Logs showing container logs
- Verify: Health check returns 200 OK through ALB at `/v1/health`
- _Requirements: LLD 03 Section 2.3_

---

## Milestone 2: Validation Pipeline Implementation (Days 4-7)

### Task 4: Trust Score Check Validator ✅ COMPLETED

- Create `validators/trust_checker.py` with `TrustChecker` class
- Implement `check(session, request)` method
- Load session from SessionManager
- Check if `quarantine_status == "suspended"` (trust_score < 10)
  - If suspended, return DENY with reason "Session suspended due to low trust score"
- Check if `quarantine_status == "quarantined"` AND `operation_type == "WRITE"`
  - If quarantined + write operation, return DENY with reason "Write operations blocked while quarantined"
- If checks pass, return PASS
- **Error Handling**: Wrap in try-except, return DENY on errors (fail-secure)
- Integrate into validation pipeline in `routes.py` (Step 1)
- **Unit Tests**: Create `tests/unit/test_trust_checker.py`
  - Test: Suspended session (trust_score=5) returns DENY for all operations
  - Test: Quarantined session (trust_score=30) allows READ but denies WRITE
  - Test: Active session (trust_score=80) allows all operations
  - Test: Error handling returns DENY on exceptions
  - Coverage target: >80%
- _Requirements: LLD 03 Section 3.1, 6.2, 8.1_

---

### Task 5: Policy Engine Implementation ✅ COMPLETED

- Create `validators/policy_engine.py` with `PolicyEngine` class
- Implement `get_agent_policy(agent_id)` method
- Query DynamoDB `sentra-policies` table using GSI `agent_id-index`
- Filter for `is_active = true`
- **Error Handling**: If no policy found, raise PolicyNotFoundError (fail-secure: deny if policy missing)
- Return `AgentPolicy` object with `allowed_tools`, `allowed_agents`, `max_calls_per_minute`
- Implement `validate(policy, request)` method
- Check if `tool_name` is in `policy.allowed_tools`
  - If not, return DENY with reason "Tool '{tool_name}' not authorized for {agent_id}"
- If `tool_name == "invoke_agent"`, check if target agent is in `policy.allowed_agents`
  - If not, return DENY with reason "Agent '{agent_id}' cannot invoke '{target_agent}'"
- If checks pass, return ALLOW
- **Error Handling**: Wrap validation logic in try-except, return DENY on errors
- Integrate into validation pipeline (Step 2)
- **Unit Tests**: Create `tests/unit/test_policy_engine.py`
  - Use moto to mock DynamoDB
  - Test: Authorized tool (query_customers in allowed_tools) returns ALLOW
  - Test: Unauthorized tool (process_refund NOT in allowed_tools) returns DENY
  - Test: Authorized agent invocation returns ALLOW
  - Test: Unauthorized agent invocation returns DENY
  - Test: Missing policy (agent_id not found) returns DENY (fail-secure)
  - Test: Error handling returns DENY on exceptions
  - Coverage target: >80%
- _Requirements: LLD 03 Section 3.3, 8.1_

---

### Task 6: Sigma Rule Engine Implementation with In-Memory Cache ✅ COMPLETED

- Create `validators/sigma_engine.py` with `SigmaEngine` class
- **Sample Sigma Rule Reference**: Use format from `sample-artifacts/sigma_rules/llm/prompt_injection_basic.yaml` (see LLD Section 3.2.1)
- Implement `__init__(s3_bucket, s3_prefix, cache_ttl_seconds)` constructor
  - `cache_ttl_seconds` defaults to 300 (5 minutes) but configurable via env var `SIGMA_RULES_CACHE_TTL_SECONDS`
  - Initialize `rules_cache = None` and `cache_timestamp = 0`
- Implement `load_rules_from_s3()` method with in-memory caching:
  - Check if cache is valid: `(current_time - cache_timestamp) < cache_ttl_seconds`
  - If valid, return cached rules (skip S3 call)
  - If expired, load from S3 `s3://sentra-mvp-artifacts/sigma_rules/llm/`
  - List all `.yaml` files in prefix
  - Download and parse each file using `yaml.safe_load()`
  - Parse Sigma rule format: extract patterns from `detection` sections (see `_parse_sigma_rule()` method)
  - Update cache and timestamp
  - **Error Handling**: If S3 fails and cache exists, use stale cache (fail-open for availability). If no cache, raise SigmaRulesLoadError (fail-secure)
- Implement `_parse_sigma_rule(rule_data)` method:
  - Extract patterns from `detection` dict (all fields with `|contains`)
  - Extract threat_type from `tags` (e.g., "llm.prompt_injection" → "PROMPT_INJECTION")
  - Return SigmaRule object with: id, title, patterns, severity, threat_type, action
- Implement `match_rules(user_input)` method:
  - Load rules (from cache or S3)
  - Convert user_input to lowercase
  - For each rule, check if any pattern matches (case-insensitive substring match)
  - If match found, return DENY with: `threat_type`, `matched_rule`, `matched_pattern`, `severity`, `reason`
  - If no matches, return PASS
  - **Error Handling**: Wrap in try-except, return DENY on errors (fail-secure)
- Integrate into validation pipeline (Step 3)
- **Unit Tests**: Create `tests/unit/test_sigma_engine.py`
  - Use moto to mock S3
  - Test: Prompt injection detected ("ignore previous instructions") returns DENY
  - Test: Legitimate input ("show customers from CA") returns PASS
  - Test: Cache hit - second request uses cached rules (verify no S3 call)
  - Test: Cache expiration - after TTL, rules reloaded from S3
  - Test: Stale cache fallback - S3 error with valid cache uses stale cache
  - Test: No cache + S3 error returns DENY (fail-secure)
  - Test: Rule parsing extracts patterns correctly from detection sections
  - Coverage target: >80%
- _Requirements: LLD 03 Section 3.2.1, 8.1_

---

### Task 7: Context Validator Implementation ✅ COMPLETED

- Create `validators/context_validator.py` with `ContextValidator` class
- Load tool requirements from config file `config/tool_requirements.yaml`
- Example: `process_refund: {requires: ["check_order"]}`
- Implement `validate_sequence(session, request)` method
- Check if `tool_name` has requirements in config
- If yes, extract `tool_history` from session (last 10 tools)
- Check if ALL required tools are present in tool_history
- If any required tool missing, return DENY with reason "Must call '{required_tool}' before '{tool_name}'"
- If no requirements or all present, return PASS
- **Error Handling**: Wrap in try-except, return DENY on errors (fail-secure)
- Integrate into validation pipeline (Step 4)
- **Unit Tests**: Create `tests/unit/test_context_validator.py`
  - Test: process_refund without check_order in history returns DENY
  - Test: process_refund with check_order in history returns PASS
  - Test: reverse_refund without process_refund returns DENY
  - Test: Tool with no requirements always returns PASS
  - Test: Only last 10 tools checked (11th tool in history ignored)
  - Test: Error handling returns DENY on exceptions
  - Coverage target: >80%
- _Requirements: LLD 03 Section 3.4, 8.1_

---

### Task 8: Abuse Detector Implementation ✅ COMPLETED

- Create `validators/abuse_detector.py` with `AbuseDetector` class
- Implement `check_rate_limit(session, policy)` method
- Get `abuse_counters` from session: `calls_this_minute`, `last_minute_reset`
- Calculate current minute: `current_minute = int(time.time()) // 60`
- If `last_minute_reset != current_minute`, reset counter to 1 and update `last_minute_reset`
- Else, increment `calls_this_minute`
- Check if `calls_this_minute > policy.max_calls_per_minute`
  - If exceeded, return DENY with reason "Rate limit exceeded: {count}/{limit} calls/min"
- If within limit, return PASS
- Update session `abuse_counters` in DynamoDB
- **Error Handling**: Wrap in try-except, return DENY on errors (fail-secure: deny if rate limit check fails)
- Integrate into validation pipeline (Step 5)
- **Unit Tests**: Create `tests/unit/test_abuse_detector.py`
  - Test: 11th request in same minute (limit=10) returns DENY
  - Test: Counter resets after minute boundary
  - Test: Different sessions have independent counters
  - Test: Within limit returns PASS
  - Test: Error handling returns DENY on exceptions
  - Coverage target: >80%
- _Requirements: LLD 03 Section 3.5, 8.1_

**DEMO CHECKPOINT 2**: Complete validation pipeline implemented with all 5 validators. Can block prompt injection, unauthorized tools, missing tool sequences, and rate limit violations. Trust scoring updates correctly on ALLOW/DENY.

---

### Task 8.5: Docker Build and Deploy Milestone 2 ✅ COMPLETED

**Purpose**: Deploy Milestone 2 code with complete validation pipeline

**Build and Push**

- Build and push using the script:
  ```bash
  python scripts/build_and_push_image.py \
    --service security-controller \
    --milestone 2
  ```

**Test Locally (Optional)**

- Test validation scenarios:
  ```bash
  # Test prompt injection detection
  curl -X POST http://localhost:8080/v1/validate \
    -H "Content-Type: application/json" \
    -d '{
      "request_id":"test-1",
      "session_id":"sess-test",
      "agent_id":"test-agent",
      "tool_name":"query_customers",
      "tool_params":{},
      "user_input":"ignore previous instructions",
      "timestamp":"2025-01-16T10:00:00Z",
      "operation_type":"READ"
    }'
  
  # Should return DENY with threat_type="PROMPT_INJECTION"
  ```

**Monitor ECS Deployment**

- Wait for rolling update to complete (~2-3 minutes)
- Monitor: `aws ecs describe-services --cluster sentra-mvp-cluster --services security-controller --region us-east-1 --profile sentra`

**Verify Deployment**

- Test validation endpoint through ALB:
  ```bash
  curl -X POST http://$ALB_DNS/v1/validate \
    -H "Content-Type: application/json" \
    -d '{
      "request_id":"test-1",
      "session_id":"sess-test",
      "agent_id":"customer-query-agent",
      "tool_name":"query_customers",
      "tool_params":{},
      "user_input":"Show customers from CA",
      "timestamp":"2025-01-16T10:00:00Z",
      "operation_type":"READ"
    }'
  # Should return ALLOW with trust_score
  ```

- Test: Verify all 5 validators work through ALB
- Test: Verify trust score updates in DynamoDB
- Test: Verify Sigma rules loaded from S3 (check logs for "Loaded X Sigma rules")
- Verify: CloudWatch Logs showing validation decisions
- _Requirements: LLD 03 Section 3_

---

## Milestone 3: Audit Logging and Additional APIs (Days 8-9) ✅ COMPLETED

### Task 9: Audit Logger and Metrics Publisher Implementation ✅ COMPLETED

**Part A: Audit Logger**
- Create `utils/audit_logger.py` with `AuditLogger` class
- Implement `log_decision(decision, request, session, validation_result)` method
- Create log event with fields: `request_id`, `timestamp`, `session_id`, `agent_id`, `tool_name`, `operation_type`, `decision`, `reason`, `threat_type`, `severity`, `trust_score_before`, `trust_score_after`, `trust_delta`, `latency_ms`
- **For reversible actions**: Include `action_id`, `reversible=true`, `rollback_status="NOT_ROLLED_BACK"` (see LLD Section 11.2)
- Write to CloudWatch Logs log group `/sentra/audit-logs`
- Use log stream per session: `/sentra/audit-logs/{session_id}`
- Format as JSON for CloudWatch Insights queries
- Log asynchronously (fire-and-forget, don't block validation response)
- **Error Handling**: Catch and log exceptions, don't raise (logging failures should not block validation)

**Part B: Metrics Publisher**
- Create `utils/metrics_publisher.py` with `MetricsPublisher` class (see LLD Section 9.1)
- Implement `publish_validation_metrics(decision, latency_ms, agent_id, trust_score)` method
- Publish 4 metrics to CloudWatch namespace "Sentra/SecurityController":
  - `ValidationsTotal` (counter, dimensions: AgentId, Decision)
  - `ValidationLatency` (histogram, dimensions: AgentId)
  - `TrustScoreAverage` (gauge, dimensions: AgentId)
  - `DenyRate` (gauge, only if decision=DENY, dimensions: AgentId)
- Implement `publish_session_metrics(quarantined_count, suspended_count)` method
- Implement `publish_error_metric(error_type)` method
- All methods fire-and-forget (async, non-blocking)
- **Error Handling**: Catch and log exceptions, don't raise (metrics failures should not block validation)

**Integration**:
- Integrate audit logger into validation pipeline (after each decision)
- Integrate metrics publisher into validation pipeline (after each decision)
- Call metrics publisher from main validation logic in `routes.py`

**Testing**:
- Test: Send validation request, verify log appears in CloudWatch Logs
- Test: Query logs using CloudWatch Insights: `fields @timestamp, decision, tool_name | filter decision = "DENY"`
- Test: Verify metrics appear in CloudWatch Metrics console
- Test: Verify action_id is logged for reversible actions
- Verify: Log stream created per session_id
- Verify: Metrics published with correct dimensions
- _Requirements: LLD 03 Section 5.3, 9.1, 11.2_

---

### Task 10: GET /logs Endpoint Implementation ✅ COMPLETED

- Implement `GET /logs` endpoint in `api/routes.py`
- **Note**: MVP uses polling approach (dashboard calls this endpoint every 5 seconds). Phase 2 will add WebSocket support for real-time streaming (see LLD Section 4.3)
- Accept query parameters: `since` (ISO timestamp), `until` (ISO timestamp), `limit` (default 100, max 1000), `session_id`, `agent_id`, `decision`, `threat_type`
- Query CloudWatch Logs using `boto3.client('logs').start_query()`
- Build CloudWatch Insights query based on filters
- Example: `fields @timestamp, request_id, decision, tool_name | filter decision = "DENY" | sort @timestamp desc | limit 100`
- Poll for query results using `get_query_results()` (max 5 seconds wait)
- Parse results and return as JSON array
- Include pagination: `total`, `has_more`, `next_token`
- **Error Handling**: Return 500 on CloudWatch query failures, log errors
- Test: Query logs with `since=2025-01-13T10:00:00Z&limit=50`
- Test: Filter by `decision=DENY` and verify only DENY logs returned
- Test: Verify pagination works for large result sets
- Test: Verify query timeout handling (if query takes > 5 seconds)
- _Requirements: LLD 03 Section 4.3, 8.1_

---

### Task 11: GET /sessions and GET /metrics Endpoints ✅ COMPLETED

- Implement `GET /sessions` endpoint
- Accept query parameters: `status` (active/quarantined/suspended), `agent_id`, `limit` (default 50, max 200)
- Query DynamoDB `sentra-session-context` table
- Filter by `quarantine_status` if provided
- Return array of sessions with: `session_id`, `user_id`, `agent_id`, `trust_score`, `quarantine_status`, `total_requests`, `allow_count`, `deny_count`, `consecutive_allows`, `created_at`, `last_activity`
- Implement `GET /metrics` endpoint
- Accept query parameters: `since` (ISO timestamp), `until` (ISO timestamp)
- Query CloudWatch Logs for summary metrics in time range
- Calculate: `total_requests`, `allow_count`, `deny_count`, `deny_rate`, `avg_latency_ms`, `p95_latency_ms`, `active_sessions`, `quarantined_sessions`, `suspended_sessions`
- Group threats by type: `{"PROMPT_INJECTION": 15, "JAILBREAK": 8, ...}`
- Return metrics as JSON
- Test: Query `/sessions?status=quarantined` returns only quarantined sessions
- Test: Query `/metrics?since=2025-01-13T10:00:00Z` returns correct counts
- Verify: Metrics match audit log data
- _Requirements: LLD 03 Section 4.4, 4.5_

---

## Milestone 4: Rollback and Quarantine (Days 13-14)

### Task 12: Rollback Coordinator Implementation ✅ COMPLETED

- Create `utils/rollback_coordinator.py` with `RollbackCoordinator` class
- Implement `rollback_action(action_id, action_type, reason, operator_id)` method
- Validate `action_type` is in supported list (currently only "process_refund")
- Implement `_get_action_from_logs(action_id)` method:
  - Query CloudWatch Logs Insights for `action_id` in `/sentra/audit-logs`
  - Filter: `fields @timestamp, action_id, tool_name, tool_params, reversible | filter action_id = "{action_id}"`
  - Return action details or None if not found
- Check if action exists and is reversible (`reversible == true`)
- Check if action already rolled back (`rollback_status == "ROLLED_BACK"`)
- If already rolled back, return error "Action already rolled back"
- Execute rollback handler based on action_type
- For `process_refund`: Call `_rollback_refund(original_action)` method
- Implement `_rollback_refund(original_action)` method:
  - Extract `order_id` and `amount` from original action tool_params
  - Update DynamoDB `sentra-demo-orders` table: `SET refund_status = "REVERSED", refund_reversed_at = :timestamp`
  - Return rollback action details
- Implement `_log_rollback(action_id, rollback_id, operator_id, reason, result)` method:
  - Create rollback event with all details (see LLD Section 11.5)
  - Write to CloudWatch Logs `/sentra/audit-logs` with `event_type="ROLLBACK"`
- **Error Handling**: Wrap all operations in try-except, return detailed error messages
- Test: Process refund, then rollback, verify order status changed to "REVERSED"
- Test: Attempt to rollback same action twice, verify error returned
- Test: Verify rollback event logged to audit logs with correct schema
- Test: Verify action_id lookup from CloudWatch Logs works
- _Requirements: LLD 03 Section 11.2, 11.4, 11.5, 8.1_

---

### Task 13: POST /rollback and POST /quarantine Endpoints ✅ COMPLETED

- Implement `POST /rollback` endpoint in `api/routes.py`
- Accept request body: `{"action_id": "...", "action_type": "...", "reason": "...", "operator_id": "..."}`
- Call `RollbackCoordinator.rollback_action()`
- Return success response with rollback details or error response
- Implement `POST /quarantine/{session_id}` endpoint
- Accept request body: `{"reason": "...", "operator_id": "..."}`
- Call `SessionManager.manual_quarantine(session_id, reason, operator_id)`
- Return success response with updated session or error if session not found
- Test: POST to `/rollback` with valid action_id, verify success
- Test: POST to `/rollback` with invalid action_id, verify 404 error
- Test: POST to `/quarantine/{session_id}` with valid session, verify quarantine_status updated
- Test: Verify quarantined session blocks WRITE operations in validation
- _Requirements: LLD 03 Section 4.6, 4.7_

**DEMO CHECKPOINT 3**: Complete Security Controller with all APIs functional. Can validate requests, log to CloudWatch, query logs/sessions/metrics, manually rollback actions, and manually quarantine sessions.

---

### Task 13.5: Docker Build and Deploy Milestone 3 ✅ COMPLETED

**Purpose**: Deploy Milestone 3 code with all query APIs and rollback functionality

**Build and Push**

- Build and push using the script:
  ```bash
  python scripts/build_and_push_image.py \
    --service security-controller \
    --milestone 3
  ```

**Test Locally (Optional)**

- Test query endpoints:
  ```bash
  curl "http://localhost:8080/v1/logs?limit=10"
  curl "http://localhost:8080/v1/sessions?limit=10"
  curl "http://localhost:8080/v1/metrics"
  ```

**Monitor ECS Deployment**

- Wait for rolling update to complete (~2-3 minutes)
- Monitor: `aws ecs describe-services --cluster sentra-mvp-cluster --services security-controller --region us-east-1 --profile sentra`

**Verify Deployment**

- Test query endpoints through ALB:
  ```bash
  curl "http://$ALB_DNS/v1/logs?limit=10"
  curl "http://$ALB_DNS/v1/sessions?limit=10"
  curl "http://$ALB_DNS/v1/metrics"
  ```

- Test: Verify CloudWatch Logs query works (returns JSON array)
- Test: Verify CloudWatch Metrics are published (check CloudWatch console)
- Test: Verify rollback endpoint works (if refund action exists)
- Verify: All 7 REST endpoints functional through ALB
- _Requirements: LLD 03 Section 4_

---

## Milestone 4: CloudWatch Alarms and Final Testing (Days 14-16)

### Task 14: CloudWatch Alarms and Dashboard for Security Controller ✅ COMPLETED

**Part A: Create CloudWatch Alarms**

- Create 5 CloudWatch Alarms for Security Controller (can be added to MonitoringStack or created via CLI)
- **Alarm 1: HealthCheckFailure**
  - Metric: Custom metric `HealthCheckStatus` (0=healthy, 1=unhealthy)
  - Threshold: ≥ 1 for 2 consecutive periods (1 minute each)
  - Action: Send to SNS topic `sentra-critical-alerts`
- **Alarm 2: DynamoDBErrors**
  - Metric: Custom metric `DynamoDBErrors`
  - Threshold: > 5 errors/minute for 2 consecutive periods
  - Action: Send to SNS topic `sentra-critical-alerts`
- **Alarm 3: HighLatency**
  - Metric: Custom metric `ValidationLatency` (p95)
  - Threshold: > 100ms for 3 consecutive periods (1 minute each)
  - Action: Send to SNS topic `sentra-alerts`
- **Alarm 4: HighDenyRate**
  - Metric: Custom metric `DenyRate`
  - Threshold: > 0.50 (50%) for 3 consecutive periods (5 minutes each)
  - Action: Send to SNS topic `sentra-alerts`
- **Alarm 5: SuspendedSession**
  - Metric: Custom metric `SuspendedSessions`
  - Threshold: ≥ 1 for 1 period (1 minute)
  - Action: Send to SNS topic `sentra-info`

**Part B: Create CloudWatch Dashboard**

- Create dashboard: `Sentra-SecurityController-Dashboard` via AWS CLI or CDK
- Dashboard layout (6 widgets total):

  **Row 1: Performance Metrics**
  - Widget 1: Validation Latency (line graph)
    - Metrics: ValidationLatency p50, p95, p99
    - Period: 1 minute
    - Statistic: Percentile
  - Widget 2: Request Volume (stacked area)
    - Metrics: ValidationsTotal (ALLOW + DENY)
    - Period: 1 minute
    - Statistic: Sum

  **Row 2: Security Metrics**
  - Widget 3: Allow/Deny Rate (stacked area)
    - Metrics: DenyRate, AllowRate
    - Period: 5 minutes
    - Statistic: Average
  - Widget 4: Threat Types (pie chart)
    - Metrics: Threats by type (PROMPT_INJECTION, JAILBREAK, SQL_INJECTION, etc.)
    - Period: 1 hour
    - Statistic: Sum

  **Row 3: Session Health**
  - Widget 5: Trust Score Distribution (number widgets)
    - Metrics: TrustScoreAverage
    - Period: 5 minutes
    - Statistic: Average
  - Widget 6: Session Status (number widgets)
    - Metrics: QuarantinedSessions, SuspendedSessions
    - Period: 1 minute
    - Statistic: Maximum

- Create dashboard using AWS CLI:
  ```bash
  aws cloudwatch put-dashboard \
    --dashboard-name Sentra-SecurityController-Dashboard \
    --dashboard-body file://config/cloudwatch-dashboard.json \
    --region us-east-1 \
    --profile sentra
  ```

- Or add to CDK MonitoringStack:
  ```python
  dashboard = cloudwatch.Dashboard(
      self, "SecurityControllerDashboard",
      dashboard_name="Sentra-SecurityController-Dashboard"
  )

  dashboard.add_widgets(
      cloudwatch.GraphWidget(
          title="Validation Latency (p50/p95/p99)",
          left=[validation_latency_p50, validation_latency_p95, validation_latency_p99]
      ),
      # ... add remaining widgets
  )
  ```

**Testing**:
- Test: Trigger each alarm by simulating failure conditions
- Test: View dashboard in CloudWatch console
- Verify: All 6 widgets display data correctly
- Verify: Alarms appear on dashboard
- Verify: Email notifications received for alarms
- _Requirements: LLD 03 Section 9.1, 9.2_

**Note**: Full comprehensive dashboard with cross-service metrics will be built in Workstream 5 (Dashboard service). This is a basic Security Controller-only dashboard for MVP.

---

### Task 15: End-to-End Integration Testing

**Purpose**: Comprehensive testing of all Security Controller functionality with specific acceptance criteria

- **Test Suite 1: Validation Pipeline**
  - Test all 5 validators with various inputs
  - Verify trust score updates correctly
  - Verify quarantine behavior (suspended, quarantined, warning, active)
  - Test rate limiting across multiple sessions
  - **Acceptance Criteria**:
    - ✅ Prompt injection ("ignore previous instructions") returns DENY with threat_type="PROMPT_INJECTION"
    - ✅ Unauthorized tool returns DENY within 15ms (policy check)
    - ✅ process_refund without check_order returns DENY (context violation)
    - ✅ 11th request in same minute returns DENY (rate limit)
    - ✅ Trust score decrements correctly on DENY (-15 to -30)
    - ✅ Trust score increments correctly after N consecutive allows (10, 12, or 15 based on score)

- **Test Suite 2: Query APIs**
  - Test logs endpoint with various filters
  - Test sessions endpoint with status filters
  - Test metrics endpoint with time ranges
  - Verify pagination works correctly
  - **Acceptance Criteria**:
    - ✅ GET /logs returns audit logs within 2 seconds
    - ✅ Filter by decision=DENY returns only denied requests
    - ✅ GET /sessions returns all sessions with trust_score and quarantine_status
    - ✅ GET /metrics returns summary with allow_count, deny_count, deny_rate
    - ✅ Pagination returns has_more=true when results exceed limit

- **Test Suite 3: Rollback & Quarantine**
  - Process refund → Rollback → Verify order status
  - Manually quarantine session → Verify write operations blocked
  - Test rollback idempotency (can't rollback twice)
  - **Acceptance Criteria**:
    - ✅ POST /rollback reverses refund in DynamoDB (refund_status="REVERSED")
    - ✅ Rollback event logged to CloudWatch with event_type="ROLLBACK"
    - ✅ Second rollback attempt returns 400 error "Action already rolled back"
    - ✅ POST /quarantine sets quarantine_status="quarantined"
    - ✅ Quarantined session blocks WRITE operations but allows READ

- **Test Suite 4: Error Scenarios**
  - DynamoDB unavailable → Verify fail-secure (DENY)
  - S3 unavailable → Verify stale cache used
  - CloudWatch unavailable → Verify validation continues
  - Invalid requests → Verify 400 errors
  - **Acceptance Criteria**:
    - ✅ Mock DynamoDB error → Validation returns DENY (fail-secure)
    - ✅ Mock S3 error with valid cache → Validation uses stale cache and succeeds
    - ✅ Mock S3 error with no cache → Validation returns DENY (fail-secure)
    - ✅ CloudWatch write error → Validation succeeds (logging is non-blocking)
    - ✅ Invalid JSON request → Returns 400 with error details

- **Test Suite 5: Performance**
  - Measure validation latency using pytest-benchmark or manual timing
  - Test concurrent requests (50 req/sec for 60 seconds)
  - Verify cache effectiveness (S3 calls reduced)
  - **Acceptance Criteria**:
    - ✅ Validation latency p50 < 50ms (target: ~45ms)
    - ✅ Validation latency p95 < 100ms (LLD requirement)
    - ✅ Validation latency p99 < 150ms
    - ✅ Concurrent load test: 50 req/sec for 60 seconds with 0 errors
    - ✅ Sigma rule cache hit rate > 99% (after initial load)
    - ✅ No memory leaks after 3000+ requests

- **Test Suite 6: CloudWatch Alarms**
  - Trigger each alarm and verify notifications
  - Verify alarm recovery when issue resolved
  - **Acceptance Criteria**:
    - ✅ Simulate health check failure → Alarm triggered within 2 minutes
    - ✅ Simulate high deny rate (>50%) → Alarm triggered
    - ✅ Simulate high latency (>100ms p95) → Alarm triggered
    - ✅ Resolve issue → Alarm returns to OK state
    - ✅ SNS notification received for each alarm

- **Test Suite 7: Deployment Rollback**
  - Deploy milestone-2 tag to ECS
  - Verify service healthy
  - Deploy intentionally broken version (e.g., invalid Dockerfile)
  - Monitor deployment failure
  - Execute rollback to milestone-2 tag
  - Verify service returns to healthy state
  - **Acceptance Criteria**:
    - ✅ Milestone-2 deployment succeeds and passes health checks
    - ✅ Broken deployment detected (ECS task fails to start)
    - ✅ Rollback command: `python scripts/build_and_push_image.py --service security-controller --milestone 2 --force`
    - ✅ After rollback, ECS service returns to RUNNING state within 5 minutes
    - ✅ Health check passes: `curl http://$ALB_DNS/v1/health` returns 200
    - ✅ Validation endpoint functional after rollback

- Document all test results in `docs/security-controller-test-results.md`
  - Include actual latency measurements (p50/p95/p99)
  - Include test execution time
  - Include any failed tests and reasons
  - Include rollback procedure and timing
- _Requirements: LLD 03 All Sections_

**DEMO CHECKPOINT 4 (FINAL)**: Security Controller fully deployed to ECS with Docker image, all APIs accessible through ALB, CloudWatch alarms configured and tested. Complete end-to-end validation pipeline operational.

---

## Milestone 5: Documentation and Handoff (Day 17)

### Task 16: Documentation and Deployment Guide

- Create `docs/security-controller-deployment.md` with:
  - Architecture diagram
  - Deployment steps (Docker build, ECR push, ECS update)
  - Configuration reference (all environment variables)
  - Troubleshooting guide (common issues and solutions)
  - Rollback procedures
  
- Create `docs/security-controller-api-reference.md` with:
  - All 7 REST endpoints with examples
  - Request/response schemas
  - Error codes and meanings
  - Rate limits per endpoint
  
- Create `docs/security-controller-operations.md` with:
  - How to update policies (run seed script)
  - How to update Sigma rules (upload to S3)
  - How to manually quarantine sessions
  - How to rollback actions
  - How to monitor health (CloudWatch dashboards)
  
- Update main README with Security Controller section
- _Requirements: LLD 03 All Sections_

---

### Task 17: Docker Image and ECS Deployment ✅ COMPLETED (Already done via build_and_push_image.py script)

- Create `Dockerfile` in `src/security-controller/`
- Use base image: `python:3.11-slim`
- Copy `requirements.txt` and install dependencies
- Copy application code to `/app`
- Expose port 8080
- Set CMD: `["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]`
- Build Docker image: `docker build -t sentra/security-controller:latest .`
- Test locally: `docker run -p 8080:8080 -e AWS_REGION=us-east-1 sentra/security-controller:latest`
- Verify health endpoint works in container at `/v1/health`
- Tag image for ECR: `docker tag sentra/security-controller:latest 531109575379.dkr.ecr.us-east-1.amazonaws.com/sentra/security-controller:latest`
- Push to ECR: `docker push 531109575379.dkr.ecr.us-east-1.amazonaws.com/sentra/security-controller:latest`
- Update ECS task definition to use new image tag
- Deploy to ECS: ECS service will automatically pull new image and perform rolling update
- Test: Curl ALB endpoint `/v1/health` returns 200 OK
- Test: POST to `/v1/validate` through ALB works correctly
- Verify: ECS task is running and healthy in ECS console
- Verify: CloudWatch Logs showing container logs
- _Requirements: LLD 03 Section 2.3_

---

### Task 18: CloudWatch Alarms for Security Controller

- Create 5 CloudWatch Alarms for Security Controller (can be added to MonitoringStack)
- **Alarm 1: HealthCheckFailure**
  - Metric: Custom metric `HealthCheckStatus` (0=healthy, 1=unhealthy)
  - Threshold: ≥ 1 for 2 consecutive periods (1 minute each)
  - Action: Send to SNS topic `sentra-critical-alerts`
- **Alarm 2: DynamoDBErrors**
  - Metric: Custom metric `DynamoDBErrors`
  - Threshold: > 5 errors/minute for 2 consecutive periods
  - Action: Send to SNS topic `sentra-critical-alerts`
- **Alarm 3: HighLatency**
  - Metric: Custom metric `ValidationLatency` (p95)
  - Threshold: > 100ms for 3 consecutive periods (1 minute each)
  - Action: Send to SNS topic `sentra-alerts`
- **Alarm 4: HighDenyRate**
  - Metric: Custom metric `DenyRate`
  - Threshold: > 0.50 (50%) for 3 consecutive periods (5 minutes each)
  - Action: Send to SNS topic `sentra-alerts`
- **Alarm 5: SuspendedSession**
  - Metric: Custom metric `SuspendedSessions`
  - Threshold: ≥ 1 for 1 period (1 minute)
  - Action: Send to SNS topic `sentra-info`
- Update Security Controller to publish custom metrics to CloudWatch
- Test: Trigger each alarm by simulating failure conditions
- Verify: Email notifications received for each alarm
- _Requirements: LLD 03 Section 9.2_

**DEMO CHECKPOINT 4 (FINAL)**: Security Controller fully deployed to ECS with Docker image, all APIs accessible through ALB, CloudWatch alarms configured and tested. Complete end-to-end validation pipeline operational.

---

## Post-Deployment Verification Checklist

After Task 16 (final deployment), run these verification steps:

```bash
# Set environment
export AWS_PROFILE=sentra
export AWS_REGION=us-east-1

# 1. Verify ECS service running
aws ecs describe-services --cluster sentra-mvp-cluster --services security-controller --region us-east-1

# 2. Test health endpoint through ALB
ALB_DNS=$(aws elbv2 describe-load-balancers --names sentra-alb --query 'LoadBalancers[0].DNSName' --output text)
curl http://$ALB_DNS/v1/health

# 3. Test validation endpoint (requires API Gateway)
API_KEY=$(aws apigateway get-api-key --api-key <key-id> --include-value --query 'value' --output text)
curl -X POST -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"request_id":"test-1","session_id":"sess-test","agent_id":"test-agent","tool_name":"query_customers","tool_params":{},"user_input":"Show customers","timestamp":"2025-01-13T10:00:00Z","operation_type":"READ"}' \
  https://<api-id>.execute-api.us-east-1.amazonaws.com/prod/v1/validate

# 4. Verify CloudWatch Logs
aws logs tail /sentra/audit-logs --follow

# 5. Check CloudWatch Alarms
aws cloudwatch describe-alarms --alarm-name-prefix SecurityController

# 6. Query sessions
curl -H "X-API-Key: $API_KEY" \
  https://<api-id>.execute-api.us-east-1.amazonaws.com/prod/v1/sessions

# 7. Query metrics
curl -H "X-API-Key: $API_KEY" \
  https://<api-id>.execute-api.us-east-1.amazonaws.com/prod/v1/metrics
```

---

## Dependencies and Parallel Work

**Prerequisites**:
- Workstream 1 (Infrastructure) must be completed
- DynamoDB tables created and seeded
- S3 bucket with Sigma rules uploaded
- ECS cluster and task definitions ready
- ECR repository created: `sentra/security-controller`

**Can Run in Parallel**:
- Tasks 4-8 (all validators can be developed independently)
- Tasks 10-11 (query endpoints independent)

**Must Run Sequentially**:
- Task 1 → Task 1.5 → Task 2 → Task 3 → Task 3.5 (Milestone 1 foundation + deploy)
- Tasks 4-8 → Task 8.5 (validators + deploy)
- Task 9 → Task 10 → Task 11 (audit logging before query APIs)
- Task 12 → Task 13 → Task 13.5 (rollback + deploy)
- Task 14 → Task 15 (alarms before integration testing)
- Task 15 → Task 16 (testing before documentation)

**Incremental Deployment Strategy**:
- Each milestone deploys to ECS with milestone-specific tag (e.g., `milestone-1`, `milestone-2`)
- Also updates `:latest` tag for ECS to pick up
- Allows testing in production-like environment after each milestone
- Rollback available by reverting to previous milestone tag

---

## Estimated Timeline

| Task | Duration | Cumulative |
|------|----------|------------|
| **Milestone 0** | | |
| Task 0 (NEW) | 0.5 day | Day 0.5 |
| **Milestone 1** | | |
| Task 1 | 1 day | Day 1.5 |
| Task 1.5 | 0.5 day | Day 2 |
| Task 2 | 1.5 days | Day 3.5 |
| Task 3 | 0.5 day | Day 4 |
| Task 3.5 | 0.5 day | Day 4.5 |
| **Checkpoint 1 + Deploy** | - | Day 4.5 |
| **Milestone 2** | | |
| Task 4 (UPDATED) | 0.5 day | Day 5 |
| Task 5 (UPDATED) | 1 day | Day 6 |
| Task 6 (UPDATED) | 1.5 days | Day 7.5 |
| Task 7 (UPDATED) | 0.5 day | Day 8 |
| Task 8 (UPDATED) | 0.5 day | Day 8.5 |
| Task 8.5 | 0.5 day | Day 9 |
| **Checkpoint 2 + Deploy** | - | Day 9 |
| **Milestone 3** | | |
| Task 9 | 1.5 days | Day 10.5 |
| Task 10 | 1 day | Day 11.5 |
| Task 11 | 1 day | Day 12.5 |
| Task 12 | 1.5 days | Day 14 |
| Task 13 | 0.5 day | Day 14.5 |
| Task 13.5 | 0.5 day | Day 15 |
| **Checkpoint 3 + Deploy** | - | Day 15 |
| **Milestone 4** | | |
| Task 14 (UPDATED) | 1 day | Day 16 |
| Task 15 (UPDATED) | 1.5 days | Day 17.5 |
| **Checkpoint 4 (Final)** | - | Day 17.5 |
| **Milestone 5** | | |
| Task 16 | 1 day | Day 18.5 |

**Total: ~18.5 days (≈4 weeks)**

**Changes from Original (17 days) to Updated (18.5 days)**:
- Added Task 0: Configuration files and Sigma rules setup (+0.5 day)
- Updated Tasks 4-8: Added explicit unit test creation (+0 days, included in original estimates)
- Updated Task 14: Added CloudWatch dashboard creation (+0.5 day, was 0.5 day, now 1 day)
- Updated Task 15: Added acceptance criteria and rollback testing (+0.5 day, was 1 day, now 1.5 days)
- Added Section 10 to best-practices.md: Docker versioning strategy (+0 days, documentation only)
- **Total increase**: +1.5 days (17 → 18.5 days)
- **Still within 4-week timeline**: ✅ (18.5 < 20 days)

---

**Next Workstream**: Agents Implementation (LLD 04) - Start after Task 14 completion

**Integration Point**: Security Controller APIs will be called by agents via `@secured_tool` decorator
