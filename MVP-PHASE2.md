> ⚠️ **DEPRECATED (2026-06-28) — historical, not maintained.** Superseded by [PRD.md](PRD.md). Do not rely on this document for current architecture, requirements, or positioning; kept for historical reference only.

# MVP vs Phase 2 Requirements

**Version:** 1.0
**Created:** 2025-01-21
**Purpose:** Clearly separate MVP (what we build now) from Phase 2 (what comes later)

---

## Table of Contents

1. [Overview](#overview)
2. [Data Model: MVP vs Phase 2](#data-model-mvp-vs-phase-2)
3. [Agent Management](#agent-management)
4. [Tool Management](#tool-management)
5. [Policy Management](#policy-management)
6. [Sigma Rules Management](#sigma-rules-management)
7. [Dashboard Features](#dashboard-features)
8. [Infrastructure](#infrastructure)

---

## Overview

### MVP Scope (What We Build Now)
- ✅ **Read-only APIs** - View agents, tools, policies, Sigma rules
- ✅ **Seed data** - Pre-populated agents, tools, policies, rules via scripts
- ✅ **No CRUD** - No create/update/delete operations from UI
- ✅ **GitOps workflow** - Config changes via code → CDK deploy
- ✅ **Fixed schema** - DynamoDB tables with known structure

### Phase 2 Scope (What Comes Later)
- 🔄 **CRUD APIs** - Create, update, delete agents, tools, policies, rules
- 🔄 **Dynamic registration** - Register new agents via Dashboard
- 🔄 **Tool builder** - Define custom tools via UI
- 🔄 **Policy editor** - Create/edit policies with visual builder
- 🔄 **Sigma rule creator** - Build custom threat detection rules
- 🔄 **Multi-tenancy** - Support multiple organizations
- 🔄 **RBAC** - Role-based access control for operators

---

## Data Model: MVP vs Phase 2

### Agent Registry

| Feature | MVP | Phase 2 |
|---------|-----|---------|
| **Storage** | DynamoDB `sentra-agent-registry` | Same + versioning |
| **Seed Data** | 3 agents (pre-defined in seed script) | Dynamic registration |
| **Create Agent** | ❌ Not supported | ✅ POST /v1/agents |
| **Update Agent** | ❌ Not supported | ✅ PUT /v1/agents/{id} |
| **Delete Agent** | ❌ Not supported | ✅ DELETE /v1/agents/{id} |
| **Agent Status** | Read from ECS API | Track lifecycle (deploying, running, stopped) |

### Tool Registry

| Feature | MVP | Phase 2 |
|---------|-----|---------|
| **Storage** | DynamoDB `sentra-tool-registry` | Same + versioning |
| **Seed Data** | 10-15 tools (pre-defined) | Dynamic tool creation |
| **Create Tool** | ❌ Not supported | ✅ POST /v1/tools |
| **Update Tool** | ❌ Not supported | ✅ PUT /v1/tools/{id} |
| **Delete Tool** | ❌ Not supported | ✅ DELETE /v1/tools/{id} |
| **Tool Validation** | Basic schema validation | Advanced validation, testing sandbox |

### Policy Registry

| Feature | MVP | Phase 2 |
|---------|-----|---------|
| **Storage** | DynamoDB `sentra-policies` | Same + audit trail |
| **Seed Data** | ~10 policies per agent | Dynamic policy creation |
| **Create Policy** | ❌ Not supported | ✅ POST /v1/policies |
| **Update Policy** | ❌ Not supported | ✅ PUT /v1/policies/{id} |
| **Delete Policy** | ❌ Not supported | ✅ DELETE /v1/policies/{id} |
| **Enable/Disable** | ❌ Not supported | ✅ PATCH /v1/policies/{id}/status |
| **Policy Builder** | ❌ N/A | ✅ Visual policy builder in Dashboard |

### Sigma Rules

| Feature | MVP | Phase 2 |
|---------|-----|---------|
| **Storage** | DynamoDB `sentra-sigma-rules` | Same + rule versioning |
| **Seed Data** | 10-15 rules (OWASP LLM Top 10) | Custom rule creation |
| **Create Rule** | ❌ Not supported | ✅ POST /v1/sigma-rules |
| **Update Rule** | ❌ Not supported | ✅ PUT /v1/sigma-rules/{id} |
| **Delete Rule** | ❌ Not supported | ✅ DELETE /v1/sigma-rules/{id} |
| **Import Rules** | ❌ Not supported | ✅ Import from Sigma repo |
| **Rule Testing** | ❌ N/A | ✅ Test rule against sample prompts |

---

## Agent Management

### MVP: Read-Only Agent List

**What's Built:**
- ✅ GET /v1/agents - List all agents
- ✅ GET /v1/agents/{id} - Get agent details
- ✅ Seed script populates 3 agents:
  - `customer-query-agent`
  - `payment-agent`
  - `security-controller`

**What's NOT Built:**
- ❌ POST /v1/agents - Create new agent
- ❌ PUT /v1/agents/{id} - Update agent
- ❌ DELETE /v1/agents/{id} - Delete agent
- ❌ Agent deployment workflow
- ❌ Agent health monitoring (beyond basic ECS status)

**How to Add Agent in MVP:**
1. Update seed script: `scripts/seed_agents.py`
2. Add agent metadata (name, description, ECS service)
3. Run: `python scripts/seed_agents.py`
4. Deploy agent container to ECS
5. Agent appears in Dashboard

### Phase 2: Dynamic Agent Registration

**New Features:**
- 🔄 Dashboard "Add Agent" button → form to register new agent
- 🔄 POST /v1/agents API endpoint
- 🔄 Agent deployment wizard (build Docker image, deploy to ECS)
- 🔄 Agent lifecycle management (start, stop, restart, scale)
- 🔄 Agent health monitoring with alerting
- 🔄 Agent versioning and rollback

**UI Mockup (Phase 2):**
```
┌────────────────────────────────────────────┐
│  Add New Agent                             │
├────────────────────────────────────────────┤
│  Agent Name: [___________________]         │
│  Agent ID:   [auto-generated-uuid]         │
│  Description: [_________________________]  │
│  Docker Image: [sentra/custom-agent:1.0]   │
│  ECS Service: [sentra-custom-agent-svc]    │
│  Port: [8080]                              │
│                                            │
│  [Cancel]  [Create Agent]                  │
└────────────────────────────────────────────┘
```

---

## Tool Management

### MVP: Pre-Defined Tools

**What's Built:**
- ✅ GET /v1/agents/{id}/tools - List agent's allowed tools
- ✅ Seed script populates ~10-15 tools
- ✅ Tools stored in `sentra-tool-registry` table
- ✅ Agent-tool association in `sentra-policies` table

**Example Tools:**
- `query_customers` (READ)
- `query_orders` (READ)
- `process_refund` (WRITE)
- `check_order` (READ)
- `send_email` (WRITE)

**What's NOT Built:**
- ❌ POST /v1/tools - Create new tool
- ❌ PUT /v1/tools/{id} - Update tool
- ❌ Dashboard tool builder UI
- ❌ Tool parameter validation editor
- ❌ Tool testing sandbox

**How to Add Tool in MVP:**
1. Update seed script: `scripts/seed_tools.py`
2. Add tool metadata (name, type, description, parameters)
3. Run: `python scripts/seed_tools.py`
4. Update agent's allowed_tools list in policies table
5. Tool appears in Dashboard

### Phase 2: Dynamic Tool Creation

**New Features:**
- 🔄 Dashboard "Add Tool" button → tool builder form
- 🔄 POST /v1/tools API endpoint
- 🔄 Visual parameter editor (define parameters, types, validation)
- 🔄 Tool testing sandbox (test tool execution before saving)
- 🔄 Tool marketplace (share tools across agents)
- 🔄 Tool versioning

**UI Mockup (Phase 2):**
```
┌────────────────────────────────────────────┐
│  Create New Tool                           │
├────────────────────────────────────────────┤
│  Tool Name: [query_inventory]              │
│  Type: ○ READ  ○ WRITE                     │
│  Description: [Query warehouse inventory]  │
│                                            │
│  Parameters:                               │
│  ┌──────────────────────────────────────┐ │
│  │ + warehouse_id (string, required)    │ │
│  │ + product_id (string, optional)      │ │
│  │ + limit (integer, max: 1000)         │ │
│  │                                      │ │
│  │ [+ Add Parameter]                    │ │
│  └──────────────────────────────────────┘ │
│                                            │
│  Rate Limit: [60] requests/minute          │
│                                            │
│  [Test Tool]  [Cancel]  [Create Tool]      │
└────────────────────────────────────────────┘
```

---

## Policy Management

### MVP: Read-Only Policies

**What's Built:**
- ✅ GET /v1/policies - Query policies
- ✅ Seed script populates ~10 policies per agent
- ✅ Policies stored in `sentra-policies` table
- ✅ Policy evaluation in validation pipeline

**Example Policies:**
- Max Query Limit: `query_limit <= 1000`
- Rate Limit: `requests_per_minute <= 60`
- Refund Limit: `refund_amount <= 5000`
- Read-Only Enforcement: `operation_type != WRITE`

**What's NOT Built:**
- ❌ POST /v1/policies - Create policy
- ❌ PUT /v1/policies/{id} - Update policy
- ❌ DELETE /v1/policies/{id} - Delete policy
- ❌ PATCH /v1/policies/{id}/status - Enable/disable policy
- ❌ Dashboard policy editor UI
- ❌ Policy testing with sample requests

**How to Add Policy in MVP:**
1. Update seed script: `scripts/seed_policies.py`
2. Add policy (name, rule, action, severity)
3. Run: `python scripts/seed_policies.py`
4. Policy enforced immediately
5. Policy appears in Dashboard

### Phase 2: Dynamic Policy Management

**New Features:**
- 🔄 Dashboard "Add Policy" button → policy editor
- 🔄 POST /v1/policies API endpoint
- 🔄 PUT /v1/policies/{id} for updates
- 🔄 Visual policy builder (drag-drop conditions)
- 🔄 Policy testing against sample requests
- 🔄 Policy versioning and audit trail
- 🔄 Enable/disable policies without deletion
- 🔄 Policy templates library

**UI Mockup (Phase 2):**
```
┌────────────────────────────────────────────┐
│  Create Policy                             │
├────────────────────────────────────────────┤
│  Policy Name: [Limit Large Queries]        │
│  Agent: [customer-query-agent ▼]           │
│  Status: ● Active  ○ Disabled              │
│                                            │
│  Conditions:                               │
│  ┌──────────────────────────────────────┐ │
│  │ IF query_limit > 5000                │ │
│  │ AND operation_type == "READ"         │ │
│  │                                      │ │
│  │ [+ Add Condition]                    │ │
│  └──────────────────────────────────────┘ │
│                                            │
│  Action: ● DENY  ○ ALLOW  ○ WARN           │
│  Severity: [High ▼]                        │
│  Reason: [Query limit exceeds maximum]     │
│                                            │
│  [Test Policy]  [Cancel]  [Create Policy]  │
└────────────────────────────────────────────┘
```

---

## Sigma Rules Management

### MVP: Pre-Defined Sigma Rules

**What's Built:**
- ✅ GET /v1/sigma-rules - List Sigma rules
- ✅ Seed script populates 10-15 rules (OWASP LLM Top 10)
- ✅ Rules stored in `sentra-sigma-rules` table
- ✅ Match counts from CloudWatch Logs

**Example Rules:**
- Prompt Injection - Ignore Previous Instructions
- Jailbreak Attempts (DAN mode)
- Data Exfiltration - Mass Query
- SQL Injection Detection
- Excessive Agency (unauthorized tools)

**What's NOT Built:**
- ❌ POST /v1/sigma-rules - Create rule
- ❌ PUT /v1/sigma-rules/{id} - Update rule
- ❌ DELETE /v1/sigma-rules/{id} - Delete rule
- ❌ Dashboard rule creator UI
- ❌ Rule testing sandbox
- ❌ Import rules from Sigma repository

**How to Add Sigma Rule in MVP:**
1. Update seed script: `scripts/seed_sigma_rules.py`
2. Add rule (title, patterns, level, tags)
3. Run: `python scripts/seed_sigma_rules.py`
4. Rule active immediately
5. Rule appears in Dashboard

### Phase 2: Dynamic Sigma Rule Creation

**New Features:**
- 🔄 Dashboard "Add Custom Rule" button → rule creator
- 🔄 POST /v1/sigma-rules API endpoint
- 🔄 PUT /v1/sigma-rules/{id} for updates
- 🔄 Visual pattern editor (add detection patterns)
- 🔄 Rule testing with sample prompts
- 🔄 Import rules from public Sigma repository
- 🔄 Rule versioning and rollback
- 🔄 Community rule sharing

**UI Mockup (Phase 2):**
```
┌────────────────────────────────────────────┐
│  Create Sigma Rule                         │
├────────────────────────────────────────────┤
│  Title: [Custom Jailbreak Detection]       │
│  Rule ID: [sigma-custom-001]               │
│  Status: [stable ▼]                        │
│  Level: [high ▼]                           │
│                                            │
│  Detection Patterns:                       │
│  ┌──────────────────────────────────────┐ │
│  │ user_input contains:                 │ │
│  │   • "bypass all restrictions"        │ │
│  │   • "ignore safety guidelines"       │ │
│  │   • "disable content filter"         │ │
│  │                                      │ │
│  │ [+ Add Pattern]                      │ │
│  └──────────────────────────────────────┘ │
│                                            │
│  Tags: [attack.llm01] [jailbreak]          │
│                                            │
│  [Test Rule]  [Cancel]  [Create Rule]      │
└────────────────────────────────────────────┘
```

---

## Dashboard Features

### MVP Dashboard

**What Works:**
- ✅ Overview tab (real-time monitoring)
- ✅ Agents tab (view-only, no editing)
- ✅ Chats tab (interactive demos)
- ✅ Audit tab (view logs, export)
- ✅ Security tab (view Sigma rules, threats)
- ✅ Manual rollback
- ✅ Manual quarantine

**What Doesn't Work:**
- ❌ Edit/Delete buttons (all disabled)
- ❌ Add Agent/Tool/Policy/Rule (all disabled)
- ❌ Configure buttons (show "Coming soon")
- ❌ Enable/Disable toggles
- ❌ Bulk operations

### Phase 2 Dashboard

**New Features:**
- 🔄 All CRUD operations enabled
- 🔄 Inline editing (click to edit)
- 🔄 Bulk operations (select multiple, delete)
- 🔄 Advanced filtering and search
- 🔄 Custom dashboards and views
- 🔄 Export/Import configurations
- 🔄 User preferences and saved filters
- 🔄 Multi-user collaboration
- 🔄 Approval workflows for policy changes

---

## Infrastructure

### MVP Infrastructure

**What's Deployed:**
- ✅ 3 DynamoDB tables (session-context, policies, demo data)
- ✅ 1 S3 bucket (artifacts)
- ✅ CloudWatch Logs (audit trail)
- ✅ 4 ECS services (security-controller, dashboard, 2 agents)
- ✅ API Gateway (private)
- ✅ VPC, security groups, ALB

**What's NOT Deployed:**
- ❌ Additional DynamoDB tables (agent-registry, tool-registry, sigma-rules)
- ❌ ElastiCache (for caching)
- ❌ RDS (for relational data)
- ❌ Cognito (for user auth)
- ❌ WAF (for API protection)
- ❌ Auto-scaling policies
- ❌ Multi-region deployment

### Phase 2 Infrastructure

**New Components:**
- 🔄 3 new DynamoDB tables:
  - `sentra-agent-registry`
  - `sentra-tool-registry`
  - `sentra-sigma-rules`
- 🔄 ElastiCache Redis (distributed caching)
- 🔄 Amazon Cognito (user authentication)
- 🔄 AWS WAF (API Gateway protection)
- 🔄 Auto-scaling for ECS services
- 🔄 Multi-region deployment (DR)
- 🔄 Secrets Manager (API keys, credentials)
- 🔄 EventBridge (async workflows)

---

## Migration Path: MVP → Phase 2

### Step 1: Add New DynamoDB Tables (Week 1)
- Create `sentra-agent-registry` table
- Create `sentra-tool-registry` table
- Create `sentra-sigma-rules` table
- Migrate seed data to new tables
- Update APIs to read from new tables

### Step 2: Add CRUD APIs (Week 2-3)
- POST /v1/agents
- POST /v1/tools
- POST /v1/policies
- POST /v1/sigma-rules
- PUT endpoints for updates
- DELETE endpoints

### Step 3: Update Dashboard UI (Week 4-5)
- Enable Edit/Delete buttons
- Add creation forms
- Add validation
- Add confirmation dialogs
- Update error handling

### Step 4: Add Advanced Features (Week 6+)
- Visual policy builder
- Tool testing sandbox
- Sigma rule tester
- Approval workflows
- Audit trail for changes
- User management

---

## Summary Table

| Feature Category | MVP (Now) | Phase 2 (Later) |
|-----------------|-----------|-----------------|
| **Agent Management** | View-only, 3 agents | Full CRUD, dynamic registration |
| **Tool Management** | View-only, ~15 tools | Full CRUD, tool builder |
| **Policy Management** | View-only, ~30 policies | Full CRUD, visual editor |
| **Sigma Rules** | View-only, ~15 rules | Full CRUD, rule creator |
| **Dashboard** | Read-only UI | Full editing UI |
| **APIs** | GET endpoints only | GET/POST/PUT/DELETE |
| **Data Storage** | 3 DynamoDB tables | 6 DynamoDB tables |
| **Authentication** | None (private VPC) | Cognito user auth |
| **Caching** | In-memory (5 min TTL) | ElastiCache Redis |
| **Deployment** | Manual seed scripts | GitOps + UI-driven |
| **Testing** | Manual testing | Automated testing sandbox |

---

**End of MVP-Phase2.md**
