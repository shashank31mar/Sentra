"""
Pydantic models for Agent Registry.
"""
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from enum import Enum


class AgentType(str, Enum):
    """Agent type enumeration."""
    QUERY = "query"
    ACTION = "action"
    ORCHESTRATOR = "orchestrator"
    BEDROCK = "bedrock"
    CUSTOM = "custom"
    EXTERNAL = "external"
    SYSTEM = "system"


class AgentStatus(str, Enum):
    """Agent status enumeration."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    DEPLOYING = "deploying"
    FAILED = "failed"


class EcsConfig(BaseModel):
    """ECS service configuration."""
    service_name: str = Field(..., description="ECS service name")
    task_definition_arn: Optional[str] = Field(None, description="ECS task definition ARN")
    container_name: Optional[str] = Field(None, description="Container name")
    container_port: int = Field(..., ge=1, le=65535, description="Container port")
    desired_count: int = Field(..., ge=0, description="Desired task count")


class RuntimeConfig(BaseModel):
    """Agent runtime configuration."""
    max_sessions: int = Field(..., ge=0, description="Maximum concurrent sessions")
    session_timeout_minutes: int = Field(..., ge=0, description="Session timeout in minutes")
    default_trust_score: float = Field(..., ge=0.0, le=100.0, description="Default trust score")


class Agent(BaseModel):
    """Agent registry item."""
    agent_id: str = Field(..., description="Unique agent identifier")
    name: str = Field(..., description="Human-readable agent name")
    description: str = Field(..., description="Agent description")
    type: AgentType = Field(..., description="Agent type")
    status: AgentStatus = Field(..., description="Agent status")
    version: str = Field(..., description="Agent version")
    
    ecs_config: EcsConfig = Field(..., description="ECS configuration")
    runtime_config: RuntimeConfig = Field(..., description="Runtime configuration")
    
    created_at: str = Field(..., description="Creation timestamp (ISO 8601)")
    updated_at: Optional[str] = Field(None, description="Last update timestamp (ISO 8601)")
    created_by: str = Field(..., description="Creator identifier")
    tags: List[str] = Field(default_factory=list, description="Agent tags")

    class Config:
        use_enum_values = True
        json_schema_extra = {
            "example": {
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
            }
        }
