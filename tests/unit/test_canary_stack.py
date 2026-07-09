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


def _canary_template(*, with_critical_topic: bool = True):
    """Synthesize the CanaryStack. ``with_critical_topic=False`` exercises the
    topic-ABSENT instantiation (a CanaryStack stood up without the shared critical
    topic) — the branch app.py doesn't hit today but the code must stay fail-secure
    under (FINDING 2)."""
    os.environ["ENV"] = "dev"
    os.environ.setdefault("AWS_ACCOUNT_ID", "123456789012")
    os.environ.setdefault("AWS_REGION", "us-east-1")
    config = _load_cdk_config()
    env = cdk.Environment(account="123456789012", region="us-east-1")
    app = cdk.App()
    suffix = "" if with_critical_topic else "NoCrit"
    network = NetworkStack(app, f"TestNetworkStack{suffix}", config=config, env=env)
    storage = StorageStack(app, f"TestStorageStack{suffix}", config=config, env=env)
    cognito = CognitoStack(app, f"TestCognitoStack{suffix}", config=config, env=env)
    compute = ComputeStack(
        app, f"TestComputeStack{suffix}", config=config, network_stack=network,
        storage_stack=storage, cognito_stack=cognito, env=env,
    )
    canary = CanaryStack(
        app, f"TestCanaryStack{suffix}",
        config=config,
        vpc=network.vpc,
        cluster=compute.ecs_cluster,
        # execution_role omitted → canary-local exec role (avoids the cross-stack
        # log-group-grant cyclic reference; see CanaryStack rationale).
        api_gw_url="https://api.example.invalid/prod",
        critical_alerts_topic_arn=(
            "arn:aws:sns:us-east-1:123456789012:sentra-mvp-critical-alerts"
            if with_critical_topic else None
        ),
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
    """Ji.4 / J8.5 — a sentra-canary Fargate task def (512/1024) with CANARY_TARGET=live,
    SENTRA_CONSOLE_URL (the J8 console lane), and a task role scoped to the SEC-4 actions.
    J8 adds a read-only apigateway:GET (gateway reconciliation) — still NO product-table
    write, still no _platform."""
    t = _canary_template()
    t.has_resource_properties("AWS::ECS::TaskDefinition", {
        "Family": "sentra-canary",
        "Cpu": "512",
        "Memory": "1024",
    })
    # The container carries CANARY_TARGET=live + the J8 console URL.
    t.has_resource_properties("AWS::ECS::TaskDefinition", {
        "ContainerDefinitions": Match.array_with([
            Match.object_like({
                "Environment": Match.array_with([
                    {"Name": "CANARY_TARGET", "Value": "live"},
                    {"Name": "SENTRA_CONSOLE_URL", "Value": "https://console.aegionai.ai"},
                ]),
            }),
        ]),
    })
    policies = t.find_resources("AWS::IAM::Policy")
    all_actions = []
    for p in policies.values():
        for stmt in p["Properties"]["PolicyDocument"]["Statement"]:
            act = stmt.get("Action")
            all_actions.extend(act if isinstance(act, list) else [act])
    # J8.5: apigateway:GET is now PRESENT (read-only gateway reconciliation), but still
    # NO write verb (POST/PUT/DELETE/PATCH) on apigateway and NO product-table write.
    assert any("apigateway:GET" == a for a in all_actions), \
        "J8 needs apigateway:GET for the gateway reconciliation"
    assert not any(
        isinstance(a, str) and a.lower().startswith("apigateway:")
        and a.split(":", 1)[1] not in ("GET",)
        for a in all_actions
    ), "canary apigateway grant must be GET-only (read), never a write verb"
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
    """Ji.6 / Jr.3 — ChecksFailed>=1 fires on a REAL failure (NOT_BREACHING: the metric
    posts once/hour, so BREACHING would re-fire on the gap between runs — a false ALARM
    observed in prod 2026-07-05) + overlap alarm exists."""
    t = _canary_template()
    # The failure alarm watches a SHORT 5-min (300s) window, NOT_BREACHING, so a one-off
    # failure self-clears in ~5-10 min instead of a stale datapoint locking a 1h window.
    t.has_resource_properties("AWS::CloudWatch::Alarm", {
        "MetricName": "ChecksFailed",
        "Namespace": "Sentra/Canary",
        "TreatMissingData": "notBreaching",
        "Period": 300,
    })
    t.has_resource_properties("AWS::CloudWatch::Alarm", {
        "MetricName": "CanarySkippedOverlap",
        "EvaluationPeriods": 2,
    })


def test_canary_heartbeat_alarm_catches_no_run():
    """The 'did-it-run' monitor-the-monitor signal (separated from ChecksFailed): watch
    ChecksExpected (emitted by EVERY real run) with BREACHING missing-data over 2/2
    periods, so two consecutive missed hourly fires page. This is the correct home for
    the no-run concern the old ChecksFailed=BREACHING alarm mis-handled — a single-metric
    LESS_THAN alarm that fires when the canary stops emitting."""
    t = _canary_template()
    t.has_resource_properties("AWS::CloudWatch::Alarm", {
        "MetricName": "ChecksExpected",
        "Namespace": "Sentra/Canary",
        "ComparisonOperator": "LessThanThreshold",
        "TreatMissingData": "breaching",
        "EvaluationPeriods": 2,
        "DatapointsToAlarm": 2,
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
        # 5-min window so a transient/one-off product 5xx self-clears in ~5-10 min
        # instead of holding the critical alarm for a full hour (prod 2026-07-05).
        "Period": 300,
    })


def test_alarm_metric_names_are_all_in_the_emitter_contract():
    """The stack's ALARM_METRIC_NAMES contract lists exactly the metrics the alarms
    watch — the join anchor the seam test uses to prove every one is emitted."""
    from stacks.canary_stack import ALARM_METRIC_NAMES

    assert ALARM_METRIC_NAMES == frozenset({
        "ChecksFailed", "ChecksPassed", "InfraErrors", "ChecksExpected",
        "CanarySkippedOverlap", "ProductFivexxFail",
    })


def test_product_5xx_alarm_exists_even_without_critical_topic():
    """FINDING 2 (fail-secure) — entrypoint emits ProductFivexxFail EVERY run, so the
    alarm must exist REGARDLESS of the critical topic. A CanaryStack stood up WITHOUT
    the shared critical topic must STILL alarm on product 5xx (routed to the dedicated
    canary topic as a fallback), never silently drop the escalation. This asserts the
    topic-ABSENT branch (which app.py doesn't hit today, so had ZERO coverage)."""
    t = _canary_template(with_critical_topic=False)
    # The alarm exists in the topic-absent instantiation ...
    t.has_resource_properties("AWS::CloudWatch::Alarm", {
        "MetricName": "ProductFivexxFail",
        "Namespace": "Sentra/Canary",
    })
    # ... and its action falls back to the dedicated sentra-canary-alerts topic (a
    # Ref to the local topic construct, not a missing/empty action).
    alarms = t.find_resources("AWS::CloudWatch::Alarm")
    p5xx = [
        a for a in alarms.values()
        if a["Properties"].get("MetricName") == "ProductFivexxFail"
    ]
    assert len(p5xx) == 1, "exactly one ProductFivexxFail alarm must exist"
    actions = p5xx[0]["Properties"].get("AlarmActions") or []
    assert actions, "ProductFivexxFail alarm must have a fallback SNS action, not none"
    # The fallback is a Ref to the local canary-alerts topic (not the imported crit ARN).
    assert any(isinstance(a, dict) and "Ref" in a for a in actions), \
        "topic-absent ProductFivexxFail must action the local sentra-canary-alerts topic"


def test_product_5xx_alarm_still_escalates_to_critical_topic_when_present():
    """FINDING 2 companion — with the critical topic present the ProductFivexxFail
    alarm escalates THERE (the prod path, SEC-8), keeping the existing behavior green
    after the unconditional-creation refactor."""
    t = _canary_template(with_critical_topic=True)
    alarms = t.find_resources("AWS::CloudWatch::Alarm")
    p5xx = [
        a for a in alarms.values()
        if a["Properties"].get("MetricName") == "ProductFivexxFail"
    ]
    assert len(p5xx) == 1
    actions = p5xx[0]["Properties"].get("AlarmActions") or []
    assert "arn:aws:sns:us-east-1:123456789012:sentra-mvp-critical-alerts" in actions, \
        "with the critical topic present, product-5xx must page the critical audience"


def test_every_synthesized_alarm_metric_is_in_the_constant_and_emitted():
    """FINDING 3 — join REAL synthesized alarms ↔ the ALARM_METRIC_NAMES constant ↔ the
    entrypoint emitter. Every AWS::CloudWatch::Alarm's watched metric name MUST be in
    ALARM_METRIC_NAMES AND be one entrypoint actually emits (emit_run_metrics +
    guard_at_most_one). Closes the dead-alarm gap: a new alarm on a metric outside the
    constant / never emitted would fail HERE, where nothing joined them before."""
    from stacks.canary_stack import ALARM_METRIC_NAMES

    # The metric names entrypoint.emit_run_metrics emits (derived from its MetricData)
    # ∪ the CanarySkippedOverlap that guard_at_most_one emits. Kept as an explicit
    # literal so a change to what the entrypoint emits must be reflected here too.
    emitted_names = {
        "ChecksPassed", "ChecksFailed", "InfraErrors", "ChecksExpected",
        "ProductFivexxFail",         # emit_run_metrics
        "CanarySkippedOverlap",      # guard_at_most_one
    }

    t = _canary_template()
    alarms = t.find_resources("AWS::CloudWatch::Alarm")
    assert alarms, "the canary stack must synthesize at least one alarm"

    # Alarms carry the watched metric either as a top-level MetricName (simple metric)
    # or inside Metrics[] (MathExpression alarms — shortfall). Collect BOTH, keeping only
    # the Sentra/Canary source metrics (math sub-metrics carry their own MetricName).
    alarmed_metrics: set = set()
    for a in alarms.values():
        props = a["Properties"]
        if "MetricName" in props:
            alarmed_metrics.add(props["MetricName"])
        for m in props.get("Metrics", []) or []:
            stat = m.get("MetricStat")
            if stat and stat.get("Metric", {}).get("Namespace") == "Sentra/Canary":
                mn = stat["Metric"].get("MetricName")
                if mn:
                    alarmed_metrics.add(mn)

    # Every metric a real alarm watches is declared in the constant ...
    not_in_constant = alarmed_metrics - ALARM_METRIC_NAMES
    assert not not_in_constant, (
        f"alarms watch metric(s) missing from ALARM_METRIC_NAMES: {sorted(not_in_constant)}"
    )
    # ... and is one the entrypoint actually emits (no dead alarm on a never-produced metric).
    not_emitted = alarmed_metrics - emitted_names
    assert not not_emitted, (
        f"alarms watch metric(s) the entrypoint never emits (dead alarms): "
        f"{sorted(not_emitted)}"
    )


def test_canary_ecr_repo_created():
    """Ji.2 — the StorageStack synthesizes an ECR repo sentra/canary (the 8th image)."""
    os.environ["ENV"] = "dev"
    config = _load_cdk_config()
    env = cdk.Environment(account="123456789012", region="us-east-1")
    app = cdk.App()
    storage = StorageStack(app, "TestStorageStackEcr", config=config, env=env)
    t = Template.from_stack(storage)
    t.has_resource_properties("AWS::ECR::Repository", {"RepositoryName": "sentra/canary"})
