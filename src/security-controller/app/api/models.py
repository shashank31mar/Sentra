"""
Pydantic Models for API Request/Response Schemas

Defines data models for validation requests and responses.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from pydantic import BaseModel, Field, validator
import sys
import os

# Add scripts path for policy_schema import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../..', 'scripts'))
from schemas.policy_schema import PolicyRule


class ValidationRequest(BaseModel):
    """
    Request schema for POST /validate endpoint.

    All fields are required for proper validation.
    """
    request_id: str = Field(..., description="Unique request identifier for tracing")
    session_id: str = Field(..., description="Session identifier")
    agent_id: str = Field(..., description="Agent making the request")
    tool_name: str = Field(..., description="Tool to be executed")
    tool_params: Dict[str, Any] = Field(default_factory=dict, description="Tool parameters")
    user_input: str = Field(..., description="Original user input (for threat detection)")
    timestamp: str = Field(..., description="Request timestamp (ISO 8601)")
    operation_type: str = Field(..., description="Operation type: READ or WRITE")
    context: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional context (user_id, ip_address, authorization_level, etc.)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "request_id": "req-abc-123",
                "session_id": "sess-xyz-789",
                "agent_id": "customer-query-agent",
                "tool_name": "query_customers",
                "tool_params": {"query": "SELECT * FROM customers WHERE state='CA' LIMIT 10"},
                "user_input": "Show customers from California",
                "timestamp": "2025-01-18T10:30:00Z",
                "operation_type": "READ"
            }
        }


class ValidationResponse(BaseModel):
    """
    Response schema for ALLOW decision.
    """
    decision: str = Field(..., description="ALLOW or DENY")
    reason: str = Field(..., description="Human-readable reason for decision")
    trust_score: float = Field(..., description="Current trust score (0-100)")
    session_id: str = Field(..., description="Session identifier")
    latency_ms: float = Field(..., description="Validation latency in milliseconds")
    action_id: Optional[str] = Field(None, description="Action ID for reversible actions")
    
    class Config:
        json_schema_extra = {
            "example": {
                "decision": "ALLOW",
                "reason": "All validation checks passed",
                "trust_score": 95.5,
                "session_id": "sess-xyz-789",
                "latency_ms": 52.3,
                "action_id": None
            }
        }


class ValidationDenyResponse(BaseModel):
    """
    Response schema for DENY decision.
    """
    decision: str = Field(..., description="DENY")
    reason: str = Field(..., description="Human-readable reason for denial")
    threat_type: Optional[str] = Field(None, description="Type of threat detected")
    matched_rule: Optional[str] = Field(None, description="Rule that triggered denial")
    severity: Optional[str] = Field(None, description="Threat severity level")
    trust_score: float = Field(..., description="Current trust score after penalty")
    session_id: str = Field(..., description="Session identifier")
    latency_ms: float = Field(..., description="Validation latency in milliseconds")
    violation_type: Optional[str] = Field(None, description="Type of violation")
    
    class Config:
        json_schema_extra = {
            "example": {
                "decision": "DENY",
                "reason": "Prompt injection detected",
                "threat_type": "PROMPT_INJECTION",
                "matched_rule": "prompt_injection_basic.yml",
                "severity": "CRITICAL",
                "trust_score": 75.0,
                "session_id": "sess-xyz-789",
                "latency_ms": 38.2,
                "violation_type": "PROMPT_INJECTION"
            }
        }


class ValidationResult(BaseModel):
    """
    Internal validation result from validators.
    """
    decision: str  # ALLOW or DENY
    reason: str
    violation_type: Optional[str] = None
    threat_type: Optional[str] = None
    matched_rule: Optional[str] = None
    severity: Optional[str] = None
    penalty: int = 0  # Trust score penalty (negative)
    should_deny: bool = False


# ============================================================
# Task 10: Query API Models
# ============================================================

class LogEntry(BaseModel):
    """Single audit log entry"""
    request_id: str
    timestamp: str
    session_id: str
    agent_id: str
    tool_name: str
    operation_type: str
    decision: str
    reason: str
    trust_score_before: float
    trust_score_after: float
    trust_delta: float
    latency_ms: float
    threat_type: Optional[str] = None
    severity: Optional[str] = None
    matched_rule: Optional[str] = None
    violation_type: Optional[str] = None
    action_id: Optional[str] = None
    reversible: Optional[bool] = None
    rollback_status: Optional[str] = None


class LogsResponse(BaseModel):
    """Response for GET /v1/logs"""
    logs: List[LogEntry]
    total: int
    has_more: bool
    next_token: Optional[str] = None


class SessionInfo(BaseModel):
    """Single session information"""
    session_id: str
    user_id: str
    agent_id: str
    trust_score: float
    quarantine_status: str
    total_requests: int
    allow_count: int
    deny_count: int
    consecutive_allows: int
    created_at: str
    last_activity: str


class SessionsResponse(BaseModel):
    """Response for GET /v1/sessions"""
    sessions: List[SessionInfo]
    total: int


class MetricsResponse(BaseModel):
    """Response for GET /v1/metrics"""
    time_range: Dict[str, str]
    requests: Dict[str, Any]
    latency: Dict[str, float]
    sessions: Dict[str, int]
    threats: Dict[str, int]


# ============================================================
# Workstream 11: Policy CRUD Models
# ============================================================

class PolicyCreateRequest(BaseModel):
    """
    Request model for POST /v1/policies.

    Creates a new agent policy with hybrid storage (DynamoDB metadata + S3 content).
    Reference: LLD 11 Section 3.1
    """
    schema_version: str = Field(default="v1", description="Policy schema version")
    agent_id: str = Field(..., min_length=1, max_length=100, description="Agent identifier")
    name: str = Field(..., min_length=1, max_length=200, description="Policy document name")
    version: str = Field(..., pattern=r'^\d+\.\d+\.\d+$', description="Semantic version (e.g., 1.0.0)")
    description: Optional[str] = Field(None, max_length=1000, description="Policy description")

    allowed_tools: List[str] = Field(..., min_items=1, description="List of allowed tool IDs")
    policies: List[PolicyRule] = Field(..., min_items=1, description="List of policy rules")

    @validator('allowed_tools')
    def validate_tool_ids(cls, v):
        """Validate tool ID format."""
        for tool_id in v:
            if not tool_id or not isinstance(tool_id, str):
                raise ValueError(f"Invalid tool_id: {tool_id}")
            if len(tool_id.strip()) == 0:
                raise ValueError("Tool IDs cannot be empty strings")
        return v

    @validator('policies')
    def validate_policies_unique(cls, v):
        """Ensure no duplicate policy IDs."""
        policy_ids = [p.policy_id for p in v]
        if len(policy_ids) != len(set(policy_ids)):
            raise ValueError("Duplicate policy_id found within policies array")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "schema_version": "v1",
                "agent_id": "customer-query-agent",
                "name": "Customer Query Agent Policies",
                "version": "1.0.0",
                "description": "Policies for customer query agent",
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
                ]
            }
        }


class PolicyUpdateRequest(PolicyCreateRequest):
    """
    Request model for PUT /v1/policies/{policy_id}.

    Updates existing policy (creates new S3 version).
    Same validation rules as PolicyCreateRequest.
    Reference: LLD 11 Section 3.2
    """
    pass
