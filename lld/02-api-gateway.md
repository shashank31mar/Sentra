# LLD 02: API Gateway Layer

**Version:** 2.0
**Last Updated:** 2025-11-12
**Status:** Ready for Review
**Prerequisites:** [LLD 01: CDK Infrastructure](./01-cdk-infrastructure.md)

---

## Table of Contents

1. [Overview](#1-overview)
2. [API Endpoints & Rate Limits](#2-api-endpoints--rate-limits)
3. [CDK Configuration](#3-cdk-configuration)
4. [Integration with ECS](#4-integration-with-ecs)
5. [Authentication](#5-authentication)
6. [CORS](#6-cors)
7. [Monitoring](#7-monitoring)

---

## 1. Overview

### 1.1 Purpose

API Gateway is the **single public entry point** for Sentra MVP. It provides:
- API key authentication
- Rate limiting per endpoint
- Request validation (JSON schema)
- VPC Link to private ECS services
- CORS for Dashboard access

### 1.2 Architecture

```
External User (Dashboard/Postman)
         │
         ▼ HTTPS
┌────────────────────────────┐
│   API Gateway (Public)     │
│  • API Key validation      │
│  • Rate limiting           │
│  • Request validation      │
└────────┬───────────────────┘
         │ VPC Link
         ▼
┌────────────────────────────┐
│  Application Load Balancer │
│  • Path-based routing      │
│  • Health checks           │
└────────┬───────────────────┘
         │
    ┌────┴─────┬──────────┐
    ▼          ▼          ▼
Security      Customer    Payment
Controller    Query Agent Agent
  (ECS)         (ECS)     (ECS)
```

**Design Decision:** Use ALB (not NLB) for Layer 7 path-based routing to different ECS services.

---

## 2. API Endpoints & Rate Limits

### 2.1 Endpoints Summary

| Endpoint | Method | Target Service | Rate Limit | Purpose |
|----------|--------|----------------|------------|---------|
| `/v1/validate` | POST | Security Controller | 100 req/min | Validate agent tool calls |
| `/v1/health` | GET | Security Controller | 1000 req/min | Health check (no auth) |
| `/v1/logs` | GET | Security Controller | 50 req/min | Query audit logs for Dashboard |
| `/v1/rollback` | POST | Security Controller | 10 req/min | Rollback action (future, returns 501) |
| `/v1/agents/customer-query/query` | POST | Customer Query Agent | 20 req/min | Natural language queries (read operations) |
| `/v1/agents/customer-query/action` | POST | Customer Query Agent | 10 req/min | Natural language actions (write operations) |
| `/v1/agents/payment/query` | POST | Payment Agent | 20 req/min | Natural language queries (read operations) |
| `/v1/agents/payment/action` | POST | Payment Agent | 10 req/min | Natural language actions (write operations) |

### 2.2 Rate Limit Rationale

| Endpoint | Limit | Why |
|----------|-------|-----|
| `/validate` | 100/min | Primary endpoint, high traffic expected |
| `/health` | 1000/min | Monitoring pings, no restrictive limit |
| `/logs` | 50/min | Dashboard polling, moderate traffic |
| `/rollback` | 10/min | Rare operation, prevent abuse |
| `/agents/{agent-id}/query` | 20/min | Read operations (all agents), reasonable query rate |
| `/agents/{agent-id}/action` | 10/min | Write operations (all agents), conservative limit |

**Global Limits (Usage Plan):**
- Burst: 200 requests
- Quota: 100,000 requests/month

---

## 3. CDK Configuration

### 3.1 REST API

```python
from aws_cdk import (
    aws_apigateway as apigateway,
    Duration
)

# Create REST API
api = apigateway.RestApi(
    self, "SentraApi",
    rest_api_name="sentra-mvp-api",
    description="Sentra MVP Public API",

    # Enable CORS for Dashboard
    default_cors_preflight_options=apigateway.CorsOptions(
        allow_origins=apigateway.Cors.ALL_ORIGINS,  # MVP: allow all
        allow_methods=apigateway.Cors.ALL_METHODS,
        allow_headers=[
            "Content-Type",
            "X-Api-Key",
            "Authorization"
        ],
        max_age=Duration.hours(1)
    ),

    # Enable CloudWatch logging
    deploy_options=apigateway.StageOptions(
        stage_name="prod",
        metrics_enabled=True,
        logging_level=apigateway.MethodLoggingLevel.INFO,
        data_trace_enabled=False,  # Don't log request/response bodies (security)
        throttling_rate_limit=100,  # Global rate limit
        throttling_burst_limit=200
    )
)
```

### 3.2 API Key & Usage Plan

```python
# Create API key
api_key = apigateway.ApiKey(
    self, "SentraDemoApiKey",
    api_key_name="sentra-demo-key",
    description="API key for Sentra MVP demo",
    enabled=True
)

# Create usage plan with rate limits
usage_plan = apigateway.UsagePlan(
    self, "SentraUsagePlan",
    name="sentra-mvp-usage-plan",
    description="Usage plan for Sentra MVP",

    # Global throttling
    throttle=apigateway.ThrottleSettings(
        rate_limit=100,  # Requests per second
        burst_limit=200  # Burst capacity
    ),

    # Monthly quota
    quota=apigateway.QuotaSettings(
        limit=100000,  # 100K requests per month
        period=apigateway.Period.MONTH
    )
)

# Associate API key with usage plan
usage_plan.add_api_key(api_key)
usage_plan.add_api_stage(
    stage=api.deployment_stage
)

# Export API key ID (retrieve value with AWS CLI)
CfnOutput(self, "ApiKeyId", value=api_key.key_id)
```

**Retrieve API Key Value:**
```bash
aws apigateway get-api-key \
  --api-key <key-id-from-output> \
  --include-value \
  --query 'value' \
  --output text
```

### 3.3 VPC Link to ALB

```python
from aws_cdk import aws_elasticloadbalancingv2 as elbv2

# Create Application Load Balancer (from ComputeStack)
alb = elbv2.ApplicationLoadBalancer(
    self, "SentraALB",
    vpc=vpc,
    internet_facing=False,  # Private ALB
    load_balancer_name="sentra-alb"
)

# Create VPC Link
vpc_link = apigateway.VpcLink(
    self, "SentraVpcLink",
    description="VPC Link to Sentra ECS services",
    targets=[alb],
    vpc_link_name="sentra-vpc-link"
)

# Integration to ALB
integration = apigateway.Integration(
    type=apigateway.IntegrationType.HTTP_PROXY,
    integration_http_method="ANY",
    uri=f"http://{alb.load_balancer_dns_name}/{{proxy}}",
    connection_type=apigateway.ConnectionType.VPC_LINK,
    vpc_link=vpc_link,

    # Inject headers
    request_parameters={
        "integration.request.path.proxy": "method.request.path.proxy",
        "integration.request.header.X-Correlation-ID": "context.requestId",
        "integration.request.header.X-API-Key-ID": "context.identity.apiKeyId"
    }
)
```

**Design Decision: ALB vs NLB**
- ✅ ALB supports path-based routing (route different paths to different ECS services)
- ✅ ALB supports HTTP/HTTPS (Layer 7)
- ❌ NLB only supports TCP (Layer 4) - would need separate VPC Links per service

### 3.4 API Resources & Methods

```python
# Root resource: /v1
v1 = api.root.add_resource("v1")

# Security Controller endpoints
validate = v1.add_resource("validate")
validate.add_method(
    "POST",
    integration,
    api_key_required=True,
    request_validator=apigateway.RequestValidator(
        self, "ValidateRequestValidator",
        rest_api=api,
        validate_request_body=True,
        validate_request_parameters=True
    )
)

health = v1.add_resource("health")
health.add_method(
    "GET",
    integration,
    api_key_required=False  # Health check doesn't need auth
)

logs = v1.add_resource("logs")
logs.add_method(
    "GET",
    integration,
    api_key_required=True
)

rollback = v1.add_resource("rollback")
rollback.add_method(
    "POST",
    integration,
    api_key_required=True
)

# Agent endpoints (standardized interface)
agents = v1.add_resource("agents")

# Customer Query Agent
customer_query = agents.add_resource("customer-query")

# /query endpoint (read operations)
customer_query_query = customer_query.add_resource("query")
customer_query_query.add_method(
    "POST",
    integration,
    api_key_required=True
)

# /action endpoint (write operations)
customer_query_action = customer_query.add_resource("action")
customer_query_action.add_method(
    "POST",
    integration,
    api_key_required=True
)

# Payment Agent
payment = agents.add_resource("payment")

# /query endpoint (read operations)
payment_query = payment.add_resource("query")
payment_query.add_method(
    "POST",
    integration,
    api_key_required=True
)

# /action endpoint (write operations)
payment_action = payment.add_resource("action")
payment_action.add_method(
    "POST",
    integration,
    api_key_required=True
)
```

### 3.5 Standardized Agent Interface Design

**Key Design Decision**: All agents expose **both** `/query` AND `/action` endpoints for consistency and scalability.

**Benefits**:
1. **Consistent API**: Same interface pattern for all agents
2. **Different rate limits**: Stricter limits on writes (actions) vs reads (queries)
3. **Security policies**: Can apply different rules (e.g., quarantined agents can only query, not act)
4. **Scalability**: Easy to add new agents without API changes

**Usage Examples**:
```bash
# Customer Query Agent - Read operation
curl -X POST https://api.sentra.ai/v1/agents/customer-query/query \
  -H "X-API-Key: ${API_KEY}" \
  -d '{"message": "Show customers from California"}'

# Customer Query Agent - Write operation (if needed)
curl -X POST https://api.sentra.ai/v1/agents/customer-query/action \
  -H "X-API-Key: ${API_KEY}" \
  -d '{"message": "Update customer email for customer 12345"}'

# Payment Agent - Read operation
curl -X POST https://api.sentra.ai/v1/agents/payment/query \
  -H "X-API-Key: ${API_KEY}" \
  -d '{"message": "Check refund status for order 12345"}'

# Payment Agent - Write operation
curl -X POST https://api.sentra.ai/v1/agents/payment/action \
  -H "X-API-Key: ${API_KEY}" \
  -d '{"message": "Process refund for order 12345"}'
```

### 3.6 Per-Method Rate Limiting

```python
# Apply method-specific rate limits (override global)
validate_method = validate.node.find_child("POST")
cfn_method = validate_method.node.default_child

cfn_method.add_property_override("ThrottleSettings", {
    "RateLimit": 100,  # 100 req/min
    "BurstLimit": 200
})

# Logs endpoint (lower limit)
logs_method = logs.node.find_child("GET")
cfn_logs_method = logs_method.node.default_child

cfn_logs_method.add_property_override("ThrottleSettings", {
    "RateLimit": 50,  # 50 req/min
    "BurstLimit": 100
})

# Agent /query endpoints (all agents, read operations)
for agent_name in ["customer-query", "payment"]:
    query_method = agents.node.find_child(agent_name).node.find_child("query").node.find_child("POST")
    cfn_query_method = query_method.node.default_child
    cfn_query_method.add_property_override("ThrottleSettings", {
        "RateLimit": 20,  # 20 req/min
        "BurstLimit": 40
    })

# Agent /action endpoints (all agents, write operations - stricter)
for agent_name in ["customer-query", "payment"]:
    action_method = agents.node.find_child(agent_name).node.find_child("action").node.find_child("POST")
    cfn_action_method = action_method.node.default_child
    cfn_action_method.add_property_override("ThrottleSettings", {
        "RateLimit": 10,  # 10 req/min (conservative for writes)
        "BurstLimit": 20
    })
```

---

## 4. Integration with ECS

### 4.1 ALB Target Groups

```python
# Security Controller target group
security_controller_tg = elbv2.ApplicationTargetGroup(
    self, "SecurityControllerTG",
    vpc=vpc,
    port=8080,
    protocol=elbv2.ApplicationProtocol.HTTP,
    target_type=elbv2.TargetType.IP,
    health_check=elbv2.HealthCheck(
        path="/health",
        interval=Duration.seconds(30),
        healthy_threshold_count=2
    )
)

# Customer Query Agent target group
customer_query_agent_tg = elbv2.ApplicationTargetGroup(
    self, "CustomerQueryAgentTG",
    vpc=vpc,
    port=8002,
    protocol=elbv2.ApplicationProtocol.HTTP,
    target_type=elbv2.TargetType.IP
)

# Payment Agent target group
payment_agent_tg = elbv2.ApplicationTargetGroup(
    self, "PaymentAgentTG",
    vpc=vpc,
    port=8003,
    protocol=elbv2.ApplicationProtocol.HTTP,
    target_type=elbv2.TargetType.IP
)
```

### 4.2 ALB Listener Rules (Path-Based Routing)

```python
listener = alb.add_listener(
    "HttpListener",
    port=80,
    protocol=elbv2.ApplicationProtocol.HTTP
)

# Route /v1/validate, /v1/health, /v1/logs, /v1/rollback to Security Controller
listener.add_targets(
    "SecurityControllerTarget",
    port=8080,
    targets=[security_controller_service],
    conditions=[
        elbv2.ListenerCondition.path_patterns([
            "/v1/validate",
            "/v1/health",
            "/v1/logs",
            "/v1/rollback"
        ])
    ],
    priority=1
)

# Route /v1/agents/customer-query/* to Customer Query Agent
listener.add_targets(
    "CustomerQueryAgentTarget",
    port=8002,
    targets=[customer_query_agent_service],
    conditions=[
        elbv2.ListenerCondition.path_patterns(["/v1/agents/customer-query/*"])
    ],
    priority=2
)

# Route /v1/agents/payment/* to Payment Agent
listener.add_targets(
    "PaymentAgentTarget",
    port=8003,
    targets=[payment_agent_service],
    conditions=[
        elbv2.ListenerCondition.path_patterns(["/v1/agents/payment/*"])
    ],
    priority=3
)
```

---

## 5. Authentication

### 5.1 API Key Authentication

All endpoints (except `/health`) require `X-API-Key` header.

**Flow:**
```
1. User sends request with X-API-Key header
2. API Gateway validates key against usage plan
3. If valid → forward to backend
4. If invalid → return 403 Forbidden
```

**No backend validation needed** - API Gateway handles authentication.

### 5.2 Security Considerations

| Risk | Mitigation |
|------|------------|
| **API key leakage** | Store in AWS Secrets Manager, rotate quarterly |
| **Key theft** | HTTPS-only (no HTTP endpoint) |
| **Unauthorized access** | Usage plan limits blast radius (100 req/min) |
| **Key sharing** | Unique keys per environment (dev/staging/prod) |

---

## 6. CORS

### 6.1 Configuration

```python
default_cors_preflight_options=apigateway.CorsOptions(
    allow_origins=apigateway.Cors.ALL_ORIGINS,  # MVP: allow all
    allow_methods=apigateway.Cors.ALL_METHODS,
    allow_headers=[
        "Content-Type",
        "X-Api-Key",
        "Authorization"
    ],
    max_age=Duration.hours(1)
)
```

**Production:** Change `allow_origins` to specific Dashboard URL:
```python
allow_origins=["https://dashboard.sentra.com"]
```

### 6.2 Preflight Response

**OPTIONS /v1/validate**

Request:
```http
OPTIONS /v1/validate HTTP/1.1
Origin: http://localhost:8501
Access-Control-Request-Method: POST
Access-Control-Request-Headers: X-API-Key, Content-Type
```

Response:
```http
HTTP/1.1 200 OK
Access-Control-Allow-Origin: *
Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS
Access-Control-Allow-Headers: Content-Type, X-API-Key, Authorization
Access-Control-Max-Age: 3600
```

---

## 7. Monitoring

### 7.1 CloudWatch Metrics

**API Gateway automatically publishes:**

| Metric | Alert Threshold | Action |
|--------|----------------|--------|
| `4XXError` | > 5% of requests | Check request validation |
| `5XXError` | > 1% of requests | Check backend health |
| `Latency` (p99) | > 5s | Check ECS/ALB performance |
| `Count` | Track total traffic | - |

### 7.2 CloudWatch Alarms

```python
# High error rate alarm
error_alarm = cloudwatch.Alarm(
    self, "ApiGateway5XXErrorAlarm",
    alarm_name="sentra-api-5xx-errors",
    metric=api.metric_server_error(
        period=Duration.minutes(5),
        statistic="Sum"
    ),
    threshold=10,  # More than 10 errors in 5 minutes
    evaluation_periods=1
)

# High latency alarm
latency_alarm = cloudwatch.Alarm(
    self, "ApiGatewayLatencyAlarm",
    alarm_name="sentra-api-high-latency",
    metric=api.metric_latency(
        period=Duration.minutes(5),
        statistic="p99"
    ),
    threshold=5000,  # p99 > 5 seconds
    evaluation_periods=2
)
```

### 7.3 Access Logs

```python
log_group = logs.LogGroup(
    self, "ApiGatewayAccessLogs",
    log_group_name="/aws/apigateway/sentra-mvp",
    retention=logs.RetentionDays.ONE_MONTH
)

api = apigateway.RestApi(
    self, "SentraApi",
    deploy_options=apigateway.StageOptions(
        access_log_destination=apigateway.LogGroupLogDestination(log_group),
        access_log_format=apigateway.AccessLogFormat.json_with_standard_fields(
            caller=True,
            http_method=True,
            ip=True,
            request_time=True,
            status=True
        )
    )
)
```

**Log Format:**
```json
{
  "requestId": "abc-123",
  "ip": "203.0.113.45",
  "requestTime": "2025-11-12T10:30:00Z",
  "httpMethod": "POST",
  "resourcePath": "/v1/validate",
  "status": 200,
  "responseLatency": 150
}
```

---

## Summary

### What API Gateway Provides

✅ **Single Public Entry Point** - All traffic goes through one gateway
✅ **API Key Authentication** - No backend validation needed
✅ **Rate Limiting** - Per-endpoint limits (10-1000 req/min)
✅ **Request Validation** - JSON schema validation at gateway
✅ **VPC Link + ALB** - Routes to private ECS services
✅ **CORS** - Enables Dashboard browser access
✅ **Monitoring** - CloudWatch metrics, alarms, access logs

### CDK Resources Created

1. REST API (`sentra-mvp-api`)
2. API Key (`sentra-demo-key`)
3. Usage Plan (rate limits + quota)
4. VPC Link (to private ALB)
5. 6 API resources with methods
6. CloudWatch Log Group (access logs)
7. CloudWatch Alarms (errors, latency)

### Next LLD

See [LLD 03: Security Controller](./03-security-controller.md) for validation logic and Sigma rules.

---

**End of LLD 02: API Gateway Layer**
