"""Reusable CDK construct for the `distilled-classifier` model-serving Fargate service.

Runs the request-phase tier-1 front-runner student model (FR-3.12) as its OWN warm,
always-on ECS Fargate service — a peer to `security-controller`, NOT co-located on it.
The serving stack (torch + a ~465MB multilingual sentence-embedder + the LogisticRegression
head) is ~1.3GB; the controller is deliberately stdlib-lean (~92MB). Isolating the model
keeps the PDP light and lets the model fleet scale independently. This mirrors the
`phi_ner_service_construct.py` sidecar pattern exactly.

The controller's `DistilledClassifier` client reaches this service at
`distilled-classifier.sentra.internal:8080` (CloudMap, in-VPC only, no public ALB) and
POSTs {tool_name, operation_type, user_input} → {decision, confidence}. A confident-DENY
short-circuits Haiku (block); a confident-ALLOW short-circuits only when the controller's
`distilled_allow_shortcircuit_enabled` gate is on (gated until shadow-proven). Any error /
timeout / unreachable service → the client escalates to Haiku (fail-secure), so a
service outage NEVER fails open — it just reverts to the pre-front-runner behavior.

Warm pool (min_capacity >= 1) is non-negotiable: a lazy per-request model load would put
a cold ~465MB embedder load on the <100ms path. Verified by `cdk synth` + assertions —
NO deploy, NO image push in the construct.
"""

from aws_cdk import (
    Duration,
    aws_ecs as ecs,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_logs as logs,
    aws_servicediscovery as servicediscovery,
)
from constructs import Construct


class DistilledClassifierServiceConstruct(Construct):
    """The `distilled-classifier` warm Fargate model-serving service (FR-3.12).

    Attributes:
        task_definition: the `ecs.FargateTaskDefinition` (2 vCPU / 4 GB).
        service: the `ecs.FargateService` (warm pool, CloudMap, circuit-breaker).
        scalable_task_count: the autoscaling target (`min_capacity >= 1`).
    """

    # CloudMap registers `<name>.<namespace>` — with `sentra.internal` this yields
    # `distilled-classifier.sentra.internal`, the DNS the controller client resolves
    # (settings.distilled_service_url). One spelling, shared by client + tests.
    SERVICE_NAME = "distilled-classifier"
    CONTAINER_PORT = 8080

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cluster: ecs.ICluster,
        task_role: iam.IRole,
        execution_role: iam.IRole,
        security_group: ec2.ISecurityGroup,
        service_discovery_namespace: servicediscovery.INamespace,
        image: ecs.ContainerImage,
        log_group: logs.ILogGroup,
        cpu: int = 2048,
        memory_limit_mib: int = 4096,
        desired_count: int = 1,
        min_capacity: int = 1,
        max_capacity: int = 4,
        cpu_target_utilization: int = 60,
    ) -> None:
        """Provision the distilled-classifier task definition + warm Fargate service.

        Args mirror PhiNerServiceConstruct. `task_role` needs no data-write IAM (the
        service only classifies text and returns a verdict; it persists nothing).

        Raises:
            ValueError: if `min_capacity < 1` or `desired_count < 1` — a cold pool is a
                hard misconfiguration for a model-serving service (the ~465MB embedder
                load would land on the request path); fail-fast at synth.
        """
        super().__init__(scope, construct_id)

        if min_capacity < 1:
            raise ValueError(
                "distilled-classifier min_capacity must be >= 1 (warm pool); "
                "min_capacity=0 is the cold-model-load footgun."
            )
        if desired_count < 1:
            raise ValueError(
                "distilled-classifier desired_count must be >= 1 (warm pool); a cold "
                "service puts a ~465MB embedder load on the <100ms request path."
            )

        self.task_definition = ecs.FargateTaskDefinition(
            self,
            "DistilledTaskDef",
            cpu=cpu,
            memory_limit_mib=memory_limit_mib,
            task_role=task_role,
            execution_role=execution_role,
            family=f"sentra-{self.SERVICE_NAME}",
        )

        self.task_definition.add_container(
            "DistilledContainer",
            container_name=self.SERVICE_NAME,
            image=image,
            logging=ecs.LogDriver.aws_logs(
                stream_prefix=self.SERVICE_NAME,
                log_group=log_group,
            ),
            environment={
                "SERVICE_NAME": self.SERVICE_NAME,
                # Quiet the transformers/tokenizers noise; never verbose (could echo
                # the classified text). HF offline — the model is baked into the image.
                "TRANSFORMERS_VERBOSITY": "error",
                "TRANSFORMERS_NO_ADVISORY_WARNINGS": "1",
                "TOKENIZERS_PARALLELISM": "false",
                "HF_HUB_OFFLINE": "1",
                # Eager-load the model at boot — NEVER lazy-per-request (cold-start
                # footgun the warm pool exists to prevent).
                "DISTILLED_MODEL_EAGER_LOAD": "1",
                "DISTILLED_MODEL_DIR": "/models/distilled",
            },
            port_mappings=[
                ecs.PortMapping(
                    container_port=self.CONTAINER_PORT,
                    protocol=ecs.Protocol.TCP,
                )
            ],
            health_check=ecs.HealthCheck(
                command=[
                    "CMD-SHELL",
                    f"curl -f http://localhost:{self.CONTAINER_PORT}/health || exit 1",
                ],
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                retries=3,
                # Generous grace for the ~465MB embedder load at boot (warm/always-on
                # so the load is a startup cost, not a per-request one).
                start_period=Duration.seconds(180),
            ),
        )

        self.service = ecs.FargateService(
            self,
            "DistilledService",
            service_name=f"sentra-{self.SERVICE_NAME}",
            cluster=cluster,
            task_definition=self.task_definition,
            desired_count=desired_count,
            min_healthy_percent=50,
            max_healthy_percent=200,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
            ),
            security_groups=[security_group],
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            health_check_grace_period=Duration.seconds(180),
            enable_execute_command=True,
            cloud_map_options=ecs.CloudMapOptions(
                # DNS: distilled-classifier.sentra.internal
                name=self.SERVICE_NAME,
                cloud_map_namespace=service_discovery_namespace,
                dns_record_type=servicediscovery.DnsRecordType.A,
                dns_ttl=Duration.seconds(10),
                container=self.task_definition.default_container,
                container_port=self.CONTAINER_PORT,
            ),
        )

        self.scalable_task_count = self.service.auto_scale_task_count(
            min_capacity=min_capacity,
            max_capacity=max_capacity,
        )
        self.scalable_task_count.scale_on_cpu_utilization(
            "DistilledCpuScaling",
            target_utilization_percent=cpu_target_utilization,
            scale_in_cooldown=Duration.seconds(120),
            scale_out_cooldown=Duration.seconds(60),
        )

    @property
    def service_name(self) -> str:
        return self.service.service_name
