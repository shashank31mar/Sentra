# Sentra MVP - End-to-End Flows

**Version:** 1.0
**Last Updated:** 2025-11-12
**Purpose:** Document key operational flows for Sentra MVP

---

## Table of Contents

1. [Single Agent Flow](#1-single-agent-flow)
2. [Multi-Agent Flow](#2-multi-agent-flow)
3. [Validation Flow (Security Controller)](#3-validation-flow-security-controller)
4. [Session Management Flow](#4-session-management-flow)
5. [Dashboard Query Flow](#5-dashboard-query-flow)
6. [Policy Enforcement Flow](#6-policy-enforcement-flow)

---

## 1. Single Agent Flow

### Flow: User queries customer query agent

```
┌──────────┐
│   User   │
└─────┬────┘
      │ 1. POST /agents/customer-query/query
      │    {"message": "Show orders for Acme Corp"}
      ▼
┌─────────────────────────────┐
│     API Gateway             │
│  • Validate API key         │
│  • Rate limit check (20/min)│
└─────┬───────────────────────┘
      │ 2. Forward to Customer Query Agent
      ▼
┌─────────────────────────────────────────────┐
│          Customer Query Agent (ECS)               │
│  • Receive user query                       │
│  • LangChain parses intent                  │
│  • Selects tool: execute_sql               │
└─────┬───────────────────────────────────────┘
      │ 3. Call Security Controller to validate tool
      │    POST /validate
      │    {
      │      "session_id": "sess-abc-123",
      │      "agent_id": "customer-query-agent",
      │      "tool_name": "execute_sql",
      │      "tool_params": {"query": "SELECT * FROM orders WHERE customer='Acme'"}
      │    }
      ▼
┌─────────────────────────────────────────────┐
│      Security Controller (ECS)              │
│  • Load session context from DynamoDB       │
│  • Check if session quarantined            │
│  • Load Sigma rules from S3                 │
│  • Load policies from S3 (via DynamoDB)     │
│  • Run validation checks                    │
└─────┬───────────────────────────────────────┘
      │ 4. Validation result: ALLOW
      │    {"decision": "ALLOW", "request_id": "req-001"}
      ▼
┌─────────────────────────────────────────────┐
│      Security Controller (ECS)              │
│  • Write audit log to CloudWatch Logs       │
│  • Update session context in DynamoDB       │
│    (increment allow_count, update tool_history) │
└─────┬───────────────────────────────────────┘
      │ 5. Return ALLOW to Customer Query Agent
      ▼
┌─────────────────────────────────────────────┐
│          Customer Query Agent (ECS)               │
│  • Execute tool: execute_sql()              │
│  • Query DynamoDB: sentra-demo-orders       │
│  • Format results                           │
└─────┬───────────────────────────────────────┘
      │ 6. Return results to user
      │    {
      │      "response": "Found 5 orders for Acme Corp",
      │      "data": [{order_id: "ORD-001", ...}],
      │      "metadata": {"validation_requests": 1}
      │    }
      ▼
┌──────────┐
│   User   │
└──────────┘
```

**Key Points:**
- **EVERY tool call** goes through Security Controller validation
- Session context is updated after each validation
- Audit logs written to CloudWatch Logs (not DynamoDB)
- Customer query agent reads from `sentra-demo-orders` table

---

## 2. Multi-Agent Flow

### Flow: Customer query agent calls payment agent

```
┌──────────┐
│   User   │
└─────┬────┘
      │ 1. "Show orders for Acme Corp and issue refund if needed"
      ▼
┌─────────────────────────────────────────────┐
│          Customer Query Agent (ECS)               │
│  • Parse query                              │
│  • Step 1: Query orders (execute_sql tool)  │
└─────┬───────────────────────────────────────┘
      │ 2. Validate execute_sql with Security Controller
      ▼
┌─────────────────────────────────────────────┐
│      Security Controller (ECS)              │
│  • Validation: ALLOW                        │
│  • Log: req-001 (conversation_id: conv-abc) │
└─────┬───────────────────────────────────────┘
      │ 3. Execute SQL query
      ▼
┌─────────────────────────────────────────────┐
│          Customer Query Agent (ECS)               │
│  • Query returns: Order ORD-001, $500       │
│  • Step 2: Determine refund needed          │
│  • Call Payment Agent                       │
└─────┬───────────────────────────────────────┘
      │ 4. Inter-agent call
      │    POST http://payment-agent.sentra.internal:8003/action
      │    {"action": "Process refund $500 for ORD-001"}
      ▼
┌─────────────────────────────────────────────┐
│          Payment Agent (ECS)                │
│  • Receive request from Customer Query Agent      │
│  • Parse action                             │
│  • Select tool: process_refund              │
└─────┬───────────────────────────────────────┘
      │ 5. Validate process_refund with Security Controller
      │    POST /validate
      │    {
      │      "session_id": "sess-abc-123",
      │      "conversation_id": "conv-abc",  ← SAME conversation
      │      "agent_id": "payment-agent",
      │      "parent_request_id": "req-001",  ← Links back
      │      "caller_agent_id": "customer-query-agent",
      │      "tool_name": "process_refund",
      │      "tool_params": {"order_id": "ORD-001", "amount": 500}
      │    }
      ▼
┌─────────────────────────────────────────────┐
│      Security Controller (ECS)              │
│  • Load session context                     │
│  • Check authorization level: "manager"     │
│  • Load policy: refund-limit-policy-v1.yaml │
│  • Evaluate: Manager limit is $200          │
│  • Decision: DENY (exceeds authorization)   │
└─────┬───────────────────────────────────────┘
      │ 6. Validation result: DENY
      │    {
      │      "decision": "DENY",
      │      "reason": "Refund $500 exceeds manager authorization ($200)",
      │      "request_id": "req-002"
      │    }
      ▼
┌─────────────────────────────────────────────┐
│      Security Controller (ECS)              │
│  • Write audit log to CloudWatch (req-002)  │
│  • Update session context:                  │
│    - Increment deny_count                   │
│    - Increment consecutive_denies           │
└─────┬───────────────────────────────────────┘
      │ 7. Return DENY to Payment Agent
      ▼
┌─────────────────────────────────────────────┐
│          Payment Agent (ECS)                │
│  • Tool call BLOCKED                        │
│  • Return error to Customer Query Agent           │
└─────┬───────────────────────────────────────┘
      │ 8. Return error to Customer Query Agent
      ▼
┌─────────────────────────────────────────────┐
│          Customer Query Agent (ECS)               │
│  • Format error response for user           │
└─────┬───────────────────────────────────────┘
      │ 9. Return to user
      │    {
      │      "response": "Found order ORD-001 ($500). Refund requires director approval.",
      │      "blocked_action": "process_refund",
      │      "reason": "Exceeds manager authorization limit"
      │    }
      ▼
┌──────────┐
│   User   │
└──────────┘
```

**CloudWatch Logs (conversation_id: conv-abc):**
```json
// req-001: Customer query agent validates execute_sql
{
  "request_id": "req-001",
  "conversation_id": "conv-abc",
  "agent_id": "customer-query-agent",
  "tool_name": "execute_sql",
  "decision": "ALLOW"
}

// req-002: Payment agent validates process_refund (BLOCKED)
{
  "request_id": "req-002",
  "conversation_id": "conv-abc",
  "parent_request_id": "req-001",
  "caller_agent_id": "customer-query-agent",
  "agent_id": "payment-agent",
  "tool_name": "process_refund",
  "decision": "DENY",
  "reason": "Refund $500 exceeds manager authorization ($200)"
}
```

**Key Points:**
- **Same conversation_id** tracks entire user conversation
- **parent_request_id** links child requests to parent
- **caller_agent_id** identifies which agent made inter-agent call
- Session context spans both agents (same session_id)

---

## 3. Validation Flow (Security Controller)

### Flow: How Security Controller validates a tool call

```
┌─────────────────────┐
│  Agent calls        │
│  POST /validate     │
└─────┬───────────────┘
      │ Request: {session_id, agent_id, tool_name, tool_params, user_input}
      ▼
┌─────────────────────────────────────────────┐
│  Step 1: Load Session Context (DynamoDB)    │
│  • GetItem(session_id)                      │
│  • Check quarantine_status                  │
│  • If quarantined → immediate DENY          │
└─────┬───────────────────────────────────────┘
      │ Session active
      ▼
┌─────────────────────────────────────────────┐
│  Step 2: Load Validation Rules              │
│  • Sigma Rules (S3): sigma_rules/llm/*.yaml │
│  • Policies (DynamoDB + S3):                │
│    - Query policies table                   │
│    - Fetch YAML from S3                     │
│  • Cache in memory                          │
└─────┬───────────────────────────────────────┘
      │ Rules loaded
      ▼
┌─────────────────────────────────────────────┐
│  Step 3: Run Validation Checks (6 areas)    │
│                                             │
│  Check 1: User Input Validation             │
│   • Run Sigma rules on user_input           │
│   • Detect: prompt injection, jailbreak     │
│                                             │
│  Check 2: Tool Selection Validation         │
│   • Is tool allowed for this agent?         │
│   • Check approved_tools in session context │
│                                             │
│  Check 3: Parameter Validation              │
│   • Run Sigma rules on tool_params          │
│   • Detect: SQL injection, PII leakage      │
│                                             │
│  Check 4: Business Rules (Policies)         │
│   • Load policy YAML for this tool          │
│   • Evaluate conditions (e.g., refund limit)│
│   • Check authorization level               │
│                                             │
│  Check 5: Workflow Context                  │
│   • Check tool_history in session           │
│   • Example: process_refund requires        │
│     check_order to be called first          │
│                                             │
│  Check 6: Rate Limits                       │
│   • Check abuse_counters in session         │
│   • requests_last_minute < 100?             │
│   • consecutive_denies < 5?                 │
└─────┬───────────────────────────────────────┘
      │ All checks complete
      ▼
┌─────────────────────────────────────────────┐
│  Step 4: Make Decision                      │
│  • IF any check failed → DENY               │
│  • IF PII detected → REDACT                 │
│  • ELSE → ALLOW                             │
└─────┬───────────────────────────────────────┘
      │ Decision: DENY
      ▼
┌─────────────────────────────────────────────┐
│  Step 5: Write Audit Log (CloudWatch Logs)  │
│  • PutLogEvents to /sentra/audit-logs       │
│  • Log stream: session_id                   │
│  • Full JSON: user_input, tool_params,      │
│    matched_rules, reason, metadata          │
└─────┬───────────────────────────────────────┘
      │ Log written
      ▼
┌─────────────────────────────────────────────┐
│  Step 6: Update Session Context (DynamoDB)  │
│  • UpdateItem(session_id)                   │
│  • Increment: deny_count, consecutive_denies│
│  • Append to tool_history (last 10)         │
│  • Update: last_activity                    │
└─────┬───────────────────────────────────────┘
      │ Session updated
      ▼
┌─────────────────────────────────────────────┐
│  Step 7: Return Decision to Agent           │
│  {                                          │
│    "request_id": "req-abc",                 │
│    "decision": "DENY",                      │
│    "reason": "...",                         │
│    "matched_rules": [...]                   │
│  }                                          │
└─────────────────────────────────────────────┘
```

**Timing:**
- Session context load: ~10ms (DynamoDB)
- Sigma rules (cached): ~5ms
- Policy load (cached): ~10ms
- Validation logic: ~20ms
- CloudWatch log write: ~50ms (async)
- Session update: ~10ms (async)
- **Total:** ~50-100ms per validation

---

## 4. Session Management Flow

### Flow: Session lifecycle

```
┌──────────┐
│   User   │ First request
└─────┬────┘
      │ 1. POST /agents/customer-query/query
      │    No session_id provided
      ▼
┌─────────────────────────────────────────────┐
│          Customer Query Agent (ECS)               │
│  • Generate new session_id: "sess-abc-123"  │
│  • Generate conversation_id: "conv-xyz-001" │
└─────┬───────────────────────────────────────┘
      │ 2. Create session in DynamoDB
      ▼
┌─────────────────────────────────────────────┐
│      Security Controller (ECS)              │
│  • PutItem to sentra-session-context        │
│  • Initial state:                           │
│    {                                        │
│      "session_id": "sess-abc-123",          │
│      "user_id": "manager@sentra.com",       │
│      "agent_id": "customer-query-agent",          │
│      "created_at": 1699876543210,           │
│      "last_activity": 1699876543210,        │
│      "total_requests": 0,                   │
│      "allow_count": 0,                      │
│      "deny_count": 0,                       │
│      "quarantine_status": "active",         │
│      "risk_score": 0.0,                     │
│      "ttl": 1699962543  (24 hours)          │
│    }                                        │
└─────┬───────────────────────────────────────┘
      │ 3. Session active for 24 hours
      ▼
┌─────────────────────────────────────────────┐
│  Each subsequent request:                   │
│  • GetItem(session_id) - verify session     │
│  • UpdateItem - increment counters          │
│  • UpdateItem - refresh last_activity       │
│  • UpdateItem - extend TTL                  │
└─────┬───────────────────────────────────────┘
      │ 4. After 24 hours of inactivity
      ▼
┌─────────────────────────────────────────────┐
│      DynamoDB TTL (automatic)               │
│  • Session expires (TTL reached)            │
│  • Row deleted automatically                │
│  • Next request creates new session         │
└─────────────────────────────────────────────┘
```

**Session Context Updates:**

```python
# After ALLOW decision
UpdateItem(
    session_id = "sess-abc-123",
    UpdateExpression = """
        SET total_requests = total_requests + :inc,
            allow_count = allow_count + :inc,
            consecutive_denies = :zero,
            last_activity = :now,
            ttl = :new_ttl
    """,
    ExpressionAttributeValues = {
        ":inc": 1,
        ":zero": 0,  # Reset consecutive denies on ALLOW
        ":now": current_timestamp,
        ":new_ttl": current_timestamp + 86400  # Extend 24h
    }
)

# After DENY decision
UpdateItem(
    session_id = "sess-abc-123",
    UpdateExpression = """
        SET total_requests = total_requests + :inc,
            deny_count = deny_count + :inc,
            consecutive_denies = consecutive_denies + :inc,
            risk_score = risk_score + :penalty,
            last_activity = :now
    """,
    ExpressionAttributeValues = {
        ":inc": 1,
        ":penalty": 0.1,  # Increase risk score
        ":now": current_timestamp
    }
)

# Quarantine trigger (future feature)
if consecutive_denies >= 5:
    UpdateItem(
        session_id = "sess-abc-123",
        UpdateExpression = "SET quarantine_status = :quarantined, quarantine_reason = :reason",
        ExpressionAttributeValues = {
            ":quarantined": "quarantined",
            ":reason": "Exceeded 5 consecutive deny decisions"
        }
    )
```

---

## 5. Dashboard Query Flow

### Flow: Dashboard displays audit logs

```
┌──────────┐
│Dashboard │ User opens dashboard
│(Streamlit)│
└─────┬────┘
      │ 1. Auto-refresh every 5 seconds
      ▼
┌─────────────────────────────────────────────┐
│  Step 1: Query CloudWatch Logs API          │
│  logs_client.start_query(                   │
│    logGroupName='/sentra/audit-logs',       │
│    queryString='''                          │
│      fields @timestamp, request_id,         │
│             agent_id, tool_name, decision   │
│      | filter @timestamp > ago(1h)          │
│      | sort @timestamp desc                 │
│      | limit 100                            │
│    '''                                      │
│  )                                          │
└─────┬───────────────────────────────────────┘
      │ 2. Poll for results (query takes 5-10s)
      ▼
┌─────────────────────────────────────────────┐
│  Step 2: Get Query Results                  │
│  while status != 'Complete':                │
│    time.sleep(1)                            │
│    result = logs_client.get_query_results() │
└─────┬───────────────────────────────────────┘
      │ 3. Results ready
      ▼
┌─────────────────────────────────────────────┐
│  Step 3: Parse and Display in Streamlit     │
│  • Convert to pandas DataFrame              │
│  • Display as table with filters            │
│  • Show charts (ALLOW vs DENY by hour)      │
│  • Highlight DENY rows in red               │
└─────┬───────────────────────────────────────┘
      │ 4. User clicks on a DENY row
      ▼
┌─────────────────────────────────────────────┐
│  Step 4: Show Detailed View                 │
│  • Query CloudWatch for full log entry:     │
│    filter request_id = 'req-abc-123'        │
│  • Display:                                 │
│    - Full user_input                        │
│    - Full tool_params (JSON)                │
│    - matched_rules (expandable list)        │
│    - reason (full explanation)              │
│  • Show "View in CloudWatch Console" link   │
└─────────────────────────────────────────────┘
```

**Dashboard Queries:**

```python
# Query 1: Recent logs (last hour)
query_1 = """
fields @timestamp, request_id, agent_id, tool_name, decision
| filter @timestamp > ago(1h)
| sort @timestamp desc
| limit 100
"""

# Query 2: DENY decisions only
query_2 = """
fields @timestamp, request_id, agent_id, tool_name, reason
| filter decision = 'DENY'
| filter @timestamp > ago(24h)
| sort @timestamp desc
"""

# Query 3: Session timeline
query_3 = """
fields @timestamp, request_id, agent_id, tool_name, decision
| filter session_id = 'sess-abc-123'
| sort @timestamp asc
"""

# Query 4: Agent activity
query_4 = """
stats count(*) as requests by agent_id, decision
| filter @timestamp > ago(1h)
"""
```

---

## 6. Policy Enforcement Flow

### Flow: How policies are loaded and evaluated

```
┌─────────────────────┐
│ Security Controller │ Startup
└─────┬───────────────┘
      │ 1. Load all active policies from DynamoDB
      ▼
┌─────────────────────────────────────────────┐
│  Step 1: Query DynamoDB                     │
│  Scan(                                      │
│    TableName='sentra-policies',             │
│    FilterExpression='is_active = true'      │
│  )                                          │
│  → Returns: 10 active policies              │
└─────┬───────────────────────────────────────┘
      │ 2. For each policy, fetch YAML from S3
      ▼
┌─────────────────────────────────────────────┐
│  Step 2: Fetch Policy YAML from S3          │
│  s3.get_object(                             │
│    Bucket='sentra-artifacts',               │
│    Key='policies/refund-limit-policy-v1.yaml'│
│  )                                          │
│  → Returns: Full YAML (10KB)                │
└─────┬───────────────────────────────────────┘
      │ 3. Parse and validate YAML
      ▼
┌─────────────────────────────────────────────┐
│  Step 3: Parse YAML and Cache in Memory     │
│  policy = yaml.safe_load(policy_yaml)       │
│  policy_cache[policy_id] = policy           │
│                                             │
│  • Verify checksum (integrity)              │
│  • Validate schema                          │
│  • Compile conditions (if needed)           │
└─────┬───────────────────────────────────────┘
      │ 4. Policies cached, ready for validation
      ▼
┌─────────────────────────────────────────────┐
│  Step 4: Policy Evaluation (during /validate)│
│                                             │
│  For each policy that matches (agent, tool): │
│    1. Get policy from cache                 │
│    2. Evaluate conditions:                  │
│       - Check user.authorization_level      │
│       - Check tool_params['amount']         │
│       - Check session context               │
│    3. If condition matches → apply action   │
│       (allow, deny, redact)                 │
└─────────────────────────────────────────────┘
```

**Policy Reload (every 5 minutes):**

```python
# Background thread in Security Controller
def reload_policies_periodically():
    while True:
        time.sleep(300)  # 5 minutes

        # Query DynamoDB for updated policies
        policies = dynamodb.scan(
            TableName='sentra-policies',
            FilterExpression='is_active = true AND updated_at > :last_check',
            ExpressionAttributeValues={':last_check': last_reload_time}
        )

        # Fetch updated YAMLs from S3
        for policy_metadata in policies:
            policy_yaml = s3.get_object(
                Bucket='sentra-artifacts',
                Key=policy_metadata['policy_yaml_s3']
            )

            # Update cache
            policy_cache[policy_metadata['policy_id']] = yaml.safe_load(policy_yaml)

        last_reload_time = current_time
```

---

## 7. Dashboard Login Flow (Cognito Authentication)

### Flow: User authenticates to Dashboard via AWS Cognito

**Architecture Context**: Dashboard is deployed on Public ALB with AWS Cognito authentication. API services are on Private ALB (no authentication, network-level security).

```
┌──────────┐
│   User   │ First visit to Dashboard
└─────┬────┘
      │ 1. Navigate to Dashboard URL
      │    https://sentra-public-alb-123.us-east-1.elb.amazonaws.com/
      ▼
┌─────────────────────────────────────────────┐
│          Public ALB (Listener Rule)         │
│  • Check for session cookie                 │
│  • No valid session found                   │
│  • Trigger Cognito authentication action    │
└─────┬───────────────────────────────────────┘
      │ 2. Redirect to Cognito login page
      │    302 Redirect to:
      │    https://sentra-dashboard-mvp.auth.us-east-1.amazoncognito.com/login?
      │      client_id=<client-id>
      │      &response_type=code
      │      &scope=openid+email+profile
      │      &redirect_uri=https://<alb-dns>/oauth2/idpresponse
      ▼
┌─────────────────────────────────────────────┐
│      AWS Cognito Hosted UI                  │
│  • Display login form                       │
│  • User enters email + password             │
│  • Validate credentials                     │
└─────┬───────────────────────────────────────┘
      │ 3. User submits credentials
      │    POST /login
      │    email: admin@sentra.com
      │    password: ************
      ▼
┌─────────────────────────────────────────────┐
│      AWS Cognito User Pool                  │
│  • Authenticate user                        │
│  • Check password policy compliance         │
│  • Verify account status (active/not locked)│
│  • Generate authorization code              │
└─────┬───────────────────────────────────────┘
      │ 4. Authentication successful
      │    302 Redirect with authorization code:
      │    https://<alb-dns>/oauth2/idpresponse?code=<auth-code>
      ▼
┌─────────────────────────────────────────────┐
│          Public ALB (OAuth Callback)        │
│  • Receive authorization code               │
│  • Exchange code for tokens:                │
│    - POST to Cognito token endpoint         │
│    - Include client_id + client_secret      │
└─────┬───────────────────────────────────────┘
      │ 5. Token exchange
      ▼
┌─────────────────────────────────────────────┐
│      AWS Cognito Token Endpoint             │
│  • Validate authorization code              │
│  • Generate tokens:                         │
│    - ID token (JWT, 1 hour)                 │
│    - Access token (JWT, 1 hour)             │
│    - Refresh token (30 days)                │
└─────┬───────────────────────────────────────┘
      │ 6. Return tokens
      ▼
┌─────────────────────────────────────────────┐
│          Public ALB                         │
│  • Receive tokens from Cognito              │
│  • Set httpOnly session cookies:            │
│    - AWSELBAuthSessionCookie-0 (encrypted)  │
│    - AWSELBAuthSessionCookie-1 (encrypted)  │
│  • Redirect to original URL (/)             │
└─────┬───────────────────────────────────────┘
      │ 7. Final redirect with session cookies
      │    302 Redirect to: https://<alb-dns>/
      │    Set-Cookie: AWSELBAuthSessionCookie-0=<encrypted-token>
      ▼
┌─────────────────────────────────────────────┐
│          Public ALB (Authenticated Request) │
│  • Receive request with session cookies     │
│  • Validate session cookies                 │
│  • Check token expiration                   │
│  • Session valid → Forward to Dashboard     │
└─────┬───────────────────────────────────────┘
      │ 8. Forward to Dashboard ECS task
      │    HTTP GET / (with user attributes in headers)
      │    x-amzn-oidc-data: <base64-encoded-jwt>
      │    x-amzn-oidc-identity: admin@sentra.com
      ▼
┌─────────────────────────────────────────────┐
│      Dashboard (Streamlit - ECS)            │
│  • Receive authenticated request            │
│  • Extract user info from headers:          │
│    - st.experimental_user.email             │
│  • Render Dashboard UI                      │
└─────┬───────────────────────────────────────┘
      │ 9. Return Dashboard HTML
      ▼
┌──────────┐
│   User   │ Dashboard displayed
└──────────┘
```

**Session Management:**

```python
# Subsequent requests (session already exists)
User Browser → Public ALB
   │
   ├─ Check session cookies
   ├─ Validate token expiration
   │
   ├─ If valid (< 1 hour) → Forward to Dashboard ✅
   │
   └─ If expired → Attempt refresh
      ├─ Use refresh token (valid for 30 days)
      ├─ Get new ID/access tokens from Cognito
      ├─ Update session cookies
      └─ Forward to Dashboard ✅

# Token expiration (after 30 days of inactivity)
User Browser → Public ALB
   │
   ├─ Refresh token expired
   └─ Redirect to Cognito login (repeat flow from step 2)
```

**Logout Flow:**

```
┌──────────┐
│   User   │ Clicks "Logout" in Dashboard
└─────┬────┘
      │ 1. POST /logout (handled by Streamlit)
      ▼
┌─────────────────────────────────────────────┐
│      Dashboard (Streamlit - ECS)            │
│  • Redirect to ALB logout endpoint          │
│    https://<alb-dns>/logout                 │
└─────┬───────────────────────────────────────┘
      │ 2. Redirect to ALB logout
      ▼
┌─────────────────────────────────────────────┐
│          Public ALB (Logout Handler)        │
│  • Clear session cookies                    │
│  • Redirect to Cognito logout endpoint      │
└─────┬───────────────────────────────────────┘
      │ 3. Redirect to Cognito logout
      │    https://sentra-dashboard-mvp.auth.us-east-1.amazoncognito.com/logout?
      │      client_id=<client-id>
      │      &logout_uri=https://<alb-dns>/
      ▼
┌─────────────────────────────────────────────┐
│      AWS Cognito                            │
│  • Revoke tokens                            │
│  • Clear Cognito session                    │
│  • Redirect to logout_uri                   │
└─────┬───────────────────────────────────────┘
      │ 4. Redirect to Dashboard homepage (logged out)
      ▼
┌──────────┐
│   User   │ Redirected to login page
└──────────┘
```

**Security Features:**

1. **Password Policy**:
   - Minimum 12 characters
   - Mixed case (uppercase + lowercase)
   - Numbers and symbols required
   - Temporary password expires in 7 days

2. **Session Security**:
   - httpOnly cookies (not accessible via JavaScript)
   - Encrypted session cookies (AES-256)
   - 1-hour token validity (automatic renewal via refresh token)
   - 30-day refresh token validity

3. **MFA (Optional)**:
   - TOTP-based (Google Authenticator, Authy, etc.)
   - Can be enabled per user
   - Not required for MVP

4. **Account Security**:
   - Account lockout after failed login attempts
   - Email verification for new users
   - Self-sign-up disabled (admin creates users)

---

## 8. Dashboard to API Services Flow (Split ALB)

### Flow: Dashboard calls API services via Private ALB

**Architecture Context**: Dashboard runs on Public ALB, API services run on Private ALB (VPC internal).

```
┌──────────────────┐
│ User (Browser)   │ Authenticated via Cognito
└─────┬────────────┘
      │ 1. Clicks "Query Customers from CA"
      ▼
┌─────────────────────────────────────────────┐
│      Dashboard (Streamlit - ECS)            │
│  • User already authenticated (session cookie)│
│  • Streamlit app receives user action       │
│  • Constructs API call to Customer Query Agent│
└─────┬───────────────────────────────────────┘
      │ 2. Internal API call (VPC traffic)
      │    POST http://sentra-private-alb-internal.us-east-1.elb.amazonaws.com/v1/agents/customer-query/query
      │    Body: {"message": "Show customers from CA", "session_id": "sess-123"}
      │
      │    NOTE: No authentication header needed (Private ALB, network security)
      ▼
┌─────────────────────────────────────────────┐
│      Private ALB (VPC Internal)             │
│  • Receive request from Dashboard           │
│  • Match path pattern: /v1/agents/customer-query/*│
│  • Route to Customer Query Agent target group│
│  • No authentication check (internal traffic)│
└─────┬───────────────────────────────────────┘
      │ 3. Forward to Customer Query Agent
      ▼
┌─────────────────────────────────────────────┐
│      Customer Query Agent (ECS)             │
│  • Receive query request                    │
│  • LangChain parses intent                  │
│  • Selects tool: query_customers()          │
└─────┬───────────────────────────────────────┘
      │ 4. Call Security Controller for validation
      │    POST http://sentra-private-alb-internal.us-east-1.elb.amazonaws.com/v1/validate
      │    Body: {"session_id": "sess-123", "agent_id": "customer-query", "tool_name": "query_customers", ...}
      ▼
┌─────────────────────────────────────────────┐
│      Private ALB (VPC Internal)             │
│  • Match path pattern: /v1/validate*        │
│  • Route to Security Controller target group│
└─────┬───────────────────────────────────────┘
      │ 5. Forward to Security Controller
      ▼
┌─────────────────────────────────────────────┐
│      Security Controller (ECS)              │
│  • Validate tool call                       │
│  • Decision: ALLOW                          │
└─────┬───────────────────────────────────────┘
      │ 6. Return ALLOW to Customer Query Agent
      ▼
┌─────────────────────────────────────────────┐
│      Customer Query Agent (ECS)             │
│  • Execute tool: query_customers()          │
│  • Query DynamoDB: sentra-demo-customers    │
│  • Filter by state = 'CA'                   │
│  • Format results                           │
└─────┬───────────────────────────────────────┘
      │ 7. Return results to Dashboard
      │    Response flows back:
      │    CQA → Private ALB → Dashboard
      ▼
┌─────────────────────────────────────────────┐
│      Dashboard (Streamlit - ECS)            │
│  • Receive query results                    │
│  • Display in Streamlit table               │
└─────┬───────────────────────────────────────┘
      │ 8. Render results in browser
      ▼
┌──────────────────┐
│ User (Browser)   │ Sees customer list
└──────────────────┘
```

**Network Flow Details:**

```
Public Network:
  User Browser ←→ Public ALB (with Cognito) ←→ Dashboard ECS
                                                    ↓
                                                    │ Internal VPC traffic
                                                    ▼
Private Network (VPC):
  Dashboard ECS ←→ Private ALB ←→ Security Controller ECS
                               ←→ Customer Query Agent ECS
                               ←→ Payment Agent ECS
```

**Security Isolation:**

1. **Public ALB** (Internet-facing):
   - Only Dashboard exposed to internet
   - Cognito authentication required
   - Security group: Allow HTTP/HTTPS from 0.0.0.0/0
   - Target: Dashboard ECS tasks only

2. **Private ALB** (VPC Internal):
   - NOT accessible from internet (no public IP)
   - No authentication (network-level security)
   - Security groups:
     - Allow from Dashboard security group
     - Allow from API service security groups (for inter-service calls)
   - Targets: Security Controller, Customer Query Agent, Payment Agent

3. **ECS Tasks** (All in private subnets):
   - No public IPs
   - Egress via NAT Gateway (for AWS API calls)
   - Security groups enforce least privilege

**Environment Variables** (Dashboard ECS task):

```python
# Dashboard container environment variables
SECURITY_CONTROLLER_URL=http://sentra-private-alb-internal.us-east-1.elb.amazonaws.com
CUSTOMER_QUERY_AGENT_URL=http://sentra-private-alb-internal.us-east-1.elb.amazonaws.com
PAYMENT_AGENT_URL=http://sentra-private-alb-internal.us-east-1.elb.amazonaws.com

# All API calls go through Private ALB
# Private ALB routes to correct service based on path pattern
```

**Key Differences from Single ALB**:

| Aspect | Single ALB (Old) | Split ALB (New) |
|--------|------------------|-----------------|
| Dashboard Access | Public (no auth) ❌ | Public (with Cognito) ✅ |
| API Services Access | Public ❌ | Private (VPC only) ✅ |
| Fault Isolation | None (single point of failure) | Dashboard failures don't affect APIs ✅ |
| Security Posture | Lower (all services exposed) | Higher (defense in depth) ✅ |
| AppSec Compliance | Violation (triggers remediation) ❌ | Compliant ✅ |

---

## Summary

**Key Takeaways:**

1. **EVERY tool call** is validated by Security Controller (no exceptions)
2. **Session context** (DynamoDB) tracks current state, **audit logs** (CloudWatch) record history
3. **Multi-agent flows** use `parent_request_id` and `caller_agent_id` to link requests
4. **Policies** are stored in S3 (large YAML), DynamoDB stores metadata only
5. **Dashboard** queries CloudWatch Logs API (no websockets needed, 5s refresh)
6. **Validation** happens in ~50-100ms (session load + rules + policy + logging)
7. **Dashboard authentication** via AWS Cognito OAuth 2.0 flow (httpOnly cookies, 1-hour sessions)
8. **Split ALB architecture** isolates public UI (Dashboard) from private APIs (Security Controller, Agents)
9. **Network security**: Dashboard → Private ALB → API services (all internal VPC traffic)

**Next:** See `demo.md` for specific demo scenarios and test cases.
