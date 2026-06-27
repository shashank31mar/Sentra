> ⚠️ **DEPRECATED (2026-06-28) — historical, not maintained.** Superseded by [lld/ARCHITECTURE.md](lld/ARCHITECTURE.md). Do not rely on this document for current architecture, requirements, or positioning; kept for historical reference only.

# New Approach: Database-First Agent Management

**Created:** 2025-01-21
**Status:** Ready for Implementation
**Replaces:** Hardcoded agent/tool/rule metadata approach

---

## TL;DR

**Instead of hardcoding** agent metadata, tool definitions, and Sigma rules in Python code or S3, we now have **dedicated DynamoDB tables** that can be seeded for MVP and extended for Phase 2.

---

## Old Approach (Rejected)

### Agent Metadata
```python
# ❌ Hardcoded in Security Controller
REGISTERED_AGENTS = [
    {
        "agent_id": "customer-query-agent",
        "name": "Customer Query Agent",
        ...
    }
]
```

**Problems:**
- Requires code changes to add agents
- No database of record
- Can't query or filter
- No foundation for Phase 2 UI

### Tool Definitions
```python
# ❌ Hardcoded in Security Controller or agent code
TOOL_REGISTRY = {
    "query_customers": {
        "name": "Query Customers",
        "type": "READ",
        ...
    }
}
```

**Problems:**
- Duplicated across agent code and Security Controller
- Can't list all available tools
- No parameter validation schema storage
- Embedded in policies table (DynamoDB row size limit)

### Sigma Rules
```yaml
# ❌ S3 YAML files
s3://sentra-mvp-artifacts/sigma_rules/llm/prompt_injection_basic.yaml
```

**Problems:**
- Slow to query (list all objects, download, parse YAML)
- Can't filter by level or status efficiently
- No match count storage (requires separate CloudWatch query)
- No foundation for Phase 2 rule creator UI

---

## New Approach (Accepted)

### 3 New DynamoDB Tables

| Table | Purpose | MVP Items | Phase 2 |
|-------|---------|-----------|---------|
| `sentra-agent-registry` | Agent metadata | 3-5 | Dynamic registration |
| `sentra-tool-registry` | Tool definitions | 15-20 | Tool builder UI |
| `sentra-sigma-rules` | Sigma rules | 15-20 | Rule creator UI |

### Benefits

#### 1. Agent Metadata in `sentra-agent-registry`

**MVP:**
```python
# Seed script populates table
{
  "agent_id": "customer-query-agent",
  "name": "Customer Query Agent",
  "description": "...",
  "ecs_config": {...},
  "runtime_config": {...},
  "status": "active"
}
```

```python
# GET /v1/agents implementation
table = dynamodb.Table('sentra-agent-registry')
agents = table.scan().get('Items', [])
```

**Phase 2:**
- POST /v1/agents → Dashboard "Add Agent" button
- PUT /v1/agents/{id} → Edit agent metadata
- Agent deployment wizard

#### 2. Tool Definitions in `sentra-tool-registry`

**MVP:**
```python
# Seed script populates table
{
  "tool_id": "query_customers",
  "name": "Query Customers",
  "tool_type": "READ",
  "parameters": {
    "state": {"type": "string", "required": False},
    "limit": {"type": "integer", "max": 1000}
  },
  "rate_limit": {...}
}
```

```python
# GET /v1/agents/{id}/tools implementation
# 1. Get allowed tool IDs from sentra-policies
allowed_tool_ids = ["query_customers", "query_orders"]

# 2. Fetch full tool objects from sentra-tool-registry
tools = [get_tool(tool_id) for tool_id in allowed_tool_ids]
```

**Solves DynamoDB row size limit:**
- `sentra-policies` table stores only tool IDs (list of strings)
- Full tool metadata in separate `sentra-tool-registry` table
- No 400KB row limit concerns

**Phase 2:**
- POST /v1/tools → Dashboard "Add Tool" button
- Visual parameter editor
- Tool testing sandbox

#### 3. Sigma Rules in `sentra-sigma-rules`

**MVP:**
```python
# Seed script populates table
{
  "rule_id": "sigma-llm-001",
  "title": "Prompt Injection - Ignore Previous Instructions",
  "level": "high",
  "detection": {
    "patterns": ["ignore previous instructions", ...]
  },
  "stats": {
    "match_count_24h": 12,
    "last_matched": "2025-01-21T10:42:15Z"
  }
}
```

```python
# GET /v1/sigma-rules?level=high
table = dynamodb.Table('sentra-sigma-rules')
rules = table.query(
    IndexName='level-index',
    KeyConditionExpression=Key('level').eq('high')
)
```

**Benefits:**
- Fast queries with GSI (level-index, status-index)
- Match counts stored in rule item (no separate CloudWatch query)
- Can filter and sort efficiently

**Phase 2:**
- POST /v1/sigma-rules → Dashboard "Add Custom Rule" button
- Visual pattern editor
- Rule testing with sample prompts

---

## Database Schema Overview

### sentra-agent-registry

```json
{
  "agent_id": "customer-query-agent",  // PK
  "name": "Customer Query Agent",
  "description": "...",
  "type": "custom",
  "status": "active",  // GSI
  "ecs_config": {...},
  "runtime_config": {...},
  "created_at": "...",
  "tags": [...]
}
```

**Indexes:**
- Primary Key: `agent_id`
- GSI: `status-index` (for filtering active/inactive agents)

---

### sentra-tool-registry

```json
{
  "tool_id": "query_customers",  // PK
  "name": "Query Customers",
  "tool_type": "READ",  // GSI
  "category": "database",
  "parameters": {...},
  "rate_limit": {...},
  "created_at": "..."
}
```

**Indexes:**
- Primary Key: `tool_id`
- GSI: `type-index` (for filtering READ/WRITE tools)

---

### sentra-sigma-rules

```json
{
  "rule_id": "sigma-llm-001",  // PK
  "title": "Prompt Injection...",
  "status": "stable",  // GSI
  "level": "high",  // GSI
  "detection": {
    "patterns": [...],
    "condition": "any"
  },
  "stats": {
    "match_count_24h": 12,
    "match_count_7d": 45,
    "last_matched": "..."
  },
  "created_at": "..."
}
```

**Indexes:**
- Primary Key: `rule_id`
- GSI: `status-index` (for filtering stable/experimental rules)
- GSI: `level-index` (for filtering critical/high/medium/low rules)

---

### sentra-policies (Updated)

```json
{
  "policy_id": "agent-config-customer-query-agent",
  "agent_id": "customer-query-agent",

  // ✅ Tool IDs only (not full objects)
  "allowed_tools": ["query_customers", "query_orders"],

  "policies": [
    {
      "policy_id": "pol-001",
      "name": "Max Query Limit",
      "rule": "query_limit <= 1000",
      "action": "DENY"
    }
  ]
}
```

**Key Change:** `allowed_tools` is now a **list of tool IDs** (strings), not full tool objects. No DynamoDB row size concerns.

---

## Seed Scripts

### Master Script
```bash
# scripts/seed_all.py
python scripts/seed_all.py
```

**Seeds 4 tables:**
1. `sentra-agent-registry` (3-5 agents)
2. `sentra-tool-registry` (15-20 tools)
3. `sentra-sigma-rules` (15-20 rules)
4. `sentra-policies` (updated with tool IDs)

### Individual Scripts
```bash
python scripts/seed_agents.py
python scripts/seed_tools.py
python scripts/seed_sigma_rules.py
python scripts/seed_policies.py
```

**Example: seed_agents.py**
```python
#!/usr/bin/env python3
import boto3
from datetime import datetime

def seed_agents():
    dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
    table = dynamodb.Table('sentra-agent-registry')

    agents = [
        {
            "agent_id": "customer-query-agent",
            "name": "Customer Query Agent",
            "description": "Handles customer data queries",
            "type": "custom",
            "status": "active",
            "ecs_config": {...},
            "created_at": datetime.utcnow().isoformat() + "Z"
        },
        # ... more agents
    ]

    for agent in agents:
        table.put_item(Item=agent)
        print(f"✅ Seeded {agent['agent_id']}")

if __name__ == "__main__":
    seed_agents()
```

---

## API Implementation Changes

### GET /v1/agents

**Before (rejected):**
```python
# ❌ Hardcoded
AGENTS = [...]
return {"agents": AGENTS, "total": len(AGENTS)}
```

**After (new approach):**
```python
# ✅ From DynamoDB
table = dynamodb.Table('sentra-agent-registry')
agents = table.scan().get('Items', [])

# Enrich with runtime stats
for agent in agents:
    agent['status'] = await get_ecs_status(agent['ecs_config']['service_name'])
    agent['requests_total'] = await get_request_counts(agent['agent_id'])

return {"agents": agents, "total": len(agents)}
```

---

### GET /v1/agents/{id}/tools

**Before (rejected):**
```python
# ❌ Tools embedded in policies table (DynamoDB row size limit)
agent_config = get_agent_config(agent_id)
tools = agent_config['allowed_tools']  # Full tool objects (can exceed 400KB)
```

**After (new approach):**
```python
# ✅ Tool IDs in policies, full objects in tool-registry
# 1. Get tool IDs from sentra-policies
allowed_tool_ids = ["query_customers", "query_orders"]

# 2. Fetch full tool objects from sentra-tool-registry
tools = []
for tool_id in allowed_tool_ids:
    tool = dynamodb.Table('sentra-tool-registry').get_item(Key={'tool_id': tool_id})
    tools.append(tool['Item'])

return {"tools": tools, "total": len(tools)}
```

---

### GET /v1/sigma-rules

**Before (rejected):**
```python
# ❌ S3 YAML files (slow, requires YAML parsing)
s3_objects = s3.list_objects_v2(Bucket='sentra-mvp-artifacts', Prefix='sigma_rules/')
rules = []
for obj in s3_objects['Contents']:
    yaml_content = s3.get_object(Bucket='...', Key=obj['Key'])['Body'].read()
    rule = yaml.safe_load(yaml_content)
    rules.append(rule)
```

**After (new approach):**
```python
# ✅ DynamoDB with GSI for fast queries
table = dynamodb.Table('sentra-sigma-rules')

if level:
    # Fast query using level-index GSI
    rules = table.query(
        IndexName='level-index',
        KeyConditionExpression=Key('level').eq(level)
    ).get('Items', [])
else:
    # Scan (low item count ~15-20, acceptable)
    rules = table.scan().get('Items', [])

# Match counts already in rule items (no separate CloudWatch query)
return {"rules": rules, "total": len(rules)}
```

---

## Configurable Caching

**Environment Variables:**
```yaml
# ECS Task Definition
environment:
  - CACHE_ENABLED=true
  - AGENT_METADATA_CACHE_TTL_SECONDS=60
  - TOOL_REGISTRY_CACHE_TTL_SECONDS=300
  - POLICY_CACHE_TTL_SECONDS=300
  - SIGMA_RULES_CACHE_TTL_SECONDS=600
  - MAX_CACHE_SIZE=1000
```

**Implementation:**
```python
class PolicyService:
    def __init__(self):
        from app.config import settings
        self._cache_enabled = settings.cache_enabled
        self._cache_ttl = settings.policy_cache_ttl_seconds

    async def query_policies(self, agent_id: str):
        if not self._cache_enabled:
            return await self._fetch_policies(agent_id)

        # Check cache, fetch if miss, update cache
        ...
```

**Disable for testing:**
```bash
export CACHE_ENABLED=false
```

---

## Migration Path

### Step 1: Deploy Tables (CDK)
```bash
# Update cdk/stacks/storage_stack.py with new tables
# See LLD 06 for table definitions

cdk deploy Sentra-DEV-Storage-Stack --profile sentra
```

### Step 2: Run Seed Scripts
```bash
cd scripts
python seed_all.py
```

### Step 3: Verify Data
```bash
# Check agents
aws dynamodb scan --table-name sentra-agent-registry --profile sentra

# Check tools
aws dynamodb scan --table-name sentra-tool-registry --profile sentra

# Check rules
aws dynamodb scan --table-name sentra-sigma-rules --profile sentra
```

### Step 4: Implement APIs
```bash
# Implement agent_service.py, policy_service.py, sigma_rules_service.py
# Add routes to app/api/routes.py
# Write unit tests
```

### Step 5: Update Dashboard
```bash
# Replace mock data with real API calls
# See Workstream 4, Milestone 5
```

---

## Cost Analysis

**Additional DynamoDB Tables (On-Demand):**
- Storage: (3 agents × 2KB) + (15 tools × 3KB) + (15 rules × 5KB) ≈ 0.1 MB = **$0.00/month**
- Reads: ~100 reads/hour × 24 × 30 = 72K reads/month = **$0.02/month**
- Writes: Seed scripts only (one-time) = **$0.00**

**Total Additional Cost:** < $0.50/month

**ElastiCache (Phase 2):** ~$15/month for t3.micro Redis instance

---

## Documentation Created

1. ✅ **MVP-PHASE2.md** - Clear separation of MVP vs Phase 2 features
2. ✅ **LLD 06: Data Model v2** - Complete table schemas, seed scripts, query patterns
3. ✅ **LLD 05: Agent Management APIs** - Updated to reference new tables
4. ✅ **Dashboard LLD** - Updated data flow and API references
5. ✅ **Workstream 4** - Updated Milestone 5 tasks with correct API calls

---

## Next Steps

### Immediate (Day 1-2)
1. Review and approve new approach
2. Update CDK stack with new table definitions
3. Write seed scripts (3 scripts, ~300 lines total)

### Week 1
4. Deploy tables to dev environment
5. Run seed scripts and verify data
6. Implement Agent Management APIs in Security Controller

### Week 2
7. Test APIs with curl/Postman
8. Update Dashboard to use real APIs (Milestone 5)
9. Deploy to ECS and test end-to-end

**Estimated Total Effort:** 3-4 days

---

## Summary

| Aspect | Old Approach | New Approach |
|--------|--------------|--------------|
| **Agent Metadata** | Hardcoded in Python | DynamoDB `sentra-agent-registry` |
| **Tool Definitions** | Hardcoded or embedded in policies | DynamoDB `sentra-tool-registry` |
| **Sigma Rules** | S3 YAML files | DynamoDB `sentra-sigma-rules` |
| **Query Performance** | N/A (in-memory) | Fast with GSI indexes |
| **Caching** | Not configurable | Fully configurable via env vars |
| **DynamoDB Row Size** | Can exceed 400KB | No concerns (separate tables) |
| **Phase 2 Ready** | ❌ Requires major refactoring | ✅ Foundation in place |
| **Cost** | $0 | < $0.50/month |
| **Implementation Effort** | N/A | 3-4 days |

**Conclusion:** The new database-first approach provides a clean, scalable foundation for MVP that can seamlessly evolve into Phase 2 CRUD operations without major refactoring.

---

**End of New Approach Summary**
