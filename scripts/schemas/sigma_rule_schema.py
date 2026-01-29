"""
Pydantic models for Sigma Rule Metadata and Documents.
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from datetime import datetime
from enum import Enum


class SigmaRuleStatus(str, Enum):
    """Sigma rule status enumeration."""
    STABLE = "stable"
    EXPERIMENTAL = "experimental"
    DEPRECATED = "deprecated"
    DISABLED = "disabled"


class SigmaRuleLevel(str, Enum):
    """Sigma rule severity level enumeration."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SigmaRuleCondition(str, Enum):
    """Sigma rule detection condition."""
    ANY = "any"
    ALL = "all"


class SigmaRuleDetection(BaseModel):
    """Detection patterns for Sigma rule."""
    # Flexible detection - can be simple patterns or complex conditions
    patterns: Optional[List[str]] = Field(None, min_length=1, description="List of detection patterns")
    condition: str = Field(..., description="Match condition expression")
    case_sensitive: Optional[bool] = Field(False, description="Whether matching is case-sensitive")
    
    # Allow arbitrary detection fields for complex rules
    class Config:
        extra = "allow"  # Allow additional fields


class SigmaRuleDocument(BaseModel):
    """Full Sigma rule from S3 (validated)."""
    title: str = Field(..., description="Rule title")
    id: str = Field(..., description="Unique rule identifier")
    status: SigmaRuleStatus = Field(..., description="Rule status")
    description: str = Field(..., description="Rule description")
    
    # Optional version and timestamps
    version: Optional[str] = Field(None, description="Rule version")
    date: Optional[str] = Field(None, description="Creation date")
    modified: Optional[str] = Field(None, description="Last modified date")
    created_at: Optional[str] = Field(None, description="Creation timestamp (ISO 8601)")
    
    logsource: Optional[dict] = Field(None, description="Log source configuration")
    detection: SigmaRuleDetection = Field(..., description="Detection patterns")
    level: SigmaRuleLevel = Field(..., description="Severity level")
    tags: List[str] = Field(default_factory=list, description="Rule tags")
    references: Optional[List[str]] = Field(default_factory=list, description="Reference URLs")
    falsepositives: Optional[List[str]] = Field(None, description="Known false positives")
    response: Optional[Dict] = Field(None, description="Response configuration")
    fields: Optional[List[str]] = Field(None, description="Relevant fields")
    
    author: str = Field(..., description="Rule author")

    class Config:
        use_enum_values = True
        json_schema_extra = {
            "example": {
                "title": "Prompt Injection - Ignore Previous Instructions",
                "id": "sigma-llm-001",
                "status": "stable",
                "description": "Detects prompt injection attempts",
                "version": "1.0.0",
                "logsource": {
                    "product": "ai_agent",
                    "category": "user_input"
                },
                "detection": {
                    "patterns": [
                        "ignore previous instructions",
                        "disregard all prior"
                    ],
                    "condition": "any",
                    "case_sensitive": False
                },
                "level": "high",
                "tags": ["attack.llm01", "owasp.llm.top10.2025"],
                "references": ["https://owasp.org/..."],
                "author": "Sentra Security Team",
                "created_at": "2025-01-13T08:00:00Z"
            }
        }


class SigmaRuleStats(BaseModel):
    """Runtime statistics for Sigma rule."""
    match_count_24h: int = Field(0, ge=0, description="Matches in last 24 hours")
    match_count_7d: int = Field(0, ge=0, description="Matches in last 7 days")
    last_matched: Optional[str] = Field(None, description="Last match timestamp (ISO 8601)")


class SigmaRuleMetadata(BaseModel):
    """Sigma rule metadata (DynamoDB item only)."""
    rule_id: str = Field(..., description="Unique rule identifier")
    title: str = Field(..., description="Rule title")
    description: str = Field(..., description="Rule description")
    status: SigmaRuleStatus = Field(..., description="Rule status")
    level: SigmaRuleLevel = Field(..., description="Severity level")
    version: str = Field(..., description="Rule version")
    
    # S3 references
    s3_bucket: str = Field(..., description="S3 bucket containing rule content")
    s3_key: str = Field(..., description="S3 key for rule content")
    s3_version_id: Optional[str] = Field(None, description="S3 version ID")
    
    # Quick metadata
    patterns_count: int = Field(..., ge=1, description="Number of detection patterns")
    tags: List[str] = Field(default_factory=list, description="Rule tags")
    
    # Runtime stats
    stats: SigmaRuleStats = Field(default_factory=SigmaRuleStats, description="Runtime statistics")
    
    # Integrity
    content_hash: str = Field(..., description="SHA256 hash of content")
    schema_version: str = Field(default="v1", description="Schema version")
    
    # Audit trail
    created_at: str = Field(..., description="Creation timestamp (ISO 8601)")
    updated_at: Optional[str] = Field(None, description="Last update timestamp (ISO 8601)")
    created_by: str = Field(..., description="Creator identifier")
    author: str = Field(..., description="Rule author")

    class Config:
        use_enum_values = True
        json_schema_extra = {
            "example": {
                "rule_id": "sigma-llm-001",
                "title": "Prompt Injection - Ignore Previous Instructions",
                "description": "Detects prompt injection attempts",
                "status": "stable",
                "level": "high",
                "version": "1.0.0",
                "s3_bucket": "sentra-mvp-artifacts",
                "s3_key": "sigma_rules/llm/prompt_injection_basic.yaml",
                "patterns_count": 10,
                "tags": ["attack.llm01", "owasp.llm.top10.2025"],
                "stats": {
                    "match_count_24h": 0,
                    "match_count_7d": 0,
                    "last_matched": None
                },
                "content_hash": "sha256:def456...",
                "schema_version": "v1",
                "created_at": "2025-01-13T08:00:00Z",
                "created_by": "seed-script",
                "author": "Sentra Security Team"
            }
        }
