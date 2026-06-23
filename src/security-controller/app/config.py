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

    # Validation Signal Store (Workstream 17 / LLD 17)
    dynamodb_validation_signals_table: str = Field(
        default="sentra-validation-signals",
        validation_alias="VALIDATION_SIGNALS_TABLE"
    )

    # ------------------------------------------------------------------
    # Tenancy v2 (Multi-Cloud Agent Import — P0a, workstream §1.2)
    # ------------------------------------------------------------------
    # Master cutover flag. OFF (default) → every read/write hits the v1
    # tables exactly as today (byte-identical, rollback-safe). ON → the
    # `*-v2` tenant-scoped tables. Read PER REQUEST via the tenancy helper
    # (never latched at __init__) so a rolling deploy that runs old+new tasks
    # concurrently stays consistent within each task's env (workstream T7).
    tenancy_v2_enabled: bool = Field(
        default=False, validation_alias="TENANCY_V2_ENABLED"
    )
    dynamodb_agent_registry_table_v2: str = Field(
        default="sentra-agent-registry-v2",
        validation_alias="AGENT_REGISTRY_TABLE_V2",
    )
    dynamodb_policies_metadata_table_v2: str = Field(
        default="sentra-policies-metadata-v2",
        validation_alias="POLICIES_METADATA_TABLE_V2",
    )
    dynamodb_session_table_v2: str = Field(
        default="sentra-session-context-v2",
        validation_alias="SESSION_CONTEXT_TABLE_V2",
    )
    dynamodb_validation_signals_table_v2: str = Field(
        default="sentra-validation-signals-v2",
        validation_alias="VALIDATION_SIGNALS_TABLE_V2",
    )

    # ------------------------------------------------------------------
    # Multi-Tenancy runtime identity (LLD-26 / WS-A, WS-D)
    # ------------------------------------------------------------------
    # Tenant registry + operator↔tenant membership (WS-D D1) and the per-agent
    # asymmetric credential store (WS-A A1). All three are net-new, born
    # tenant-scoped tables; they sit empty (and unread on the hot path) until
    # identity is rolled out, so adding them is regression-free.
    dynamodb_tenants_table: str = Field(
        default="sentra-tenants", validation_alias="TENANTS_TABLE"
    )
    dynamodb_tenant_members_table: str = Field(
        default="sentra-tenant-members", validation_alias="TENANT_MEMBERS_TABLE"
    )
    dynamodb_agent_credentials_table: str = Field(
        default="sentra-agent-credentials", validation_alias="AGENT_CREDENTIALS_TABLE"
    )
    # Per-tenant quota counters (WS-E E2b). Write-sharded; rows auto-expire via TTL.
    dynamodb_quota_counters_table: str = Field(
        default="sentra-quota-counters", validation_alias="QUOTA_COUNTERS_TABLE"
    )
    # Hot-path RPS quota enforcement (WS-E E2b) — OFF by default (founder-gated,
    # LLD-26 §9.3). On → a write-sharded per-validate counter (fail-open). Leave
    # off until there are paying tenants with contractual limits.
    quota_enforcement_enabled: bool = Field(
        default=False, validation_alias="QUOTA_ENFORCEMENT_ENABLED"
    )

    # Fleet-wide rollout CEILING for runtime agent identity (LLD-26 §7.2).
    # `off` → /v1/validate never resolves a JWT (byte-identical to pre-26).
    # `shadow` → verify + log resolved tid, but DO NOT route onto it.
    # `enforce` → route onto the verified tid; uncredentialed → fail-secure.
    # Effective mode = min(this ceiling, the tenant row's `identity_mode`), so a
    # tenant never rises above the fleet ceiling. Default `off` — no regression.
    tenant_identity_mode: str = Field(
        default="off", validation_alias="TENANT_IDENTITY_MODE"
    )
    # Dedicated / Self-Managed single-tenant pin (LLD-26 §3.6). When set, the
    # verified token is still checked but set_current_tenant() always gets this
    # value, and a tid-mismatch is a hard error. Empty = multi-tenant (default).
    tenant_pin: str = Field(default="", validation_alias="TENANT_PIN")
    # Public-key cache (WS-A A3.1). TTL is a *second* revocation budget alongside
    # token lifetime, so keep it short (≤60s). The revoked-since shared signal is
    # refreshed at most once per `revoked_since_refresh_seconds`.
    credential_cache_ttl_seconds: int = Field(
        default=60, validation_alias="CREDENTIAL_CACHE_TTL_SECONDS"
    )
    credential_cache_max_size: int = Field(
        default=5000, validation_alias="CREDENTIAL_CACHE_MAX_SIZE"
    )
    credential_negative_cache_ttl_seconds: int = Field(
        default=10, validation_alias="CREDENTIAL_NEGATIVE_CACHE_TTL_SECONDS"
    )
    revoked_since_refresh_seconds: int = Field(
        default=10, validation_alias="REVOKED_SINCE_REFRESH_SECONDS"
    )
    # JWT clock-skew leeway (seconds); matters with ≤15-min agent tokens.
    jwt_clock_skew_seconds: int = Field(
        default=60, validation_alias="JWT_CLOCK_SKEW_SECONDS"
    )

    # ------------------------------------------------------------------
    # Cloud Connections (Connect-Account wizard — connections-api-spec.md)
    # ------------------------------------------------------------------
    # Born tenant-scoped (PK tenant_id) — no v1/v2 flag split (it's a net-new
    # table, feature §6 group F / §14.2). Stores a credentials *reference* +
    # scopes only; the assumed role itself lives in the customer account.
    dynamodb_connections_table: str = Field(
        default="sentra-connections",
        validation_alias="CONNECTIONS_TABLE",
    )
    # Discovery cache (feature §8.1): agents the live scan sees in a connected
    # account, persisted so the Detected-Agents list is the real account union
    # (not policy-derived). Born tenant-scoped (PK tenant_id, SK native_resource_id).
    dynamodb_discovery_cache_table: str = Field(
        default="sentra-discovery-cache",
        validation_alias="DISCOVERY_CACHE_TABLE",
    )
    signal_store_ttl_days: int = Field(default=90, validation_alias="SIGNAL_STORE_TTL_DAYS")
    signal_store_write_timeout_ms: int = Field(default=200, validation_alias="SIGNAL_STORE_WRITE_TIMEOUT_MS")
    signal_store_batch_max_retries: int = Field(default=3, validation_alias="SIGNAL_STORE_BATCH_MAX_RETRIES")
    
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
    # WS24 M3.2: how often each task polls the shared sigma version row to detect a
    # rule change (cross-instance invalidation). 10s = fast propagation, one tiny
    # DDB get_item per 10s per task.
    sigma_version_check_interval_seconds: int = Field(
        default=10, validation_alias="SIGMA_VERSION_CHECK_INTERVAL_SECONDS")

    # ML Threat Classifier (Workstream 19 / LLD 19)
    # Disabled by default until WS19 M2 eval harness signs off on precision/recall.
    ml_classifier_enabled: bool = Field(default=False, validation_alias="ML_CLASSIFIER_ENABLED")
    # M3 shadow mode: when true AND ml_classifier_enabled is also true, the
    # validator runs and emits its Signal to the audit log + signal store, but
    # its DENY does NOT influence the live customer verdict. Lets us measure
    # ML's real-world accuracy on production-shaped traffic before flipping it
    # into the combiner. Default off; flip on in shadow phase, then off for active.
    ml_classifier_shadow_mode: bool = Field(default=False, validation_alias="ML_CLASSIFIER_SHADOW_MODE")

    # Cedar authorization engine (feature: cedar-policy).
    # cedar_enabled: master switch for the Cedar policy engine. cedar_shadow_mode:
    # when both are true, CedarPolicyEngine runs ALONGSIDE the legacy policy_engine
    # at STEP 2, records its verdict + any disagreement (Sentra/SecurityController
    # `CedarShadowDiscrepancy` metric), but the LIVE decision stays the legacy
    # engine's — mirrors ml_classifier_shadow_mode. Cutover (CT10): shadow off,
    # enabled on, Cedar takes the policy slot. Both default off.
    cedar_enabled: bool = Field(default=False, validation_alias="CEDAR_ENABLED")
    cedar_shadow_mode: bool = Field(default=False, validation_alias="CEDAR_SHADOW_MODE")
    # Workload isolation lever (LLD 19 §2.4): the validator's invocations route
    # through this Application Inference Profile, separating its quota / cost /
    # CloudWatch metrics from any other Bedrock consumer on the same model family.
    # If unset, the validator falls back to invoking the hot model ID directly
    # (acceptable during early dev; production should have the profile provisioned).
    ml_classifier_inference_profile_arn: str = Field(
        default="",
        validation_alias="ML_CLASSIFIER_INFERENCE_PROFILE_ARN",
    )
    # Hot path: Haiku 4.5 — newer than the 3.5 used by the existing fallback
    # LLM generator, gives a separate Bedrock quota bucket (LLD 19 §2.4).
    ml_classifier_hot_model_id: str = Field(
        default="anthropic.claude-haiku-4-5-20251001-v1:0",
        validation_alias="ML_CLASSIFIER_HOT_MODEL_ID",
    )
    # Escalation: Sonnet 4.6 via US cross-region system inference profile.
    # Sonnet 4.6 (like Haiku 4.5) does NOT support on-demand foundation-model
    # invocation — only inference-profile routing. The bare ID
    # `anthropic.claude-sonnet-4-6-v1:0` returns "The provided model identifier
    # is invalid" from Bedrock. No co-tenancy concern with the agent (no other
    # high-volume inline Sonnet consumer in the account).
    ml_classifier_escalation_model_id: str = Field(
        default="us.anthropic.claude-sonnet-4-6",
        validation_alias="ML_CLASSIFIER_ESCALATION_MODEL_ID",
    )
    # Per-call timeout (each tier independently).
    ml_classifier_timeout_seconds: float = Field(
        default=2.0,
        validation_alias="ML_CLASSIFIER_TIMEOUT_SECONDS",
    )
    # Aggregate ceiling across hot+escalation (LLD 19 §3.2.1). Bounds /v1/validate
    # p99 — without this, worst-case hot+esc = 4s, which blows the latency budget.
    ml_classifier_total_budget_seconds: float = Field(
        default=2.5,
        validation_alias="ML_CLASSIFIER_TOTAL_BUDGET_SECONDS",
    )
    # Above this confidence, trust Haiku and skip escalation.
    ml_confidence_trust_threshold: float = Field(
        default=0.9,
        validation_alias="ML_CONFIDENCE_TRUST_THRESHOLD",
    )
    # Below this confidence, escalate AND fall back to ABSTAIN if escalation
    # also lacks confidence.
    ml_confidence_abstain_threshold: float = Field(
        default=0.5,
        validation_alias="ML_CONFIDENCE_ABSTAIN_THRESHOLD",
    )

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
