# Architecture Decision Records (ADRs)

**Project**: Sentra MVP - AI Agent Security Platform
**Version**: 1.0
**Last Updated**: January 11, 2025

This document contains all architecture decisions made during the Sentra MVP development. Each ADR documents the context, decision, rationale, and consequences of key technical choices.

---

## ADR-001: Use AWS ECS Fargate for Compute

**Date**: January 2025
**Status**: Accepted

### Context
Need production-grade container orchestration for MVP within 4-week timeline.

### Decision
Use AWS ECS Fargate instead of EKS or EC2 for all compute workloads.

### Rationale
- **Faster to deploy**: No cluster management, no control plane setup
- **Lower cost for MVP**: No EC2 instances to manage (~$100-150/month vs $300+ for EKS)
- **Production-grade**: 99.99% SLA from AWS
- **Easy migration path**: Can migrate to EKS post-MVP without major refactoring
- **Serverless model**: Auto-scaling, pay per use, no capacity planning

### Consequences
- ✅ Faster time to production (2-3 days vs 1-2 weeks for EKS)
- ✅ Lower operational overhead for MVP
- ⚠️ Limited customization vs Kubernetes (no custom schedulers, node affinity)
- ⚠️ No CRDs for MVP (planned post-MVP with EKS migration)
- ✅ Good fit for demo and investor presentations
- 🔄 May need EKS migration for production scale (500+ agents)

### Alternatives Considered
1. **AWS EKS**: Too complex for 4-week MVP, higher cost, longer setup time
2. **EC2 with Docker Compose**: Not production-grade, no auto-scaling, manual management
3. **Lambda Functions**: Cold start latency issues, 15-min timeout limits

---

## ADR-002: Use DynamoDB On-Demand Pricing

**Date**: January 2025
**Status**: Accepted

### Context
Need scalable storage with minimal operational overhead for session state, policies, and demo data.

### Decision
Use DynamoDB with on-demand billing instead of provisioned capacity.

### Rationale
- **Unknown traffic patterns**: MVP will have unpredictable load during demos
- **Auto-scaling**: On-demand automatically scales without throttling
- **Cost-effective for MVP**: Pay only for usage (~$1-2/month for demo load)
- **Zero capacity planning**: No need to estimate RCUs/WCUs
- **Easy migration**: Can switch to provisioned capacity post-MVP for cost optimization

### Consequences
- ✅ No throttling during demos (critical for investor presentations)
- ✅ Simple to set up (no capacity planning)
- ⚠️ Slightly higher cost per request vs provisioned (~25% more)
- ✅ Good fit for unpredictable MVP load
- 🔄 Should evaluate provisioned capacity post-MVP if traffic patterns stabilize

### Cost Analysis
- **On-demand**: $1.25/million writes, $0.25/million reads
- **MVP estimate**: 10K requests/day = $0.50/day = $15/month
- **Break-even**: Provisioned becomes cheaper at ~1M requests/day

### Alternatives Considered
1. **DynamoDB Provisioned**: Requires capacity planning, risk of throttling during demos
2. **PostgreSQL RDS**: Higher operational overhead, slower for key-value lookups
3. **Redis/ElastiCache**: Not durable for audit logs, higher cost

---

## ADR-003: Public API Gateway with Public ALB Backend (Simplified MVP)

**Date**: January 2025 (Revised v2)
**Status**: Accepted (Changed from Private VPC in v1.1)

### Context
Need to simplify architecture for 4-week MVP demo while staying within $200/month budget. The MVP is for **investor demos in controlled environment**, not production deployment.

### Decision
Deploy **REST API Gateway** as public endpoint (https://api.sentra.ai) with **internet-facing ALB** and ECS services. No VPC Link, no private subnets, no NAT Gateway.

### Rationale
- **Simpler architecture**: Direct API Gateway → Public ALB → ECS (no VPC Link complexity)
- **Lower cost**: Saves ~$32/month on NAT Gateway (16% of total budget)
- **Faster to build**: No VPC Link setup/debugging, removes 2-3 days of work
- **Easier debugging**: Can directly test ALB endpoints during development
- **Focus on core demo**: Engineering time spent on security features, not infrastructure complexity
- **REST API for API keys**: Provides built-in API key authentication and per-endpoint rate limiting
- **Good enough for demo**: This is controlled demo environment, not production

### Architecture
```
Public Internet
    ↓
REST API Gateway (public, managed by AWS)
    ↓
Internet-facing ALB (public, in public subnets)
    ↓
ECS Fargate Services (public subnets, secured with Security Groups)
    ↓
DynamoDB, S3, CloudWatch (AWS managed services)
```

### Consequences
- ✅ Simplified architecture (easier to understand for investors)
- ✅ $32/month cost savings (NAT Gateway elimination)
- ✅ 2-3 days faster implementation (no VPC Link debugging)
- ✅ Easier to demo and test
- ✅ REST API provides API keys and granular rate limiting
- ⚠️ ALB and ECS have public IPs (mitigated with Security Groups)
- ⚠️ Not production-ready architecture (acceptable for demo)
- 🔄 Can add private subnets + VPC Link post-MVP if needed

### Security Measures (Still Strong)
1. **API Key authentication**: REST API Gateway built-in API keys
2. **Rate limiting**: Per-endpoint throttling (10-1000 req/min based on endpoint)
3. **Security Groups**: ECS services only accept traffic from ALB
4. **CloudWatch logging**: Full request/response audit trail
5. **DynamoDB/S3**: Still use AWS managed security (encryption, IAM)
6. **Demo environment**: Not handling real customer data

### Cost Comparison
| Component | Private VPC | Public ALB | Savings |
|-----------|-------------|------------|---------|
| NAT Gateway | $32/month | $0 | $32 |
| VPC Link | $0 (included) | $0 (not needed) | $0 |
| **Total** | **~$200/month** | **~$168/month** | **$32/month** |

### Alternatives Considered
1. **Private VPC + VPC Link**: Over-engineered for demo, adds $32/month, 2-3 days extra work
2. **HTTP API v2**: Doesn't support built-in API keys (would need Lambda authorizer)
3. **Fully open (no auth)**: Not acceptable even for demo

### Migration Path Post-MVP
If/when moving to production:
1. Move ECS to private subnets
2. Add NAT Gateway for outbound traffic
3. Add VPC Link between API Gateway and ALB
4. Keep REST API Gateway (already production-ready)

**Note**: This is an intentional simplification for MVP demo. The **security value** is in the Security Controller logic (blocking attacks), not in infrastructure security layers.

---

## ADR-004: YAML Policy Format for MVP

**Date**: January 2025
**Status**: Accepted

### Context
Need policy language that's easy to implement within 4-week timeline and intuitive for demos.

### Decision
Use YAML with Python expressions for MVP policy definition.

### Rationale
- **Fastest to implement**: 2-3 days vs 1-2 weeks for CEDAR or OPA
- **Human-readable**: Great for live demos and investor presentations
- **Zero external dependencies**: Pure Python evaluation
- **Flexible**: Supports complex conditions with Python syntax
- **Migration path**: Can add CEDAR or OPA support post-MVP

### Consequences
- ✅ Fast implementation (meets 4-week deadline)
- ✅ Easy to demo and explain to non-technical stakeholders
- ✅ No learning curve for developers (standard YAML + Python)
- ⚠️ Less performant than CEDAR (~10-20ms vs 1-5ms)
- ⚠️ Less mature ecosystem than OPA (no policy testing frameworks)
- ⚠️ Security risk if eval() used incorrectly (mitigated with safe parsing)
- 🔄 Should evaluate CEDAR integration post-MVP for AWS compatibility

### Example Policy Format
```yaml
policies:
  - name: max-refund-amount
    condition: "refund_amount <= 5000"
    action: deny
    severity: high
```

### Alternatives Considered
1. **AWS CEDAR**: More secure, better performance, but 1-2 weeks to learn and implement
2. **Open Policy Agent (OPA)**: Mature ecosystem, but Rego language has learning curve
3. **Custom DSL**: Too much work for MVP, reinventing the wheel

---

## ADR-005: Manual Rollback (No Automation)

**Date**: January 2025
**Status**: Accepted

### Context
Need rollback capability for demo, but must balance automation with trust.

### Decision
Implement manual operator-confirmed rollback, NOT automated rollback.

### Rationale
- **Trust requirement**: Customers won't trust automated rollback of financial transactions
- **Simpler to implement**: No complex undo logic or transaction coordination
- **Compliance**: Audit trail includes operator ID and confirmation timestamp
- **Differentiation**: Rubrik does automated rollback; we differentiate with prevention + manual control
- **MVP scope**: 2 use cases sufficient for demo (refund reversal, EC2 termination)

### Consequences
- ✅ Higher trust from enterprise customers (explicit human control)
- ✅ Simpler implementation (meets 4-week deadline)
- ✅ Better audit trail (operator ID, confirmation timestamp)
- ✅ Clear positioning vs Rubrik (prevention-first vs post-facto cleanup)
- ⚠️ Requires operator intervention (not zero-touch)
- ⚠️ Slower than automated rollback (seconds vs milliseconds)
- 🔄 May add automated rollback for specific low-risk actions post-MVP

### Rollback Workflow
1. Dashboard shows "Rollback" button for reversible actions
2. Operator clicks → Confirmation dialog with impact preview
3. Operator confirms → System executes compensating transaction
4. Success/failure displayed with audit log entry

### Alternatives Considered
1. **Automated rollback (like Rubrik)**: Too risky for financial transactions, customers won't trust
2. **No rollback**: Doesn't showcase platform capability
3. **Approval workflow**: Over-engineered for MVP

---

## ADR-006: CloudWatch Logs for Audit Trail (Not DynamoDB)

**Date**: January 2025
**Status**: Accepted

### Context
Need immutable audit log for all security decisions with 90-day retention.

### Decision
Use CloudWatch Logs for audit trail instead of DynamoDB table.

### Rationale
- **Cost**: 2.5x cheaper than DynamoDB for write-heavy workload ($0.50/GB vs $1.25/GB)
- **No item size limit**: DynamoDB has 400KB limit, Sigma rules + SBOM can exceed this
- **Purpose-built**: CloudWatch designed for log aggregation
- **Retention**: Built-in 90-day retention with automatic deletion
- **Query**: CloudWatch Insights for dashboard queries
- **Compliance**: Immutable by default, perfect for audit logs

### Consequences
- ✅ Lower cost (~$10-15/month vs $30-50/month for DynamoDB)
- ✅ No 400KB item size limits (can log large payloads)
- ✅ Built-in retention management
- ⚠️ Slower queries than DynamoDB (1-3 seconds vs 10ms)
- ⚠️ Dashboard needs to optimize query frequency (cache results)
- ✅ Better for write-heavy, read-light audit log workload

### Storage Strategy
- **CloudWatch Logs**: Audit trail (write-heavy, large items)
- **DynamoDB**: Session context (read-heavy, small items, < 10ms latency)
- **S3**: Large artifacts (Sigma rules, SBOM files, compliance exports)

### Alternatives Considered
1. **DynamoDB**: 2.5x more expensive, 400KB item limit
2. **S3 directly**: No structured querying, slow dashboard updates
3. **PostgreSQL RDS**: Overkill for append-only logs, higher cost

---

## ADR-007: Route53 Private Hosted Zone for Service Discovery

**Date**: January 2025
**Status**: Accepted

### Context
Need reliable service-to-service communication in VPC without hardcoding IPs.

### Decision
Use Route53 Private Hosted Zone (`sentra.internal`) with ECS Service Discovery.

### Rationale
- **Dynamic IPs**: ECS Fargate tasks get new IPs on restart
- **DNS-based**: Standard pattern, works with all HTTP clients
- **ECS integration**: Service Discovery auto-registers tasks
- **Cost**: $0.50/month per hosted zone (negligible)
- **Resilience**: DNS load balancing across multiple tasks

### Consequences
- ✅ No hardcoded IPs in configuration
- ✅ Automatic registration of new tasks
- ✅ Standard DNS-based service discovery
- ✅ Works with HTTP clients (no special libraries)
- ⚠️ DNS propagation delay (~1-5 seconds)
- ✅ Good fit for ECS Fargate deployments

### DNS Records
- `security-controller.sentra.internal` → Security Controller ECS tasks
- `dashboard.sentra.internal` → Dashboard ECS tasks
- `customer-query-agent.sentra.internal` → Customer Query Agent ECS tasks
- `payment-agent.sentra.internal` → Payment Agent ECS tasks

### Alternatives Considered
1. **Hardcoded IPs**: Breaks on task restart
2. **ALB for internal traffic**: Overkill, higher cost ($16/month per ALB)
3. **AWS Cloud Map only**: Route53 provides better DNS integration

---

## ADR-008: Multi-Agent Architecture with Shared Tools

**Date**: January 2025
**Status**: Accepted

### Context
Demo scenarios require multiple agents with different responsibilities.

### Decision
Deploy 2 specialized agents (Customer Query Agent, Payment Agent) with shared tool library.

### Rationale
- **Realistic enterprise pattern**: Enterprises have multiple specialized agents
- **Demo scenarios**: Shows cross-agent security (different agents, same tools)
- **Code reuse**: Shared tools library avoids duplication
- **Scalability demonstration**: Proves platform can secure multiple agents
- **Trust scoring**: Each agent has independent trust score

### Consequences
- ✅ More realistic demo for enterprise customers
- ✅ Shows platform scales to multiple agents
- ✅ Code reuse via shared library
- ⚠️ More infrastructure to manage (2 ECS services vs 1)
- ⚠️ Higher cost (~$100/month vs $70/month for single agent)
- ✅ Better showcases platform capabilities

### Agent Responsibilities
- **Customer Query Agent**: Customer/order queries (read operations), data exfiltration scenarios
- **Payment Agent**: Refund processing (write operations), financial security scenarios
- **Shared Tools**: `query_database()`, `check_order()`, `process_refund()`, etc.

### Alternatives Considered
1. **Single agent**: Simpler but less realistic for enterprise demos
2. **3+ agents**: Over-engineered for MVP, higher cost
3. **Agent per scenario**: Too many services to manage

---

## ADR-009: Trust Scoring with Automated Quarantine

**Date**: January 2025
**Status**: Accepted

### Context
Need to demonstrate adaptive security that learns from agent behavior.

### Decision
Implement trust scoring (0-100) per agent session with automated quarantine thresholds.

### Rationale
- **Adaptive security**: Shows platform learns and adapts to threats
- **Demo differentiator**: Competitors don't have trust-based containment
- **Enterprise value**: Prevents cascade failures in multi-agent systems
- **Simple algorithm**: Score decrements on violations, increments on good behavior
- **Non-invasive**: Quarantine allows read-only operations, not full shutdown

### Consequences
- ✅ Shows intelligent, adaptive security (not just static rules)
- ✅ Differentiates from competitors (Lakera, CalypsoAI don't have this)
- ✅ Demonstrates containment strategy for compromised agents
- ⚠️ Requires tuning thresholds (may need adjustment based on demos)
- ✅ Adds "wow factor" to investor demos

### Trust Score Thresholds
- **100**: Fully trusted (new session)
- **70-100**: Normal operation (all tools allowed)
- **40-69**: Warning (all tools allowed, alerts triggered)
- **10-39**: Quarantined (only read-only tools allowed)
- **< 10**: Suspended (all tools denied, requires admin review)

### Score Adjustments
- Deny decision: -10 points
- Prompt injection: -20 points
- Jailbreak: -30 points
- Data exfiltration: -25 points
- 10 consecutive allows: +5 points (max 100)

### Alternatives Considered
1. **No trust scoring**: Simpler but less impressive for demos
2. **Binary trust (trusted/untrusted)**: Too simplistic, not adaptive
3. **ML-based scoring**: Too complex for 4-week MVP

---

## ADR-010: Standardized Agent API Interface (/query and /action)

**Date**: January 2025
**Status**: Accepted

### Context
Need to define API interface for agents that is consistent, scalable, and supports different security policies for read vs write operations.

### Decision
All agents expose **both** `/query` AND `/action` endpoints with standardized interface pattern.

### Rationale
- **Consistency**: Same API pattern for all agents (easy for developers to learn)
- **Different rate limits**: Can apply stricter limits on writes (10/min) vs reads (20/min)
- **Security policies**: Can enforce different rules based on operation type
  - Quarantined agents: `/action` returns 403 Forbidden, `/query` still works
  - Read-only mode: Disable `/action` globally
- **Scalability**: Add new agents without changing API design
- **Future-proof**: Agents can evolve capabilities without breaking API contract

### Consequences
- ✅ Consistent developer experience across all agents
- ✅ Clear separation of read vs write operations
- ✅ Can enforce read-only mode for quarantined agents
- ✅ Easier to add new agents (follow same pattern)
- ⚠️ Each agent must implement both endpoints (even if one is rarely used)
- ✅ Better for multi-tenancy (different rate limits per operation type)

### API Design
```
# All agents follow this pattern:
POST /v1/agents/{agent-id}/query   # Read operations (20 req/min)
POST /v1/agents/{agent-id}/action  # Write operations (10 req/min)
GET  /v1/agents/{agent-id}/health  # Health check (1000 req/min)
```

### Examples
```bash
# Customer Query Agent
POST /v1/agents/customer-query/query   # "Show customers from CA"
POST /v1/agents/customer-query/action  # "Update customer email"

# Payment Agent
POST /v1/agents/payment/query          # "Check refund status"
POST /v1/agents/payment/action         # "Process refund"
```

### Alternatives Considered
1. **Agent-specific endpoints**: Customer Query Agent has `/query` only, Payment Agent has `/action` only
   - ❌ Inconsistent API, hard to scale
2. **Single `/chat` endpoint**: One endpoint handles everything
   - ❌ Can't apply different rate limits or policies to reads vs writes
3. **RESTful CRUD**: `/customers`, `/orders`, `/refunds`
   - ❌ Too granular for conversational AI agents

---

## Summary Table

| ADR | Decision | Status | Impact |
|-----|----------|--------|--------|
| ADR-001 | ECS Fargate for compute | ✅ Accepted | Faster deployment, lower cost |
| ADR-002 | DynamoDB on-demand pricing | ✅ Accepted | Auto-scaling, no throttling |
| ADR-003 | Public API Gateway + Private VPC | ✅ Accepted | Easier demos, still secure |
| ADR-004 | YAML policy format | ✅ Accepted | Fast implementation |
| ADR-005 | Manual rollback | ✅ Accepted | Higher trust, simpler |
| ADR-006 | CloudWatch for audit logs | ✅ Accepted | Lower cost, no size limits |
| ADR-007 | Route53 service discovery | ✅ Accepted | Dynamic IPs, resilient |
| ADR-008 | Multi-agent architecture | ✅ Accepted | Realistic enterprise demo |
| ADR-009 | Trust scoring & quarantine | ✅ Accepted | Adaptive security, differentiator |
| ADR-010 | Standardized agent API | ✅ Accepted | Consistent interface, scalable |
| ADR-011 | VPC design (no public, 1 NAT) | ✅ Accepted | Security + cost optimization |
| ADR-012 | ALB vs NLB | ✅ Accepted | Path-based routing, simpler |
| ADR-013 | DynamoDB + CloudWatch Logs | ✅ Accepted | Cost-effective storage strategy |
| ADR-014 | VPC Endpoints strategy | ✅ Accepted | Lower latency, cost savings |
| ADR-015 | Security group design | ✅ Accepted | Least privilege access |
| ADR-016 | ECS task sizing (2 vCPU, 4 GB) | ✅ Accepted | Standardized, sufficient capacity |
| ADR-017 | CloudWatch log retention | ✅ Accepted | Compliance + cost optimization |
| ADR-018 | REST API vs HTTP API | ✅ Accepted | Built-in auth, easier MVP |
| ADR-019 | Split ALB + Cognito auth | ✅ Accepted | Security compliance, fault isolation |

---

## ADR-011: VPC Design - No Public Subnets, Single NAT Gateway

**Date**: January 2025
**Status**: Accepted

### Context
Need to balance security, cost, and high availability for MVP deployment.

### Decision
Deploy VPC with only private subnets, 1 NAT Gateway in us-east-1a, and isolated subnets for VPC endpoints.

### Rationale
- **No Public Subnets**: Maximum security - all services private, access via API Gateway + VPC Link only
- **Single NAT Gateway**: Cost optimization for MVP (~$32/month vs $64/month for 2 NATs)
  - Production: Add second NAT in us-east-1b for high availability
- **Isolated Subnets**: VPC endpoints don't need internet access (no NAT route)
- **2 Availability Zones**: ECS services can failover if one AZ fails

### Consequences
- ✅ Lower cost for MVP ($32/month savings)
- ✅ Maximum security (no public attack surface)
- ⚠️ Single point of failure for outbound traffic (NAT)
  - Acceptable for MVP - can add second NAT post-MVP
- ✅ Simplified network topology
- 🔄 Will add second NAT Gateway for production

### Alternatives Considered
1. **Public subnets for services**: Not acceptable for security platform
2. **2 NAT Gateways**: Too expensive for MVP ($64/month)
3. **No NAT, VPC endpoints only**: Can't pull Docker images from Docker Hub

---

## ADR-012: Application Load Balancer vs Network Load Balancer

**Date**: January 2025
**Status**: Accepted

### Context
Need load balancer to route traffic from API Gateway VPC Link to multiple ECS services.

### Decision
Use Application Load Balancer (ALB) instead of Network Load Balancer (NLB).

### Rationale
- **Path-based routing**: ALB supports routing different paths to different services
  - `/v1/validate` → Security Controller
  - `/v1/agents/customer-query/*` → Customer Query Agent
  - `/v1/agents/payment/*` → Payment Agent
- **HTTP/HTTPS native**: ALB operates at Layer 7 (application layer)
- **Single VPC Link**: One VPC Link can route to all services via ALB
  - NLB would require separate VPC Links per service (more complex, higher cost)
- **Health checks**: ALB supports HTTP health checks with custom paths
- **Cost**: Similar cost to NLB (~$16/month)

### Consequences
- ✅ Single load balancer for all services (simplified architecture)
- ✅ Path-based routing (no need for separate endpoints)
- ✅ HTTP health checks (more flexible than TCP)
- ✅ Lower operational overhead (fewer VPC Links)
- ⚠️ Slightly higher latency than NLB (~1-2ms)
  - Acceptable for MVP (total latency budget is 50-100ms)

### Alternatives Considered
1. **NLB**: Lower latency but requires separate VPC Links per service
2. **Multiple ALBs**: Unnecessary complexity and cost
3. **Direct ECS routing**: No load balancing or failover

---

## ADR-013: DynamoDB On-Demand Pricing and CloudWatch Logs for Audit Trail

**Date**: January 2025
**Status**: Accepted

### Context
Need scalable storage with minimal operational overhead for session state, policies, and audit logs.

### Decision
1. Use DynamoDB with on-demand billing for all tables
2. Use CloudWatch Logs (not DynamoDB) for audit trail

### Rationale

**DynamoDB On-Demand**:
- **Unknown traffic patterns**: MVP has unpredictable load during demos
- **Auto-scaling**: No throttling, no capacity planning
- **Cost-effective for MVP**: Pay only for usage (~$1-2/month for demo load)
- **Easy migration**: Can switch to provisioned capacity post-MVP

**CloudWatch Logs for Audit Trail**:
- **Cost**: $0.50/GB ingestion vs DynamoDB $1.25/GB write (2.5x cheaper)
- **No size limits**: User prompts can be huge (10KB+), matched_rules can grow
  - DynamoDB has 400KB item limit
- **Built for logs**: Append-only, immutable, automatic retention
- **CloudWatch Insights**: Query with SQL-like syntax
- **Write-heavy workload**: Audit logs written on EVERY request, rarely read

### Consequences
- ✅ No throttling during demos
- ✅ Simple to set up (no capacity planning)
- ✅ Lower cost: ~$3.50/month for audit logs vs $15/month with DynamoDB
- ⚠️ CloudWatch queries slower than DynamoDB (5-10s vs 10ms)
  - Acceptable: Dashboard caches results, refresh every 5 seconds
- 🔄 Should evaluate provisioned capacity post-MVP if traffic stabilizes

### Cost Analysis (1M requests/month)
- **CloudWatch Logs**: $2.50 ingestion + $0.45 storage + $0.50 queries = **$3.50/month**
- **DynamoDB**: $1.25/million writes = **$12.50/month** (3.5x more expensive)

### Alternatives Considered
1. **DynamoDB for audit logs**: 3.5x more expensive, 400KB limit
2. **S3 directly**: No structured querying, slow dashboard updates
3. **PostgreSQL RDS**: Overkill, much higher cost (~$50/month)

---

## ADR-014: VPC Endpoints Strategy

**Date**: January 2025
**Status**: Accepted

### Context
ECS services need to access AWS services (ECR, S3, DynamoDB, CloudWatch) without using NAT Gateway.

### Decision
Deploy 5 VPC endpoints:
- **Interface Endpoints** (3): ECR Docker, ECR API, CloudWatch Logs
- **Gateway Endpoints** (2): S3, DynamoDB

### Rationale
- **Interface Endpoints for ECR/CloudWatch**:
  - ECS pulls Docker images frequently (every deployment)
  - Container logs stream continuously to CloudWatch
  - Using NAT would add latency and cost
- **Gateway Endpoints for S3/DynamoDB**:
  - FREE! (no per-hour charge)
  - Sigma rules, policies loaded from S3 on startup
  - DynamoDB queried on every validation (high frequency)
- **No Bedrock endpoint**: Bedrock traffic low-frequency (only during agent calls), use NAT

### Consequences
- ✅ Lower NAT traffic (saves bandwidth costs)
- ✅ Faster Docker pulls and log streaming (no NAT hop)
- ✅ Gateway endpoints are FREE
- ⚠️ Interface endpoints cost $0.01/hour = $7/month each ($21/month total)
  - ROI: Saves ~$30/month in NAT bandwidth costs
- ✅ Traffic stays within AWS network (more secure, lower latency)

### Cost Analysis
- **3 Interface Endpoints**: 3 × $7/month = **$21/month**
- **2 Gateway Endpoints**: FREE
- **NAT Bandwidth Saved**: ~100GB/month × $0.09/GB = **$9/month**
- **Latency Improvement**: ~5-10ms per request (no NAT hop)

### Alternatives Considered
1. **No VPC endpoints**: All traffic through NAT (higher cost, slower)
2. **All interface endpoints**: Too expensive ($35+/month)
3. **VPC endpoints for everything**: Unnecessary (low-frequency traffic fine with NAT)

---

## ADR-015: Security Group Design - Least Privilege Access

**Date**: January 2025
**Status**: Accepted

### Context
Need network access control for 4 ECS services (Security Controller, Dashboard, 2 Agents) and ALB.

### Decision
Create 5 security groups with least-privilege ingress rules and all-outbound egress (for MVP).

### Rationale
- **Least Privilege Ingress**: Each service only allows necessary ports from specific sources
  - Security Controller: Only accepts from dashboard, agents, ALB (port 8080)
  - Dashboard: Only accepts from ALB (port 8501)
  - Agents: Only accept from ALB (ports 8002, 8003)
- **Source-based Rules**: Security groups reference each other (not IP ranges)
  - More maintainable (IPs change, security groups don't)
- **All Outbound**: Simplified for MVP (can tighten post-MVP)
  - Services need access to: DynamoDB, S3, CloudWatch, Bedrock
  - Explicit outbound rules would be complex (many AWS service IPs)

### Consequences
- ✅ Strong network isolation (defense in depth)
- ✅ Easy to maintain (security group references)
- ✅ Audit-friendly (clear documentation of access patterns)
- ⚠️ All outbound traffic allowed (simplified for MVP)
  - Post-MVP: Can restrict to specific AWS service prefixes
- ✅ No cross-service access (agents can't talk directly)

### Alternatives Considered
1. **Single security group for all services**: Too permissive, no isolation
2. **Explicit outbound rules**: Complex to maintain, many AWS service IPs
3. **NACLs instead of security groups**: Less flexible, subnet-level only

---

## ADR-016: ECS Fargate Task Sizing - 2 vCPU, 4 GB RAM

**Date**: January 2025
**Status**: Accepted

### Context
Need to size ECS Fargate tasks for Security Controller, Dashboard, and 2 AI agents.

### Decision
Standardize all tasks at **2 vCPU (2048 units), 4 GB RAM (4096 MiB)**.

### Rationale
- **Security Controller**: CPU-bound (Sigma rule matching, policy evaluation)
  - 2 vCPU handles 100 validations/min easily
- **AI Agents**: Memory-bound (LangChain, prompt caching)
  - 4 GB RAM supports multiple concurrent conversations
- **Dashboard**: Low resource (Streamlit queries CloudWatch API)
  - 2 vCPU is overkill, but standardization simplifies ops
- **Fargate Pricing**: 2 vCPU + 4 GB = $0.08/hour = **$58/month per service**
  - 4 services × $58 = **$232/month** (within MVP budget)
- **Standardization Benefits**:
  - Single task definition template
  - Predictable costs
  - Easy to swap services (same resources)

### Consequences
- ✅ Sufficient for MVP load (< 100 requests/min)
- ✅ Simplified operations (all tasks identical)
- ✅ Room for growth (can handle 500+ requests/min)
- ⚠️ Dashboard over-provisioned (could use 1 vCPU, 2 GB)
  - Trade-off: Simplicity vs $29/month savings
- 🔄 Post-MVP: Right-size based on production metrics

### Cost Breakdown
| Service | vCPU | RAM | Cost/month |
|---------|------|-----|------------|
| Security Controller | 2 | 4 GB | $58 |
| Dashboard | 2 | 4 GB | $58 |
| Customer Query Agent | 2 | 4 GB | $58 |
| Payment Agent | 2 | 4 GB | $58 |
| **Total** | **8** | **16 GB** | **$232** |

### Alternatives Considered
1. **1 vCPU, 2 GB for all**: Too small for agents (memory issues with LangChain)
2. **Different sizes per service**: More complex to manage, hard to predict costs
3. **4 vCPU, 8 GB for all**: Overkill for MVP, 2x cost ($464/month)

---

## ADR-017: CloudWatch Log Retention Periods

**Date**: January 2025
**Status**: Accepted

### Context
Need to define retention periods for CloudWatch Logs (ECS containers, VPC flow logs, audit logs).

### Decision
- **Audit logs** (`/sentra/audit-logs`): **90 days** (compliance requirement)
- **ECS container logs** (`/ecs/sentra/*`): **7 days** (cost optimization)
- **VPC flow logs** (`/aws/vpc/sentra-mvp`): **7 days** (security audit)

### Rationale
- **Audit Logs (90 days)**:
  - Compliance requirement (SOC2, HIPAA)
  - Immutable record of all security decisions
  - Cost: ~$0.45/month for storage (after ingestion)
- **ECS Container Logs (7 days)**:
  - Debugging recent deployments only
  - Older logs rarely accessed
  - Cost savings: $0.03/GB/month × 90 days = **$2.70/GB** saved
- **VPC Flow Logs (7 days)**:
  - Security audit for recent traffic patterns
  - Post-MVP: Can increase if needed for forensics

### Consequences
- ✅ Compliance-ready audit logs (90 days)
- ✅ Lower storage costs for container logs (87% savings vs 90 days)
- ✅ Sufficient for MVP debugging (7 days)
- ⚠️ Older container logs deleted automatically
  - Mitigation: Export critical logs to S3 if needed
- 🔄 Post-MVP: Consider S3 archival for long-term audit storage

### Cost Analysis (1M requests/month)
| Log Type | Retention | Storage | Cost/month |
|----------|-----------|---------|------------|
| Audit logs | 90 days | 15 GB | $0.45 |
| ECS logs | 7 days | 2 GB | $0.06 |
| VPC flow logs | 7 days | 1 GB | $0.03 |
| **Total** | - | **18 GB** | **$0.54** |

**Comparison with 90-day retention for all**:
- Storage: 50 GB (vs 18 GB)
- Cost: **$1.50/month** (vs $0.54/month)
- **Savings**: **$0.96/month** (64% reduction)

### Alternatives Considered
1. **90 days for all logs**: Unnecessary for container logs, higher cost
2. **30 days for audit logs**: Not compliant with SOC2 requirements

---

## ADR-018: REST API vs HTTP API for API Gateway

**Date**: January 2025
**Status**: Accepted

### Context
Need to choose between REST API (API Gateway v1) and HTTP API (API Gateway v2) for public API endpoint. Initially selected HTTP API for cost savings, but reconsidered based on authentication and rate limiting needs.

### Decision
Use **REST API Gateway** instead of HTTP API v2.

### Rationale
- **Built-in API keys**: REST API provides native API key authentication without Lambda authorizer
- **Per-endpoint rate limiting**: Granular throttling (10-1000 req/min per endpoint type)
- **Request validators**: Built-in JSON schema validation
- **Usage plans**: Track and limit API usage per customer/demo
- **Simpler for MVP**: No need to build Lambda authorizer
- **Worth the cost**: Extra $20-30/month justified by auth simplicity

### Comparison

| Feature | REST API | HTTP API v2 |
|---------|----------|-------------|
| **Cost** | ~$3.50/million | ~$1.00/million |
| **API Keys** | ✅ Built-in | ❌ Need Lambda authorizer |
| **Per-endpoint throttling** | ✅ Native | ✅ Native |
| **Request validation** | ✅ Built-in | ❌ Manual |
| **Usage plans** | ✅ Built-in | ❌ Manual |
| **VPC Link** | ✅ Supported | ✅ Native |
| **Setup time** | 2 hours | 4 hours (with Lambda auth) |

### Consequences
- ✅ Simpler authentication (no Lambda authorizer needed)
- ✅ Built-in usage tracking and quotas
- ✅ Per-endpoint rate limiting (10-1000 req/min)
- ✅ Request validation without custom code
- ⚠️ 3.5x higher cost ($35/month vs $10/month at 10M requests)
- ✅ Good fit for investor demo (professional API management)
- 🔄 Can optimize to HTTP API post-MVP if cost becomes issue

### Cost Analysis (MVP Load: 1M requests/month)
- **REST API**: 1M × $3.50/million = **$3.50/month**
- **HTTP API**: 1M × $1.00/million + Lambda authorizer (~$1) = **$2.00/month**
- **Difference**: **$1.50/month** (acceptable for MVP)

At 10M requests/month:
- REST API: **$35/month**
- HTTP API: **$10/month** + **$10 Lambda** = **$20/month**
- Difference: **$15/month** (still within budget)

### Alternatives Considered
1. **HTTP API + Lambda Authorizer**: More complex, requires Lambda maintenance, similar cost at scale
2. **No authentication**: Not acceptable for security platform demo
3. **CloudFront + Lambda@Edge**: Over-engineered, higher latency

### Implementation Notes
- Use REST API with API keys and usage plans
- Configure per-endpoint throttling in API Gateway stage settings
- No VPC Link needed (public ALB architecture per ADR-003 v2)
3. **S3 archival for all logs**: Over-engineered for MVP

---

## ADR-019: Split ALB Architecture with Cognito Authentication

**Date**: November 2025
**Status**: Accepted

### Context

The Streamlit Dashboard is currently exposed on a public Application Load Balancer (ALB) without authentication. This configuration triggers automated security remediation by AppSec monitoring systems (DyePack plugin), which automatically removes ALB listeners when detecting unauthenticated Streamlit applications on public ALBs. This remediation affects all services sharing the ALB, causing complete service outage.

**Security Detection Criteria**:
- Public ALB (internet-facing) with no authentication
- Target group pointing to Streamlit application (port 8501)
- No authentication action configured in ALB listener rules
- No Web Application Firewall (WAF) or other security controls

### Decision

Implement **Phase 2 architecture** with split ALBs and AWS Cognito authentication:

1. **Public ALB** (internet-facing):
   - Dashboard only
   - AWS Cognito authentication required
   - HTTPS with Cognito OAuth 2.0 flow

2. **Private ALB** (VPC internal):
   - Security Controller
   - Customer Query Agent
   - Payment Agent
   - No authentication (network-level security via security groups)

### Rationale

**Security Benefits**:
- Dashboard protected by AWS Cognito authentication (prevents AppSec violations)
- API services not exposed to internet (private ALB only)
- Defense in depth (authentication + network isolation)
- Security groups enforce least privilege access

**Architecture Benefits**:
- Fault isolation (Dashboard issues don't affect APIs)
- Independent scaling (public vs private traffic)
- Production-ready architecture (follows AWS Well-Architected Framework)
- Clear separation of concerns (public UI vs private APIs)

**vs Phase 1 (Single ALB with Cognito)**:
- Phase 1 would still expose API services to internet
- No fault isolation
- Single point of failure

**Why AWS Cognito**:
- AWS-native integration with ALB
- Low cost ($0.05/user/month for < 50K MAUs)
- Built-in security features (password policy, MFA, account recovery)
- OAuth 2.0 / OIDC standard
- Session management with refresh tokens

### Architecture

```
Internet → Public ALB (with Cognito) → Dashboard only

VPC Internal → Private ALB → Security Controller
                           → Customer Query Agent
                           → Payment Agent
```

### Consequences

**Positive**:
- ✅ Dashboard isolated with authentication
- ✅ API services private (not internet-accessible)
- ✅ Better security posture (no AppSec violations)
- ✅ Fault isolation (Dashboard issues don't affect APIs)
- ✅ Production-ready architecture
- ✅ Follows AWS Well-Architected Framework

**Negative**:
- ⚠️ More infrastructure (2 ALBs vs 1)
- ⚠️ Higher cost (+$16/month for second ALB)
- ⚠️ Requires VPN/SSM for direct API testing (APIs not publicly accessible)

**Trade-offs**:
- Cost vs Security: $16/month additional cost justified by security compliance
- Convenience vs Security: Direct API testing requires VPN, but APIs are more secure

### Implementation

**Cognito Configuration**:
- User Pool: `sentra-dashboard-users`
- Client: OAuth 2.0 authorization code grant
- Domain: `sentra-dashboard-mvp.auth.us-east-1.amazoncognito.com`
- Password Policy: 12+ chars, mixed case, numbers, symbols
- MFA: Optional TOTP
- Session: 1 hour ID/access tokens, 30 day refresh tokens

**Public ALB Configuration**:
- Internet-facing, public subnets
- Port 80/443 with Cognito authentication action
- Target group: Dashboard (port 8501)
- Security group: Allow HTTP/HTTPS from internet

**Private ALB Configuration**:
- Internal, private subnets
- Port 80, no authentication
- Target groups: Security Controller, Customer Query Agent, Payment Agent
- Security group: Allow from Dashboard + API services only

**Network Flow**:
1. User → Public ALB → Cognito login → Dashboard
2. Dashboard → Private ALB → API services (internal VPC traffic)

### Cost Analysis

| Component | Current | Phase 2 | Delta |
|-----------|---------|---------|-------|
| ALB | 1 × $16/month | 2 × $16/month | +$16/month |
| Cognito | $0 | $0 (< 50K MAUs) | $0 |
| **Total** | ~$16/month | ~$32/month | +$16/month |

**ROI**: $16/month cost justified by:
- Preventing AppSec automated remediation (service outages)
- Production-ready security compliance
- Fault isolation and independent scaling

### Alternatives Considered

1. **Phase 1 (Single ALB with Cognito)**: API services still exposed, no fault isolation
2. **Private ALB + VPN Only**: Less convenient for demos, requires VPN setup
3. **API Gateway for authentication**: More complex, higher cost, not suitable for Streamlit
4. **Custom authentication in Dashboard**: Not acceptable for security compliance

### Migration Path

1. Create Cognito User Pool and test login
2. Create Private ALB and attach API services
3. Update Dashboard environment variables (point to Private ALB)
4. Add Cognito authentication to Public ALB
5. Remove API service routing from Public ALB
6. Verify and test

**Total Migration Time**: ~2.5 hours

### Success Criteria

- ✅ Dashboard accessible via Public ALB with Cognito login
- ✅ API services accessible from Dashboard (via Private ALB)
- ✅ API services NOT accessible from internet
- ✅ No AppSec violations detected
- ✅ All health checks passing

### References

- **LLD-08**: Authentication and ALB Architecture (detailed implementation)
- **ADR-003**: Public API Gateway (superseded for Dashboard, still valid for API Gateway)
- **ADR-012**: ALB vs NLB (path-based routing rationale)

---

## ADR-020: Azure First, GCP Fast-Follow for Cross-Cloud Demo

**Date**: May 2026
**Status**: Accepted

### Context

AegionAI's investor thesis is cross-cloud governance, but the live demo runs on AWS only. The pitch deck v4 commits to a live AWS + Azure cross-cloud demo as the Month 2 milestone gating the seed-raise narrative. We needed to choose which second cloud to add first: Azure AI Foundry, GCP Vertex AI, or OpenAI Assistants API.

### Decision

Add Azure AI Foundry as the second cloud in Phase 1 (Weeks 1–2). GCP Vertex AI follows in Phase 2 (Weeks 3–4) behind the same connector abstraction. OpenAI Assistants API is explicitly off the table for investor demos.

### Rationale

- **Matches pitch deck v4 commitment**: Investors saw the v4 deck name "AWS + Azure" as the Month 2 milestone. Shipping what was promised builds credibility.
- **Lowest translation overhead**: Azure AI Foundry's tool-calling is OpenAI-compatible. The Azure Function interceptor mirrors the existing AWS Lambda 1:1, with different SDK clients. GCP's Gemini function-call schema requires a translation layer (more divergent).
- **Engineering effort**: Azure is ~2 weeks end-to-end (connector + Function + Bicep + scenarios). GCP would be ~2.5–3 weeks for the same scope. Once the connector abstraction is proven, GCP becomes ~1.5 weeks.
- **Investor narrative**: AWS + Azure = two top-2 hyperscalers, structurally competing. OpenAI Assistants is a SaaS, not a cloud — sophisticated reviewers (Travis Priest's feedback explicitly) will discount it.

### Consequences

- ✅ Demo aligns exactly with pitch deck v4 commitments and investor expectations.
- ✅ Azure-first builds the connector abstraction; GCP is mostly subclassing the abstraction afterward.
- ✅ Two-week timeline for Phase 1 fits the Month 2 milestone gate.
- ⚠️ GCP design-partner conversations wait until Phase 2 (Week 4) — acceptable because design-partner outreach starts after the investor demo is recorded.
- ⚠️ Bicep ramp-up required for the engineer owning the Azure stack — budgeted at 2 days inside Phase 1.

### Alternatives Considered

1. **GCP Vertex AI first**: Strong narrative ("two hyperscalers"), but breaks the v4 deck commitment and adds ~1 week of translation work for the Gemini function-call schema.
2. **OpenAI Assistants API first**: Fastest (1 week), but narratively weak. Any sophisticated infrastructure-security investor will call it out within 30 seconds.
3. **All three clouds simultaneously**: Pushes the timeline from 2 weeks to ~5 weeks — misses the Month 2 milestone and the seed-raise window.

### References

- **LLD 15**: Cross-Cloud Connectors
- **Workstream 15**: Execution tracking
- **Pitch deck v4**: §11 Month 2 milestones
- **Investor feedback**: Travis Priest, March 2026 — "until it works on camera across AWS + Azure, you're selling a slide, not a product"

---

## ADR-021: Connector Abstraction with Foreign-Cloud Interceptors

**Date**: May 2026
**Status**: Accepted

### Context

The cross-cloud demo requires Sentra to govern AI agents running on any major cloud (AWS Bedrock, Azure AI Foundry, GCP Vertex AI). The security controller's `/v1/validate` endpoint is already cloud-agnostic, but there is no existing abstraction for either (a) invoking native cloud agents from the dashboard or (b) intercepting tool calls inside foreign clouds. Need a pattern that scales to N clouds without forcing a common runtime.

### Decision

Use a two-layer pattern:

1. **Dashboard-side `AgentConnector` ABC** (Python) — one concrete subclass per cloud. Used by the dashboard, demo orchestrator, and integration tests. Not in the security path.
2. **Foreign-cloud interceptor** (per cloud) — Lambda for AWS, Azure Function for Azure, Cloud Run for GCP. Lives inside the foreign cloud, intercepts native tool calls, POSTs to `/v1/validate`, returns native-format ALLOW/DENY. This **is** the security path.

The dashboard layer and the interceptor layer share a translation contract — foreign tool event ↔ `ValidationRequest` — but are otherwise independent.

### Rationale

- **Separation of concerns**: Dashboard convenience vs. security enforcement are distinct concerns deployed in different environments. Coupling them would force the dashboard to live inside each cloud (or vice versa) — neither acceptable.
- **Per-cloud native idioms**: Each cloud has the right way to host an HTTP interceptor (Lambda handler, Azure Function binding, Flask on Cloud Run). Forcing a common runtime (e.g., all-Kubernetes) sacrifices the speed advantage of per-cloud serverless.
- **Reference implementation already exists**: The Bedrock Action Group Lambda at [lambda/bedrock_agent_actions/index.py:61-118](../lambda/bedrock_agent_actions/index.py) is the canonical interceptor. Every new cloud's interceptor mirrors its `validate_with_sentra()` function line-for-line.
- **Backward compatibility for Bedrock dashboard**: Existing `BedrockAgentCaller` becomes a thin shim around the new `BedrockConnector`. No changes required to `src/dashboard/tabs/agents_tab.py`.

### Consequences

- ✅ Adding a new cloud is two files: a new `XYZConnector(AgentConnector)` for the dashboard plus a new interceptor under `src/connectors/xyz/<runtime>/tool_interceptor/`.
- ✅ Security controller stays single-deployment, single-URL — no per-cloud forking.
- ✅ Validation pipeline (Trust → Policy → Sigma → Context → Abuse) sees all clouds uniformly.
- ✅ Backward compatibility: legacy dashboard imports work unchanged via a shim.
- ⚠️ Two layers must stay in sync via the `ValidationRequest` schema — schema changes require updating every interceptor. Mitigation: schema is small (<10 fields) and frozen for Phase 1.
- ⚠️ Cross-cloud network latency budget: ~120ms p95 vs. 80ms single-cloud. Mitigation: paired-region deployment, controller behind regional ALB.

### Alternatives Considered

1. **Single all-Kubernetes deployment with cloud connectors as pods**: Forces the customer/demo to run K8s in every cloud. Defeats the "deploy as a sidecar in your existing cloud" sell.
2. **A single SDK consumed by agents directly**: Requires agent-code changes for every customer. Defeats the "no SDK changes" sell in the pitch deck.
3. **A managed-SaaS gateway in front of every cloud's agents**: Works for B2C, fails for regulated markets (on-prem requirement). Phase 1 demo must support both deployment models.

### References

- **LLD 15**: Cross-Cloud Connectors §3 and §6
- **Workstream 15**: Milestone 1 (Tasks 1.1 and 1.2) implements this pattern
- **Existing reference implementation**: `lambda/bedrock_agent_actions/index.py`
- **Pitch deck v4 architectural narrative**: §6 (Kubernetes sidecar pattern), §7 (Wiz/Aqua structural incompatibility — they cannot do inline enforcement)

---

## ADR-022: Fix REST API Gateway via NLB + VPC Link

**Date**: May 2026
**Status**: Accepted

### Context

During Workstream 15 Milestone 2 smoke-testing, every `/v1/*` call to the deployed API Gateway URL (`https://iw3limi4k7.execute-api.us-east-1.amazonaws.com/prod/`) returned HTTP 500 with `Execution failed due to configuration error: Invalid endpoint address`. Root cause: [`cdk/utils/api_gateway_helpers.py:58`](cdk/utils/api_gateway_helpers.py) configures every integration with `ConnectionType.INTERNET` while the URI targets the Private ALB's `internal-*.elb.amazonaws.com` hostname — VPC-internal DNS that cannot be reached over the public internet by design. **The API Gateway has never been functional**, which means the Bedrock Action Group Lambda's calls to `/v1/validate` have been silently failing too.

The cross-cloud demo (Workstream 15 M3) was designed to have the Azure Function POST to this same URL. M3 cannot proceed until the gateway works.

The Public ALB has Cognito SSO as its default action; bypassing Cognito on a publicly-routable path on that ALB would be a SOC2 finding for an AI security product and is therefore not an option.

### Decision

Fix the existing REST API Gateway by adding the missing private-integration plumbing AWS designed for exactly this purpose:

1. Add an internal **Network Load Balancer (NLB)** in private subnets, with a target group of type ALB targeting the existing Private ALB.
2. Add a **VPC Link** from API Gateway → the NLB.
3. Change the integration helper from `ConnectionType.INTERNET` → `ConnectionType.VPC_LINK` and update the integration URI to use the NLB's DNS name.

Two entry points remain, each with the right auth model:
- **Public ALB**: human traffic, Cognito SSO.
- **API Gateway**: programmatic traffic, API key + Usage Plan.

### Rationale

- Restores the original [LLD 02](lld/02-api-gateway.md) and [design-hld.md §2.2](design-hld.md) design intent — API Gateway as the single programmatic entry point.
- Preserves the Cognito security boundary on the Public ALB (no bypass).
- Unblocks both Workstream 15 M3 (cross-cloud demo) and the pre-existing Bedrock Lambda silent-failure in one change.
- Minimal CDK surface area — one new SG, one new NLB + target group, one new VPC Link, one helper function update that cascades to all 22 routes.
- Same API Gateway URL — no downstream client changes required (Bedrock Lambda env var stays as-is).
- Canonical AWS-documented pattern: [REST API Gateway Private Integration via VPC Link](https://docs.aws.amazon.com/apigateway/latest/developerguide/getting-started-with-private-integration.html).
- CDK constructs all verified available in pinned `aws-cdk-lib==2.114.1`.

### Consequences

- ✅ Bedrock Lambda → `/v1/validate` calls work end-to-end (closes silent-failure since deploy).
- ✅ Cross-cloud Azure Function can target the same URL — M3 unblocked.
- ✅ Existing API Gateway URL preserved — no downstream client config changes.
- ⚠️ NLB monthly cost: ~$18 + Load Balancer Capacity Units. Acceptable for always-on infra.
- ⚠️ VPC Link provisioning is slow (5–10 min on first creation). One-time cost during deploy.
- ⚠️ Brief 5xx window (~30s) during integration cutover. Acceptable; dev environment.

### Alternatives Considered

1. **Add `/v1/*` rule to Public ALB that bypasses Cognito** — Rejected: SOC2 finding for an AI security product; sharp investor or security review would flag a public endpoint with weaker auth than the dashboard pages it shares an ALB with.
2. **Cognito M2M (client_credentials) flow for Azure** — Rejected: premature complexity. Cognito on Public ALB is designed for human SSO. API Gateway already has clean machine-to-machine auth (API keys).
3. **Migrate to HTTP API Gateway (newer, supports VPC Link to ALB directly)** — Rejected: requires rewriting every route in CDK with different constructs (effort: 1–1.5 days vs ~1 day for the NLB+VPC Link fix). URL pattern would change too.
4. **New dedicated API ALB without Cognito** — Rejected: same "public endpoint without SSO" optics on a different ALB; doesn't fix the security concern, just hides it behind a different name.
5. **Lambda Function URL as a VPC proxy** — Rejected: adds Lambda cold-start latency on every validate call; Function URLs have weaker auth options than API Gateway Usage Plans.

### References

- **LLD 16**: [API Gateway VPC Link Networking](lld/16-apigw-vpc-link-networking.md) — detailed design + diagrams + stack ownership
- **Workstream 16**: [API Gateway VPC Link Fix](tasks/workstream-16-apigw-vpc-link-networking.md) — execution tracking
- **AWS Docs**: [REST API Gateway Private Integration with VPC Link to NLB](https://docs.aws.amazon.com/apigateway/latest/developerguide/getting-started-with-private-integration.html)

---

## ADR-029: In-Process Local Enforcement via Signed Policy Bundle

**Date**: June 2026
**Status**: Accepted

### Context

Every guarded action is a blocking WAN POST to the hosted PDP ([guard.py:391](demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L391)) — the deterministic floor pays a ~0.6–1.2 s round-trip, and an agent stops enforcing entirely if the PDP is unreachable (violates NFR-4). FR-1.7 splits the PDP into the hosted engine **plus an in-process SDK evaluator** for the deterministic tier (tool allow/deny, parameter bounds, sequence, prompt-signature, and egress destination/host/path/port matching). A cached local evaluator is only safe if its policy is fresh, revocable, and fails closed when stale. Because the SDK is stdlib-only by design (`dependencies = []`, LLD 23 §2) and `cedarpy==4.8.4` ships native-wheel-only with no `py3-none-any` fallback, the SDK **cannot** embed the Cedar engine.

### Decision

The SDK evaluates a **pure-Python, stdlib-only interpreter of a *derived data bundle*** — not `cedarpy` in-process. The control plane publishes a **bundle** (allow/deny + parameter-bounds + sequence + prompt-signature + egress rules compiled from the authoritative Cedar policy) plus a **manifest of per-file SHA-256 hashes signed as a JWT**. The SDK:

- **Background-polls** on a timer (never on the validate path), using **conditional GET / ETag → 304** so an unchanged bundle is near-free; **keeps last-good** on any fetch failure.
- **Verifies the JWT signature + every file hash before swapping** a bundle in; rejects a tampered/unsigned bundle (fail-secure).
- Enforces a **fail-closed max-staleness bound computed from a monotonic clock** (`time.monotonic`, not wall clock) — past the bound the local floor reverts to a deny-by-default floor (deny dangerous tools, allow only an explicit safe set).
- Reads a **revocation-epoch item** (the LLD 26 §3.6 `revoked-since` pattern) at most once per short interval to invalidate stale-epoch bundles below the poll interval.
- Enforces **anti-rollback**: a monotonic `bundle_version` + `nbf`/`iat` **inside the JWT-signed payload**; the SDK rejects any version `<=` the highest seen (keep-last-good is bounded by it).

**Signing-key lifecycle**: rotation with a **dual-sign overlap window sized below the max-staleness bound**; the bundle-signing pubkey is a **distinct keypair from the per-agent `kid`-LRU**, pinned at SDK build/install time; **per-tenant(-group) signing keys** bound blast radius; a **key-compromise path** (rotate + force-rotate pin + reject `kid`) distinct from bundle-version revocation. Signature verify uses the SDK crypto extra; for **money-movement tenants the crypto-verify path is REQUIRED** (hash-only is not edge-cache-safe behind a CDN). The verifier is either a confirmed-portable pure-Python ES256 (`ecdsa==0.19.2`, `py2.py3-none-any`, verify-only-no-secret rationale) or a costed per-platform packaging path — at least one preserves the drop-in promise.

### Rationale

- **Tenet C** (refresh out-of-band, decide in-process), **tenet 1** (control plane never on the validate path — only the background timer talks to it), **tenet 2** (stale-past-bound fails closed, not open).
- A stale policy that still ALLOWs is the most devastating failure — staleness is a **safety** mechanism, not a freshness nicety; the bound + revocation epoch cap how long a no-longer-valid ALLOW can survive.
- The interpreter is a **closed, non-Turing lookup table**, not a second Cedar engine: the bundle-emit step is an **allowlist** of supported constructs and **fail-closed-escalates everything else** (an out-of-subset `forbid` is never silently dropped — a dropped forbid = ALLOW-by-omission = silent fail-open). A differential conformance test asserts interpreter ≡ `cedarpy` on that closed subset.

### Consequences

- ✅ Deterministic-tier common path resolves in-process (tens of ms) with no WAN round-trip; an unreachable PDP no longer stops enforcement (NFR-4).
- ✅ Tampered/unsigned/stale/rolled-back bundles are all rejected fail-secure; blocking the refresh endpoint forces deny-by-default, never a frozen ALLOW.
- ✅ Per-tenant signing contains a key leak; monotonic-clock staleness defeats wall-clock rewind.
- ⚠️ A pure-Python interpreter must stay differentially equivalent to `cedarpy` on the closed subset — a divergence where the edge ALLOWs what the server would DENY is a silent fail-open; the differential corpus (incl. egress + subset-boundary cases) is a hard build requirement.
- ⚠️ The crypto extra / per-platform packaging punctures the stdlib-only invariant for money-movement tenants — the LLD must pick and cost one path.
- ⚠️ A bundle-distribution outage longer than the staleness bound could fleet-degrade every customer at once — mitigated by multi-region CDN + HSM-backed multi-region signer + a bound sized above signing-path recovery (Appendix H); NFR-3 must be demonstrated, not asserted.

### Alternatives Considered

1. **Push / long-poll (server-initiated)** — Rejected: maintaining server-held connections to a churning ephemeral Lambda/Function fleet is heavy and stateful, and a cold-started instance still needs a pull to bootstrap.
2. **DDB-signal-only (no cached bundle)** — Rejected as the policy source: re-introduces a per-call DDB read on the hot path + a cross-tenant hot partition. Kept only as the cheap revocation-epoch layer.
3. **No local eval (hosted-only status quo)** — Rejected: fails the two reasons the split exists — latency stays a WAN round-trip and an unreachable PDP means no enforcement.
4. **Embed `cedarpy` in the SDK** — Rejected: native-wheel-only, breaks the stdlib-only vendor-unchanged invariant LLD 23 exists to protect.

### References

- **HLD**: [hld/serverless-edition.md](hld/serverless-edition.md) §6.2(a), Appendix C (interpreter soundness), Appendix D (signing-key lifecycle), Appendix H (availability/fail-closed sizing)
- **LLD 23** (SDK interpreter — must not add a native dep), **LLD 24** (latency), **new Cedar LLD** (hosted-side bundle-emit + interpreter↔`cedarpy` differential corpus)
- **Verified**: `cedarpy==4.8.4` native-wheel-only (pypi.org/project/cedarpy/4.8.4); `ecdsa==0.19.2` `py2.py3-none-any` verify-only (pypi.org/project/ecdsa/0.19.2)

---

## ADR-030: Cost-Annotated DAG Scheduler for the Validation Pipeline

**Date**: June 2026
**Status**: Accepted

### Context

The validation pipeline is today a **fixed sequential chain**: trust → policy/Cedar → cross-agent → prompt-signature → context → abuse → ML classifier (ML moved last in WS24 M4.1), each `await`ed in order ([validation_service.py:220](src/security-controller/app/services/validation_service.py#L220)). Adding the D1–D7 defense-in-depth layers to a sequential chain grows p99 with every added layer — the NFR-1/NFR-2 latency budget breaks. Moving ML last is already a frontier-first *partial* optimization; the design needs to generalize it rather than keep patching a sequential baseline.

### Decision

Model the validators as nodes in a **cost-annotated directed acyclic graph** (cost = latency class; edges = real data dependencies):

- **Tier-0** — cheap deterministic checks (trust, Cedar, cross-agent, prompt-signature, context/sequence, abuse; ~1–5 ms each) run first **with short-circuit**: a DENY here stops before any model runs.
- **Tier-1** — expensive models (ML classifier, D1–D7) are **gathered in parallel** (latency = max of independent nodes, not sum) only for the survivors that passed tier-0. Dependency edges express the real D1–D7 ordering (D2 taint → D4 information-flow control → D5 output DLP), which runs sequentially and sums.

The **static two-phase split** (all-cheap-then-all-expensive) is the first implementable milestone *inside* this DAG; the DAG generalizes it without re-architecture when a dependency edge is needed. Replaces the fixed-sequential pipeline at [validation_service.py:220](src/security-controller/app/services/validation_service.py#L220). Realizes AD-4.

### Rationale

- **Tenet 5** (latency scales with risk — a cheap DENY skips model cost) and **tenet 4** (independent layers run in parallel, no single point of detection failure).
- A flat two-phase model cannot express the D1–D7 dependency chain (taint must precede IFC must precede output-DLP); the moment a layer consumes another's output it needs a re-write — the exact late-add the architecture-bender rule rejects.
- Depth that adds *independent* detectors is near-free (parallel-gather); depth that *extends a chain* still adds its own latency — the scheduler removes the all-sequential cost, not genuine data-dependency cost.

### Consequences

- ✅ Adding independent detectors no longer grows p99 linearly; a tier-0 DENY pays for none of the expensive tier.
- ✅ The D1–D7 dependency ordering is expressible as edges, not hard-coded sequence.
- ⚠️ The scheduler's run model must be reconciled with the audit trail (a skipped detector must be recorded "not-run") — see ADR-031.
- ⚠️ Escalated (tier-1) calls on Serverless still pay the full WAN + Bedrock-inference latency; the DAG bounds server-side ordering, not the WAN leg (§6.4).

### Alternatives Considered

1. **Static two-phase split only (no DAG)** — Rejected: cannot carry D1–D7 dependencies; needs a re-write the moment a layer consumes another's output. Kept as the first milestone *inside* the DAG.
2. **Keep the sequential chain** — Rejected: latency grows linearly with each added layer — precisely the failure the scheduler exists to prevent.

### References

- **HLD**: [hld/serverless-edition.md](hld/serverless-edition.md) §6.2(c)
- **LLD 20** (D1–D7), controller pipeline (**LLD 03**)
- Realizes **AD-4** (deterministic-first, parallel models)

---

## ADR-031: Record-What-Ran Decision Trail Reconciled with the Scheduler

**Date**: June 2026
**Status**: Accepted

### Context

FR-6.8 wants the audit to record **every** detector that ran and its verdict; the combiner today **short-circuits on first DENY** so later layers don't run ([validation_service.py:220](src/security-controller/app/services/validation_service.py#L220)), and ADR-030's scheduler *also* gates expensive detectors behind cheap ones. A full record and running as little as possible appear to conflict — two requirements touch the same run model and must define **one** execution model or they contradict. This is the single most important reconciliation in the HLD.

### Decision

**"Record what ran, force nothing extra."** The scheduler runs tier-0 (with short-circuit) + tier-1 parallel for survivors (exactly ADR-030); the trail records **every layer that actually executed** with its verdict + source + latency, and on a short-circuit DENY explicitly records the prefix that ran plus marks later layers **"not-run (gated by earlier DENY/cost)."** No extra detectors are run just to fill the record. The `Signal[]` collected via `_capture()` ([validation_service.py:237](src/security-controller/app/services/validation_service.py#L237)) is the seed; the change is the **run model** (persist not-run markers + keep the trail under the scheduler), **not** the DenyOverrides algorithm ([deny_overrides.py](src/security-controller/app/combiners/deny_overrides.py) — any DENY wins → priority → confidence → alphabetical source — stays byte-for-byte).

A **tunable per-tenant/per-session high-assurance mode** runs the full deterministic tier for the trail even after a DENY (offered as a setting, not the default). The persisted trail captures: **(1) coverage** (every detector that could run for the phase, which ran vs. not-run, each with verdict/source/latency); **(2) block point + why, with depth** (state/layer + reason + prompt + tool & parameters + caller→target agent + IP/source); **(3) both outcomes** (ALLOW and DENY, not deny-only); **(4) the phase** (`request|content|output|memory`).

### Rationale

- **Tie-breaker B** (record what ran; don't over-execute to get a trail), **tenet 5** (don't pay for layers risk didn't warrant), **tenet 3** (every verdict names its deciding source and is auditable — the not-run markers keep the trail honest about what didn't run).
- Running all layers on every request would blow the latency budget and re-incur the exact cost the scheduler exists to avoid.

### Consequences

- ✅ The trail is complete about *what ran* and honest about *what didn't* (and why), with no extra detector cost.
- ✅ High-assurance tenants can opt into a full deterministic trail via a tunable mode.
- ✅ The DenyOverrides algorithm is out of scope of this change — no behavioral drift in verdict combination.
- ⚠️ The signal store / trail record shape (LLD 17) must carry the not-run markers + `winning_source` + the four-field detail set — a schema deliverable, not just a code change.

### Alternatives Considered

1. **Always run all layers, every request** — Rejected: blows the latency budget, contradicts tenet 5 (a tier-0 DENY would still pay for D1–D7).
2. **Always-run-cheap-tier-then-short-circuit** (full deterministic trail, gate only the expensive tier) — a small constant overhead on every DENY; kept as the **tunable high-assurance mode** inside the recommendation, not the default.

### References

- **HLD**: [hld/serverless-edition.md](hld/serverless-edition.md) §6.2(d)
- **LLD 17** (signal store / trail shape)
- Related: ADR-030 (scheduler run model); the §6.4 escalate-async fence (money-movement hard fail-closed) is referenced from this run-model

---

## ADR-032: Two-Tier Input Redaction and the Three-Clause NFR-7 Amendment

**Date**: June 2026
**Status**: Accepted

### Context

Serverless is the only edition where customer content leaves the boundary. The SDK auto-captures `tool_params` + `user_input` and POSTs them **un-redacted** today ([guard.py:325](demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L325)). The owner flagged this serious. A pure regex/checksum scrubber reliably catches *structured* identifiers (card numbers, SSNs, emails, high-entropy secrets) but not *free-text/semantic* PHI (names, conditions, addresses in prose). An earlier position routed all PHI to in-VPC on the reasoning that raw PHI reaching our cloud "breaks NFR-7" — but that rested on a self-imposed bar stricter than HIPAA, which explicitly contemplates a business associate processing PHI under a BAA (45 CFR 160.103).

### Decision

A **two-tier redactor**:

- **Tier 1 — structured PII/PCI, inline at the edge.** The redactor **ships in the SDK** (same stdlib-only install) and runs **before egress**. Deterministic: regex + Luhn card check + secret/credential entropy + lite-NER. **Structure-preserving**: sensitive *values* are replaced with **typed tokens** (`<CARD>`, `<SSN>`, `<EMAIL>`, `<SECRET>`) so detection still operates on the redacted text; **any pre-existing token-shaped substring in the input is escaped/namespaced first** so attacker text can never spoof a redactor-emitted token. Raw structured PII never leaves. **Hard GA gate** for any sensitive-data customer. Redaction runs on **every egressing phase** (request/content/output/memory), not just `request`.
- **Tier 2 — free-text PHI, server-side under a BAA (P0).** Free-text semantic PHI is redacted by a **server-side semantic NER layer** — too heavy for the stdlib edge (CPU spaCy ~50 ms+, transformer NER ~700 ms). Compliance basis is **containment** (redaction = defense-in-depth). Self-hosted **Presidio (MIT)** — **no managed subprocessor**; the latency form is a **warm ONNX-int8 microservice**. Raw free-text PHI transits under a BAA, is processed **transiently, never retained, never logged, with no human access**, then discarded. **This is P0 — it ships in the first-wave Serverless build**, gated only by a measured recall target + counsel's BAA sign-off. This is how **HIPAA/PHI customers use Serverless.**

The **Nitro Enclave** (a TEE upgrading the claim to "never readable") is a **demoted roadmap note, NOT the GA basis**. **In-VPC** stays the floor for **air-gapped / no-egress mandates only**.

**NFR-7 is amended to three clauses**: **(a)** no raw retention on any edition (not logs, audit, meter, feedback store, or crash dumps); **(b)** an opt-in, DPA-scoped, retention-bounded **redacted** feedback store (redacted records only, never raw); **(c)** **PHI-transit-under-BAA** — free-text PHI may transit to the hosted PDP under a BAA, processed transiently / not retained / not logged / no human access (replaces the old "raw never leaves the customer boundary"). Anchored to **HIPAA Safe Harbor (45 CFR 164.514(b)(2))** + **PCI-DSS** (PAN mask, SAD never-store) + **GDPR Recital 26** (masking is pseudonymisation, still personal data).

### Rationale

- **Tenet 6** (the data boundary is the customer's — set by edition + the BAA) and **tenet 2** (deterministic structured redaction fails safe inline).
- Because *our* SDK is what pulls `tool_params`/`user_input` across the wire, *we* must redact what *we* capture — before the network POST; the customer cannot be burdened or trusted to pre-redact for our detection.
- The honest claim is "transient + not-retained + not-logged + no human access under a BAA," **not** "machine-unreadable by us" (the redaction code reads the value to scrub it) — the enclave is what would upgrade that later.

### Consequences

- ✅ Structured PII/PCI never leaves the edge; HIPAA/PHI customers can use Serverless under a BAA at GA (not routed to in-VPC).
- ✅ The redactor rides the SDK install — no separate component to deploy.
- ⚠️ Edge redaction strips the very values the deep tier would read — the **masked-vs-unmasked recall-delta** is unmeasured and is a **precondition of locking the redaction GA gate** (Appendix G), not a residual to defer.
- ⚠️ No-retention of raw PHI is a **hard engineering invariant the LLD must PROVE** (no raw in logs/feedback/crash dumps) — under clause (c) a logging bug is a *reportable breach*, not just an NFR miss.
- ⚠️ Image/binary content (FR-3.15) and the server-side `REDACT`-verdict rewrite path (FR-3.7) are scoped **out/stubbed** explicitly (blocked from egress or routed to in-VPC until designed).
- ⚠️ Supersedes the old "PHI → in-VPC only" conclusion and Option-B's blanket "hosted redaction always violates NFR-7" *for the BAA-covered PHI case* — a propagate-change target across PRD/ARCHITECTURE/STRATEGY/sub-PRD (NFR-7 3-clause form).
- ⚠️ Tier-2 server-side NER is a **happens-before barrier** on the PHI content path — redaction completes *before* any audit/detector/persist read of that content; the parallel/off-path latency optimization applies only to the verdict-return of non-PHI-bearing calls ([LLD 29](lld/29-redaction.md) §4.1/§5.3, grill finding F1). A PHI-bearing free-text call pays the NER latency on the **critical path** (≤900 ms ML budget), not hidden behind the floor.

### Alternatives Considered

1. **Hosted-side redaction (redact after arrival)** — Rejected for structured PII: the boundary is already crossed; no-retention doesn't undo that the value transited. (Retained, under a BAA, only for the free-text-PHI case where the semantic model is unavoidably server-side.)
2. **Customer pre-redacts before calling us** — Rejected: can't burden the customer to redact for *our* detection, can't trust a self-asserted "already clean," and the SDK auto-captures raw `tool_params` they never touched.
3. **Managed subprocessor (Comprehend Medical / Google DLP)** — Rejected as the basis: adds a subprocessor + a network round-trip; self-hosted Presidio keeps the processing in-boundary under our BAA.

### References

- **HLD**: [hld/serverless-edition.md](hld/serverless-edition.md) §6.2(e), Appendix I (mechanism/standard/enclave), Appendix F (data-class allowlist), Appendix G (redaction gate pass/fail)
- **LLD 29** (redaction), **LLD 23** (SDK edge redactor), **LLD 17** (feedback store)
- **Standards**: 45 CFR 164.514(b)(2) (HIPAA Safe Harbor), 45 CFR 160.103 (business associate), PCI-DSS, GDPR Recital 26

---

## ADR-033: Durable Meter-Event Pipeline (Billing Source of Truth)

**Date**: June 2026
**Status**: Accepted

### Context

We charge per **governed agent** (not per check), consistent with ARCHITECTURE §2.10 ("metering per validation would tax coverage"). But every event write today is **fire-and-forget** ([validation_service.py:512](src/security-controller/app/services/validation_service.py#L512) via `_fire_and_forget`; metrics swallow failures, [metrics_publisher.py:126](src/security-controller/app/utils/metrics_publisher.py#L126)) and the signal store has **no DynamoDB Streams** — so neither the CloudWatch counters nor the audit store can be a billing source of truth (a dropped write is silently lost, and there is no stream to drive a rollup). ADR-029's local floor compounds this: most benign calls resolve in-process and never reach the server, so per-server-call billing would structurally under-count and couple the bill to the threat mix.

### Decision

A **new durable meter-event pipeline** (adapted from the internal Synapse multi-tenant metering pattern — durable source-of-truth + dedup-on-unique-id + recomputed aggregate + hourly audit re-drive):

- **`sentra-meter-events`** (durable source of truth): PK `tenant_id`, SK `request_id` (idempotency key); attrs `agent_id`, `event_time`, `decision`, `phase`, `sku`, `usage_unit=1`, `processed`, `claimed_tenant_id`, `expires_at` (TTL ~13 mo). Write = conditional `PutItem attribute_not_exists(request_id)`, **AWAITED with back-off retry (durable-before-ack)** → **DLQ on exhausted retry, never silently dropped**. **DynamoDB Streams ENABLED.**
- **`sentra-usage-rollup`** (aggregate): PK `tenant_id`, SK `billing_period#agent_id`; aggregation = **recomputed SUM over the period (idempotent)** so a re-driven event changes nothing.
- **Streams → aggregator Lambda → rollup**; an **hourly EventBridge-Scheduler audit Lambda** finds `processed=false`/missing events and **re-drives** them.

The **charged dimension stays per governed agent**; the per-call event is the usage/evidence substrate, not the billable unit. **Governed-agent presence is registered on the durable bundle-fetch + low-frequency heartbeat path** (not per-call beacons), so an agent that never escalates is still counted. Edge-resolved usage bills off a **non-durable edge beacon** (not covered by the ledger's no-miss) — tolerable because tiers are coarse order-of-magnitude bands and existence is registered durably. **CloudWatch counters (`Decisions{tenant_id}`, `ValidationsTotal{AgentId}`) are demoted to ops/dashboards only.**

**Spoof/identity-DENY dual-tag split**: spoof-DENYs are counted against the **claimed tenant for the SECURITY/visibility view only** (rate-limited/capped + written with a **durable** audit write so a flood can't erase the evidence), and against **`_unverified` for billing/quota** — **never** the claimed tenant's quota/rate budget (the `claimed_tenant_id` is attacker-asserted; drawing quota from it would be a third-party quota-exhaustion DoS).

### Rationale

- **Tenet D** — an unattributable/lost verdict is a metering and isolation defect; billing needs a ledger that never silently loses an event, which the best-effort counters cannot be.
- Charging per governed agent is the **correct** unit given the local floor: governed-agent count doesn't depend on how many calls reach the server; volume loss only sets a coarse tier band.
- Metering on an attacker-controllable key (`claimed_tenant_id`) is a hazard, not just a billing line — hence the dual-tag split.

### Consequences

- ✅ No-miss (server-arrived events), exactly-once (conditional-put dedup + idempotent recomputed-SUM), re-drivable after a large-scale event (Streams + hourly audit).
- ✅ Spoof-DENYs are visible in the victim tenant's security view without letting an attacker exhaust that tenant's quota.
- ⚠️ Net-new COGS: an awaited meter `PutItem` per escalated call (roughly doubles per-call DDB write cost for escalated calls) + per-escalation Bedrock inference — both bounded by the escalation rate (residual #6), which becomes the single biggest COGS variable.
- ⚠️ Edge-beacon volume is not no-miss; billing error must be bounded to **NFR-12 (≥99.9%)** as an LLD acceptance criterion, plus a **DLQ-drain runbook/SLA** (Appendix H).
- ⚠️ Partially supersedes ARCHITECTURE §2.10's "no separate metering path" mechanism claim (the per-agent *charged dimension* is unchanged and re-affirmed) — a propagate-change target.

### Alternatives Considered

1. **Reuse the existing fire-and-forget CloudWatch/audit counters as the billing ledger** — Rejected: best-effort writes are silently lost and there is no stream to drive a rollup; kept ops-only.
2. **Per-server-call billable unit** — Rejected: the local floor makes most benign calls invisible to the server, so it structurally under-counts and taxes coverage (couples the bill to threat mix).
3. **Credit the `claimed_tenant_id` on a spoof to billing/quota** — Rejected: attacker-asserted key → third-party quota-exhaustion DoS.

### References

- **HLD**: [hld/serverless-edition.md](hld/serverless-edition.md) §6.5, Appendix H (loss model + DLQ-drain runbook)
- **LLD 17** + a new metering LLD; **ARCHITECTURE §2.10** (charged dimension re-affirmed; mechanism sentence reconciled)

---

## ADR-034: The Deterministic Floor Is Non-Disableable; No Customer Detection Dial

**Date**: June 2026
**Status**: Accepted

### Context

A customer-facing light/medium/strong/extra-strong detection dial was considered. Today's differentiation is thin (ML is shadow-only, D1–D7 is roadmap), and a "light" tier is a **one-way door** — selling a weaker mode then retracting it is hard. The focus now is basic billing, not a detection-strength SKU.

### Decision

The customer-selectable detection-strength dial is **NOT built now**. For now **all detectors are enabled and NOTHING is customer-disableable** (revisit later). **Invariant, locked as an ADR**: whatever modes ever exist, the **Cedar + prompt-signature deterministic floor is NON-DISABLEABLE in every mode and every edition** — so a future "mode" can never mean "unprotected." The **local-floor kill-switch** disables only the **edge evaluation *location*** (the SDK falls back to the hosted PDP for the decision), **never enforcement itself** — the floor is still evaluated, just server-side.

### Rationale

- **Tenet 4** (defense in depth — no removable floor) and **tenet 8** (honest staging — don't sell a weaker mode before the depth exists to tier).
- A "light" detection tier is a one-way door; guarding the floor as non-disableable prevents a future mode from becoming a hole.

### Consequences

- ✅ No mode or edition can ever run "unprotected" — the deterministic floor is always on.
- ✅ Product surface stays simple (basic billing, not a detection-strength SKU).
- ✅ The kill-switch is an operability lever (evaluate locally vs. hosted), not a way to turn enforcement off.
- ⚠️ Customers who want a lighter/cheaper posture are not served by a dial now — revisited only when the depth exists to tier honestly.

### Alternatives Considered

1. **Ship the light/medium/strong dial now** — Rejected: a one-way door on thin differentiation; ML is shadow-only and D1–D7 is roadmap, so the tiers wouldn't be honest.
2. **Allow the deterministic floor to be disabled in a "light" mode** — Rejected: makes "mode" mean "unprotected" — the exact hole the invariant guards against.

### References

- **HLD**: [hld/serverless-edition.md](hld/serverless-edition.md) §6.2(h)
- **LLD 28** §5.6 (local-floor kill-switch semantics); controller pipeline / config

---

## ADR-035: Console Federation (SAML + OIDC + SCIM) Behind an IdP-Neutral Seam — Scoped, Deferred

**Date**: June 2026
**Status**: Accepted

### Context

The web console authenticates operators via Cognito OIDC but is **not tenant-scoped** (no tenant claim, no membership mapping, no RBAC — sub-PRD §4.10). Worse, today's console derives tenant **cosmetically from the email domain** (`web/console/src/lib/auth.ts:54-56` marks it "DISPLAY-ONLY, NON-AUTHORITATIVE") — as an *authority* that breaks isolation (a contractor with a customer's domain maps to the wrong tenant). The runtime fix keeps Cognito now and hardens the seam (refines AD-8/ADR-019); this ADR pre-designs the eventual provider switch so it is cheap when made.

### Decision

Write the **SAML + OIDC + SCIM federation** design **now**, but **defer the actual provider switch (done last)** — it touches too much to do early. Two insurance moves are taken now so the switch is cheap: **(1)** the tenant-root identity is renamed from "Cognito `sub`" to an **IdP-neutral "verified operator subject"** behind **ONE claim-extraction seam** (only that seam changes when federation lands); **(2)** this ADR pre-designs SAML + OIDC + SCIM so the switch is not improvised later.

**Server-derived `sentra-tenant-members` membership is the tenant authority — NEVER the email domain.** IdP group claims map to roles (**owner | admin | editor | viewer** + reserved `_platform`). A multi-tenant operator gets a tenant switcher: the API accepts an **`X-Aegion-Tenant`** header **validated server-side against the membership set** (deny if not a member) before honoring it; default = the operator's sole/primary tenant. `require_role` (LLD 26 §6.3) is the server-side authority; UI role-gating is UX only, never the boundary. This blends into the already-designed LLD 26 §5–6 — not reinvented.

### Rationale

- **Tenet 7** (multi-tenant from the foundation, not retrofitted) and the reuse discipline (matches the Splunk/Datadog/Auth0/Okta org→membership→role pattern, IdP pluggable beneath a stable membership/role layer).
- Email-domain inference cannot be the isolation boundary — a spoofable/multi-domain signal; the membership table is the fix.
- Cognito natively federates SAML/OIDC later as a config add, so pre-designing the seam makes the switch a configuration change, not a re-platform.

### Consequences

- ✅ The current email-domain isolation weakness (Option-B security issue) is closed — every tenant decision resolves server-side against `sentra-tenant-members`.
- ✅ When federation lands, only the claim-extraction seam changes, not every call site.
- ✅ RBAC + server-validated tenant switcher ship now on the hardened Cognito substrate.
- ⚠️ SAML-now vs OIDC-now is an open sequencing sub-question (non-blocking residual).
- ⚠️ SCIM deprovisioning + the full provider switch are **deferred** — scoped here, done last; until then Cognito is the substrate.

### Alternatives Considered

1. **Cognito-only email-domain inference as the authority** — Rejected: this is today's security issue; a spoofable/multi-domain signal cannot be the isolation boundary.
2. **Bespoke RBAC from scratch** — Rejected: reinvents the proven Auth0-Organizations / Splunk-Cloud org→tenant→role pattern; a hand-rolled authz model is a security-risk surface.
3. **Switch the identity provider now** — Rejected: touches too much to do early; the seam + deferred ADR make it cheap to do last.

### References

- **HLD**: [hld/serverless-edition.md](hld/serverless-edition.md) §6.2(f)
- **LLD 26 §5–6** (`web/console` tenancy/RBAC — the anchor; LLD 04/Streamlit decommissioned)
- **Refines AD-8 / ADR-019**

---

## Future ADRs to Consider (Post-MVP)

- **ADR-023**: Migration from ECS Fargate to EKS
- **ADR-024**: Adding CEDAR policy language support
- **ADR-025**: ML-based anomaly detection layer
- **ADR-026**: Automated rollback for low-risk actions
- **ADR-027**: Multi-region deployment strategy
- **ADR-028**: Integration with external SIEM systems

---

**Document Version**: 2.3
**Last Updated**: June 30, 2026
**Status**: Active - Reference during implementation
**Next Review**: Post-MVP (after Week 4)
