"""
Pydantic models for Policy Metadata and Documents.
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from datetime import datetime
from enum import Enum


class PolicyAction(str, Enum):
    """Policy action enumeration."""
    ALLOW = "ALLOW"
    DENY = "DENY"
    WARN = "WARN"


class PolicySeverity(str, Enum):
    """Policy severity enumeration."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class PolicyStatus(str, Enum):
    """Policy status enumeration."""
    ACTIVE = "active"
    DISABLED = "disabled"


class PolicyRule(BaseModel):
    """Individual policy rule."""
    policy_id: str = Field(..., description="Unique policy rule identifier")
    name: str = Field(..., description="Policy rule name")
    description: Optional[str] = Field(None, description="Policy rule description")
    priority: Optional[int] = Field(None, description="Rule priority")
    
    # Flexible rule definition - can be simple expression or complex conditions
    rule: Optional[str] = Field(None, description="Policy rule expression (Python)")
    conditions: Optional[List[Dict]] = Field(None, description="Complex rule conditions")
    
    # Action/decision
    action: Optional[PolicyAction] = Field(None, description="Action to take when rule matches")
    decision: Optional[str] = Field(None, description="Decision (ALLOW/DENY/WARN)")
    reason: Optional[str] = Field(None, description="Reason for decision")
    
    severity: PolicySeverity = Field(..., description="Policy severity level")
    enabled: Optional[bool] = Field(True, description="Whether policy is enabled")
    metadata: Optional[Dict] = Field(None, description="Additional metadata")

    class Config:
        use_enum_values = True


class AgentPolicyDocument(BaseModel):
    """Full policy document from S3 (validated)."""
    schema_version: str = Field(..., description="Policy schema version")
    policy_id: str = Field(..., description="Unique policy document identifier")
    agent_id: str = Field(..., description="Agent this policy applies to")
    name: str = Field(..., description="Policy document name")
    version: str = Field(..., description="Policy version")
    status: str = Field(..., description="Policy status")
    description: Optional[str] = Field(None, description="Policy description")
    
    allowed_tools: List[str] = Field(..., description="List of allowed tool IDs")
    policies: List[PolicyRule] = Field(..., description="List of policy rules")

    # Workstream 15 (cross-cloud) — optional governance fields honored by the
    # context validator (LLD 15 §4.5). Declared here so the validation schema
    # recognizes them and they survive any future extra='forbid' tightening.
    platform: Optional[str] = Field(None, description="bedrock | azure_foundry | vertex_ai")
    cloud_region: Optional[str] = Field(None, description="Native cloud region identifier")
    allowed_agents: Optional[List[str]] = Field(None, description="Agents this agent may invoke")
    cross_cloud_dependencies: Optional[List[Dict]] = Field(
        None, description="Cross-cloud tool-sequence preconditions (LLD 15 §4.5)"
    )
    max_calls_per_minute: Optional[int] = Field(None, description="Per-agent rate limit")

    # Optional metadata sections
    policy_metadata: Optional[Dict] = Field(None, description="Policy metadata")
    notifications: Optional[Dict] = Field(None, description="Notification configuration")
    changelog: Optional[List[Dict]] = Field(None, description="Change history")
    
    created_at: str = Field(..., description="Creation timestamp (ISO 8601)")
    updated_at: Optional[str] = Field(None, description="Last update timestamp (ISO 8601)")
    created_by: str = Field(..., description="Creator identifier")

    class Config:
        json_schema_extra = {
            "example": {
                "schema_version": "v1",
                "policy_id": "agent-config-customer-query-agent",
                "agent_id": "customer-query-agent",
                "version": "1.0.0",
                "allowed_tools": ["query_customers", "query_orders"],
                "policies": [
                    {
                        "policy_id": "pol-001",
                        "name": "Max Query Limit",
                        "description": "Limit query results to 1000 rows",
                        "rule": "query_limit <= 1000",
                        "action": "DENY",
                        "severity": "high",
                        "enabled": True
                    }
                ],
                "created_at": "2025-01-13T08:00:00Z",
                "created_by": "admin@sentra.com"
            }
        }


class SeverityBreakdown(BaseModel):
    """Severity breakdown statistics."""
    critical: int = Field(0, ge=0, description="Number of critical policies")
    high: int = Field(0, ge=0, description="Number of high severity policies")
    medium: int = Field(0, ge=0, description="Number of medium severity policies")
    low: int = Field(0, ge=0, description="Number of low severity policies")


class PolicyMetadata(BaseModel):
    """Policy metadata (DynamoDB item only)."""
    policy_id: str = Field(..., description="Unique policy document identifier")
    agent_id: str = Field(..., description="Agent this policy applies to")
    name: str = Field(..., description="Policy document name")
    version: str = Field(..., description="Policy version")
    status: PolicyStatus = Field(..., description="Policy status")
    
    # S3 references
    s3_bucket: str = Field(..., description="S3 bucket containing policy content")
    s3_key: str = Field(..., description="S3 key for policy content")
    s3_version_id: Optional[str] = Field(None, description="S3 version ID")
    
    # Quick metadata
    allowed_tools_count: int = Field(..., ge=0, description="Number of allowed tools")
    policies_count: int = Field(..., ge=0, description="Number of policy rules")
    severity_breakdown: SeverityBreakdown = Field(..., description="Severity breakdown")
    
    # Integrity
    content_hash: str = Field(..., description="SHA256 hash of content")
    schema_version: str = Field(default="v1", description="Schema version")
    
    # Audit trail
    created_at: str = Field(..., description="Creation timestamp (ISO 8601)")
    updated_at: Optional[str] = Field(None, description="Last update timestamp (ISO 8601)")
    created_by: str = Field(..., description="Creator identifier")
    last_updated_by: Optional[str] = Field(None, description="Last updater identifier")

    class Config:
        use_enum_values = True
        json_schema_extra = {
            "example": {
                "policy_id": "agent-config-customer-query-agent",
                "agent_id": "customer-query-agent",
                "name": "Customer Query Agent Policies",
                "version": "1.0.0",
                "status": "active",
                "s3_bucket": "sentra-mvp-artifacts",
                "s3_key": "policies/agents/customer-query-agent/v1.0.0.yaml",
                "allowed_tools_count": 3,
                "policies_count": 3,
                "severity_breakdown": {
                    "critical": 1,
                    "high": 1,
                    "medium": 1,
                    "low": 0
                },
                "content_hash": "sha256:abc123...",
                "schema_version": "v1",
                "created_at": "2025-01-13T08:00:00Z",
                "created_by": "seed-script"
            }
        }
