"""
Sentra MVP - Compute Stack
Creates ECS Cluster, ECR Repositories, IAM Roles, ALB, and ECS Services

Reference: LLD 01 Section 4 (Compute Stack)
ADRs: ADR-001 (ECS Fargate), ADR-012 (ALB vs NLB), ADR-016 (Task Sizing)
"""

from aws_cdk import (
    Stack,
    RemovalPolicy,
    CfnOutput,
    Duration,
    CustomResource,
    aws_ecs as ecs,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_logs as logs,
    aws_elasticloadbalancingv2 as elbv2,
    aws_servicediscovery as servicediscovery,
    aws_certificatemanager as acm,
    aws_acmpca as acmpca,
    aws_lambda as lambda_,
)
from constructs import Construct
from typing import Dict, Any


class ComputeStack(Stack):
    """
    Compute Stack - Container Orchestration Layer

    Creates (Task 9):
    - ECS Cluster with Container Insights enabled
    - 4 ECR Repositories: security-controller, dashboard, customer-query-agent, payment-agent
    - Image scanning on push, lifecycle rules (keep last 10 images)

    Future Tasks (10-12):
    - IAM Roles for ECS tasks (Task 10)
    - Application Load Balancer and Target Groups (Task 11)
    - ECS Task Definitions and Services (Task 12)

    Exports:
    - ECS Cluster name and ARN
    - ECR Repository URIs (4)
    - ALB DNS name (Task 11)
    - Service ARNs (Task 12)
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        config: Dict[str, Any],
        network_stack,  # Reference to NetworkStack for VPC
        storage_stack,  # Reference to StorageStack for DynamoDB/S3
        cognito_stack,  # Reference to CognitoStack for Public ALB authentication
        **kwargs
    ) -> None:
        """
        Initialize Compute Stack

        Args:
            scope: CDK app scope
            construct_id: Stack identifier
            config: Configuration dict from YAML (no hard-coded values)
            network_stack: NetworkStack instance for VPC references
            storage_stack: StorageStack instance for DynamoDB/S3 references
            cognito_stack: CognitoStack instance for Cognito User Pool
            **kwargs: Additional stack properties
        """
        super().__init__(scope, construct_id, **kwargs)

        # Extract configuration
        compute_config = config.get("compute", {})
        naming_config = config.get("naming", {})
        prefix = naming_config.get("prefix", "sentra-mvp")

        # ============================================================
        # ECS Cluster (Task 9)
        # ============================================================
        # See LLD Section 4.1 and ADR-001 for ECS Fargate choice
        # Container Insights enabled for CloudWatch monitoring
        # Associated with VPC from NetworkStack

        cluster_config = compute_config.get("ecs_cluster", {})

        self.ecs_cluster = ecs.Cluster(
            self,
            "EcsCluster",
            cluster_name=cluster_config.get("cluster_name", "sentra-mvp-cluster"),
            vpc=network_stack.vpc,
            container_insights=cluster_config.get("container_insights", True),  # Enable CloudWatch Container Insights
        )

        # ============================================================
        # Service Discovery - Use from Network Stack
        # ============================================================
        # Network Stack created both Route53 zone and Service Discovery namespace
        # Just reference it here

        # ECR repositories now created in StorageStack
        # Reference them via storage_stack.ecr_repositories

        # ============================================================
        # CloudFormation Outputs - ECS Cluster (Task 9)
        # ============================================================

        CfnOutput(
            self,
            "EcsClusterName",
            value=self.ecs_cluster.cluster_name,
            description="ECS Cluster name for Sentra MVP services",
            export_name=f"{prefix}-ecs-cluster-name",
        )

        CfnOutput(
            self,
            "EcsClusterArn",
            value=self.ecs_cluster.cluster_arn,
            description="ECS Cluster ARN",
            export_name=f"{prefix}-ecs-cluster-arn",
        )

        # ============================================================
        # Task 10 - IAM Roles for ECS Tasks
        # ============================================================
        # See LLD Section 4.3 and 4.4 for IAM permissions design
        # Each service gets a Task Role (for application permissions)
        # All services share a Task Execution Role (for ECS infrastructure)

        # ------------------------------------------------------------
        # Shared Task Execution Role (used by all 4 services)
        # ------------------------------------------------------------
        # Purpose: Allow ECS to pull images from ECR and write logs to CloudWatch
        # Used by: All ECS task definitions

        self.task_execution_role = iam.Role(
            self,
            "TaskExecutionRole",
            role_name=f"{prefix}-task-execution-role",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            description="Shared execution role for all Sentra ECS tasks (ECR pull, CloudWatch logging)",
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AmazonECSTaskExecutionRolePolicy"),
            ],
        )

        # ------------------------------------------------------------
        # Security Controller Task Role
        # ------------------------------------------------------------
        # Purpose: Validate requests, enforce policies, detect threats
        # Permissions: DynamoDB (session-context R/W, policies R), S3 (sigma_rules R, policies R, debug_logs W),
        #              CloudWatch Logs (audit logs W), CloudWatch Metrics (custom metrics W), Bedrock (optional)

        self.security_controller_task_role = iam.Role(
            self,
            "SecurityControllerTaskRole",
            role_name=f"{prefix}-security-controller-task-role",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            description="Task role for Security Controller service",
        )

        # DynamoDB permissions (legacy tables)
        storage_stack.session_context_table.grant_read_write_data(self.security_controller_task_role)
        storage_stack.policies_table.grant_read_data(self.security_controller_task_role)
        
        # DynamoDB permissions (Data Model v2 tables - Workstream 6, Task 1.5)
        storage_stack.agent_registry_table.grant_read_data(self.security_controller_task_role)
        storage_stack.tool_registry_table.grant_read_data(self.security_controller_task_role)
        # Policies metadata: read + write for CRUD operations (Workstream 11)
        storage_stack.policies_metadata_table.grant_read_write_data(self.security_controller_task_role)
        storage_stack.sigma_rules_metadata_table.grant_read_data(self.security_controller_task_role)

        # S3 permissions - read sigma_rules and policies, write debug_logs
        storage_stack.artifacts_bucket.grant_read(
            self.security_controller_task_role,
            objects_key_pattern="sigma_rules/*"
        )
        # Policies: read + write for CRUD operations (Workstream 11)
        storage_stack.artifacts_bucket.grant_read_write(
            self.security_controller_task_role,
            objects_key_pattern="policies/*"
        )
        storage_stack.artifacts_bucket.grant_put(
            self.security_controller_task_role,
            objects_key_pattern="debug_logs/*"
        )

        # CloudWatch Logs - write audit logs and query for GET /v1/logs endpoint
        storage_stack.audit_log_group.grant_write(self.security_controller_task_role)
        
        # Additional CloudWatch Logs permissions for audit logger and logs service
        self.security_controller_task_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "logs:CreateLogGroup",      # For audit logger to create log groups
                    "logs:CreateLogStream",     # For audit logger to create log streams
                    "logs:PutLogEvents",        # For audit logger to write logs
                    "logs:StartQuery",          # For logs service to query CloudWatch Logs Insights
                    "logs:GetQueryResults",     # For logs service to retrieve query results
                    "logs:StopQuery",           # For logs service to stop queries
                ],
                resources=[
                    storage_stack.audit_log_group_arn,
                    f"{storage_stack.audit_log_group_arn}:*",  # Include log streams
                ]
            )
        )

        # CloudWatch Metrics - custom metrics for metrics publisher
        self.security_controller_task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],  # CloudWatch metrics don't support resource-level permissions
            )
        )

        # ECS permissions - read service status for agent monitoring
        self.security_controller_task_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ecs:DescribeServices",
                    "ecs:ListServices",
                    "ecs:DescribeTasks",
                    "ecs:ListTasks"
                ],
                resources=["*"],  # Scoped to cluster in practice
                effect=iam.Effect.ALLOW
            )
        )

        # Bedrock permissions for validation and LLM-formatted DENY responses (Workstream 9)
        self.security_controller_task_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:ListFoundationModels"  # For health checks
                ],
                resources=[
                    # Allow all foundation models and inference profiles
                    f"arn:aws:bedrock:*::foundation-model/*",
                    f"arn:aws:bedrock:*:{self.account}:inference-profile/*",
                    "*"  # ListFoundationModels requires wildcard resource
                ]
            )
        )

        # ------------------------------------------------------------
        # Dashboard Task Role
        # ------------------------------------------------------------
        # Purpose: Display monitoring dashboard, query audit logs
        # Permissions: CloudWatch Logs (audit logs - StartQuery, GetQueryResults),
        #              DynamoDB (session-context R)

        self.dashboard_task_role = iam.Role(
            self,
            "DashboardTaskRole",
            role_name=f"{prefix}-dashboard-task-role",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            description="Task role for Dashboard service",
        )

        # CloudWatch Logs - query audit logs
        self.dashboard_task_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "logs:StartQuery",
                    "logs:GetQueryResults",
                    "logs:StopQuery",
                    "logs:FilterLogEvents",
                    "logs:GetLogEvents",
                ],
                resources=[storage_stack.audit_log_group_arn]
            )
        )

        # DynamoDB - read session context for monitoring
        storage_stack.session_context_table.grant_read_data(self.dashboard_task_role)

        # Bedrock - Claude for LLM-formatted DENY responses (Workstream 9 - Milestone 2)
        self.dashboard_task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=[
                    # Allow all foundation models and inference profiles
                    f"arn:aws:bedrock:*::foundation-model/*",
                    f"arn:aws:bedrock:*:{self.account}:inference-profile/*"
                ]
            )
        )

        # Bedrock Agents - Allow dashboard to invoke and list Bedrock agents
        self.dashboard_task_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:InvokeAgent",
                    "bedrock:ListAgents",
                    "bedrock:GetAgent",
                ],
                resources=[
                    f"arn:aws:bedrock:{self.region}:{self.account}:agent/*",
                    f"arn:aws:bedrock:{self.region}:{self.account}:agent-alias/*",
                ]
            )
        )

        # ------------------------------------------------------------
        # Customer Query Agent Task Role
        # ------------------------------------------------------------
        # Purpose: Query customer/order data (demo agent)
        # Permissions: DynamoDB (demo-customers R, demo-orders R), Bedrock (Claude Sonnet)

        self.customer_query_agent_task_role = iam.Role(
            self,
            "CustomerQueryAgentTaskRole",
            role_name=f"{prefix}-customer-query-agent-task-role",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            description="Task role for Customer Query Agent service",
        )

        # DynamoDB - read demo data
        storage_stack.demo_customers_table.grant_read_data(self.customer_query_agent_task_role)
        storage_stack.demo_orders_table.grant_read_data(self.customer_query_agent_task_role)

        # Bedrock - Claude models for natural language queries (Workstream 9 - LLM Response Generation)
        self.customer_query_agent_task_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:ListFoundationModels"  # For health checks
                ],
                resources=[
                    # Allow all foundation models and inference profiles
                    f"arn:aws:bedrock:*::foundation-model/*",
                    f"arn:aws:bedrock:*:{self.account}:inference-profile/*",
                    "*"  # ListFoundationModels requires wildcard resource
                ]
            )
        )

        # ------------------------------------------------------------
        # Payment Agent Task Role
        # ------------------------------------------------------------
        # Purpose: Process refunds and payment operations (demo agent)
        # Permissions: DynamoDB (demo-orders R/W for refund updates), Bedrock (Claude Sonnet)

        self.payment_agent_task_role = iam.Role(
            self,
            "PaymentAgentTaskRole",
            role_name=f"{prefix}-payment-agent-task-role",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            description="Task role for Payment Agent service",
        )

        # DynamoDB - read/write demo orders (for refund updates)
        storage_stack.demo_orders_table.grant_read_write_data(self.payment_agent_task_role)

        # Bedrock - Claude models for natural language processing (Workstream 9 - LLM Response Generation)
        self.payment_agent_task_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:ListFoundationModels"  # For health checks
                ],
                resources=[
                    # Allow all foundation models and inference profiles
                    f"arn:aws:bedrock:*::foundation-model/*",
                    f"arn:aws:bedrock:*:{self.account}:inference-profile/*",
                    "*"  # ListFoundationModels requires wildcard resource
                ]
            )
        )

        # ------------------------------------------------------------
        # Demo Orchestrator Task Role (Workstream 13)
        # ------------------------------------------------------------
        # Purpose: Execute security test scenarios against agents
        # Permissions: Bedrock (invoke agents), CloudWatch Logs (write demo logs),
        #              HTTP access to self-hosted agents via ALB

        self.demo_orchestrator_task_role = iam.Role(
            self,
            "DemoOrchestratorTaskRole",
            role_name=f"{prefix}-demo-orchestrator-task-role",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            description="Task role for Demo Orchestrator service",
        )

        # Bedrock - Invoke Bedrock agents (secured and unsecured)
        self.demo_orchestrator_task_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:InvokeAgent",
                    "bedrock:ListAgents",
                    "bedrock:GetAgent"
                ],
                resources=["*"]
            )
        )

        # CloudWatch Logs - Write demo scenario logs to audit log group
        storage_stack.audit_log_group.grant_write(self.demo_orchestrator_task_role)
        self.demo_orchestrator_task_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "logs:CreateLogStream",
                    "logs:PutLogEvents"
                ],
                resources=[
                    storage_stack.audit_log_group_arn,
                    f"{storage_stack.audit_log_group_arn}:*"
                ]
            )
        )

        # DynamoDB - Read demo orders table (for order ID resolution in scenarios)
        storage_stack.demo_orders_table.grant_read_data(self.demo_orchestrator_task_role)

        # ============================================================
        # CloudFormation Outputs - IAM Roles (Task 10)
        # ============================================================

        CfnOutput(
            self,
            "TaskExecutionRoleArn",
            value=self.task_execution_role.role_arn,
            description="Shared Task Execution Role ARN (used by all ECS tasks)",
            export_name=f"{prefix}-task-execution-role-arn",
        )

        CfnOutput(
            self,
            "SecurityControllerTaskRoleArn",
            value=self.security_controller_task_role.role_arn,
            description="Security Controller Task Role ARN",
            export_name=f"{prefix}-security-controller-task-role-arn",
        )

        CfnOutput(
            self,
            "DashboardTaskRoleArn",
            value=self.dashboard_task_role.role_arn,
            description="Dashboard Task Role ARN",
            export_name=f"{prefix}-dashboard-task-role-arn",
        )

        CfnOutput(
            self,
            "CustomerQueryAgentTaskRoleArn",
            value=self.customer_query_agent_task_role.role_arn,
            description="Customer Query Agent Task Role ARN",
            export_name=f"{prefix}-customer-query-agent-task-role-arn",
        )

        CfnOutput(
            self,
            "PaymentAgentTaskRoleArn",
            value=self.payment_agent_task_role.role_arn,
            description="Payment Agent Task Role ARN",
            export_name=f"{prefix}-payment-agent-task-role-arn",
        )

        CfnOutput(
            self,
            "DemoOrchestratorTaskRoleArn",
            value=self.demo_orchestrator_task_role.role_arn,
            description="Demo Orchestrator Task Role ARN",
            export_name=f"{prefix}-demo-orchestrator-task-role-arn",
        )

        # ============================================================
        # Task 11 - Application Load Balancer and Target Groups
        # ============================================================
        # See LLD Section 4.5 and ADR-012 for ALB design
        # Private ALB (not internet-facing) for internal routing
        # Split ALB Architecture (Workstream 8)
        # Public ALB: Dashboard only (with Cognito authentication)
        # Private ALB: API services (Security Controller, Customer Query Agent, Payment Agent)

        alb_config = compute_config.get("alb", {})

        # ============================================================
        # Public ALB - Dashboard Only (with Cognito Authentication)
        # ============================================================
        # Self-Signed Certificate for HTTPS (MVP/Demo)
        # ============================================================
        # Using imported self-signed certificate for HTTPS
        # Certificate: *.elb.amazonaws.com (wildcard for all ALB DNS names)
        # Valid for: 365 days
        # Note: Browsers will show security warning (expected for self-signed certs)
        
        self.alb_certificate = acm.Certificate.from_certificate_arn(
            self,
            "ALBCertificate",
            certificate_arn="arn:aws:acm:us-east-1:531109575379:certificate/70506764-c759-4737-b8aa-8498924d4c85"
        )

        # ============================================================

        self.public_alb = elbv2.ApplicationLoadBalancer(
            self,
            "PublicApplicationLoadBalancer",
            load_balancer_name="sentra-public-alb",
            vpc=network_stack.vpc,
            internet_facing=True,  # Public ALB
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            security_group=network_stack.public_alb_sg,
            deletion_protection=False,
            idle_timeout=Duration.seconds(60)
        )

        # ============================================================
        # Private ALB - API Services Only (No Authentication)
        # ============================================================

        self.private_alb = elbv2.ApplicationLoadBalancer(
            self,
            "PrivateApplicationLoadBalancer",
            load_balancer_name="sentra-private-alb",
            vpc=network_stack.vpc,
            internet_facing=False,  # Private ALB (KEY!)
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_group=network_stack.private_alb_sg,
            deletion_protection=False,
            idle_timeout=Duration.seconds(60)
        )

        # ============================================================
        # Target Groups
        # ============================================================
        # Dashboard → Public ALB
        # API Services → Private ALB

        # Dashboard Target Group (Public ALB)
        self.dashboard_tg = elbv2.ApplicationTargetGroup(
            self,
            "DashboardTargetGroup",
            target_group_name="sentra-dashboard-tg",
            vpc=network_stack.vpc,
            port=8501,
            protocol=elbv2.ApplicationProtocol.HTTP,
            target_type=elbv2.TargetType.IP,
            health_check=elbv2.HealthCheck(
                path="/_stcore/health",
                interval=Duration.seconds(60),
                timeout=Duration.seconds(10),
                healthy_threshold_count=2,
                unhealthy_threshold_count=3
            ),
            deregistration_delay=Duration.seconds(30)
        )

        # Security Controller Target Group (Private ALB)
        self.security_controller_tg = elbv2.ApplicationTargetGroup(
            self,
            "SecurityControllerTargetGroup",
            target_group_name="sentra-sc-tg",
            vpc=network_stack.vpc,
            port=8080,
            protocol=elbv2.ApplicationProtocol.HTTP,
            target_type=elbv2.TargetType.IP,
            health_check=elbv2.HealthCheck(
                path="/v1/health",
                interval=Duration.seconds(60),
                timeout=Duration.seconds(10),
                healthy_threshold_count=2,
                unhealthy_threshold_count=3
            ),
            deregistration_delay=Duration.seconds(30)
        )

        # Customer Query Agent Target Group (Private ALB)
        self.customer_query_agent_tg = elbv2.ApplicationTargetGroup(
            self,
            "CustomerQueryAgentTargetGroup",
            target_group_name="sentra-cqa-tg",
            vpc=network_stack.vpc,
            port=8080,
            protocol=elbv2.ApplicationProtocol.HTTP,
            target_type=elbv2.TargetType.IP,
            health_check=elbv2.HealthCheck(
                path="/v1/health",
                interval=Duration.seconds(60),
                timeout=Duration.seconds(10),
                healthy_threshold_count=2,
                unhealthy_threshold_count=3
            ),
            deregistration_delay=Duration.seconds(30)
        )

        # Payment Agent Target Group (Private ALB)
        self.payment_agent_tg = elbv2.ApplicationTargetGroup(
            self,
            "PaymentAgentTargetGroup",
            target_group_name="sentra-pa-tg",
            vpc=network_stack.vpc,
            port=8080,
            protocol=elbv2.ApplicationProtocol.HTTP,
            target_type=elbv2.TargetType.IP,
            health_check=elbv2.HealthCheck(
                path="/v1/health",
                interval=Duration.seconds(60),
                timeout=Duration.seconds(10),
                healthy_threshold_count=2,
                unhealthy_threshold_count=3
            ),
            deregistration_delay=Duration.seconds(30)
        )

        # ============================================================
        # Public ALB Listeners (Dashboard with HTTPS + Cognito Auth)
        # ============================================================
        
        # HTTP listener - redirect to HTTPS
        self.public_http_listener = self.public_alb.add_listener(
            "PublicHttpListener",
            port=80,
            protocol=elbv2.ApplicationProtocol.HTTP,
            default_action=elbv2.ListenerAction.redirect(
                protocol="HTTPS",
                port="443",
                permanent=True
            )
        )
        
        # HTTPS listener with Cognito authentication
        # Using CfnListener because L2 construct doesn't support authenticate-cognito
        self.public_https_listener = elbv2.CfnListener(
            self,
            "PublicHttpsListener",
            load_balancer_arn=self.public_alb.load_balancer_arn,
            port=443,
            protocol="HTTPS",
            certificates=[elbv2.CfnListener.CertificateProperty(
                certificate_arn=self.alb_certificate.certificate_arn
            )],
            default_actions=[
                elbv2.CfnListener.ActionProperty(
                    type="authenticate-cognito",
                    authenticate_cognito_config=elbv2.CfnListener.AuthenticateCognitoConfigProperty(
                        user_pool_arn=cognito_stack.user_pool.user_pool_arn,
                        user_pool_client_id=cognito_stack.user_pool_client.user_pool_client_id,
                        user_pool_domain=f"{cognito_stack.user_pool_domain.domain_name}.auth.{self.region}.amazoncognito.com",
                        scope="openid email profile",
                        session_timeout="3600",  # String required by CfnListener (1 hour)
                        on_unauthenticated_request="authenticate"
                    ),
                    order=1
                ),
                elbv2.CfnListener.ActionProperty(
                    type="forward",
                    target_group_arn=self.dashboard_tg.target_group_arn,
                    order=2
                )
            ]
        )

        # ============================================================
        # Private ALB Listener (API Services with Path-Based Routing)
        # ============================================================

        self.private_http_listener = self.private_alb.add_listener(
            "PrivateHttpListener",
            port=80,
            protocol=elbv2.ApplicationProtocol.HTTP,
            default_action=elbv2.ListenerAction.fixed_response(
                status_code=404,
                content_type="text/plain",
                message_body="Not Found"
            )
        )

        # Priority 1: Security Controller endpoints (core APIs)
        self.private_http_listener.add_action(
            "SecurityControllerRoutingCore",
            priority=1,
            conditions=[
                elbv2.ListenerCondition.path_patterns([
                    "/v1/validate*",
                    "/v1/health",
                    "/v1/logs*",
                    "/v1/sessions*",
                    "/v1/metrics*"
                ])
            ],
            action=elbv2.ListenerAction.forward(
                target_groups=[self.security_controller_tg]
            )
        )

        # Priority 4: Security Controller endpoints (management APIs)
        self.private_http_listener.add_action(
            "SecurityControllerRoutingManagement",
            priority=4,
            conditions=[
                elbv2.ListenerCondition.path_patterns([
                    "/v1/agents*",
                    "/v1/policies*",
                    "/v1/sigma-rules*"
                ])
            ],
            action=elbv2.ListenerAction.forward(
                target_groups=[self.security_controller_tg]
            )
        )

        # Priority 2: Customer Query Agent endpoints
        self.private_http_listener.add_action(
            "CustomerQueryAgentRouting",
            priority=2,
            conditions=[
                elbv2.ListenerCondition.path_patterns([
                    "/v1/agents/customer-query/*"
                ])
            ],
            action=elbv2.ListenerAction.forward(
                target_groups=[self.customer_query_agent_tg]
            )
        )

        # Priority 3: Payment Agent endpoints
        self.private_http_listener.add_action(
            "PaymentAgentRouting",
            priority=3,
            conditions=[
                elbv2.ListenerCondition.path_patterns([
                    "/v1/agents/payment/*"
                ])
            ],
            action=elbv2.ListenerAction.forward(
                target_groups=[self.payment_agent_tg]
            )
        )

        # ============================================================
        # CloudFormation Outputs - ALBs and Target Groups
        # ============================================================

        # Public ALB Outputs
        CfnOutput(
            self,
            "PublicAlbDnsName",
            value=self.public_alb.load_balancer_dns_name,
            description="Public ALB DNS name (Dashboard access)",
            export_name=f"{prefix}-public-alb-dns-name",
        )

        CfnOutput(
            self,
            "PublicAlbArn",
            value=self.public_alb.load_balancer_arn,
            description="Public ALB ARN",
            export_name=f"{prefix}-public-alb-arn",
        )

        # Private ALB Outputs
        CfnOutput(
            self,
            "PrivateAlbDnsName",
            value=self.private_alb.load_balancer_dns_name,
            description="Private ALB DNS name (API services - VPC internal only)",
            export_name=f"{prefix}-private-alb-dns-name",
        )

        CfnOutput(
            self,
            "PrivateAlbArn",
            value=self.private_alb.load_balancer_arn,
            description="Private ALB ARN",
            export_name=f"{prefix}-private-alb-arn",
        )

        CfnOutput(
            self,
            "SecurityControllerTargetGroupArn",
            value=self.security_controller_tg.target_group_arn,
            description="Security Controller Target Group ARN",
            export_name=f"{prefix}-security-controller-tg-arn",
        )

        CfnOutput(
            self,
            "DashboardTargetGroupArn",
            value=self.dashboard_tg.target_group_arn,
            description="Dashboard Target Group ARN",
            export_name=f"{prefix}-dashboard-tg-arn",
        )

        CfnOutput(
            self,
            "CustomerQueryAgentTargetGroupArn",
            value=self.customer_query_agent_tg.target_group_arn,
            description="Customer Query Agent Target Group ARN",
            export_name=f"{prefix}-customer-query-agent-tg-arn",
        )

        CfnOutput(
            self,
            "PaymentAgentTargetGroupArn",
            value=self.payment_agent_tg.target_group_arn,
            description="Payment Agent Target Group ARN",
            export_name=f"{prefix}-payment-agent-tg-arn",
        )

        # ============================================================
        # Update Cognito Callback URLs (After ALB Creation)
        # ============================================================
        # Use Custom Resource to update Cognito callback URLs with actual ALB DNS
        # This avoids circular dependency by keeping the update logic in Compute Stack

        # Lambda function to update Cognito callback URLs
        update_callback_lambda = lambda_.Function(
            self,
            "UpdateCallbackUrlsFunction",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="index.handler",
            code=lambda_.Code.from_inline("""
import json
import boto3
import cfnresponse

cognito = boto3.client('cognito-idp')

def handler(event, context):
    print(f"Event: {json.dumps(event)}")

    try:
        request_type = event['RequestType']

        if request_type in ['Create', 'Update']:
            user_pool_id = event['ResourceProperties']['UserPoolId']
            client_id = event['ResourceProperties']['ClientId']
            alb_dns_name = event['ResourceProperties']['AlbDnsName']

            callback_urls = [f"https://{alb_dns_name}/oauth2/idpresponse"]
            logout_urls = [f"https://{alb_dns_name}/"]

            print(f"Updating User Pool Client {client_id}")
            print(f"Callback URLs: {callback_urls}")
            print(f"Logout URLs: {logout_urls}")

            # Get current client configuration
            response = cognito.describe_user_pool_client(
                UserPoolId=user_pool_id,
                ClientId=client_id
            )

            client_config = response['UserPoolClient']

            # Update callback URLs
            cognito.update_user_pool_client(
                UserPoolId=user_pool_id,
                ClientId=client_id,
                ClientName=client_config['ClientName'],
                CallbackURLs=callback_urls,
                LogoutURLs=logout_urls,
                AllowedOAuthFlows=client_config.get('AllowedOAuthFlows', ['code']),
                AllowedOAuthScopes=client_config.get('AllowedOAuthScopes', ['openid', 'email', 'profile']),
                AllowedOAuthFlowsUserPoolClient=client_config.get('AllowedOAuthFlowsUserPoolClient', True),
                SupportedIdentityProviders=client_config.get('SupportedIdentityProviders', ['COGNITO'])
            )

            print("Callback URLs updated successfully")
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {
                'CallbackURLs': ','.join(callback_urls),
                'LogoutURLs': ','.join(logout_urls)
            })

        elif request_type == 'Delete':
            # No cleanup needed
            print("Delete request - no action needed")
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {})

        else:
            print(f"Unknown request type: {request_type}")
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {})

    except Exception as e:
        print(f"Error: {str(e)}")
        cfnresponse.send(event, context, cfnresponse.FAILED, {
            'Error': str(e)
        })
"""),
            timeout=Duration.seconds(30),
            description="Updates Cognito User Pool Client callback URLs after ALB creation",
        )

        # Grant Lambda permission to update Cognito
        update_callback_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "cognito-idp:DescribeUserPoolClient",
                    "cognito-idp:UpdateUserPoolClient",
                ],
                resources=[cognito_stack.user_pool.user_pool_arn],
            )
        )

        # Create Custom Resource to trigger the update
        CustomResource(
            self,
            "UpdateCallbackUrlsCustomResource",
            service_token=update_callback_lambda.function_arn,
            properties={
                "UserPoolId": cognito_stack.user_pool.user_pool_id,
                "ClientId": cognito_stack.user_pool_client.user_pool_client_id,
                "AlbDnsName": self.public_alb.load_balancer_dns_name,
            },
        )

        # ============================================================
        # Task 12 - ECS Task Definitions and Services
        # ============================================================
        # See LLD Section 4.3, 4.4 and ADR-016 for task sizing
        # Creates:
        # - 4 CloudWatch Log Groups for container logs (7-day retention)
        # - 4 Fargate Task Definitions (2 vCPU, 4 GB RAM)
        # - 4 ECS Services with Service Discovery
        # - Integration with ALB target groups

        task_config = compute_config.get("ecs_tasks", {})

        # ============================================================
        # CloudWatch Log Groups for Container Logs
        # ============================================================
        # See LLD Section 4.3 - 7-day retention for container logs
        # Separate log groups per service for better organization

        self.container_log_groups = {}

        service_configs = {
            "security-controller": {
                "log_group_name": "/ecs/sentra/security-controller",
                "port": 8080,
                "task_role": self.security_controller_task_role,
                "target_group": self.security_controller_tg,
                "environment": {
                    "PORT": "8080",
                    "SERVICE_NAME": "security-controller",
                    "SESSION_CONTEXT_TABLE": storage_stack.session_context_table.table_name,
                    "POLICIES_TABLE": storage_stack.policies_table.table_name,
                    "ARTIFACTS_BUCKET": storage_stack.artifacts_bucket.bucket_name,
                    "AWS_REGION": self.region,
                    "LOG_LEVEL": "INFO",
                    "SIGMA_RULES_PREFIX": "sigma_rules/llm/",
                    "SIGMA_REFRESH_INTERVAL": "300",
                    "POLICY_CACHE_TTL": "10",
                    "MAX_VALIDATION_TIME_MS": "5000",
                    "ENABLE_METRICS": "true",
                    "AUDIT_LOG_GROUP": storage_stack.audit_log_group.log_group_name,
                    # Data Model v2 Tables (Workstream 6, Task 1.5)
                    "AGENT_REGISTRY_TABLE": storage_stack.agent_registry_table.table_name,
                    "TOOL_REGISTRY_TABLE": storage_stack.tool_registry_table.table_name,
                    "POLICIES_METADATA_TABLE": storage_stack.policies_metadata_table.table_name,
                    "SIGMA_RULES_METADATA_TABLE": storage_stack.sigma_rules_metadata_table.table_name,
                    # Cache Configuration (Workstream 5, Task 1)
                    "CACHE_ENABLED": "true",
                    "AGENT_METADATA_CACHE_TTL_SECONDS": "60",
                    "TOOL_REGISTRY_CACHE_TTL_SECONDS": "300",
                    "POLICY_CACHE_TTL_SECONDS": "10",
                    "SIGMA_RULES_METADATA_CACHE_TTL_SECONDS": "600",
                    "MAX_CACHE_SIZE": "1000",
                },
                "health_check_command": ["CMD-SHELL", "curl -f http://localhost:8080/v1/health || exit 1"],
            },
            "dashboard": {
                "log_group_name": "/ecs/sentra/dashboard",
                "port": 8501,  # Streamlit default port
                "task_role": self.dashboard_task_role,
                "target_group": self.dashboard_tg,
                "environment": {
                    "PORT": "8501",
                    "SERVICE_NAME": "dashboard",
                    "SESSION_CONTEXT_TABLE": storage_stack.session_context_table.table_name,
                    "AUDIT_LOG_GROUP": storage_stack.audit_log_group.log_group_name,
                    "AWS_REGION": self.region,
                    # IMPORTANT: Use Private ALB for API calls
                    "SECURITY_CONTROLLER_URL": f"http://{self.private_alb.load_balancer_dns_name}",
                    "CUSTOMER_QUERY_AGENT_URL": f"http://{self.private_alb.load_balancer_dns_name}",
                    "PAYMENT_AGENT_URL": f"http://{self.private_alb.load_balancer_dns_name}",
                },
                "health_check_command": ["CMD-SHELL", "curl -f http://localhost:8501/_stcore/health || exit 1"],
            },
            "customer-query-agent": {
                "log_group_name": "/ecs/sentra/customer-query-agent",
                "port": 8080,
                "task_role": self.customer_query_agent_task_role,
                "target_group": self.customer_query_agent_tg,
                "environment": {
                    "PORT": "8080",
                    "SERVICE_NAME": "customer-query-agent",
                    "DEMO_CUSTOMERS_TABLE": storage_stack.demo_customers_table.table_name,
                    "DEMO_ORDERS_TABLE": storage_stack.demo_orders_table.table_name,
                    "SECURITY_CONTROLLER_URL": f"http://{self.private_alb.load_balancer_dns_name}",
                    "PAYMENT_AGENT_URL": f"http://{self.private_alb.load_balancer_dns_name}",
                    "BEDROCK_MODEL_ID": "us.anthropic.claude-3-5-sonnet-20241022-v2:0",  # Sonnet 3.5 v2 inference profile (faster, cheaper, no built-in guardrails)
                    "AWS_REGION": self.region,
                    "LOG_LEVEL": "INFO",
                },
                "health_check_command": ["CMD-SHELL", "curl -f http://localhost:8080/v1/health || exit 1"],
            },
            "payment-agent": {
                "log_group_name": "/ecs/sentra/payment-agent",
                "port": 8080,
                "task_role": self.payment_agent_task_role,
                "target_group": self.payment_agent_tg,
                "environment": {
                    "PORT": "8080",
                    "SERVICE_NAME": "payment-agent",
                    "DEMO_ORDERS_TABLE": storage_stack.demo_orders_table.table_name,
                    "SECURITY_CONTROLLER_URL": f"http://{self.private_alb.load_balancer_dns_name}",
                    "BEDROCK_MODEL_ID": "us.anthropic.claude-3-5-sonnet-20241022-v2:0",  # Sonnet 3.5 v2 inference profile (faster, cheaper, no built-in guardrails)
                    "AWS_REGION": self.region,
                    "LOG_LEVEL": "INFO",
                },
                "health_check_command": ["CMD-SHELL", "curl -f http://localhost:8080/v1/health || exit 1"],
            },
            "demo-orchestrator": {
                "log_group_name": "/ecs/sentra/demo-orchestrator",
                "port": 8080,
                "task_role": self.demo_orchestrator_task_role,
                "target_group": None,  # No ALB routing - internal service only
                "environment": {
                    "PORT": "8080",
                    "SERVICE_NAME": "demo-orchestrator",
                    "SECURITY_CONTROLLER_URL": f"http://{self.private_alb.load_balancer_dns_name}",
                    "PAYMENT_AGENT_URL": f"http://{self.private_alb.load_balancer_dns_name}",
                    "CUSTOMER_QUERY_AGENT_URL": f"http://{self.private_alb.load_balancer_dns_name}",
                    "AUDIT_LOG_GROUP": storage_stack.audit_log_group.log_group_name,
                    "AWS_REGION": self.region,
                    "LOG_LEVEL": "INFO",
                    "SCENARIOS_DIR": "/app/scenarios",
                    "AUTO_START_CONTINUOUS": "true",  # Auto-start continuous scenarios on boot
                    # Bedrock agent IDs discovered at runtime via ListAgents API
                    # No hardcoded IDs needed - eliminates CDK/Bedrock cyclic dependency
                },
                "health_check_command": ["CMD-SHELL", "curl -f http://localhost:8080/health || exit 1"],
            },
        }

        # Create log groups
        for service_name, config in service_configs.items():
            log_group = logs.LogGroup(
                self,
                f"{service_name.replace('-', ' ').title().replace(' ', '')}LogGroup",
                log_group_name=config["log_group_name"],
                retention=logs.RetentionDays.ONE_WEEK,  # 7-day retention as per LLD
                removal_policy=RemovalPolicy.DESTROY,  # Can delete when stack destroyed
            )
            self.container_log_groups[service_name] = log_group

        # ============================================================
        # ECS Task Definitions (Fargate)
        # ============================================================
        # See LLD Section 4.3 and ADR-016 for task sizing
        # Standard configuration: 2 vCPU (2048), 4 GB RAM (4096)
        # Each task uses placeholder image (will be updated when containers built)

        self.task_definitions = {}
        self.ecs_services = {}

        for service_name, config in service_configs.items():
            # Create task definition
            task_def = ecs.FargateTaskDefinition(
                self,
                f"{service_name.replace('-', ' ').title().replace(' ', '')}TaskDef",
                cpu=task_config.get("cpu", 2048),  # 2 vCPU
                memory_limit_mib=task_config.get("memory", 4096),  # 4 GB RAM
                task_role=config["task_role"],
                execution_role=self.task_execution_role,
                family=f"sentra-{service_name}",
            )

            # Add container to task definition
            container = task_def.add_container(
                f"{service_name.replace('-', ' ').title().replace(' ', '')}Container",
                container_name=service_name,
                # Use image from private ECR repository
                image=ecs.ContainerImage.from_registry(
                    f"{self.account}.dkr.ecr.{self.region}.amazonaws.com/sentra/{service_name}:latest"
                ),
                logging=ecs.LogDriver.aws_logs(
                    stream_prefix=service_name,
                    log_group=self.container_log_groups[service_name],
                ),
                environment=config["environment"],
                port_mappings=[
                    ecs.PortMapping(
                        container_port=config["port"],
                        protocol=ecs.Protocol.TCP,
                    )
                ],
                health_check=ecs.HealthCheck(
                    command=config["health_check_command"],
                    interval=Duration.seconds(30),
                    timeout=Duration.seconds(5),
                    retries=3,
                    start_period=Duration.seconds(60),
                ),
            )

            self.task_definitions[service_name] = task_def

        # ============================================================
        # ECS Services (With CloudMap Service Discovery)
        # ============================================================
        # See LLD Section 4.4 for service configuration
        # - Desired count: 1 (MVP)
        # - Min healthy: 0%, Max: 200% (allow rolling updates)
        # - Associated with target groups for ALB routing (external access)
        # - Cloud Map service discovery enabled (internal service-to-service communication)
        # - DNS names: service-name.sentra.internal (e.g., security-controller.sentra.internal)

        for service_name, config in service_configs.items():
            # Get security group for this service
            security_group_map = {
                "security-controller": network_stack.security_controller_sg,
                "dashboard": network_stack.dashboard_sg,
                "customer-query-agent": network_stack.customer_query_agent_sg,
                "payment-agent": network_stack.payment_agent_sg,
                "demo-orchestrator": network_stack.security_controller_sg,  # Reuse SC security group for internal service
            }

            # Create ECS service with Cloud Map service discovery
            # Services are accessible via:
            # 1. Private ALB path-based routing (primary)
            # 2. Cloud Map DNS using Network Stack's Route53 zone (service-to-service)
            # Circuit breaker enabled with rollback for production readiness
            service = ecs.FargateService(
                self,
                f"{service_name.replace('-', ' ').title().replace(' ', '')}Service",
                service_name=f"sentra-{service_name}",
                cluster=self.ecs_cluster,
                task_definition=self.task_definitions[service_name],
                desired_count=task_config.get("desired_count", 1),  # 1 for MVP
                min_healthy_percent=50,  # Keep 50% healthy during updates
                max_healthy_percent=200,  # Can have 2 tasks during updates
                vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
                security_groups=[security_group_map[service_name]],
                circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),  # Enable auto-rollback
                health_check_grace_period=Duration.seconds(120),  # Give containers 120s to start before health checks
                enable_execute_command=True,  # Allow debugging via ECS Exec
                # Enable Cloud Map service discovery using Network Stack's Service Discovery namespace
                cloud_map_options=ecs.CloudMapOptions(
                    name=service_name,  # DNS name: security-controller.sentra.internal
                    cloud_map_namespace=network_stack.service_discovery_namespace,
                    dns_record_type=servicediscovery.DnsRecordType.A,  # A record pointing to task IP
                    dns_ttl=Duration.seconds(10),  # Low TTL for faster updates
                    container=self.task_definitions[service_name].default_container,
                    container_port=config["port"],
                ),
            )

            # Associate service with target group (if it has one)
            if config["target_group"] is not None:
                service.attach_to_application_target_group(config["target_group"])
                
                # Add explicit dependency on ALB listeners to ensure target groups are attached first
                if service_name == "dashboard":
                    service.node.add_dependency(self.public_https_listener)
                else:
                    service.node.add_dependency(self.private_http_listener)

            self.ecs_services[service_name] = service

        # ============================================================
        # CloudFormation Outputs - ECS Services (Task 12)
        # ============================================================

        for service_name in service_configs.keys():
            CfnOutput(
                self,
                f"{service_name.replace('-', ' ').title().replace(' ', '')}ServiceArn",
                value=self.ecs_services[service_name].service_arn,
                description=f"ECS Service ARN for {service_name}",
                export_name=f"{prefix}-{service_name}-service-arn",
            )

            CfnOutput(
                self,
                f"{service_name.replace('-', ' ').title().replace(' ', '')}ServiceName",
                value=self.ecs_services[service_name].service_name,
                description=f"ECS Service name for {service_name}",
                export_name=f"{prefix}-{service_name}-service-name",
            )

        # Note: Services are accessible via both:
        # 1. Cloud Map service discovery (internal): http://service-name.sentra.internal:port
        # 2. ALB routing (external): http://alb-dns/path

    @property
    def cluster_name(self) -> str:
        """Return ECS cluster name for cross-stack references"""
        return self.ecs_cluster.cluster_name

    @property
    def cluster_arn(self) -> str:
        """Return ECS cluster ARN for cross-stack references"""
        return self.ecs_cluster.cluster_arn

    def get_repository_uri(self, repo_name: str) -> str:
        """
        Get ECR repository URI by name

        Args:
            repo_name: Repository name (e.g., "security-controller")

        Returns:
            ECR repository URI
        """
        if repo_name not in self.ecr_repositories:
            raise ValueError(f"Repository {repo_name} not found. Available: {list(self.ecr_repositories.keys())}")
        return self.ecr_repositories[repo_name].repository_uri
