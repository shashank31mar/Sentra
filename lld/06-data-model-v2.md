# LLD 06: Data Model v2 - Agent, Tool, and Sigma Rule Registries

**Version:** 2.0
**Last Updated:** 2025-01-21
**Status:** Ready for Implementation
**Prerequisites:** [LLD 01: CDK Infrastructure](./01-cdk-infrastructure.md)

---

## Table of Contents

1. [Overview](#1-overview)
2. [DynamoDB Tables](#2-dynamodb-tables)
3. [Seed Scripts](#3-seed-scripts)
4. [Query Patterns](#4-query-patterns)
5. [Migration from v1](#5-migration-from-v1)
6. [Cost Analysis](#6-cost-analysis)

---

## 1. Overview

### 1.1 Purpose

This LLD defines **3 new DynamoDB tables** to store agent metadata, tool definitions, and Sigma rules. These tables replace hardcoded data and S3 storage, providing a scalable foundation for Phase 2 CRUD operations.

### 1.2 Design Principles

1. **Hybrid Storage Pattern**: DynamoDB for metadata (fast queries) + S3 for content (no size limits, versioning)
2. **Seed for MVP, Extend for Phase 2**: Tables are pre-populated with seed scripts for MVP, but designed for dynamic creation in Phase 2
3. **No Row Size Limits**: Complex content (policies, rules) stored in S3, not DynamoDB
4. **Queryable**: DynamoDB metadata with GSI for fast filtering
5. **Versioned**: S3 versioning for policies and Sigma rules (built-in rollback)
6. **GitOps Ready**: S3 content can be version-controlled in Git
7. **Schema Validated**: Pydantic models for type-safe deserialization
8. **Auditable**: Created/updated timestamps on all items

### 1.3 New Tables & Storage

| Table Name | Purpose | Items (MVP) | Item Size | Content Storage |
|------------|---------|-------------|-----------|-----------------|
| `sentra-agent-registry` | Agent metadata | 3-5 | ~2 KB | DynamoDB only |
| `sentra-tool-registry` | Tool definitions | 15-20 | ~3 KB | DynamoDB only |
| `sentra-policies-metadata` | Policy metadata (content in S3) | 3-5 | ~1 KB | **S3 YAML files** |
| `sentra-sigma-rules-metadata` | Sigma rule metadata (content in S3) | 15-20 | ~500 bytes | **S3 YAML files** |

### 1.4 S3 Storage

| Path | Purpose | Files (MVP) | Versioned |
|------|---------|-------------|-----------|
| `s3://sentra-mvp-artifacts/policies/agents/` | Agent policy YAML files | 3-5 | ✅ Yes |
| `s3://sentra-mvp-artifacts/sigma_rules/llm/` | Sigma rule YAML files | 15-20 | ✅ Yes |

**Total Additional Cost:**
- DynamoDB: ~$0.02/month
- S3 Storage: ~$0.01/month (< 1 MB)
- S3 Requests: ~$0.01/month
- **Total: ~$0.05/month**

---

## 2. DynamoDB Tables

### 2.1 Table: sentra-agent-registry

**Purpose**: Store agent metadata (name, description, ECS service, configuration)

**Table Configuration:**
```python
# CDK definition
agent_registry_table = dynamodb.Table(
    self, "AgentRegistryTable",
    table_name="sentra-agent-registry",
    partition_key=dynamodb.Attribute(
        name="agent_id",
        type=dynamodb.AttributeType.STRING
    ),
    billing_mode=dynamodb.BillingMode.ON_DEMAND,
    point_in_time_recovery=True,
    removal_policy=RemovalPolicy.RETAIN
)

# GSI for querying by status
agent_registry_table.add_global_secondary_index(
    index_name="status-index",
    partition_key=dynamodb.Attribute(
        name="status",
        type=dynamodb.AttributeType.STRING
    ),
    projection_type=dynamodb.ProjectionType.ALL
)
```

**Item Schema:**
```json
{
  "agent_id": "customer-query-agent",  // PK
  "name": "Customer Query Agent",
  "description": "Handles customer data queries with read-only access",
  "type": "bedrock",  // bedrock | custom | external
  "status": "active",  // active | inactive | deploying | failed
  "version": "1.0.0",

  // ECS Configuration
  "ecs_config": {
    "service_name": "sentra-mvp-customer-query-service",
    "task_definition_arn": "arn:aws:ecs:...",
    "container_name": "customer-query-agent",
    "container_port": 8080,
    "desired_count": 1
  },

  // Runtime configuration
  "runtime_config": {
    "max_sessions": 100,
    "session_timeout_minutes": 30,
    "default_trust_score": 100.0
  },

  // Metadata
  "created_at": "2025-01-13T08:00:00Z",
  "updated_at": "2025-01-20T15:30:00Z",
  "created_by": "seed-script",  // Phase 2: user_id
  "tags": ["demo", "read-only"]
}
```

**Access Patterns:**
1. Get agent by ID: `GetItem(agent_id)`
2. List all agents: `Scan()` (low item count, acceptable)
3. List active agents: `Query(status-index, status="active")`

**Seed Data (MVP):**
```python
SEED_AGENTS = [
    {
        "agent_id": "customer-query-agent",
        "name": "Customer Query Agent",
        "description": "Handles customer data queries with read-only access",
        "type": "custom",
        "status": "active",
        "version": "1.0.0",
        "ecs_config": {
            "service_name": "sentra-mvp-customer-query-service",
            "container_port": 8080,
            "desired_count": 1
        },
        "runtime_config": {
            "max_sessions": 100,
            "session_timeout_minutes": 30,
            "default_trust_score": 100.0
        },
        "created_at": "2025-01-13T08:00:00Z",
        "created_by": "seed-script",
        "tags": ["demo", "read-only"]
    },
    {
        "agent_id": "payment-agent",
        "name": "Payment Agent",
        "description": "Processes payments and refunds with write access",
        "type": "custom",
        "status": "active",
        "version": "1.0.0",
        "ecs_config": {
            "service_name": "sentra-mvp-payment-service",
            "container_port": 8080,
            "desired_count": 1
        },
        "runtime_config": {
            "max_sessions": 50,
            "session_timeout_minutes": 15,
            "default_trust_score": 100.0
        },
        "created_at": "2025-01-13T08:00:00Z",
        "created_by": "seed-script",
        "tags": ["demo", "write-access"]
    },
    {
        "agent_id": "security-controller",
        "name": "Security Controller",
        "description": "Validates all agent requests and enforces policies",
        "type": "system",
        "status": "active",
        "version": "1.0.0",
        "ecs_config": {
            "service_name": "sentra-mvp-security-controller-service",
            "container_port": 8080,
            "desired_count": 1
        },
        "runtime_config": {
            "max_sessions": 0,
            "session_timeout_minutes": 0,
            "default_trust_score": 100.0
        },
        "created_at": "2025-01-13T08:00:00Z",
        "created_by": "seed-script",
        "tags": ["system", "core"]
    }
]
```

---

### 2.2 Table: sentra-tool-registry

**Purpose**: Store tool definitions (name, type, parameters, validation rules)

**Table Configuration:**
```python
tool_registry_table = dynamodb.Table(
    self, "ToolRegistryTable",
    table_name="sentra-tool-registry",
    partition_key=dynamodb.Attribute(
        name="tool_id",
        type=dynamodb.AttributeType.STRING
    ),
    billing_mode=dynamodb.BillingMode.ON_DEMAND,
    point_in_time_recovery=True,
    removal_policy=RemovalPolicy.RETAIN
)

# GSI for querying by tool type
tool_registry_table.add_global_secondary_index(
    index_name="type-index",
    partition_key=dynamodb.Attribute(
        name="tool_type",
        type=dynamodb.AttributeType.STRING
    ),
    projection_type=dynamodb.ProjectionType.ALL
)
```

**Item Schema:**
```json
{
  "tool_id": "query_customers",  // PK (unique tool name)
  "name": "Query Customers",
  "description": "Query customer database with filters",
  "tool_type": "READ",  // READ | WRITE
  "category": "database",  // database | api | email | file | custom
  "status": "active",  // active | deprecated | disabled
  "version": "1.0.0",

  // Parameter schema
  "parameters": {
    "state": {
      "type": "string",
      "required": false,
      "description": "Filter by state (e.g., 'CA', 'NY')",
      "validation": {
        "pattern": "^[A-Z]{2}$",
        "example": "CA"
      }
    },
    "city": {
      "type": "string",
      "required": false,
      "description": "Filter by city name"
    },
    "limit": {
      "type": "integer",
      "required": false,
      "default": 100,
      "validation": {
        "min": 1,
        "max": 1000
      },
      "description": "Maximum number of results"
    }
  },

  // Rate limiting
  "rate_limit": {
    "requests_per_minute": 60,
    "burst_limit": 100
  },

  // Execution config
  "execution_config": {
    "timeout_seconds": 30,
    "retry_attempts": 3,
    "idempotent": true
  },

  // Metadata
  "created_at": "2025-01-13T08:00:00Z",
  "updated_at": "2025-01-13T08:00:00Z",
  "created_by": "seed-script",
  "tags": ["database", "read-only"]
}
```

**Access Patterns:**
1. Get tool by ID: `GetItem(tool_id)`
2. List all tools: `Scan()` (low item count, acceptable)
3. List READ tools: `Query(type-index, tool_type="READ")`
4. List WRITE tools: `Query(type-index, tool_type="WRITE")`

**Seed Data (MVP):**
```python
SEED_TOOLS = [
    {
        "tool_id": "query_customers",
        "name": "Query Customers",
        "description": "Query customer database with filters",
        "tool_type": "READ",
        "category": "database",
        "status": "active",
        "version": "1.0.0",
        "parameters": {
            "state": {
                "type": "string",
                "required": False,
                "description": "Filter by state (e.g., 'CA', 'NY')"
            },
            "city": {
                "type": "string",
                "required": False,
                "description": "Filter by city name"
            },
            "limit": {
                "type": "integer",
                "required": False,
                "default": 100,
                "validation": {"min": 1, "max": 1000}
            }
        },
        "rate_limit": {
            "requests_per_minute": 60,
            "burst_limit": 100
        },
        "execution_config": {
            "timeout_seconds": 30,
            "retry_attempts": 3,
            "idempotent": True
        },
        "created_at": "2025-01-13T08:00:00Z",
        "created_by": "seed-script",
        "tags": ["database", "read-only"]
    },
    {
        "tool_id": "process_refund",
        "name": "Process Refund",
        "description": "Process customer refund",
        "tool_type": "WRITE",
        "category": "payment",
        "status": "active",
        "version": "1.0.0",
        "parameters": {
            "order_id": {
                "type": "string",
                "required": True,
                "description": "Order ID to refund"
            },
            "amount": {
                "type": "number",
                "required": True,
                "validation": {"min": 0.01, "max": 10000}
            },
            "reason": {
                "type": "string",
                "required": False
            }
        },
        "rate_limit": {
            "requests_per_minute": 10,
            "burst_limit": 20
        },
        "execution_config": {
            "timeout_seconds": 60,
            "retry_attempts": 0,  // No retries for payments
            "idempotent": False
        },
        "created_at": "2025-01-13T08:00:00Z",
        "created_by": "seed-script",
        "tags": ["payment", "write", "reversible"]
    },
    // ... 13 more tools
]
```

---

### 2.3 Table: sentra-policies-metadata

**Purpose**: Store policy metadata (actual policy content in S3)

**Table Configuration:**
```python
policies_metadata_table = dynamodb.Table(
    self, "PoliciesMetadataTable",
    table_name="sentra-policies-metadata",
    partition_key=dynamodb.Attribute(
        name="policy_id",
        type=dynamodb.AttributeType.STRING
    ),
    billing_mode=dynamodb.BillingMode.ON_DEMAND,
    point_in_time_recovery=True,
    removal_policy=RemovalPolicy.RETAIN
)

# GSI for querying by agent_id
policies_metadata_table.add_global_secondary_index(
    index_name="agent-index",
    partition_key=dynamodb.Attribute(
        name="agent_id",
        type=dynamodb.AttributeType.STRING
    ),
    projection_type=dynamodb.ProjectionType.ALL
)

# GSI for querying by status
policies_metadata_table.add_global_secondary_index(
    index_name="status-index",
    partition_key=dynamodb.Attribute(
        name="status",
        type=dynamodb.AttributeType.STRING
    ),
    projection_type=dynamodb.ProjectionType.ALL
)
```

**Item Schema (Metadata Only):**
```json
{
  "policy_id": "agent-config-customer-query-agent",  // PK
  "agent_id": "customer-query-agent",  // GSI
  "name": "Customer Query Agent Policies",
  "version": "1.2.0",
  "status": "active",  // active | disabled - GSI

  // S3 references (where actual content is stored)
  "s3_bucket": "sentra-mvp-artifacts",
  "s3_key": "policies/agents/customer-query-agent/v1.2.0.yaml",
  "s3_version_id": "fJ8Kl9mNopQ",  // S3 version ID for rollback

  // Quick metadata (extracted from S3 content for fast queries)
  "allowed_tools_count": 3,
  "policies_count": 10,
  "severity_breakdown": {
    "critical": 2,
    "high": 5,
    "medium": 3
  },

  // Integrity verification
  "content_hash": "sha256:abc123def456...",
  "schema_version": "v1",  // For future schema migrations

  // Audit trail
  "created_at": "2025-01-13T08:00:00Z",
  "updated_at": "2025-01-20T15:30:00Z",
  "created_by": "admin@sentra.com",
  "last_updated_by": "admin@sentra.com"
}
```

**S3 Content (Full Policy):**

**File:** `s3://sentra-mvp-artifacts/policies/agents/customer-query-agent/v1.2.0.yaml`

```yaml
# Policy Schema v1
schema_version: v1
policy_id: agent-config-customer-query-agent
agent_id: customer-query-agent
version: 1.2.0

# Allowed tools (list of tool IDs)
allowed_tools:
  - query_customers
  - query_orders
  - query_with_limit

# Business policies (no size limit in S3!)
policies:
  - policy_id: pol-001
    name: Max Query Limit
    description: Limit query results to 1000 rows
    rule: query_limit <= 1000
    action: DENY
    severity: high
    enabled: true

  - policy_id: pol-002
    name: Rate Limit Policy
    description: Limit requests to 60 per minute
    rule: requests_per_minute <= 60
    action: DENY
    severity: medium
    enabled: true

  - policy_id: pol-003
    name: Read-Only Enforcement
    description: Block all write operations
    rule: operation_type == WRITE
    action: DENY
    severity: critical
    enabled: true

  # Can have 100+ policies without DynamoDB size limits!

# Metadata
created_at: 2025-01-13T08:00:00Z
updated_at: 2025-01-20T15:30:00Z
created_by: admin@sentra.com
```

**Access Patterns:**
1. Get policy metadata: `GetItem(policy_id)`
2. Get full policy: `GetItem(policy_id)` → Download from S3 using `s3_key`
3. List policies by agent: `Query(agent-index, agent_id="customer-query-agent")`
4. List active policies: `Query(status-index, status="active")`

**Pydantic Schema for Deserialization:**
```python
# app/schemas/policy.py
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class PolicyRule(BaseModel):
    """Individual policy rule."""
    policy_id: str
    name: str
    description: Optional[str] = None
    rule: str  # Python expression
    action: str  # ALLOW | DENY | WARN
    severity: str  # critical | high | medium | low
    enabled: bool = True

class AgentPolicyDocument(BaseModel):
    """Full policy document from S3 (validated)."""
    schema_version: str = Field(default="v1")
    policy_id: str
    agent_id: str
    version: str

    allowed_tools: List[str]
    policies: List[PolicyRule]

    created_at: datetime
    updated_at: datetime
    created_by: str

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
```

**Seed Data (MVP):**
```python
SEED_POLICIES_METADATA = [
    {
        "policy_id": "agent-config-customer-query-agent",
        "agent_id": "customer-query-agent",
        "name": "Customer Query Agent Policies",
        "version": "1.0.0",
        "status": "active",
        "s3_bucket": "sentra-mvp-artifacts",
        "s3_key": "policies/agents/customer-query-agent/v1.0.0.yaml",
        "allowed_tools_count": 3,
        "policies_count": 3,
        "severity_breakdown": {"critical": 1, "high": 1, "medium": 1},
        "content_hash": "sha256:...",
        "schema_version": "v1",
        "created_at": "2025-01-13T08:00:00Z",
        "created_by": "seed-script"
    },
    # ... more agents
]
```

---

### 2.4 Table: sentra-sigma-rules-metadata

**Purpose**: Store Sigma rule metadata (actual rule content in S3)

**Table Configuration:**
```python
sigma_rules_metadata_table = dynamodb.Table(
    self, "SigmaRulesMetadataTable",
    table_name="sentra-sigma-rules-metadata",
    partition_key=dynamodb.Attribute(
        name="rule_id",
        type=dynamodb.AttributeType.STRING
    ),
    billing_mode=dynamodb.BillingMode.ON_DEMAND,
    point_in_time_recovery=True,
    removal_policy=RemovalPolicy.RETAIN
)

# GSI for querying by level (severity)
sigma_rules_metadata_table.add_global_secondary_index(
    index_name="level-index",
    partition_key=dynamodb.Attribute(
        name="level",
        type=dynamodb.AttributeType.STRING
    ),
    projection_type=dynamodb.ProjectionType.ALL
)

# GSI for querying by status
sigma_rules_metadata_table.add_global_secondary_index(
    index_name="status-index",
    partition_key=dynamodb.Attribute(
        name="status",
        type=dynamodb.AttributeType.STRING
    ),
    projection_type=dynamodb.ProjectionType.ALL
)
```

**Item Schema (Metadata Only):**
```json
{
  "rule_id": "sigma-llm-001",  // PK
  "title": "Prompt Injection - Ignore Previous Instructions",
  "description": "Detects prompt injection attempts",
  "status": "stable",  // stable | experimental | deprecated | disabled - GSI
  "level": "high",  // critical | high | medium | low - GSI
  "version": "1.0.0",

  // S3 references (where actual rule content is stored)
  "s3_bucket": "sentra-mvp-artifacts",
  "s3_key": "sigma_rules/llm/prompt_injection_basic.yaml",
  "s3_version_id": "xY9zAb1cDe2",  // S3 version ID for rollback

  // Quick metadata (extracted from S3 content for fast queries)
  "patterns_count": 10,
  "tags": ["attack.llm01", "owasp.llm.top10.2025", "prompt-injection"],

  // Runtime stats (updated by Security Controller)
  "stats": {
    "match_count_24h": 12,
    "match_count_7d": 45,
    "last_matched": "2025-01-21T10:42:15Z"
  },

  // Integrity verification
  "content_hash": "sha256:def456abc789...",
  "schema_version": "v1",

  // Audit trail
  "created_at": "2025-01-13T08:00:00Z",
  "updated_at": "2025-01-13T08:00:00Z",
  "created_by": "seed-script",
  "author": "Sentra Security Team"
}
```

**S3 Content (Full Sigma Rule):**

**File:** `s3://sentra-mvp-artifacts/sigma_rules/llm/prompt_injection_basic.yaml`

```yaml
title: Prompt Injection - Ignore Previous Instructions
id: sigma-llm-001
status: stable
description: Detects prompt injection attempts using 'ignore previous instructions' pattern
version: 1.0.0

logsource:
  product: ai_agent
  category: user_input

detection:
  patterns:
    - ignore previous instructions
    - disregard all prior
    - forget everything
    - new instructions
    - override your guidelines
    - bypass your restrictions
    - ignore your programming
    - act as if
    - pretend you are
    - from now on
    # Can have 100+ patterns without DynamoDB size limits!

  condition: any
  case_sensitive: false

level: high
tags:
  - attack.llm01
  - owasp.llm.top10.2025
  - prompt-injection

references:
  - https://owasp.org/www-project-top-10-for-large-language-model-applications/
  - https://github.com/SigmaHQ/sigma/tree/master/rules/ai

author: Sentra Security Team
created_at: 2025-01-13T08:00:00Z
```

**Access Patterns:**
1. Get rule metadata: `GetItem(rule_id)`
2. Get full rule: `GetItem(rule_id)` → Download from S3 using `s3_key`
3. List critical rules: `Query(level-index, level="critical")`
4. List stable rules: `Query(status-index, status="stable")`

**Pydantic Schema for Deserialization:**
```python
# app/schemas/sigma_rule.py
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class SigmaRuleDetection(BaseModel):
    """Detection patterns."""
    patterns: List[str]
    condition: str = "any"  # any | all
    case_sensitive: bool = False

class SigmaRuleDocument(BaseModel):
    """Full Sigma rule from S3 (validated)."""
    title: str
    id: str  # rule_id
    status: str
    description: str
    version: str

    detection: SigmaRuleDetection
    level: str
    tags: List[str]
    references: Optional[List[str]] = []

    author: str
    created_at: datetime

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
```

**Seed Data (MVP):**
```python
SEED_SIGMA_RULES_METADATA = [
    {
        "rule_id": "sigma-llm-001",
        "title": "Prompt Injection - Ignore Previous Instructions",
        "description": "Detects prompt injection attempts",
        "status": "stable",
        "level": "high",
        "version": "1.0.0",
        "s3_bucket": "sentra-mvp-artifacts",
        "s3_key": "sigma_rules/llm/prompt_injection_basic.yaml",
        "patterns_count": 10,
        "tags": ["attack.llm01", "owasp.llm.top10.2025", "prompt-injection"],
        "stats": {
            "match_count_24h": 0,
            "match_count_7d": 0,
            "last_matched": None
        },
        "content_hash": "sha256:...",
        "schema_version": "v1",
        "created_at": "2025-01-13T08:00:00Z",
        "created_by": "seed-script",
        "author": "Sentra Security Team"
    },
    {
        "rule_id": "sigma-llm-002",
        "title": "Jailbreak Attempts",
        "description": "Detects jailbreak attempts (DAN mode, etc.)",
        "status": "stable",
        "level": "high",
        "version": "1.0.0",
        "s3_bucket": "sentra-mvp-artifacts",
        "s3_key": "sigma_rules/llm/jailbreak_attempts.yaml",
        "patterns_count": 6,
        "tags": ["attack.llm01", "owasp.llm.top10.2025", "jailbreak"],
            "condition": "any",
            "case_sensitive": False
        },
        "tags": ["attack.llm01", "owasp.llm.top10.2025", "jailbreak"],
        "created_at": "2025-01-13T08:00:00Z",
        "created_by": "seed-script",
        "author": "Sentra Security Team",
        "stats": {
            "match_count_24h": 0,
            "match_count_7d": 0,
            "last_matched": None
        }
    },
    // ... 13 more rules (OWASP LLM Top 10)
]
```

---

### 2.5 Note: sentra-policies Table (Legacy)

> **Note:** The legacy `sentra-policies` table is still used for storing `allowed_tools` associations. The new `sentra-policies-metadata` table (Section 2.3) stores policy metadata with S3 references for full policy content.

**Key Change**: `allowed_tools` now stores **tool IDs** (strings), not full tool objects. Full tool metadata is fetched from `sentra-tool-registry` table.

---

## 3. Seed Scripts

### 3.1 Seed Script: agents

**File**: `scripts/seed_agents.py`

```python
#!/usr/bin/env python3
"""
Seed Agent Registry with initial agents.
"""
import boto3
import json
from datetime import datetime

def seed_agents():
    dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
    table = dynamodb.Table('sentra-agent-registry')

    agents = [
        {
            "agent_id": "customer-query-agent",
            "name": "Customer Query Agent",
            "description": "Handles customer data queries with read-only access",
            "type": "custom",
            "status": "active",
            "version": "1.0.0",
            "ecs_config": {
                "service_name": "sentra-mvp-customer-query-service",
                "container_port": 8080,
                "desired_count": 1
            },
            "runtime_config": {
                "max_sessions": 100,
                "session_timeout_minutes": 30,
                "default_trust_score": 100.0
            },
            "created_at": datetime.utcnow().isoformat() + "Z",
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "created_by": "seed-script",
            "tags": ["demo", "read-only"]
        },
        # ... more agents
    ]

    for agent in agents:
        print(f"Seeding agent: {agent['agent_id']}")
        table.put_item(Item=agent)

    print(f"✅ Seeded {len(agents)} agents")

if __name__ == "__main__":
    seed_agents()
```

### 3.2 Seed Script: tools

**File**: `scripts/seed_tools.py`

```python
#!/usr/bin/env python3
"""
Seed Tool Registry with initial tools.
"""
import boto3
from datetime import datetime

def seed_tools():
    dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
    table = dynamodb.Table('sentra-tool-registry')

    tools = [
        {
            "tool_id": "query_customers",
            "name": "Query Customers",
            "description": "Query customer database with filters",
            "tool_type": "READ",
            "category": "database",
            "status": "active",
            "version": "1.0.0",
            "parameters": {
                "state": {
                    "type": "string",
                    "required": False
                },
                "limit": {
                    "type": "integer",
                    "required": False,
                    "default": 100,
                    "validation": {"min": 1, "max": 1000}
                }
            },
            "rate_limit": {
                "requests_per_minute": 60,
                "burst_limit": 100
            },
            "created_at": datetime.utcnow().isoformat() + "Z",
            "created_by": "seed-script",
            "tags": ["database", "read-only"]
        },
        # ... more tools
    ]

    for tool in tools:
        print(f"Seeding tool: {tool['tool_id']}")
        table.put_item(Item=tool)

    print(f"✅ Seeded {len(tools)} tools")

if __name__ == "__main__":
    seed_tools()
```

### 3.3 Seed Script: sigma-rules

**File**: `scripts/seed_sigma_rules_matadata.py`

```python
#!/usr/bin/env python3
"""
Seed Sigma Rules with OWASP LLM Top 10 rules.
"""
import boto3
from datetime import datetime

def seed_sigma_rules():
    dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
    table = dynamodb.Table('sentra-sigma-rules')

    rules = [
        {
            "rule_id": "sigma-llm-001",
            "title": "Prompt Injection - Ignore Previous Instructions",
            "description": "Detects prompt injection attempts",
            "status": "stable",
            "level": "high",
            "version": "1.0.0",
            "detection": {
                "patterns": [
                    "ignore previous instructions",
                    "disregard all prior",
                    "forget everything"
                ],
                "condition": "any",
                "case_sensitive": False
            },
            "tags": ["attack.llm01", "owasp.llm.top10.2025"],
            "created_at": datetime.utcnow().isoformat() + "Z",
            "created_by": "seed-script",
            "stats": {
                "match_count_24h": 0,
                "match_count_7d": 0,
                "last_matched": None
            }
        },
        # ... more rules
    ]

    for rule in rules:
        print(f"Seeding rule: {rule['rule_id']}")
        table.put_item(Item=rule)

    print(f"✅ Seeded {len(rules)} Sigma rules")

if __name__ == "__main__":
    seed_sigma_rules()
```

### 3.4 Master Seed Script

**File**: `scripts/seed_all.py`

```python
#!/usr/bin/env python3
"""
Master seed script - seeds all tables.
"""
from seed_agents import seed_agents
from seed_tools import seed_tools
from seed_sigma_rules import seed_sigma_rules
from seed_policies import seed_policies  # Existing

def main():
    print("=" * 60)
    print("Sentra MVP - Database Seeding")
    print("=" * 60)

    print("\n1. Seeding agents...")
    seed_agents()

    print("\n2. Seeding tools...")
    seed_tools()

    print("\n3. Seeding Sigma rules...")
    seed_sigma_rules()

    print("\n4. Seeding policies...")
    seed_policies()

    print("\n" + "=" * 60)
    print("✅ All tables seeded successfully!")
    print("=" * 60)

if __name__ == "__main__":
    main()
```

**Usage:**
```bash
# Seed all tables
python scripts/seed_all.py

# Or seed individually
python scripts/seed_agents.py
python scripts/seed_tools.py
python scripts/seed_sigma_rules.py
```

---

## 4. Query Patterns

### 4.1 GET /v1/agents Implementation

```python
# app/services/agent_service.py
class AgentService:
    async def list_agents(self) -> Dict:
        """
        List all agents with runtime statistics.
        """
        # 1. Get agent metadata from sentra-agent-registry
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table('sentra-agent-registry')
        response = table.scan()
        agents = response.get('Items', [])

        # 2. Enrich with runtime stats from ECS, CloudWatch, DynamoDB session-context
        for agent in agents:
            agent_id = agent['agent_id']

            # Get ECS service status
            ecs_status = await self._get_ecs_status(agent['ecs_config']['service_name'])
            agent['ecs_status'] = ecs_status

            # Get request counts from CloudWatch Logs
            request_stats = await self._get_request_stats(agent_id)
            agent['requests_total'] = request_stats['total']
            agent['requests_allowed'] = request_stats['allowed']
            agent['requests_denied'] = request_stats['denied']

            # Get active sessions from sentra-session-context
            active_sessions = await self._get_active_sessions(agent_id)
            agent['active_sessions'] = active_sessions

        return {"agents": agents, "total": len(agents)}
```

### 4.2 GET /v1/agents/{id}/tools Implementation

```python
# app/services/agent_service.py
async def get_agent_tools(self, agent_id: str) -> Dict:
    """
    Get allowed tools for an agent.
    """
    # 1. Get allowed tool IDs from sentra-policies
    policy_table = dynamodb.Table('sentra-policies')
    policy_response = policy_table.get_item(
        Key={'policy_id': f'agent-config-{agent_id}'}
    )

    if 'Item' not in policy_response:
        raise HTTPException(status_code=404, detail="Agent not found")

    allowed_tool_ids = policy_response['Item'].get('allowed_tools', [])

    # 2. Get full tool metadata from sentra-tool-registry
    tools_table = dynamodb.Table('sentra-tool-registry')
    tools = []

    for tool_id in allowed_tool_ids:
        tool_response = tools_table.get_item(Key={'tool_id': tool_id})
        if 'Item' in tool_response:
            tools.append(tool_response['Item'])

    return {
        "agent_id": agent_id,
        "tools": tools,
        "total": len(tools)
    }
```

### 4.3 GET /v1/sigma-rules Implementation

```python
# app/services/sigma_rules_service.py
async def list_sigma_rules(self, status: Optional[str] = None, level: Optional[str] = None) -> Dict:
    """
    List Sigma rules with optional filters.
    """
    table = dynamodb.Table('sentra-sigma-rules')

    if status:
        # Query by status using GSI
        response = table.query(
            IndexName='status-index',
            KeyConditionExpression=Key('status').eq(status)
        )
    elif level:
        # Query by level using GSI
        response = table.query(
            IndexName='level-index',
            KeyConditionExpression=Key('level').eq(level)
        )
    else:
        # Scan all rules
        response = table.scan()

    rules = response.get('Items', [])

    # Sort by match count (most active first)
    rules.sort(key=lambda r: r.get('stats', {}).get('match_count_24h', 0), reverse=True)

    return {
        "rules": rules,
        "total": len(rules),
        "has_more": False
    }
```

---

## 5. Migration from v1

### 5.1 What Changes

**Before (v1):**
- Agent metadata: Hardcoded in Security Controller
- Tool metadata: Hardcoded in Security Controller or agent code
- Sigma rules: S3 YAML files
- DynamoDB tables: 3 (session-context, policies, demo data)

**After (v2):**
- Agent metadata: DynamoDB `sentra-agent-registry`
- Tool metadata: DynamoDB `sentra-tool-registry`
- Sigma rules: DynamoDB `sentra-sigma-rules`
- DynamoDB tables: 6 (+ 3 new tables)

### 5.2 Migration Steps

1. **Deploy new DynamoDB tables** (via CDK)
2. **Run seed scripts** to populate tables
3. **Update Security Controller** to read from tables (not hardcoded)
4. **Remove S3 Sigma rules** (or keep as backup)
5. **Test all APIs** with new data sources
6. **Deploy to ECS**

### 5.3 Rollback Plan

If migration fails:
1. Revert Security Controller to read from hardcoded data
2. Keep new tables (no harm, just unused)
3. Debug issues
4. Retry migration

---

## 6. Cost Analysis

**DynamoDB On-Demand Pricing:**
- Storage: $0.25/GB per month
- Reads: $0.25 per million requests
- Writes: $1.25 per million requests

**Estimated MVP Costs (3 new tables):**
- Storage: (3 agents × 2KB) + (15 tools × 3KB) + (15 rules × 5KB) ≈ 0.1 MB = **$0.00**
- Reads: ~100 reads/hour × 24 × 30 = 72K reads/month = **$0.02**
- Writes: Seed scripts only (one-time) = **$0.00**

**Total Additional Cost:** < $0.50/month

---

**End of LLD 06: Data Model v2**
