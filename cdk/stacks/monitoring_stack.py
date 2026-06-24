"""
Sentra MVP - Monitoring Stack
Creates CloudWatch Dashboard, Alarms, and SNS notifications

Reference: LLD 01 Section 6 (Monitoring Stack)
ADRs: ADR-017 (Monitoring strategy)
"""

from aws_cdk import (
    Stack,
    CfnOutput,
    Duration,
    aws_cloudwatch as cloudwatch,
    aws_sns as sns,
    aws_sns_subscriptions as sns_subs,
    aws_cloudwatch_actions as cw_actions,
)
from constructs import Construct
from typing import Dict, Any, List


class MonitoringStack(Stack):
    """
    Monitoring Stack - Observability and Alerting Layer

    Creates (Task 14):
    - CloudWatch Dashboard with 12 widgets
    - SNS Topic for email notifications
    - 6 CloudWatch Alarms with SNS actions

    Features:
    - Real-time monitoring of system health
    - Automated alerts for critical issues
    - Comprehensive visibility into API, ECS, and DynamoDB metrics

    Exports:
    - Dashboard URL
    - SNS Topic ARN
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        config: Dict[str, Any],
        network_stack=None,
        storage_stack=None,
        compute_stack=None,
        api_stack=None,
        **kwargs
    ) -> None:
        """
        Initialize Monitoring Stack

        Args:
            scope: CDK app scope
            construct_id: Stack identifier
            config: Configuration dict from YAML
            network_stack: NetworkStack instance (optional)
            storage_stack: StorageStack instance for DynamoDB references
            compute_stack: ComputeStack instance for ECS/ALB references
            api_stack: ApiStack instance for API Gateway references
            **kwargs: Additional stack properties
        """
        super().__init__(scope, construct_id, **kwargs)

        # Extract configuration
        monitoring_config = config.get("monitoring", {})
        naming_config = config.get("naming", {})
        prefix = naming_config.get("prefix", "sentra-mvp")

        # ============================================================
        # SNS Topic for Alerts (Task 14)
        # ============================================================
        # Create SNS topic for email notifications
        # See LLD Section 6.3 for SNS configuration

        self.alerts_topic = sns.Topic(
            self,
            "AlertsTopic",
            topic_name=monitoring_config.get("sns_topic_name", f"{prefix}-alerts"),
            display_name="Sentra MVP - Alert Notifications",
        )

        # Subscribe email to SNS topic
        alert_email = monitoring_config.get("alert_email")
        if alert_email:
            self.alerts_topic.add_subscription(
                sns_subs.EmailSubscription(alert_email)
            )

        # ============================================================
        # CloudWatch Dashboard (Task 14)
        # ============================================================
        # Create comprehensive dashboard with 12 widgets
        # See LLD Section 6.1 for dashboard configuration

        self.dashboard = cloudwatch.Dashboard(
            self,
            "SentraDashboard",
            dashboard_name=monitoring_config.get("dashboard_name", f"{prefix}-dashboard"),
        )

        # Row 1: System Metrics (ECS and ALB)
        if compute_stack:
            # ECS CPU Utilization (all 4 services)
            ecs_cpu_widget = cloudwatch.GraphWidget(
                title="ECS CPU Utilization",
                left=[
                    cloudwatch.Metric(
                        namespace="AWS/ECS",
                        metric_name="CPUUtilization",
                        dimensions_map={
                            "ServiceName": "security-controller-service",
                            "ClusterName": compute_stack.ecs_cluster.cluster_name,
                        },
                        statistic="Average",
                        label="Security Controller",
                    ),
                    cloudwatch.Metric(
                        namespace="AWS/ECS",
                        metric_name="CPUUtilization",
                        dimensions_map={
                            "ServiceName": "dashboard-service",
                            "ClusterName": compute_stack.ecs_cluster.cluster_name,
                        },
                        statistic="Average",
                        label="Dashboard",
                    ),
                    cloudwatch.Metric(
                        namespace="AWS/ECS",
                        metric_name="CPUUtilization",
                        dimensions_map={
                            "ServiceName": "customer-query-agent-service",
                            "ClusterName": compute_stack.ecs_cluster.cluster_name,
                        },
                        statistic="Average",
                        label="Customer Query Agent",
                    ),
                    cloudwatch.Metric(
                        namespace="AWS/ECS",
                        metric_name="CPUUtilization",
                        dimensions_map={
                            "ServiceName": "payment-agent-service",
                            "ClusterName": compute_stack.ecs_cluster.cluster_name,
                        },
                        statistic="Average",
                        label="Payment Agent",
                    ),
                ],
                width=12,
                height=6,
            )

            # ECS Memory Utilization (all 4 services)
            ecs_memory_widget = cloudwatch.GraphWidget(
                title="ECS Memory Utilization",
                left=[
                    cloudwatch.Metric(
                        namespace="AWS/ECS",
                        metric_name="MemoryUtilization",
                        dimensions_map={
                            "ServiceName": "security-controller-service",
                            "ClusterName": compute_stack.ecs_cluster.cluster_name,
                        },
                        statistic="Average",
                        label="Security Controller",
                    ),
                    cloudwatch.Metric(
                        namespace="AWS/ECS",
                        metric_name="MemoryUtilization",
                        dimensions_map={
                            "ServiceName": "dashboard-service",
                            "ClusterName": compute_stack.ecs_cluster.cluster_name,
                        },
                        statistic="Average",
                        label="Dashboard",
                    ),
                    cloudwatch.Metric(
                        namespace="AWS/ECS",
                        metric_name="MemoryUtilization",
                        dimensions_map={
                            "ServiceName": "customer-query-agent-service",
                            "ClusterName": compute_stack.ecs_cluster.cluster_name,
                        },
                        statistic="Average",
                        label="Customer Query Agent",
                    ),
                    cloudwatch.Metric(
                        namespace="AWS/ECS",
                        metric_name="MemoryUtilization",
                        dimensions_map={
                            "ServiceName": "payment-agent-service",
                            "ClusterName": compute_stack.ecs_cluster.cluster_name,
                        },
                        statistic="Average",
                        label="Payment Agent",
                    ),
                ],
                width=12,
                height=6,
            )

            # ALB Request Count
            alb_requests_widget = cloudwatch.GraphWidget(
                title="ALB Request Count",
                left=[
                    cloudwatch.Metric(
                        namespace="AWS/ApplicationELB",
                        metric_name="RequestCount",
                        dimensions_map={
                            "LoadBalancer": compute_stack.private_alb.load_balancer_full_name,
                        },
                        statistic="Sum",
                        period=Duration.minutes(1),
                    ),
                ],
                width=8,
                height=6,
            )

            self.dashboard.add_widgets(ecs_cpu_widget, ecs_memory_widget, alb_requests_widget)

        # Row 2: API Gateway Metrics
        if api_stack:
            # API Gateway 4XX Errors
            api_4xx_widget = cloudwatch.GraphWidget(
                title="API Gateway 4XX Errors",
                left=[
                    cloudwatch.Metric(
                        namespace="AWS/ApiGateway",
                        metric_name="4XXError",
                        dimensions_map={
                            "ApiId": api_stack.api.rest_api_id,
                        },
                        statistic="Sum",
                        period=Duration.minutes(5),
                    ),
                ],
                width=8,
                height=6,
            )

            # API Gateway 5XX Errors
            api_5xx_widget = cloudwatch.GraphWidget(
                title="API Gateway 5XX Errors",
                left=[
                    cloudwatch.Metric(
                        namespace="AWS/ApiGateway",
                        metric_name="5XXError",
                        dimensions_map={
                            "ApiId": api_stack.api.rest_api_id,
                        },
                        statistic="Sum",
                        period=Duration.minutes(5),
                        color=cloudwatch.Color.RED,
                    ),
                ],
                width=8,
                height=6,
            )

            # API Gateway Latency (p50, p99)
            api_latency_widget = cloudwatch.GraphWidget(
                title="API Gateway Latency",
                left=[
                    cloudwatch.Metric(
                        namespace="AWS/ApiGateway",
                        metric_name="Latency",
                        dimensions_map={
                            "ApiId": api_stack.api.rest_api_id,
                        },
                        statistic="p50",
                        label="p50",
                        period=Duration.minutes(5),
                    ),
                    cloudwatch.Metric(
                        namespace="AWS/ApiGateway",
                        metric_name="Latency",
                        dimensions_map={
                            "ApiId": api_stack.api.rest_api_id,
                        },
                        statistic="p99",
                        label="p99",
                        period=Duration.minutes(5),
                        color=cloudwatch.Color.ORANGE,
                    ),
                ],
                width=8,
                height=6,
            )

            self.dashboard.add_widgets(api_4xx_widget, api_5xx_widget, api_latency_widget)

        # Row 3: Security Controller Metrics (Task 14)
        # Note: These metrics won't have data until Security Controller is running
        
        # Widget 1: Validation Latency (p50, p95, p99)
        sc_validation_latency_widget = cloudwatch.GraphWidget(
            title="Security Controller - Validation Latency (p50/p95/p99)",
            left=[
                cloudwatch.Metric(
                    namespace="Sentra/SecurityController",
                    metric_name="ValidationLatency",
                    statistic="p50",
                    label="p50",
                    period=Duration.minutes(1),
                    color=cloudwatch.Color.GREEN,
                ),
                cloudwatch.Metric(
                    namespace="Sentra/SecurityController",
                    metric_name="ValidationLatency",
                    statistic="p95",
                    label="p95",
                    period=Duration.minutes(1),
                    color=cloudwatch.Color.ORANGE,
                ),
                cloudwatch.Metric(
                    namespace="Sentra/SecurityController",
                    metric_name="ValidationLatency",
                    statistic="p99",
                    label="p99",
                    period=Duration.minutes(1),
                    color=cloudwatch.Color.RED,
                ),
            ],
            width=12,
            height=6,
        )

        # Widget 2: Request Volume (ALLOW + DENY)
        sc_request_volume_widget = cloudwatch.GraphWidget(
            title="Security Controller - Request Volume (ALLOW vs DENY)",
            left=[
                cloudwatch.Metric(
                    namespace="Sentra/SecurityController",
                    metric_name="ValidationsTotal",
                    dimensions_map={"Decision": "ALLOW"},
                    statistic="Sum",
                    label="ALLOW",
                    period=Duration.minutes(1),
                    color=cloudwatch.Color.GREEN,
                ),
                cloudwatch.Metric(
                    namespace="Sentra/SecurityController",
                    metric_name="ValidationsTotal",
                    dimensions_map={"Decision": "DENY"},
                    statistic="Sum",
                    label="DENY",
                    period=Duration.minutes(1),
                    color=cloudwatch.Color.RED,
                ),
            ],
            width=12,
            height=6,
        )

        # Widget 3: Deny Rate
        sc_deny_rate_widget = cloudwatch.GraphWidget(
            title="Security Controller - Deny Rate",
            left=[
                cloudwatch.Metric(
                    namespace="Sentra/SecurityController",
                    metric_name="DenyRate",
                    statistic="Average",
                    period=Duration.minutes(5),
                    color=cloudwatch.Color.RED,
                ),
            ],
            width=8,
            height=6,
        )

        # Widget 4: Trust Score Distribution
        sc_trust_score_widget = cloudwatch.SingleValueWidget(
            title="Security Controller - Average Trust Score",
            metrics=[
                cloudwatch.Metric(
                    namespace="Sentra/SecurityController",
                    metric_name="TrustScoreAverage",
                    statistic="Average",
                    period=Duration.minutes(5),
                ),
            ],
            width=8,
            height=6,
        )

        # Widget 5: Session Status (Quarantined)
        sc_quarantined_widget = cloudwatch.SingleValueWidget(
            title="Security Controller - Quarantined Sessions",
            metrics=[
                cloudwatch.Metric(
                    namespace="Sentra/SecurityController",
                    metric_name="QuarantinedSessions",
                    statistic="Maximum",
                    period=Duration.minutes(1),
                ),
            ],
            width=4,
            height=6,
        )

        # Widget 6: Session Status (Suspended)
        sc_suspended_widget = cloudwatch.SingleValueWidget(
            title="Security Controller - Suspended Sessions",
            metrics=[
                cloudwatch.Metric(
                    namespace="Sentra/SecurityController",
                    metric_name="SuspendedSessions",
                    statistic="Maximum",
                    period=Duration.minutes(1),
                ),
            ],
            width=4,
            height=6,
        )

        self.dashboard.add_widgets(
            sc_validation_latency_widget,
            sc_request_volume_widget,
        )
        self.dashboard.add_widgets(
            sc_deny_rate_widget,
            sc_trust_score_widget,
            sc_quarantined_widget,
            sc_suspended_widget,
        )

        # Row 4: DynamoDB Metrics
        if storage_stack:
            # DynamoDB Read Capacity (session-context table)
            dynamodb_read_widget = cloudwatch.GraphWidget(
                title="DynamoDB Read Capacity (session-context)",
                left=[
                    cloudwatch.Metric(
                        namespace="AWS/DynamoDB",
                        metric_name="ConsumedReadCapacityUnits",
                        dimensions_map={
                            "TableName": storage_stack.session_context_table.table_name,
                        },
                        statistic="Sum",
                    ),
                ],
                width=8,
                height=6,
            )

            # DynamoDB Write Capacity (session-context table)
            dynamodb_write_widget = cloudwatch.GraphWidget(
                title="DynamoDB Write Capacity (session-context)",
                left=[
                    cloudwatch.Metric(
                        namespace="AWS/DynamoDB",
                        metric_name="ConsumedWriteCapacityUnits",
                        dimensions_map={
                            "TableName": storage_stack.session_context_table.table_name,
                        },
                        statistic="Sum",
                    ),
                ],
                width=8,
                height=6,
            )

            # DynamoDB Throttled Requests
            dynamodb_throttle_widget = cloudwatch.GraphWidget(
                title="DynamoDB Throttled Requests",
                left=[
                    cloudwatch.Metric(
                        namespace="AWS/DynamoDB",
                        metric_name="UserErrors",
                        dimensions_map={
                            "TableName": storage_stack.session_context_table.table_name,
                        },
                        statistic="Sum",
                        color=cloudwatch.Color.RED,
                    ),
                ],
                width=8,
                height=6,
            )

            self.dashboard.add_widgets(
                dynamodb_read_widget,
                dynamodb_write_widget,
                dynamodb_throttle_widget,
            )

        # ============================================================
        # CloudWatch Alarms (Task 14)
        # ============================================================
        # Create 6 alarms with SNS notifications
        # See LLD Section 6.2 for alarm configuration

        self.alarms: List[cloudwatch.Alarm] = []

        # Alarm 1: API Gateway 5XX Errors
        if api_stack:
            api_5xx_alarm = cloudwatch.Alarm(
                self,
                "API5XXErrorsAlarm",
                alarm_name=f"{prefix}-api-5xx-errors",
                alarm_description="Alert when API Gateway 5XX errors exceed threshold",
                metric=cloudwatch.Metric(
                    namespace="AWS/ApiGateway",
                    metric_name="5XXError",
                    dimensions_map={
                        "ApiId": api_stack.api.rest_api_id,
                    },
                    statistic="Sum",
                    period=Duration.minutes(5),
                ),
                threshold=10,
                evaluation_periods=1,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            )
            api_5xx_alarm.add_alarm_action(cw_actions.SnsAction(self.alerts_topic))
            self.alarms.append(api_5xx_alarm)

            # Alarm 2: API Gateway High Latency
            api_latency_alarm = cloudwatch.Alarm(
                self,
                "APIHighLatencyAlarm",
                alarm_name=f"{prefix}-api-high-latency",
                alarm_description="Alert when API Gateway p99 latency exceeds 5 seconds",
                metric=cloudwatch.Metric(
                    namespace="AWS/ApiGateway",
                    metric_name="Latency",
                    dimensions_map={
                        "ApiId": api_stack.api.rest_api_id,
                    },
                    statistic="p99",
                    period=Duration.minutes(5),
                ),
                threshold=5000,  # 5 seconds in milliseconds
                evaluation_periods=1,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            )
            api_latency_alarm.add_alarm_action(cw_actions.SnsAction(self.alerts_topic))
            self.alarms.append(api_latency_alarm)

        # Alarm 3: ECS CPU High
        if compute_stack:
            ecs_cpu_alarm = cloudwatch.Alarm(
                self,
                "ECSCPUHighAlarm",
                alarm_name=f"{prefix}-ecs-cpu-high",
                alarm_description="Alert when ECS CPU utilization exceeds 80%",
                metric=cloudwatch.Metric(
                    namespace="AWS/ECS",
                    metric_name="CPUUtilization",
                    dimensions_map={
                        "ClusterName": compute_stack.ecs_cluster.cluster_name,
                    },
                    statistic="Average",
                    period=Duration.minutes(5),
                ),
                threshold=80,
                evaluation_periods=2,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            )
            ecs_cpu_alarm.add_alarm_action(cw_actions.SnsAction(self.alerts_topic))
            self.alarms.append(ecs_cpu_alarm)

            # Alarm 4: ECS Memory High
            ecs_memory_alarm = cloudwatch.Alarm(
                self,
                "ECSMemoryHighAlarm",
                alarm_name=f"{prefix}-ecs-memory-high",
                alarm_description="Alert when ECS Memory utilization exceeds 80%",
                metric=cloudwatch.Metric(
                    namespace="AWS/ECS",
                    metric_name="MemoryUtilization",
                    dimensions_map={
                        "ClusterName": compute_stack.ecs_cluster.cluster_name,
                    },
                    statistic="Average",
                    period=Duration.minutes(5),
                ),
                threshold=80,
                evaluation_periods=2,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            )
            ecs_memory_alarm.add_alarm_action(cw_actions.SnsAction(self.alerts_topic))
            self.alarms.append(ecs_memory_alarm)

        # Alarm 5: DynamoDB Throttled Requests
        if storage_stack:
            dynamodb_throttle_alarm = cloudwatch.Alarm(
                self,
                "DynamoDBThrottledAlarm",
                alarm_name=f"{prefix}-dynamodb-throttled",
                alarm_description="Alert when DynamoDB throttled requests exceed threshold",
                metric=cloudwatch.Metric(
                    namespace="AWS/DynamoDB",
                    metric_name="UserErrors",
                    dimensions_map={
                        "TableName": storage_stack.session_context_table.table_name,
                    },
                    statistic="Sum",
                    period=Duration.minutes(1),
                ),
                threshold=5,
                evaluation_periods=1,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            )
            dynamodb_throttle_alarm.add_alarm_action(cw_actions.SnsAction(self.alerts_topic))
            self.alarms.append(dynamodb_throttle_alarm)

        # Alarm 6: High Severity Threats
        high_severity_alarm = cloudwatch.Alarm(
            self,
            "HighSeverityThreatsAlarm",
            alarm_name=f"{prefix}-high-severity-threats",
            alarm_description="Alert when high-severity threats exceed threshold",
            metric=cloudwatch.Metric(
                namespace="Sentra/Security",
                metric_name="ThreatDetected",
                dimensions_map={"Severity": "HIGH"},
                statistic="Sum",
                period=Duration.minutes(5),
            ),
            threshold=10,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        high_severity_alarm.add_alarm_action(cw_actions.SnsAction(self.alerts_topic))
        self.alarms.append(high_severity_alarm)

        # ============================================================
        # Security Controller Specific Alarms (Task 14)
        # ============================================================
        # Create 5 Security Controller-specific alarms
        # Reference: LLD 03 Section 9.2, Task 14

        # Create SNS topics for different severity levels
        self.critical_alerts_topic = sns.Topic(
            self,
            "CriticalAlertsTopic",
            topic_name=f"{prefix}-critical-alerts",
            display_name="Sentra MVP - Critical Alerts (P0)",
        )
        if alert_email:
            self.critical_alerts_topic.add_subscription(
                sns_subs.EmailSubscription(alert_email)
            )

        self.info_alerts_topic = sns.Topic(
            self,
            "InfoAlertsTopic",
            topic_name=f"{prefix}-info-alerts",
            display_name="Sentra MVP - Info Alerts (P2)",
        )
        if alert_email:
            self.info_alerts_topic.add_subscription(
                sns_subs.EmailSubscription(alert_email)
            )

        # Alarm 1: Security Controller - Health Check Failure (P0 - Critical)
        sc_health_check_alarm = cloudwatch.Alarm(
            self,
            "SecurityControllerHealthCheckFailure",
            alarm_name=f"{prefix}-sc-health-check-failure",
            alarm_description="Security Controller: Health check failing (P0 - Demo Breaking)",
            metric=cloudwatch.Metric(
                namespace="Sentra/SecurityController",
                metric_name="HealthCheckStatus",
                statistic="Average",
                period=Duration.minutes(1),
            ),
            threshold=1,  # 0 = healthy, 1 = unhealthy
            evaluation_periods=2,
            datapoints_to_alarm=2,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.BREACHING,
        )
        sc_health_check_alarm.add_alarm_action(cw_actions.SnsAction(self.critical_alerts_topic))
        self.alarms.append(sc_health_check_alarm)

        # Alarm 2: Security Controller - DynamoDB Errors (P0 - Critical)
        sc_dynamodb_errors_alarm = cloudwatch.Alarm(
            self,
            "SecurityControllerDynamoDBErrors",
            alarm_name=f"{prefix}-sc-dynamodb-errors",
            alarm_description="Security Controller: High rate of DynamoDB errors (P0 - Demo Breaking)",
            metric=cloudwatch.Metric(
                namespace="Sentra/SecurityController",
                metric_name="ValidationErrors",
                dimensions_map={"ErrorType": "DYNAMODB_ERROR"},
                statistic="Sum",
                period=Duration.minutes(1),
            ),
            threshold=5,  # > 5 errors per minute
            evaluation_periods=2,
            datapoints_to_alarm=2,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        sc_dynamodb_errors_alarm.add_alarm_action(cw_actions.SnsAction(self.critical_alerts_topic))
        self.alarms.append(sc_dynamodb_errors_alarm)

        # Alarm 3: Security Controller - High Validation Latency (P1 - Important)
        sc_high_latency_alarm = cloudwatch.Alarm(
            self,
            "SecurityControllerHighLatency",
            alarm_name=f"{prefix}-sc-high-latency",
            alarm_description="Security Controller: Validation latency p95 exceeds 100ms (P1 - Demo Degrading)",
            metric=cloudwatch.Metric(
                namespace="Sentra/SecurityController",
                metric_name="ValidationLatency",
                statistic="p95",
                period=Duration.minutes(1),
            ),
            threshold=100,  # 100ms
            evaluation_periods=3,
            datapoints_to_alarm=2,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        sc_high_latency_alarm.add_alarm_action(cw_actions.SnsAction(self.alerts_topic))
        self.alarms.append(sc_high_latency_alarm)

        # Alarm 4: Security Controller - High Deny Rate (P1 - Important)
        sc_high_deny_rate_alarm = cloudwatch.Alarm(
            self,
            "SecurityControllerHighDenyRate",
            alarm_name=f"{prefix}-sc-high-deny-rate",
            alarm_description="Security Controller: Deny rate exceeds 50% - possible misconfiguration (P1)",
            metric=cloudwatch.Metric(
                namespace="Sentra/SecurityController",
                metric_name="DenyRate",
                statistic="Average",
                period=Duration.minutes(5),
            ),
            threshold=0.50,  # 50% deny rate
            evaluation_periods=3,
            datapoints_to_alarm=2,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        sc_high_deny_rate_alarm.add_alarm_action(cw_actions.SnsAction(self.alerts_topic))
        self.alarms.append(sc_high_deny_rate_alarm)

        # Alarm 5: Security Controller - Suspended Session (P2 - Informational)
        sc_suspended_session_alarm = cloudwatch.Alarm(
            self,
            "SecurityControllerSuspendedSession",
            alarm_name=f"{prefix}-sc-suspended-session",
            alarm_description="Security Controller: Agent session suspended due to low trust score (P2)",
            metric=cloudwatch.Metric(
                namespace="Sentra/SecurityController",
                metric_name="SuspendedSessions",
                statistic="Sum",
                period=Duration.minutes(1),
            ),
            threshold=1,
            evaluation_periods=1,
            datapoints_to_alarm=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        sc_suspended_session_alarm.add_alarm_action(cw_actions.SnsAction(self.info_alerts_topic))
        self.alarms.append(sc_suspended_session_alarm)

        # Note: We now have 6 Security Controller alarms (1-5 from Task 14, plus quarantined sessions)
        sc_quarantined_sessions_alarm = cloudwatch.Alarm(
            self,
            "SecurityControllerQuarantinedSessions",
            alarm_name=f"{prefix}-sc-quarantined-sessions",
            alarm_description="Security Controller: Multiple sessions quarantined (P2)",
            metric=cloudwatch.Metric(
                namespace="Sentra/SecurityController",
                metric_name="QuarantinedSessions",
                statistic="Sum",
                period=Duration.minutes(5),
            ),
            threshold=5,  # > 5 quarantined sessions
            evaluation_periods=1,
            datapoints_to_alarm=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        sc_quarantined_sessions_alarm.add_alarm_action(cw_actions.SnsAction(self.info_alerts_topic))
        self.alarms.append(sc_quarantined_sessions_alarm)

        # Alarm 7: Per-tenant commercial RPS quota exceeded (P1 — LLD-26 §9.3 / WS-E E2b).
        # Fires when a tenant's validate traffic is DENIED for QUOTA_EXCEEDED. Quota is a
        # commercial guardrail (not a security boundary), so this pages the standard P1
        # topic, not critical. Only emits once max_validate_rps enforcement is founder-enabled.
        sc_quota_exceeded_alarm = cloudwatch.Alarm(
            self,
            "QuotaExceededAlarm",
            alarm_name=f"{prefix}-quota-exceeded",
            alarm_description="Security Controller: tenant exceeded its commercial validate-RPS quota (P1, WS-E E2b)",
            metric=cloudwatch.Metric(
                namespace="Sentra/SecurityController",
                metric_name="QuotaExceeded",
                statistic="Sum",
                period=Duration.minutes(5),
            ),
            threshold=1,
            evaluation_periods=1,
            datapoints_to_alarm=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        sc_quota_exceeded_alarm.add_alarm_action(cw_actions.SnsAction(self.alerts_topic))
        self.alarms.append(sc_quota_exceeded_alarm)

        # ============================================================
        # Agent Management API Metrics and Alarms (Task 10)
        # ============================================================
        # Add dashboard widgets and alarms for Agent Management APIs
        # Reference: Workstream 5 Task 10

        # Row 5: Agent Management API Metrics
        # Widget 1: API Request Volume (all 5 endpoints)
        agent_api_volume_widget = cloudwatch.GraphWidget(
            title="Agent Management API - Request Volume",
            left=[
                cloudwatch.Metric(
                    namespace="AgentManagementAPI",
                    metric_name="GetAgents/Count",
                    statistic="Sum",
                    label="GET /v1/agents",
                    period=Duration.minutes(1),
                    color=cloudwatch.Color.BLUE,
                ),
                cloudwatch.Metric(
                    namespace="AgentManagementAPI",
                    metric_name="GetAgent/Count",
                    statistic="Sum",
                    label="GET /v1/agents/{id}",
                    period=Duration.minutes(1),
                    color=cloudwatch.Color.GREEN,
                ),
                cloudwatch.Metric(
                    namespace="AgentManagementAPI",
                    metric_name="GetAgentTools/Count",
                    statistic="Sum",
                    label="GET /v1/agents/{id}/tools",
                    period=Duration.minutes(1),
                    color=cloudwatch.Color.ORANGE,
                ),
                cloudwatch.Metric(
                    namespace="AgentManagementAPI",
                    metric_name="GetPolicies/Count",
                    statistic="Sum",
                    label="GET /v1/policies",
                    period=Duration.minutes(1),
                    color=cloudwatch.Color.PURPLE,
                ),
                cloudwatch.Metric(
                    namespace="AgentManagementAPI",
                    metric_name="GetSigmaRules/Count",
                    statistic="Sum",
                    label="GET /v1/sigma-rules",
                    period=Duration.minutes(1),
                    color=cloudwatch.Color.RED,
                ),
            ],
            width=12,
            height=6,
        )

        # Widget 2: API Latency (p50/p95)
        agent_api_latency_widget = cloudwatch.GraphWidget(
            title="Agent Management API - Latency (p50/p95)",
            left=[
                cloudwatch.Metric(
                    namespace="AgentManagementAPI",
                    metric_name="GetAgents/Latency",
                    statistic="p50",
                    label="GET /v1/agents (p50)",
                    period=Duration.minutes(1),
                    color=cloudwatch.Color.BLUE,
                ),
                cloudwatch.Metric(
                    namespace="AgentManagementAPI",
                    metric_name="GetAgents/Latency",
                    statistic="p95",
                    label="GET /v1/agents (p95)",
                    period=Duration.minutes(1),
                    color=cloudwatch.Color.ORANGE,
                ),
                cloudwatch.Metric(
                    namespace="AgentManagementAPI",
                    metric_name="GetPolicies/Latency",
                    statistic="p50",
                    label="GET /v1/policies (p50)",
                    period=Duration.minutes(1),
                    color=cloudwatch.Color.GREEN,
                ),
                cloudwatch.Metric(
                    namespace="AgentManagementAPI",
                    metric_name="GetSigmaRules/Latency",
                    statistic="p50",
                    label="GET /v1/sigma-rules (p50)",
                    period=Duration.minutes(1),
                    color=cloudwatch.Color.PURPLE,
                ),
            ],
            width=12,
            height=6,
        )

        # Widget 3: Cache Hit Rate
        agent_api_cache_widget = cloudwatch.GraphWidget(
            title="Agent Management API - Cache Hit Rate",
            left=[
                cloudwatch.Metric(
                    namespace="AgentManagementAPI",
                    metric_name="CacheHitRate",
                    dimensions_map={"Operation": "GetAgents"},
                    statistic="Average",
                    label="GET /v1/agents",
                    period=Duration.minutes(5),
                    color=cloudwatch.Color.BLUE,
                ),
                cloudwatch.Metric(
                    namespace="AgentManagementAPI",
                    metric_name="CacheHitRate",
                    dimensions_map={"Operation": "GetPolicies"},
                    statistic="Average",
                    label="GET /v1/policies",
                    period=Duration.minutes(5),
                    color=cloudwatch.Color.GREEN,
                ),
                cloudwatch.Metric(
                    namespace="AgentManagementAPI",
                    metric_name="CacheHitRate",
                    dimensions_map={"Operation": "GetSigmaRules"},
                    statistic="Average",
                    label="GET /v1/sigma-rules",
                    period=Duration.minutes(5),
                    color=cloudwatch.Color.ORANGE,
                ),
            ],
            width=12,
            height=6,
        )

        self.dashboard.add_widgets(
            agent_api_volume_widget,
            agent_api_latency_widget,
            agent_api_cache_widget,
        )

        # Alarm 1: Agent Management API - High Latency (P1)
        agent_api_high_latency_alarm = cloudwatch.Alarm(
            self,
            "AgentAPIHighLatency",
            alarm_name=f"{prefix}-agent-api-high-latency",
            alarm_description="Agent Management API: GET /v1/agents latency exceeds 1 second (P1)",
            metric=cloudwatch.Metric(
                namespace="AgentManagementAPI",
                metric_name="GetAgents/Latency",
                statistic="p95",
                period=Duration.minutes(5),
            ),
            threshold=1000,  # 1 second in milliseconds
            evaluation_periods=2,
            datapoints_to_alarm=2,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        agent_api_high_latency_alarm.add_alarm_action(cw_actions.SnsAction(self.alerts_topic))
        self.alarms.append(agent_api_high_latency_alarm)

        # Alarm 2: Agent Management API - High Error Rate (P0)
        agent_api_errors_alarm = cloudwatch.Alarm(
            self,
            "AgentAPIErrors",
            alarm_name=f"{prefix}-agent-api-errors",
            alarm_description="Agent Management API: High error rate (> 5 errors/min) (P0)",
            metric=cloudwatch.Metric(
                namespace="AgentManagementAPI",
                metric_name="GetAgents/Errors",
                statistic="Sum",
                period=Duration.minutes(1),
            ),
            threshold=5,
            evaluation_periods=2,
            datapoints_to_alarm=2,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        agent_api_errors_alarm.add_alarm_action(cw_actions.SnsAction(self.critical_alerts_topic))
        self.alarms.append(agent_api_errors_alarm)

        # Alarm 3: Agent Management API - Low Cache Hit Rate (P2)
        agent_api_cache_miss_alarm = cloudwatch.Alarm(
            self,
            "AgentAPICacheMissRateHigh",
            alarm_name=f"{prefix}-agent-api-cache-miss-high",
            alarm_description="Agent Management API: Cache hit rate below 50% (P2 - Performance)",
            metric=cloudwatch.Metric(
                namespace="AgentManagementAPI",
                metric_name="CacheHitRate",
                statistic="Average",
                period=Duration.minutes(5),
            ),
            threshold=0.50,  # 50% hit rate
            evaluation_periods=3,
            datapoints_to_alarm=2,
            comparison_operator=cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        agent_api_cache_miss_alarm.add_alarm_action(cw_actions.SnsAction(self.info_alerts_topic))
        self.alarms.append(agent_api_cache_miss_alarm)

        # ============================================================
        # Workstream 11: Policy CRUD Monitoring
        # ============================================================
        # Add dashboard widgets and alarms for Policy CRUD operations
        # Reference: LLD 11 Section 7 (Monitoring & Observability)

        # Row: Policy CRUD - Operations Volume
        policy_crud_volume_widget = cloudwatch.GraphWidget(
            title="Policy CRUD - Operations Volume",
            left=[
                cloudwatch.Metric(
                    namespace="Sentra/SecurityController",
                    metric_name="PolicyCRUD/CREATE_POLICY/Success",
                    statistic="Sum",
                    label="Create (Success)",
                    period=Duration.minutes(5),
                    color=cloudwatch.Color.GREEN,
                ),
                cloudwatch.Metric(
                    namespace="Sentra/SecurityController",
                    metric_name="PolicyCRUD/CREATE_POLICY/Failure",
                    statistic="Sum",
                    label="Create (Failure)",
                    period=Duration.minutes(5),
                    color=cloudwatch.Color.RED,
                ),
                cloudwatch.Metric(
                    namespace="Sentra/SecurityController",
                    metric_name="PolicyCRUD/UPDATE_POLICY/Success",
                    statistic="Sum",
                    label="Update (Success)",
                    period=Duration.minutes(5),
                    color=cloudwatch.Color.BLUE,
                ),
                cloudwatch.Metric(
                    namespace="Sentra/SecurityController",
                    metric_name="PolicyCRUD/UPDATE_POLICY/Failure",
                    statistic="Sum",
                    label="Update (Failure)",
                    period=Duration.minutes(5),
                    color=cloudwatch.Color.ORANGE,
                ),
                cloudwatch.Metric(
                    namespace="Sentra/SecurityController",
                    metric_name="PolicyCRUD/DELETE_POLICY/Success",
                    statistic="Sum",
                    label="Delete (Success)",
                    period=Duration.minutes(5),
                    color=cloudwatch.Color.PURPLE,
                ),
            ],
            width=12,
            height=6,
        )

        # Row: Policy CRUD - Latency
        policy_crud_latency_widget = cloudwatch.GraphWidget(
            title="Policy CRUD - Operation Latency (p50/p95)",
            left=[
                cloudwatch.Metric(
                    namespace="Sentra/SecurityController",
                    metric_name="PolicyCRUD/CREATE_POLICY/Latency",
                    statistic="p50",
                    label="Create (p50)",
                    period=Duration.minutes(5),
                    color=cloudwatch.Color.GREEN,
                ),
                cloudwatch.Metric(
                    namespace="Sentra/SecurityController",
                    metric_name="PolicyCRUD/CREATE_POLICY/Latency",
                    statistic="p95",
                    label="Create (p95)",
                    period=Duration.minutes(5),
                    color=cloudwatch.Color.ORANGE,
                ),
                cloudwatch.Metric(
                    namespace="Sentra/SecurityController",
                    metric_name="PolicyCRUD/UPDATE_POLICY/Latency",
                    statistic="p50",
                    label="Update (p50)",
                    period=Duration.minutes(5),
                    color=cloudwatch.Color.BLUE,
                ),
                cloudwatch.Metric(
                    namespace="Sentra/SecurityController",
                    metric_name="PolicyCRUD/UPDATE_POLICY/Latency",
                    statistic="p95",
                    label="Update (p95)",
                    period=Duration.minutes(5),
                    color=cloudwatch.Color.RED,
                ),
            ],
            width=12,
            height=6,
        )

        # Row: Policy CRUD - Validation Failures
        policy_crud_validation_widget = cloudwatch.GraphWidget(
            title="Policy CRUD - Validation Failures",
            left=[
                cloudwatch.Metric(
                    namespace="Sentra/SecurityController",
                    metric_name="PolicyCRUD/ValidationFailure",
                    dimensions_map={"ValidationType": "SCHEMA_ERROR"},
                    statistic="Sum",
                    label="Schema Errors",
                    period=Duration.minutes(5),
                    color=cloudwatch.Color.RED,
                ),
                cloudwatch.Metric(
                    namespace="Sentra/SecurityController",
                    metric_name="PolicyCRUD/ValidationFailure",
                    dimensions_map={"ValidationType": "AGENT_NOT_FOUND"},
                    statistic="Sum",
                    label="Agent Not Found",
                    period=Duration.minutes(5),
                    color=cloudwatch.Color.ORANGE,
                ),
                cloudwatch.Metric(
                    namespace="Sentra/SecurityController",
                    metric_name="PolicyCRUD/ValidationFailure",
                    dimensions_map={"ValidationType": "TOOL_NOT_FOUND"},
                    statistic="Sum",
                    label="Tool Not Found",
                    period=Duration.minutes(5),
                    color=cloudwatch.Color.PURPLE,
                ),
            ],
            width=12,
            height=6,
        )

        self.dashboard.add_widgets(
            policy_crud_volume_widget,
            policy_crud_latency_widget,
            policy_crud_validation_widget,
        )

        # Alarm 1: Policy CRUD - High Failure Rate (P1)
        policy_crud_failure_alarm = cloudwatch.Alarm(
            self,
            "PolicyCRUDHighFailureRate",
            alarm_name=f"{prefix}-policy-crud-high-failure-rate",
            alarm_description="Policy CRUD: High failure rate (> 5 failures/5min) (P1)",
            metric=cloudwatch.Metric(
                namespace="Sentra/SecurityController",
                metric_name="PolicyCRUD/CREATE_POLICY/Failure",
                statistic="Sum",
                period=Duration.minutes(5),
            ),
            threshold=5,
            evaluation_periods=1,
            datapoints_to_alarm=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        policy_crud_failure_alarm.add_alarm_action(cw_actions.SnsAction(self.alerts_topic))
        self.alarms.append(policy_crud_failure_alarm)

        # Alarm 2: Policy CRUD - High Latency (P1)
        policy_crud_latency_alarm = cloudwatch.Alarm(
            self,
            "PolicyCRUDHighLatency",
            alarm_name=f"{prefix}-policy-crud-high-latency",
            alarm_description="Policy CRUD: Operation latency p95 > 2 seconds (P1)",
            metric=cloudwatch.Metric(
                namespace="Sentra/SecurityController",
                metric_name="PolicyCRUD/CREATE_POLICY/Latency",
                statistic="p95",
                period=Duration.minutes(5),
            ),
            threshold=2000,  # 2 seconds in milliseconds
            evaluation_periods=2,
            datapoints_to_alarm=2,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        policy_crud_latency_alarm.add_alarm_action(cw_actions.SnsAction(self.alerts_topic))
        self.alarms.append(policy_crud_latency_alarm)

        # Alarm 3: Policy CRUD - High Validation Failures (P2)
        policy_crud_validation_alarm = cloudwatch.Alarm(
            self,
            "PolicyCRUDValidationFailures",
            alarm_name=f"{prefix}-policy-crud-validation-failures",
            alarm_description="Policy CRUD: Validation failures > 10/5min (P2 - Info)",
            metric=cloudwatch.Metric(
                namespace="Sentra/SecurityController",
                metric_name="PolicyCRUD/ValidationFailure",
                statistic="Sum",
                period=Duration.minutes(5),
            ),
            threshold=10,
            evaluation_periods=1,
            datapoints_to_alarm=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        policy_crud_validation_alarm.add_alarm_action(cw_actions.SnsAction(self.info_alerts_topic))
        self.alarms.append(policy_crud_validation_alarm)

        # ============================================================
        # Data Model v2 - DynamoDB Tables Monitoring (Task 16 Part B)
        # ============================================================
        # Add monitoring for the 4 new tables: agent-registry, tool-registry,
        # policies-metadata, sigma-rules-metadata
        # Reference: Workstream 6 Task 16

        if storage_stack:
            # Get the 4 new tables from storage stack
            data_model_tables = []
            if hasattr(storage_stack, 'agent_registry_table'):
                data_model_tables.append({
                    "table": storage_stack.agent_registry_table,
                    "label": "Agent Registry"
                })
            if hasattr(storage_stack, 'tool_registry_table'):
                data_model_tables.append({
                    "table": storage_stack.tool_registry_table,
                    "label": "Tool Registry"
                })
            if hasattr(storage_stack, 'policies_metadata_table'):
                data_model_tables.append({
                    "table": storage_stack.policies_metadata_table,
                    "label": "Policies Metadata"
                })
            if hasattr(storage_stack, 'sigma_rules_metadata_table'):
                data_model_tables.append({
                    "table": storage_stack.sigma_rules_metadata_table,
                    "label": "Sigma Rules Metadata"
                })

            if data_model_tables:
                # Row 6: Data Model v2 - DynamoDB Read/Write Capacity
                data_model_capacity_widget = cloudwatch.GraphWidget(
                    title="Data Model v2 - DynamoDB Read/Write Capacity",
                    left=[
                        cloudwatch.Metric(
                            namespace="AWS/DynamoDB",
                            metric_name="ConsumedReadCapacityUnits",
                            dimensions_map={"TableName": t["table"].table_name},
                            statistic="Sum",
                            label=f"{t['label']} (Read)",
                            period=Duration.minutes(5),
                        )
                        for t in data_model_tables
                    ] + [
                        cloudwatch.Metric(
                            namespace="AWS/DynamoDB",
                            metric_name="ConsumedWriteCapacityUnits",
                            dimensions_map={"TableName": t["table"].table_name},
                            statistic="Sum",
                            label=f"{t['label']} (Write)",
                            period=Duration.minutes(5),
                        )
                        for t in data_model_tables
                    ],
                    width=12,
                    height=6,
                )

                # Row 6: Data Model v2 - DynamoDB Throttled Requests
                data_model_throttle_widget = cloudwatch.GraphWidget(
                    title="Data Model v2 - DynamoDB Throttled Requests (Should be 0)",
                    left=[
                        cloudwatch.Metric(
                            namespace="AWS/DynamoDB",
                            metric_name="ReadThrottleEvents",
                            dimensions_map={"TableName": t["table"].table_name},
                            statistic="Sum",
                            label=f"{t['label']} (Read)",
                            period=Duration.minutes(1),
                            color=cloudwatch.Color.RED,
                        )
                        for t in data_model_tables
                    ] + [
                        cloudwatch.Metric(
                            namespace="AWS/DynamoDB",
                            metric_name="WriteThrottleEvents",
                            dimensions_map={"TableName": t["table"].table_name},
                            statistic="Sum",
                            label=f"{t['label']} (Write)",
                            period=Duration.minutes(1),
                            color=cloudwatch.Color.ORANGE,
                        )
                        for t in data_model_tables
                    ],
                    width=12,
                    height=6,
                )

                # Row 7: Data Model v2 - DynamoDB Query Latency
                data_model_latency_widget = cloudwatch.GraphWidget(
                    title="Data Model v2 - DynamoDB Query Latency (p95)",
                    left=[
                        cloudwatch.Metric(
                            namespace="AWS/DynamoDB",
                            metric_name="SuccessfulRequestLatency",
                            dimensions_map={
                                "TableName": t["table"].table_name,
                                "Operation": "Query"
                            },
                            statistic="p95",
                            label=t["label"],
                            period=Duration.minutes(5),
                        )
                        for t in data_model_tables
                    ],
                    width=12,
                    height=6,
                )

                # Row 7: Data Model v2 - S3 Metrics (Policies + Sigma Rules)
                data_model_s3_widget = cloudwatch.GraphWidget(
                    title="Data Model v2 - S3 GET Requests (Policies + Sigma Rules)",
                    left=[
                        cloudwatch.Metric(
                            namespace="AWS/S3",
                            metric_name="GetRequests",
                            dimensions_map={"BucketName": storage_stack.artifacts_bucket.bucket_name},
                            statistic="Sum",
                            label="S3 GET Requests",
                            period=Duration.minutes(5),
                            color=cloudwatch.Color.BLUE,
                        ),
                        cloudwatch.Metric(
                            namespace="AWS/S3",
                            metric_name="4xxErrors",
                            dimensions_map={"BucketName": storage_stack.artifacts_bucket.bucket_name},
                            statistic="Sum",
                            label="4xx Errors",
                            period=Duration.minutes(5),
                            color=cloudwatch.Color.ORANGE,
                        ),
                        cloudwatch.Metric(
                            namespace="AWS/S3",
                            metric_name="5xxErrors",
                            dimensions_map={"BucketName": storage_stack.artifacts_bucket.bucket_name},
                            statistic="Sum",
                            label="5xx Errors",
                            period=Duration.minutes(5),
                            color=cloudwatch.Color.RED,
                        ),
                    ],
                    width=12,
                    height=6,
                )

                self.dashboard.add_widgets(
                    data_model_capacity_widget,
                    data_model_throttle_widget,
                )
                self.dashboard.add_widgets(
                    data_model_latency_widget,
                    data_model_s3_widget,
                )

                # Create alarms for Data Model v2 tables
                for t in data_model_tables:
                    table_name_short = t["label"].replace(" ", "")

                    # Alarm: DynamoDB Throttling
                    throttle_alarm = cloudwatch.Alarm(
                        self,
                        f"DataModelV2Throttle{table_name_short}",
                        alarm_name=f"{prefix}-datamodel-throttle-{t['table'].table_name}",
                        alarm_description=f"Data Model v2: {t['label']} table experiencing throttling (P1)",
                        metric=cloudwatch.Metric(
                            namespace="AWS/DynamoDB",
                            metric_name="ReadThrottleEvents",
                            dimensions_map={"TableName": t["table"].table_name},
                            statistic="Sum",
                            period=Duration.minutes(1),
                        ),
                        threshold=5,
                        evaluation_periods=1,
                        comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
                        treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
                    )
                    throttle_alarm.add_alarm_action(cw_actions.SnsAction(self.alerts_topic))
                    self.alarms.append(throttle_alarm)

                    # Alarm: High Latency
                    latency_alarm = cloudwatch.Alarm(
                        self,
                        f"DataModelV2HighLatency{table_name_short}",
                        alarm_name=f"{prefix}-datamodel-high-latency-{t['table'].table_name}",
                        alarm_description=f"Data Model v2: {t['label']} query latency p95 > 100ms (P2)",
                        metric=cloudwatch.Metric(
                            namespace="AWS/DynamoDB",
                            metric_name="SuccessfulRequestLatency",
                            dimensions_map={
                                "TableName": t["table"].table_name,
                                "Operation": "Query"
                            },
                            statistic="Average",
                            period=Duration.minutes(5),
                        ),
                        threshold=100,  # 100ms
                        evaluation_periods=2,
                        comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
                        treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
                    )
                    latency_alarm.add_alarm_action(cw_actions.SnsAction(self.info_alerts_topic))
                    self.alarms.append(latency_alarm)

                # Alarm: S3 Errors accessing policies/sigma rules
                s3_errors_alarm = cloudwatch.Alarm(
                    self,
                    "DataModelV2S3Errors",
                    alarm_name=f"{prefix}-datamodel-s3-errors",
                    alarm_description="Data Model v2: S3 errors accessing policies/sigma rules (P1)",
                    metric=cloudwatch.Metric(
                        namespace="AWS/S3",
                        metric_name="4xxErrors",
                        dimensions_map={"BucketName": storage_stack.artifacts_bucket.bucket_name},
                        statistic="Sum",
                        period=Duration.minutes(5),
                    ),
                    threshold=5,
                    evaluation_periods=1,
                    comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
                    treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
                )
                s3_errors_alarm.add_alarm_action(cw_actions.SnsAction(self.alerts_topic))
                self.alarms.append(s3_errors_alarm)

        # ============================================================
        # AI Agents Monitoring (Workstream 7 - Task 13)
        # ============================================================
        # Add monitoring for Customer Query Agent and Payment Agent
        # Reference: LLD 07 Section 10, Workstream 7 Task 13

        # Row 8: AI Agents - Request Volume
        ai_agents_request_volume_widget = cloudwatch.GraphWidget(
            title="AI Agents - Request Volume",
            left=[
                cloudwatch.Metric(
                    namespace="Sentra/Agents",
                    metric_name="RequestsReceived",
                    dimensions_map={"ServiceName": "customer-query-agent"},
                    statistic="Sum",
                    label="CQA Requests",
                    period=Duration.minutes(1),
                    color=cloudwatch.Color.BLUE,
                ),
                cloudwatch.Metric(
                    namespace="Sentra/Agents",
                    metric_name="RequestsReceived",
                    dimensions_map={"ServiceName": "payment-agent"},
                    statistic="Sum",
                    label="Payment Agent Requests",
                    period=Duration.minutes(1),
                    color=cloudwatch.Color.GREEN,
                ),
                cloudwatch.Metric(
                    namespace="Sentra/Agents",
                    metric_name="RequestsSucceeded",
                    dimensions_map={"ServiceName": "customer-query-agent"},
                    statistic="Sum",
                    label="CQA Succeeded",
                    period=Duration.minutes(1),
                    color=cloudwatch.Color.PURPLE,
                ),
                cloudwatch.Metric(
                    namespace="Sentra/Agents",
                    metric_name="RequestsSucceeded",
                    dimensions_map={"ServiceName": "payment-agent"},
                    statistic="Sum",
                    label="Payment Agent Succeeded",
                    period=Duration.minutes(1),
                    color=cloudwatch.Color.ORANGE,
                ),
            ],
            width=12,
            height=6,
        )

        # Row 8: AI Agents - Security Denials
        ai_agents_security_denials_widget = cloudwatch.GraphWidget(
            title="AI Agents - Security Denials",
            left=[
                cloudwatch.Metric(
                    namespace="Sentra/Agents",
                    metric_name="SecurityDenials",
                    dimensions_map={"ServiceName": "customer-query-agent"},
                    statistic="Sum",
                    label="CQA Denials",
                    period=Duration.minutes(1),
                    color=cloudwatch.Color.RED,
                ),
                cloudwatch.Metric(
                    namespace="Sentra/Agents",
                    metric_name="SecurityDenials",
                    dimensions_map={"ServiceName": "payment-agent"},
                    statistic="Sum",
                    label="Payment Agent Denials",
                    period=Duration.minutes(1),
                    color=cloudwatch.Color.ORANGE,
                ),
            ],
            width=12,
            height=6,
        )

        # Row 9: AI Agents - Bedrock Latency
        ai_agents_bedrock_latency_widget = cloudwatch.GraphWidget(
            title="AI Agents - Bedrock Latency (p50/p95)",
            left=[
                cloudwatch.Metric(
                    namespace="Sentra/Agents",
                    metric_name="BedrockLatency",
                    dimensions_map={"ServiceName": "customer-query-agent"},
                    statistic="p50",
                    label="CQA p50",
                    period=Duration.minutes(1),
                    color=cloudwatch.Color.BLUE,
                ),
                cloudwatch.Metric(
                    namespace="Sentra/Agents",
                    metric_name="BedrockLatency",
                    dimensions_map={"ServiceName": "customer-query-agent"},
                    statistic="p95",
                    label="CQA p95",
                    period=Duration.minutes(1),
                    color=cloudwatch.Color.ORANGE,
                ),
                cloudwatch.Metric(
                    namespace="Sentra/Agents",
                    metric_name="BedrockLatency",
                    dimensions_map={"ServiceName": "payment-agent"},
                    statistic="p50",
                    label="Payment Agent p50",
                    period=Duration.minutes(1),
                    color=cloudwatch.Color.GREEN,
                ),
                cloudwatch.Metric(
                    namespace="Sentra/Agents",
                    metric_name="BedrockLatency",
                    dimensions_map={"ServiceName": "payment-agent"},
                    statistic="p95",
                    label="Payment Agent p95",
                    period=Duration.minutes(1),
                    color=cloudwatch.Color.RED,
                ),
            ],
            width=12,
            height=6,
        )

        # Row 9: AI Agents - Tool Execution Time
        ai_agents_tool_execution_widget = cloudwatch.GraphWidget(
            title="AI Agents - Tool Execution Time (p95)",
            left=[
                cloudwatch.Metric(
                    namespace="Sentra/Agents",
                    metric_name="ToolExecutionTime",
                    dimensions_map={"ServiceName": "customer-query-agent"},
                    statistic="p95",
                    label="CQA Tools",
                    period=Duration.minutes(1),
                    color=cloudwatch.Color.BLUE,
                ),
                cloudwatch.Metric(
                    namespace="Sentra/Agents",
                    metric_name="ToolExecutionTime",
                    dimensions_map={"ServiceName": "payment-agent"},
                    statistic="p95",
                    label="Payment Agent Tools",
                    period=Duration.minutes(1),
                    color=cloudwatch.Color.GREEN,
                ),
            ],
            width=12,
            height=6,
        )

        # Row 10: AI Agents - Bedrock Token Usage
        ai_agents_tokens_widget = cloudwatch.GraphWidget(
            title="AI Agents - Bedrock Token Usage",
            left=[
                cloudwatch.Metric(
                    namespace="Sentra/Agents",
                    metric_name="BedrockInputTokens",
                    dimensions_map={"ServiceName": "customer-query-agent"},
                    statistic="Sum",
                    label="CQA Input Tokens",
                    period=Duration.minutes(5),
                    color=cloudwatch.Color.BLUE,
                ),
                cloudwatch.Metric(
                    namespace="Sentra/Agents",
                    metric_name="BedrockOutputTokens",
                    dimensions_map={"ServiceName": "customer-query-agent"},
                    statistic="Sum",
                    label="CQA Output Tokens",
                    period=Duration.minutes(5),
                    color=cloudwatch.Color.GREEN,
                ),
                cloudwatch.Metric(
                    namespace="Sentra/Agents",
                    metric_name="BedrockInputTokens",
                    dimensions_map={"ServiceName": "payment-agent"},
                    statistic="Sum",
                    label="Payment Input Tokens",
                    period=Duration.minutes(5),
                    color=cloudwatch.Color.ORANGE,
                ),
                cloudwatch.Metric(
                    namespace="Sentra/Agents",
                    metric_name="BedrockOutputTokens",
                    dimensions_map={"ServiceName": "payment-agent"},
                    statistic="Sum",
                    label="Payment Output Tokens",
                    period=Duration.minutes(5),
                    color=cloudwatch.Color.RED,
                ),
            ],
            width=12,
            height=6,
        )

        # Row 10: AI Agents - Trust Score Average
        ai_agents_trust_score_widget = cloudwatch.SingleValueWidget(
            title="AI Agents - Average Trust Score",
            metrics=[
                cloudwatch.Metric(
                    namespace="Sentra/Agents",
                    metric_name="TrustScoreAverage",
                    dimensions_map={"ServiceName": "customer-query-agent"},
                    statistic="Average",
                    label="CQA",
                    period=Duration.minutes(5),
                ),
                cloudwatch.Metric(
                    namespace="Sentra/Agents",
                    metric_name="TrustScoreAverage",
                    dimensions_map={"ServiceName": "payment-agent"},
                    statistic="Average",
                    label="Payment Agent",
                    period=Duration.minutes(5),
                ),
            ],
            width=12,
            height=6,
        )

        self.dashboard.add_widgets(
            ai_agents_request_volume_widget,
            ai_agents_security_denials_widget,
        )
        self.dashboard.add_widgets(
            ai_agents_bedrock_latency_widget,
            ai_agents_tool_execution_widget,
        )
        self.dashboard.add_widgets(
            ai_agents_tokens_widget,
            ai_agents_trust_score_widget,
        )

        # ============================================================
        # AI Agents Alarms (Workstream 7 - Task 13)
        # ============================================================

        # Alarm 1: Customer Query Agent - Health Check Failure (P0)
        cqa_health_alarm = cloudwatch.Alarm(
            self,
            "CustomerQueryAgentHealthCheckFailure",
            alarm_name=f"{prefix}-cqa-health-check-failure",
            alarm_description="Customer Query Agent: Health check failing (P0 - Demo Breaking)",
            metric=cloudwatch.Metric(
                namespace="Sentra/Agents",
                metric_name="HealthCheckStatus",
                dimensions_map={"ServiceName": "customer-query-agent"},
                statistic="Average",
                period=Duration.minutes(1),
            ),
            threshold=1,  # 0 = healthy, 1 = unhealthy
            evaluation_periods=2,
            datapoints_to_alarm=2,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.BREACHING,
        )
        cqa_health_alarm.add_alarm_action(cw_actions.SnsAction(self.critical_alerts_topic))
        self.alarms.append(cqa_health_alarm)

        # Alarm 2: Payment Agent - Health Check Failure (P0)
        pa_health_alarm = cloudwatch.Alarm(
            self,
            "PaymentAgentHealthCheckFailure",
            alarm_name=f"{prefix}-pa-health-check-failure",
            alarm_description="Payment Agent: Health check failing (P0 - Demo Breaking)",
            metric=cloudwatch.Metric(
                namespace="Sentra/Agents",
                metric_name="HealthCheckStatus",
                dimensions_map={"ServiceName": "payment-agent"},
                statistic="Average",
                period=Duration.minutes(1),
            ),
            threshold=1,
            evaluation_periods=2,
            datapoints_to_alarm=2,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.BREACHING,
        )
        pa_health_alarm.add_alarm_action(cw_actions.SnsAction(self.critical_alerts_topic))
        self.alarms.append(pa_health_alarm)

        # Alarm 3: AI Agents - High Latency (P1)
        ai_agents_high_latency_alarm = cloudwatch.Alarm(
            self,
            "AIAgentsHighLatency",
            alarm_name=f"{prefix}-ai-agents-high-latency",
            alarm_description="AI Agents: Response time p95 exceeds 5 seconds (P1)",
            metric=cloudwatch.Metric(
                namespace="Sentra/Agents",
                metric_name="ResponseLatency",
                statistic="p95",
                period=Duration.minutes(5),
            ),
            threshold=5000,  # 5 seconds in milliseconds
            evaluation_periods=2,
            datapoints_to_alarm=2,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        ai_agents_high_latency_alarm.add_alarm_action(cw_actions.SnsAction(self.alerts_topic))
        self.alarms.append(ai_agents_high_latency_alarm)

        # Alarm 4: AI Agents - Bedrock Errors (P0)
        ai_agents_bedrock_errors_alarm = cloudwatch.Alarm(
            self,
            "AIAgentsBedrockErrors",
            alarm_name=f"{prefix}-ai-agents-bedrock-errors",
            alarm_description="AI Agents: Bedrock API errors > 5/min (P0 - Demo Breaking)",
            metric=cloudwatch.Metric(
                namespace="Sentra/Agents",
                metric_name="BedrockErrors",
                statistic="Sum",
                period=Duration.minutes(1),
            ),
            threshold=5,
            evaluation_periods=2,
            datapoints_to_alarm=2,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        ai_agents_bedrock_errors_alarm.add_alarm_action(cw_actions.SnsAction(self.critical_alerts_topic))
        self.alarms.append(ai_agents_bedrock_errors_alarm)

        # Alarm 5: AI Agents - High Security Denial Rate (P1)
        ai_agents_high_denial_rate_alarm = cloudwatch.Alarm(
            self,
            "AIAgentsHighDenialRate",
            alarm_name=f"{prefix}-ai-agents-high-denial-rate",
            alarm_description="AI Agents: Security denial rate > 30% for 5 min (P1)",
            metric=cloudwatch.Metric(
                namespace="Sentra/Agents",
                metric_name="SecurityDenialRate",
                statistic="Average",
                period=Duration.minutes(5),
            ),
            threshold=0.30,  # 30% denial rate
            evaluation_periods=1,
            datapoints_to_alarm=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        ai_agents_high_denial_rate_alarm.add_alarm_action(cw_actions.SnsAction(self.alerts_topic))
        self.alarms.append(ai_agents_high_denial_rate_alarm)

        # Alarm 6: AI Agents - Tool Execution Errors (P1)
        ai_agents_tool_errors_alarm = cloudwatch.Alarm(
            self,
            "AIAgentsToolExecutionErrors",
            alarm_name=f"{prefix}-ai-agents-tool-errors",
            alarm_description="AI Agents: Tool execution failures > 10/min (P1)",
            metric=cloudwatch.Metric(
                namespace="Sentra/Agents",
                metric_name="ToolExecutionErrors",
                statistic="Sum",
                period=Duration.minutes(1),
            ),
            threshold=10,
            evaluation_periods=2,
            datapoints_to_alarm=2,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        ai_agents_tool_errors_alarm.add_alarm_action(cw_actions.SnsAction(self.alerts_topic))
        self.alarms.append(ai_agents_tool_errors_alarm)

        # Alarm 7: Customer Query Agent - Request Failures (P1)
        cqa_request_failures_alarm = cloudwatch.Alarm(
            self,
            "CustomerQueryAgentRequestFailures",
            alarm_name=f"{prefix}-cqa-request-failures",
            alarm_description="Customer Query Agent: Request failures > 5/min (P1)",
            metric=cloudwatch.Metric(
                namespace="Sentra/Agents",
                metric_name="RequestsFailed",
                dimensions_map={"ServiceName": "customer-query-agent"},
                statistic="Sum",
                period=Duration.minutes(1),
            ),
            threshold=5,
            evaluation_periods=2,
            datapoints_to_alarm=2,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        cqa_request_failures_alarm.add_alarm_action(cw_actions.SnsAction(self.alerts_topic))
        self.alarms.append(cqa_request_failures_alarm)

        # Alarm 8: Payment Agent - Request Failures (P1)
        pa_request_failures_alarm = cloudwatch.Alarm(
            self,
            "PaymentAgentRequestFailures",
            alarm_name=f"{prefix}-pa-request-failures",
            alarm_description="Payment Agent: Request failures > 5/min (P1)",
            metric=cloudwatch.Metric(
                namespace="Sentra/Agents",
                metric_name="RequestsFailed",
                dimensions_map={"ServiceName": "payment-agent"},
                statistic="Sum",
                period=Duration.minutes(1),
            ),
            threshold=5,
            evaluation_periods=2,
            datapoints_to_alarm=2,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        pa_request_failures_alarm.add_alarm_action(cw_actions.SnsAction(self.alerts_topic))
        self.alarms.append(pa_request_failures_alarm)

        # ============================================================
        # CloudFormation Outputs (Task 14)
        # ============================================================

        CfnOutput(
            self,
            "DashboardUrl",
            description="CloudWatch Dashboard URL",
            value=f"https://console.aws.amazon.com/cloudwatch/home?region={self.region}#dashboards:name={self.dashboard.dashboard_name}",
            export_name=f"{construct_id}-DashboardUrl",
        )

        CfnOutput(
            self,
            "DashboardName",
            description="CloudWatch Dashboard Name",
            value=self.dashboard.dashboard_name,
            export_name=f"{construct_id}-DashboardName",
        )

        CfnOutput(
            self,
            "AlertsTopicArn",
            description="SNS Topic ARN for alerts",
            value=self.alerts_topic.topic_arn,
            export_name=f"{construct_id}-AlertsTopicArn",
        )

        CfnOutput(
            self,
            "AlertsTopicName",
            description="SNS Topic Name for alerts",
            value=self.alerts_topic.topic_name,
            export_name=f"{construct_id}-AlertsTopicName",
        )

        CfnOutput(
            self,
            "AlarmsCount",
            description="Number of CloudWatch Alarms created",
            value=str(len(self.alarms)),
        )

        CfnOutput(
            self,
            "CriticalAlertsTopicArn",
            description="SNS Topic ARN for critical alerts (P0)",
            value=self.critical_alerts_topic.topic_arn,
            export_name=f"{construct_id}-CriticalAlertsTopicArn",
        )

        CfnOutput(
            self,
            "InfoAlertsTopicArn",
            description="SNS Topic ARN for info alerts (P2)",
            value=self.info_alerts_topic.topic_arn,
            export_name=f"{construct_id}-InfoAlertsTopicArn",
        )
