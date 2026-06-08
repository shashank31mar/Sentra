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

    Core fields are required for proper validation. Cross-cloud fields
    (platform, cloud_region) are optional — when present, the controller
    will use them as hints for the audit log and may override values
    derived from the policy.
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
    # Cross-cloud fields (Workstream 15) — interceptor-supplied hints.
    # When absent, the controller resolves platform/cloud_region from the agent's policy.
    platform: Optional[str] = Field(None, description="bedrock | azure_foundry | vertex_ai (optional; resolved from policy if absent)")
    cloud_region: Optional[str] = Field(None, description="Native cloud region (optional; resolved from policy if absent)")
    
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
    # Cross-cloud fields (Workstream 15)
    platform: Optional[str] = Field(None, description="Cloud platform governing this agent (from policy)")
    cloud_region: Optional[str] = Field(None, description="Cloud region of the agent (from policy)")
    
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
    # Cross-cloud fields (Workstream 15)
    platform: Optional[str] = Field(None, description="Cloud platform governing this agent (from policy)")
    cloud_region: Optional[str] = Field(None, description="Cloud region of the agent (from policy)")
    
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
    # decision: "ALLOW", "DENY", or None for ABSTAIN (LLD 17 §4 + LLD 19 §5).
    # ABSTAIN means "this validator declines to vote on this request" — the
    # combiner treats absence-of-signal per LLD 17 §4. Used by the ML classifier
    # when Bedrock is unavailable or confidence is too low to trust either tier.
    decision: Optional[str] = None
    reason: str
    violation_type: Optional[str] = None
    threat_type: Optional[str] = None
    matched_rule: Optional[str] = None
    severity: Optional[str] = None
    penalty: int = 0  # Trust score penalty (negative)
    should_deny: bool = False
    # Cross-cloud fields (Workstream 15) — populated by policy_engine from the
    # loaded policy; propagated through the pipeline so the orchestrator can
    # surface them in the response and audit log.
    platform: Optional[str] = None
    cloud_region: Optional[str] = None
    # violated_policy: optional reference to a policy-engine rule that triggered DENY
    violated_policy: Optional[str] = None
    # Signal source — Workstream 17 / LLD 17 §4. Every validator stamps its
    # ValidationResult with the source taxonomy string (e.g. "sentra.sigma").
    # ValidationService converts each result to a Signal via to_signal() and
    # forwards the list to the audit logger + combiner. Defaults to None for
    # backward compatibility — pre-W17 callers and synthetic results still work.
    source: Optional[str] = None
    # Optional ML-style confidence score (0.0-1.0). Combiner uses this as a
    # secondary tie-break when priorities are equal.
    confidence: Optional[float] = None
    # Free-form metadata bag — validator-specific extras (e.g. ML classifier's
    # model_used, model_id). Propagated to Signal.metadata for the audit log
    # and dashboard expander.
    metadata: Optional[Dict[str, Any]] = None

    @classmethod
    def abstain(cls, reason: str) -> "ValidationResult":
        """Validator declines to vote on this request (LLD 17 §4, LLD 19 §5.2).

        ABSTAIN means "this producer wasn't consulted" — the combiner treats it
        as absence of signal, not as ALLOW. Used by the ML classifier on Bedrock
        outage, low-confidence escalation failure, or feature-flag-disabled.

        to_signal() returns None for an abstain result; validation_service's
        _capture must check is_abstain() before appending to the signals list.
        """
        return cls(
            decision=None,
            reason=reason,
            should_deny=False,
            penalty=0,
            metadata={"abstain": True},
        )

    @property
    def is_abstain(self) -> bool:
        """True if the validator declined to vote (decision=None)."""
        return self.decision is None

    def to_signal(self):
        """Convert this result into a combiners.Signal — LLD 17 §6.

        Imported lazily so models.py stays free of combiner imports during
        Pydantic class construction (avoids a circular import path).

        Returns None for abstain results (LLD 17 §4 absence semantics) — the
        caller is responsible for skipping signal emission when this happens.
        """
        if self.is_abstain:
            return None

        from app.combiners import Signal, default_priority

        if self.source is None:
            raise ValueError(
                "ValidationResult.to_signal: source is unset — validator "
                "must stamp a Source.* taxonomy string before emission"
            )
        # Merge validator-specific extras into the metadata bag the audit log
        # and dashboard expander surface. violation_type / violated_policy stay
        # at the top level for back-compat with consumers that read them there.
        signal_metadata: Dict[str, Any] = {
            "violation_type": self.violation_type,
            "violated_policy": self.violated_policy,
        }
        if self.metadata:
            signal_metadata.update(self.metadata)

        return Signal(
            source=self.source,
            decision=self.decision,
            reason=self.reason if self.decision == "DENY" else None,
            priority=default_priority(self.source),
            confidence=self.confidence,
            threat_type=self.threat_type,
            matched_rule=self.matched_rule,
            severity=self.severity,
            metadata=signal_metadata,
        )


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
    # Cross-cloud fields (Workstream 15) — enable per-cloud filtering of audit logs
    platform: Optional[str] = None
    cloud_region: Optional[str] = None


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

    # Workstream 15 (cross-cloud) — optional fields that MUST round-trip through
    # the CRUD path so the context validator can enforce cross_cloud_dependencies.
    # Before this, PolicyCreate/UpdateRequest didn't declare them, so request.dict()
    # in routes.py silently dropped them on every POST/PUT — the active S3 policy
    # lost the cross-cloud rule and S3's attack-path enforcement failed open
    # (see LLD 15 §4.5). Optional so existing single-cloud policies are unaffected.
    platform: Optional[str] = Field(None, description="bedrock | azure_foundry | vertex_ai")
    cloud_region: Optional[str] = Field(None, description="Native cloud region identifier")
    allowed_agents: Optional[List[str]] = Field(None, description="Agents this agent may invoke")
    cross_cloud_dependencies: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="Cross-cloud tool-sequence preconditions (LLD 15 §4.5)",
    )
    max_calls_per_minute: Optional[int] = Field(None, description="Per-agent rate limit")

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
