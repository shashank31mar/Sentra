"""
Configuration Management for Security Controller

Loads configuration from environment variables with sensible defaults.
"""
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Service Configuration
    port: int = 8080
    log_level: str = "INFO"
    environment: str = "production"
    
    # AWS Configuration
    aws_region: str = "us-east-1"
    dynamodb_session_table: str = Field(default="sentra-session-context", validation_alias="SESSION_CONTEXT_TABLE")
    s3_bucket: str = Field(default="sentra-mvp-artifacts", validation_alias="ARTIFACTS_BUCKET")
    cloudwatch_log_group: str = Field(default="/sentra/audit-logs", validation_alias="AUDIT_LOG_GROUP")
    
    # Data Model v2 Tables (Workstream 6, Task 1.5)
    dynamodb_agent_registry_table: str = Field(
        default="sentra-agent-registry",
        validation_alias="AGENT_REGISTRY_TABLE"
    )
    dynamodb_tool_registry_table: str = Field(
        default="sentra-tool-registry",
        validation_alias="TOOL_REGISTRY_TABLE"
    )
    dynamodb_policies_metadata_table: str = Field(
        default="sentra-policies-metadata",
        validation_alias="POLICIES_METADATA_TABLE"
    )
    dynamodb_sigma_rules_metadata_table: str = Field(
        default="sentra-sigma-rules-metadata",
        validation_alias="SIGMA_RULES_METADATA_TABLE"
    )
    
    # Validation Configuration
    validation_timeout_seconds: int = 5
    max_validation_latency_ms: int = 100
    
    # Trust Scoring Configuration
    trust_initial_score: float = 100.0
    trust_quarantine_threshold: float = 40.0
    trust_suspend_threshold: float = 10.0
    
    # Sigma Rules Configuration
    sigma_rules_s3_prefix: str = "sigma_rules/llm/"
    sigma_rules_cache_ttl_seconds: int = 300  # 5 minutes
    
    # Cache Configuration (Workstream 5, Task 1)
    cache_enabled: bool = Field(default=True, validation_alias="CACHE_ENABLED")
    agent_metadata_cache_ttl_seconds: int = Field(default=60, validation_alias="AGENT_METADATA_CACHE_TTL_SECONDS")
    tool_registry_cache_ttl_seconds: int = Field(default=300, validation_alias="TOOL_REGISTRY_CACHE_TTL_SECONDS")
    policy_cache_ttl_seconds: int = Field(default=300, validation_alias="POLICY_CACHE_TTL_SECONDS")
    sigma_rules_metadata_cache_ttl_seconds: int = Field(default=600, validation_alias="SIGMA_RULES_METADATA_CACHE_TTL_SECONDS")
    max_cache_size: int = Field(default=1000, validation_alias="MAX_CACHE_SIZE")
    
    class Config:
        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings = Settings()
