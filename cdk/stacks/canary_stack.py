"""WS-J J-infra — the synthetic-canary ECS monitor stack (lld/38 §9, tasks §6).

Net-new infra for the HOURLY prod synthetic monitor (Runner B): an ECS Fargate
task def running the 8th image (``sentra/canary``) against the live API Gateway,
an EventBridge Scheduler firing ``rate(1 hour)``, the ``sentra-canary-results``
DynamoDB failure ledger, a dedicated ``sentra-canary-alerts`` SNS topic with the
P0-3 email subscription, and the ``Sentra/Canary`` alarms (ChecksFailed +
anti-false-PASS + overlap). Copies the compute/monitoring/storage-stack patterns.

Least privilege (SEC-4): the canary task role gets ONLY secrets ``sentra/canary/*``,
CW ``Sentra/Canary`` PutMetricData, DDB ``sentra-canary-results`` PutItem/Query, SNS
Publish on the two canary topics, and cluster-scoped ``ecs:ListTasks`` (the overlap
guard) — NO product-table write, NO ``apigateway:GET`` (that is Increment-2 J8).
"""
from __future__ import annotations

from typing import Optional

from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_scheduler as scheduler
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as sns_subs
from constructs import Construct

CANARY_ALERT_EMAIL = "shshgup@amazon.com"  # P0-3 (founder) — verbatim.
CANARY_NAMESPACE = "Sentra/Canary"
RESULTS_TABLE_NAME = "sentra-canary-results"
CANARY_ALERTS_TOPIC = "sentra-canary-alerts"

# The metric names the alarms below WATCH. Every one of these MUST be emitted at
# runtime by ``canary.entrypoint`` (emit_run_metrics + guard_at_most_one), or the
# alarm watching it is dead (a never-produced metric never fires a NOT_BREACHING
# alarm, and sits permanently ALARM under BREACHING). The alarm-to-emitter seam is
# asserted by tests/canary/test_metric_emission_seam.py, which joins THIS set against
# the names entrypoint actually emits — reverting either end breaks that test.
ALARM_METRIC_NAMES = frozenset({
    "ChecksFailed",          # ChecksFailed alarm (BREACHING monitor-the-monitor)
    "ChecksPassed",          # shortfall math (p)
    "InfraErrors",           # shortfall math (i)
    "ChecksExpected",        # shortfall math (expected) — anti-false-PASS §9.4
    "CanarySkippedOverlap",  # overlap alarm (Jr.4)
    "ProductFivexxFail",     # product-5xx critical escalation (§9.1)
})


class CanaryStack(Stack):
    """The WS-J ECS synthetic-monitor stack."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: dict,
        vpc: ec2.IVpc,
        cluster: ecs.ICluster,
        execution_role: Optional[iam.IRole] = None,
        api_gw_url: str = "",
        critical_alerts_topic_arn: Optional[str] = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        prefix = config.get("naming", {}).get("prefix", "sentra-mvp")

        # Execution role: a canary-LOCAL role (NOT the shared ComputeStack one).
        # Reusing the cross-stack shared exec role creates a CloudFormation cyclic
        # reference — CDK auto-grants the exec role write access to this stack's
        # /ecs/sentra/canary LogGroup (ComputeStack -> CanaryStack) while the canary
        # already imports the cluster/roles (CanaryStack -> ComputeStack). A local,
        # minimal exec role (ECR pull + its own log group) breaks the cycle and keeps
        # least-privilege — the exec role only pulls the image + writes canary logs.
        if execution_role is None:
            execution_role = iam.Role(
                self,
                "CanaryExecutionRole",
                assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
                managed_policies=[
                    iam.ManagedPolicy.from_aws_managed_policy_name(
                        "service-role/AmazonECSTaskExecutionRolePolicy"
                    )
                ],
                description="WS-J canary ECS execution role (image pull + logs).",
            )
        self.execution_role = execution_role

        # ---- 1) sentra-canary-results DDB (Ji.3) — the failure ledger -----------
        self.results_table = dynamodb.Table(
            self,
            "CanaryResults",
            table_name=RESULTS_TABLE_NAME,
            partition_key=dynamodb.Attribute(
                name="run_id", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="check_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",  # 90-day epoch — plugin sets it every row.
            point_in_time_recovery=False,  # ephemeral observability data.
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ---- 2) log group (Ji.4) -------------------------------------------------
        self.log_group = logs.LogGroup(
            self,
            "CanaryLogGroup",
            log_group_name="/ecs/sentra/canary",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ---- 3) SNS topics (Ji.6 / P0-3) -----------------------------------------
        # Dedicated canary topic (SEC-8) so routine FAILs can't desensitize the
        # shared critical audience. The P0-3 email subscription lands HERE.
        self.canary_alerts_topic = sns.Topic(
            self,
            "CanaryAlertsTopic",
            topic_name=CANARY_ALERTS_TOPIC,
            display_name="Sentra Canary Alerts",
        )
        self.canary_alerts_topic.add_subscription(
            sns_subs.EmailSubscription(CANARY_ALERT_EMAIL)
        )
        # The shared critical topic (only sustained/product-5xx escalations page here).
        if critical_alerts_topic_arn:
            self.critical_alerts_topic = sns.Topic.from_topic_arn(
                self, "ImportedCriticalTopic", critical_alerts_topic_arn
            )
        else:
            self.critical_alerts_topic = None

        # ---- 4) canary task role (SEC-4 least privilege) -------------------------
        self.canary_task_role = iam.Role(
            self,
            "CanaryTaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            description="WS-J canary task — minimal SEC-4 permissions only.",
        )
        self.canary_task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[
                    f"arn:aws:secretsmanager:{self.region}:{self.account}:secret:sentra/canary/*"
                ],
            )
        )
        self.canary_task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],
                conditions={
                    "StringEquals": {"cloudwatch:namespace": CANARY_NAMESPACE}
                },
            )
        )
        self.canary_task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["dynamodb:PutItem", "dynamodb:Query"],
                resources=[self.results_table.table_arn],
            )
        )
        publish_arns = [self.canary_alerts_topic.topic_arn]
        if critical_alerts_topic_arn:
            publish_arns.append(critical_alerts_topic_arn)
        self.canary_task_role.add_to_policy(
            iam.PolicyStatement(actions=["sns:Publish"], resources=publish_arns)
        )
        # cluster-scoped ecs:ListTasks for the at-most-one overlap guard (§12.1).
        self.canary_task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ecs:ListTasks"],
                resources=["*"],
                conditions={
                    "ArnEquals": {"ecs:cluster": cluster.cluster_arn}
                },
            )
        )
        # (NO apigateway:GET, NO product-table write — Increment-1 scope.)

        # ---- 5) Fargate task def (Ji.4) ------------------------------------------
        self.task_definition = ecs.FargateTaskDefinition(
            self,
            "CanaryTaskDef",
            family="sentra-canary",
            cpu=512,
            memory_limit_mib=1024,
            task_role=self.canary_task_role,
            execution_role=execution_role,
        )
        self.task_definition.add_container(
            "CanaryContainer",
            container_name="canary",
            image=ecs.ContainerImage.from_registry(
                f"{self.account}.dkr.ecr.{self.region}.amazonaws.com/sentra/canary:latest"
            ),
            logging=ecs.LogDriver.aws_logs(
                stream_prefix="canary", log_group=self.log_group
            ),
            environment={
                "CANARY_TARGET": "live",
                "SENTRA_API_GW_URL": api_gw_url,
                "CANARY_RESULTS_TABLE": RESULTS_TABLE_NAME,
            },
            # 15-min hard deadline — a wedged task is reaped externally (§12).
            stop_timeout=Duration.minutes(2),
        )

        self.canary_sg = ec2.SecurityGroup(
            self,
            "CanarySecurityGroup",
            vpc=vpc,
            description="WS-J canary task — egress to public API Gateway via NAT.",
            allow_all_outbound=True,
        )

        # ---- 6) EventBridge Scheduler rate(1 hour) → RunTask (Ji.5) --------------
        scheduler_role = iam.Role(
            self,
            "CanarySchedulerRole",
            assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"),
            description="EventBridge Scheduler → ecs:RunTask on the canary task def.",
        )
        scheduler_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ecs:RunTask"],
                resources=[self.task_definition.task_definition_arn],
            )
        )
        # iam:PassRole MUST cover BOTH the task role and the execution role (§12.1).
        scheduler_role.add_to_policy(
            iam.PolicyStatement(
                actions=["iam:PassRole"],
                resources=[self.canary_task_role.role_arn, execution_role.role_arn],
            )
        )
        self.scheduler_role = scheduler_role

        private_subnet_ids = [
            s.subnet_id
            for s in vpc.select_subnets(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ).subnets
        ]

        self.schedule = scheduler.CfnSchedule(
            self,
            "CanarySchedule",
            flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(
                mode="OFF"
            ),
            schedule_expression="rate(1 hour)",
            name=f"{prefix}-canary-hourly",
            target=scheduler.CfnSchedule.TargetProperty(
                arn=cluster.cluster_arn,
                role_arn=scheduler_role.role_arn,
                ecs_parameters=scheduler.CfnSchedule.EcsParametersProperty(
                    task_definition_arn=self.task_definition.task_definition_arn,
                    launch_type="FARGATE",
                    network_configuration=scheduler.CfnSchedule.NetworkConfigurationProperty(
                        awsvpc_configuration=scheduler.CfnSchedule.AwsVpcConfigurationProperty(
                            subnets=private_subnet_ids,
                            security_groups=[self.canary_sg.security_group_id],
                            assign_public_ip="DISABLED",
                        )
                    ),
                ),
            ),
        )

        # ---- 7) alarms (Ji.6 / Jr.3) ---------------------------------------------
        checks_failed = cloudwatch.Metric(
            namespace=CANARY_NAMESPACE,
            metric_name="ChecksFailed",
            period=Duration.hours(1),
            statistic="Sum",
        )
        self.checks_failed_alarm = cloudwatch.Alarm(
            self,
            "CanaryChecksFailedAlarm",
            alarm_name=f"{prefix}-canary-checks-failed",
            metric=checks_failed,
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            # Monitor-the-monitor: entrypoint.emit_run_metrics emits ChecksFailed EVERY
            # hourly run (0 on a clean run, ≥1 on a real failure), so BREACHING fires
            # ONLY when a run produced no datapoint at all — i.e. the hourly canary did
            # not run / crashed before emit. (Before the emitter was wired this metric
            # was never produced, so BREACHING meant a permanent false ALARM — the
            # dead-seam bug this WS closes; the emission is asserted by the seam test.)
            treat_missing_data=cloudwatch.TreatMissingData.BREACHING,
        )
        self.checks_failed_alarm.add_alarm_action(
            cw_actions.SnsAction(self.canary_alerts_topic)
        )

        # anti-false-PASS (§9.4): Passed+Failed+Infra < Expected → a check-dropping run.
        expected_metric = cloudwatch.Metric(
            namespace=CANARY_NAMESPACE, metric_name="ChecksExpected",
            period=Duration.hours(1), statistic="Maximum",
        )
        reported_metric = cloudwatch.MathExpression(
            expression="p + f + i",
            using_metrics={
                "p": cloudwatch.Metric(namespace=CANARY_NAMESPACE, metric_name="ChecksPassed",
                                       period=Duration.hours(1), statistic="Sum"),
                "f": checks_failed,
                "i": cloudwatch.Metric(namespace=CANARY_NAMESPACE, metric_name="InfraErrors",
                                       period=Duration.hours(1), statistic="Sum"),
            },
        )
        shortfall = cloudwatch.MathExpression(
            expression="expected - reported",
            using_metrics={"expected": expected_metric, "reported": reported_metric},
        )
        self.shortfall_alarm = cloudwatch.Alarm(
            self,
            "CanaryChecksShortfallAlarm",
            alarm_name=f"{prefix}-canary-checks-shortfall",
            metric=shortfall,
            threshold=0,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        self.shortfall_alarm.add_alarm_action(
            cw_actions.SnsAction(self.canary_alerts_topic)
        )

        # overlap visibility (Jr.4): 2 consecutive CanarySkippedOverlap periods → page.
        overlap_metric = cloudwatch.Metric(
            namespace=CANARY_NAMESPACE, metric_name="CanarySkippedOverlap",
            period=Duration.hours(1), statistic="Sum",
        )
        self.overlap_alarm = cloudwatch.Alarm(
            self,
            "CanaryOverlapAlarm",
            alarm_name=f"{prefix}-canary-skipped-overlap",
            metric=overlap_metric,
            threshold=1,
            evaluation_periods=2,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        self.overlap_alarm.add_alarm_action(
            cw_actions.SnsAction(self.canary_alerts_topic)
        )

        # product-5xx escalation → the CRITICAL topic (SEC-8) when imported.
        if self.critical_alerts_topic is not None:
            product_5xx = cloudwatch.Metric(
                namespace=CANARY_NAMESPACE, metric_name="ProductFivexxFail",
                period=Duration.hours(1), statistic="Sum",
            )
            self.product_5xx_alarm = cloudwatch.Alarm(
                self,
                "CanaryProductFivexxAlarm",
                alarm_name=f"{prefix}-canary-product-5xx",
                metric=product_5xx,
                threshold=1,
                evaluation_periods=1,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            )
            self.product_5xx_alarm.add_alarm_action(
                cw_actions.SnsAction(self.critical_alerts_topic)
            )
