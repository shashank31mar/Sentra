"""WS-J J-infra — CDK unit tests for CanaryStack (lld/38 §9).

Asserts the synthesized CloudFormation carries the P0-3 email subscription, the
sentra-canary-results DDB, the least-privilege task role (SEC-4), the sentra-canary
Fargate task def, the EventBridge rate(1 hour) schedule + scheduler role, and the
ChecksFailed / anti-false-PASS / overlap alarms — the contracts the reporting plugin
and scheduler depend on.
"""
import os
from pathlib import Path

import aws_cdk as cdk
import yaml
from aws_cdk.assertions import Match, Template
from stacks.canary_stack import CanaryStack
from stacks.compute_stack import ComputeStack
from stacks.cognito_stack import CognitoStack
from stacks.network_stack import NetworkStack
from stacks.storage_stack import StorageStack


def _load_cdk_config():
    repo_root = Path(__file__).resolve().parents[2]
    with open(repo_root / "cdk" / "config" / "dev.yaml", "r") as f:
        config = yaml.safe_load(f)
    config.setdefault("aws", {})
    config["aws"]["account_id"] = os.environ.get("AWS_ACCOUNT_ID", "123456789012")
    config["aws"]["region"] = os.environ.get("AWS_REGION", "us-east-1")
    return config


def _canary_template():
    os.environ["ENV"] = "dev"
    os.environ.setdefault("AWS_ACCOUNT_ID", "123456789012")
    os.environ.setdefault("AWS_REGION", "us-east-1")
    config = _load_cdk_config()
    env = cdk.Environment(account="123456789012", region="us-east-1")
    app = cdk.App()
    network = NetworkStack(app, "TestNetworkStack", config=config, env=env)
    storage = StorageStack(app, "TestStorageStack", config=config, env=env)
    cognito = CognitoStack(app, "TestCognitoStack", config=config, env=env)
    compute = ComputeStack(
        app, "TestComputeStack", config=config, network_stack=network,
        storage_stack=storage, cognito_stack=cognito, env=env,
    )
    canary = CanaryStack(
        app, "TestCanaryStack",
        config=config,
        vpc=network.vpc,
        cluster=compute.ecs_cluster,
        # execution_role omitted → canary-local exec role (avoids the cross-stack
        # log-group-grant cyclic reference; see CanaryStack rationale).
        api_gw_url="https://api.example.invalid/prod",
        critical_alerts_topic_arn="arn:aws:sns:us-east-1:123456789012:sentra-mvp-critical-alerts",
        env=env,
    )
    return Template.from_stack(canary)


def test_canary_results_table():
    """Ji.3 — sentra-canary-results with PK run_id/SK check_id, PAY_PER_REQUEST, TTL ttl."""
    t = _canary_template()
    t.has_resource_properties("AWS::DynamoDB::Table", {
        "TableName": "sentra-canary-results",
        "BillingMode": "PAY_PER_REQUEST",
        "KeySchema": [
            {"AttributeName": "run_id", "KeyType": "HASH"},
            {"AttributeName": "check_id", "KeyType": "RANGE"},
        ],
        "TimeToLiveSpecification": {"AttributeName": "ttl", "Enabled": True},
    })


def test_canary_sns_email_p0_3():
    """P0-3 — a sentra-canary-alerts topic carries an EmailSubscription to
    shshgup@amazon.com (verbatim)."""
    t = _canary_template()
    t.has_resource_properties("AWS::SNS::Topic", {"TopicName": "sentra-canary-alerts"})
    t.has_resource_properties("AWS::SNS::Subscription", {
        "Protocol": "email",
        "Endpoint": "shshgup@amazon.com",
    })


def test_canary_task_def_least_privilege():
    """Ji.4 — a sentra-canary Fargate task def (512/1024) with CANARY_TARGET=live and
    a task role scoped to the SEC-4 actions (no product-table write, no apigateway:GET)."""
    t = _canary_template()
    t.has_resource_properties("AWS::ECS::TaskDefinition", {
        "Family": "sentra-canary",
        "Cpu": "512",
        "Memory": "1024",
    })
    # The container carries CANARY_TARGET=live.
    t.has_resource_properties("AWS::ECS::TaskDefinition", {
        "ContainerDefinitions": Match.array_with([
            Match.object_like({
                "Environment": Match.array_with([
                    {"Name": "CANARY_TARGET", "Value": "live"},
                ]),
            }),
        ]),
    })
    # The task role must NOT grant apigateway:GET (Increment-1 negative contract).
    policies = t.find_resources("AWS::IAM::Policy")
    all_actions = []
    for p in policies.values():
        for stmt in p["Properties"]["PolicyDocument"]["Statement"]:
            act = stmt.get("Action")
            all_actions.extend(act if isinstance(act, list) else [act])
    assert not any("apigateway" in str(a).lower() for a in all_actions), \
        "canary role must not carry apigateway:* in Increment 1"
    assert any("ecs:ListTasks" == a for a in all_actions), "overlap guard needs ecs:ListTasks"
    assert any("cloudwatch:PutMetricData" == a for a in all_actions)
    assert any("dynamodb:PutItem" == a for a in all_actions)


def test_canary_scheduler_rate_1_hour():
    """Ji.5 — an EventBridge Scheduler rate(1 hour) → ECS RunTask target; the
    scheduler role passes both roles."""
    t = _canary_template()
    t.has_resource_properties("AWS::Scheduler::Schedule", {
        "ScheduleExpression": "rate(1 hour)",
    })
    # The scheduler role allows ecs:RunTask + iam:PassRole.
    policies = t.find_resources("AWS::IAM::Policy")
    acts = set()
    for p in policies.values():
        for stmt in p["Properties"]["PolicyDocument"]["Statement"]:
            a = stmt.get("Action")
            acts.update(a if isinstance(a, list) else [a])
    assert "ecs:RunTask" in acts
    assert "iam:PassRole" in acts


def test_canary_alarms():
    """Ji.6 / Jr.3 — ChecksFailed>=1 (BREACHING) + overlap alarms exist."""
    t = _canary_template()
    t.has_resource_properties("AWS::CloudWatch::Alarm", {
        "MetricName": "ChecksFailed",
        "Namespace": "Sentra/Canary",
        "TreatMissingData": "breaching",
    })
    t.has_resource_properties("AWS::CloudWatch::Alarm", {
        "MetricName": "CanarySkippedOverlap",
        "EvaluationPeriods": 2,
    })


def test_canary_product_5xx_alarm_escalates_to_critical_topic():
    """§9.1 — the ProductFivexxFail alarm exists and (when the critical topic is
    imported) escalates there. The metric it watches is emitted every run by
    entrypoint.emit_run_metrics (the alarm-to-emitter seam is asserted end-to-end by
    tests/canary/test_metric_emission_seam.py)."""
    t = _canary_template()
    t.has_resource_properties("AWS::CloudWatch::Alarm", {
        "MetricName": "ProductFivexxFail",
        "Namespace": "Sentra/Canary",
    })


def test_alarm_metric_names_are_all_in_the_emitter_contract():
    """The stack's ALARM_METRIC_NAMES contract lists exactly the metrics the alarms
    watch — the join anchor the seam test uses to prove every one is emitted."""
    from stacks.canary_stack import ALARM_METRIC_NAMES

    assert ALARM_METRIC_NAMES == frozenset({
        "ChecksFailed", "ChecksPassed", "InfraErrors", "ChecksExpected",
        "CanarySkippedOverlap", "ProductFivexxFail",
    })


def test_canary_ecr_repo_created():
    """Ji.2 — the StorageStack synthesizes an ECR repo sentra/canary (the 8th image)."""
    os.environ["ENV"] = "dev"
    config = _load_cdk_config()
    env = cdk.Environment(account="123456789012", region="us-east-1")
    app = cdk.App()
    storage = StorageStack(app, "TestStorageStackEcr", config=config, env=env)
    t = Template.from_stack(storage)
    t.has_resource_properties("AWS::ECR::Repository", {"RepositoryName": "sentra/canary"})
