# Update Artifact Script

Unified script for updating Policies and Sigma Rules in S3 + DynamoDB.

## Overview

The `update_artifact.py` script provides a single interface for updating both:
- **Agent Policies** - Authorization rules for AI agents
- **Sigma Rules** - Threat detection patterns

## Features

✅ Schema validation (Pydantic-based)  
✅ S3 upload with versioning  
✅ DynamoDB metadata sync  
✅ Dry-run mode for testing  
✅ Atomic updates (rollback on failure)  
✅ Auto-discovery of S3 bucket from CloudFormation  

## Usage

### Update a Sigma Rule

```bash
# Update SQL injection rule
python scripts/update_artifact.py \
  --usecase sigma \
  --file sample-artifacts/sigma_rules/llm/sql_injection.yaml

# Dry-run (validate only)
python scripts/update_artifact.py \
  --usecase sigma \
  --file sample-artifacts/sigma_rules/llm/sql_injection.yaml \
  --dry-run
```

### Update a Policy

```bash
# Update payment agent policy
python scripts/update_artifact.py \
  --usecase policy \
  --file sample-artifacts/policies/agents/payment-agent/v1.0.0.yaml

# Dry-run (validate only)
python scripts/update_artifact.py \
  --usecase policy \
  --file sample-artifacts/policies/agents/payment-agent/v1.0.0.yaml \
  --dry-run
```

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `--usecase` | Yes | Type of artifact: `policy` or `sigma` |
| `--file` | Yes | Path to YAML file |
| `--dry-run` | No | Validate only, don't update S3/DynamoDB |
| `--bucket` | No | Override S3 bucket (auto-discovered by default) |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AWS_PROFILE` | `sentra` | AWS profile to use |
| `AWS_REGION` | `us-east-1` | AWS region |
| `POLICIES_METADATA_TABLE` | `sentra-policies-metadata` | DynamoDB table for policies |
| `SIGMA_RULES_METADATA_TABLE` | `sentra-sigma-rules-metadata` | DynamoDB table for Sigma rules |
| `ARTIFACTS_BUCKET` | Auto-discovered | S3 bucket for artifacts |

## Validation

### Policy Schema Validation

Required fields:
- `schema_version`
- `policy_id`
- `agent_id`
- `name`
- `version`
- `status` (must be: `active`, `inactive`, or `draft`)
- `allowed_tools` (non-empty list)
- `policies` (list)

### Sigma Rule Schema Validation

Uses Pydantic model (`SigmaRuleDocument`) to validate:
- `title`
- `id`
- `status` (must be: `stable`, `experimental`, `deprecated`, or `disabled`)
- `description`
- `detection` (with patterns and condition)
- `level` (must be: `critical`, `high`, `medium`, or `low`)
- `tags`
- `author`

## What Gets Updated

### For Policies

**S3:**
- Path: `policies/agents/{agent_id}/v{version}.yaml`
- Versioning enabled
- Metadata: policy_id, agent_id, version, uploaded_at

**DynamoDB (sentra-policies-metadata):**
- `policy_id` (primary key)
- `allowed_tools_count`
- `policies_count`
- `severity_breakdown`
- `content_hash` (SHA256)
- `s3_bucket`, `s3_key`, `s3_version_id`
- `status`, `version`, `agent_id`, `name`
- `updated_at` timestamp

### For Sigma Rules

**S3:**
- Path: `sigma_rules/llm/{rule_id}.yaml`
- Versioning enabled
- Metadata: rule_id, title, level, uploaded_at

**DynamoDB (sentra-sigma-rules-metadata):**
- `rule_id` (primary key)
- `title`, `description`
- `status`, `level`
- `patterns_count`
- `tags`
- `content_hash` (SHA256)
- `s3_bucket`, `s3_key`, `s3_version_id`
- `stats` (match counts - preserved on update)
- `updated_at` timestamp

## Examples

### Example 1: Update SQL Injection Rule After Adding Patterns

```bash
# 1. Edit the rule
vim sample-artifacts/sigma_rules/llm/sql_injection.yaml

# 2. Validate changes
python scripts/update_artifact.py \
  --usecase sigma \
  --file sample-artifacts/sigma_rules/llm/sql_injection.yaml \
  --dry-run

# 3. Apply changes
python scripts/update_artifact.py \
  --usecase sigma \
  --file sample-artifacts/sigma_rules/llm/sql_injection.yaml
```

### Example 2: Update Policy to Add New Tool

```bash
# 1. Edit the policy
vim sample-artifacts/policies/agents/payment-agent/v1.0.0.yaml

# 2. Validate changes
python scripts/update_artifact.py \
  --usecase policy \
  --file sample-artifacts/policies/agents/payment-agent/v1.0.0.yaml \
  --dry-run

# 3. Apply changes
python scripts/update_artifact.py \
  --usecase policy \
  --file sample-artifacts/policies/agents/payment-agent/v1.0.0.yaml
```

## Cache Invalidation

After updating a Sigma rule or policy:

**Security Controller:**
- Sigma rules cache: 5 minutes (automatic refresh)
- Policy cache: 5 minutes (automatic refresh)

**Dashboard:**
- Metrics cache: 5 seconds
- Sigma rules cache: 5 seconds
- Policies cache: 5 seconds

To force immediate refresh:
- Restart Security Controller service, OR
- Wait for cache TTL to expire

## Troubleshooting

### Error: "File not found"
- Check the file path is correct
- Use relative path from Sentra/ directory

### Error: "Validation failed"
- Check YAML syntax
- Ensure all required fields are present
- Verify field types match schema

### Error: "Failed to discover artifacts bucket"
- Set `ARTIFACTS_BUCKET` environment variable, OR
- Ensure CloudFormation stack "Sentra-DEV-Storage-Stack" exists

### Error: "DynamoDB update failed"
- Check AWS credentials are valid
- Verify table exists
- Check IAM permissions

## Migration from Old Scripts

### Old: `update_agent_policy.py`

```bash
python scripts/update_agent_policy.py --policy-file policies/payment-agent-policy.yaml
```

### New: `update_artifact.py`

```bash
python scripts/update_artifact.py --usecase policy --file policies/payment-agent-policy.yaml
```

The old script still works but shows a deprecation warning.

## See Also

- `seed_sigma_rules_metadata.py` - Bulk seed all Sigma rules from S3
- `seed_policies_metadata.py` - Bulk seed all policies from S3
- `schemas/sigma_rule_schema.py` - Pydantic models for validation
