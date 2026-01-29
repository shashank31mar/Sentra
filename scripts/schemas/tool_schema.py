"""
Pydantic models for Tool Registry.
"""
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
from enum import Enum


class ToolType(str, Enum):
    """Tool type enumeration."""
    READ = "READ"
    WRITE = "WRITE"


class ToolStatus(str, Enum):
    """Tool status enumeration."""
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    DISABLED = "disabled"


class ParameterValidation(BaseModel):
    """Parameter validation rules."""
    min: Optional[float] = Field(None, description="Minimum value (for numbers)")
    max: Optional[float] = Field(None, description="Maximum value (for numbers)")
    pattern: Optional[str] = Field(None, description="Regex pattern (for strings)")
    example: Optional[str] = Field(None, description="Example value")


class ParameterSchema(BaseModel):
    """Tool parameter schema."""
    type: str = Field(..., description="Parameter type (string, integer, number, boolean)")
    required: bool = Field(False, description="Whether parameter is required")
    default: Optional[Any] = Field(None, description="Default value")
    description: Optional[str] = Field(None, description="Parameter description")
    validation: Optional[ParameterValidation] = Field(None, description="Validation rules")


class RateLimit(BaseModel):
    """Rate limiting configuration."""
    requests_per_minute: int = Field(..., ge=1, description="Requests per minute limit")
    burst_limit: int = Field(..., ge=1, description="Burst limit")


class ExecutionConfig(BaseModel):
    """Tool execution configuration."""
    timeout_seconds: int = Field(..., ge=1, description="Execution timeout in seconds")
    retry_attempts: int = Field(..., ge=0, description="Number of retry attempts")
    idempotent: bool = Field(..., description="Whether tool is idempotent")


class Tool(BaseModel):
    """Tool registry item."""
    tool_id: str = Field(..., description="Unique tool identifier")
    name: str = Field(..., description="Human-readable tool name")
    description: str = Field(..., description="Tool description")
    tool_type: ToolType = Field(..., description="Tool type (READ or WRITE)")
    category: str = Field(..., description="Tool category")
    status: ToolStatus = Field(..., description="Tool status")
    version: str = Field(..., description="Tool version")
    
    parameters: Dict[str, ParameterSchema] = Field(
        default_factory=dict,
        description="Tool parameters schema"
    )
    rate_limit: RateLimit = Field(..., description="Rate limiting configuration")
    execution_config: ExecutionConfig = Field(..., description="Execution configuration")
    
    created_at: str = Field(..., description="Creation timestamp (ISO 8601)")
    updated_at: Optional[str] = Field(None, description="Last update timestamp (ISO 8601)")
    created_by: str = Field(..., description="Creator identifier")
    tags: List[str] = Field(default_factory=list, description="Tool tags")

    class Config:
        use_enum_values = True
        json_schema_extra = {
            "example": {
                "tool_id": "query_customers",
                "name": "Query Customers",
                "description": "Query customer database with filters",
                "tool_type": "READ",
                "category": "database",
                "status": "active",
                "version": "1.0.0",
                "parameters": {
                    "state": {
                        "type": "string",
                        "required": False,
                        "description": "Filter by state"
                    }
                },
                "rate_limit": {
                    "requests_per_minute": 60,
                    "burst_limit": 100
                },
                "execution_config": {
                    "timeout_seconds": 30,
                    "retry_attempts": 3,
                    "idempotent": True
                },
                "created_at": "2025-01-13T08:00:00Z",
                "created_by": "seed-script",
                "tags": ["database", "read-only"]
            }
        }
