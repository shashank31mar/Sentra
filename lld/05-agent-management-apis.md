# LLD 05: Agent Management APIs

**Version:** 1.0
**Last Updated:** 2025-01-21
**Status:** Ready for Implementation
**Prerequisites:** [LLD 01: CDK Infrastructure](./01-cdk-infrastructure.md), [LLD 03: Security Controller](./03-security-controller.md)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Component Architecture](#2-component-architecture)
3. [APIs & Interfaces](#3-apis--interfaces)
4. [Data Models](#4-data-models)
5. [Configuration](#5-configuration)
6. [Error Handling](#6-error-handling)
7. [Monitoring & Observability](#7-monitoring--observability)
8. [Cross-References](#8-cross-references)

---

## 1. Overview

### 1.1 Purpose

The **Agent Management APIs** provide read-only access to agent metadata, policies, tools, and Sigma rules. These APIs enable the Dashboard to display agent configurations, security policies, and threat detection rules without directly accessing DynamoDB or S3.

**Key Principle**: Dashboard should call Security Controller APIs, not directly query DynamoDB/S3.

### 1.2 Scope

**In Scope**:
- ✅ GET /v1/agents - List all registered agents
- ✅ GET /v1/agents/{agent_id} - Get specific agent details
- ✅ GET /v1/agents/{agent_id}/tools - Get agent's allowed tools
- ✅ GET /v1/policies - Query policies with filters
- ✅ GET /v1/sigma-rules - List Sigma rules with match counts
- ✅ Read-only access to configuration data

**Out of Scope** (MVP):
- ❌ POST/PUT/DELETE endpoints (policy CRUD)
- ❌ Runtime policy updates (use GitOps for config changes)
- ❌ Sigma rule editing UI (rules managed in S3)
- ❌ Agent registration/deregistration APIs

**Phase 2 Candidates**:
- Policy CRUD APIs (POST /v1/policies, PUT /v1/policies/{id}, DELETE /v1/policies/{id})
- Sigma rule management APIs
- Agent registration workflow

### 1.3 Dependencies

| Dependency | Purpose | Critical? |
|------------|---------|-----------|
| DynamoDB: `sentra-agent-registry` | Agent metadata (NEW - see [LLD 06](./06-data-model-v2.md)) | ✅ Yes |
| DynamoDB: `sentra-tool-registry` | Tool definitions (NEW - see [LLD 06](./06-data-model-v2.md)) | ✅ Yes |
| DynamoDB: `sentra-sigma-rules-metadata` | Sigma rule metadata (content in S3) (NEW - see [LLD 06](./06-data-model-v2.md)) | ✅ Yes |
| DynamoDB: `sentra-policies` | Agent-tool associations (legacy, updated format) | ✅ Yes |
| S3: `s3://sentra-mvp-artifacts/sigma_rules/llm/` | Full Sigma rule YAML files | ✅ Yes |
| DynamoDB: `sentra-session-context` | Agent runtime stats (uptime, requests) | ✅ Yes |
| CloudWatch Logs: `/sentra/audit-logs` | Request counts and match statistics | ✅ Yes |
| ECS API | Service status (running/stopped) | ✅ Yes |

### 1.4 Design Principles

1. **Read-Only for MVP**: No runtime config changes (use GitOps)
2. **Single Source of Truth**: Security Controller is the only API layer for Dashboard
3. **Hybrid Storage**: DynamoDB for metadata (fast queries) + S3 for content (no size limits, versioning)
4. **Performance**: Cache policy/rule data (5-minute TTL)
5. **Fail-Safe**: Return empty arrays on errors (never block Dashboard)
6. **Observable**: Log all API calls for audit

### 1.5 Hybrid Storage Pattern

**Why Hybrid Storage?**
- **DynamoDB metadata tables**: Fast queries, GSI filtering, real-time stats (match counts, trust scores)
- **S3 content storage**: No size limits (100+ policies/rules), versioning, GitOps-friendly

**Tables Using Hybrid Storage**:
1. **Sigma Rules**: `sentra-sigma-rules-metadata` (DynamoDB) + `s3://sentra-mvp-artifacts/sigma_rules/llm/*.yaml` (S3)
   - Metadata: rule_id, title, level, status, patterns_count, tags, match stats
   - Content: Full detection patterns, references, author info
2. **Policies** (Phase 2): `sentra-policies-metadata` (DynamoDB) + `s3://sentra-mvp-artifacts/policies/agents/*.yaml` (S3)
   - MVP uses legacy `sentra-policies` table (no S3) for simplicity
   - Phase 2 migrates to hybrid storage

**Content Loading Strategy**:
- **Security Controller**: Loads full content from S3 on startup, caches in memory (5-10 min TTL)
- **Dashboard APIs**: Returns metadata only (fast), Dashboard fetches S3 content on-demand if needed
- **Phase 2**: Add `include_content=true` query param to APIs to return full content inline

---

## 2. Component Architecture

### 2.1 File Structure

```
security-controller/
├── app/
│   ├── api/
│   │   └── routes.py                          # Add new endpoints
│   ├── services/
│   │   ├── agent_service.py                   # NEW - Agent metadata logic
│   │   ├── policy_service.py                  # NEW - Policy queries
│   │   └── sigma_rules_service.py             # NEW - Sigma rule queries
│   ├── utils/
│   │   ├── policy_loader.py                   # Load from DynamoDB
│   │   └── sigma_loader.py                    # Load from S3
│   └── config.py
```

### 2.2 Component Responsibilities

| Component | File | Purpose | Lines (Est.) |
|-----------|------|---------|--------------|
| **Agent Service** | `services/agent_service.py` | Aggregate agent metadata | ~200 |
| **Policy Service** | `services/policy_service.py` | Query policies from DynamoDB | ~150 |
| **Sigma Rules Service** | `services/sigma_rules_service.py` | Load rules from S3 + match counts | ~180 |
| **Policy Loader** | `utils/policy_loader.py` | DynamoDB query helper | ~100 |
| **Sigma Loader** | `utils/sigma_loader.py` | S3 + YAML parsing | ~120 |

**Total Estimated Code**: ~750 lines

### 2.3 Data Flow

```
Dashboard Request
    ↓
Security Controller API (routes.py)
    ↓
Service Layer (agent_service.py, policy_service.py, sigma_rules_service.py)
    ↓
Data Sources (DynamoDB sentra-agent-registry, sentra-tool-registry, sentra-sigma-rules-metadata, sentra-policies, S3 sigma_rules/, CloudWatch Logs)
    ↓
Response (JSON)
    ↓
Dashboard (display data)
```

---

## 3. APIs & Interfaces

### 3.1 GET /v1/agents

**Purpose**: List all registered agents with runtime statistics.

**Query Parameters**: None

**Response**:
```json
{
  "agents": [
    {
      "agent_id": "customer-query-agent",
      "name": "Customer Query Agent",
      "description": "Handles customer data queries with read-only access",
      "status": "running",
      "uptime_seconds": 9240,
      "last_seen": "2025-01-21T10:45:30Z",
      "trust_score_avg": 95.0,
      "requests_total": 847,
      "requests_allowed": 845,
      "requests_denied": 2,
      "active_sessions": 3
    },
    {
      "agent_id": "payment-agent",
      "name": "Payment Agent",
      "description": "Processes payments and refunds with write access",
      "status": "running",
      "uptime_seconds": 9240,
      "last_seen": "2025-01-21T10:45:28Z",
      "trust_score_avg": 88.5,
      "requests_total": 234,
      "requests_allowed": 230,
      "requests_denied": 4,
      "active_sessions": 1
    },
    {
      "agent_id": "security-controller",
      "name": "Security Controller",
      "description": "Validates all agent requests and enforces policies",
      "status": "running",
      "uptime_seconds": 9300,
      "last_seen": "2025-01-21T10:45:32Z",
      "trust_score_avg": 100.0,
      "requests_total": 1247,
      "requests_allowed": 1224,
      "requests_denied": 23,
      "active_sessions": 0
    }
  ],
  "total": 3
}
```

**Implementation**:
```python
# app/services/agent_service.py
class AgentService:
    async def list_agents(self) -> Dict:
        """
        List all agents with runtime statistics.

        Data Sources:
        1. Agent metadata from sentra-agent-registry table (NEW - see LLD 06)
        2. Runtime stats from ECS API (service status)
        3. Request counts from CloudWatch Logs (last 24h)
        4. Active sessions from sentra-session-context

        Returns:
            Dictionary with agents array and total count.
        """
        # 1. Get agent metadata from sentra-agent-registry
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table('sentra-agent-registry')
        response = table.scan()  # Low item count (3-5 agents), Scan is acceptable
        agents = response.get('Items', [])

        # 2. Enrich with runtime statistics
        for agent in agents:
            agent_id = agent['agent_id']

            # Get ECS service status (running, stopped, deploying)
            ecs_status = await self._get_ecs_status(agent['ecs_config']['service_name'])
            agent['status'] = ecs_status['status']
            agent['uptime_seconds'] = ecs_status['uptime_seconds']
            agent['last_seen'] = ecs_status['last_seen']

            # Get request counts from CloudWatch Logs (last 24h)
            logs_service = LogsService()
            counts = await logs_service.get_request_counts_by_agent(agent_id)
            agent['requests_total'] = counts.get('total', 0)
            agent['requests_allowed'] = counts.get('allowed', 0)
            agent['requests_denied'] = counts.get('denied', 0)

            # Get active sessions from sentra-session-context
            session_manager = SessionManager()
            sessions = await session_manager.get_active_sessions_count(agent_id)
            agent['active_sessions'] = sessions

            # Calculate average trust score from active sessions
            avg_trust = await session_manager.get_avg_trust_score(agent_id)
            agent['trust_score_avg'] = avg_trust

        return {
            "agents": agents,
            "total": len(agents)
        }
```

**HTTP Status Codes**:
- `200 OK` - Success
- `500 Internal Server Error` - DynamoDB/CloudWatch failure (return empty array with error logged)

---

### 3.2 GET /v1/agents/{agent_id}

**Purpose**: Get detailed information about a specific agent.

**Path Parameters**:
- `agent_id` (string, required) - Agent identifier

**Response**:
```json
{
  "agent_id": "customer-query-agent",
  "name": "Customer Query Agent",
  "description": "Handles customer data queries with read-only access",
  "status": "running",
  "uptime_seconds": 9240,
  "last_seen": "2025-01-21T10:45:30Z",
  "trust_score_avg": 95.0,
  "requests_total": 847,
  "requests_allowed": 845,
  "requests_denied": 2,
  "active_sessions": 3,
  "allowed_tools": [
    "query_customers",
    "query_orders",
    "query_with_limit"
  ],
  "policies_count": 3,
  "created_at": "2025-01-13T08:00:00Z",
  "updated_at": "2025-01-20T15:30:00Z"
}
```


**HTTP Status Codes**:
- `200 OK` - Success
- `404 Not Found` - Agent not found
- `500 Internal Server Error` - DynamoDB failure

---

### 3.3 GET /v1/agents/{agent_id}/tools

**Purpose**: Get list of allowed tools for an agent.

**Path Parameters**:
- `agent_id` (string, required) - Agent identifier

**Response**:
```json
{
  "agent_id": "customer-query-agent",
  "tools": [
    {
      "name": "query_customers",
      "type": "READ",
      "description": "Query customer database with filters",
      "parameters": {
        "state": "string (optional)",
        "city": "string (optional)",
        "limit": "integer (max: 1000)"
      },
      "rate_limit": 60
    },
    {
      "name": "query_orders",
      "type": "READ",
      "description": "Query order history for customers",
      "parameters": {
        "customer_id": "string (required)",
        "limit": "integer (max: 100)"
      },
      "rate_limit": 60
    },
    {
      "name": "query_with_limit",
      "type": "READ",
      "description": "Query with row limit enforcement",
      "parameters": {
        "query": "string (required)",
        "limit": "integer (max: 1000)"
      },
      "rate_limit": 30
    }
  ],
  "total": 3
}
```

**Implementation**:
```python
# app/services/agent_service.py
async def get_agent_tools(self, agent_id: str) -> Dict:
    """
    Get allowed tools for an agent.

    Data Sources:
    1. sentra-policies table (allowed_tools field - list of tool IDs)
    2. sentra-tool-registry table (full tool metadata)

    Returns:
        Dictionary with tools array and total count.
    """
    dynamodb = boto3.resource('dynamodb')

    # 1. Get allowed tool IDs from sentra-policies
    policies_table = dynamodb.Table('sentra-policies')
    policy_response = policies_table.get_item(
        Key={'policy_id': f'agent-config-{agent_id}'}
    )

    if 'Item' not in policy_response:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    allowed_tool_ids = policy_response['Item'].get('allowed_tools', [])

    # 2. Get full tool metadata from sentra-tool-registry
    tools_table = dynamodb.Table('sentra-tool-registry')
    tools = []

    for tool_id in allowed_tool_ids:
        tool_response = tools_table.get_item(Key={'tool_id': tool_id})
        if 'Item' in tool_response:
            tools.append(tool_response['Item'])
        else:
            # Tool ID in allowed list but not in registry (data inconsistency)
            logger.warning(f"Tool {tool_id} not found in registry for agent {agent_id}")

    return {
        "agent_id": agent_id,
        "tools": tools,
        "total": len(tools)
    }
```

**HTTP Status Codes**:
- `200 OK` - Success
- `404 Not Found` - Agent not found
- `500 Internal Server Error` - DynamoDB failure

---

### 3.4 GET /v1/policies

**Purpose**: Query agent policies with optional filters.

**Query Parameters**:
- `agent_id` (string, optional) - Filter by agent ID
- `status` (string, optional) - Filter by status (active, disabled, warning)
- `limit` (integer, optional, default: 50, max: 200) - Max results

**Response**:
```json
{
  "policies": [
    {
      "policy_id": "pol-001",
      "agent_id": "customer-query-agent",
      "name": "Max Query Limit",
      "description": "Limit query results to 1000 rows",
      "status": "active",
      "rule": "query_limit <= 1000",
      "action": "DENY",
      "severity": "high",
      "match_count_24h": 0,
      "created_at": "2025-01-13T08:00:00Z",
      "updated_at": "2025-01-13T08:00:00Z"
    },
    {
      "policy_id": "pol-002",
      "agent_id": "customer-query-agent",
      "name": "Rate Limit Policy",
      "description": "Limit requests to 60 per minute",
      "status": "active",
      "rule": "requests_per_minute <= 60",
      "action": "DENY",
      "severity": "medium",
      "match_count_24h": 0,
      "created_at": "2025-01-13T08:00:00Z",
      "updated_at": "2025-01-13T08:00:00Z"
    },
    {
      "policy_id": "pol-003",
      "agent_id": "customer-query-agent",
      "name": "Read-Only Enforcement",
      "description": "Block all write operations",
      "status": "active",
      "rule": "operation_type == WRITE",
      "action": "DENY",
      "severity": "critical",
      "match_count_24h": 0,
      "created_at": "2025-01-13T08:00:00Z",
      "updated_at": "2025-01-13T08:00:00Z"
    }
  ],
  "total": 3,
  "has_more": false
}
```

**Implementation**:
```python
# app/services/policy_service.py
class PolicyService:
    async def query_policies(
        self,
        agent_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50
    ) -> Dict:
        """
        Query policies from DynamoDB with filters.

        Returns:
            Dictionary with policies array, total, and has_more flag.
        """
        policy_loader = PolicyLoader()

        # Query DynamoDB
        policies = await policy_loader.query_policies(
            agent_id=agent_id,
            status=status,
            limit=limit
        )

        # Get match counts from CloudWatch Logs (last 24h)
        logs_service = LogsService()
        match_counts = await logs_service.get_policy_match_counts()

        # Enrich policies with match counts
        for policy in policies:
            policy_id = policy['policy_id']
            policy['match_count_24h'] = match_counts.get(policy_id, 0)

        return {
            "policies": policies[:limit],
            "total": len(policies),
            "has_more": len(policies) > limit
        }
```

**HTTP Status Codes**:
- `200 OK` - Success (empty array if no matches)
- `400 Bad Request` - Invalid status or limit
- `500 Internal Server Error` - DynamoDB failure

---

### 3.5 GET /v1/sigma-rules

**Purpose**: List Sigma rules with match counts.

**Query Parameters**:
- `status` (string, optional) - Filter by status (stable, experimental, deprecated)
- `level` (string, optional) - Filter by severity level (critical, high, medium, low)
- `limit` (integer, optional, default: 50, max: 200) - Max results

**Response**:
```json
{
  "rules": [
    {
      "rule_id": "sigma-llm-001",
      "title": "Prompt Injection - Ignore Previous Instructions",
      "description": "Detects prompt injection attempts using 'ignore previous instructions' pattern",
      "status": "stable",
      "level": "high",
      "tags": [
        "attack.llm01",
        "owasp.llm.top10.2025"
      ],
      "patterns_count": 20,
      "match_count_24h": 12,
      "match_count_7d": 45,
      "last_matched": "2025-01-21T10:42:15Z",
      "s3_key": "sigma_rules/llm/prompt_injection_basic.yaml",
      "created_at": "2025-01-13T08:00:00Z",
      "updated_at": "2025-01-13T08:00:00Z"
    },
    {
      "rule_id": "sigma-llm-002",
      "title": "Jailbreak Attempts",
      "description": "Detects jailbreak attempts (DAN mode, etc.)",
      "status": "stable",
      "level": "high",
      "tags": [
        "attack.llm01",
        "owasp.llm.top10.2025",
        "jailbreak"
      ],
      "patterns_count": 15,
      "match_count_24h": 0,
      "match_count_7d": 2,
      "last_matched": "2025-01-20T14:22:30Z",
      "s3_key": "sigma_rules/llm/jailbreak_attempts.yaml",
      "created_at": "2025-01-13T08:00:00Z",
      "updated_at": "2025-01-13T08:00:00Z"
    },
    {
      "rule_id": "sigma-llm-003",
      "title": "Data Exfiltration - Mass Query",
      "description": "Detects mass data exfiltration via repeated queries",
      "status": "stable",
      "level": "critical",
      "tags": [
        "attack.llm06",
        "owasp.llm.top10.2025",
        "data-leak"
      ],
      "patterns_count": 10,
      "match_count_24h": 8,
      "match_count_7d": 23,
      "last_matched": "2025-01-21T09:15:42Z",
      "s3_key": "sigma_rules/llm/data_exfiltration.yaml",
      "created_at": "2025-01-13T08:00:00Z",
      "updated_at": "2025-01-13T08:00:00Z"
    }
  ],
  "total": 3,
  "has_more": false
}
```

**Implementation**:
```python
# app/services/sigma_rules_service.py
class SigmaRulesService:
    async def list_sigma_rules(
        self,
        status: Optional[str] = None,
        level: Optional[str] = None,
        limit: int = 50
    ) -> Dict:
        """
        List Sigma rules from DynamoDB metadata table with match counts.

        Data Source: sentra-sigma-rules-metadata table (NEW - see LLD 06)
        Note: Returns metadata only. Full rule content in S3, loaded on-demand.

        Returns:
            Dictionary with rules array, total, and has_more flag.
        """
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table('sentra-sigma-rules-metadata')

        # Query with filters using GSI
        if status:
            # Query by status using status-index GSI
            response = table.query(
                IndexName='status-index',
                KeyConditionExpression=Key('status').eq(status)
            )
        elif level:
            # Query by level using level-index GSI
            response = table.query(
                IndexName='level-index',
                KeyConditionExpression=Key('level').eq(level)
            )
        else:
            # Scan all rules (low item count ~15-20, acceptable)
            response = table.scan()

        rules = response.get('Items', [])

        # Note: Returns metadata only (rule_id, title, level, status, patterns_count, etc.)
        # Full rule content (detection patterns, YAML) is stored in S3 at s3_key
        # Dashboard can fetch full content via: s3.get_object(Bucket=s3_bucket, Key=s3_key)
        # Security Controller already has full rules loaded in memory cache

        # Match counts stored in metadata (updated by Security Controller after each match)
        # No need to query CloudWatch separately

        # Sort by match count (most active first)
        rules.sort(key=lambda r: r.get('stats', {}).get('match_count_24h', 0), reverse=True)

        return {
            "rules": rules[:limit],
            "total": len(rules),
            "has_more": len(rules) > limit
        }
```

**HTTP Status Codes**:
- `200 OK` - Success (empty array if no rules)
- `400 Bad Request` - Invalid status or level
- `500 Internal Server Error` - S3 failure

---

## 4. Data Models

**IMPORTANT**: Detailed table schemas are defined in **[LLD 06: Data Model v2](./06-data-model-v2.md)**.

This section provides a brief summary only. Refer to LLD 06 for complete schemas, seed data, and query patterns.

### 4.1 DynamoDB Tables Overview

| Table | Purpose | Items (MVP) | Details |
|-------|---------|-------------|---------|
| `sentra-agent-registry` | Agent metadata | 3-5 | See [LLD 06 Section 2.1](./06-data-model-v2.md#21-table-sentra-agent-registry) |
| `sentra-tool-registry` | Tool definitions | 15-20 | See [LLD 06 Section 2.2](./06-data-model-v2.md#22-table-sentra-tool-registry) |
| `sentra-sigma-rules-metadata` | Sigma rule metadata (content in S3) | 15-20 | See [LLD 06 Section 2.4](./06-data-model-v2.md#24-table-sentra-sigma-rules-metadata) |
| `sentra-policies` | Agent-tool associations | 3-5 | See [LLD 06 Section 2.4](./06-data-model-v2.md#24-updated-table-sentra-policies) |

### 4.2 DynamoDB Schema: sentra-policies (Agent-Tool Associations)

**Purpose**: Link agents to their allowed tools (tool IDs only, not full objects)

```json
{
  "policy_id": "agent-config-customer-query-agent",
  "agent_id": "customer-query-agent",

  // Allowed tools (list of tool IDs, NOT full tool objects)
  "allowed_tools": [
    "query_customers",
    "query_orders",
    "query_with_limit"
  ],

  // Business policies
  "policies": [
    {
      "policy_id": "pol-001",
      "name": "Max Query Limit",
      "description": "Limit query results to 1000 rows",
      "rule": "query_limit <= 1000",
      "action": "DENY",
      "severity": "high",
      "enabled": true
    }
  ],

  "created_at": "2025-01-13T08:00:00Z",
  "updated_at": "2025-01-20T15:30:00Z"
}
```

**Key Change from v1**: `allowed_tools` now stores **tool IDs** (strings), not full tool objects. Full tool metadata is fetched from `sentra-tool-registry` table.

**Query Patterns**:
1. Get agent config: `GetItem(policy_id="agent-config-{agent_id}")`
2. Query policies by agent: Already exists (see LLD 03)

---

## 5. Configuration

### 5.1 Environment Variables

**Add new environment variables for caching configuration**:

```python
# app/config.py
class Settings(BaseSettings):
    # Existing settings
    environment: str = "dev"
    aws_region: str = "us-east-1"
    port: int = 8080
    log_level: str = "INFO"

    # NEW: Caching configuration
    cache_enabled: bool = True
    agent_metadata_cache_ttl_seconds: int = 60  # 1 minute (agents rarely change)
    tool_registry_cache_ttl_seconds: int = 300  # 5 minutes (tools rarely change)
    policy_cache_ttl_seconds: int = 300  # 5 minutes (policies change via GitOps)
    sigma_rules_cache_ttl_seconds: int = 600  # 10 minutes (rules change via GitOps)

    # Cache size limits (prevent memory bloat)
    max_cache_size: int = 1000  # Max cached items per service

    class Config:
        env_file = ".env"
```

**Docker Environment Variables** (ECS Task Definition):
```yaml
environment:
  # Existing
  - AWS_REGION=us-east-1
  - LOG_LEVEL=INFO

  # NEW: Caching
  - CACHE_ENABLED=true
  - AGENT_METADATA_CACHE_TTL_SECONDS=60
  - TOOL_REGISTRY_CACHE_TTL_SECONDS=300
  - POLICY_CACHE_TTL_SECONDS=300
  - SIGMA_RULES_CACHE_TTL_SECONDS=600
  - MAX_CACHE_SIZE=1000
```

### 5.2 Caching Strategy

**Configurable TTL-based caching** (in-memory for MVP, ElastiCache for Phase 2):

```python
# app/services/policy_service.py
class PolicyService:
    def __init__(self):
        from app.config import settings
        self._cache = {}
        self._cache_enabled = settings.cache_enabled
        self._cache_ttl = settings.policy_cache_ttl_seconds
        self._max_cache_size = settings.max_cache_size

    async def query_policies(self, agent_id: str) -> Dict:
        if not self._cache_enabled:
            # Caching disabled, fetch directly
            return await self._fetch_policies(agent_id)

        cache_key = f"policies:{agent_id}"

        # Check cache
        if cache_key in self._cache:
            cached_data, timestamp = self._cache[cache_key]
            if time.time() - timestamp < self._cache_ttl:
                logger.debug(f"Cache hit for {cache_key}")
                return cached_data
            else:
                # Cache expired, remove
                logger.debug(f"Cache expired for {cache_key}")
                del self._cache[cache_key]

        # Fetch from DynamoDB
        data = await self._fetch_policies(agent_id)

        # Update cache (with size limit check)
        if len(self._cache) >= self._max_cache_size:
            # Evict oldest entry (simple LRU)
            oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][1])
            del self._cache[oldest_key]
            logger.warning(f"Cache size limit reached, evicted {oldest_key}")

        self._cache[cache_key] = (data, time.time())
        logger.debug(f"Cached {cache_key}")

        return data
```

**Cache Invalidation Strategy**:
- **MVP**: TTL-based only (no manual invalidation)
  - Agents, tools, policies, rules change via GitOps → rare changes
  - TTL ensures eventual consistency (max staleness = TTL seconds)
- **Phase 2**: Event-driven invalidation
  - POST/PUT/DELETE operations invalidate cache
  - Use ElastiCache Redis for distributed caching across ECS tasks

**Cache Metrics**:
```python
# Emit metrics for monitoring
metrics_publisher.put_metric(
    namespace="AgentManagementAPI",
    metric_name="CacheHitRate",
    value=cache_hits / (cache_hits + cache_misses),
    unit="Percent"
)
```

**Disabling Cache** (for testing):
```bash
# Set environment variable
export CACHE_ENABLED=false

# Or in docker-compose.yml
environment:
  - CACHE_ENABLED=false
```

---

## 6. Error Handling

### 6.1 Error Scenarios

| Scenario | HTTP Status | Response | Handling |
|----------|-------------|----------|----------|
| Agent not found | 404 | `{"error": "Agent not found"}` | Return error |
| DynamoDB failure | 500 | `{"error": "Internal error", "agents": []}` | Log error, return empty array |
| S3 failure | 500 | `{"error": "Failed to load rules", "rules": []}` | Log error, return empty array |
| Invalid query params | 400 | `{"error": "Invalid status value"}` | Return error with details |
| CloudWatch timeout | 200 | Return data with match_count=0 | Degrade gracefully |

### 6.2 Graceful Degradation

**Never block Dashboard on failures**:
- If DynamoDB fails → Return empty array + log error
- If CloudWatch fails → Return data with match counts as 0
- If S3 fails → Return empty rules array

---

## 7. Monitoring & Observability

### 7.1 Metrics

**CloudWatch Custom Metrics**:
- `AgentManagementAPI/GetAgents/Count` - Requests to GET /v1/agents
- `AgentManagementAPI/GetAgents/Latency` - Response time
- `AgentManagementAPI/GetPolicies/Count` - Requests to GET /v1/policies
- `AgentManagementAPI/GetSigmaRules/Count` - Requests to GET /v1/sigma-rules
- `AgentManagementAPI/CacheHitRate` - Cache hit/miss ratio

### 7.2 Logs

**Structured JSON Logs**:
```json
{
  "timestamp": "2025-01-21T10:45:30Z",
  "level": "INFO",
  "message": "Agent list requested",
  "endpoint": "/v1/agents",
  "response_time_ms": 45,
  "agents_count": 3,
  "cache_hit": true
}
```

### 7.3 Alarms

| Alarm | Metric | Threshold | Action |
|-------|--------|-----------|--------|
| **AgentAPI-HighLatency** | GET /v1/agents latency | > 1 second | SNS alert |
| **AgentAPI-Errors** | 5xx errors | > 5/min | SNS alert |
| **CacheMissRateHigh** | Cache miss rate | > 50% | Investigate cache TTL |

---

## 8. Cross-References

### 8.1 Related LLDs
- [LLD 01: CDK Infrastructure](./01-cdk-infrastructure.md) - DynamoDB tables deployment
- [LLD 03: Security Controller](./03-security-controller.md) - Existing APIs
- [LLD 04: Dashboard](./04-dashboard-v2.md) - Consumer of these APIs
- **[LLD 06: Data Model v2](./06-data-model-v2.md)** - **NEW - Complete table schemas and seed scripts**

### 8.2 Architecture Decision Records
- **ADR-013**: CloudWatch Logs for audit trail (provides match counts)
- **ADR-018**: Read-only config APIs for MVP (no runtime updates)

### 8.3 Workstreams
- **Workstream 3**: Security Controller implementation
- **Workstream 4**: Dashboard integration (Milestone 5+ depends on these APIs)

### 8.4 Prerequisites for Implementation

**BEFORE implementing Agent Management APIs, you MUST:**

1. ✅ **Deploy new DynamoDB tables** (see [LLD 06 Section 2](./06-data-model-v2.md#2-dynamodb-tables))
   - `sentra-agent-registry`
   - `sentra-tool-registry`
   - `sentra-sigma-rules-metadata`
   - Update CDK Stack with table definitions
   - Deploy via `cdk deploy Sentra-DEV-Storage-Stack`

2. ✅ **Run seed scripts** (see [LLD 06 Section 3](./06-data-model-v2.md#3-seed-scripts))
   ```bash
   # Option 1: Seed all tables at once
   python scripts/seed_all.py

   # Option 2: Seed individually
   python scripts/seed_agents.py
   python scripts/seed_tools.py
   python scripts/seed_sigma_rules_metadata.py  # Metadata + S3 upload
   python scripts/seed_policies.py  # Update existing
   ```

3. ✅ **Verify data in DynamoDB**
   ```bash
   # Check agent registry
   aws dynamodb scan --table-name sentra-agent-registry --profile sentra

   # Check tool registry
   aws dynamodb scan --table-name sentra-tool-registry --profile sentra

   # Check Sigma rules metadata
   aws dynamodb scan --table-name sentra-sigma-rules-metadata --profile sentra

   # Check S3 Sigma rule content
   aws s3 ls s3://sentra-mvp-artifacts/sigma_rules/llm/ --profile sentra
   ```

4. ✅ **Implement APIs** (this LLD)
   - Create service classes
   - Add routes
   - Write unit tests
   - Test with curl/Postman

5. ✅ **Update Dashboard** (see Workstream 4, Milestone 5)
   - Use new SecurityControllerClient methods
   - Replace mock data with real API calls

---

## Appendix A: API Summary Table

| Endpoint | Method | Purpose | DynamoDB | S3 | CloudWatch |
|----------|--------|---------|----------|----|-----------|
| `/v1/agents` | GET | List agents | ✅ sentra-agent-registry | ❌ | ✅ Match counts |
| `/v1/agents/{id}` | GET | Get agent details | ✅ sentra-agent-registry | ❌ | ✅ Stats |
| `/v1/agents/{id}/tools` | GET | Get allowed tools | ✅ sentra-policies + sentra-tool-registry | ❌ | ❌ |
| `/v1/policies` | GET | Query policies | ✅ sentra-policies | ❌ | ✅ Match counts |
| `/v1/sigma-rules` | GET | List Sigma rules | ✅ sentra-sigma-rules-metadata | ✅ sigma_rules/ (on-demand) | ✅ Match counts |

---

## Appendix B: Migration from Mock Data

**Dashboard changes required**:

1. **Milestone 5 (Agents Tab API Integration)**:
   - Replace `agent_list._get_mock_agents()` with `security_controller_client.get_agents()`
   - Replace `agent_tools._get_mock_tools()` with `security_controller_client.get_agent_tools(agent_id)`
   - Replace `agent_policies._get_mock_policies()` with `security_controller_client.get_policies(agent_id=agent_id)`

2. **Milestone 9 (Security Tab)**:
   - Replace Sigma rules mock data with `security_controller_client.get_sigma_rules()`

**No breaking changes** - APIs are new additions, not replacements.

---

**End of LLD 05: Agent Management APIs - v1.0**
