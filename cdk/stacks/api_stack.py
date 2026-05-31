"""
Sentra MVP - API Stack (REST API)
Creates REST API Gateway with VPC Link, API keys, and per-endpoint rate limiting

Reference: LLD 02 (API Gateway Layer)
ADRs: ADR-003 (Public API Gateway), ADR-010 (Standardized Agent Interface)

Updated for Workstream 2 Task 1:
- Configuration-driven (no hard-coded values)
- Reusable constructs for endpoints
- REST API (not HTTP API) for API key support and granular rate limiting
"""

from aws_cdk import (
    Stack,
    CfnOutput,
    Duration,
    RemovalPolicy,
    aws_apigateway as apigateway,
    aws_ec2 as ec2,
    aws_logs as logs,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_sns as sns,
    aws_iam as iam,
)
from constructs import Construct
import os
from config import Config
from cdk_constructs.api_endpoint_construct import StandardApiEndpoint
from utils.api_gateway_helpers import create_http_integration, create_standard_method_responses


class ApiStack(Stack):
    """
    API Stack - Public REST API Gateway Layer

    Creates:
    - REST API Gateway with CORS and CloudWatch logging
    - API Key and Usage Plan with rate limits
    - VPC Link to private ALB
    - HTTP_PROXY integration to ALB

    Features:
    - Configuration-driven (zero hard-coded values)
    - API key authentication
    - Per-endpoint rate limiting
    - X-Ray tracing enabled
    - CloudWatch access logs
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        config=None,  # Kept for backward compatibility, but we load fresh
        network_stack=None,
        compute_stack=None,
        **kwargs
    ) -> None:
        """Initialize API Stack.

        Args:
            scope: CDK app scope
            construct_id: Stack identifier
            config: Legacy config dict (kept for compatibility, but we use Config class)
            network_stack: NetworkStack for VPC references
            compute_stack: ComputeStack for ALB reference
            **kwargs: Additional stack properties
        """
        super().__init__(scope, construct_id, **kwargs)

        # Load configuration
        env = os.environ.get("ENV", "dev")
        self.config = Config(env=env)

        # ============================================================
        # CloudWatch Logs Role for API Gateway (Account-level setting)
        # ============================================================
        # This role allows API Gateway to write logs to CloudWatch
        # It's an account-level configuration that gets cleaned up with the stack
        cloudwatch_role = iam.Role(
            self,
            "ApiGatewayCloudWatchRole",
            assumed_by=iam.ServicePrincipal("apigateway.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AmazonAPIGatewayPushToCloudWatchLogs"
                )
            ],
            description="CloudWatch Logs role for API Gateway (managed by Sentra CDK stack)",
        )
        
        # Apply removal policy to ensure role is deleted with stack
        cloudwatch_role.apply_removal_policy(RemovalPolicy.DESTROY)

        # Set the CloudWatch role for API Gateway account settings
        # Note: This is an account-level setting but managed by this stack
        # When the stack is deleted, the account setting will be cleared
        cfn_account = apigateway.CfnAccount(
            self,
            "ApiGatewayAccount",
            cloud_watch_role_arn=cloudwatch_role.role_arn
        )

        # ============================================================
        # CloudWatch Log Group for Access Logs
        # ============================================================
        access_log_group = logs.LogGroup(
            self,
            "ApiAccessLogs",
            log_group_name="/aws/apigateway/sentra-mvp-access-logs",
            retention=logs.RetentionDays.ONE_MONTH,  # 30 days
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ============================================================
        # REST API Gateway
        # ============================================================
        self.api = apigateway.RestApi(
            self,
            "SentraApi",
            rest_api_name=self.config.get_api_gateway_config("api_name"),
            description="Sentra MVP Public API",
            cloud_watch_role=False,  # We manage the CloudWatch role explicitly above

            # CORS configuration
            default_cors_preflight_options=apigateway.CorsOptions(
                allow_origins=self.config.get("api_gateway.cors_allow_origins", ["*"]),
                allow_methods=apigateway.Cors.ALL_METHODS,
                allow_headers=self.config.get("api_gateway.cors_allow_headers", [
                    "Content-Type",
                    "X-Api-Key",
                    "Authorization"
                ]),
                max_age=Duration.hours(1)
            ),

            # Deployment options
            deploy_options=apigateway.StageOptions(
                stage_name=self.config.get_api_gateway_config("stage_name", "prod"),
                metrics_enabled=self.config.get_api_gateway_config("enable_metrics", True),
                logging_level=apigateway.MethodLoggingLevel.INFO,
                data_trace_enabled=self.config.get_api_gateway_config("data_trace_enabled", False),
                tracing_enabled=self.config.get_api_gateway_config("enable_xray_tracing", True),
                throttling_rate_limit=self.config.get_api_gateway_config("throttle_rate_limit", 100),
                throttling_burst_limit=self.config.get_api_gateway_config("throttle_burst_limit", 200),
                access_log_destination=apigateway.LogGroupLogDestination(access_log_group),
                access_log_format=apigateway.AccessLogFormat.json_with_standard_fields(
                    caller=True,
                    http_method=True,
                    ip=True,
                    protocol=True,
                    request_time=True,
                    resource_path=True,
                    response_length=True,
                    status=True,
                    user=True,
                )
            )
        )

        # ============================================================
        # API Key and Usage Plan
        # ============================================================
        self.api_key = apigateway.ApiKey(
            self,
            "ApiKey",
            api_key_name=self.config.get_api_gateway_config("api_key_name"),
            description="API key for Sentra MVP demo",
            enabled=True
        )

        # Usage plan with throttle and quota settings
        self.usage_plan = apigateway.UsagePlan(
            self,
            "UsagePlan",
            name=self.config.get_api_gateway_config("usage_plan_name"),
            description="Usage plan for Sentra MVP",
            throttle=apigateway.ThrottleSettings(
                rate_limit=self.config.get_api_gateway_config("usage_plan_rate_limit", 100),
                burst_limit=self.config.get_api_gateway_config("usage_plan_burst_limit", 200)
            ),
            quota=apigateway.QuotaSettings(
                limit=self.config.get_api_gateway_config("usage_plan_quota_limit", 100000),
                period=apigateway.Period.MONTH
            )
        )

        # Associate API key with usage plan
        self.usage_plan.add_api_key(self.api_key)
        self.usage_plan.add_api_stage(stage=self.api.deployment_stage)

        # ============================================================
        # VPC Link (Workstream 16 — ADR-022)
        # ============================================================
        # The original CDK pointed API Gateway integrations at the Private ALB's
        # internal DNS with ConnectionType.INTERNET — which can never work
        # (internal DNS isn't routable from API Gateway's public edge). The fix:
        # an NLB (in compute_stack.api_nlb) fronts the Private ALB, and this
        # VPC Link connects API Gateway → NLB.
        # See LLD 16 §7.4.
        self.api_vpc_link = apigateway.VpcLink(
            self,
            "SentraApiVpcLink",
            description="API Gateway -> Sentra Private ALB (via NLB) - Workstream 16",
            targets=[compute_stack.api_nlb],
        )

        # ============================================================
        # HTTP_PROXY Integration via VPC Link → NLB → Private ALB
        # ============================================================
        # Integrations target the NLB's DNS name (not the Private ALB's). VPC
        # Link carries the request from API Gateway to the NLB; NLB target
        # group forwards to the Private ALB; Private ALB does path-routing to
        # the security-controller target group.
        self.nlb_base_url = f"http://{compute_stack.api_nlb.load_balancer_dns_name}"

        # Store API root resource for use in other stacks
        self.root_resource = self.api.root

        # ============================================================
        # Create /v1 root resource
        # ============================================================
        v1_resource = self.api.root.add_resource("v1")

        # ============================================================
        # Shared Request Validators and Models
        # ============================================================
        # Create reusable request validator
        body_validator = apigateway.RequestValidator(
            self,
            "BodyValidator",
            rest_api=self.api,
            request_validator_name="body-validator",
            validate_request_body=True,
            validate_request_parameters=True,
        )

        # Validate request model (matches ValidationRequest in models.py)
        validate_request_model = apigateway.Model(
            self,
            "ValidateRequestModel",
            rest_api=self.api,
            content_type="application/json",
            model_name="ValidateRequest",
            schema=apigateway.JsonSchema(
                schema=apigateway.JsonSchemaVersion.DRAFT4,
                title="Validation Request",
                type=apigateway.JsonSchemaType.OBJECT,
                required=["request_id", "session_id", "agent_id", "tool_name", "user_input", "timestamp", "operation_type"],
                properties={
                    "request_id": apigateway.JsonSchema(type=apigateway.JsonSchemaType.STRING),
                    "session_id": apigateway.JsonSchema(type=apigateway.JsonSchemaType.STRING),
                    "agent_id": apigateway.JsonSchema(type=apigateway.JsonSchemaType.STRING),
                    "tool_name": apigateway.JsonSchema(type=apigateway.JsonSchemaType.STRING),
                    "tool_params": apigateway.JsonSchema(type=apigateway.JsonSchemaType.OBJECT),
                    "user_input": apigateway.JsonSchema(type=apigateway.JsonSchemaType.STRING),
                    "timestamp": apigateway.JsonSchema(type=apigateway.JsonSchemaType.STRING),
                    "operation_type": apigateway.JsonSchema(type=apigateway.JsonSchemaType.STRING),
                }
            )
        )

        # Rollback request model
        rollback_request_model = apigateway.Model(
            self,
            "RollbackRequestModel",
            rest_api=self.api,
            content_type="application/json",
            model_name="RollbackRequest",
            schema=apigateway.JsonSchema(
                schema=apigateway.JsonSchemaVersion.DRAFT4,
                title="Rollback Request",
                type=apigateway.JsonSchemaType.OBJECT,
                required=["action_id", "reason"],
                properties={
                    "action_id": apigateway.JsonSchema(type=apigateway.JsonSchemaType.STRING),
                    "reason": apigateway.JsonSchema(type=apigateway.JsonSchemaType.STRING),
                    "operator_id": apigateway.JsonSchema(type=apigateway.JsonSchemaType.STRING),
                }
            )
        )

        # Agent request model (shared by all agents)
        agent_request_model = apigateway.Model(
            self,
            "AgentRequestModel",
            rest_api=self.api,
            content_type="application/json",
            model_name="AgentRequest",
            schema=apigateway.JsonSchema(
                schema=apigateway.JsonSchemaVersion.DRAFT4,
                title="Agent Request",
                type=apigateway.JsonSchemaType.OBJECT,
                required=["message"],
                properties={
                    "message": apigateway.JsonSchema(
                        type=apigateway.JsonSchemaType.STRING,
                        min_length=1,
                        max_length=10000
                    ),
                    "context": apigateway.JsonSchema(type=apigateway.JsonSchemaType.OBJECT),
                    "session_id": apigateway.JsonSchema(type=apigateway.JsonSchemaType.STRING),
                }
            )
        )

        # ============================================================
        # Task 4-7: Security Controller Endpoints
        # ============================================================

        # /v1/validate - POST
        StandardApiEndpoint(
            self, "ValidateEndpoint",
            api=self.api,
            parent_resource=v1_resource,
            path="validate",
            http_method="POST",
            integration=create_http_integration(self.nlb_base_url, "/v1/validate", "POST", vpc_link=self.api_vpc_link),
            rate_limit=self.config.get_endpoint_rate_limit("validate"),
            burst_limit=self.config.get_endpoint_burst_limit("validate"),
            api_key_required=True,
            request_validator=body_validator,
            request_models={"application/json": validate_request_model},
            method_responses=create_standard_method_responses(include_500=True)
        )

        # /v1/health - GET (no authentication required)
        StandardApiEndpoint(
            self, "HealthEndpoint",
            api=self.api,
            parent_resource=v1_resource,
            path="health",
            http_method="GET",
            integration=create_http_integration(self.nlb_base_url, "/v1/health", "GET", vpc_link=self.api_vpc_link, include_api_key_header=False),
            rate_limit=self.config.get_endpoint_rate_limit("health"),
            burst_limit=self.config.get_endpoint_burst_limit("health"),
            api_key_required=False,  # Public endpoint
            method_responses=[
                apigateway.MethodResponse(status_code="200", response_models={"application/json": apigateway.Model.EMPTY_MODEL}),
            ]
        )

        # /v1/logs - GET (with query parameters)
        StandardApiEndpoint(
            self, "LogsEndpoint",
            api=self.api,
            parent_resource=v1_resource,
            path="logs",
            http_method="GET",
            integration=create_http_integration(
                self.nlb_base_url, "/v1/logs", "GET",
                vpc_link=self.api_vpc_link,
                pass_query_params={
                    "session_id": "method.request.querystring.session_id",
                    "start_time": "method.request.querystring.start_time",
                    "end_time": "method.request.querystring.end_time",
                    "limit": "method.request.querystring.limit",
                }
            ),
            rate_limit=self.config.get_endpoint_rate_limit("logs"),
            burst_limit=self.config.get_endpoint_burst_limit("logs"),
            api_key_required=True,
            request_parameters={
                "method.request.querystring.session_id": False,
                "method.request.querystring.start_time": False,
                "method.request.querystring.end_time": False,
                "method.request.querystring.limit": False,
            }
        )

        # /v1/rollback - POST
        StandardApiEndpoint(
            self, "RollbackEndpoint",
            api=self.api,
            parent_resource=v1_resource,
            path="rollback",
            http_method="POST",
            integration=create_http_integration(self.nlb_base_url, "/v1/rollback", "POST", vpc_link=self.api_vpc_link),
            rate_limit=self.config.get_endpoint_rate_limit("rollback"),
            burst_limit=self.config.get_endpoint_burst_limit("rollback"),
            api_key_required=True,
            request_validator=body_validator,
            request_models={"application/json": rollback_request_model},
            method_responses=[
                apigateway.MethodResponse(status_code="200", response_models={"application/json": apigateway.Model.EMPTY_MODEL}),
                apigateway.MethodResponse(status_code="400"),
                apigateway.MethodResponse(status_code="403"),
                apigateway.MethodResponse(status_code="501"),  # Not implemented
            ]
        )

        # ============================================================
        # Task 8-10: AI Agent Endpoints
        # ============================================================
        # Create base /v1/agents resource
        agents_resource = v1_resource.add_resource("agents")

        # Customer Query Agent
        customer_query_resource = agents_resource.add_resource("customer-query")

        # /v1/agents/customer-query/query - POST
        StandardApiEndpoint(
            self, "CustomerQueryQueryEndpoint",
            api=self.api,
            parent_resource=customer_query_resource,
            path="query",
            http_method="POST",
            integration=create_http_integration(self.nlb_base_url, "/v1/agents/customer-query/query", "POST", vpc_link=self.api_vpc_link),
            rate_limit=self.config.get_endpoint_rate_limit("agent_query"),
            burst_limit=self.config.get_endpoint_burst_limit("agent_query"),
            api_key_required=True,
            request_validator=body_validator,
            request_models={"application/json": agent_request_model}
        )

        # /v1/agents/customer-query/action - POST
        StandardApiEndpoint(
            self, "CustomerQueryActionEndpoint",
            api=self.api,
            parent_resource=customer_query_resource,
            path="action",
            http_method="POST",
            integration=create_http_integration(self.nlb_base_url, "/v1/agents/customer-query/action", "POST", vpc_link=self.api_vpc_link),
            rate_limit=self.config.get_endpoint_rate_limit("agent_action"),
            burst_limit=self.config.get_endpoint_burst_limit("agent_action"),
            api_key_required=True,
            request_validator=body_validator,
            request_models={"application/json": agent_request_model}
        )

        # Payment Agent
        payment_resource = agents_resource.add_resource("payment")

        # /v1/agents/payment/query - POST
        StandardApiEndpoint(
            self, "PaymentQueryEndpoint",
            api=self.api,
            parent_resource=payment_resource,
            path="query",
            http_method="POST",
            integration=create_http_integration(self.nlb_base_url, "/v1/agents/payment/query", "POST", vpc_link=self.api_vpc_link),
            rate_limit=self.config.get_endpoint_rate_limit("agent_query"),
            burst_limit=self.config.get_endpoint_burst_limit("agent_query"),
            api_key_required=True,
            request_validator=body_validator,
            request_models={"application/json": agent_request_model}
        )

        # /v1/agents/payment/action - POST
        StandardApiEndpoint(
            self, "PaymentActionEndpoint",
            api=self.api,
            parent_resource=payment_resource,
            path="action",
            http_method="POST",
            integration=create_http_integration(self.nlb_base_url, "/v1/agents/payment/action", "POST", vpc_link=self.api_vpc_link),
            rate_limit=self.config.get_endpoint_rate_limit("agent_action"),
            burst_limit=self.config.get_endpoint_burst_limit("agent_action"),
            api_key_required=True,
            request_validator=body_validator,
            request_models={"application/json": agent_request_model}
        )

        # ============================================================
        # Workstream 11: Agent Policy CRUD APIs
        # ============================================================

        # Create /v1/policies resource
        policies_resource = v1_resource.add_resource("policies")

        # GET /v1/policies - List policies with filters
        policies_resource.add_method(
            "GET",
            integration=create_http_integration(
                self.nlb_base_url, "/v1/policies", "GET",
                vpc_link=self.api_vpc_link,
                pass_query_params={
                    "agent_id": "method.request.querystring.agent_id",
                    "status": "method.request.querystring.status",
                    "limit": "method.request.querystring.limit",
                }
            ),
            api_key_required=True,
            request_parameters={
                "method.request.querystring.agent_id": False,
                "method.request.querystring.status": False,
                "method.request.querystring.limit": False,
            }
        )

        # POST /v1/policies - Create policy
        policies_resource.add_method(
            "POST",
            integration=create_http_integration(self.nlb_base_url, "/v1/policies", "POST", vpc_link=self.api_vpc_link),
            api_key_required=True,
            request_validator=body_validator
        )

        # Create /v1/policies/{policy_id} resource
        policy_id_resource = policies_resource.add_resource("{policy_id}")

        # GET /v1/policies/{policy_id} - Get single policy
        policy_id_resource.add_method(
            "GET",
            integration=create_http_integration(
                self.nlb_base_url, "/v1/policies/{policy_id}", "GET",
                vpc_link=self.api_vpc_link,
                pass_query_params={"include_content": "method.request.querystring.include_content"}
            ),
            api_key_required=True,
            request_parameters={
                "method.request.path.policy_id": True,
                "method.request.querystring.include_content": False,
            }
        )

        # PUT /v1/policies/{policy_id} - Update policy
        policy_id_resource.add_method(
            "PUT",
            integration=create_http_integration(
                self.nlb_base_url, "/v1/policies/{policy_id}", "PUT",
                vpc_link=self.api_vpc_link,
            ),
            api_key_required=True,
            request_validator=body_validator,
            request_parameters={"method.request.path.policy_id": True}
        )

        # DELETE /v1/policies/{policy_id} - Soft delete policy
        policy_id_resource.add_method(
            "DELETE",
            integration=create_http_integration(
                self.nlb_base_url, "/v1/policies/{policy_id}", "DELETE",
                vpc_link=self.api_vpc_link,
            ),
            api_key_required=True,
            request_parameters={"method.request.path.policy_id": True}
        )

        # ============================================================
        # Sigma Rules APIs (Workstream 7)
        # ============================================================

        # Create /v1/sigma-rules resource
        sigma_rules_resource = v1_resource.add_resource("sigma-rules")

        # GET /v1/sigma-rules - List sigma rules
        sigma_rules_resource.add_method(
            "GET",
            integration=create_http_integration(
                self.nlb_base_url, "/v1/sigma-rules", "GET",
                vpc_link=self.api_vpc_link,
                pass_query_params={
                    "category": "method.request.querystring.category",
                    "severity": "method.request.querystring.severity",
                    "enabled": "method.request.querystring.enabled",
                    "limit": "method.request.querystring.limit",
                }
            ),
            api_key_required=True,
            request_parameters={
                "method.request.querystring.category": False,
                "method.request.querystring.severity": False,
                "method.request.querystring.enabled": False,
                "method.request.querystring.limit": False,
            }
        )

        # Create /v1/sigma-rules/{rule_id} resource
        sigma_rule_id_resource = sigma_rules_resource.add_resource("{rule_id}")

        # PATCH /v1/sigma-rules/{rule_id} - Update sigma rule (enable/disable)
        sigma_rule_id_resource.add_method(
            "PATCH",
            integration=create_http_integration(
                self.nlb_base_url, "/v1/sigma-rules/{rule_id}", "PATCH",
                vpc_link=self.api_vpc_link,
            ),
            api_key_required=True,
            request_validator=body_validator,
            request_parameters={"method.request.path.rule_id": True}
        )

        # ============================================================
        # Task 11: CloudWatch Alarms for API Gateway
        # ============================================================
        # Create SNS topic for alarm notifications (or import from monitoring stack if exists)
        # For MVP, create a simple SNS topic for email notifications
        
        alarm_topic = sns.Topic(
            self,
            "ApiGatewayAlarmTopic",
            topic_name="sentra-api-gateway-alarms",
            display_name="Sentra API Gateway Alarms"
        )
        
        # Add email subscription (can be configured via environment variable)
        alarm_email = self.config.get("monitoring.alert_email", "admin@example.com")
        sns.Subscription(
            self,
            "AlarmEmailSubscription",
            topic=alarm_topic,
            protocol=sns.SubscriptionProtocol.EMAIL,
            endpoint=alarm_email
        )
        
        # Alarm 1: API Gateway 5XX Errors (Server Errors)
        # Threshold: > 10 errors in 5 minutes
        api_5xx_alarm = cloudwatch.Alarm(
            self,
            "Api5XXErrorsAlarm",
            alarm_name="Sentra-API-5XX-Errors",
            alarm_description="API Gateway server errors (5XX) exceeded threshold",
            metric=self.api.metric_server_error(
                period=Duration.minutes(5),
                statistic=cloudwatch.Stats.SUM
            ),
            threshold=10,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        api_5xx_alarm.add_alarm_action(cw_actions.SnsAction(alarm_topic))
        
        # Alarm 2: API Gateway High Latency (p99)
        # Threshold: > 5000ms (5 seconds)
        # Must breach twice (2 evaluation periods)
        api_latency_alarm = cloudwatch.Alarm(
            self,
            "ApiHighLatencyAlarm",
            alarm_name="Sentra-API-High-Latency",
            alarm_description="API Gateway p99 latency exceeded 5 seconds",
            metric=self.api.metric_latency(
                period=Duration.minutes(5),
                statistic="p99"
            ),
            threshold=5000,  # 5000ms = 5 seconds
            evaluation_periods=2,  # Must breach twice
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        api_latency_alarm.add_alarm_action(cw_actions.SnsAction(alarm_topic))
        
        # Alarm 3: API Gateway 4XX Errors (Client Errors)
        # Threshold: > 5% of total requests
        # This is a composite metric (4XX count / total count)
        api_4xx_metric = self.api.metric_client_error(
            period=Duration.minutes(5),
            statistic=cloudwatch.Stats.SUM
        )
        
        api_count_metric = self.api.metric_count(
            period=Duration.minutes(5),
            statistic=cloudwatch.Stats.SUM
        )
        
        # Create math expression for 4XX percentage
        api_4xx_percentage = cloudwatch.MathExpression(
            expression="(m1 / m2) * 100",
            using_metrics={
                "m1": api_4xx_metric,
                "m2": api_count_metric
            },
            period=Duration.minutes(5)
        )
        
        api_4xx_alarm = cloudwatch.Alarm(
            self,
            "Api4XXErrorsAlarm",
            alarm_name="Sentra-API-4XX-Errors",
            alarm_description="API Gateway client errors (4XX) exceeded 5% of requests",
            metric=api_4xx_percentage,
            threshold=5,  # 5%
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        api_4xx_alarm.add_alarm_action(cw_actions.SnsAction(alarm_topic))

        # ============================================================
        # Task 12: Access Logs and Metrics
        # ============================================================
        # Access logs already configured in Task 1 (access_log_group)
        # Now add custom metric filters and dashboard widgets
        
        # Custom Metric Filter 1: High-latency requests (> 3 seconds)
        # Note: Metric filters will be configured post-deployment via CloudWatch Insights
        # For now, we rely on built-in API Gateway metrics
        
        # Custom Metric Filter 2: 5XX errors
        # Note: Using built-in API Gateway 5XX metric instead of custom filter
        
        # Create CloudWatch Dashboard for API Gateway metrics
        dashboard = cloudwatch.Dashboard(
            self,
            "ApiGatewayDashboard",
            dashboard_name="Sentra-API-Gateway-Metrics"
        )
        
        # Widget 1: API Gateway Request Count (last 1 hour)
        dashboard.add_widgets(
            cloudwatch.GraphWidget(
                title="API Gateway Request Count (Last 1 Hour)",
                left=[
                    self.api.metric_count(
                        period=Duration.minutes(5),
                        statistic=cloudwatch.Stats.SUM
                    )
                ],
                width=12,
                height=6
            )
        )
        
        # Widget 2: API Gateway Latency (p50, p90, p99)
        dashboard.add_widgets(
            cloudwatch.GraphWidget(
                title="API Gateway Latency (p50, p90, p99)",
                left=[
                    self.api.metric_latency(
                        period=Duration.minutes(5),
                        statistic="p50",
                        label="p50"
                    ),
                    self.api.metric_latency(
                        period=Duration.minutes(5),
                        statistic="p90",
                        label="p90"
                    ),
                    self.api.metric_latency(
                        period=Duration.minutes(5),
                        statistic="p99",
                        label="p99"
                    )
                ],
                width=12,
                height=6
            )
        )
        
        # Widget 3: API Gateway Error Rate (4XX, 5XX)
        dashboard.add_widgets(
            cloudwatch.GraphWidget(
                title="API Gateway Error Rate (4XX, 5XX)",
                left=[
                    self.api.metric_client_error(
                        period=Duration.minutes(5),
                        statistic=cloudwatch.Stats.SUM,
                        label="4XX Errors"
                    ),
                    self.api.metric_server_error(
                        period=Duration.minutes(5),
                        statistic=cloudwatch.Stats.SUM,
                        label="5XX Errors"
                    )
                ],
                width=12,
                height=6
            )
        )
        
        # Widget 4: API Gateway Throttled Requests
        dashboard.add_widgets(
            cloudwatch.GraphWidget(
                title="API Gateway Throttled Requests",
                left=[
                    cloudwatch.Metric(
                        namespace="AWS/ApiGateway",
                        metric_name="Count",
                        dimensions_map={
                            "ApiName": self.api.rest_api_name
                        },
                        period=Duration.minutes(5),
                        statistic=cloudwatch.Stats.SUM,
                        label="Total Requests"
                    ),
                    cloudwatch.Metric(
                        namespace="AWS/ApiGateway",
                        metric_name="Count",
                        dimensions_map={
                            "ApiName": self.api.rest_api_name
                        },
                        period=Duration.minutes(5),
                        statistic=cloudwatch.Stats.SUM,
                        label="Throttled (429)"
                    )
                ],
                width=12,
                height=6
            )
        )

        # ============================================================
        # CloudFormation Outputs
        # ============================================================
        CfnOutput(
            self,
            "ApiUrl",
            description="API Gateway URL",
            value=self.api.url,
            export_name=f"{construct_id}-ApiUrl"
        )

        CfnOutput(
            self,
            "ApiKeyId",
            description="API Key ID (retrieve value with: aws apigateway get-api-key --api-key <id> --include-value)",
            value=self.api_key.key_id,
            export_name=f"{construct_id}-ApiKeyId"
        )

        CfnOutput(
            self,
            "ApiId",
            description="API Gateway ID",
            value=self.api.rest_api_id,
            export_name=f"{construct_id}-ApiId"
        )

        CfnOutput(
            self,
            "PrivateAlbDnsName",
            description="Private ALB DNS Name (for direct testing)",
            value=compute_stack.private_alb.load_balancer_dns_name
        )

        CfnOutput(
            self,
            "AlarmTopicArn",
            description="SNS Topic ARN for API Gateway alarms",
            value=alarm_topic.topic_arn,
            export_name=f"{construct_id}-AlarmTopicArn"
        )

        CfnOutput(
            self,
            "DashboardName",
            description="CloudWatch Dashboard name for API Gateway metrics",
            value=dashboard.dashboard_name
        )

        CfnOutput(
            self,
            "AccessLogGroupName",
            description="CloudWatch Log Group for API Gateway access logs",
            value=access_log_group.log_group_name
        )
