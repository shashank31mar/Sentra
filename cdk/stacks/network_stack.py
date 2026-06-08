"""
Sentra MVP - Network Stack
Creates VPC, Route53 Private Hosted Zone, Security Groups, and VPC Endpoints

Reference: LLD 01 Section 2 (Network Stack)
ADRs: ADR-011 (VPC Design), ADR-015 (Security Groups), ADR-014 (VPC Endpoints)
"""

from aws_cdk import (
    Stack,
    Tags,
    RemovalPolicy,
    CfnOutput,
    aws_ec2 as ec2,
    aws_logs as logs,
    aws_route53 as route53,
    aws_servicediscovery as servicediscovery,
)
from constructs import Construct
from typing import Dict, Any


class NetworkStack(Stack):
    """
    Network Stack - VPC Infrastructure

    Creates:
    - VPC with public, private, and isolated subnets (ADR-019: public subnets for Public ALB + NAT)
    - 1 NAT Gateway (cost optimization for MVP)
    - VPC Flow Logs (7-day retention)
    - 5 Security Groups (Security Controller, Dashboard, Customer Query Agent, Payment Agent, ALB)
    - Route53 Private Hosted Zone (sentra.internal) for service discovery
    - 5 VPC Endpoints (3 Interface: ECR Docker, ECR API, CloudWatch Logs; 2 Gateway: S3, DynamoDB)

    Subnet Configuration:
    - Public: 10.0.1.0/24, 10.0.2.0/24 (for Public ALB + NAT Gateway)
    - Private: 10.0.11.0/24, 10.0.12.0/24 (for ECS services + Private ALB)
    - Isolated: 10.0.21.0/28, 10.0.22.0/28 (for VPC endpoints)

    Exports:
    - VPC ID, Public Subnet IDs, Private Subnet IDs, Isolated Subnet IDs
    - 5 Security Group IDs
    - Route53 Private Hosted Zone ID and Name
    - VPC Endpoint IDs
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        config: Dict[str, Any],
        **kwargs
    ) -> None:
        """
        Initialize Network Stack

        Args:
            scope: CDK app scope
            construct_id: Stack identifier
            config: Configuration dict from YAML (no hard-coded values)
            **kwargs: Additional stack properties
        """
        super().__init__(scope, construct_id, **kwargs)

        # Extract configuration
        vpc_config = config.get("vpc", {})
        naming_config = config.get("naming", {})
        tags_config = config.get("tags", {})

        # Create VPC with public, private, and isolated subnets (ADR-011, updated by ADR-019)
        # Note: Public subnets (/24) are used for Public ALB (requires /27 minimum) and NAT Gateway
        # All ECS services run in private subnets for security
        self.vpc = ec2.Vpc(
            self,
            "SentraMvpVpc",
            vpc_name=naming_config.get("vpc_name", "sentra-mvp-vpc"),
            ip_addresses=ec2.IpAddresses.cidr(vpc_config.get("cidr", "10.0.0.0/16")),
            max_azs=vpc_config.get("max_azs", 2),
            nat_gateways=vpc_config.get("nat_gateways", 1),  # Single NAT for MVP cost optimization

            # Subnet Configuration
            subnet_configuration=[
                # Public subnets for NAT Gateway and Public ALB (10.0.1.0/24, 10.0.2.0/24)
                # Updated from /28 to /24 to accommodate Public ALB (requires minimum /27 per AWS)
                # ADR-019: Split ALB architecture requires Public ALB in public subnets
                ec2.SubnetConfiguration(
                    subnet_type=ec2.SubnetType.PUBLIC,
                    name="Public",
                    cidr_mask=24,  # /24 to accommodate Public ALB + NAT Gateway
                ),
                # Private subnets for ECS services (10.0.11.0/24, 10.0.12.0/24)
                ec2.SubnetConfiguration(
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    name="Private",
                    cidr_mask=vpc_config.get("subnets", {}).get("private", [{}])[0].get("cidr_mask", 24),
                ),
                # Isolated subnets for VPC endpoints (10.0.21.0/28, 10.0.22.0/28)
                ec2.SubnetConfiguration(
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    name="Isolated",
                    cidr_mask=vpc_config.get("subnets", {}).get("isolated", [{}])[0].get("cidr_mask", 28),
                ),
            ],

            # Enable DNS for ECS Service Discovery (ADR-007)
            enable_dns_hostnames=vpc_config.get("enable_dns_hostnames", True),
            enable_dns_support=vpc_config.get("enable_dns_support", True),
        )

        # Add VPC Flow Logs (7-day retention for security audit)
        if vpc_config.get("flow_logs", {}).get("enabled", True):
            log_group = logs.LogGroup(
                self,
                "VpcFlowLogsGroup",
                log_group_name="/aws/vpc/sentra-mvp",
                retention=logs.RetentionDays.ONE_WEEK,  # 7 days
                removal_policy=RemovalPolicy.DESTROY,  # Clean up when stack is deleted
            )

            self.vpc.add_flow_log(
                "VpcFlowLog",
                destination=ec2.FlowLogDestination.to_cloud_watch_logs(log_group),
                traffic_type=ec2.FlowLogTrafficType.ALL,
            )

        # Apply tags to all resources (from config)
        for key, value in tags_config.items():
            Tags.of(self.vpc).add(key, value)

        # ============================================================
        # Security Groups (Task 2)
        # ============================================================
        # See LLD Section 2.3 and ADR-015 for security group design

        # 1. Security Controller SG - Port 8080
        self.security_controller_sg = ec2.SecurityGroup(
            self,
            "SecurityControllerSG",
            vpc=self.vpc,
            description="Security group for Security Controller (FastAPI validation API on port 8080)",
            allow_all_outbound=True,  # Needs to call AWS services (DynamoDB, S3, CloudWatch)
        )

        # 2. Dashboard SG - Port 8501
        self.dashboard_sg = ec2.SecurityGroup(
            self,
            "DashboardSG",
            vpc=self.vpc,
            description="Security group for Dashboard (Streamlit UI on port 8501)",
            allow_all_outbound=True,  # Needs to call Security Controller and AWS services
        )

        # 3. Customer Query Agent SG - Port 8080
        self.customer_query_agent_sg = ec2.SecurityGroup(
            self,
            "CustomerQueryAgentSG",
            vpc=self.vpc,
            description="Security group for Customer Query Agent (LangChain agent on port 8080)",
            allow_all_outbound=True,  # Needs to call Security Controller and AWS Bedrock
        )

        # 4. Payment Agent SG - Port 8080
        self.payment_agent_sg = ec2.SecurityGroup(
            self,
            "PaymentAgentSG",
            vpc=self.vpc,
            description="Security group for Payment Agent (LangChain agent on port 8080)",
            allow_all_outbound=True,  # Needs to call Security Controller and AWS Bedrock
        )

        # 4b. Console SG - Port 80 (nginx serving the SOC console SPA + /v1 proxy)
        self.console_sg = ec2.SecurityGroup(
            self,
            "ConsoleSG",
            vpc=self.vpc,
            description="Security group for SOC Console (nginx SPA and API proxy on port 80)",
            allow_all_outbound=True,  # Proxies /v1 to the public API Gateway and pulls image via NAT
        )

        # 5. Public ALB SG - Port 80 (Dashboard only)
        self.public_alb_sg = ec2.SecurityGroup(
            self,
            "PublicAlbSG",
            vpc=self.vpc,
            security_group_name="sentra-public-alb-sg",
            description="Security group for Public ALB (Dashboard only)",
            allow_all_outbound=False,  # Specific egress rules only
        )

        # 6. Private ALB SG - Port 80 (API services)
        self.private_alb_sg = ec2.SecurityGroup(
            self,
            "PrivateAlbSG",
            vpc=self.vpc,
            security_group_name="sentra-private-alb-sg",
            description="Security group for Private ALB (API services)",
            allow_all_outbound=False,  # Specific egress rules only
        )

        # 7. API NLB SG (Workstream 16 — fronts API Gateway VPC Link traffic)
        # NLB sits between API Gateway VPC Link ENIs and the Private ALB.
        # Inbound: TCP/80 from the VPC CIDR (VPC Link ENIs are in-VPC).
        # Egress: TCP/80 to private_alb_sg (NLB forwards to Private ALB).
        # See LLD 16 §7.1 and ADR-022.
        self.nlb_sg = ec2.SecurityGroup(
            self,
            "ApiNlbSG",
            vpc=self.vpc,
            security_group_name="sentra-api-nlb-sg",
            description="Security group for API Gateway VPC Link to NLB (Workstream 16)",
            allow_all_outbound=False,
        )

        # ============================================================
        # Security Group Ingress Rules
        # ============================================================

        # Security Controller: Allow TCP 8080 from dashboard, agents, and Private ALB
        self.security_controller_sg.add_ingress_rule(
            peer=self.dashboard_sg,
            connection=ec2.Port.tcp(8080),
            description="Allow Dashboard to call Security Controller validation API",
        )
        self.security_controller_sg.add_ingress_rule(
            peer=self.customer_query_agent_sg,
            connection=ec2.Port.tcp(8080),
            description="Allow Customer Query Agent to call Security Controller validation API",
        )
        self.security_controller_sg.add_ingress_rule(
            peer=self.payment_agent_sg,
            connection=ec2.Port.tcp(8080),
            description="Allow Payment Agent to call Security Controller validation API",
        )
        self.security_controller_sg.add_ingress_rule(
            peer=self.private_alb_sg,
            connection=ec2.Port.tcp(8080),
            description="Allow Private ALB to forward requests to Security Controller",
        )

        # Dashboard: Allow TCP 8501 from Public ALB
        self.dashboard_sg.add_ingress_rule(
            peer=self.public_alb_sg,
            connection=ec2.Port.tcp(8501),
            description="Allow Public ALB to forward requests to Dashboard UI",
        )

        # Console: Allow TCP 80 from Public ALB
        self.console_sg.add_ingress_rule(
            peer=self.public_alb_sg,
            connection=ec2.Port.tcp(80),
            description="Allow Public ALB to forward requests to SOC Console",
        )

        # Customer Query Agent: Allow TCP 8080 from Private ALB
        self.customer_query_agent_sg.add_ingress_rule(
            peer=self.private_alb_sg,
            connection=ec2.Port.tcp(8080),
            description="Allow Private ALB to forward requests to Customer Query Agent API",
        )

        # Payment Agent: Allow TCP 8080 from Private ALB
        self.payment_agent_sg.add_ingress_rule(
            peer=self.private_alb_sg,
            connection=ec2.Port.tcp(8080),
            description="Allow Private ALB to forward requests to Payment Agent API",
        )

        # ============================================================
        # Public ALB Rules
        # ============================================================

        # Public ALB: Allow HTTP from internet
        self.public_alb_sg.add_ingress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(80),
            description="Allow HTTP from internet",
        )

        # Public ALB: Allow HTTPS from internet
        self.public_alb_sg.add_ingress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(443),
            description="Allow HTTPS from internet",
        )

        # Public ALB: Egress to Dashboard
        self.public_alb_sg.add_egress_rule(
            peer=self.dashboard_sg,
            connection=ec2.Port.tcp(8501),
            description="Allow to Dashboard",
        )

        # Public ALB: Egress to SOC Console
        self.public_alb_sg.add_egress_rule(
            peer=self.console_sg,
            connection=ec2.Port.tcp(80),
            description="Allow to SOC Console",
        )

        # Public ALB: Egress to internet for Cognito authentication
        # Required for ALB to exchange OAuth code with Cognito token endpoint
        self.public_alb_sg.add_egress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(443),
            description="Allow HTTPS to Cognito for OAuth token exchange",
        )

        # ============================================================
        # Private ALB Rules
        # ============================================================

        # Private ALB: Allow from Dashboard
        self.private_alb_sg.add_ingress_rule(
            peer=self.dashboard_sg,
            connection=ec2.Port.tcp(80),
            description="Allow from Dashboard",
        )

        # Private ALB: Allow from API services (inter-service communication)
        self.private_alb_sg.add_ingress_rule(
            peer=self.security_controller_sg,
            connection=ec2.Port.tcp(80),
            description="Allow from Security Controller",
        )

        self.private_alb_sg.add_ingress_rule(
            peer=self.customer_query_agent_sg,
            connection=ec2.Port.tcp(80),
            description="Allow from Customer Query Agent",
        )

        self.private_alb_sg.add_ingress_rule(
            peer=self.payment_agent_sg,
            connection=ec2.Port.tcp(80),
            description="Allow from Payment Agent",
        )

        # Workstream 16: Private ALB accepts traffic from the new API NLB
        self.private_alb_sg.add_ingress_rule(
            peer=self.nlb_sg,
            connection=ec2.Port.tcp(80),
            description="Allow from API NLB (Workstream 16 - API Gateway VPC Link path)",
        )

        # Workstream 16: NLB inbound — TCP/80 from any source.
        #
        # IMPORTANT (deploy-time finding 2026-05-22): REST API Gateway VPC Link
        # traffic does NOT come from the customer VPC CIDR. AWS does not
        # publicly document the source IP range, and customer VPC Flow Logs
        # do not capture the API Gateway -> NLB hop (the NLB does NAT for
        # ALB-target type). A 10.0.0.0/16 ingress rule produces silent traffic
        # drops with API Gateway returning "Invalid endpoint address" / 500.
        #
        # 0.0.0.0/0 is acceptable here because the NLB is INTERNAL
        # (internet_facing=False) — externally-routed IPs cannot reach it.
        # Defense-in-depth is provided by:
        #   (1) NLB being internal-only
        #   (2) API Gateway API-key + Usage Plan auth at the public edge
        #   (3) Private ALB SG ingress restricted to nlb_sg (NLB's own SG)
        # See LLD 16 §7.1 "Deploy-time SG finding" for the full rationale.
        self.nlb_sg.add_ingress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(80),
            description="API Gateway VPC Link to NLB :80 (Workstream 16 - internal NLB, any-IPv4 safe)",
        )
        self.nlb_sg.add_egress_rule(
            peer=self.private_alb_sg,
            connection=ec2.Port.tcp(80),
            description="NLB to Private ALB :80 (Workstream 16)",
        )

        # Private ALB: Egress to all API services
        self.private_alb_sg.add_egress_rule(
            peer=self.security_controller_sg,
            connection=ec2.Port.tcp(8080),
            description="Allow to Security Controller",
        )

        self.private_alb_sg.add_egress_rule(
            peer=self.customer_query_agent_sg,
            connection=ec2.Port.tcp(8080),
            description="Allow to Customer Query Agent",
        )

        self.private_alb_sg.add_egress_rule(
            peer=self.payment_agent_sg,
            connection=ec2.Port.tcp(8080),
            description="Allow to Payment Agent",
        )

        # Dashboard needs to call Private ALB
        self.dashboard_sg.add_egress_rule(
            peer=self.private_alb_sg,
            connection=ec2.Port.tcp(80),
            description="Allow Dashboard to call Private ALB",
        )

        # Dashboard needs to call agents directly (for self-hosted agent integration)
        self.dashboard_sg.add_egress_rule(
            peer=self.customer_query_agent_sg,
            connection=ec2.Port.tcp(8080),
            description="Allow Dashboard to call Customer Query Agent directly",
        )
        self.dashboard_sg.add_egress_rule(
            peer=self.payment_agent_sg,
            connection=ec2.Port.tcp(8080),
            description="Allow Dashboard to call Payment Agent directly",
        )

        # Agents need to accept connections from Dashboard
        self.customer_query_agent_sg.add_ingress_rule(
            peer=self.dashboard_sg,
            connection=ec2.Port.tcp(8080),
            description="Allow Dashboard to call Customer Query Agent",
        )
        self.payment_agent_sg.add_ingress_rule(
            peer=self.dashboard_sg,
            connection=ec2.Port.tcp(8080),
            description="Allow Dashboard to call Payment Agent",
        )

        # Store references for other stacks (will be used by ComputeStack, ApiStack, etc.)
        self.private_subnets = self.vpc.private_subnets
        self.isolated_subnets = self.vpc.isolated_subnets

        # ============================================================
        # Service Discovery Namespace (creates Route53 Private Hosted Zone automatically)
        # ============================================================
        # See LLD Section 2.2 and ADR-007 for Route53 service discovery design
        # Service Discovery namespace automatically creates a Route53 private hosted zone
        # This allows ECS services to register themselves for DNS-based service discovery

        route53_config = config.get("route53", {})
        self.service_discovery_namespace = servicediscovery.PrivateDnsNamespace(
            self,
            "ServiceDiscoveryNamespace",
            name=route53_config.get("private_zone_name", "sentra.internal"),
            vpc=self.vpc,
            description="Service Discovery namespace for Sentra MVP - auto-registers ECS services"
        )
        
        # Expose the Route53 zone created by Service Discovery for reference
        self.private_zone = self.service_discovery_namespace

        # ============================================================
        # VPC Endpoints (Task 4)
        # ============================================================
        # See LLD Section 2.4 and ADR-014 for VPC endpoint strategy

        vpc_endpoints_config = config.get("vpc_endpoints", {})

        # Interface Endpoints (3) - Deployed in isolated subnets
        # Cost: $0.01/hour each = ~$7/month each = $21/month total
        # ROI: Saves ~$30/month in NAT bandwidth costs + reduces latency

        # 1. ECR Docker - For pulling container images
        self.ecr_docker_endpoint = ec2.InterfaceVpcEndpoint(
            self,
            "EcrDockerEndpoint",
            vpc=self.vpc,
            service=ec2.InterfaceVpcEndpointAwsService.ECR_DOCKER,
            subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
            private_dns_enabled=True,  # Enable private DNS for seamless ECR access
        )

        # 2. ECR API - For ECR API calls (GetAuthorizationToken, etc.)
        self.ecr_api_endpoint = ec2.InterfaceVpcEndpoint(
            self,
            "EcrApiEndpoint",
            vpc=self.vpc,
            service=ec2.InterfaceVpcEndpointAwsService.ECR,
            subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
            private_dns_enabled=True,
        )

        # 3. CloudWatch Logs - For streaming container logs
        self.logs_endpoint = ec2.InterfaceVpcEndpoint(
            self,
            "CloudWatchLogsEndpoint",
            vpc=self.vpc,
            service=ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS,
            subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
            private_dns_enabled=True,
        )

        # Gateway Endpoints (2) - FREE! No per-hour charge
        # Deployed in route tables for private subnets

        # 4. S3 - For accessing Sigma rules, policies, and artifacts
        self.s3_endpoint = ec2.GatewayVpcEndpoint(
            self,
            "S3Endpoint",
            vpc=self.vpc,
            service=ec2.GatewayVpcEndpointAwsService.S3,
            subnets=[ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS)],
        )

        # 5. DynamoDB - For session context and policy queries (high frequency)
        self.dynamodb_endpoint = ec2.GatewayVpcEndpoint(
            self,
            "DynamoDbEndpoint",
            vpc=self.vpc,
            service=ec2.GatewayVpcEndpointAwsService.DYNAMODB,
            subnets=[ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS)],
        )

        # ============================================================
        # CloudFormation Outputs
        # ============================================================

        # VPC Outputs
        CfnOutput(
            self,
            "VpcId",
            value=self.vpc.vpc_id,
            description="VPC ID for Sentra MVP",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-vpc-id",
        )

        # Security Group Outputs
        CfnOutput(
            self,
            "SecurityControllerSgId",
            value=self.security_controller_sg.security_group_id,
            description="Security group ID for Security Controller (port 8080)",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-security-controller-sg-id",
        )

        CfnOutput(
            self,
            "DashboardSgId",
            value=self.dashboard_sg.security_group_id,
            description="Security group ID for Dashboard (port 8501)",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-dashboard-sg-id",
        )

        CfnOutput(
            self,
            "CustomerQueryAgentSgId",
            value=self.customer_query_agent_sg.security_group_id,
            description="Security group ID for Customer Query Agent (port 8080)",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-customer-query-agent-sg-id",
        )

        CfnOutput(
            self,
            "PaymentAgentSgId",
            value=self.payment_agent_sg.security_group_id,
            description="Security group ID for Payment Agent (port 8080)",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-payment-agent-sg-id",
        )

        CfnOutput(
            self,
            "PublicAlbSgId",
            value=self.public_alb_sg.security_group_id,
            description="Security group ID for Public ALB (Dashboard only)",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-public-alb-sg-id",
        )

        CfnOutput(
            self,
            "PrivateAlbSgId",
            value=self.private_alb_sg.security_group_id,
            description="Security group ID for Private ALB (API services)",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-private-alb-sg-id",
        )

        # Route53 Outputs
        CfnOutput(
            self,
            "ServiceDiscoveryNamespaceId",
            value=self.service_discovery_namespace.namespace_id,
            description="Service Discovery Namespace ID (also Route53 Hosted Zone ID)",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-service-discovery-namespace-id",
        )

        CfnOutput(
            self,
            "ServiceDiscoveryNamespaceName",
            value=self.service_discovery_namespace.namespace_name,
            description="Service Discovery Namespace name (sentra.internal)",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-service-discovery-namespace-name",
        )

        # VPC Endpoint Outputs
        CfnOutput(
            self,
            "EcrDockerEndpointId",
            value=self.ecr_docker_endpoint.vpc_endpoint_id,
            description="VPC Endpoint ID for ECR Docker",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-ecr-docker-endpoint-id",
        )

        CfnOutput(
            self,
            "S3EndpointId",
            value=self.s3_endpoint.vpc_endpoint_id,
            description="VPC Gateway Endpoint ID for S3",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-s3-endpoint-id",
        )

        CfnOutput(
            self,
            "DynamoDbEndpointId",
            value=self.dynamodb_endpoint.vpc_endpoint_id,
            description="VPC Gateway Endpoint ID for DynamoDB",
            export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-dynamodb-endpoint-id",
        )

    @property
    def vpc_id(self) -> str:
        """Return VPC ID for cross-stack references"""
        return self.vpc.vpc_id
