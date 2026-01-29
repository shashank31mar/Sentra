# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Sentra** - A Kubernetes-style runtime control plane for autonomous AI agents, providing orchestration, security, and governance at scale.

### Vision
A future where enterprises can safely deploy autonomous AI agents at scale — with the same level of trust, security, and governance that containers and Kubernetes brought to cloud workloads.

### Mission
Build the industry's first runtime control plane for AI agents — providing real-time observability, policy enforcement, containment, rollback, and compliance across single- and multi-agent systems.

### Core Value Proposition
Unlike existing players (Lakera, CalypsoAI, HiddenLayer) who focus on guardrails and detection, Sentra provides:
- **Automatic enforcement** of security rules at runtime
- **Rollback capabilities** for unsafe agent actions
- **Cross-agent containment** to prevent cascade failures
- **Cryptographic SBOM** for agent provenance
- **Forensic chain-of-thought** tracing for compliance

## Repository Structure

```
/Sentra/                          # Main documentation and design
├── Kuberneters-Control-Plane-For-AI-Agents.md  # Core architecture design
├── Prototype-Plan.md                            # Implementation roadmap
├── Sentra.md                                    # Technical requirements & components
├── The-Missing-Security-Governance-Layer.md     # Market analysis & positioning
└── README.md                                    # Project overview
```

## Architecture (Kubernetes Analogy)

Sentra extends Kubernetes for AI agents using:

1. **Custom Resource Definitions (CRDs)**:
   - `Agent` - Like Pods, but for AI agents
   - `AgentPolicy` - RBAC + safety rules for agents
   - `ToolBinding` - Permissions for tools/resources
   - `AgentTopology` - Real-time agent-tool-resource graph

2. **Control Plane Layer**:
   - Agent Controller (CRD Operator)
   - Policy Engine (OPA-based)
   - Security Controller (runtime guardian)
   - Topology Manager
   - Agent Scheduler

3. **Runtime Layer (Agent Security Mesh)**:
   - Sidecar Security Proxy (per agent)
   - Cross-Agent Security Module
   - Service Mesh Integration
   - Cross-Agent Coordinator

4. **Agent Layer (Workloads)**:
   - Agents-as-Pods with security sidecars
   - External Agent Connectors (for Bedrock, Azure, etc.)

5. **Observability & Governance Layer**:
   - Audit & Logging
   - Metrics Collection
   - Forensics & Chain-of-Thought Tracing

## Core Security Features

The prototype focuses on runtime security enforcement:

1. **Prompt Injection Detection & Blocking** - Sidecar intercepts and validates all prompts
2. **Data Redaction / DLP** - Automatic PII/credential masking
3. **Tool/API Call Guardrails** - Policy-based allow/deny for agent tool usage
4. **Rollback Actions** - Undo unsafe operations (DB writes, API calls)
5. **Privilege Escalation Prevention** - Cross-agent permission enforcement
6. **Inter-Agent Message Filtering** - Validate agent-to-agent communications
7. **Agent Quarantine** - Isolate compromised agents based on trust scores

## Development Approach

### Phase 1: Prototype (2-3 months)
- Define Agent, AgentPolicy CRDs
- Implement sidecar security proxy with core features
- Basic Policy Engine and Security Controller APIs
- Minimal dashboard for observability

### Phase 2: Short Term (6-9 months)
- Expand CRDs (AgentTopology, AgentRBAC)
- Full cross-agent communication controls
- Multi-cloud connectors (AWS Bedrock, Azure OpenAI, GCP Vertex)
- Integration with OPA/Gatekeeper

### Phase 3: Medium Term (12-18 months)
- Topology Manager with live graph
- Global Security Agent coordinating mesh-wide security
- Automated rollback/containment workflows
- Observability stack (Grafana dashboards)

### Phase 4: Long Term (24+ months)
- Full Agent Security Mesh (Istio for agents)
- Compliance profiles (HIPAA, GDPR, SOC2)
- Self-optimizing scheduler
- AgentOps SaaS platform

## Key Design Principles

1. **Separation of Concerns** - Control plane separate from runtime execution
2. **Defense in Depth** - Multiple layers of security validation
3. **Zero Trust** - Every action validated, no implicit trust
4. **Fail Secure** - Deny by default, explicit allow policies
5. **Observable by Design** - All state changes logged and traceable
6. **Declarative Configuration** - Policies as code, version controlled
7. **Horizontal Scalability** - Support single agent to fleet management

## Competitive Differentiation

### vs AWS Bedrock AgentCore
- **Deeper enforcement**: Rollback, quarantine, cross-agent containment
- **Transparent policy control**: More flexible than AWS managed policies
- **Hybrid/on-prem support**: Not locked to AWS cloud
- **Forensic focus**: Chain-of-thought, immutable audit trails

### vs Security Players (Lakera, CalypsoAI, HiddenLayer)
- **Beyond guardrails**: Orchestration + security + governance
- **Multi-agent focus**: Cascade prevention, inter-agent security
- **Rollback capabilities**: Undo unsafe actions, not just detect
- **Platform play**: Category-defining like Kubernetes, not point solution

## Technology Stack (Planned)

- **Control Plane**: Go/Rust microservices (Kubernetes-native)
- **API**: gRPC + REST with OpenAPI spec
- **Policy Engine**: OPA (Rego) or custom DSL with Rego layer
- **Sidecar**: Lightweight Rust/Go service
- **Sandboxing**: Firecracker microVMs / Wasmtime (WASM)
- **Storage**: S3 for blobs + PostgreSQL/CockroachDB for metadata
- **SBOM Ledger**: Append-only DB with KMS signing
- **UI**: React + Tailwind admin console
- **AuthN/Z**: OIDC + RBAC with corporate IdP integration
- **CI/CD**: GitOps (Flux/ArgoCD)

## Key Documentation References

When working on specific features, refer to:

- **Architecture decisions**: `Sentra/Kuberneters-Control-Plane-For-AI-Agents.md`
- **Implementation details**: `Sentra/Sentra.md`
- **Prototype roadmap**: `Sentra/Prototype-Plan.md`
- **Market positioning**: `Sentra/The-Missing-Security-Governance-Layer.md`

## Critical Constraints

1. **Low Latency**: Policy checks must not significantly impact agent response times
2. **Security First**: Never compromise security for convenience
3. **Standards-Based**: Follow Kubernetes patterns (CRDs, controllers, operators)
4. **Multi-Cloud**: Must work across AWS, Azure, GCP, and on-premises
5. **Compliance Ready**: Design for SOC2, HIPAA, GDPR, EU AI Act from day one

---

## Best Practices for Low-Level Design (LLD)

### 1. Keep LLD Focused on Specific Component Context

Each LLD document should focus on **one specific component or layer**:
- ✅ Good: `01-cdk-infrastructure.md`, `02-api-gateway.md`, `03-security-controller.md`
- ❌ Bad: Single monolithic LLD file covering everything

**Rationale**:
- Easier to review and maintain
- Clear ownership and scope
- Parallel development possible

### 2. Maintain Cross-Document Consistency

**Critical**: When making changes to any LLD, update ALL related documents:

| Document | Purpose | What to Sync |
|----------|---------|--------------|
| `lld/*.md` | Component-specific design | Implementation details, APIs, schemas |
| `design-hld.md` | High-level architecture | Component interactions, data flows |
| `adr.md` | Architecture decisions | Rationale for design choices |
| `flow.md` | Operational flows | End-to-end request flows |
| `demo.md` | Demo scenarios | User-facing behaviors |

**Example**: If you add a new API endpoint to `02-api-gateway.md`:
1. Update `design-hld.md` - Add endpoint to API Gateway section
2. Update `flow.md` - Add flow diagram showing endpoint usage
3. Update `adr.md` - Document decision if it's a significant change
4. Update `demo.md` - Add demo scenario if user-facing

**Verification Checklist**:
- [ ] Are agent names consistent across all docs?
- [ ] Are API endpoints consistent (paths, methods, parameters)?
- [ ] Are rate limits documented consistently?
- [ ] Are architecture diagrams up-to-date?

### 3. Use Pseudo-Code, Not Concrete Implementation

LLD should describe **WHAT** and **HOW** at a conceptual level, not provide production code.

**✅ Good - Pseudo-code/Conceptual CDK**:
```python
# Create VPC with 2 availability zones
vpc = ec2.Vpc(
    self, "SentraVpc",
    max_azs=2,
    nat_gateways=1
)

# Create security group for agents
agent_sg = ec2.SecurityGroup(
    self, "AgentSecurityGroup",
    vpc=vpc,
    description="Security group for AI agents"
)
```

**❌ Bad - Full concrete implementation**:
```python
# Don't include complete error handling, logging, retry logic
vpc = ec2.Vpc(
    self, "SentraVpc",
    max_azs=2,
    cidr="10.0.0.0/16",
    subnet_configuration=[
        ec2.SubnetConfiguration(
            subnet_type=ec2.SubnetType.PUBLIC,
            name="Public",
            cidr_mask=24
        ),
        ec2.SubnetConfiguration(
            subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
            name="Private",
            cidr_mask=24
        )
    ],
    nat_gateways=1,
    enable_dns_hostnames=True,
    enable_dns_support=True
)
try:
    agent_sg = ec2.SecurityGroup(...)
    # 50 more lines of detailed configuration
except Exception as e:
    logger.error(f"Failed to create security group: {e}")
    raise
```

**Rationale**:
- Focus on design decisions, not implementation details
- Keep document readable and maintainable
- Actual implementation goes in `/cdk` and `/src` directories

### 4. Keep LLD Documents Concise

**Target Length**:
- **Minimum**: No hard minimum, but should be comprehensive
- **Ideal**: 500-1000 lines per LLD document
- **Maximum**: 2000 lines (hard limit)

**If an LLD exceeds 2000 lines**:
1. Split into multiple LLD documents (e.g., `02a-api-gateway-endpoints.md`, `02b-api-gateway-monitoring.md`)
2. Move detailed examples to separate appendix
3. Move concrete code to implementation files
4. Reference external documents instead of duplicating content

**Example Structure** (keeps docs < 1000 lines):
```
lld/
├── 01-cdk-infrastructure.md      (~800 lines)
├── 02-api-gateway.md             (~600 lines)
├── 03-security-controller.md     (~900 lines)
├── 04-agents.md                  (~700 lines)
├── 05-dashboard.md               (~500 lines)
```

**Rationale**:
- Easier to review (< 30 min per document)
- Faster to find information
- Better for version control diffs
- Less cognitive load

### 5. Document Structure Template

Each LLD should follow this structure:

```markdown
# LLD XX: Component Name

**Version**: 1.0
**Last Updated**: YYYY-MM-DD
**Status**: Draft | Ready for Review | Approved
**Prerequisites**: [Link to prerequisite LLDs]

## Table of Contents
1. Overview
2. Component Architecture
3. APIs / Interfaces
4. Data Models
5. Configuration
6. Error Handling
7. Monitoring & Observability
8. Cross-References

## 1. Overview
### 1.1 Purpose
### 1.2 Scope
### 1.3 Dependencies

## 2. Component Architecture
[Diagrams and high-level design]

## 3. APIs / Interfaces
[Endpoints, schemas, pseudo-code]

## 4. Data Models
[Schemas, relationships]

## 5. Configuration
[Environment variables, config files]

## 6. Error Handling
[Error scenarios, fallback strategies]

## 7. Monitoring & Observability
[Metrics, logs, alarms]

## 8. Cross-References
[Links to HLD, ADRs, other LLDs]
```

### Summary: LLD Best Practices Checklist

Before finalizing any LLD document:

- [ ] **Focused**: Single component/layer scope
- [ ] **Consistent**: All related docs updated (HLD, ADR, flow, demo)
- [ ] **Conceptual**: Pseudo-code, not production code
- [ ] **Concise**: < 2000 lines (ideally 500-1000)
- [ ] **Structured**: Follows template structure
- [ ] **Linked**: Cross-references to HLD, ADRs, other LLDs
- [ ] **Reviewable**: Can be reviewed in < 30 minutes
- [ ] **Maintainable**: Easy to update when requirements change

---

**Remember**: LLD is a **living document** that evolves with the project. Keep it up-to-date, concise, and consistent with other documentation.
