# LLD 07: Agent Policy CRUD Operations

**Version:** 1.0
**Last Updated:** 2025-12-02
**Status:** Ready for Implementation
**Prerequisites:** [LLD 05: Agent Management APIs](./05-agent-management-apis.md), [LLD 06: Data Model v2](./06-data-model-v2.md)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Component Architecture](#2-component-architecture)
3. [APIs & Interfaces](#3-apis--interfaces)
4. [Data Models](#4-data-models)
5. [Validation & Business Logic](#5-validation--business-logic)
6. [Error Handling](#6-error-handling)
7. [Monitoring & Observability](#7-monitoring--observability)
8. [Cross-References](#8-cross-references)

---

## 1. Overview

### 1.1 Purpose

This LLD defines **Create, Update, Delete operations** for agent policies, enabling runtime policy management through the Dashboard UI. This extends LLD 05 (read-only APIs) with full CRUD capabilities.

### 1.2 Scope

**In Scope:**
- ✅ POST `/v1/policies` - Create new policy
- ✅ PUT `/v1/policies/{policy_id}` - Update existing policy
- ✅ DELETE `/v1/policies/{policy_id}` - Soft delete policy (set status=disabled)
- ✅ GET `/v1/policies/{policy_id}` - Get single policy with full content
- ✅ Hybrid storage (DynamoDB metadata + S3 YAML content)
- ✅ Schema validation using Pydantic
- ✅ Audit logging for all mutations
- ✅ Dashboard UI for policy management (JSON editor)

**Out of Scope:**
- ❌ Policy versioning rollback UI (Phase 2)
- ❌ Policy conflict detection (Phase 2)
- ❌ Policy approval workflow (Phase 2)
- ❌ Bulk policy operations

### 1.3 Design Principles

1. **Hybrid Storage**: DynamoDB for metadata (fast queries) + S3 for content (versioning, no size limits)
2. **Soft Delete**: Policies are never hard-deleted; set `status=disabled` for audit trail
3. **Schema Validation**: All policies validated against Pydantic schema before storage
4. **Audit Trail**: All create/update/delete operations logged with operator context
5. **Idempotent**: PUT operations are idempotent (same payload → same result)
6. **Fail-Safe**: Invalid policies rejected at API layer, never stored

### 1.4 Storage Strategy

**Hybrid Storage Pattern:**

| Component | Storage | Purpose |
|-----------|---------|---------|
| **Metadata** | DynamoDB `sentra-policies-metadata` | Fast queries, list operations, counts |
| **Content** | S3 `s3://sentra-mvp-artifacts/policies/agents/{agent_id}/v{version}.yaml` | Full policy YAML, versioning, GitOps |

**Benefits:**
- DynamoDB: Fast filtering by agent_id, status, version
- S3: Unlimited policy size, built-in versioning, Git-friendly YAML
- Decoupled: Metadata changes don't require S3 updates (e.g., marking as disabled)

---

## 2. Component Architecture

### 2.1 File Structure

```
security-controller/
├── app/
│   ├── api/
│   │   ├── routes.py                   # Add CRUD endpoints
│   │   └── models.py                   # Add PolicyCreateRequest, PolicyUpdateRequest
│   ├── services/
│   │   ├── policy_service.py           # NEW - Policy CRUD business logic
│   │   └── policy_validator.py         # NEW - Schema + business validation
│   ├── utils/
│   │   ├── s3_policy_store.py          # NEW - S3 upload/download/versioning
│   │   └── audit_logger.py             # Existing - Audit trail

dashboard/
├── services/
│   └── security_controller_client.py   # Add CRUD methods
├── components/
│   ├── agent_policies.py               # Add create/edit/delete UI
│   └── policy_json_editor.py           # NEW - JSON editor component

tests/
├── unit/
│   ├── test_policy_service.py          # NEW
│   └── test_policy_validator.py        # NEW
└── integration/
    └── test_policy_crud_e2e.py         # NEW
```

### 2.2 Component Responsibilities

| Component | Purpose | Lines (Est.) |
|-----------|---------|--------------|
| `policy_service.py` | CRUD operations (create/update/delete/get) | ~400 |
| `policy_validator.py` | Schema + business validation | ~200 |
| `s3_policy_store.py` | S3 upload/download/versioning | ~150 |
| `routes.py` additions | API endpoint handlers | ~200 |
| `security_controller_client.py` | Dashboard API client | ~150 |
| `agent_policies.py` updates | UI for create/edit/delete | ~300 |
| `policy_json_editor.py` | Reusable JSON editor component | ~150 |

**Total Estimated Code**: ~1550 lines

### 2.3 Data Flow

**Create Policy:**
```
Dashboard UI (JSON editor)
    ↓ POST /v1/policies
Security Controller API (routes.py)
    ↓
PolicyService.create_policy()
    ↓
PolicyValidator.validate() → Pydantic schema + business rules
    ↓
DynamoDB.put_item() (metadata)
    ↓
S3PolicyStore.upload() (YAML content)
    ↓
AuditLogger.log_mutation() (operator, timestamp)
    ↓
Response (policy_id, s3_version_id)
    ↓
Dashboard (show success + refresh)
```

**Update Policy:**
```
Dashboard UI (edit modal)
    ↓ PUT /v1/policies/{policy_id}
Security Controller API
    ↓
PolicyService.update_policy()
    ↓
Validate (schema + business rules)
    ↓
DynamoDB.update_item() (increment version, update metadata)
    ↓
S3PolicyStore.upload() (new S3 version - automatic versioning)
    ↓
AuditLogger.log_mutation()
    ↓
Response (new_version, s3_version_id)
```

**Delete Policy (Soft):**
```
Dashboard UI (confirm dialog)
    ↓ DELETE /v1/policies/{policy_id}
Security Controller API
    ↓
PolicyService.delete_policy()
    ↓
DynamoDB.update_item() (set status=disabled)
    ↓
S3: No changes (content preserved for audit)
    ↓
AuditLogger.log_mutation()
    ↓
Response (success)
```

---

## 3. APIs & Interfaces

### 3.1 POST /v1/policies - Create Policy

**Purpose**: Create a new agent policy with hybrid storage.

**Request Body**:
```json
{
  "schema_version": "v1",
  "agent_id": "customer-query-agent",
  "name": "Customer Query Agent Policies",
  "version": "1.0.0",
  "description": "Policies for customer query agent",
  "allowed_tools": [
    "query_customers",
    "query_orders"
  ],
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
  ]
}
```

**Response** (201 Created):
```json
{
  "success": true,
  "policy_id": "agent-config-customer-query-agent",
  "version": "1.0.0",
  "s3_key": "policies/agents/customer-query-agent/v1.0.0.yaml",
  "s3_version_id": "xY9zAb1cDe2",
  "content_hash": "sha256:abc123...",
  "created_at": "2025-12-02T10:30:00Z",
  "message": "Policy created successfully"
}
```

**Validation Rules**:
- `agent_id` must exist in `sentra-agent-registry`
- All `allowed_tools` must exist in `sentra-tool-registry`
- `policy_id` must not already exist (409 Conflict)
- `version` must follow semver format (e.g., "1.0.0")
- Policy rules must be valid Python expressions
- At least one policy rule required

**Error Responses**:
```json
// 400 Bad Request - Invalid schema
{
  "success": false,
  "error": "Validation failed",
  "details": [
    {"field": "allowed_tools[0]", "error": "Tool 'invalid_tool' not found in registry"}
  ]
}

// 409 Conflict - Policy already exists
{
  "success": false,
  "error": "Policy already exists",
  "policy_id": "agent-config-customer-query-agent",
  "existing_version": "1.0.0"
}
```

**Implementation**:
```python
# app/api/routes.py
from app.api.models import PolicyCreateRequest

@router.post("/policies", status_code=201)
async def create_policy(
    request: PolicyCreateRequest,
    operator_email: str = Header(None, alias="X-Operator-Email")
) -> Dict:
    """Create a new agent policy."""
    from app.services.policy_service import PolicyService

    policy_service = PolicyService()
    return await policy_service.create_policy(
        policy_data=request.dict(),
        operator_email=operator_email or "unknown"
    )
```

---

### 3.2 PUT /v1/policies/{policy_id} - Update Policy

**Purpose**: Update existing policy (creates new S3 version).

**Path Parameters**:
- `policy_id` (string, required) - Policy identifier

**Request Body**: Same as POST (full policy document)

**Response** (200 OK):
```json
{
  "success": true,
  "policy_id": "agent-config-customer-query-agent",
  "version": "1.1.0",
  "previous_version": "1.0.0",
  "s3_key": "policies/agents/customer-query-agent/v1.1.0.yaml",
  "s3_version_id": "aB1cDe2fGh3",
  "content_hash": "sha256:def456...",
  "updated_at": "2025-12-02T11:00:00Z",
  "message": "Policy updated successfully"
}
```

**Validation Rules**:
- Policy must exist (404 if not found)
- Cannot update disabled policies (enable first)
- Version must be incremented (or auto-increment if not provided)
- Same validation rules as POST

**Implementation**:
```python
@router.put("/policies/{policy_id}")
async def update_policy(
    policy_id: str,
    request: PolicyUpdateRequest,
    operator_email: str = Header(None, alias="X-Operator-Email")
) -> Dict:
    """Update existing policy."""
    from app.services.policy_service import PolicyService

    policy_service = PolicyService()
    return await policy_service.update_policy(
        policy_id=policy_id,
        policy_data=request.dict(),
        operator_email=operator_email or "unknown"
    )
```

---

### 3.3 DELETE /v1/policies/{policy_id} - Soft Delete

**Purpose**: Disable policy (soft delete - preserves audit trail).

**Path Parameters**:
- `policy_id` (string, required) - Policy identifier

**Request Body**: None

**Response** (200 OK):
```json
{
  "success": true,
  "policy_id": "agent-config-customer-query-agent",
  "status": "disabled",
  "disabled_at": "2025-12-02T12:00:00Z",
  "message": "Policy disabled successfully"
}
```

**Validation Rules**:
- Policy must exist (404 if not found)
- Cannot delete system policies (403 Forbidden)
- Idempotent - deleting already disabled policy returns success

**Implementation**:
```python
@router.delete("/policies/{policy_id}")
async def delete_policy(
    policy_id: str,
    operator_email: str = Header(None, alias="X-Operator-Email")
) -> Dict:
    """Soft delete policy (set status=disabled)."""
    from app.services.policy_service import PolicyService

    policy_service = PolicyService()
    return await policy_service.delete_policy(
        policy_id=policy_id,
        operator_email=operator_email or "unknown"
    )
```

---

### 3.4 GET /v1/policies/{policy_id} - Get Single Policy

**Purpose**: Get single policy with full content from S3.

**Path Parameters**:
- `policy_id` (string, required) - Policy identifier

**Query Parameters**:
- `include_content` (boolean, optional, default: true) - Include S3 YAML content

**Response** (200 OK):
```json
{
  "success": true,
  "policy_id": "agent-config-customer-query-agent",
  "metadata": {
    "agent_id": "customer-query-agent",
    "name": "Customer Query Agent Policies",
    "version": "1.0.0",
    "status": "active",
    "s3_bucket": "sentra-mvp-artifacts",
    "s3_key": "policies/agents/customer-query-agent/v1.0.0.yaml",
    "s3_version_id": "xY9zAb1cDe2",
    "allowed_tools_count": 2,
    "policies_count": 3,
    "created_at": "2025-12-02T10:30:00Z",
    "updated_at": "2025-12-02T10:30:00Z"
  },
  "content": {
    "schema_version": "v1",
    "policy_id": "agent-config-customer-query-agent",
    "agent_id": "customer-query-agent",
    "version": "1.0.0",
    "allowed_tools": ["query_customers", "query_orders"],
    "policies": [
      {
        "policy_id": "pol-001",
        "name": "Max Query Limit",
        "rule": "query_limit <= 1000",
        "action": "DENY",
        "severity": "high",
        "enabled": true
      }
    ]
  }
}
```

**Implementation**:
```python
@router.get("/policies/{policy_id}")
async def get_policy_by_id(
    policy_id: str,
    include_content: bool = True
) -> Dict:
    """Get single policy with optional S3 content."""
    from app.services.policy_service import PolicyService

    policy_service = PolicyService()
    return await policy_service.get_policy_by_id(
        policy_id=policy_id,
        include_content=include_content
    )
```

---

## 4. Data Models

### 4.1 Pydantic Request Models

```python
# app/api/models.py
from pydantic import BaseModel, Field, validator
from typing import List, Optional
from schemas.policy_schema import PolicyRule

class PolicyCreateRequest(BaseModel):
    """Request model for POST /v1/policies."""
    schema_version: str = Field(default="v1")
    agent_id: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=200)
    version: str = Field(..., pattern=r'^\d+\.\d+\.\d+$')  # semver
    description: Optional[str] = Field(None, max_length=1000)

    allowed_tools: List[str] = Field(..., min_items=1)
    policies: List[PolicyRule] = Field(..., min_items=1)

    @validator('allowed_tools')
    def validate_tool_ids(cls, v):
        """Validate tool ID format."""
        for tool_id in v:
            if not tool_id or not isinstance(tool_id, str):
                raise ValueError(f"Invalid tool_id: {tool_id}")
        return v

class PolicyUpdateRequest(PolicyCreateRequest):
    """Request model for PUT /v1/policies/{id}."""
    pass  # Same validation as create
```

### 4.2 DynamoDB Schema

See [LLD 06 Section 2.3](./06-data-model-v2.md#23-table-sentra-policies-metadata) for complete schema.

**Key fields:**
- `policy_id` (PK) - Format: `agent-config-{agent_id}`
- `agent_id` (GSI) - For querying policies by agent
- `status` (GSI) - `active` | `disabled`
- `s3_key` - Path to YAML content
- `s3_version_id` - S3 version for rollback
- `content_hash` - SHA256 for integrity verification

### 4.3 S3 YAML Format

```yaml
# policies/agents/customer-query-agent/v1.0.0.yaml
schema_version: v1
policy_id: agent-config-customer-query-agent
agent_id: customer-query-agent
name: Customer Query Agent Policies
version: 1.0.0
status: active
description: Policies for customer query agent with read-only access

allowed_tools:
  - query_customers
  - query_orders
  - query_with_limit

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

created_at: 2025-12-02T10:30:00Z
updated_at: 2025-12-02T10:30:00Z
created_by: admin@sentra.com
```

---

## 5. Validation & Business Logic

### 5.1 PolicyValidator

```python
# app/services/policy_validator.py
from typing import Dict, List, Tuple
import boto3
from pydantic import ValidationError
from schemas.policy_schema import AgentPolicyDocument

class PolicyValidator:
    """Validates policy documents (schema + business rules)."""

    def __init__(self):
        self.dynamodb = boto3.resource('dynamodb')
        self.agent_registry = self.dynamodb.Table('sentra-agent-registry')
        self.tool_registry = self.dynamodb.Table('sentra-tool-registry')

    def validate_policy(self, policy_data: Dict) -> Tuple[bool, Optional[List[str]]]:
        """
        Validate policy against schema and business rules.

        Returns:
            (is_valid, errors) - Tuple of boolean and optional error list
        """
        errors = []

        # 1. Schema validation (Pydantic)
        try:
            policy = AgentPolicyDocument(**policy_data)
        except ValidationError as e:
            errors.append(f"Schema validation failed: {e}")
            return False, errors

        # 2. Agent exists?
        agent_response = self.agent_registry.get_item(
            Key={'agent_id': policy.agent_id}
        )
        if 'Item' not in agent_response:
            errors.append(f"Agent '{policy.agent_id}' not found in registry")

        # 3. Tools exist?
        for tool_id in policy.allowed_tools:
            tool_response = self.tool_registry.get_item(
                Key={'tool_id': tool_id}
            )
            if 'Item' not in tool_response:
                errors.append(f"Tool '{tool_id}' not found in registry")

        # 4. Policy rules are valid Python expressions?
        for rule in policy.policies:
            if rule.rule:
                try:
                    # Test compile (don't execute!)
                    compile(rule.rule, '<string>', 'eval')
                except SyntaxError as e:
                    errors.append(f"Invalid rule expression '{rule.rule}': {e}")

        # 5. No duplicate policy IDs within document
        policy_ids = [p.policy_id for p in policy.policies]
        if len(policy_ids) != len(set(policy_ids)):
            errors.append("Duplicate policy_id found within policies array")

        return (len(errors) == 0), (errors if errors else None)
```

### 5.2 PolicyService

```python
# app/services/policy_service.py
from typing import Dict, Optional
import hashlib
import yaml
from datetime import datetime
from app.services.policy_validator import PolicyValidator
from app.utils.s3_policy_store import S3PolicyStore
from app.utils.audit_logger import AuditLogger

class PolicyService:
    """Service for policy CRUD operations."""

    def __init__(self):
        self.dynamodb = boto3.resource('dynamodb')
        self.metadata_table = self.dynamodb.Table('sentra-policies-metadata')
        self.validator = PolicyValidator()
        self.s3_store = S3PolicyStore()
        self.audit_logger = AuditLogger()

    async def create_policy(
        self,
        policy_data: Dict,
        operator_email: str
    ) -> Dict:
        """Create new policy with hybrid storage."""

        # 1. Validate
        is_valid, errors = self.validator.validate_policy(policy_data)
        if not is_valid:
            raise ValidationException(errors)

        # 2. Check if policy already exists
        policy_id = f"agent-config-{policy_data['agent_id']}"
        existing = self.metadata_table.get_item(Key={'policy_id': policy_id})
        if 'Item' in existing:
            raise ConflictException(f"Policy {policy_id} already exists")

        # 3. Generate content hash
        yaml_content = yaml.dump(policy_data, sort_keys=False)
        content_hash = f"sha256:{hashlib.sha256(yaml_content.encode()).hexdigest()}"

        # 4. Upload to S3
        version = policy_data['version']
        s3_key = f"policies/agents/{policy_data['agent_id']}/v{version}.yaml"
        s3_version_id = await self.s3_store.upload(
            key=s3_key,
            content=yaml_content,
            metadata={'policy_id': policy_id, 'version': version}
        )

        # 5. Store metadata in DynamoDB
        now = datetime.utcnow().isoformat() + 'Z'
        metadata_item = {
            'policy_id': policy_id,
            'agent_id': policy_data['agent_id'],
            'name': policy_data['name'],
            'version': version,
            'status': 'active',
            's3_bucket': 'sentra-mvp-artifacts',
            's3_key': s3_key,
            's3_version_id': s3_version_id,
            'allowed_tools_count': len(policy_data['allowed_tools']),
            'policies_count': len(policy_data['policies']),
            'severity_breakdown': self._calculate_severity_breakdown(policy_data['policies']),
            'content_hash': content_hash,
            'schema_version': policy_data.get('schema_version', 'v1'),
            'created_at': now,
            'updated_at': now,
            'created_by': operator_email,
            'last_updated_by': operator_email
        }

        self.metadata_table.put_item(Item=metadata_item)

        # 6. Audit log
        await self.audit_logger.log_mutation(
            operation='CREATE_POLICY',
            resource_id=policy_id,
            operator_email=operator_email,
            details={'version': version, 's3_key': s3_key}
        )

        return {
            'success': True,
            'policy_id': policy_id,
            'version': version,
            's3_key': s3_key,
            's3_version_id': s3_version_id,
            'content_hash': content_hash,
            'created_at': now,
            'message': 'Policy created successfully'
        }

    async def update_policy(
        self,
        policy_id: str,
        policy_data: Dict,
        operator_email: str
    ) -> Dict:
        """Update existing policy (creates new S3 version)."""

        # 1. Check policy exists
        existing = self.metadata_table.get_item(Key={'policy_id': policy_id})
        if 'Item' not in existing:
            raise NotFoundException(f"Policy {policy_id} not found")

        existing_item = existing['Item']

        # 2. Check not disabled
        if existing_item['status'] == 'disabled':
            raise ForbiddenException("Cannot update disabled policy. Enable it first.")

        # 3. Validate
        is_valid, errors = self.validator.validate_policy(policy_data)
        if not is_valid:
            raise ValidationException(errors)

        # 4. Auto-increment version if not provided
        new_version = policy_data.get('version', self._increment_version(existing_item['version']))

        # 5. Generate content hash
        yaml_content = yaml.dump(policy_data, sort_keys=False)
        content_hash = f"sha256:{hashlib.sha256(yaml_content.encode()).hexdigest()}"

        # 6. Upload to S3 (S3 versioning creates new version automatically)
        s3_key = f"policies/agents/{policy_data['agent_id']}/v{new_version}.yaml"
        s3_version_id = await self.s3_store.upload(
            key=s3_key,
            content=yaml_content,
            metadata={'policy_id': policy_id, 'version': new_version}
        )

        # 7. Update metadata
        now = datetime.utcnow().isoformat() + 'Z'
        self.metadata_table.update_item(
            Key={'policy_id': policy_id},
            UpdateExpression="""
                SET version = :version,
                    s3_key = :s3_key,
                    s3_version_id = :s3_version_id,
                    content_hash = :content_hash,
                    allowed_tools_count = :tools_count,
                    policies_count = :policies_count,
                    severity_breakdown = :severity,
                    updated_at = :updated_at,
                    last_updated_by = :updated_by
            """,
            ExpressionAttributeValues={
                ':version': new_version,
                ':s3_key': s3_key,
                ':s3_version_id': s3_version_id,
                ':content_hash': content_hash,
                ':tools_count': len(policy_data['allowed_tools']),
                ':policies_count': len(policy_data['policies']),
                ':severity': self._calculate_severity_breakdown(policy_data['policies']),
                ':updated_at': now,
                ':updated_by': operator_email
            }
        )

        # 8. Audit log
        await self.audit_logger.log_mutation(
            operation='UPDATE_POLICY',
            resource_id=policy_id,
            operator_email=operator_email,
            details={
                'previous_version': existing_item['version'],
                'new_version': new_version,
                's3_key': s3_key
            }
        )

        return {
            'success': True,
            'policy_id': policy_id,
            'version': new_version,
            'previous_version': existing_item['version'],
            's3_key': s3_key,
            's3_version_id': s3_version_id,
            'content_hash': content_hash,
            'updated_at': now,
            'message': 'Policy updated successfully'
        }

    async def delete_policy(
        self,
        policy_id: str,
        operator_email: str
    ) -> Dict:
        """Soft delete policy (set status=disabled)."""

        # 1. Check policy exists
        existing = self.metadata_table.get_item(Key={'policy_id': policy_id})
        if 'Item' not in existing:
            raise NotFoundException(f"Policy {policy_id} not found")

        # 2. Check not system policy
        if existing['Item'].get('created_by') == 'system':
            raise ForbiddenException("Cannot delete system policies")

        # 3. Soft delete (idempotent - already disabled returns success)
        now = datetime.utcnow().isoformat() + 'Z'
        self.metadata_table.update_item(
            Key={'policy_id': policy_id},
            UpdateExpression="SET #status = :disabled, updated_at = :now, last_updated_by = :operator",
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={
                ':disabled': 'disabled',
                ':now': now,
                ':operator': operator_email
            }
        )

        # 4. Audit log
        await self.audit_logger.log_mutation(
            operation='DELETE_POLICY',
            resource_id=policy_id,
            operator_email=operator_email,
            details={'disabled_at': now}
        )

        return {
            'success': True,
            'policy_id': policy_id,
            'status': 'disabled',
            'disabled_at': now,
            'message': 'Policy disabled successfully'
        }

    async def get_policy_by_id(
        self,
        policy_id: str,
        include_content: bool = True
    ) -> Dict:
        """Get single policy with optional S3 content."""

        # 1. Get metadata
        response = self.metadata_table.get_item(Key={'policy_id': policy_id})
        if 'Item' not in response:
            raise NotFoundException(f"Policy {policy_id} not found")

        metadata = response['Item']

        # 2. Optionally fetch S3 content
        content = None
        if include_content:
            yaml_content = await self.s3_store.download(
                key=metadata['s3_key'],
                version_id=metadata.get('s3_version_id')
            )
            content = yaml.safe_load(yaml_content)

        return {
            'success': True,
            'policy_id': policy_id,
            'metadata': metadata,
            'content': content
        }

    def _calculate_severity_breakdown(self, policies: List[Dict]) -> Dict:
        """Calculate severity breakdown for metadata."""
        breakdown = {'critical': 0, 'high': 0, 'medium': 0, 'low': 0}
        for policy in policies:
            severity = policy.get('severity', 'medium')
            if severity in breakdown:
                breakdown[severity] += 1
        return breakdown

    def _increment_version(self, version: str) -> str:
        """Auto-increment patch version (1.0.0 → 1.0.1)."""
        parts = version.split('.')
        parts[2] = str(int(parts[2]) + 1)
        return '.'.join(parts)
```

---

## 6. Error Handling

### 6.1 Exception Classes

```python
# app/exceptions.py
class ValidationException(Exception):
    """Raised when policy validation fails."""
    status_code = 400

class NotFoundException(Exception):
    """Raised when policy not found."""
    status_code = 404

class ConflictException(Exception):
    """Raised when policy already exists."""
    status_code = 409

class ForbiddenException(Exception):
    """Raised when operation not allowed."""
    status_code = 403
```

### 6.2 Error Response Format

```json
{
  "success": false,
  "error": "Validation failed",
  "details": [
    {"field": "allowed_tools[0]", "error": "Tool 'invalid_tool' not found in registry"},
    {"field": "policies[1].rule", "error": "Invalid Python expression: unexpected EOF"}
  ],
  "timestamp": "2025-12-02T10:30:00Z"
}
```

---

## 7. Monitoring & Observability

### 7.1 Metrics

**CloudWatch Custom Metrics:**
- `PolicyCRUD/CreatePolicy/Success` - Successful creates
- `PolicyCRUD/CreatePolicy/Failure` - Failed creates
- `PolicyCRUD/UpdatePolicy/Success` - Successful updates
- `PolicyCRUD/UpdatePolicy/Failure` - Failed updates
- `PolicyCRUD/DeletePolicy/Success` - Successful deletes
- `PolicyCRUD/ValidationFailure` - Validation failures

### 7.2 Audit Logs

**All mutations logged to CloudWatch Logs** (`/sentra/audit-logs`):

```json
{
  "timestamp": "2025-12-02T10:30:00Z",
  "operation": "CREATE_POLICY",
  "resource_id": "agent-config-customer-query-agent",
  "operator_email": "admin@sentra.com",
  "operator_source": "dashboard",
  "details": {
    "version": "1.0.0",
    "s3_key": "policies/agents/customer-query-agent/v1.0.0.yaml",
    "s3_version_id": "xY9zAb1cDe2"
  },
  "result": "success"
}
```

---

## 8. Cross-References

### 8.1 Related LLDs
- [LLD 05: Agent Management APIs](./05-agent-management-apis.md) - Read-only policy APIs
- [LLD 06: Data Model v2](./06-data-model-v2.md) - Complete table schemas

### 8.2 Implementation Files
- `src/security-controller/app/services/policy_service.py` - Main service
- `src/security-controller/app/api/routes.py` - API endpoints
- `src/dashboard/components/agent_policies.py` - UI components
- `scripts/schemas/policy_schema.py` - Pydantic schemas

---

**End of LLD 07: Agent Policy CRUD Operations - v1.0**
