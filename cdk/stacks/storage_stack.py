"""
Sentra MVP - Storage Stack
Creates CloudWatch Logs, DynamoDB Tables, and S3 Bucket

Reference: LLD 01 Section 3 (Storage Stack)
ADRs: ADR-006 (CloudWatch for Audit), ADR-013 (DynamoDB On-Demand), ADR-017 (Log Retention)
"""

from aws_cdk import (
    Stack,
    RemovalPolicy,
    CfnOutput,
    Duration,
    aws_logs as logs,
    aws_cloudwatch as cloudwatch,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_ecr as ecr,
)
from constructs import Construct
from typing import Dict, Any

from cdk_constructs.signal_store_table_construct import ValidationSignalStoreTable


class StorageStack(Stack):
    """
    Storage Stack - Persistent Storage Layer

    Creates:
    - CloudWatch Log Group for audit trail (90-day retention)
    - Metric filter for high-severity threats
    - DynamoDB Tables: session-context, policies, demo-orders, demo-customers (Task 6-7)
    - S3 Bucket for artifacts (Task 8)

    Exports:
    - CloudWatch Log Group name and ARN
    - DynamoDB table names and ARNs
    - S3 bucket name and ARN
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        config: Dict[str, Any],
        **kwargs
    ) -> None:
        """
        Initialize Storage Stack

        Args:
            scope: CDK app scope
            construct_id: Stack identifier
            config: Configuration dict from YAML (no hard-coded values)
            **kwargs: Additional stack properties
        """
        super().__init__(scope, construct_id, **kwargs)

        # Extract configuration
        storage_config = config.get("storage", {})
        naming_config = config.get("naming", {})

        # ============================================================
        # CloudWatch Log Group for Audit Trail (Task 5)
        # ============================================================
        # See LLD Section 3.2 and ADR-006 for CloudWatch Logs design
        # Purpose: Immutable audit trail of all validation decisions
        # Retention: 90 days (compliance requirement - SOC2, HIPAA)
        # Cost: ~$0.50/GB ingestion + $0.03/GB storage/month

        audit_log_config = storage_config.get("audit_logs", {})

        # Map retention days to CDK enum (CDK only supports specific values)
        retention_days = audit_log_config.get("retention_days", 90)
        retention_map = {
            1: logs.RetentionDays.ONE_DAY,
            3: logs.RetentionDays.THREE_DAYS,
            5: logs.RetentionDays.FIVE_DAYS,
            7: logs.RetentionDays.ONE_WEEK,
            14: logs.RetentionDays.TWO_WEEKS,
            30: logs.RetentionDays.ONE_MONTH,
            60: logs.RetentionDays.TWO_MONTHS,
            90: logs.RetentionDays.THREE_MONTHS,
            120: logs.RetentionDays.FOUR_MONTHS,
            150: logs.RetentionDays.FIVE_MONTHS,
            180: logs.RetentionDays.SIX_MONTHS,
            365: logs.RetentionDays.ONE_YEAR,
        }
        retention = retention_map.get(retention_days, logs.RetentionDays.THREE_MONTHS)

        self.audit_log_group = logs.LogGroup(
            self,
            "AuditLogGroup",
            log_group_name=audit_log_config.get("log_group_name", "/sentra/audit-logs"),
            retention=retention,
            removal_policy=RemovalPolicy.RETAIN,  # RETAIN for compliance - must manually delete
        )

        # ============================================================
        # Metric Filter for High-Severity Threats
        # ============================================================
        # Create CloudWatch metric from log events where threat_severity = "HIGH"
        # This metric will be used by MonitoringStack for alarms
        # Using text pattern filter (JSON pattern not available in this CDK version)

        # Note: Metric filters will be created later when we have actual log data
        # For now, we'll skip metric filters in Task 5 and add them in MonitoringStack (Task 14)
        # This simplifies the initial deployment and avoids filter pattern issues

        # self.high_severity_metric_filter = logs.MetricFilter(
        #     self,
        #     "HighSeverityThreatFilter",
        #     log_group=self.audit_log_group,
        #     metric_namespace="Sentra/Security",
        #     metric_name="HighSeverityThreats",
        #     filter_pattern=logs.FilterPattern.all_terms("threat_severity", "HIGH"),
        #     metric_value="1",
        #     default_value=0,
        # )

        # ============================================================
        # CloudFormation Outputs
        # ============================================================

        # Audit Log Group Outputs
        CfnOutput(
            self,
            "AuditLogGroupName",
            value=self.audit_log_group.log_group_name,
            description="CloudWatch Log Group name for audit trail (90-day retention)",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-audit-log-group-name",
        )

        CfnOutput(
            self,
            "AuditLogGroupArn",
            value=self.audit_log_group.log_group_arn,
            description="CloudWatch Log Group ARN for audit trail",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-audit-log-group-arn",
        )

        # ============================================================
        # DynamoDB Table 1: sentra-session-context (Task 6)
        # ============================================================
        # Purpose: Track CURRENT state of active sessions for real-time policy decisions
        # See LLD Section 3.3.1 for full schema details
        # Access Pattern: GetItem by session_id (most frequent, < 10ms)
        # TTL: 24 hours (ephemeral session data)

        dynamodb_config = storage_config.get("dynamodb", {})
        session_context_config = dynamodb_config.get("session_context", {})

        self.session_context_table = dynamodb.Table(
            self,
            "SessionContextTable",
            table_name=session_context_config.get("table_name", "sentra-session-context"),
            partition_key=dynamodb.Attribute(
                name="session_id",
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,  # On-demand pricing (ADR-013)
            time_to_live_attribute="ttl",  # Auto-expire sessions after 24 hours
            point_in_time_recovery=False,  # Ephemeral data - no PITR needed
            removal_policy=RemovalPolicy.DESTROY,  # Can delete when stack destroyed
            stream=dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,  # Optional: for analytics
        )

        # GSI: agent-updated-index (agent_id, last_activity)
        # Access Pattern: Query all active sessions for a specific agent
        self.session_context_table.add_global_secondary_index(
            index_name="agent-updated-index",
            partition_key=dynamodb.Attribute(
                name="agent_id",
                type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="last_activity",
                type=dynamodb.AttributeType.NUMBER
            ),
            projection_type=dynamodb.ProjectionType.ALL,  # Include all attributes
        )

        # NOTE: the legacy `sentra-policies` table (pre-hybrid-storage, Task 6)
        # has been retired. Policies now live in `sentra-policies-metadata`
        # (metadata) + S3 (full YAML). Nothing read the legacy table at runtime
        # (validator, dashboard, health check all use the metadata table), so the
        # table + its grants/env/outputs were removed (cleanup, 2026-06).

        # ============================================================
        # CloudFormation Outputs - DynamoDB Tables (Task 6)
        # ============================================================

        # Session Context Table Outputs
        CfnOutput(
            self,
            "SessionContextTableName",
            value=self.session_context_table.table_name,
            description="DynamoDB table name for session context (ephemeral session state)",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-session-context-table-name",
        )

        CfnOutput(
            self,
            "SessionContextTableArn",
            value=self.session_context_table.table_arn,
            description="DynamoDB table ARN for session context",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-session-context-table-arn",
        )


        # ============================================================
        # DynamoDB Table 3: sentra-demo-orders (Task 7)
        # ============================================================
        # Purpose: Mock order database for demo
        # See LLD Section 3.3.3 for full schema details
        # Access Pattern: GetItem by order_id, Query by customer_id
        # Data: Pre-seeded with 500 sample orders

        demo_orders_config = dynamodb_config.get("demo_orders", {})

        self.demo_orders_table = dynamodb.Table(
            self,
            "DemoOrdersTable",
            table_name=demo_orders_config.get("table_name", "sentra-demo-orders"),
            partition_key=dynamodb.Attribute(
                name="order_id",
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,  # On-demand pricing
            point_in_time_recovery=False,  # Demo data - no PITR needed
            removal_policy=RemovalPolicy.DESTROY,  # Can delete when stack destroyed
        )

        # GSI: customer-index (customer_id, created_at)
        # Access Pattern: Get all orders for a specific customer
        self.demo_orders_table.add_global_secondary_index(
            index_name="customer-index",
            partition_key=dynamodb.Attribute(
                name="customer_id",
                type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="created_at",
                type=dynamodb.AttributeType.NUMBER
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # GSI: transaction-index (transaction_id) - SPARSE INDEX
        # Access Pattern: Lookup order by transaction_id for refund rollback
        # Note: transaction_id is only present on orders that have been refunded
        # Used by Payment Agent's reverse_refund tool (LLD 07 Section 4.4)
        self.demo_orders_table.add_global_secondary_index(
            index_name="transaction-index",
            partition_key=dynamodb.Attribute(
                name="transaction_id",
                type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # ============================================================
        # DynamoDB Table 4: sentra-demo-customers (Task 7)
        # ============================================================
        # Purpose: Mock customer database (data exfiltration demo)
        # See LLD Section 3.3.4 for full schema details
        # Access Pattern: GetItem by customer_id, Query by state
        # Data: Pre-seeded with 500 sample customers (includes fake SSNs for PII detection)

        demo_customers_config = dynamodb_config.get("demo_customers", {})

        self.demo_customers_table = dynamodb.Table(
            self,
            "DemoCustomersTable",
            table_name=demo_customers_config.get("table_name", "sentra-demo-customers"),
            partition_key=dynamodb.Attribute(
                name="customer_id",
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,  # On-demand pricing
            point_in_time_recovery=False,  # Demo data - no PITR needed
            removal_policy=RemovalPolicy.DESTROY,  # Can delete when stack destroyed
        )

        # GSI: state-index (state, created_at)
        # Access Pattern: Query customers by state (for testing data exfiltration scenarios)
        # Distribution: 150 CA, 100 NY, 80 TX, 70 FL, 100 other states
        self.demo_customers_table.add_global_secondary_index(
            index_name="state-index",
            partition_key=dynamodb.Attribute(
                name="state",
                type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="created_at",
                type=dynamodb.AttributeType.NUMBER
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # ============================================================
        # CloudFormation Outputs - Demo Tables (Task 7)
        # ============================================================

        # Demo Orders Table Outputs
        CfnOutput(
            self,
            "DemoOrdersTableName",
            value=self.demo_orders_table.table_name,
            description="DynamoDB table name for demo orders (500 sample orders)",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-demo-orders-table-name",
        )

        CfnOutput(
            self,
            "DemoOrdersTableArn",
            value=self.demo_orders_table.table_arn,
            description="DynamoDB table ARN for demo orders",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-demo-orders-table-arn",
        )

        # Demo Customers Table Outputs
        CfnOutput(
            self,
            "DemoCustomersTableName",
            value=self.demo_customers_table.table_name,
            description="DynamoDB table name for demo customers (500 sample customers with fake PII)",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-demo-customers-table-name",
        )

        CfnOutput(
            self,
            "DemoCustomersTableArn",
            value=self.demo_customers_table.table_arn,
            description="DynamoDB table ARN for demo customers",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-demo-customers-table-arn",
        )

        # ============================================================
        # DynamoDB Table 5: sentra-agent-registry (Workstream 6, Task 1)
        # ============================================================
        # Purpose: Store agent metadata (name, description, ECS config, runtime config)
        # See LLD 06 Section 2.1 for full schema details
        # Access Pattern: GetItem by agent_id, Query by status
        # Data: Pre-seeded with 3-5 agents (customer-query-agent, payment-agent, security-controller)

        agent_registry_config = dynamodb_config.get("agent_registry", {})

        self.agent_registry_table = dynamodb.Table(
            self,
            "AgentRegistryTable",
            table_name=agent_registry_config.get("table_name", "sentra-agent-registry"),
            partition_key=dynamodb.Attribute(
                name="agent_id",
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,  # On-demand pricing (ADR-013)
            point_in_time_recovery=True,  # Critical metadata - enable PITR
            removal_policy=RemovalPolicy.RETAIN,  # RETAIN for production safety
        )

        # GSI: status-index (status)
        # Access Pattern: Query all active agents
        self.agent_registry_table.add_global_secondary_index(
            index_name="status-index",
            partition_key=dynamodb.Attribute(
                name="status",
                type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # NOTE (WS-21 T04, Kiro review): a `cloud-provider-index` GSI was
        # considered for the Cloud-Provider Distribution, but at MVP scale the
        # distribution is computed with a small table Scan (get_cloud_provider_
        # distribution). Provisioning an unused GSI only adds write-amplification
        # + storage for zero read benefit, so it is intentionally NOT created
        # here. Re-add it in P1 (with per-provider Select=COUNT queries) once the
        # fleet is large enough that the Scan cost matters. The `cloud_provider`
        # attribute itself IS stored (seeded) and used by the Scan-based grouping.

        # ============================================================
        # CloudFormation Outputs - Agent Registry Table (Workstream 6, Task 1)
        # ============================================================

        CfnOutput(
            self,
            "AgentRegistryTableName",
            value=self.agent_registry_table.table_name,
            description="DynamoDB table name for agent registry (agent metadata)",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-agent-registry-table-name",
        )

        CfnOutput(
            self,
            "AgentRegistryTableArn",
            value=self.agent_registry_table.table_arn,
            description="DynamoDB table ARN for agent registry",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-agent-registry-table-arn",
        )

        # ============================================================
        # DynamoDB Table 6: sentra-tool-registry (Workstream 6, Task 2)
        # ============================================================
        # Purpose: Store tool definitions (name, type, parameters, validation rules)
        # See LLD 06 Section 2.2 for full schema details
        # Access Pattern: GetItem by tool_id, Query by tool_type (READ/WRITE)
        # Data: Pre-seeded with 15-20 tools

        tool_registry_config = dynamodb_config.get("tool_registry", {})

        self.tool_registry_table = dynamodb.Table(
            self,
            "ToolRegistryTable",
            table_name=tool_registry_config.get("table_name", "sentra-tool-registry"),
            partition_key=dynamodb.Attribute(
                name="tool_id",
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,  # On-demand pricing (ADR-013)
            point_in_time_recovery=True,  # Critical metadata - enable PITR
            removal_policy=RemovalPolicy.RETAIN,  # RETAIN for production safety
        )

        # GSI: type-index (tool_type)
        # Access Pattern: Query all READ tools or all WRITE tools
        self.tool_registry_table.add_global_secondary_index(
            index_name="type-index",
            partition_key=dynamodb.Attribute(
                name="tool_type",
                type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # ============================================================
        # CloudFormation Outputs - Tool Registry Table (Workstream 6, Task 2)
        # ============================================================

        CfnOutput(
            self,
            "ToolRegistryTableName",
            value=self.tool_registry_table.table_name,
            description="DynamoDB table name for tool registry (tool definitions)",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-tool-registry-table-name",
        )

        CfnOutput(
            self,
            "ToolRegistryTableArn",
            value=self.tool_registry_table.table_arn,
            description="DynamoDB table ARN for tool registry",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-tool-registry-table-arn",
        )

        # ============================================================
        # DynamoDB Table 7: sentra-policies-metadata (Workstream 6, Task 3)
        # ============================================================
        # Purpose: Store policy metadata (actual policy content in S3)
        # See LLD 06 Section 2.3 for full schema details
        # Access Pattern: GetItem by policy_id, Query by agent_id, Query by status
        # Data: Pre-seeded with 3-5 policy metadata items (content in S3)

        policies_metadata_config = dynamodb_config.get("policies_metadata", {})

        self.policies_metadata_table = dynamodb.Table(
            self,
            "PoliciesMetadataTable",
            table_name=policies_metadata_config.get("table_name", "sentra-policies-metadata"),
            partition_key=dynamodb.Attribute(
                name="policy_id",
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,  # On-demand pricing (ADR-013)
            point_in_time_recovery=True,  # Critical metadata - enable PITR
            removal_policy=RemovalPolicy.RETAIN,  # RETAIN for production safety
        )

        # GSI: agent-index (agent_id)
        # Access Pattern: Query all policies for a specific agent
        self.policies_metadata_table.add_global_secondary_index(
            index_name="agent-index",
            partition_key=dynamodb.Attribute(
                name="agent_id",
                type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # GSI: status-index (status)
        # Access Pattern: Query all active policies
        self.policies_metadata_table.add_global_secondary_index(
            index_name="status-index",
            partition_key=dynamodb.Attribute(
                name="status",
                type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # ============================================================
        # CloudFormation Outputs - Policies Metadata Table (Workstream 6, Task 3)
        # ============================================================

        CfnOutput(
            self,
            "PoliciesMetadataTableName",
            value=self.policies_metadata_table.table_name,
            description="DynamoDB table name for policies metadata (content in S3)",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-policies-metadata-table-name",
        )

        CfnOutput(
            self,
            "PoliciesMetadataTableArn",
            value=self.policies_metadata_table.table_arn,
            description="DynamoDB table ARN for policies metadata",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-policies-metadata-table-arn",
        )

        # ============================================================
        # DynamoDB Table 8: sentra-sigma-rules-metadata (Workstream 6, Task 4)
        # ============================================================
        # Purpose: Store Sigma rule metadata (actual rule content in S3)
        # See LLD 06 Section 2.4 for full schema details
        # Access Pattern: GetItem by rule_id, Query by level, Query by status
        # Data: Pre-seeded with 15-20 Sigma rule metadata items (content in S3)

        sigma_rules_metadata_config = dynamodb_config.get("sigma_rules_metadata", {})

        self.sigma_rules_metadata_table = dynamodb.Table(
            self,
            "SigmaRulesMetadataTable",
            table_name=sigma_rules_metadata_config.get("table_name", "sentra-sigma-rules-metadata"),
            partition_key=dynamodb.Attribute(
                name="rule_id",
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,  # On-demand pricing (ADR-013)
            point_in_time_recovery=True,  # Critical metadata - enable PITR
            removal_policy=RemovalPolicy.RETAIN,  # RETAIN for production safety
        )

        # GSI: level-index (level)
        # Access Pattern: Query all critical/high/medium/low severity rules
        self.sigma_rules_metadata_table.add_global_secondary_index(
            index_name="level-index",
            partition_key=dynamodb.Attribute(
                name="level",
                type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # GSI: status-index (status)
        # Access Pattern: Query all stable/experimental/deprecated rules
        self.sigma_rules_metadata_table.add_global_secondary_index(
            index_name="status-index",
            partition_key=dynamodb.Attribute(
                name="status",
                type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # ============================================================
        # CloudFormation Outputs - Sigma Rules Metadata Table (Workstream 6, Task 4)
        # ============================================================

        CfnOutput(
            self,
            "SigmaRulesMetadataTableName",
            value=self.sigma_rules_metadata_table.table_name,
            description="DynamoDB table name for Sigma rules metadata (content in S3)",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-sigma-rules-metadata-table-name",
        )

        CfnOutput(
            self,
            "SigmaRulesMetadataTableArn",
            value=self.sigma_rules_metadata_table.table_arn,
            description="DynamoDB table ARN for Sigma rules metadata",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-sigma-rules-metadata-table-arn",
        )

        # ============================================================
        # S3 Bucket for Artifacts (Task 8)
        # ============================================================
        # Purpose: Store policies, Sigma rules, SBOMs, compliance exports, debug logs
        # See LLD Section 3.4 for folder structure and lifecycle policies
        # Encryption: S3-managed (SSE-S3)
        # Versioning: Enabled for rollback capability
        # Public Access: Completely blocked

        s3_config = storage_config.get("s3", {})

        self.artifacts_bucket = s3.Bucket(
            self,
            "ArtifactsBucket",
            bucket_name=None,  # Let CloudFormation generate unique name
            encryption=s3.BucketEncryption.S3_MANAGED,  # SSE-S3 encryption
            versioned=s3_config.get("versioning", True),  # Enable versioning for rollback
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,  # Block all public access
            removal_policy=RemovalPolicy.RETAIN,  # RETAIN artifacts on stack deletion
            auto_delete_objects=False,  # Require explicit manual deletion
            enforce_ssl=True,  # Require SSL/TLS for all requests
        )

        # ============================================================
        # S3 Lifecycle Rules (Task 8)
        # ============================================================
        # Rule 1: Archive compliance exports to Glacier after 30 days
        # Rule 2: Delete debug logs after 7 days
        # Rule 3: Keep sigma_rules, sbom, policies forever

        # Lifecycle Rule 1: Archive compliance exports to Glacier after 30 days
        compliance_archive_days = s3_config.get("lifecycle_rules", {}).get("compliance_archive_days", 30)
        self.artifacts_bucket.add_lifecycle_rule(
            id="ArchiveComplianceExports",
            prefix="compliance_exports/",
            transitions=[
                s3.Transition(
                    storage_class=s3.StorageClass.GLACIER,
                    transition_after=Duration.days(compliance_archive_days),
                )
            ],
            enabled=True,
        )

        # Lifecycle Rule 2: Delete debug logs after 7 days
        debug_logs_delete_days = s3_config.get("lifecycle_rules", {}).get("debug_logs_delete_days", 7)
        self.artifacts_bucket.add_lifecycle_rule(
            id="DeleteDebugLogs",
            prefix="debug_logs/",
            expiration=Duration.days(debug_logs_delete_days),
            enabled=True,
        )

        # Note: No lifecycle rules for sigma_rules/, sbom/, policies/ - keep forever

        # ============================================================
        # CloudFormation Outputs - S3 Bucket (Task 8)
        # ============================================================

        CfnOutput(
            self,
            "ArtifactsBucketName",
            value=self.artifacts_bucket.bucket_name,
            description="S3 bucket name for artifacts (policies, Sigma rules, SBOMs, exports)",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-artifacts-bucket-name",
        )

        CfnOutput(
            self,
            "ArtifactsBucketArn",
            value=self.artifacts_bucket.bucket_arn,
            description="S3 bucket ARN for artifacts",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-artifacts-bucket-arn",
        )

        CfnOutput(
            self,
            "ArtifactsBucketDomainName",
            value=self.artifacts_bucket.bucket_regional_domain_name,
            description="S3 bucket regional domain name for artifacts",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-artifacts-bucket-domain",
        )

        # ============================================================
        # DynamoDB Table: sentra-validation-signals (Workstream 17)
        # ============================================================
        # Purpose: Multi-signal substrate — one row per validator's
        # contribution to a /v1/validate decision. Replaces CloudWatch
        # Logs Insights on the dashboard's hot-read path; CW kept as
        # compliance archive (dual-write).
        # See LLD 17 §5.2 for full schema rationale.

        signal_store_config = dynamodb_config.get("validation_signals", {})

        self.validation_signal_store = ValidationSignalStoreTable(
            self,
            "ValidationSignalStore",
            table_name=signal_store_config.get(
                "table_name", "sentra-validation-signals"
            ),
        )

        CfnOutput(
            self,
            "ValidationSignalStoreTableName",
            value=self.validation_signal_store.table_name,
            description="DynamoDB table name for validation signal store (LLD 17)",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-validation-signals-table-name",
        )

        CfnOutput(
            self,
            "ValidationSignalStoreTableArn",
            value=self.validation_signal_store.table_arn,
            description="DynamoDB table ARN for validation signal store",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-validation-signals-table-arn",
        )

        # ============================================================
        # Tenancy v2 Tables (Multi-Cloud Agent Import — P0a, Workstream M0a/T01)
        # ============================================================
        # Multi-tenant variants of the four runtime tables. `tenant_id` is the
        # partition key on every store (feature §14.2); the old PK becomes the
        # sort key, so a tenant Query() is the natural isolation boundary and
        # get_item is an exact (tenant_id, entity_id) lookup.
        #
        # Agent-keyed GSIs key off a composite `tenant_agent_id` attribute
        # (`{tenant}#{agent_id}`) so the plain `agent_id` attribute is never
        # clobbered; the compliance GSI keys off `tenant_decision_date`.
        #
        # These are created EMPTY and read/written only behind TENANCY_V2_ENABLED
        # (workstream §1.2). Removal policies mirror their v1 counterparts (T5)
        # so a flag-rollback keeps both schemas intact.

        # agent-registry-v2: PK tenant_id / SK agent_id; status-index (tenant_id / status)
        self.agent_registry_table_v2 = dynamodb.Table(
            self,
            "AgentRegistryTableV2",
            table_name=agent_registry_config.get("table_name_v2", "sentra-agent-registry-v2"),
            partition_key=dynamodb.Attribute(name="tenant_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="agent_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery=True,
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.agent_registry_table_v2.add_global_secondary_index(
            index_name="status-index",
            partition_key=dynamodb.Attribute(name="tenant_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="status", type=dynamodb.AttributeType.STRING),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # policies-metadata-v2: PK tenant_id / SK policy_id;
        #   agent-index (tenant_agent_id), status-index (tenant_id / status)
        self.policies_metadata_table_v2 = dynamodb.Table(
            self,
            "PoliciesMetadataTableV2",
            table_name=policies_metadata_config.get("table_name_v2", "sentra-policies-metadata-v2"),
            partition_key=dynamodb.Attribute(name="tenant_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="policy_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery=True,
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.policies_metadata_table_v2.add_global_secondary_index(
            index_name="agent-index",
            partition_key=dynamodb.Attribute(name="tenant_agent_id", type=dynamodb.AttributeType.STRING),
            projection_type=dynamodb.ProjectionType.ALL,
        )
        self.policies_metadata_table_v2.add_global_secondary_index(
            index_name="status-index",
            partition_key=dynamodb.Attribute(name="tenant_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="status", type=dynamodb.AttributeType.STRING),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # session-context-v2: PK tenant_id / SK session_id;
        #   agent-updated-index (tenant_agent_id / last_activity). DESTROY (ephemeral).
        self.session_context_table_v2 = dynamodb.Table(
            self,
            "SessionContextTableV2",
            table_name=session_context_config.get("table_name_v2", "sentra-session-context-v2"),
            partition_key=dynamodb.Attribute(name="tenant_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="session_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            point_in_time_recovery=False,
            removal_policy=RemovalPolicy.DESTROY,
            stream=dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,
        )
        self.session_context_table_v2.add_global_secondary_index(
            index_name="agent-updated-index",
            partition_key=dynamodb.Attribute(name="tenant_agent_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="last_activity", type=dynamodb.AttributeType.NUMBER),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # validation-signals-v2: tenant-scoped variant of the LLD 17 construct.
        self.validation_signal_store_v2 = ValidationSignalStoreTable(
            self,
            "ValidationSignalStoreV2",
            table_name=signal_store_config.get(
                "table_name_v2", "sentra-validation-signals-v2"
            ),
            tenant_scoped=True,
        )

        # Cloud Connections (Connect-Account wizard — connections-api-spec.md).
        # Born tenant-scoped (PK tenant_id, SK id) — net-new table, no v1/v2 flag.
        # Stores a credentials *reference* (role_arn) + minted external_id + scopes,
        # never a secret. RETAIN: losing a connection record orphans the binding.
        connections_config = dynamodb_config.get("connections", {})
        self.connections_table = dynamodb.Table(
            self,
            "ConnectionsTable",
            table_name=connections_config.get("table_name", "sentra-connections"),
            partition_key=dynamodb.Attribute(name="tenant_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery=True,
            removal_policy=RemovalPolicy.RETAIN,
        )
        CfnOutput(
            self,
            "ConnectionsTableName",
            value=self.connections_table.table_name,
            description="DynamoDB table name for cloud connections (Connect-Account wizard)",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-connections-table-name",
        )

        # Discovery cache (feature §8.1) — agents the live scan finds in a
        # connected account. Born tenant-scoped (PK tenant_id, SK native_resource_id);
        # the Detected-Agents union dedupes registry ∪ this on native_resource_id.
        discovery_cache_config = dynamodb_config.get("discovery_cache", {})
        self.discovery_cache_table = dynamodb.Table(
            self,
            "DiscoveryCacheTable",
            table_name=discovery_cache_config.get("table_name", "sentra-discovery-cache"),
            partition_key=dynamodb.Attribute(name="tenant_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="native_resource_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery=False,
            removal_policy=RemovalPolicy.RETAIN,
        )
        CfnOutput(
            self,
            "DiscoveryCacheTableName",
            value=self.discovery_cache_table.table_name,
            description="DynamoDB table name for discovery cache (scanned cloud agents)",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-discovery-cache-table-name",
        )

        for _logical, _table in {
            "agent-registry-v2": self.agent_registry_table_v2,
            "policies-metadata-v2": self.policies_metadata_table_v2,
            "session-context-v2": self.session_context_table_v2,
            "validation-signals-v2": self.validation_signal_store_v2,
        }.items():
            CfnOutput(
                self,
                f"{_logical.replace('-', ' ').title().replace(' ', '')}TableName",
                value=_table.table_name,
                description=f"DynamoDB table name for {_logical} (tenancy v2)",
                export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-{_logical}-table-name",
            )

        # ============================================================
        # Multi-Tenancy: registry, membership & agent credentials (LLD-26)
        #   WS-D D1 — sentra-tenants, sentra-tenant-members (+ GSI)
        #   WS-A A1 — sentra-agent-credentials (+ kid-index GSI)
        # All three are net-new, born tenant-scoped, and unread on the hot path
        # until identity rollout — additive, regression-free. RETAIN: these hold
        # the tenant registry + the public keys that establish agent identity;
        # losing them strands every tenant.
        # ============================================================
        tenancy_cfg = dynamodb_config.get("multitenancy", {})

        # sentra-tenants — PK tenant_id (immutable slug). The `identity_mode`
        # attribute on each row is the authoritative per-tenant rollout control
        # (WS-A/WS-B read it); no GSI — lookups are by tenant_id.
        self.tenants_table = dynamodb.Table(
            self,
            "TenantsTable",
            table_name=tenancy_cfg.get("tenants_table_name", "sentra-tenants"),
            partition_key=dynamodb.Attribute(name="tenant_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # sentra-tenant-members — PK operator_sub / SK tenant_id (membership pair).
        # GSI tenant-members-index (PK tenant_id) lists all operators in a tenant
        # for the members-admin screen (WS-C).
        self.tenant_members_table = dynamodb.Table(
            self,
            "TenantMembersTable",
            table_name=tenancy_cfg.get("tenant_members_table_name", "sentra-tenant-members"),
            partition_key=dynamodb.Attribute(name="operator_sub", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="tenant_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery=True,
            # Pending invites are time-boxed rows (operator_sub = `_invite#<token>`)
            # carrying a `ttl`; real membership rows omit it and never expire.
            time_to_live_attribute="ttl",
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.tenant_members_table.add_global_secondary_index(
            index_name="tenant-members-index",
            partition_key=dynamodb.Attribute(name="tenant_id", type=dynamodb.AttributeType.STRING),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # sentra-agent-credentials — PK tenant_id / SK key_id ({agent_id}#{kid}).
        # GSI kid-index (PK kid) is the ONE pre-tenant lookup that establishes the
        # tenant at verify time; kid is a globally-unique UUID so no hot partition.
        self.agent_credentials_table = dynamodb.Table(
            self,
            "AgentCredentialsTable",
            table_name=tenancy_cfg.get("agent_credentials_table_name", "sentra-agent-credentials"),
            partition_key=dynamodb.Attribute(name="tenant_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="key_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery=True,
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.agent_credentials_table.add_global_secondary_index(
            index_name="kid-index",
            partition_key=dynamodb.Attribute(name="kid", type=dynamodb.AttributeType.STRING),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # sentra-quota-counters — per-tenant write-sharded RPS counters (WS-E E2b).
        # PK tenant_id / SK counter_key (`_rps#{window}#{shard}`); rows auto-reap
        # via the `ttl` attribute. DESTROY: pure ephemeral rate state, no value lost.
        self.quota_counters_table = dynamodb.Table(
            self,
            "QuotaCountersTable",
            table_name=tenancy_cfg.get("quota_counters_table_name", "sentra-quota-counters"),
            partition_key=dynamodb.Attribute(name="tenant_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="counter_key", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            point_in_time_recovery=False,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # sentra-identity-fallback — residual uncredentialed-agent legacy-fallback
        # window (WS-B B1). PK agent_id (self-asserted) with tenant_id as a plain
        # attribute; rows auto-reap past their deadline via `ttl`. DESTROY: pure
        # transitional ramp state, no durable value.
        self.identity_fallback_table = dynamodb.Table(
            self,
            "IdentityFallbackTable",
            table_name=tenancy_cfg.get("identity_fallback_table_name", "sentra-identity-fallback"),
            partition_key=dynamodb.Attribute(name="agent_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            point_in_time_recovery=False,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # sentra-platform-audit-records — append-only audit of platform-admin
        # cross-tenant reads (WS-E E3 / §10 Q2). PK tenant_id (target) / SK
        # record_id ({ms}#{uuid}). RETAIN + PITR: these are immutable compliance
        # records, never auto-deleted with a stack teardown.
        self.platform_audit_table = dynamodb.Table(
            self,
            "PlatformAuditRecordsTable",
            table_name=tenancy_cfg.get("platform_audit_table_name", "sentra-platform-audit-records"),
            partition_key=dynamodb.Attribute(name="tenant_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="record_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        for _logical, _table in {
            "tenants": self.tenants_table,
            "tenant-members": self.tenant_members_table,
            "agent-credentials": self.agent_credentials_table,
            "quota-counters": self.quota_counters_table,
            "identity-fallback": self.identity_fallback_table,
            "platform-audit-records": self.platform_audit_table,
        }.items():
            CfnOutput(
                self,
                f"{_logical.replace('-', ' ').title().replace(' ', '')}TableName",
                value=_table.table_name,
                description=f"DynamoDB table name for {_logical} (multi-tenancy, LLD-26)",
                export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-{_logical}-table-name",
            )

        # ============================================================
        # ECR Repositories (Task 9 - moved from Compute Stack)
        # ============================================================
        ecr_config = config.get("compute", {}).get("ecr", {})
        prefix = naming_config.get("prefix", "sentra-mvp")

        repository_names = ["security-controller", "dashboard", "customer-query-agent", "payment-agent", "demo-orchestrator", "console", "canary"]  # WS-J Ji.2: sentra/canary (8th image, ECS synthetic monitor)
        self.ecr_repositories = {}

        for repo_name in repository_names:
            repository = ecr.Repository(
                self,
                f"{repo_name.replace('-', ' ').title().replace(' ', '')}Repository",
                repository_name=f"sentra/{repo_name}",
                image_scan_on_push=ecr_config.get("image_scan_on_push", True),
                image_tag_mutability=ecr.TagMutability.MUTABLE,
                removal_policy=RemovalPolicy.DESTROY,
                auto_delete_images=True,  # Auto-delete all images when stack is destroyed
                lifecycle_rules=[ecr.LifecycleRule(description="Keep last 10 images", max_image_count=10, rule_priority=1)],
            )
            self.ecr_repositories[repo_name] = repository
            CfnOutput(self, f"{repo_name.replace('-', ' ').title().replace(' ', '')}RepositoryUri",
                value=repository.repository_uri, description=f"ECR repository URI for {repo_name}",
                export_name=f"{prefix}-{repo_name}-ecr-uri")

    @property
    def audit_log_group_name(self) -> str:
        """Return audit log group name for cross-stack references"""
        return self.audit_log_group.log_group_name

    @property
    def audit_log_group_arn(self) -> str:
        """Return audit log group ARN for IAM permissions"""
        return self.audit_log_group.log_group_arn

    # DynamoDB Table Properties (Task 6)
    @property
    def session_context_table_name(self) -> str:
        """Return session context table name for cross-stack references"""
        return self.session_context_table.table_name

    @property
    def session_context_table_arn(self) -> str:
        """Return session context table ARN for IAM permissions"""
        return self.session_context_table.table_arn

    # DynamoDB Demo Table Properties (Task 7)
    @property
    def demo_orders_table_name(self) -> str:
        """Return demo orders table name for cross-stack references"""
        return self.demo_orders_table.table_name

    @property
    def demo_orders_table_arn(self) -> str:
        """Return demo orders table ARN for IAM permissions"""
        return self.demo_orders_table.table_arn

    @property
    def demo_customers_table_name(self) -> str:
        """Return demo customers table name for cross-stack references"""
        return self.demo_customers_table.table_name

    @property
    def demo_customers_table_arn(self) -> str:
        """Return demo customers table ARN for IAM permissions"""
        return self.demo_customers_table.table_arn

    # S3 Bucket Properties (Task 8)
    @property
    def artifacts_bucket_name(self) -> str:
        """Return artifacts bucket name for cross-stack references"""
        return self.artifacts_bucket.bucket_name

    @property
    def artifacts_bucket_arn(self) -> str:
        """Return artifacts bucket ARN for IAM permissions"""
        return self.artifacts_bucket.bucket_arn

    # Agent Registry Table Properties (Workstream 6, Task 1)
    @property
    def agent_registry_table_name(self) -> str:
        """Return agent registry table name for cross-stack references"""
        return self.agent_registry_table.table_name

    @property
    def agent_registry_table_arn(self) -> str:
        """Return agent registry table ARN for IAM permissions"""
        return self.agent_registry_table.table_arn

    # Tool Registry Table Properties (Workstream 6, Task 2)
    @property
    def tool_registry_table_name(self) -> str:
        """Return tool registry table name for cross-stack references"""
        return self.tool_registry_table.table_name

    @property
    def tool_registry_table_arn(self) -> str:
        """Return tool registry table ARN for IAM permissions"""
        return self.tool_registry_table.table_arn

    # Policies Metadata Table Properties (Workstream 6, Task 3)
    @property
    def policies_metadata_table_name(self) -> str:
        """Return policies metadata table name for cross-stack references"""
        return self.policies_metadata_table.table_name

    @property
    def policies_metadata_table_arn(self) -> str:
        """Return policies metadata table ARN for IAM permissions"""
        return self.policies_metadata_table.table_arn

    # Sigma Rules Metadata Table Properties (Workstream 6, Task 4)
    @property
    def sigma_rules_metadata_table_name(self) -> str:
        """Return Sigma rules metadata table name for cross-stack references"""
        return self.sigma_rules_metadata_table.table_name

    @property
    def sigma_rules_metadata_table_arn(self) -> str:
        """Return Sigma rules metadata table ARN for IAM permissions"""
        return self.sigma_rules_metadata_table.table_arn

    # Validation Signal Store Properties (Workstream 17)
    @property
    def validation_signal_store_table_name(self) -> str:
        return self.validation_signal_store.table_name

    @property
    def validation_signal_store_table_arn(self) -> str:
        return self.validation_signal_store.table_arn

    @property
    def connections_table_name(self) -> str:
        return self.connections_table.table_name

    @property
    def connections_table_arn(self) -> str:
        return self.connections_table.table_arn

    @property
    def discovery_cache_table_name(self) -> str:
        return self.discovery_cache_table.table_name

    @property
    def discovery_cache_table_arn(self) -> str:
        return self.discovery_cache_table.table_arn

    # Tenancy v2 Table Properties (Multi-Cloud Agent Import — P0a/T01)
    @property
    def tenancy_v2_tables(self) -> list:
        """All four tenancy-v2 `dynamodb.Table` constructs, for IAM grants."""
        return [
            self.agent_registry_table_v2,
            self.policies_metadata_table_v2,
            self.session_context_table_v2,
            self.validation_signal_store_v2.table,
        ]

    # Multi-Tenancy Table Properties (LLD-26 — WS-D D1 / WS-A A1)
    @property
    def multitenancy_tables(self) -> list:
        """tenants / tenant-members / agent-credentials `dynamodb.Table`
        constructs, for IAM grants (read+write incl. their GSIs)."""
        return [
            self.tenants_table,
            self.tenant_members_table,
            self.agent_credentials_table,
            self.quota_counters_table,
            self.identity_fallback_table,
            self.platform_audit_table,
        ]
