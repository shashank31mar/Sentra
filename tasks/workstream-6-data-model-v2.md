# Workstream 6: Data Model v2 - Agent, Tool, and Sigma Rule Registries

**Component**: Data Model v2 (LLD 06)
**Timeline**: Week 4 (6-8 days)
**Owner**: Infrastructure + Backend Team
**Prerequisites**: Workstream 1 (Infrastructure - Storage Stack) completed

---

## AWS Configuration

**Critical**: All tasks must use these AWS settings:

- **AWS Account ID**: `531109575379`
- **AWS Profile**: `sentra` (credentials configured in `~/.aws/credentials`)
- **Region**: `us-east-1` (IAD - Northern Virginia)

**Environment Setup**:
```bash
# Verify AWS profile configuration
export AWS_PROFILE=sentra
aws sts get-caller-identity  # Should show account 531109575379

# Verify region
export AWS_REGION=us-east-1
aws configure get region --profile sentra  # Should return us-east-1
```

---

## Overview

This workstream creates **4 new DynamoDB tables** and associated seed scripts to replace hardcoded data with a scalable, queryable registry system.

**Key Principle**: Hybrid storage pattern - DynamoDB for metadata (fast queries) + S3 for content (no size limits, versioning).

**New Tables**:
1. `sentra-agent-registry` - Agent metadata (3-5 agents)
2. `sentra-tool-registry` - Tool definitions (15-20 tools)
3. `sentra-policies-metadata` - Policy metadata (content in S3)
4. `sentra-sigma-rules-metadata` - Sigma rule metadata (content in S3)

**Cost**: ~$0.50/month additional (DynamoDB + S3)

---

## Project Structure

All scripts go in:
```
scripts/
├── seed_agents.py              # Task 5
├── seed_tools.py               # Task 6
├── seed_policies_metadata.py   # Task 7 (+ S3 upload)
├── seed_sigma_rules_metadata.py # Task 8 (+ S3 upload)
├── seed_all.py                 # Task 9 (master script)
├── verify_data_model.py        # Task 12 (verification)
└── schemas/
    ├── agent_schema.py         # Task 10 (Pydantic models)
    ├── tool_schema.py          # Task 10
    ├── policy_schema.py        # Task 10
    └── sigma_rule_schema.py    # Task 10

cdk/stacks/
├── storage_stack.py            # Update with new table definitions

sample-artifacts/
├── policies/
│   └── agents/                 # Task 7 (policy YAML files)
│       ├── customer-query-agent/
│       │   └── v1.0.0.yaml
│       └── payment-agent/
│           └── v1.0.0.yaml
└── sigma_rules/llm/            # Task 8 (already exists, need metadata)
```

---

## Milestone 1: DynamoDB Table Creation (Days 1-2)

### Task 1: Update CDK Storage Stack - Agent Registry Table ✅ COMPLETE

- Open `cdk/stacks/storage_stack.py`
- Add `sentra-agent-registry` table definition with schema from LLD 06 Section 2.1
- Configure partition key: `agent_id` (STRING)
- Add GSI: `status-index` (partition: status)
- Set billing mode: ON_DEMAND
- Enable point-in-time recovery: True
- Set removal policy: RETAIN (for production safety)
- Export table name and ARN as CloudFormation outputs
- **CDK Code**:
  ```python
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

  agent_registry_table.add_global_secondary_index(
      index_name="status-index",
      partition_key=dynamodb.Attribute(
          name="status",
          type=dynamodb.AttributeType.STRING
      ),
      projection_type=dynamodb.ProjectionType.ALL
  )
  ```
- Test: `cdk synth Sentra-DEV-Storage-Stack --profile sentra > /tmp/storage_synth_agent_table.txt`
- Test: Verify table definition in synth output
- Deploy: `cdk deploy Sentra-DEV-Storage-Stack --profile sentra`
- Verify: Table created in DynamoDB console with status-index GSI
- _Requirements: LLD 06 Section 2.1_

---

### Task 2: Update CDK Storage Stack - Tool Registry Table ✅ COMPLETE

- Add `sentra-tool-registry` table definition to `storage_stack.py`
- Configure partition key: `tool_id` (STRING)
- Add GSI: `type-index` (partition: tool_type - READ/WRITE)
- Set billing mode: ON_DEMAND
- Enable point-in-time recovery: True
- Set removal policy: RETAIN
- Export table name and ARN as CloudFormation outputs
- **CDK Code**:
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

  tool_registry_table.add_global_secondary_index(
      index_name="type-index",
      partition_key=dynamodb.Attribute(
          name="tool_type",
          type=dynamodb.AttributeType.STRING
      ),
      projection_type=dynamodb.ProjectionType.ALL
  )
  ```
- Test: `cdk synth Sentra-DEV-Storage-Stack --profile sentra > /tmp/storage_synth_tool_table.txt`
- Deploy: `cdk deploy Sentra-DEV-Storage-Stack --profile sentra`
- Verify: Table created with type-index GSI
- _Requirements: LLD 06 Section 2.2_

---

### Task 3: Update CDK Storage Stack - Policies Metadata Table ✅ COMPLETE

- Add `sentra-policies-metadata` table definition (metadata only, content in S3)
- Configure partition key: `policy_id` (STRING)
- Add GSI: `agent-index` (partition: agent_id)
- Add GSI: `status-index` (partition: status)
- Set billing mode: ON_DEMAND
- Enable point-in-time recovery: True
- Set removal policy: RETAIN
- Export table name and ARN as CloudFormation outputs
- **CDK Code**:
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

  policies_metadata_table.add_global_secondary_index(
      index_name="agent-index",
      partition_key=dynamodb.Attribute(
          name="agent_id",
          type=dynamodb.AttributeType.STRING
      ),
      projection_type=dynamodb.ProjectionType.ALL
  )

  policies_metadata_table.add_global_secondary_index(
      index_name="status-index",
      partition_key=dynamodb.Attribute(
          name="status",
          type=dynamodb.AttributeType.STRING
      ),
      projection_type=dynamodb.ProjectionType.ALL
  )
  ```
- Test: `cdk synth Sentra-DEV-Storage-Stack --profile sentra > /tmp/storage_synth_policies_meta.txt`
- Deploy: `cdk deploy Sentra-DEV-Storage-Stack --profile sentra`
- Verify: Table created with 2 GSIs (agent-index, status-index)
- _Requirements: LLD 06 Section 2.3_

---

### Task 4: Update CDK Storage Stack - Sigma Rules Metadata Table ✅ COMPLETE

- Add `sentra-sigma-rules-metadata` table definition (metadata only, content in S3)
- Configure partition key: `rule_id` (STRING)
- Add GSI: `level-index` (partition: level - critical/high/medium/low)
- Add GSI: `status-index` (partition: status - stable/experimental/deprecated)
- Set billing mode: ON_DEMAND
- Enable point-in-time recovery: True
- Set removal policy: RETAIN
- Export table name and ARN as CloudFormation outputs
- **CDK Code**:
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

  sigma_rules_metadata_table.add_global_secondary_index(
      index_name="level-index",
      partition_key=dynamodb.Attribute(
          name="level",
          type=dynamodb.AttributeType.STRING
      ),
      projection_type=dynamodb.ProjectionType.ALL
  )

  sigma_rules_metadata_table.add_global_secondary_index(
      index_name="status-index",
      partition_key=dynamodb.Attribute(
          name="status",
          type=dynamodb.AttributeType.STRING
      ),
      projection_type=dynamodb.ProjectionType.ALL
  )
  ```
- Test: `cdk synth Sentra-DEV-Storage-Stack --profile sentra > /tmp/storage_synth_sigma_meta.txt`
- Deploy: `cdk deploy Sentra-DEV-Storage-Stack --profile sentra`
- Verify: Table created with 2 GSIs (level-index, status-index)
- _Requirements: LLD 06 Section 2.4_

**DEMO CHECKPOINT 1**: ✅ COMPLETE - All 4 new DynamoDB tables deployed and visible in AWS Console. Can query tables (empty) and verify GSI structures. Tables: sentra-agent-registry, sentra-tool-registry, sentra-policies-metadata, sentra-sigma-rules-metadata.

---

## Milestone 2: Seed Scripts and Data Population (Days 3-5)

### Task 5: Create Agent Seed Script ✅ COMPLETE

- Create `scripts/seed_agents.py` with seed data from LLD 06 Section 2.1
- Implement function `seed_agents()` that writes 2 agents:
  - customer-query-agent
  - payment-agent
- Each agent item includes: agent_id, name, description, type, status, version, ecs_config, runtime_config, created_at, created_by, tags
- Use `boto3.resource('dynamodb').Table('sentra-agent-registry').put_item()`
- Add `--dry-run` flag to preview changes without writing
- Add `--force` flag to overwrite existing items
- Add timestamp generation: `datetime.utcnow().isoformat() + "Z"`
- **Error Handling**: Wrap DynamoDB operations in try-except, log errors
- Test: Run with `--dry-run` flag, verify output shows 3 agents
- Test: Run without flags, verify 3 agents written to DynamoDB
- Verify: Query table using AWS CLI: `aws dynamodb scan --table-name sentra-agent-registry --profile sentra`
- _Requirements: LLD 06 Section 2.1, 3.1_

---

### Task 6: Create Tool Seed Script ✅ COMPLETE

- Create `scripts/seed_tools.py` with seed data from LLD 06 Section 2.2
- Implement function `seed_tools()` that writes 15-20 tools
- Include READ tools: query_customers, query_orders, query_with_limit, check_order
- Include WRITE tools: process_refund, reverse_refund
- Each tool item includes: tool_id, name, description, tool_type, category, status, version, parameters (with validation), rate_limit, execution_config, created_at, created_by, tags
- Add `--dry-run` and `--force` flags
- **Error Handling**: Wrap DynamoDB operations in try-except, log errors
- Test: Run with `--dry-run` flag, verify output shows all tools
- Test: Run without flags, verify tools written to DynamoDB
- Test: Query by tool_type using GSI: `aws dynamodb query --table-name sentra-tool-registry --index-name type-index --key-condition-expression "tool_type = :type" --expression-attribute-values '{":type":{"S":"READ"}}' --profile sentra`
- Verify: Count READ tools (should be ~10-12) and WRITE tools (should be ~5-8)
- _Requirements: LLD 06 Section 2.2, 3.2_

---

### Task 7: Create Policy Metadata Seed Script with S3 Upload ✅ COMPLETE

**Part A: Create Policy YAML Files in S3**
- Create directory structure: `sample-artifacts/policies/agents/`
- Create `customer-query-agent/v1.0.0.yaml` with policy content from LLD 06 Section 2.3
- Include: allowed_tools, policies (pol-001, pol-002, pol-003)
- Create `payment-agent/v1.0.0.yaml` with similar structure
- Format: YAML with schema_version, policy_id, agent_id, version, allowed_tools, policies, created_at, created_by
- Upload to S3:
  ```bash
  aws s3 cp sample-artifacts/policies/ \
    s3://sentra-mvp-artifacts/policies/ \
    --recursive \
    --region us-east-1 \
    --profile sentra
  ```

**Part B: Create Seed Script for Metadata**
- Create `scripts/seed_policies_metadata.py`
- Implement function `seed_policies_metadata()` that writes metadata items only
- Each metadata item includes: policy_id, agent_id, name, version, status, s3_bucket, s3_key, s3_version_id (optional), allowed_tools_count, policies_count, severity_breakdown, content_hash, schema_version, created_at, created_by
- Calculate content_hash: `hashlib.sha256(yaml_content.encode()).hexdigest()`
- Get S3 version_id: Use `boto3.client('s3').head_object()` to retrieve version ID
- Add `--dry-run` and `--force` flags
- **Error Handling**: Verify S3 files exist before writing metadata, raise error if missing
- Test: Run with `--dry-run` flag
- Test: Run without flags, verify metadata written
- Test: Verify S3 files accessible: `aws s3 cp s3://sentra-mvp-artifacts/policies/agents/customer-query-agent/v1.0.0.yaml - --profile sentra`
- Verify: Query metadata by agent_id using GSI
- _Requirements: LLD 06 Section 2.3, 3.3_

---

### Task 8: Create Sigma Rules Metadata Seed Script ✅ COMPLETE

**Part A: Prepare Sigma Rules in S3**
- Verify existing Sigma rules in S3: `aws s3 ls s3://sentra-mvp-artifacts/sigma_rules/llm/ --profile sentra`
- If missing, create sample rules:
  - `prompt_injection_basic.yaml` (already exists from Workstream 1)
  - `jailbreak_attempts.yaml`
  - `data_exfiltration.yaml`
- Upload to S3 if needed:
  ```bash
  aws s3 cp sample-artifacts/sigma_rules/ \
    s3://sentra-mvp-artifacts/sigma_rules/ \
    --recursive \
    --region us-east-1 \
    --profile sentra
  ```

**Part B: Create Seed Script for Metadata**
- Create `scripts/seed_sigma_rules_metadata.py`
- Implement function `seed_sigma_rules_metadata()` that writes metadata items
- Each metadata item includes: rule_id, title, description, status, level, version, s3_bucket, s3_key, s3_version_id, patterns_count, tags, stats (match_count_24h, match_count_7d, last_matched), content_hash, schema_version, created_at, created_by, author
- Parse S3 YAML files to extract patterns_count and tags
- Initialize stats with zeros: `{"match_count_24h": 0, "match_count_7d": 0, "last_matched": None}`
- Add `--dry-run` and `--force` flags
- **Error Handling**: Verify S3 files exist, handle YAML parsing errors
- Test: Run with `--dry-run` flag
- Test: Run without flags, verify metadata written
- Test: Query by level using GSI: `aws dynamodb query --table-name sentra-sigma-rules-metadata --index-name level-index --key-condition-expression "level = :level" --expression-attribute-values '{":level":{"S":"high"}}' --profile sentra`
- Verify: All high-level rules returned
- _Requirements: LLD 06 Section 2.4, 3.3_

---

### Task 9: Create Master Seed Script ✅ COMPLETE

- Create `scripts/seed_all.py` that orchestrates all seed scripts
- Import: `from seed_agents import seed_agents`, `from seed_tools import seed_tools`, etc.
- Implement `main()` function that calls all seed functions in order:
  1. seed_agents()
  2. seed_tools()
  3. seed_sigma_rules_metadata()
  4. seed_policies_metadata()
  5. Update existing sentra-policies table (from Workstream 3) with new allowed_tools format (tool IDs instead of full objects)
- Add banner output with progress indicators
- Add `--dry-run` flag that passes to all sub-scripts
- **Error Handling**: If any seed fails, log error and continue (don't fail entire script)
- **Verification Step**: After seeding, count items in each table and report summary
- Test: Run with `--dry-run` flag, verify all scripts execute
- Test: Run without flags on clean tables, verify all tables populated
- Verify: Run verification queries for all 4 tables
- _Requirements: LLD 06 Section 3_

**DEMO CHECKPOINT 2**: ✅ COMPLETE - All 4 new tables seeded with data. Can query agents (3), tools (15-20), policy metadata (3-5), Sigma rule metadata (15-20). S3 contains policy YAML files and Sigma rule YAML files. Can demonstrate querying by agent_id, tool_type, level, status using GSIs.

---

## Milestone 3: Pydantic Models and Query Patterns (Days 6-7)

### Task 10: Create Pydantic Validation Models ✅ COMPLETE

- Create `scripts/schemas/` directory
- Create `agent_schema.py` with Pydantic models:
  - `EcsConfig` - BaseModel with service_name, container_port, desired_count
  - `RuntimeConfig` - BaseModel with max_sessions, session_timeout_minutes, default_trust_score
  - `Agent` - BaseModel with all fields from table schema
- Create `tool_schema.py` with Pydantic models:
  - `ParameterSchema` - BaseModel for parameter definitions
  - `RateLimit` - BaseModel with requests_per_minute, burst_limit
  - `ExecutionConfig` - BaseModel with timeout_seconds, retry_attempts, idempotent
  - `Tool` - BaseModel with all fields
- Create `policy_schema.py` with Pydantic models:
  - `PolicyRule` - Individual policy rule
  - `AgentPolicyDocument` - Full policy document from S3
  - `PolicyMetadata` - Metadata-only (DynamoDB item)
- Create `sigma_rule_schema.py` with Pydantic models:
  - `SigmaRuleDetection` - Detection patterns
  - `SigmaRuleDocument` - Full rule from S3
  - `SigmaRuleMetadata` - Metadata-only (DynamoDB item)
- Add validation: Field constraints, datetime parsing, enum values
- Test: Create test script that loads DynamoDB items and validates with Pydantic
- Test: Verify validation catches schema violations
- _Requirements: LLD 06 Section 2, LLD 05 Section 4_

---

### Task 11: Implement Query Helper Functions ✅ COMPLETE

- Create `scripts/query_helpers.py` with reusable query functions
- Implement `get_agent_by_id(agent_id: str) -> Agent`
  - Query: `GetItem` on sentra-agent-registry
  - Validate with Pydantic Agent model
  - Return Agent object or raise AgentNotFoundError
- Implement `list_agents(status: Optional[str] = None) -> List[Agent]`
  - Query: Scan or Query status-index GSI
  - Validate and return list of Agent objects
- Implement `get_tool_by_id(tool_id: str) -> Tool`
  - Query: `GetItem` on sentra-tool-registry
  - Validate with Pydantic Tool model
- Implement `list_tools_by_type(tool_type: str) -> List[Tool]`
  - Query: Query type-index GSI with tool_type
  - Return list of Tool objects
- Implement `get_policy_metadata(policy_id: str) -> PolicyMetadata`
  - Query: `GetItem` on sentra-policies-metadata
- Implement `get_policy_full(policy_id: str) -> AgentPolicyDocument`
  - Step 1: Get metadata from DynamoDB
  - Step 2: Download YAML from S3 using s3_key
  - Step 3: Parse YAML and validate with Pydantic
  - Return AgentPolicyDocument
- Implement `get_sigma_rule_metadata(rule_id: str) -> SigmaRuleMetadata`
- Implement `get_sigma_rule_full(rule_id: str) -> SigmaRuleDocument`
  - Similar to policy: metadata from DynamoDB + content from S3
- Implement `list_sigma_rules_by_level(level: str) -> List[SigmaRuleMetadata]`
  - Query: Query level-index GSI
- **Error Handling**: All functions wrap in try-except, raise custom exceptions
- Test: Create unit tests for all query functions using moto (mock DynamoDB/S3)
- Test: Run integration tests against real AWS resources
- _Requirements: LLD 06 Section 4_

---

### Task 12: Create Verification and Testing Scripts ✅ COMPLETE

- Create `scripts/verify_data_model.py` to verify all tables and data
- Implement verification checks:
  1. Verify all 4 tables exist
  2. Verify all GSIs exist
  3. Verify item counts match expected (3 agents, 15-20 tools, etc.)
  4. Verify S3 files exist for all policy and Sigma rule metadata items
  5. Verify data integrity (all agent_ids in policies table exist in agent-registry)
  6. Verify Pydantic validation passes for all items
  7. Verify query patterns work (query by agent_id, tool_type, level, status)
- Generate report with pass/fail for each check
- Output report to `/tmp/data_model_verification_report.txt`
- **Error Handling**: Continue checking even if one check fails, report all failures
- Test: Run verification script after seeding
- Verify: All checks pass
- _Requirements: LLD 06 All Sections_

**DEMO CHECKPOINT 3**: ✅ COMPLETE - Complete data model deployed and verified. Can query all tables with filters using helper functions. Pydantic models validate all data. S3 content accessible. Verification script confirms data integrity (26/26 checks passed). Ready for integration with Security Controller and Dashboard.

---

## Milestone 4: Integration and Documentation (Day 8)

### Task 13: Integration Testing with Security Controller APIs

**Purpose**: Verify new tables integrate with LLD 05 Agent Management APIs

**Prerequisites**: Workstream 5 (Agent Management APIs) must be implemented first

**Integration Tests**:
- Test: GET /v1/agents returns agents from sentra-agent-registry
- Test: GET /v1/agents/{id} returns agent with runtime stats
- Test: GET /v1/agents/{id}/tools returns tools from sentra-tool-registry (joining with sentra-policies)
- Test: GET /v1/policies returns policies from sentra-policies-metadata
- Test: GET /v1/sigma-rules returns Sigma rules from sentra-sigma-rules-metadata
- Test: Verify API response schemas match LLD 05 specifications
- Test: Verify caching works (5-minute TTL for tool registry, 10-minute TTL for Sigma rules)
- Test: Verify S3 content is loaded correctly when full policy/rule requested
- **Error Scenarios**:
  - Test: API handles missing agent_id gracefully (404)
  - Test: API handles S3 failures (returns metadata only or cached data)
  - Test: API handles DynamoDB throttling (retry logic)
- **Performance Tests**:
  - Measure API latency for GET /v1/agents (should be < 100ms)
  - Measure API latency for GET /v1/agents/{id}/tools (should be < 150ms with tool registry join)
  - Measure cache effectiveness (hit rate > 95% after warm-up)
- Document results in `/tmp/data_model_integration_test_results.txt`
- _Requirements: LLD 05 Section 3, LLD 06 Section 4_

---

### Task 14: Performance and Load Testing

- Create `scripts/performance_test.py` to test query performance
- Test 1: Query latency for each table (GetItem, Scan, GSI Query)
  - Measure: p50, p95, p99 latency
  - Target: < 10ms for GetItem, < 50ms for GSI Query, < 100ms for Scan
- Test 2: Concurrent query load (10 concurrent workers, 1000 queries each)
  - Verify: No throttling errors
  - Verify: Consistent latency under load
- Test 3: Cache effectiveness
  - Measure: S3 fetch count vs API request count
  - Target: S3 fetch rate < 5% after cache warm-up
- Test 4: S3 download performance
  - Measure: Time to download policy YAML (should be < 50ms)
  - Measure: Time to parse YAML with Pydantic (should be < 5ms)
- Test 5: GSI query performance by different keys
  - Query agents by status
  - Query tools by tool_type
  - Query Sigma rules by level
  - Target: All queries < 50ms
- Generate performance report with all metrics
- Write report to `/tmp/data_model_performance_report.txt`
- _Requirements: LLD 06 Section 4_

---

### Task 15: Documentation and Migration Guide

**Part A: Create Data Model Documentation**
- Create `docs/data-model-v2.md` with:
  - Architecture overview (hybrid storage pattern)
  - Table schemas (all 4 tables with field descriptions)
  - GSI usage patterns (when to use each GSI)
  - Query patterns (examples for each access pattern)
  - Pydantic model reference
  - S3 content structure (YAML format examples)

**Part B: Create Operations Guide**
- Create `docs/data-model-operations.md` with:
  - How to seed tables (run seed_all.py)
  - How to add new agents (manual DynamoDB put + update seed script)
  - How to add new tools (manual DynamoDB put + update seed script)
  - How to update policies (upload new YAML to S3 + update metadata)
  - How to update Sigma rules (upload new YAML to S3 + update metadata)
  - How to verify data integrity (run verify_data_model.py)
  - How to backup and restore tables (DynamoDB export/import)

**Part C: Create Migration Guide**
- Create `docs/data-model-v1-to-v2-migration.md` with:
  - What changed from v1 (hardcoded → DynamoDB)
  - Migration steps (deploy tables → run seed scripts → update APIs)
  - Rollback plan (if migration fails)
  - Verification checklist (all queries work, no data loss)

**Part D: Update README**
- Add Data Model v2 section to main README
- Link to LLD 06 and documentation files

- _Requirements: LLD 06 All Sections_

---

### Task 16: Cost Analysis and Monitoring Setup

**Part A: Cost Analysis**
- Calculate actual costs after deployment:
  - DynamoDB: Storage costs (query using AWS CLI: `aws dynamodb describe-table`)
  - DynamoDB: Read/write request costs (check CloudWatch metrics)
  - S3: Storage costs (query using AWS CLI: `aws s3 ls --summarize`)
  - S3: Request costs (check CloudWatch metrics)
- Document in `/tmp/data_model_costs_actual.txt`
- Compare with LLD 06 Section 6 estimates (~$0.50/month)

**Part B: Monitoring Setup**
- Create CloudWatch dashboard: `Sentra-DataModel-Dashboard`
- Add widgets:
  - Widget 1: DynamoDB read/write capacity units (all 4 tables)
  - Widget 2: DynamoDB throttled requests (alarm if > 0)
  - Widget 3: S3 GET request count (policies + Sigma rules)
  - Widget 4: Query latency by table (custom metrics from helper functions)
- Create CloudWatch Alarms:
  - Alarm 1: DynamoDB throttling (threshold: > 5 throttles/min)
  - Alarm 2: High read latency (threshold: p95 > 100ms)
  - Alarm 3: S3 errors (threshold: > 5 errors/min)
- Test: View dashboard in CloudWatch console
- Verify: Metrics appear correctly
- _Requirements: LLD 06 Section 6_

**DEMO CHECKPOINT 4 (FINAL)**: Complete data model deployed, seeded, integrated, tested, and documented. All 4 tables operational with data. S3 hybrid storage working. Query helper functions tested. Integration with Security Controller APIs verified. Performance meets targets. Documentation complete.

---

## Dependencies and Parallel Work

**Prerequisites**:
- Workstream 1 (Infrastructure - Storage Stack) must be completed
- S3 bucket `sentra-mvp-artifacts` must exist
- Existing tables (`sentra-session-context`, `sentra-policies`, `sentra-demo-orders`) must exist

**Can Run in Parallel**:
- Tasks 5-8 (all seed scripts can be developed independently)
- Task 10-11 (Pydantic models + query helpers can be developed concurrently)

**Must Run Sequentially**:
- Tasks 1-4 must complete before Task 5 (tables must exist before seeding)
- Task 9 depends on Tasks 5-8 (master script calls individual seed scripts)
- Task 12 depends on Tasks 5-11 (verification requires data and query functions)
- Task 13 depends on Workstream 5 (LLD 05 APIs must be implemented)
- Tasks 13-16 can run in parallel after data seeded

**Integration with Other Workstreams**:
- Workstream 5 (Agent Management APIs - LLD 05): Will consume these tables via query patterns from Task 11
- Workstream 4 (Dashboard): Will use APIs from Workstream 5, which read from these tables
- Workstream 3 (Security Controller): Will migrate from hardcoded policies to sentra-policies-metadata table

---

## Estimated Timeline

| Task | Duration | Cumulative |
|------|----------|------------|
| **Milestone 1: DynamoDB Tables** | | |
| Task 1 | 0.5 day | Day 0.5 |
| Task 2 | 0.5 day | Day 1 |
| Task 3 | 0.5 day | Day 1.5 |
| Task 4 | 0.5 day | Day 2 |
| **Checkpoint 1** | - | Day 2 |
| **Milestone 2: Seed Scripts** | | |
| Task 5 | 0.5 day | Day 2.5 |
| Task 6 | 0.5 day | Day 3 |
| Task 7 | 1 day | Day 4 |
| Task 8 | 1 day | Day 5 |
| Task 9 | 0.5 day | Day 5.5 |
| **Checkpoint 2** | - | Day 5.5 |
| **Milestone 3: Models & Queries** | | |
| Task 10 | 1 day | Day 6.5 |
| Task 11 | 1 day | Day 7.5 |
| Task 12 | 0.5 day | Day 8 |
| **Checkpoint 3** | - | Day 8 |
| **Milestone 4: Integration** | | |
| Task 13 | 1 day | Day 9 |
| Task 14 | 0.5 day | Day 9.5 |
| Task 15 | 0.5 day | Day 10 |
| Task 16 | 0.5 day | Day 10.5 |
| **Checkpoint 4 (Final)** | - | Day 10.5 |

**Total: ~10.5 days (≈2 weeks)**

**Notes**:
- Tasks 1-4 are quick CDK updates (~30 min each)
- Tasks 5-8 are seed script development (~1-2 hours each, but Task 7-8 require S3 setup)
- Task 13 requires Workstream 5 (LLD 05) to be implemented first
- Can be completed in parallel with Dashboard development (Workstream 4)

---

## Post-Deployment Verification Checklist

After Task 16, run these verification steps:

```bash
# Set environment
export AWS_PROFILE=sentra
export AWS_REGION=us-east-1

# 1. Verify all 4 tables exist
aws dynamodb list-tables --region us-east-1 | grep sentra

# Expected output:
#   sentra-agent-registry
#   sentra-tool-registry
#   sentra-policies-metadata
#   sentra-sigma-rules-metadata

# 2. Verify table item counts
aws dynamodb scan --table-name sentra-agent-registry --select COUNT --profile sentra
# Expected: Count: 3

aws dynamodb scan --table-name sentra-tool-registry --select COUNT --profile sentra
# Expected: Count: 15-20

aws dynamodb scan --table-name sentra-policies-metadata --select COUNT --profile sentra
# Expected: Count: 3-5

aws dynamodb scan --table-name sentra-sigma-rules-metadata --select COUNT --profile sentra
# Expected: Count: 15-20

# 3. Test GSI queries
aws dynamodb query --table-name sentra-agent-registry \
  --index-name status-index \
  --key-condition-expression "status = :status" \
  --expression-attribute-values '{":status":{"S":"active"}}' \
  --profile sentra

aws dynamodb query --table-name sentra-tool-registry \
  --index-name type-index \
  --key-condition-expression "tool_type = :type" \
  --expression-attribute-values '{":type":{"S":"READ"}}' \
  --profile sentra

# 4. Verify S3 content exists
aws s3 ls s3://sentra-mvp-artifacts/policies/agents/ --recursive --profile sentra
# Expected: customer-query-agent/v1.0.0.yaml, payment-agent/v1.0.0.yaml

aws s3 ls s3://sentra-mvp-artifacts/sigma_rules/llm/ --profile sentra
# Expected: 15-20 YAML files

# 5. Test query helper functions
python scripts/test_query_helpers.py
# Should print: All query tests passed

# 6. Run verification script
python scripts/verify_data_model.py
# Should output: ✅ All checks passed (report in /tmp/data_model_verification_report.txt)

# 7. Check costs
aws cloudwatch get-metric-statistics \
  --namespace AWS/DynamoDB \
  --metric-name ConsumedReadCapacityUnits \
  --dimensions Name=TableName,Value=sentra-agent-registry \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 3600 \
  --statistics Sum \
  --region us-east-1 \
  --profile sentra
```

---

## Rollback Plan

If deployment or data model migration fails:

1. **CDK Rollback** (if table creation fails):
   ```bash
   cdk deploy Sentra-DEV-Storage-Stack --rollback --profile sentra
   ```

2. **Data Rollback** (if seed scripts corrupt data):
   - Tables have PITR enabled, can restore from backup
   - Or delete tables and recreate:
     ```bash
     aws dynamodb delete-table --table-name sentra-agent-registry --profile sentra
     # Repeat for other 3 tables
     cdk deploy Sentra-DEV-Storage-Stack --profile sentra
     python scripts/seed_all.py
     ```

3. **API Rollback** (if integration breaks):
   - Security Controller APIs (LLD 05) can fall back to reading from `sentra-policies` table
   - No breaking changes to existing tables

---

**Next Workstream**: Agent Management APIs Implementation (LLD 05) - Should be done in parallel or after this workstream

**Integration Point**: Security Controller (Workstream 3) and Dashboard (Workstream 4) will read from these tables via APIs defined in LLD 05
