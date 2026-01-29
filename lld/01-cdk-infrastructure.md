# CDK Infrastructure - Low-Level Design (LLD)

**Component**: AWS CDK Infrastructure
**Version**: 2.0 (Simplified)
**Date**: January 14, 2025
**Status**: Ready for Implementation

---

## Table of Contents

1. [Overview](#1-overview)
2. [Network Stack](#2-network-stack)
3. [Storage Stack](#3-storage-stack)
4. [Compute Stack](#4-compute-stack)
5. [API Stack](#5-api-stack)
6. [Monitoring Stack](#6-monitoring-stack)
7. [Deployment Guide](#7-deployment-guide)
8. [Cross-References](#8-cross-references)

---

## 1. Overview

### 1.1 Purpose

The CDK infrastructure provides the complete AWS deployment for Sentra MVP using Infrastructure as Code (IaC). All resources are defined using AWS CDK (Python) and deployed via CloudFormation.

### 1.2 Stack Architecture

```
┌─────────────────────────────────────────────────────────┐
│              CDK App (app.py)                           │
└─────────────────────────────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
        ▼                  ▼                  ▼
┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│ NetworkStack  │  │ StorageStack  │  │ ComputeStack  │
│ • VPC         │  │ • CloudWatch  │  │ • ECS Cluster │
│ • Route53     │  │ • DynamoDB(5) │  │ • ECR (4)     │
│ • Security    │  │ • S3 Bucket   │  │ • Tasks (4)   │
│   Groups (5)  │  │               │  │ • Services(4) │
│ • VPC         │  │               │  │ • IAM Roles   │
│   Endpoints(5)│  │               │  │               │
└───────┬───────┘  └───────┬───────┘  └───────┬───────┘
        │                  │                  │
        └──────────────────┴──────────────────┤
                           │                  │
        ┌──────────────────┴──────────┐      │
        ▼                             ▼      │
┌───────────────┐            ┌───────────────┐│
│   ApiStack    │            │MonitoringStack││
│ • API Gateway │            │ • Dashboard   ││
│ • VPC Link    │            │ • Alarms (6)  ││
│ • Usage Plans │            │ • SNS Topic   ││
└───────────────┘            └───────────────┘│
                                              │
                   Depends on all stacks ─────┘
```

### 1.3 Deployment Order

CDK automatically resolves dependencies. Logical deployment order:

1. **NetworkStack** (5-7 min) → VPC, Route53, Security Groups, VPC Endpoints
2. **StorageStack** (3-5 min) → CloudWatch Logs, DynamoDB (5 tables), S3
3. **ComputeStack** (8-10 min) → ECS cluster, ECR, Task definitions, Services
4. **ApiStack** (2-3 min) → API Gateway, VPC Link, API Keys
5. **MonitoringStack** (2-3 min) → CloudWatch dashboard, Alarms, SNS

**Total Deployment Time**: 20-30 minutes

### 1.4 AWS Services Summary

| Service | Count | Purpose |
|---------|-------|---------|
| VPC | 1 | Private network isolation |
| Route53 Private Zone | 1 | Internal service discovery |
| Security Groups | 5 | Network access control |
| VPC Endpoints | 5 | Private AWS service access |
| DynamoDB Tables | 5 | Persistent storage |
| S3 Buckets | 1 | Artifacts (Sigma rules, policies, SBOM) |
| ECS Cluster | 1 | Container orchestration |
| ECR Repositories | 4 | Container images |
| ECS Services | 4 | Long-running containers |
| API Gateway | 1 | Public REST API |
| CloudWatch Alarms | 6 | Alerting |

**Region**: us-east-1 (parameterizable)

**See ADR-011 through ADR-017** for infrastructure design decisions.

---

## 2. Network Stack

### 2.1 VPC Configuration

**CIDR Allocation**:
```
VPC: 10.0.0.0/16

Subnets (2 AZs):
├── Private Subnet 1 (us-east-1a): 10.0.1.0/24 → ECS services
├── Private Subnet 2 (us-east-1b): 10.0.2.0/24 → ECS services (HA)
├── Isolated Subnet 1 (us-east-1a): 10.0.3.0/28 → VPC endpoints
└── Isolated Subnet 2 (us-east-1b): 10.0.4.0/28 → VPC endpoints
```

**Key Configuration**:
- **No Public Subnets**: All services private (see ADR-011)
- **1 NAT Gateway**: us-east-1a only (MVP cost optimization)
- **VPC Flow Logs**: 7-day retention for security audit

**CDK Structure** (Network Stack creation - standard VPC setup):
```python
# Create VPC with private subnets and NAT gateway
self.vpc = ec2.Vpc(self, "SentraMvpVpc",
    ip_addresses=ec2.IpAddresses.cidr("10.0.0.0/16"),
    max_azs=2, nat_gateways=1,
    subnet_configuration=[...])  # See ADR-011 for details
```

### 2.2 Route53 Private Hosted Zone

**Configuration**:
```
Zone: sentra.internal

DNS Records (auto-registered by ECS Service Discovery):
├── security-controller.sentra.internal
├── dashboard.sentra.internal
├── customer-query-agent.sentra.internal
└── payment-agent.sentra.internal
```

### 2.3 Security Groups

**Security Group Rules** (5 total):

| Security Group | Inbound | Outbound | Purpose |
|----------------|---------|----------|---------|
| **security-controller-sg** | TCP 8080 from: dashboard-sg, customer-query-agent-sg, payment-agent-sg, alb-sg | All traffic | Validation API |
| **dashboard-sg** | TCP 8501 from alb-sg | TCP 8080 to security-controller-sg, All traffic | Dashboard UI |
| **customer-query-agent-sg** | TCP 8080 from alb-sg | TCP 8080 to security-controller-sg, All traffic | Query agent API |
| **payment-agent-sg** | TCP 8080 from alb-sg | TCP 8080 to security-controller-sg, All traffic | Payment agent API |
| **alb-sg** | TCP 443 from 0.0.0.0/0 | TCP 8080, 8501, 8080, 8080 to respective SGs | Load balancer |

**See ADR-015** for security group design rationale.

### 2.4 VPC Endpoints

**Endpoint Configuration** (5 total):

**Interface Endpoints** (3):
- ECR Docker (`com.amazonaws.us-east-1.ecr.dkr`)
- ECR API (`com.amazonaws.us-east-1.ecr.api`)
- CloudWatch Logs (`com.amazonaws.us-east-1.logs`)

**Gateway Endpoints** (2, FREE):
- S3 (`com.amazonaws.us-east-1.s3`)
- DynamoDB (`com.amazonaws.us-east-1.dynamodb`)

**See ADR-014** for VPC endpoint strategy.

### 2.5 Stack Outputs

Exports: VPC ID, Private Hosted Zone ID, Security Group IDs (5)

---

## 3. Storage Stack

### 3.1 Purpose

Provides persistent storage for:
- **Audit logs** → CloudWatch Logs (write-heavy, immutable)
- **Session state** → DynamoDB (read-heavy, < 10ms latency)
- **Policies** → DynamoDB + S3 (large YAML files)
- **Demo data** → DynamoDB (orders, customers)
- **Artifacts** → S3 (Sigma rules, SBOM, exports)

**See ADR-013** for CloudWatch Logs vs DynamoDB decision.

### 3.2 CloudWatch Log Group

**Configuration**:
```
Log Group: /sentra/audit-logs
├── Retention: 90 days
├── Removal Policy: RETAIN (compliance)
└── Purpose: Immutable audit trail of all validation decisions
```

**Log Event Schema** (JSON, 256 KB limit):
```json
{
  "request_id": "req-abc123",
  "timestamp": 1736611200000,
  "session_id": "sess-xyz789",
  "conversation_id": "conv-xyz-001",
  "agent_id": "payment-agent",
  "tool_name": "process_refund",
  "decision": "DENY",  // ALLOW | DENY | REDACT
  "reason": "Refund $500 exceeds manager limit",
  "matched_rules": [...],
  "threat_type": "POLICY_VIOLATION",
  "validation_duration_ms": 45
}
```

**Access Patterns**:
```
1. Get session logs: Filter by log stream (session_id)
2. Query blocked requests: CloudWatch Insights (decision = "DENY")
3. Query by agent: Filter agent_id
4. Count threats: Stats by threat_type
```

### 3.3 DynamoDB Tables

All tables use **on-demand billing** (see ADR-013).

#### **Table 1: sentra-session-context**

**Purpose**: Track CURRENT state of active sessions for real-time policy decisions

**Schema**:
```
Partition Key: session_id (STRING)

Key Attributes:
├── session_id, user_id, agent_id
├── created_at, last_activity
├── total_requests, allow_count, deny_count, redact_count
├── tool_history (LIST<MAP>) - Last 10 tools, FIFO
├── risk_score, consecutive_denies
├── quarantine_status ("active" | "quarantined" | "suspended")
├── abuse_counters (MAP) - requests_last_minute, denials_last_hour
├── authorization_level, approved_tools
└── ttl (24 hours)

GSI: agent-updated-index (agent_id, last_activity)
TTL: 24 hours
Point-in-Time Recovery: Disabled (ephemeral data)
```

**Access Patterns**:
```
1. GetItem(session_id) - MOST FREQUENT (every validation, < 10ms)
2. UpdateItem(session_id) - Increment counters after validation
3. Query GSI (agent_id) - Get all active sessions for agent
```

#### **Table 2: sentra-policies**

**Purpose**: Store policy metadata (actual YAML in S3)

**Schema**:
```
Partition Key: policy_id (STRING)

Attributes:
├── policy_id, agent_id, tool_name
├── policy_yaml_s3 (S3 path to full YAML)
├── policy_yaml_checksum (SHA256)
├── version, is_active
├── created_at, updated_at, created_by
└── description

GSI: agent-version-index (agent_id, version DESC)
Streams: Enabled (audit policy changes)
Point-in-Time Recovery: Enabled (critical config)
```

**Why DynamoDB + S3 pattern?**
- Policy YAML can be 10KB+ (complex business rules)
- DynamoDB stores metadata, S3 stores content
- S3 versioning for rollback

#### **Table 3: sentra-demo-orders**

**Purpose**: Mock order database for demo

**Schema**:
```
Partition Key: order_id (STRING)

Attributes:
├── order_id, customer_id, customer_name
├── amount, status, order_date
├── items (LIST), shipping_address (MAP)

GSI: customer-index (customer_id, created_at)
Pre-seeded: 500 sample orders
```

#### **Table 4: sentra-demo-customers**

**Purpose**: Mock customer database (data exfiltration demo)

**Schema**:
```
Partition Key: customer_id (STRING)

Attributes:
├── customer_id, name, email
├── ssn (FAKE, for PII detection demo)
├── phone, state, created_at
└── account_status

GSI: state-index (state, created_at)
Pre-seeded: 500 sample customers
```

**Distribution**: 150 CA, 100 NY, 80 TX, 70 FL, 100 other

#### **Table 5: sentra-trust-scores** (FUTURE)

**Purpose**: Per-session trust scoring (Phase 2)

**Schema**:
```
Partition Key: session_id (STRING)
Sort Key: timestamp (NUMBER)

Attributes:
├── session_id, timestamp
├── trust_score (0-100)
├── score_delta, reason
├── event_type ("deny" | "allow" | "quarantine")
└── metadata (MAP)

GSI: agent-score-index (agent_id, timestamp)
TTL: 30 days
```

### 3.4 S3 Bucket

**Configuration**:
```
Bucket: sentra-mvp-artifacts
Region: us-east-1
Encryption: S3-Managed (SSE-S3)
Versioning: Enabled (rollback)
Public Access: Blocked
```

**Folder Structure**:
```
s3://sentra-mvp-artifacts/
├── policies/                    # Large policy YAML files (10KB+)
│   ├── refund-limit-policy-v1.yaml
│   └── data-export-policy-v1.yaml
│
├── sigma_rules/llm/             # Threat detection patterns
│   ├── prompt_injection_basic.yaml
│   ├── jailbreak_attempts.yaml
│   ├── data_exfiltration.yaml
│   ├── sql_injection_detection.yaml
│   └── excessive_agency.yaml
│
├── sbom/                        # CycloneDX SBOMs
│   ├── security-controller/sbom-v1.0.0.json
│   ├── customer-query-agent/sbom-v1.0.0.json
│   ├── payment-agent/sbom-v1.0.0.json
│   └── dashboard/sbom-v1.0.0.json
│
├── compliance_exports/          # SOC2, HIPAA reports
│   └── 2025-01/...
│
└── debug_logs/                  # Request traces (7-day retention)
    └── 2025-01-11/...
```

**Lifecycle Policies**:
- Archive `compliance_exports/` to Glacier after 30 days
- Delete `debug_logs/` after 7 days
- Keep `sigma_rules/`, `sbom/`, `policies/` forever

### 3.5 Stack Outputs

Exports: CloudWatch Log Group name, DynamoDB table names (5), S3 bucket name/ARN

---

## 4. Compute Stack

### 4.1 ECS Cluster

**Configuration**:
```python
cluster = ecs.Cluster(self, "SentraMvpCluster",
    cluster_name="sentra-mvp-cluster",
    vpc=vpc,
    container_insights=True)  # CloudWatch monitoring
```

**See ADR-001** for ECS Fargate choice.

### 4.2 ECR Repositories

**4 Repositories**:
```
1. sentra/security-controller
2. sentra/dashboard
3. sentra/customer-query-agent
4. sentra/payment-agent

All with:
├── Image scanning: Enabled
├── Lifecycle: Keep last 10 images
└── Tag mutability: Mutable (MVP only)
```

### 4.3 Task Definitions

**Standard Configuration** (all 4 services):
```
├── CPU: 2048 (2 vCPU)
├── Memory: 4096 (4 GB)
├── Network Mode: awsvpc (Fargate required)
├── Logging: CloudWatch Logs (/ecs/sentra/<service>)
└── Log Retention: 7 days
```

**See ADR-016** for task sizing rationale.

#### **Task 1: Security Controller**

**Container Spec**:
```
Port: 8080
Image: {ECR}/sentra/security-controller:latest

Environment Variables (12):
├── SESSION_CONTEXT_TABLE=sentra-session-context
├── POLICIES_TABLE=sentra-policies
├── ARTIFACTS_BUCKET=sentra-mvp-artifacts
├── AWS_REGION=us-east-1
├── LOG_LEVEL=INFO
├── SIGMA_RULES_PREFIX=sigma_rules/llm/
├── SIGMA_REFRESH_INTERVAL=300
├── POLICY_CACHE_TTL=300
├── MAX_VALIDATION_TIME_MS=5000
└── ENABLE_METRICS=true

Health Check:
├── Command: curl -f http://localhost:8080/v1/health
├── Interval: 30s, Timeout: 5s, Retries: 3
```

**IAM Permissions**:
- DynamoDB: Read/Write `session-context`, Read `policies`
- S3: Read `sigma_rules/*`, `policies/*`; Write `debug_logs/*`
- CloudWatch: PutLogEvents (audit logs), PutMetricData
- Bedrock: InvokeModel (optional, for validation)

#### **Task 2: Dashboard**

**Container Spec**:
```
Port: 8501 (Streamlit)
Image: {ECR}/sentra/dashboard:latest

Environment Variables:
├── SESSION_CONTEXT_TABLE=sentra-session-context
├── AUDIT_LOG_GROUP=/sentra/audit-logs
├── AWS_REGION=us-east-1
└── SECURITY_CONTROLLER_URL=http://security-controller.sentra.internal:8080

Health Check:
├── Command: curl -f http://localhost:8501/_stcore/health
```

**IAM Permissions**:
- CloudWatch Logs: StartQuery, GetQueryResults (audit logs)
- DynamoDB: Read `session-context` (monitoring)

#### **Task 3: Customer Query Agent**

**Container Spec**:
```
Port: 8002
Image: {ECR}/sentra/customer-query-agent:latest

Environment Variables:
├── DEMO_CUSTOMERS_TABLE=sentra-demo-customers
├── DEMO_ORDERS_TABLE=sentra-demo-orders
├── SECURITY_CONTROLLER_URL=http://security-controller.sentra.internal:8080
├── BEDROCK_MODEL_ID=anthropic.claude-3-sonnet-20240229-v1:0
└── AWS_REGION=us-east-1

Health Check:
├── Command: curl -f http://localhost:8002/health
```

**IAM Permissions**:
- DynamoDB: Read `demo-customers`, `demo-orders`
- Bedrock: InvokeModel (Claude Sonnet)

#### **Task 4: Payment Agent**

**Container Spec**:
```
Port: 8003
Image: {ECR}/sentra/payment-agent:latest

Environment Variables:
├── DEMO_ORDERS_TABLE=sentra-demo-orders
├── SECURITY_CONTROLLER_URL=http://security-controller.sentra.internal:8080
├── BEDROCK_MODEL_ID=anthropic.claude-3-sonnet-20240229-v1:0
└── AWS_REGION=us-east-1

Health Check:
├── Command: curl -f http://localhost:8003/health
```

**IAM Permissions**:
- DynamoDB: Read/Write `demo-orders` (refund updates)
- Bedrock: InvokeModel (Claude Sonnet)

### 4.4 ECS Services

**Standard Service Configuration**:
```
├── Desired Count: 1 (MVP)
├── Min Healthy Percent: 0 (allow rolling updates)
├── Max Percent: 200 (can have 2 tasks during deploy)
├── Subnets: Private subnets (PRIVATE_WITH_EGRESS)
├── Security Groups: See section 2.3
└── Service Discovery: Route53 private zone (sentra.internal)
```

**Service Discovery**:
- Each service auto-registers DNS in `sentra.internal`
- Health checks integrated (only healthy tasks in DNS)
- Example: `security-controller.sentra.internal` → Task IP

### 4.5 Application Load Balancer

**Configuration**:
```
Name: sentra-alb
Internet Facing: True (public ALB - ADR-003 v2)
Subnets: Public subnets (requires public subnets in VPC)
Security Group: alb-sg (allows HTTPS from 0.0.0.0/0)
```

**Architecture Change**: Changed from private to public ALB for simplified MVP architecture. API Gateway connects directly via HTTP_PROXY (no VPC Link needed).

**Listener Rules** (path-based routing):
```
Priority 1: /v1/validate, /v1/health, /v1/logs, /v1/rollback
           → security-controller:8080

Priority 2: /v1/agents/customer-query/*
           → customer-query-agent:8002

Priority 3: /v1/agents/payment/*
           → payment-agent:8003

Priority 4: / (dashboard)
           → dashboard:8501
```

**See ADR-012** for ALB vs NLB decision.

**Target Groups**:
- Health check interval: 30s
- Healthy threshold: 2
- Unhealthy threshold: 3
- Timeout: 5s

### 4.6 Stack Outputs

Exports: ECS Cluster name, ALB DNS, Service ARNs (4), Task Role ARNs (4)

---

## 5. API Stack

### 5.1 Purpose

Public-facing API Gateway with direct HTTP integration to public ALB.

**Architecture Change (ADR-003 v2)**: Simplified for MVP - NO VPC Link needed. API Gateway directly integrates with internet-facing ALB.

**See [LLD 02: API Gateway](./02-api-gateway.md) for full details.**

### 5.2 Key Components

**API Gateway Configuration**:
```
Type: REST API
Name: sentra-mvp-api
Stage: prod
Throttle: 100 req/sec (global)
Quota: 100,000 req/month
Integration: HTTP_PROXY to public ALB DNS
```

**Direct ALB Integration** (NO VPC Link):
- Integration type: HTTP_PROXY
- Integration URI: `http://{alb-dns-name}/{proxy}`
- Connection type: INTERNET (public ALB)
- Pass-through headers: X-Correlation-ID, X-API-Key-ID
- Cost savings: ~$32/month (no NAT Gateway needed)

**Authentication**:
- API Key required (all endpoints except /health)
- Usage plan enforcement

**Rate Limits** (per endpoint):
```
/v1/validate: 100 req/min
/v1/logs: 50 req/min
/v1/rollback: 10 req/min
/v1/agents/*/query: 20 req/min
/v1/agents/*/action: 10 req/min
/v1/health: 1000 req/min (no auth)
```

**See ADR-003 v2** for public API Gateway + public ALB decision.
**See ADR-018** for REST API vs HTTP API v2 decision.

### 5.3 Stack Outputs

Exports: API Gateway ID, API Gateway URL, API Key ID, ALB DNS Name

---

## 6. Monitoring Stack

### 6.1 CloudWatch Dashboard

**Dashboard Name**: sentra-mvp-dashboard

**Widgets** (12 total):
```
Row 1: System Metrics
├── ECS CPU Utilization (all 4 services)
├── ECS Memory Utilization (all 4 services)
└── ALB Request Count

Row 2: API Metrics
├── API Gateway 4XX Errors
├── API Gateway 5XX Errors
├── API Gateway Latency (p50, p99)

Row 3: Security Metrics
├── Validation Decisions (ALLOW vs DENY)
├── Threat Types (pie chart)
├── Quarantined Sessions Count

Row 4: DynamoDB Metrics
├── Read Capacity (session-context table)
├── Write Capacity (session-context table)
└── Throttled Requests
```

### 6.2 CloudWatch Alarms

**6 Alarms** (SNS notifications):

| Alarm | Metric | Threshold | Period | Action |
|-------|--------|-----------|--------|--------|
| **API-5XX-Errors** | API Gateway 5XX | > 10 errors | 5 min | SNS alert |
| **API-High-Latency** | API Gateway p99 | > 5 seconds | 5 min | SNS alert |
| **ECS-CPU-High** | ECS CPU | > 80% | 5 min | SNS alert |
| **ECS-Memory-High** | ECS Memory | > 80% | 5 min | SNS alert |
| **DynamoDB-Throttled** | Throttled requests | > 5 | 1 min | SNS alert |
| **High-Severity-Threats** | Threat count | > 10 | 5 min | SNS alert |

**See ADR-017** for monitoring strategy.

### 6.3 SNS Topic

**Configuration**:
```
Topic: sentra-mvp-alerts
Protocol: Email
Endpoint: admin@sentra.ai (configurable)
```

### 6.4 Stack Outputs

Exports: Dashboard URL, SNS Topic ARN

---

## 7. Deployment Guide

### 7.1 Prerequisites

```bash
# Install AWS CDK
npm install -g aws-cdk

# Install Python dependencies
pip install -r requirements.txt

# Configure AWS credentials
aws configure
```

### 7.2 Deployment Commands

```bash
# Bootstrap CDK (first time only)
cdk bootstrap aws://<account-id>/us-east-1

# Synthesize CloudFormation templates
cdk synth

# Deploy all stacks
cdk deploy --all

# Deploy specific stack
cdk deploy SentraNetworkStack
cdk deploy SentraStorageStack
cdk deploy SentraComputeStack
cdk deploy SentraApiStack
cdk deploy SentraMonitoringStack
```

### 7.3 Post-Deployment Steps

1. **Retrieve API Key**:
```bash
API_KEY_ID=$(aws cloudformation describe-stacks \
  --stack-name SentraApiStack \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiKeyId`].OutputValue' \
  --output text)

aws apigateway get-api-key \
  --api-key $API_KEY_ID \
  --include-value \
  --query 'value' \
  --output text
```

2. **Upload Sigma Rules to S3**:
```bash
aws s3 sync ./sigma_rules/ s3://sentra-mvp-artifacts/sigma_rules/
```

3. **Upload Policies to S3**:
```bash
aws s3 sync ./policies/ s3://sentra-mvp-artifacts/policies/
```

4. **Seed Demo Data**:

**Option A: Small-scale (500 records)** - For testing:
```bash
python scripts/seed_demo_data.py
```

**Option B: Large-scale (1M+ records)** - For realistic demos:
```bash
# Seed 1M customers + 1M orders
python scripts/seed_all.py --seed-demo-data

# Custom counts
python scripts/seed_all.py --seed-demo-data --customers 500000 --orders 500000

# Note: Uses On-Demand billing mode (auto-scales, no provisioning needed)
# Estimated time: 60-90 minutes for 1M+1M records
# Cost: ~$2.50 for 2M write units
```

See **LLD 09 Appendix A** for million-scale seeding strategies (batch scripts vs S3 import).

5. **Build and Push Container Images**:
```bash
# Get ECR login
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin <account-id>.dkr.ecr.us-east-1.amazonaws.com

# Build and push (for each service)
docker build -t sentra/security-controller:latest ./src/security-controller
docker tag sentra/security-controller:latest \
  <account-id>.dkr.ecr.us-east-1.amazonaws.com/sentra/security-controller:latest
docker push <account-id>.dkr.ecr.us-east-1.amazonaws.com/sentra/security-controller:latest

# Repeat for dashboard, customer-query-agent, payment-agent
```

### 7.4 Verification

```bash
# Check ECS services
aws ecs list-services --cluster sentra-mvp-cluster

# Check API Gateway
API_URL=$(aws cloudformation describe-stacks \
  --stack-name SentraApiStack \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiUrl`].OutputValue' \
  --output text)

curl -H "X-API-Key: $API_KEY" $API_URL/v1/health
```

### 7.5 Teardown

```bash
# Delete all stacks (reverse order)
cdk destroy SentraMonitoringStack
cdk destroy SentraApiStack
cdk destroy SentraComputeStack
cdk destroy SentraStorageStack
cdk destroy SentraNetworkStack
```

**Warning**: S3 bucket and CloudWatch Logs have `RETAIN` policy - must delete manually if needed.

---

## 8. Cross-References

### Related LLDs
- [LLD 02: API Gateway Layer](./02-api-gateway.md)
- [LLD 03: Security Controller](./03-security-controller.md)
- [LLD 04: Agents](./04-agents.md) (future)
- [LLD 05: Dashboard](./05-dashboard.md) (future)

### Architecture Decision Records
- **ADR-001**: ECS Fargate for compute
- **ADR-011**: VPC design (no public subnets, 1 NAT for MVP)
- **ADR-012**: ALB vs NLB for ECS routing
- **ADR-013**: On-demand vs Provisioned DynamoDB pricing
- **ADR-014**: VPC Endpoints strategy
- **ADR-015**: Security Group design (least privilege)
- **ADR-016**: ECS Fargate task sizing (2 vCPU, 4 GB)
- **ADR-017**: CloudWatch Log retention periods

### Other References
- [design-hld.md](../design-hld.md) - High-level architecture
- [flow.md](../flow.md) - End-to-end operational flows
- [demo.md](../demo.md) - Demo scenarios

---

**End of LLD 01: CDK Infrastructure**
