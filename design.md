> ⚠️ **DEPRECATED (2026-06-28) — historical, not maintained.** Superseded by [lld/ARCHITECTURE.md](lld/ARCHITECTURE.md). Do not rely on this document for current architecture, requirements, or positioning; kept for historical reference only.

# Sentra MVP - Technical Design Document

**Version**: 1.0
**Date**: January 11, 2025
**Status**: Design Phase
**Target**: 4-week MVP for investor demos

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [AWS Infrastructure Design](#aws-infrastructure-design)
3. [Component Specifications](#component-specifications)
4. [Data Models & Schemas](#data-models--schemas)
5. [API Specifications](#api-specifications)
6. [Security Design](#security-design)
7. [Deployment Architecture](#deployment-architecture)
8. [Monitoring & Observability](#monitoring--observability)
9. [Cost Analysis](#cost-analysis)
10. [Future Expansion Path](#future-expansion-path)

---

## Architecture Overview

### System Context Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         SENTRA MVP SYSTEM                               │
│                   (Production AWS Deployment)                           │
│                                                                         │
│  ┌──────────────┐        ┌──────────────┐        ┌──────────────┐    │
│  │   Investor   │───VPN──│   Developer  │───SSM──│   Security   │    │
│  │    Demo      │        │   Testing    │        │     Team     │    │
│  └──────────────┘        └──────────────┘        └──────────────┘    │
│         │                        │                        │           │
│         └────────────────────────┼────────────────────────┘           │
│                                  │                                    │
│                                  ▼                                    │
│                    ┌─────────────────────────┐                       │
│                    │   API Gateway (Private) │                       │
│                    │  • Private REST API     │                       │
│                    │  • VPC Endpoint Only    │                       │
│                    │  • Rate Limiting (100/s)│                       │
│                    └─────────────────────────┘                       │
│                                  │                                    │
│                 ┌────────────────┼────────────────┐                  │
│                 │                │                │                  │
│                 ▼                ▼                ▼                  │
│        ┌────────────────┐┌────────────────┐┌────────────────┐       │
│        │  ECS Service 1 ││  ECS Service 2 ││  ECS Service 3 │       │
│        │   Security     ││   Dashboard    ││  Finance Agent │       │
│        │  Controller    ││  (Streamlit)   ││  (LangChain)   │       │
│        │   (FastAPI)    ││                ││                │       │
│        │  2vCPU/4GB RAM ││  2vCPU/4GB RAM ││  2vCPU/4GB RAM │       │
│        └────────────────┘└────────────────┘└────────────────┘       │
│                 │                │                │                  │
│                 └────────────────┼────────────────┘                  │
│                                  │                                    │
│                 ┌────────────────┼────────────────┐                  │
│                 │                │                │                  │
│                 ▼                ▼                ▼                  │
│        ┌────────────────┐┌────────────────┐┌────────────────┐       │
│        │  DynamoDB      ││    S3 Bucket   ││  CloudWatch    │       │
│        │  • audit_logs  ││ • Sigma Rules  ││ • Logs/Metrics │       │
│        │  • policies    ││ • SBOM Files   ││ • Dashboards   │       │
│        │  • sessions    ││ • Exports      ││                │       │
│        └────────────────┘└────────────────┘└────────────────┘       │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
```

### Component Interaction Flow

```
┌─────────┐
│ Finance │  1. Agent makes tool call
│  Agent  │──────────────────────────────────┐
└─────────┘                                   │
                                              ▼
                              ┌───────────────────────────┐
                              │  Security Controller      │
                              │  (FastAPI Service)        │
                              │                           │
                              │  POST /validate           │
                              │  {                        │
                              │    agent_id,              │
                              │    user_input,            │
                              │    tool_name,             │
                              │    tool_params            │
                              │  }                        │
                              └───────────────────────────┘
                                       │
                         ┌─────────────┼─────────────┐
                         │             │             │
                         ▼             ▼             ▼
                   ┌──────────┐  ┌──────────┐  ┌──────────┐
                   │  Policy  │  │  Sigma   │  │  Abuse   │
                   │ Validator│  │  Rules   │  │  Checks  │
                   │          │  │  Engine  │  │          │
                   └──────────┘  └──────────┘  └──────────┘
                         │             │             │
                         └─────────────┼─────────────┘
                                       │
                                       ▼
                              ┌───────────────┐
                              │   Decision    │
                              │   ALLOW /     │
                              │   DENY /      │
                              │   REDACT      │
                              └───────────────┘
                                       │
                         ┌─────────────┼─────────────┐
                         │             │             │
                         ▼             ▼             ▼
                   ┌──────────┐  ┌──────────┐  ┌──────────┐
                   │ DynamoDB │  │    S3    │  │CloudWatch│
                   │  Audit   │  │   SBOM   │  │   Logs   │
                   │   Logs   │  │          │  │          │
                   └──────────┘  └──────────┘  └──────────┘
```

---

## AWS Infrastructure Design

### CDK Stack Structure

```python
# cdk_app/
├── app.py                          # CDK app entry point
├── stacks/
│   ├── __init__.py
│   ├── network_stack.py            # VPC, subnets, security groups
│   ├── storage_stack.py            # DynamoDB tables, S3 buckets
│   ├── compute_stack.py            # ECS cluster, services, tasks
│   ├── api_stack.py                # API Gateway, VPC endpoints
│   └── monitoring_stack.py         # CloudWatch dashboards, alarms
├── config/
│   ├── dev.yaml                    # Dev environment config
│   ├── prod.yaml                   # Production config
│   └── constants.py                # Shared constants
└── requirements.txt                # CDK dependencies
```

### CDK Stack 1: Network Stack

**File**: `stacks/network_stack.py`

```python
from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_logs as logs,
    CfnOutput
)
from constructs import Construct

class NetworkStack(Stack):
    """
    VPC and networking infrastructure for Sentra MVP

    Creates:
    - VPC with private subnets (no public subnets for security)
    - Security groups for ECS services
    - VPC endpoints for AWS services (ECR, S3, CloudWatch, etc.)
    - Flow logs for network monitoring
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # VPC Configuration
        self.vpc = ec2.Vpc(
            self, "SentraMvpVpc",
            vpc_name="sentra-mvp-vpc",
            max_azs=2,  # High availability across 2 AZs
            nat_gateways=1,  # Single NAT for cost optimization (MVP)
            subnet_configuration=[
                # Private subnets for ECS services
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24
                ),
                # Isolated subnets for DynamoDB VPC endpoints
                ec2.SubnetConfiguration(
                    name="Isolated",
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    cidr_mask=28
                )
            ],
            enable_dns_hostnames=True,
            enable_dns_support=True
        )

        # VPC Flow Logs (for security audit)
        log_group = logs.LogGroup(
            self, "VpcFlowLogs",
            log_group_name="/aws/vpc/sentra-mvp",
            retention=logs.RetentionDays.ONE_WEEK  # Cost optimization for MVP
        )

        ec2.FlowLog(
            self, "SentraVpcFlowLog",
            resource_type=ec2.FlowLogResourceType.from_vpc(self.vpc),
            destination=ec2.FlowLogDestination.to_cloud_watch_logs(log_group)
        )

        # Security Group: Security Controller (FastAPI)
        self.security_controller_sg = ec2.SecurityGroup(
            self, "SecurityControllerSG",
            vpc=self.vpc,
            security_group_name="sentra-security-controller-sg",
            description="Security group for Security Controller service",
            allow_all_outbound=True
        )

        # Security Group: Dashboard (Streamlit)
        self.dashboard_sg = ec2.SecurityGroup(
            self, "DashboardSG",
            vpc=self.vpc,
            security_group_name="sentra-dashboard-sg",
            description="Security group for Dashboard service",
            allow_all_outbound=True
        )

        # Security Group: Finance Agent
        self.finance_agent_sg = ec2.SecurityGroup(
            self, "FinanceAgentSG",
            vpc=self.vpc,
            security_group_name="sentra-finance-agent-sg",
            description="Security group for Finance Agent service",
            allow_all_outbound=True
        )

        # Security Group: API Gateway VPC Endpoint
        self.api_gateway_sg = ec2.SecurityGroup(
            self, "ApiGatewaySG",
            vpc=self.vpc,
            security_group_name="sentra-api-gateway-sg",
            description="Security group for API Gateway VPC endpoint",
            allow_all_outbound=False
        )

        # Allow dashboard and finance agent to call Security Controller
        self.security_controller_sg.add_ingress_rule(
            peer=self.dashboard_sg,
            connection=ec2.Port.tcp(8000),
            description="Allow dashboard to call Security Controller"
        )

        self.security_controller_sg.add_ingress_rule(
            peer=self.finance_agent_sg,
            connection=ec2.Port.tcp(8000),
            description="Allow finance agent to call Security Controller"
        )

        # Allow API Gateway to reach Security Controller
        self.security_controller_sg.add_ingress_rule(
            peer=self.api_gateway_sg,
            connection=ec2.Port.tcp(8000),
            description="Allow API Gateway to call Security Controller"
        )

        # VPC Endpoints (for AWS service access without NAT)
        self.vpc.add_interface_endpoint(
            "EcrDockerEndpoint",
            service=ec2.InterfaceVpcEndpointAwsService.ECR_DOCKER
        )

        self.vpc.add_interface_endpoint(
            "EcrApiEndpoint",
            service=ec2.InterfaceVpcEndpointAwsService.ECR
        )

        self.vpc.add_interface_endpoint(
            "CloudWatchLogsEndpoint",
            service=ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS
        )

        self.vpc.add_gateway_endpoint(
            "S3Endpoint",
            service=ec2.GatewayVpcEndpointAwsService.S3
        )

        self.vpc.add_gateway_endpoint(
            "DynamoDBEndpoint",
            service=ec2.GatewayVpcEndpointAwsService.DYNAMODB
        )

        # Outputs
        CfnOutput(
            self, "VpcId",
            value=self.vpc.vpc_id,
            description="VPC ID for Sentra MVP"
        )

        CfnOutput(
            self, "SecurityControllerSgId",
            value=self.security_controller_sg.security_group_id,
            description="Security group ID for Security Controller"
        )
```

### CDK Stack 2: Storage Stack

**File**: `stacks/storage_stack.py`

```python
from aws_cdk import (
    Stack,
    RemovalPolicy,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    Duration,
    CfnOutput
)
from constructs import Construct

class StorageStack(Stack):
    """
    Storage infrastructure for Sentra MVP

    Creates:
    - DynamoDB tables (audit_logs, session_context, policies)
    - S3 bucket for Sigma rules, SBOM, compliance exports
    - Lifecycle policies for cost optimization
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # DynamoDB Table: audit_logs (on-demand)
        self.audit_logs_table = dynamodb.Table(
            self, "AuditLogsTable",
            table_name="sentra-audit-logs",
            partition_key=dynamodb.Attribute(
                name="request_id",
                type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="timestamp",
                type=dynamodb.AttributeType.NUMBER
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,  # On-demand
            point_in_time_recovery=True,  # Compliance requirement
            removal_policy=RemovalPolicy.RETAIN,  # Never delete audit logs
            time_to_live_attribute="ttl"  # Auto-expire old logs (set to 90 days)
        )

        # GSI: Query by agent_id
        self.audit_logs_table.add_global_secondary_index(
            index_name="agent-timestamp-index",
            partition_key=dynamodb.Attribute(
                name="agent_id",
                type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="timestamp",
                type=dynamodb.AttributeType.NUMBER
            )
        )

        # GSI: Query by decision type (DENY, REDACT)
        self.audit_logs_table.add_global_secondary_index(
            index_name="decision-timestamp-index",
            partition_key=dynamodb.Attribute(
                name="decision",
                type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="timestamp",
                type=dynamodb.AttributeType.NUMBER
            )
        )

        # DynamoDB Table: session_context (on-demand)
        self.session_context_table = dynamodb.Table(
            self, "SessionContextTable",
            table_name="sentra-session-context",
            partition_key=dynamodb.Attribute(
                name="session_id",
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,  # On-demand
            point_in_time_recovery=True,
            removal_policy=RemovalPolicy.DESTROY,  # OK to delete in dev
            time_to_live_attribute="ttl"  # Auto-expire sessions after 24 hours
        )

        # GSI: Query by agent_id to get all sessions
        self.session_context_table.add_global_secondary_index(
            index_name="agent-updated-index",
            partition_key=dynamodb.Attribute(
                name="agent_id",
                type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="updated_at",
                type=dynamodb.AttributeType.NUMBER
            )
        )

        # DynamoDB Table: policies (on-demand)
        self.policies_table = dynamodb.Table(
            self, "PoliciesTable",
            table_name="sentra-policies",
            partition_key=dynamodb.Attribute(
                name="policy_id",
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,  # On-demand
            point_in_time_recovery=True,
            removal_policy=RemovalPolicy.RETAIN,  # Keep policies
            stream=dynamodb.StreamViewType.NEW_AND_OLD_IMAGES  # Policy change audit
        )

        # GSI: Query policies by agent_id
        self.policies_table.add_global_secondary_index(
            index_name="agent-version-index",
            partition_key=dynamodb.Attribute(
                name="agent_id",
                type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="version",
                type=dynamodb.AttributeType.NUMBER
            )
        )

        # S3 Bucket: Sentra artifacts
        self.artifacts_bucket = s3.Bucket(
            self, "ArtifactsBucket",
            bucket_name="sentra-mvp-artifacts",
            encryption=s3.BucketEncryption.S3_MANAGED,
            versioned=True,  # Version Sigma rules and policies
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[
                # Archive old compliance exports to Glacier after 30 days
                s3.LifecycleRule(
                    id="archive-exports",
                    prefix="compliance_exports/",
                    transitions=[
                        s3.Transition(
                            storage_class=s3.StorageClass.GLACIER,
                            transition_after=Duration.days(30)
                        )
                    ]
                ),
                # Delete old debug logs after 7 days
                s3.LifecycleRule(
                    id="delete-debug-logs",
                    prefix="debug_logs/",
                    expiration=Duration.days(7)
                )
            ]
        )

        # Outputs
        CfnOutput(
            self, "AuditLogsTableName",
            value=self.audit_logs_table.table_name,
            description="DynamoDB table name for audit logs"
        )

        CfnOutput(
            self, "SessionContextTableName",
            value=self.session_context_table.table_name,
            description="DynamoDB table name for session context"
        )

        CfnOutput(
            self, "PoliciesTableName",
            value=self.policies_table.table_name,
            description="DynamoDB table name for policies"
        )

        CfnOutput(
            self, "ArtifactsBucketName",
            value=self.artifacts_bucket.bucket_name,
            description="S3 bucket name for Sigma rules, SBOM, exports"
        )
```

### CDK Stack 3: Compute Stack

**File**: `stacks/compute_stack.py`

```python
from aws_cdk import (
    Stack,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_ecr as ecr,
    aws_logs as logs,
    aws_iam as iam,
    Duration,
    CfnOutput
)
from constructs import Construct

class ComputeStack(Stack):
    """
    ECS Fargate infrastructure for Sentra MVP

    Creates:
    - ECS cluster
    - ECR repositories for container images
    - Task definitions for 3 services
    - ECS services with auto-scaling
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        vpc,
        security_controller_sg,
        dashboard_sg,
        finance_agent_sg,
        audit_logs_table,
        session_context_table,
        policies_table,
        artifacts_bucket,
        **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ECS Cluster
        self.cluster = ecs.Cluster(
            self, "SentraMvpCluster",
            cluster_name="sentra-mvp-cluster",
            vpc=vpc,
            container_insights=True  # Enable CloudWatch Container Insights
        )

        # ECR Repositories
        self.security_controller_repo = ecr.Repository(
            self, "SecurityControllerRepo",
            repository_name="sentra/security-controller",
            image_scan_on_push=True,  # Security scanning
            lifecycle_rules=[
                ecr.LifecycleRule(
                    max_image_count=10,  # Keep last 10 images
                    description="Keep last 10 images"
                )
            ]
        )

        self.dashboard_repo = ecr.Repository(
            self, "DashboardRepo",
            repository_name="sentra/dashboard",
            image_scan_on_push=True,
            lifecycle_rules=[
                ecr.LifecycleRule(
                    max_image_count=10,
                    description="Keep last 10 images"
                )
            ]
        )

        self.finance_agent_repo = ecr.Repository(
            self, "FinanceAgentRepo",
            repository_name="sentra/finance-agent",
            image_scan_on_push=True,
            lifecycle_rules=[
                ecr.LifecycleRule(
                    max_image_count=10,
                    description="Keep last 10 images"
                )
            ]
        )

        # CloudWatch Log Groups
        security_controller_log_group = logs.LogGroup(
            self, "SecurityControllerLogGroup",
            log_group_name="/ecs/sentra/security-controller",
            retention=logs.RetentionDays.ONE_WEEK
        )

        dashboard_log_group = logs.LogGroup(
            self, "DashboardLogGroup",
            log_group_name="/ecs/sentra/dashboard",
            retention=logs.RetentionDays.ONE_WEEK
        )

        finance_agent_log_group = logs.LogGroup(
            self, "FinanceAgentLogGroup",
            log_group_name="/ecs/sentra/finance-agent",
            retention=logs.RetentionDays.ONE_WEEK
        )

        # IAM Role for ECS Tasks
        task_role = iam.Role(
            self, "EcsTaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            description="IAM role for Sentra ECS tasks"
        )

        # Grant DynamoDB access
        audit_logs_table.grant_read_write_data(task_role)
        session_context_table.grant_read_write_data(task_role)
        policies_table.grant_read_write_data(task_role)

        # Grant S3 access
        artifacts_bucket.grant_read_write(task_role)

        # Grant Bedrock access (for Finance Agent)
        task_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream"
                ],
                resources=["*"]  # MVP: Allow all Bedrock models
            )
        )

        # Task Definition: Security Controller (FastAPI)
        self.security_controller_task = ecs.FargateTaskDefinition(
            self, "SecurityControllerTask",
            family="sentra-security-controller",
            cpu=2048,  # 2 vCPU
            memory_limit_mib=4096,  # 4 GB RAM
            task_role=task_role
        )

        self.security_controller_container = self.security_controller_task.add_container(
            "SecurityController",
            image=ecs.ContainerImage.from_ecr_repository(
                self.security_controller_repo,
                tag="latest"
            ),
            logging=ecs.LogDriver.aws_logs(
                stream_prefix="security-controller",
                log_group=security_controller_log_group
            ),
            environment={
                "ENV": "production",
                "PORT": "8000",
                "AUDIT_LOGS_TABLE": audit_logs_table.table_name,
                "SESSION_CONTEXT_TABLE": session_context_table.table_name,
                "POLICIES_TABLE": policies_table.table_name,
                "ARTIFACTS_BUCKET": artifacts_bucket.bucket_name,
                "AWS_REGION": self.region
            },
            health_check=ecs.HealthCheck(
                command=["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"],
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                retries=3,
                start_period=Duration.seconds(60)
            )
        )

        self.security_controller_container.add_port_mappings(
            ecs.PortMapping(container_port=8000, protocol=ecs.Protocol.TCP)
        )

        # ECS Service: Security Controller
        self.security_controller_service = ecs.FargateService(
            self, "SecurityControllerService",
            cluster=self.cluster,
            task_definition=self.security_controller_task,
            service_name="security-controller",
            desired_count=1,  # MVP: Single instance (scale later)
            security_groups=[security_controller_sg],
            vpc_subnets={"subnet_type": ec2.SubnetType.PRIVATE_WITH_EGRESS},
            enable_execute_command=True,  # For debugging via ECS Exec
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True)
        )

        # Task Definition: Dashboard (Streamlit)
        self.dashboard_task = ecs.FargateTaskDefinition(
            self, "DashboardTask",
            family="sentra-dashboard",
            cpu=2048,  # 2 vCPU
            memory_limit_mib=4096,  # 4 GB RAM
            task_role=task_role
        )

        self.dashboard_container = self.dashboard_task.add_container(
            "Dashboard",
            image=ecs.ContainerImage.from_ecr_repository(
                self.dashboard_repo,
                tag="latest"
            ),
            logging=ecs.LogDriver.aws_logs(
                stream_prefix="dashboard",
                log_group=dashboard_log_group
            ),
            environment={
                "ENV": "production",
                "PORT": "8501",
                "SECURITY_CONTROLLER_URL": f"http://{self.security_controller_service.service_name}:8000",
                "AUDIT_LOGS_TABLE": audit_logs_table.table_name,
                "AWS_REGION": self.region
            },
            health_check=ecs.HealthCheck(
                command=["CMD-SHELL", "curl -f http://localhost:8501/_stcore/health || exit 1"],
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                retries=3,
                start_period=Duration.seconds(60)
            )
        )

        self.dashboard_container.add_port_mappings(
            ecs.PortMapping(container_port=8501, protocol=ecs.Protocol.TCP)
        )

        # ECS Service: Dashboard
        self.dashboard_service = ecs.FargateService(
            self, "DashboardService",
            cluster=self.cluster,
            task_definition=self.dashboard_task,
            service_name="dashboard",
            desired_count=1,
            security_groups=[dashboard_sg],
            vpc_subnets={"subnet_type": ec2.SubnetType.PRIVATE_WITH_EGRESS},
            enable_execute_command=True,
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True)
        )

        # Task Definition: Finance Agent (LangChain)
        self.finance_agent_task = ecs.FargateTaskDefinition(
            self, "FinanceAgentTask",
            family="sentra-finance-agent",
            cpu=2048,  # 2 vCPU
            memory_limit_mib=4096,  # 4 GB RAM
            task_role=task_role
        )

        self.finance_agent_container = self.finance_agent_task.add_container(
            "FinanceAgent",
            image=ecs.ContainerImage.from_ecr_repository(
                self.finance_agent_repo,
                tag="latest"
            ),
            logging=ecs.LogDriver.aws_logs(
                stream_prefix="finance-agent",
                log_group=finance_agent_log_group
            ),
            environment={
                "ENV": "production",
                "PORT": "8002",
                "SECURITY_CONTROLLER_URL": f"http://{self.security_controller_service.service_name}:8000",
                "AWS_REGION": self.region,
                "BEDROCK_MODEL_ID": "anthropic.claude-3-5-sonnet-20241022-v2:0"
            },
            secrets={
                # For MVP: Store OpenAI key in Secrets Manager if using OpenAI
                # "OPENAI_API_KEY": ecs.Secret.from_secrets_manager(openai_secret)
            },
            health_check=ecs.HealthCheck(
                command=["CMD-SHELL", "curl -f http://localhost:8002/health || exit 1"],
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                retries=3,
                start_period=Duration.seconds(60)
            )
        )

        self.finance_agent_container.add_port_mappings(
            ecs.PortMapping(container_port=8002, protocol=ecs.Protocol.TCP)
        )

        # ECS Service: Finance Agent
        self.finance_agent_service = ecs.FargateService(
            self, "FinanceAgentService",
            cluster=self.cluster,
            task_definition=self.finance_agent_task,
            service_name="finance-agent",
            desired_count=1,
            security_groups=[finance_agent_sg],
            vpc_subnets={"subnet_type": ec2.SubnetType.PRIVATE_WITH_EGRESS},
            enable_execute_command=True,
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True)
        )

        # Outputs
        CfnOutput(
            self, "ClusterName",
            value=self.cluster.cluster_name,
            description="ECS cluster name"
        )

        CfnOutput(
            self, "SecurityControllerServiceName",
            value=self.security_controller_service.service_name,
            description="Security Controller service name"
        )
```

### CDK Stack 4: API Stack

**File**: `stacks/api_stack.py`

```python
from aws_cdk import (
    Stack,
    aws_apigateway as apigw,
    aws_ec2 as ec2,
    aws_logs as logs,
    CfnOutput
)
from constructs import Construct

class ApiStack(Stack):
    """
    API Gateway infrastructure for Sentra MVP

    Creates:
    - Private REST API (VPC-only, no public internet)
    - Rate limiting (100 requests/second)
    - Request validation
    - CloudWatch logging
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        vpc,
        security_controller_service,
        **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # VPC Link (connects API Gateway to ECS services in VPC)
        vpc_link = apigw.VpcLink(
            self, "SentraVpcLink",
            vpc_link_name="sentra-mvp-vpc-link",
            targets=[security_controller_service.load_balancer]  # Assuming ALB
        )

        # CloudWatch Log Group for API Gateway
        api_log_group = logs.LogGroup(
            self, "ApiGatewayLogs",
            log_group_name="/aws/apigateway/sentra-mvp",
            retention=logs.RetentionDays.ONE_WEEK
        )

        # Private REST API
        self.api = apigw.RestApi(
            self, "SentraMvpApi",
            rest_api_name="sentra-mvp-api",
            description="Sentra MVP Security Controller API (Private VPC)",
            endpoint_configuration=apigw.EndpointConfiguration(
                types=[apigw.EndpointType.PRIVATE],
                vpc_endpoints=[vpc.add_interface_endpoint(
                    "ApiGatewayEndpoint",
                    service=ec2.InterfaceVpcEndpointAwsService.APIGATEWAY
                )]
            ),
            deploy_options=apigw.StageOptions(
                stage_name="prod",
                throttling_rate_limit=100,  # 100 requests/second
                throttling_burst_limit=200,  # 200 burst
                logging_level=apigw.MethodLoggingLevel.INFO,
                data_trace_enabled=True,
                access_log_destination=apigw.LogGroupLogDestination(api_log_group),
                access_log_format=apigw.AccessLogFormat.json_with_standard_fields(
                    caller=True,
                    http_method=True,
                    ip=True,
                    protocol=True,
                    request_time=True,
                    resource_path=True,
                    response_length=True,
                    status=True,
                    user=True
                )
            ),
            cloud_watch_role=True,
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=["*"],  # MVP: Allow all origins (restrict in prod)
                allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
                allow_headers=["Content-Type", "Authorization"]
            )
        )

        # Resource Policy (allow access from VPC only)
        self.api.add_to_resource_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                principals=[iam.AnyPrincipal()],
                actions=["execute-api:Invoke"],
                resources=["execute-api:/*"],
                conditions={
                    "StringEquals": {
                        "aws:SourceVpc": vpc.vpc_id
                    }
                }
            )
        )

        # Request Validator
        request_validator = apigw.RequestValidator(
            self, "RequestValidator",
            rest_api=self.api,
            request_validator_name="sentra-request-validator",
            validate_request_body=True,
            validate_request_parameters=True
        )

        # Request Model: Validate Request
        validate_request_model = apigw.Model(
            self, "ValidateRequestModel",
            rest_api=self.api,
            content_type="application/json",
            model_name="ValidateRequest",
            schema=apigw.JsonSchema(
                schema=apigw.JsonSchemaVersion.DRAFT4,
                type=apigw.JsonSchemaType.OBJECT,
                required=["request_id", "agent_id", "user_input", "tool_name", "tool_params"],
                properties={
                    "request_id": apigw.JsonSchema(type=apigw.JsonSchemaType.STRING),
                    "agent_id": apigw.JsonSchema(type=apigw.JsonSchemaType.STRING),
                    "user_input": apigw.JsonSchema(type=apigw.JsonSchemaType.STRING),
                    "tool_name": apigw.JsonSchema(type=apigw.JsonSchemaType.STRING),
                    "tool_params": apigw.JsonSchema(type=apigw.JsonSchemaType.OBJECT)
                }
            )
        )

        # Integration: Forward to Security Controller ECS service
        security_controller_integration = apigw.Integration(
            type=apigw.IntegrationType.HTTP_PROXY,
            integration_http_method="POST",
            uri=f"http://{security_controller_service.service_name}:8000/validate",
            options=apigw.IntegrationOptions(
                vpc_link=vpc_link,
                timeout=Duration.seconds(29),  # Max for API Gateway
                connection_type=apigw.ConnectionType.VPC_LINK
            )
        )

        # API Resource: /validate
        validate_resource = self.api.root.add_resource("validate")
        validate_resource.add_method(
            "POST",
            security_controller_integration,
            request_validator=request_validator,
            request_models={
                "application/json": validate_request_model
            },
            method_responses=[
                apigw.MethodResponse(
                    status_code="200",
                    response_models={
                        "application/json": apigw.Model.EMPTY_MODEL
                    }
                ),
                apigw.MethodResponse(status_code="400"),
                apigw.MethodResponse(status_code="429"),  # Rate limit exceeded
                apigw.MethodResponse(status_code="500")
            ]
        )

        # API Resource: /health (for monitoring)
        health_resource = self.api.root.add_resource("health")
        health_integration = apigw.Integration(
            type=apigw.IntegrationType.HTTP_PROXY,
            integration_http_method="GET",
            uri=f"http://{security_controller_service.service_name}:8000/health",
            options=apigw.IntegrationOptions(
                vpc_link=vpc_link,
                connection_type=apigw.ConnectionType.VPC_LINK
            )
        )
        health_resource.add_method("GET", health_integration)

        # Outputs
        CfnOutput(
            self, "ApiEndpoint",
            value=self.api.url,
            description="Private API Gateway endpoint (VPC-only)"
        )

        CfnOutput(
            self, "ApiId",
            value=self.api.rest_api_id,
            description="API Gateway REST API ID"
        )
```

### CDK Stack 5: Monitoring Stack

**File**: `stacks/monitoring_stack.py`

```python
from aws_cdk import (
    Stack,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_sns as sns,
    aws_sns_subscriptions as sns_subs,
    Duration,
    CfnOutput
)
from constructs import Construct

class MonitoringStack(Stack):
    """
    Monitoring and alerting infrastructure for Sentra MVP

    Creates:
    - CloudWatch dashboards
    - Alarms for critical metrics
    - SNS topics for alerts
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        cluster,
        security_controller_service,
        dashboard_service,
        finance_agent_service,
        api,
        audit_logs_table,
        **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # SNS Topic for Alerts
        self.alert_topic = sns.Topic(
            self, "AlertTopic",
            topic_name="sentra-mvp-alerts",
            display_name="Sentra MVP Alerts"
        )

        # Add email subscription (MVP: Add investor demo email)
        # self.alert_topic.add_subscription(
        #     sns_subs.EmailSubscription("alerts@sentra.io")
        # )

        # CloudWatch Dashboard
        dashboard = cloudwatch.Dashboard(
            self, "SentraDashboard",
            dashboard_name="Sentra-MVP-Dashboard"
        )

        # Widget: API Gateway Metrics
        api_requests_widget = cloudwatch.GraphWidget(
            title="API Gateway Requests",
            left=[
                api.metric_count(period=Duration.minutes(5)),
                api.metric_client_error(period=Duration.minutes(5)),
                api.metric_server_error(period=Duration.minutes(5))
            ],
            width=12
        )

        api_latency_widget = cloudwatch.GraphWidget(
            title="API Gateway Latency",
            left=[
                api.metric_latency(
                    statistic="Average",
                    period=Duration.minutes(5)
                ),
                api.metric_latency(
                    statistic="p99",
                    period=Duration.minutes(5)
                )
            ],
            width=12
        )

        # Widget: ECS Service CPU & Memory
        ecs_cpu_widget = cloudwatch.GraphWidget(
            title="ECS Service CPU Utilization",
            left=[
                security_controller_service.metric_cpu_utilization(
                    period=Duration.minutes(5)
                ),
                dashboard_service.metric_cpu_utilization(
                    period=Duration.minutes(5)
                ),
                finance_agent_service.metric_cpu_utilization(
                    period=Duration.minutes(5)
                )
            ],
            width=12
        )

        ecs_memory_widget = cloudwatch.GraphWidget(
            title="ECS Service Memory Utilization",
            left=[
                security_controller_service.metric_memory_utilization(
                    period=Duration.minutes(5)
                ),
                dashboard_service.metric_memory_utilization(
                    period=Duration.minutes(5)
                ),
                finance_agent_service.metric_memory_utilization(
                    period=Duration.minutes(5)
                )
            ],
            width=12
        )

        # Widget: DynamoDB Metrics
        ddb_read_widget = cloudwatch.GraphWidget(
            title="DynamoDB Read Capacity",
            left=[
                audit_logs_table.metric_consumed_read_capacity_units(
                    period=Duration.minutes(5)
                )
            ],
            width=12
        )

        ddb_write_widget = cloudwatch.GraphWidget(
            title="DynamoDB Write Capacity",
            left=[
                audit_logs_table.metric_consumed_write_capacity_units(
                    period=Duration.minutes(5)
                )
            ],
            width=12
        )

        # Widget: Security Metrics (from custom CloudWatch Logs Insights queries)
        security_widget = cloudwatch.LogQueryWidget(
            title="Security Events (Last Hour)",
            log_group_names=["/ecs/sentra/security-controller"],
            query_lines=[
                "fields @timestamp, decision, agent_id, tool_name, threat_type",
                "filter decision = 'DENY' or decision = 'REDACT'",
                "sort @timestamp desc",
                "limit 100"
            ],
            width=24
        )

        # Add widgets to dashboard
        dashboard.add_widgets(api_requests_widget, api_latency_widget)
        dashboard.add_widgets(ecs_cpu_widget, ecs_memory_widget)
        dashboard.add_widgets(ddb_read_widget, ddb_write_widget)
        dashboard.add_widgets(security_widget)

        # Alarm: API Gateway 5xx Errors
        api_5xx_alarm = cloudwatch.Alarm(
            self, "Api5xxAlarm",
            alarm_name="sentra-api-5xx-errors",
            metric=api.metric_server_error(
                period=Duration.minutes(5),
                statistic="Sum"
            ),
            threshold=10,  # Alert if > 10 errors in 5 minutes
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD
        )
        api_5xx_alarm.add_alarm_action(cw_actions.SnsAction(self.alert_topic))

        # Alarm: API Gateway Latency
        api_latency_alarm = cloudwatch.Alarm(
            self, "ApiLatencyAlarm",
            alarm_name="sentra-api-high-latency",
            metric=api.metric_latency(
                period=Duration.minutes(5),
                statistic="p99"
            ),
            threshold=5000,  # Alert if p99 > 5 seconds
            evaluation_periods=2,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD
        )
        api_latency_alarm.add_alarm_action(cw_actions.SnsAction(self.alert_topic))

        # Alarm: ECS Service CPU > 80%
        ecs_cpu_alarm = cloudwatch.Alarm(
            self, "EcsCpuAlarm",
            alarm_name="sentra-ecs-high-cpu",
            metric=security_controller_service.metric_cpu_utilization(
                period=Duration.minutes(5)
            ),
            threshold=80,
            evaluation_periods=2,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD
        )
        ecs_cpu_alarm.add_alarm_action(cw_actions.SnsAction(self.alert_topic))

        # Alarm: ECS Service Memory > 80%
        ecs_memory_alarm = cloudwatch.Alarm(
            self, "EcsMemoryAlarm",
            alarm_name="sentra-ecs-high-memory",
            metric=security_controller_service.metric_memory_utilization(
                period=Duration.minutes(5)
            ),
            threshold=80,
            evaluation_periods=2,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD
        )
        ecs_memory_alarm.add_alarm_action(cw_actions.SnsAction(self.alert_topic))

        # Outputs
        CfnOutput(
            self, "DashboardUrl",
            value=f"https://console.aws.amazon.com/cloudwatch/home?region={self.region}#dashboards:name={dashboard.dashboard_name}",
            description="CloudWatch Dashboard URL"
        )

        CfnOutput(
            self, "AlertTopicArn",
            value=self.alert_topic.topic_arn,
            description="SNS topic ARN for alerts"
        )
```

---

## Component Specifications

### Security Controller (FastAPI Backend)

**Location**: `security_controller/`

**Directory Structure**:
```
security_controller/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app entry point
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py           # API endpoints (/validate, /health, etc.)
│   │   └── models.py           # Pydantic request/response models
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py           # Configuration (env vars, constants)
│   │   ├── policy_engine.py    # Policy validation logic
│   │   ├── sigma_engine.py     # Sigma rule evaluation
│   │   ├── abuse_detector.py   # Rate limiting, anomaly detection
│   │   └── context_validator.py # Session context validation
│   ├── db/
│   │   ├── __init__.py
│   │   ├── dynamodb.py         # DynamoDB client wrapper
│   │   └── s3.py               # S3 client wrapper
│   └── utils/
│       ├── __init__.py
│       ├── logger.py           # Structured logging
│       └── metrics.py          # CloudWatch custom metrics
├── tests/
│   ├── __init__.py
│   ├── test_policy_engine.py
│   ├── test_sigma_engine.py
│   └── test_api.py
├── Dockerfile
├── requirements.txt
└── README.md
```

**Key Files**:

**1. `app/main.py`** (FastAPI Entry Point)

```python
import time
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.api import routes
from app.core.config import settings
from app.utils.logger import logger

app = FastAPI(
    title="Sentra Security Controller",
    description="Runtime security validation for AI agents",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # MVP: Allow all (restrict in prod)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()

    response = await call_next(request)

    process_time = (time.time() - start_time) * 1000
    logger.info(
        "request_processed",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        process_time_ms=f"{process_time:.2f}"
    )

    response.headers["X-Process-Time"] = str(process_time)
    return response

# Exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("unhandled_exception", error=str(exc), path=request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )

# Include routes
app.include_router(routes.router)

@app.on_event("startup")
async def startup_event():
    logger.info("security_controller_starting", env=settings.ENV)

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("security_controller_shutting_down")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=settings.ENV == "development"
    )
```

**2. `app/api/models.py`** (Pydantic Request/Response Models)

```python
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
from enum import Enum

class Decision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REDACT = "REDACT"

class ThreatType(str, Enum):
    PROMPT_INJECTION = "PROMPT_INJECTION"
    JAILBREAK = "JAILBREAK"
    DATA_EXFILTRATION = "DATA_EXFILTRATION"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    ABUSE = "ABUSE"
    CONTEXT_VIOLATION = "CONTEXT_VIOLATION"

class ValidateRequest(BaseModel):
    """Request model for /validate endpoint"""
    request_id: str = Field(..., description="Unique request ID")
    agent_id: str = Field(..., description="Agent identifier")
    user_input: str = Field(..., description="User prompt/input")
    tool_name: str = Field(..., description="Tool being called")
    tool_params: Dict[str, Any] = Field(..., description="Tool parameters")
    session_id: Optional[str] = Field(None, description="Session ID for context tracking")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional metadata")

class CodeAttribution(BaseModel):
    """Code-level attribution for security decision"""
    file: str
    line_number: int
    function: str
    rule_id: str

class ValidateResponse(BaseModel):
    """Response model for /validate endpoint"""
    request_id: str
    decision: Decision
    reason: str
    matched_rules: List[str] = Field(default_factory=list)
    threat_type: Optional[ThreatType] = None
    redacted_params: Optional[Dict[str, Any]] = None
    code_attribution: Optional[CodeAttribution] = None
    process_time_ms: float

class HealthResponse(BaseModel):
    """Response model for /health endpoint"""
    status: str
    version: str
    checks: Dict[str, bool]
```

**3. `app/core/policy_engine.py`** (Policy Validation Logic)

```python
import yaml
from typing import Dict, Any, Tuple, Optional
from app.db.dynamodb import get_policies_for_agent
from app.utils.logger import logger

class PolicyEngine:
    """
    Validates tool calls against business policies (YAML format)

    MVP Policy Format:
    ```yaml
    - name: max-refund-amount
      description: Refund cannot exceed $5000
      condition: "tool_params['amount'] <= 5000"
      action: deny
      severity: high
    ```
    """

    def __init__(self):
        self.policies_cache = {}  # Simple in-memory cache for MVP

    async def validate(
        self,
        agent_id: str,
        tool_name: str,
        tool_params: Dict[str, Any],
        user_input: str
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Validate tool call against policies

        Returns:
            (is_allowed, reason, matched_rule_id)
        """
        # Load policies for agent
        policies = await self._get_policies(agent_id, tool_name)

        for policy in policies:
            try:
                # Evaluate condition (simple Python expression for MVP)
                condition = policy.get("condition", "")

                # Build evaluation context
                eval_context = {
                    "tool_params": tool_params,
                    "tool_name": tool_name,
                    "user_input": user_input
                }

                # Evaluate condition
                if eval(condition, {"__builtins__": {}}, eval_context):
                    # Condition matched (policy applies)
                    action = policy.get("action", "deny")

                    if action == "deny":
                        reason = policy.get("description", "Policy violation")
                        rule_id = policy.get("name", "unknown")
                        logger.warning(
                            "policy_violation",
                            agent_id=agent_id,
                            tool_name=tool_name,
                            rule_id=rule_id
                        )
                        return False, reason, rule_id

            except Exception as e:
                logger.error(
                    "policy_evaluation_error",
                    agent_id=agent_id,
                    policy_name=policy.get("name"),
                    error=str(e)
                )
                # Fail secure: Deny on evaluation error
                return False, f"Policy evaluation error: {str(e)}", policy.get("name")

        # All policies passed
        return True, None, None

    async def _get_policies(self, agent_id: str, tool_name: str) -> list:
        """Load policies for agent from DynamoDB (with caching)"""
        cache_key = f"{agent_id}:{tool_name}"

        if cache_key in self.policies_cache:
            return self.policies_cache[cache_key]

        # Fetch from DynamoDB
        policies = await get_policies_for_agent(agent_id, tool_name)

        # Cache for 5 minutes (simple TTL for MVP)
        self.policies_cache[cache_key] = policies

        return policies
```

**4. `app/core/sigma_engine.py`** (Sigma Rule Evaluation)

```python
import re
from typing import Dict, Any, List, Tuple, Optional
from app.db.s3 import load_sigma_rules
from app.utils.logger import logger

class SigmaEngine:
    """
    Evaluates user inputs against Sigma-format threat detection rules

    MVP Sigma Rule Format (simplified):
    ```yaml
    title: Prompt Injection - Ignore Previous Instructions
    id: sigma-llm-001
    status: stable
    description: Detects prompt injection attempts
    logsource:
        product: ai_agent
        category: user_input
    detection:
        selection:
            user_input|contains:
                - "ignore previous instructions"
                - "disregard all prior"
                - "forget everything"
        condition: selection
    level: high
    tags:
        - attack.llm01
        - owasp.llm.top10.2025
    ```
    """

    def __init__(self):
        self.rules = []
        self.rules_loaded = False

    async def load_rules(self):
        """Load Sigma rules from S3"""
        if not self.rules_loaded:
            self.rules = await load_sigma_rules()
            self.rules_loaded = True
            logger.info("sigma_rules_loaded", count=len(self.rules))

    async def detect_threats(
        self,
        user_input: str,
        tool_name: str,
        tool_params: Dict[str, Any]
    ) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
        """
        Detect security threats in user input

        Returns:
            (is_threat_detected, threat_type, reason, matched_rule_id)
        """
        await self.load_rules()

        for rule in self.rules:
            try:
                # Extract detection patterns
                detection = rule.get("detection", {})
                selection = detection.get("selection", {})

                # Check user_input patterns
                if "user_input|contains" in selection:
                    patterns = selection["user_input|contains"]

                    for pattern in patterns:
                        # Case-insensitive search
                        if re.search(pattern, user_input, re.IGNORECASE):
                            rule_id = rule.get("id", "unknown")
                            threat_type = self._map_threat_type(rule.get("tags", []))
                            reason = rule.get("title", "Security threat detected")

                            logger.warning(
                                "threat_detected",
                                rule_id=rule_id,
                                threat_type=threat_type,
                                pattern=pattern
                            )

                            return True, threat_type, reason, rule_id

                # Check tool_params patterns (for data exfiltration, etc.)
                if "tool_params|contains" in selection:
                    patterns = selection["tool_params|contains"]
                    params_str = str(tool_params)

                    for pattern in patterns:
                        if re.search(pattern, params_str, re.IGNORECASE):
                            rule_id = rule.get("id", "unknown")
                            threat_type = self._map_threat_type(rule.get("tags", []))
                            reason = rule.get("title", "Security threat detected")

                            logger.warning(
                                "threat_detected_in_params",
                                rule_id=rule_id,
                                threat_type=threat_type,
                                tool_name=tool_name
                            )

                            return True, threat_type, reason, rule_id

            except Exception as e:
                logger.error(
                    "sigma_rule_evaluation_error",
                    rule_id=rule.get("id"),
                    error=str(e)
                )
                # Continue to next rule (don't fail on single rule error)

        # No threats detected
        return False, None, None, None

    def _map_threat_type(self, tags: List[str]) -> str:
        """Map Sigma rule tags to threat types"""
        tag_map = {
            "attack.llm01": "PROMPT_INJECTION",
            "attack.llm02": "DATA_EXFILTRATION",
            "attack.llm06": "DATA_EXFILTRATION",
            "jailbreak": "JAILBREAK"
        }

        for tag in tags:
            if tag in tag_map:
                return tag_map[tag]

        return "PROMPT_INJECTION"  # Default
```

---

## Data Models & Schemas

### DynamoDB Schema: audit_logs

**Table Name**: `sentra-audit-logs`
**Billing Mode**: On-Demand
**Point-in-Time Recovery**: Enabled
**TTL Attribute**: `ttl` (set to 90 days)

**Primary Key**:
- **Partition Key**: `request_id` (STRING)
- **Sort Key**: `timestamp` (NUMBER) - Unix epoch milliseconds

**Attributes**:
```json
{
  "request_id": "req-abc123",              // Unique request ID
  "timestamp": 1736611200000,              // Unix epoch ms
  "agent_id": "finance-agent",
  "session_id": "sess-xyz789",
  "user_input": "Process refund for $50",
  "tool_name": "process_refund",
  "tool_params": {
    "order_id": "12345",
    "amount": 50
  },
  "decision": "ALLOW",                     // ALLOW | DENY | REDACT
  "reason": null,
  "matched_rules": [],
  "threat_type": null,                     // PROMPT_INJECTION | JAILBREAK | ...
  "code_attribution": {
    "file": "policies/finance.yaml",
    "line_number": 12,
    "function": "validate_refund",
    "rule_id": "max-refund-amount"
  },
  "process_time_ms": 45.2,
  "metadata": {
    "user_agent": "LangChain/0.1.0",
    "ip_address": "10.0.1.50"
  },
  "ttl": 1744387200                        // Expire after 90 days
}
```

**Global Secondary Indexes**:

1. **agent-timestamp-index**
   - Partition Key: `agent_id` (STRING)
   - Sort Key: `timestamp` (NUMBER)
   - Use Case: Query all requests for a specific agent

2. **decision-timestamp-index**
   - Partition Key: `decision` (STRING)
   - Sort Key: `timestamp` (NUMBER)
   - Use Case: Query all DENY or REDACT decisions

**Access Patterns**:
```python
# 1. Get single request by ID
response = table.get_item(
    Key={"request_id": "req-abc123", "timestamp": 1736611200000}
)

# 2. Get all requests for an agent (last 24 hours)
response = table.query(
    IndexName="agent-timestamp-index",
    KeyConditionExpression=Key("agent_id").eq("finance-agent") &
                           Key("timestamp").between(start_ts, end_ts)
)

# 3. Get all denied requests (last 1 hour)
response = table.query(
    IndexName="decision-timestamp-index",
    KeyConditionExpression=Key("decision").eq("DENY") &
                           Key("timestamp").gt(one_hour_ago)
)
```

### DynamoDB Schema: session_context

**Table Name**: `sentra-session-context`
**Billing Mode**: On-Demand
**TTL Attribute**: `ttl` (set to 24 hours)

**Primary Key**:
- **Partition Key**: `session_id` (STRING)

**Attributes**:
```json
{
  "session_id": "sess-xyz789",
  "agent_id": "finance-agent",
  "created_at": 1736611200000,
  "updated_at": 1736614800000,
  "tool_history": [
    {
      "tool_name": "check_order",
      "timestamp": 1736611200000,
      "params": {"order_id": "12345"}
    },
    {
      "tool_name": "process_refund",
      "timestamp": 1736614800000,
      "params": {"order_id": "12345", "amount": 50}
    }
  ],
  "threat_score": 0,                       // 0-100 threat score
  "abuse_counters": {
    "requests_last_minute": 5,
    "denials_last_hour": 0
  },
  "ttl": 1736697600                        // Expire after 24 hours
}
```

**Global Secondary Index**:

1. **agent-updated-index**
   - Partition Key: `agent_id` (STRING)
   - Sort Key: `updated_at` (NUMBER)
   - Use Case: Get all active sessions for an agent

### DynamoDB Schema: policies

**Table Name**: `sentra-policies`
**Billing Mode**: On-Demand
**Streams**: Enabled (NEW_AND_OLD_IMAGES for audit)

**Primary Key**:
- **Partition Key**: `policy_id` (STRING)

**Attributes**:
```json
{
  "policy_id": "pol-finance-001",
  "agent_id": "finance-agent",
  "tool_name": "process_refund",
  "version": 1,
  "created_at": 1736611200000,
  "updated_at": 1736611200000,
  "policy_yaml": "---\nname: max-refund-amount\ndescription: Refund cannot exceed $5000\n...",
  "is_active": true,
  "created_by": "admin@sentra.io"
}
```

**Global Secondary Index**:

1. **agent-version-index**
   - Partition Key: `agent_id` (STRING)
   - Sort Key: `version` (NUMBER)
   - Use Case: Get all policies for an agent (latest version)

### S3 Bucket Structure

**Bucket Name**: `sentra-mvp-artifacts`
**Encryption**: S3-Managed (SSE-S3)
**Versioning**: Enabled

**Directory Structure**:
```
s3://sentra-mvp-artifacts/
├── sigma_rules/
│   ├── llm/
│   │   ├── prompt_injection_basic.yaml
│   │   ├── jailbreak_attempt.yaml
│   │   ├── data_exfiltration.yaml
│   │   └── prompt_injection_advanced.yaml
│   └── abuse/
│       ├── rate_limit_exceeded.yaml
│       └── anomaly_detected.yaml
├── sbom/
│   ├── finance-agent/
│   │   └── sbom-2025-01-11.json          // CycloneDX format
│   └── security-controller/
│       └── sbom-2025-01-11.json
├── compliance_exports/
│   ├── 2025-01/
│   │   ├── audit-log-export-2025-01-10.csv
│   │   └── policy-report-2025-01-10.pdf
│   └── 2025-02/
└── debug_logs/
    └── 2025-01-11/
        └── request-trace-req-abc123.json
```

---

## API Specifications

### POST /validate

**Description**: Validate agent tool call before execution

**Request**:
```json
{
  "request_id": "req-abc123",
  "agent_id": "finance-agent",
  "user_input": "Process refund for $50 to customer@example.com",
  "tool_name": "process_refund",
  "tool_params": {
    "order_id": "12345",
    "amount": 50,
    "email": "customer@example.com"
  },
  "session_id": "sess-xyz789",
  "metadata": {
    "user_agent": "LangChain/0.1.0",
    "ip_address": "10.0.1.50"
  }
}
```

**Response (ALLOW)**:
```json
{
  "request_id": "req-abc123",
  "decision": "ALLOW",
  "reason": null,
  "matched_rules": [],
  "threat_type": null,
  "redacted_params": null,
  "code_attribution": null,
  "process_time_ms": 45.2
}
```

**Response (DENY - Policy Violation)**:
```json
{
  "request_id": "req-abc124",
  "decision": "DENY",
  "reason": "Refund amount exceeds maximum allowed ($5000)",
  "matched_rules": ["max-refund-amount"],
  "threat_type": "POLICY_VIOLATION",
  "redacted_params": null,
  "code_attribution": {
    "file": "policies/finance.yaml",
    "line_number": 12,
    "function": "validate_refund",
    "rule_id": "max-refund-amount"
  },
  "process_time_ms": 38.7
}
```

**Response (DENY - Prompt Injection)**:
```json
{
  "request_id": "req-abc125",
  "decision": "DENY",
  "reason": "Prompt injection detected: Ignore previous instructions",
  "matched_rules": ["prompt_injection_basic", "sigma-llm-001"],
  "threat_type": "PROMPT_INJECTION",
  "redacted_params": null,
  "code_attribution": {
    "file": "sigma_rules/llm/prompt_injection_basic.yaml",
    "line_number": 8,
    "function": "detect_threats",
    "rule_id": "sigma-llm-001"
  },
  "process_time_ms": 52.1
}
```

**Response (REDACT - PII Detected)**:
```json
{
  "request_id": "req-abc126",
  "decision": "REDACT",
  "reason": "PII detected in tool parameters (email)",
  "matched_rules": ["pii-email-redaction"],
  "threat_type": null,
  "redacted_params": {
    "order_id": "12345",
    "amount": 50,
    "email": "[REDACTED_EMAIL]"
  },
  "code_attribution": {
    "file": "policies/pii.yaml",
    "line_number": 5,
    "function": "redact_pii",
    "rule_id": "pii-email-redaction"
  },
  "process_time_ms": 41.3
}
```

**Error Responses**:

```json
// 400 Bad Request
{
  "detail": "Invalid request: missing required field 'tool_name'"
}

// 429 Too Many Requests
{
  "detail": "Rate limit exceeded: 100 requests per second"
}

// 500 Internal Server Error
{
  "detail": "Internal server error"
}
```

### GET /health

**Description**: Health check endpoint

**Response**:
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "checks": {
    "dynamodb": true,
    "s3": true,
    "sigma_rules_loaded": true
  }
}
```

---

## Security Design

### Defense in Depth Layers

```
┌──────────────────────────────────────────────────────┐
│  Layer 1: Network Security                          │
│  • Private VPC (no public internet)                 │
│  • Security groups (least privilege)                │
│  • VPC endpoints (no NAT traversal)                 │
└──────────────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│  Layer 2: API Gateway                                │
│  • Rate limiting (100 req/s)                        │
│  • Request validation (schema enforcement)          │
│  • CloudWatch logging (all requests)                │
└──────────────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│  Layer 3: Security Controller (FastAPI)              │
│  • Policy validation (business rules)               │
│  • Sigma rule evaluation (threat detection)         │
│  • Context validation (workflow enforcement)        │
│  • Abuse detection (rate limits, anomalies)         │
└──────────────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│  Layer 4: Data Storage                               │
│  • DynamoDB encryption at rest                      │
│  • S3 encryption (SSE-S3)                           │
│  • Point-in-time recovery (audit logs)              │
│  • Immutable audit trail (append-only)              │
└──────────────────────────────────────────────────────┘
```

### Threat Model & Mitigations

| Threat | Severity | Mitigation | Layer |
|--------|----------|------------|-------|
| Prompt Injection | HIGH | Sigma rules detect known patterns | Layer 3 |
| Jailbreak Attempts | HIGH | Sigma rules + context validation | Layer 3 |
| Policy Bypass | HIGH | Policy engine validates ALL tool calls | Layer 3 |
| Data Exfiltration | CRITICAL | Sigma rules detect exfil patterns in params | Layer 3 |
| DDoS / Rate Limit Abuse | MEDIUM | API Gateway rate limiting (100/s) | Layer 2 |
| Session Hijacking | MEDIUM | Session IDs tracked in DynamoDB with TTL | Layer 3 |
| Privilege Escalation | HIGH | Context validator enforces tool sequences | Layer 3 |
| Audit Log Tampering | CRITICAL | DynamoDB streams + S3 versioning | Layer 4 |
| Network Intrusion | MEDIUM | Private VPC, no public endpoints | Layer 1 |
| Container Escape | MEDIUM | Fargate isolation (managed by AWS) | Layer 1 |

### Compliance & Audit Features

**SOC2 Type II Requirements**:
- ✅ **CC6.1 (Logical Access)**: Private VPC, API Gateway auth
- ✅ **CC7.2 (System Monitoring)**: CloudWatch logs + metrics
- ✅ **CC7.3 (Quality Monitoring)**: Automated alarms for errors
- ✅ **A1.2 (Audit Logging)**: Immutable audit logs in DynamoDB

**HIPAA Requirements** (if handling PHI):
- ✅ **§164.308(a)(1)**: Access controls via IAM roles
- ✅ **§164.312(b)**: Audit logs with 90-day retention
- ✅ **§164.312(e)(1)**: Encryption at rest (DynamoDB, S3)
- ✅ **§164.312(e)(2)(i)**: Encryption in transit (TLS 1.2+)

**GDPR Requirements** (if handling EU data):
- ✅ **Art. 25 (Privacy by Design)**: PII redaction in REDACT mode
- ✅ **Art. 30 (Records of Processing)**: Audit logs track all processing
- ✅ **Art. 32 (Security)**: Encryption, access controls, monitoring
- ⚠️ **Art. 17 (Right to Erasure)**: Manual process (delete from DynamoDB + S3)

---

## Deployment Architecture

### Deployment Flow (CDK)

```
Developer Workstation
       │
       │ cdk deploy
       ▼
┌──────────────────┐
│  AWS CloudFormation  │  1. Synthesize CDK to CloudFormation
└──────────────────┘
       │
       ▼
┌──────────────────┐
│  Network Stack   │  2. Create VPC, subnets, security groups
└──────────────────┘
       │
       ▼
┌──────────────────┐
│  Storage Stack   │  3. Create DynamoDB tables, S3 bucket
└──────────────────┘
       │
       ▼
┌──────────────────┐
│  Compute Stack   │  4. Create ECS cluster, services, tasks
└──────────────────┘
       │
       ▼
┌──────────────────┐
│   API Stack      │  5. Create API Gateway, VPC Link
└──────────────────┘
       │
       ▼
┌──────────────────┐
│ Monitoring Stack │  6. Create CloudWatch dashboards, alarms
└──────────────────┘
       │
       ▼
    Stack Outputs (API endpoint, dashboard URL, etc.)
```

### CI/CD Pipeline (GitHub Actions)

```yaml
# .github/workflows/deploy.yml
name: Deploy Sentra MVP

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run tests
        run: |
          cd security_controller
          pip install -r requirements.txt
          pytest tests/

  build:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v2
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: us-east-1

      - name: Login to ECR
        id: login-ecr
        uses: aws-actions/amazon-ecr-login@v1

      - name: Build and push Security Controller image
        run: |
          cd security_controller
          docker build -t ${{ steps.login-ecr.outputs.registry }}/sentra/security-controller:${{ github.sha }} .
          docker push ${{ steps.login-ecr.outputs.registry }}/sentra/security-controller:${{ github.sha }}

      - name: Build and push Dashboard image
        run: |
          cd dashboard
          docker build -t ${{ steps.login-ecr.outputs.registry }}/sentra/dashboard:${{ github.sha }} .
          docker push ${{ steps.login-ecr.outputs.registry }}/sentra/dashboard:${{ github.sha }}

      - name: Build and push Finance Agent image
        run: |
          cd finance_agent
          docker build -t ${{ steps.login-ecr.outputs.registry }}/sentra/finance-agent:${{ github.sha }} .
          docker push ${{ steps.login-ecr.outputs.registry }}/sentra/finance-agent:${{ github.sha }}

  deploy:
    needs: build
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v3
      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v2
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: us-east-1

      - name: Install CDK
        run: npm install -g aws-cdk

      - name: Deploy CDK stacks
        run: |
          cd cdk_app
          pip install -r requirements.txt
          cdk deploy --all --require-approval never
```

### Rollback Strategy

**Automated Rollback**:
- ECS deployment circuit breaker enabled (rolls back on health check failures)
- CloudFormation stack rollback on resource creation failures

**Manual Rollback**:
```bash
# Rollback ECS service to previous task definition
aws ecs update-service \
  --cluster sentra-mvp-cluster \
  --service security-controller \
  --task-definition sentra-security-controller:PREVIOUS_REVISION

# Rollback CDK stack to previous version
cdk deploy --all --rollback
```

---

## Monitoring & Observability

### CloudWatch Dashboards

**Dashboard 1: System Health**
- API Gateway request count, latency, errors
- ECS service CPU/memory utilization
- DynamoDB consumed read/write capacity

**Dashboard 2: Security Metrics**
- Denied requests (last 1 hour, 24 hours, 7 days)
- Threat type breakdown (prompt injection, jailbreak, etc.)
- Top 10 agents by denial count
- Policy violation heatmap

**Dashboard 3: Agent Activity**
- Requests per agent (last 24 hours)
- Tool usage breakdown
- Session duration distribution
- Abuse detection events

### Custom CloudWatch Metrics

```python
# app/utils/metrics.py
import boto3
from datetime import datetime

cloudwatch = boto3.client('cloudwatch')

def put_custom_metric(metric_name: str, value: float, unit: str = "Count"):
    """Publish custom metric to CloudWatch"""
    cloudwatch.put_metric_data(
        Namespace="Sentra/MVP",
        MetricData=[
            {
                "MetricName": metric_name,
                "Value": value,
                "Unit": unit,
                "Timestamp": datetime.utcnow()
            }
        ]
    )

# Usage in Security Controller:
put_custom_metric("RequestsBlocked", 1.0)
put_custom_metric("PromptInjectionDetected", 1.0)
put_custom_metric("PolicyViolations", 1.0)
put_custom_metric("ProcessingTimeMs", 45.2, "Milliseconds")
```

### CloudWatch Alarms

| Alarm | Threshold | Action |
|-------|-----------|--------|
| API 5xx Errors | > 10 in 5 min | SNS alert |
| API Latency (p99) | > 5 seconds | SNS alert |
| ECS CPU > 80% | 2 consecutive periods | SNS alert |
| ECS Memory > 80% | 2 consecutive periods | SNS alert |
| DynamoDB Throttling | > 0 | SNS alert |
| Security Denials Spike | > 100 in 5 min | SNS alert |

---

## Cost Analysis

### Monthly Cost Breakdown (Production MVP)

**Compute (ECS Fargate)**:
```
3 services × 2 vCPU × 4 GB RAM × 730 hours/month

Per-hour cost:
- 2 vCPU: $0.04048/hour
- 4 GB RAM: $0.004445/GB/hour × 4 = $0.01778/hour
- Total per task: $0.05826/hour

Monthly cost:
- 3 tasks × $0.05826 × 730 hours = $127.63/month
```

**Storage (DynamoDB On-Demand)**:
```
Assumptions:
- 10,000 requests/day
- 1 KB average item size
- 90-day retention (audit_logs)

audit_logs:
- Writes: 10,000/day × 30 days × $1.25/million = $0.38/month
- Reads: 5,000/day × 30 days × $0.25/million = $0.04/month
- Storage: 10,000 × 90 days × 1 KB × $0.25/GB = $0.23/month
- Total: ~$0.65/month

session_context:
- Writes: 10,000/day × 30 days × $1.25/million = $0.38/month
- Reads: 20,000/day × 30 days × $0.25/million = $0.15/month
- Storage: Minimal (24-hour TTL) = $0.01/month
- Total: ~$0.54/month

policies:
- Writes: 100/month × $1.25/million = $0.00/month
- Reads: 10,000/day × 30 days × $0.25/million = $0.08/month
- Storage: Minimal = $0.01/month
- Total: ~$0.09/month

Total DynamoDB: ~$1.28/month
```

**Storage (S3)**:
```
Assumptions:
- 1 GB Sigma rules + SBOM
- 10 GB compliance exports/month

Standard storage: 11 GB × $0.023/GB = $0.25/month
Requests (PUT/GET): ~$0.01/month
Total S3: ~$0.26/month
```

**Networking (VPC, NAT Gateway)**:
```
NAT Gateway: 1 × $0.045/hour × 730 hours = $32.85/month
Data processing: 10 GB × $0.045/GB = $0.45/month
Total Networking: ~$33.30/month
```

**API Gateway (Private REST API)**:
```
Requests: 10,000/day × 30 days = 300,000/month
First 333M requests: $3.50 per million
Total: 0.3M × $3.50 = $1.05/month
```

**CloudWatch (Logs + Metrics)**:
```
Logs ingestion: 50 GB × $0.50/GB = $25.00/month
Logs storage: 50 GB × $0.03/GB = $1.50/month
Custom metrics: 10 metrics × $0.30/metric = $3.00/month
Alarms: 5 alarms × $0.10/alarm = $0.50/month
Total CloudWatch: ~$30.00/month
```

**Total Monthly Cost**:
```
ECS Fargate:    $127.63
DynamoDB:       $1.28
S3:             $0.26
Networking:     $33.30
API Gateway:    $1.05
CloudWatch:     $30.00
────────────────────────
TOTAL:          ~$193.52/month
```

### Cost Optimization Strategies

**For MVP Demo (Reduce to ~$100/month)**:
1. Reduce ECS task count to 1 per service during idle times
2. Use CloudWatch Logs retention of 3 days (instead of 7)
3. Reduce DynamoDB TTL to 30 days (instead of 90)
4. Use single AZ deployment (remove cross-AZ traffic costs)

**For Production (Scale to 1000s of agents)**:
1. Use ECS auto-scaling based on CPU/memory metrics
2. Switch DynamoDB to provisioned capacity with auto-scaling
3. Use S3 Intelligent-Tiering for compliance exports
4. Implement API Gateway caching (reduce backend hits by 50%)

---

## Future Expansion Path

### Phase 2: Model Governance (Months 2-4)

**New Components**:
- Model registry integration (MLflow, Weights & Biases)
- Model version tracking in DynamoDB
- Model SBOM generation (training data lineage)
- Model drift detection (basic statistical checks)

**CDK Changes**:
```python
# Add new DynamoDB table: model_registry
self.model_registry_table = dynamodb.Table(
    self, "ModelRegistryTable",
    table_name="sentra-model-registry",
    partition_key=dynamodb.Attribute(name="model_id", type=dynamodb.AttributeType.STRING),
    sort_key=dynamodb.Attribute(name="version", type=dynamodb.AttributeType.NUMBER)
)

# Add new ECS service: Model Governance Service
# (similar to Security Controller, but for model validation)
```

**API Changes**:
```python
# New endpoint: POST /validate_model
@app.post("/validate_model")
async def validate_model(
    model_id: str,
    model_version: int,
    input_data: Dict[str, Any]
):
    """Validate model inputs against governance policies"""
    # Check model is approved for production
    # Validate input data schema
    # Check for data drift
    # Return ALLOW/DENY
```

### Phase 3: Data Governance (Months 5-8)

**New Components**:
- Data lineage tracking (S3, Snowflake, BigQuery connectors)
- PII detection engine (using AWS Macie or custom NLP)
- Data classification policies (Confidential, Internal, Public)
- Data access audit logs

**CDK Changes**:
```python
# Add new Lambda function: Data Scanner
self.data_scanner_lambda = _lambda.Function(
    self, "DataScannerLambda",
    runtime=_lambda.Runtime.PYTHON_3_11,
    handler="scanner.handler",
    code=_lambda.Code.from_asset("lambda/data_scanner")
)

# Trigger on S3 PUT events
self.artifacts_bucket.add_event_notification(
    s3.EventType.OBJECT_CREATED,
    s3n.LambdaDestination(self.data_scanner_lambda)
)
```

### Phase 4: Workflow Governance (Months 9-12)

**New Components**:
- Multi-agent workflow orchestration (DAG-based)
- Cross-agent communication policies
- Workflow approval gates (human-in-the-loop)
- Workflow versioning and rollback

**Architecture Evolution**:
```
┌─────────────────────────────────────────────────────────┐
│  Sentra Platform (Full AI Governance)                  │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │   Agent      │  │    Model     │  │     Data     │ │
│  │  Governance  │  │  Governance  │  │  Governance  │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
│                            │                            │
│                            ▼                            │
│                  ┌──────────────────┐                  │
│                  │    Workflow      │                  │
│                  │   Orchestrator   │                  │
│                  └──────────────────┘                  │
│                                                         │
│  Unified Policy Engine | Audit Trail | Observability   │
└─────────────────────────────────────────────────────────┘
```

---

## Appendix: Reference Links

**AWS Documentation**:
- [ECS Fargate Best Practices](https://docs.aws.amazon.com/AmazonECS/latest/bestpracticesguide/intro.html)
- [DynamoDB On-Demand Pricing](https://aws.amazon.com/dynamodb/pricing/on-demand/)
- [API Gateway Private REST APIs](https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-private-apis.html)
- [AWS CDK Python Reference](https://docs.aws.amazon.com/cdk/api/v2/python/)

**Security Standards**:
- [OWASP LLM Top 10 (2025)](https://owasp.org/www-project-top-10-for-large-language-model-applications/)
- [Sigma Rule Specification](https://github.com/SigmaHQ/sigma/wiki/Specification)
- [CycloneDX SBOM Standard](https://cyclonedx.org/)

**Competitor References**:
- [AWS Bedrock Guardrails](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html)
- [Lakera Guard](https://www.lakera.ai/products/guard)
- [Rubrik Agent Rewind](https://www.rubrik.com/products/agent-rewind)

---

**Document Status**: Complete technical design for 4-week MVP
**Next Steps**: Create `tasks.md` with week-by-week implementation plan
**Estimated Implementation Time**: 4 weeks (160 hours) with 1-2 engineers
