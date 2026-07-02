"""CDK assertion tests for the phi-ner warm Fargate service construct (WS-E / E2.2).

Validates the §4/§9.3 Option-A service: a 2 vCPU/4 GB FargateTaskDefinition +
FargateService named `sentra-phi-ner`, CloudMap `phi-ner` (→ phi-ner.sentra.internal),
private subnets, a warm-pool autoscaling target with `min_capacity >= 1` (NEVER 0),
circuit-breaker rollback, and NER-framework input-logging OFF in the task env. The
construct is exercised in a minimal test stack that provides a real VPC / cluster /
namespace / SG (a NET-NEW peer construct, not yet wired into ComputeStack — that
wiring is the combined-deploy step, out of this synth-only stage).

Run from the cdk/ directory: ``python -m pytest tests/ -q``.
"""
import pytest
from aws_cdk import App, Environment, Stack
from aws_cdk import (
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_iam as iam,
    aws_logs as logs,
    aws_servicediscovery as servicediscovery,
)
from aws_cdk.assertions import Match, Template
from constructs import Construct

from cdk_constructs.phi_ner_service_construct import PhiNerServiceConstruct


class _PhiNerTestStack(Stack):
    def __init__(
        self,
        scope: Construct,
        cid: str,
        *,
        min_capacity: int = 1,
        desired_count: int = 1,
        **kwargs,
    ) -> None:
        super().__init__(scope, cid, **kwargs)
        vpc = ec2.Vpc(self, "Vpc", max_azs=2)
        cluster = ecs.Cluster(self, "Cluster", vpc=vpc)
        namespace = servicediscovery.PrivateDnsNamespace(
            self, "Ns", name="sentra.internal", vpc=vpc,
        )
        sg = ec2.SecurityGroup(self, "PhiNerSg", vpc=vpc)
        task_role = iam.Role(
            self, "TaskRole", assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
        )
        exec_role = iam.Role(
            self, "ExecRole", assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
        )
        log_group = logs.LogGroup(self, "Lg")
        self.task_role = task_role
        self.phi_ner = PhiNerServiceConstruct(
            self, "PhiNer",
            cluster=cluster,
            task_role=task_role,
            execution_role=exec_role,
            security_group=sg,
            service_discovery_namespace=namespace,
            image=ecs.ContainerImage.from_registry("sentra/phi-ner:latest"),
            log_group=log_group,
            min_capacity=min_capacity,
            desired_count=desired_count,
        )


def _template(min_capacity: int = 1, desired_count: int = 1) -> Template:
    app = App()
    stack = _PhiNerTestStack(
        app, "TestPhiNerStack", min_capacity=min_capacity, desired_count=desired_count,
        env=Environment(account="123456789012", region="us-east-1"),
    )
    return Template.from_stack(stack)


def test_task_definition_2vcpu_4gb():
    """E2.2: 2 vCPU (2048) / 4 GB (4096), mirroring the controller sizing."""
    _template().has_resource_properties(
        "AWS::ECS::TaskDefinition",
        {"Cpu": "2048", "Memory": "4096", "Family": "sentra-phi-ner"},
    )


def test_service_named_phi_ner_with_circuit_breaker():
    """E2.2: the service is `sentra-phi-ner` with circuit-breaker rollback enabled."""
    _template().has_resource_properties(
        "AWS::ECS::Service",
        {
            "ServiceName": "sentra-phi-ner",
            "DeploymentConfiguration": Match.object_like(
                {"DeploymentCircuitBreaker": {"Enable": True, "Rollback": True}}
            ),
        },
    )


def test_cloudmap_service_discovery_name():
    """E2.2: CloudMap registers the `phi-ner` label → phi-ner.sentra.internal."""
    _template().has_resource_properties(
        "AWS::ServiceDiscovery::Service", {"Name": "phi-ner"},
    )


def test_service_in_private_subnets():
    """E2.2: the service runs with assignPublicIp DISABLED — private subnets only
    (PRIVATE_WITH_EGRESS); no public exposure of the raw-PHI-processing service."""
    services = _template().find_resources("AWS::ECS::Service")
    assert services, "no ECS service synthesized"
    for props in services.values():
        net = props["Properties"].get("NetworkConfiguration", {}).get("AwsvpcConfiguration", {})
        assert net.get("AssignPublicIp") == "DISABLED"


def test_warm_pool_min_capacity_at_least_one():
    """E2.2 FOOTGUN: the autoscaling target MinCapacity is >= 1 (warm pool). A cold
    pool (0) is what puts a model-load cold-start on the <=900 ms path."""
    template = _template()
    targets = template.find_resources("AWS::ApplicationAutoScaling::ScalableTarget")
    assert targets, "no autoscaling target — warm pool not configured"
    for props in targets.values():
        assert int(props["Properties"]["MinCapacity"]) >= 1, "warm-pool min_capacity must be >= 1"


def test_cpu_utilization_scaling_policy():
    """E2.2: scale-out is on CPU UTILIZATION (a TargetTrackingScaling policy), not a
    fixed count — utilization autoscale per §9.3 Option A."""
    _template().has_resource_properties(
        "AWS::ApplicationAutoScaling::ScalingPolicy",
        {
            "PolicyType": "TargetTrackingScaling",
            "TargetTrackingScalingPolicyConfiguration": Match.object_like(
                {"PredefinedMetricSpecification": {"PredefinedMetricType": "ECSServiceAverageCPUUtilization"}}
            ),
        },
    )


def test_ner_framework_input_logging_off_in_task_env():
    """E2.4 / §9.6: the task container env pins NER-framework INPUT logging OFF —
    the transient invariant is meaningless if the framework logs the input."""
    tds = _template().find_resources("AWS::ECS::TaskDefinition")
    assert tds, "no task definition"
    for props in tds.values():
        containers = props["Properties"]["ContainerDefinitions"]
        phi = [c for c in containers if c.get("Name") == "phi-ner"]
        assert phi, "phi-ner container not found in task def"
        env = {e["Name"]: e["Value"] for e in phi[0].get("Environment", [])}
        assert env.get("PHI_NER_INPUT_LOGGING") == "off"
        # ONNX-Runtime log severity 3 = ERROR — never verbose (which could echo input).
        assert env.get("ORT_LOG_SEVERITY_LEVEL") == "3"
        assert env.get("TRANSFORMERS_VERBOSITY") == "error"


def test_no_target_group_attachment():
    """E2.2: service-to-service ONLY (CloudMap) — no ALB target group. The raw-PHI
    service is never a public/ALB target."""
    services = _template().find_resources("AWS::ECS::Service")
    for props in services.values():
        assert not props["Properties"].get("LoadBalancers"), (
            "phi-ner must not attach to a load balancer (CloudMap-only, §4.1)"
        )


def test_min_capacity_zero_rejected_at_synth():
    """E2.2 FOOTGUN, fail-fast: min_capacity=0 (the cold-pool footgun) raises at
    synth — a cold model-serving service must never be deployable by accident."""
    with pytest.raises(ValueError, match="warm pool"):
        _template(min_capacity=0)


def test_desired_count_zero_rejected_at_synth():
    """E2.2 FOOTGUN, fail-fast: desired_count=0 (a cold warm-pool floor) raises at
    synth too — sibling to the min_capacity guard. A regression dropping ONLY the
    desired_count check would let a cold desired_count=0 service synth clean and put
    a model-load cold-start on the <=900 ms path."""
    with pytest.raises(ValueError, match="warm pool"):
        _template(desired_count=0)


# --- F4 / §9.6: the task role carries NO raw-egress IAM ---------------------
#
# The whole reason phi-ner is an isolated service is that raw PHI lives here
# transiently and MUST NOT be writable anywhere off the account. The construct's
# contract is that it attaches NO data-write/egress policy of its own; the only IAM
# on the task role is the ECS-Exec / logging baseline CDK adds for
# `enable_execute_command=True`. These tests make that invariant a machine check,
# not just docstring prose — a caller (or a future construct edit) that grants the
# task role a raw-egress action (S3/DynamoDB write, a managed de-id API, Firehose,
# an SNS/SQS/Kinesis publish, etc.) fails synth-assertion here.

# Actions that would let the raw-PHI service exfiltrate/persist raw off the account
# or push it to a third-party (subprocessor) de-id API — none may appear on the
# phi-ner task role (§9.6 / task E2.4).
_FORBIDDEN_TASK_ROLE_ACTION_PREFIXES = (
    "s3:put", "s3:*",
    "dynamodb:put", "dynamodb:update", "dynamodb:batchwrite", "dynamodb:*",
    "comprehend",            # comprehend / comprehendmedical managed de-id API
    "firehose:", "kinesis:",
    "sns:publish", "sqs:sendmessage",
    "bedrock:", "sagemaker:invoke",
    "lambda:invoke",
    "secretsmanager:", "kms:decrypt",
)


def _task_role_logical_id(template: Template) -> str:
    """Resolve the phi-ner task role's logical id (CDK hashes the `TaskRole`
    construct id — don't hardcode the hash suffix). The exec role is excluded so we
    assert against the TASK role specifically."""
    role_ids = [
        rid
        for rid in template.find_resources("AWS::IAM::Role")
        if rid.startswith("TaskRole")
    ]
    assert len(role_ids) == 1, f"expected exactly one task role, got {role_ids}"
    return role_ids[0]


def _task_role_statements(template: Template) -> list:
    """Collect every IAM policy statement attached to the phi-ner task role."""
    role_logical_id = _task_role_logical_id(template)
    statements = []
    for props in template.find_resources("AWS::IAM::Policy").values():
        roles = props["Properties"].get("Roles", [])
        attached_to_task_role = any(
            isinstance(r, dict) and r.get("Ref") == role_logical_id for r in roles
        )
        if not attached_to_task_role:
            continue
        statements.extend(props["Properties"]["PolicyDocument"]["Statement"])
    return statements


def test_task_role_has_no_raw_egress_iam():
    """F4 / §9.6: the phi-ner task role grants NO raw-egress / data-write action.

    The only IAM the construct tolerates on the task role is the ECS-Exec/logging
    baseline (`ssmmessages:*`, `logs:*`) that `enable_execute_command=True` adds —
    NEVER an S3/DynamoDB write, a managed de-id API, or any publish/exfil action.
    A regression that attaches a data-write policy to the raw-PHI service's role
    (silently defeating the 'no raw egress' invariant the whole isolated service
    exists to hold) fails here."""
    statements = _task_role_statements(_template())
    for stmt in statements:
        if stmt.get("Effect") != "Allow":
            continue
        actions = stmt.get("Action", [])
        if isinstance(actions, str):
            actions = [actions]
        for action in actions:
            low = action.lower()
            assert not any(
                low.startswith(p) for p in _FORBIDDEN_TASK_ROLE_ACTION_PREFIXES
            ), (
                f"phi-ner task role grants raw-egress action {action!r} — the "
                "isolated raw-PHI service must have NO data-write/egress IAM (§9.6)"
            )


def test_task_role_only_ecs_exec_and_logging_baseline():
    """F4 / §9.6 (positive tie-down): every action on the task role is in the
    allowed ECS-Exec / logging baseline. This pins the invariant from the OTHER
    side — not just 'no known-bad action' but 'only the expected baseline' — so an
    unforeseen egress action (outside the denylist above) is still caught."""
    allowed_prefixes = ("ssmmessages:", "logs:")
    statements = _task_role_statements(_template())
    for stmt in statements:
        if stmt.get("Effect") != "Allow":
            continue
        actions = stmt.get("Action", [])
        if isinstance(actions, str):
            actions = [actions]
        for action in actions:
            assert action.lower().startswith(allowed_prefixes), (
                f"unexpected action {action!r} on the phi-ner task role — only the "
                "ECS-Exec/logging baseline is allowed (no data-write/egress, §9.6)"
            )
