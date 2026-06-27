> ⚠️ **DEPRECATED (2026-06-28) — historical, not maintained.** Superseded by [pitch/share/architecture-brief.md](pitch/share/architecture-brief.md). Do not rely on this document for current architecture, requirements, or positioning; kept for historical reference only.

# Deployment & Positioning Q&A

**Date**: January 11, 2025
**Context**: MVP architecture clarifications and competitive positioning

---

## Your Questions Addressed

### 1. **Private Endpoint Only (No R53)**
**Answer**: ✅ **IMPLEMENTED**

**Changes Made**:
- Removed Route 53 + CloudFront from architecture diagram
- Changed API Gateway to **Private REST API** (VPC-only, no public internet)
- Access method: VPN or AWS SSM Session Manager for demos
- Updated in `MVP-Requirements-New.md` lines 454-463

**Benefit**: Simpler architecture, lower cost, demonstrates security-first approach

---

### 2. **Why Do We Need CDN?**
**Answer**: ✅ **WE DON'T - REMOVED**

**Rationale**:
- CDN (CloudFront) only needed for public internet-facing apps with global users
- MVP is private VPC deployment for investor demos
- No need for edge caching or geo-distribution
- Cost savings: ~$10-20/month

**Changes Made**: Removed CloudFront from architecture diagram

---

### 3. **Finance Agent Service on ECS Cluster?**
**Answer**: ✅ **YES - Clarified in Diagram**

**ECS Fargate Cluster Composition**:
```
ECS Cluster: sentra-mvp-cluster
├── Service 1: Security Controller (FastAPI)
│   └── Task: security-controller-task (2 vCPU, 4GB RAM)
├── Service 2: Dashboard (Streamlit)
│   └── Task: dashboard-task (2 vCPU, 4GB RAM)
└── Service 3: Finance Agent (LangChain)
    └── Task: finance-agent-task (2 vCPU, 4GB RAM)
```

**Why Agent on ECS**:
1. Demonstrates production deployment model
2. Shows agents can run anywhere (not just cloud-native services)
3. Easy to add more agents (just deploy new tasks)
4. Consistent with "Kubernetes for agents" vision (ECS is AWS's container orchestrator)

**Location in Doc**: Architecture diagram lines 478-487

---

### 4. **All DynamoDB Tables On-Demand?**
**Answer**: ✅ **YES - UPDATED**

**Changes Made**:
- Changed `session_context` from provisioned to **on-demand**
- Changed `policies` from provisioned to **on-demand**
- `audit_logs` already on-demand
- Updated in lines 492-496

**Rationale**:
- MVP has unpredictable demo load (spiky traffic)
- On-demand pricing: $1.25 per million writes, $0.25 per million reads
- Provisioned only makes sense for consistent predictable traffic
- Cost for MVP demos: ~$1-2/day vs. ~$5-10/day provisioned (underutilized)

**Cost Comparison**:
```
Provisioned (5 RCU/WCU each table):
- session_context: $3.47/month
- policies: $3.47/month
- Total: ~$7/month (but wastes capacity during idle time)

On-Demand:
- Typical demo day: 1000 writes, 5000 reads
- Cost: ~$1.50/day on heavy demo days
- Cost: ~$0.10/day idle days
- Average: ~$15-20/month (only pay for what you use)
```

---

### 5. **Feature 1 API - Do We Accept CEDAR Policies? Validate Threats Too?**
**Answer**: ✅ **CLARIFIED IN FEATURE 1 OVERVIEW**

**API Structure** (lines 743-755):

```
POST /validate
Request:
{
  "request_id": "req-123",
  "agent_id": "finance-agent",
  "user_input": "Process refund for $50",
  "tool_name": "process_refund",
  "tool_params": {"order_id": "12345", "amount": 50}
}

Response:
{
  "decision": "ALLOW | DENY | REDACT",
  "reason": "Policy violation: max refund $5000 exceeded",
  "matched_rules": ["max-refund-amount", "prompt_injection_basic"],
  "threat_type": "PROMPT_INJECTION | POLICY_VIOLATION | null",
  "code_attribution": {...}
}
```

**What Gets Validated (ALL in one /validate call)**:
1. ✅ **Policies** (business rules like refund limits)
2. ✅ **Threat Detection** (Sigma rules for prompt injection, jailbreak, etc.)
3. ✅ **Context Rules** (workflow validation like check_order before process_refund)
4. ✅ **Abuse Prevention** (rate limiting, anomaly thresholds)

**Policy Format Support**:
- **MVP**: YAML with Python expressions (simple, fast to implement)
  ```yaml
  - name: max-refund-amount
    condition: "refund_amount <= 5000"
    action: deny
  ```
- **Post-MVP**: CEDAR support for AWS Bedrock customers migrating to Sentra
  ```cedar
  permit(
    principal is Agent,
    action == RefundAction,
    resource is Order
  ) when { resource.amount <= 5000 };
  ```

**Key Point**: Security Controller is **NOT just policy validation** - it's a unified validation engine that checks policies + threats + context + abuse in one API call.

---

### 6. **USP & Positioning: Why Choose Sentra?**
**Answer**: ✅ **COMPREHENSIVE SECTION ADDED (Lines 25-118)**

#### **Key Competitive Finding**:
**Kagent (Solo.io)** launched in 2025 as "Kubernetes for AI agents" - but focuses on **DevOps automation** (kubectl, cluster management), NOT security/governance. This validates the Kubernetes analogy but leaves security as a **wide-open market**.

#### **Sentra's Core USP**: "Security Control Plane for Any Agent, Anywhere"

---

### **A. Why Security-as-a-Service on AWS/Azure/GCP?**

**Use Case**: Customer has agents on AWS Bedrock, Azure OpenAI, GCP Vertex

**Sentra Value**:
1. **Multi-Cloud Unified Governance** - One control plane for ALL agents
   - AWS AgentCore: AWS-only ❌
   - Sentra: AWS + Azure + GCP + on-prem ✅

2. **No Vendor Lock-In**
   - Can migrate agents between clouds without re-engineering security
   - Avoid 20-30% annual cloud price increases
   - Negotiating leverage with AWS/Azure/GCP

3. **Cross-Agent Orchestration**
   - Agent on AWS Bedrock calls agent on Azure OpenAI securely
   - Cloud-native: Each cloud has separate security boundaries ❌
   - Sentra: Unified security mesh ✅

4. **Deeper Security Than Cloud Guardrails**
   - AWS Bedrock Guardrails: Input/output filtering only (PII, toxicity)
   - Sentra: Runtime validation of tool calls, parameters, sequences, context
   - Prevents $4.80M average AI breach (97% orgs lack AI access controls)

5. **Rollback & Forensics**
   - Cloud solutions: No rollback ❌
   - Sentra: Compensating transactions + code-level attribution ✅
   - Meets SOC2, HIPAA, GDPR, EU AI Act compliance

---

### **B. Why On-Prem Sentra Platform (vs. Deploying Agents on AWS/Azure/GCP)?**

**Use Case**: Customer building NEW agents, deciding where to deploy them

**Sentra On-Prem Value**:

1. **Kubernetes-Native Developer Experience**
   - Define agents as CRDs (like Pods): `kubectl apply -f agent.yaml`
   - GitOps deployment (ArgoCD/Flux)
   - Familiar to DevOps teams already using Kubernetes
   - **vs. AWS Bedrock**: Console-driven, black box orchestration

2. **Integrated Platform (Not Duct-Taped Services)**
   - ONE platform: Agent deployment + security + observability
   - **vs. AWS**: Wire together Bedrock + Guardrails + CloudWatch + Lambda + custom code
   - Built-in policy templates, rollback, attribution

3. **Cost Optimization (High-Volume Users)**
   - AWS Bedrock: Per-token pricing (unpredictable, can spike)
   - Sentra On-Prem: Fixed infrastructure cost
   - **Breakeven**: 12-18 months for orgs processing 500M+ tokens/month
   - **Savings**: 50-70% cost reduction
   - **Example**: E-commerce with 1000 agents → $2M/year AWS vs. $600K/year on-prem

4. **Full Control & Customization**
   - Customize orchestration logic (vs. AWS black box)
   - Debug locally with full stack traces
   - No cloud throttling or quota limits
   - Run on any Kubernetes (EKS, AKS, GKE, on-prem)

5. **Data Sovereignty & Compliance**
   - Financial services (SOX): Data CANNOT leave network
   - Healthcare (HIPAA): PHI must stay on-prem
   - EU (GDPR): Data residency requirements
   - **Cloud solutions**: Data leaves your network (even with VPC) ❌
   - **Sentra On-Prem**: True air-gapped option ✅

---

### **C. Target Customer Segments**

**1. Hybrid Multi-Cloud Enterprises (Primary Market)**
- **Profile**: Already using AWS + Azure + GCP, 1000+ employees
- **Pain**: Managing separate security for each cloud
- **Example**: Bank with Bedrock for fraud detection, Azure OpenAI for customer support, on-prem for PII processing
- **Revenue**: $500K-2M/year

**2. Regulated Industries (High-Value)**
- **Profile**: Financial (SOX), Healthcare (HIPAA), Government
- **Pain**: Compliance audits failing due to lack of AI audit trails
- **Example**: Hospital needs HIPAA-compliant audit trail for AI diagnostic agents
- **Revenue**: $1M-5M/year (compliance premium)

**3. Cost-Conscious High-Volume (Long-Term)**
- **Profile**: Processing 500M+ tokens/month
- **Pain**: AWS bills growing 30% month-over-month
- **Example**: E-commerce platform with 1000+ customer service agents
- **Revenue**: $300K-1M/year (capex investment)

**4. Security-First Organizations (Early Adopters)**
- **Profile**: Already suffered AI security incident
- **Pain**: Lost $4.80M average per breach, need rollback + forensics
- **Example**: Fintech that had agent-based fraud attack
- **Revenue**: $200K-500K/year (security urgency)

---

### **D. Competitive Positioning Matrix**

| Capability | AWS Bedrock AgentCore | Azure OpenAI Agents | Kagent (Solo.io) | **Sentra** |
|------------|----------------------|---------------------|------------------|------------|
| **Multi-Cloud** | ❌ AWS only | ❌ Azure only | ✅ Any K8s | ✅ Any cloud + on-prem |
| **Security Focus** | ⚠️ Basic guardrails | ⚠️ Content filtering | ❌ No security | ✅ **Core focus** |
| **Runtime Validation** | ❌ Input/output only | ❌ Input/output only | ❌ N/A | ✅ Tool calls + context |
| **Rollback** | ❌ No | ❌ No | ❌ N/A | ✅ Compensating transactions |
| **Cross-Agent Security** | ❌ No | ❌ No | ❌ No | ✅ Unified security mesh |
| **Kubernetes-Native** | ❌ Managed service | ❌ Managed service | ✅ K8s operators | ✅ CRDs + operators |
| **Use Case** | AWS-native agents | Azure-native agents | DevOps automation | **Security + governance** |

**Key Differentiation**:
- **Kagent**: "Kubernetes for AI agents" BUT for DevOps use cases (kubectl operations)
- **Sentra**: "Kubernetes for AI agents" BUT for Security/Governance use cases

**No Direct Competitor**: No one else is doing "Kubernetes-style control plane for AI agent security" ✅

---

### **E. Go-To-Market Strategy**

**Phase 1 (MVP Demo - Weeks 1-4)**:
- Message: "AWS Bedrock Guardrails don't validate tool calls - we do"
- Target: Security teams at AWS Bedrock customers
- Proof: Show prompt injection bypassing Bedrock, blocked by Sentra

**Phase 2 (First 10 Customers - Months 2-6)**:
- Message: "One security layer for all your agents (AWS + Azure + GCP)"
- Target: Enterprises with multi-cloud AI deployments
- Pricing: $50K-200K/year (per-agent or per-cluster)

**Phase 3 (Product-Market Fit - Months 7-12)**:
- Message: "Kubernetes for AI agents, but for security"
- Target: Regulated industries (finance, healthcare, gov)
- Pricing: $200K-1M/year (compliance + on-prem premium)

**Phase 4 (Scale - Year 2+)**:
- Open source core components (like Kubernetes)
- Commercial enterprise features (multi-region, HA, premium support)
- Community-driven standard for AI agent security

---

### **F. Legitimate Use Cases for Migration**

**Q: Is "no vendor lock-in" a legit use case for customers to move away from AWS?**

**Answer**: ✅ **YES - Multiple Validated Reasons**:

1. **Multi-Cloud Strategy** (60% of enterprises in 2025)
   - Avoiding single cloud dependency
   - Best-of-breed: AWS Bedrock for some agents, Azure for others
   - Disaster recovery: Failover to different cloud

2. **Cost Arbitrage** (High-volume users)
   - AWS Bedrock: $0.002-0.02 per 1K tokens
   - On-prem with Sentra: 50-70% cheaper at 500M+ tokens/month
   - Example: $2M/year AWS → $600K/year on-prem

3. **Compliance Requirements** (Regulated industries)
   - SOX, HIPAA, GDPR require on-prem or specific cloud regions
   - AWS Bedrock may not be available in required regions
   - Need air-gapped deployments

4. **Negotiating Leverage**
   - Enterprise: "If AWS raises prices 30%, we can migrate to Sentra"
   - Result: Better AWS pricing (saves 10-20%)

5. **Avoiding Cloud Outages**
   - AWS Bedrock downtime: Agent fleet down
   - Sentra multi-cloud: Failover to Azure/GCP/on-prem

**Real-World Examples**:
- **Dropbox**: Migrated from AWS to on-prem (2016) → Saved $75M over 2 years
- **Apple**: Uses AWS + GCP + on-prem to avoid lock-in
- **Netflix**: Uses AWS but built Spinnaker for multi-cloud portability

---

## Summary: Your Questions Answered

| # | Question | Answer | Updated? |
|---|----------|--------|----------|
| 1 | Private endpoint only (no R53) | ✅ API Gateway private, no public internet | ✅ Lines 454-463 |
| 2 | Why CDN? | ❌ Not needed for private VPC, removed | ✅ Removed |
| 3 | Finance agent on ECS? | ✅ Yes, as separate ECS Fargate task | ✅ Lines 478-487 |
| 4 | All DDB tables on-demand? | ✅ Yes, better for MVP unpredictable load | ✅ Lines 492-496 |
| 5 | Feature 1 API accepts CEDAR? | ⚠️ MVP: YAML, Post-MVP: CEDAR support<br>✅ Validates policies + threats together | ✅ Lines 743-755 |
| 6 | USP & positioning | ✅ Multi-cloud, no lock-in, Kubernetes-native<br>✅ No direct competitor (Kagent is DevOps) | ✅ Lines 25-118 |

---

## Cost Estimate (Updated)

**AWS Monthly Cost for MVP**:
```
ECS Fargate:
- 3 tasks × 2 vCPU × 4GB RAM × 730 hours
- ~$75-100/month

DynamoDB (On-Demand):
- audit_logs: ~$5-10/month
- session_context: ~$2-5/month
- policies: ~$1-2/month
- Total: ~$8-17/month

S3: ~$1-2/month (minimal storage)
API Gateway: ~$3-5/month (low traffic)
CloudWatch: ~$5-10/month (logs + metrics)
VPC: ~$0 (included in free tier for basic setup)

Total: ~$100-140/month
```

**vs. Original Estimate**: ~$150-200/month (saved ~$50/month by removing R53/CloudFront)

---

## Next Steps

1. ✅ **Deploy Architecture Updated** - Private VPC, on-demand DDB
2. ✅ **USP Clarified** - Multi-cloud, no lock-in, Kubernetes-native
3. ✅ **Feature 1 API Clarified** - Validates policies + threats together
4. 🔄 **Pending**: Update `design.md` with detailed CDK stack designs
5. 🔄 **Pending**: Update `tasks.md` with week-by-week implementation

**Ready for**: Design phase (CDK stacks, DynamoDB schemas, API specs)
