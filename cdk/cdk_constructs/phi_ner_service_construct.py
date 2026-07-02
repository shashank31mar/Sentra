"""Reusable CDK construct for the `phi-ner` model-serving Fargate service (WS-E / E2.2).

Runs the Tier-2 server-side free-text PHI redactor (LLD 29 §4) as its OWN warm,
always-on ECS Fargate service — a peer to `security-controller`, NOT co-located on
it. This is where raw free-text PHI actually lives, transiently (§4.1 / §9.6), so
the service is deliberately isolated and its lifecycle is separate from the
controller's.

Follows the `security-controller` Fargate pattern exactly
([compute_stack.py:1651](../stacks/compute_stack.py) — `ecs.FargateTaskDefinition`
2 vCPU / 4 GB — and [:1725](../stacks/compute_stack.py) — `ecs.FargateService`
with CloudMap + circuit-breaker), with the deltas E2.2 requires:

  * **Warm pool, never cold** (§9.3 Option A / task-doc FOOTGUN): `desired_count >= 1`
    AND `auto_scale_task_count(min_capacity >= 1)` with utilization-based scale-out.
    `min_capacity=0` is the cold-model-load footgun the warm pool exists to prevent
    — a lazy per-request model load would put a cold start on the <=900 ms path.
  * **CloudMap `phi-ner.sentra.internal`** — service-to-service only (no public ALB
    target); the controller reaches it inside the VPC over TLS. Private subnets only
    (`PRIVATE_WITH_EGRESS`); the controller SG is the allowed inbound peer.
  * **`circuit_breaker=DeploymentCircuitBreaker(rollback=True)`** + a generous
    health-check `start_period` (the model load at boot, not per request).
  * **Stateless fleet, F4 isolation (§9.6):** no per-tenant sticky routing; per-request
    raw buffers are zeroed in-process (the SERVED code enforces that — see
    `src/security-controller/app/redaction/phi_ner.py`); NER-framework input logging
    is OFF in prod (env below). The provable cross-tenant boundary (Nitro/CVM enclave,
    §4.5) is a NAMED DEFERRED RESIDUAL — this construct does NOT claim it present.
  * **No raw-egress task role (§9.6):** the task role passed in must have NO IAM
    permission to write raw anywhere and no egress to a third-party de-id API; its
    only write is the redacted view back to the controller. This construct does not
    attach any data-write policy of its own.

Verified by `cdk synth` + `aws_cdk.assertions.Template` unit assertions — NO deploy,
NO image push, NO live AWS (stage-3 acceptance, 00-index.md:34).
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


class PhiNerServiceConstruct(Construct):
    """The `phi-ner` warm Fargate model-serving service (LLD 29 §4 / §9.3 Option A).

    Attributes:
        task_definition: the `ecs.FargateTaskDefinition` (2 vCPU / 4 GB).
        service: the `ecs.FargateService` (warm pool, CloudMap, circuit-breaker).
        scalable_task_count: the autoscaling target (`min_capacity >= 1`).
    """

    # The service name + CloudMap DNS label the controller resolves. CloudMap
    # registers `<name>.<namespace>` — with namespace `sentra.internal` this yields
    # `phi-ner.sentra.internal` (E2.2 contract). Kept as a constant so the served
    # client and the tests key off one spelling.
    SERVICE_NAME = "phi-ner"
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
        """Provision the phi-ner task definition + warm Fargate service.

        Args:
            cluster: the shared ECS cluster (from ComputeStack).
            task_role: the phi-ner task role — MUST carry no raw-egress IAM (§9.6);
                this construct attaches no data-write policy of its own.
            execution_role: the shared ECS task execution role (ECR pull + logs).
            security_group: the phi-ner service SG; the controller SG must be
                allowed inbound (wired by the caller in the network stack).
            service_discovery_namespace: the `sentra.internal` private namespace
                (from NetworkStack) — yields `phi-ner.sentra.internal`.
            image: the container image (the `docker/Dockerfile.phi-ner` build).
            log_group: the phi-ner CloudWatch log group.
            cpu / memory_limit_mib: task sizing (2 vCPU / 4 GB, matches the
                controller sizing at compute_stack.py:1665).
            desired_count / min_capacity: warm-pool floor — BOTH >= 1. `min_capacity`
                of 0 is rejected (the cold-start footgun the warm pool prevents).
            max_capacity: autoscale ceiling.
            cpu_target_utilization: scale-out target CPU %.

        Raises:
            ValueError: if `min_capacity < 1` or `desired_count < 1` — a cold pool
                is a hard misconfiguration for a model-serving service (§9.3),
                fail-fast at synth rather than deploy a cold service.
        """
        super().__init__(scope, construct_id)

        # Warm pool is non-negotiable — reject a cold config at synth (fail-secure on
        # a footgun, not at deploy). The model load must never be lazy-per-request.
        if min_capacity < 1:
            raise ValueError(
                "phi-ner min_capacity must be >= 1 (warm pool); min_capacity=0 is the "
                "cold-model-load footgun (LLD 29 §9.3, task E2.2)."
            )
        if desired_count < 1:
            raise ValueError(
                "phi-ner desired_count must be >= 1 (warm pool); a cold service puts a "
                "model-load cold-start on the <=900 ms path (LLD 29 §9.3)."
            )

        # Task definition — 2 vCPU / 4 GB, mirrors compute_stack.py:1662 sizing.
        self.task_definition = ecs.FargateTaskDefinition(
            self,
            "PhiNerTaskDef",
            cpu=cpu,
            memory_limit_mib=memory_limit_mib,
            task_role=task_role,
            execution_role=execution_role,
            family=f"sentra-{self.SERVICE_NAME}",
        )

        self.task_definition.add_container(
            "PhiNerContainer",
            container_name=self.SERVICE_NAME,
            image=image,
            logging=ecs.LogDriver.aws_logs(
                stream_prefix=self.SERVICE_NAME,
                log_group=log_group,
            ),
            # F4 isolation (§9.6): NER-framework debug/verbose INPUT logging OFF in
            # prod — the framework must never log the raw free-text it processes.
            # The served app (phi_ner.py) reads these to keep spaCy / transformers /
            # ONNX-Runtime input logging disabled; asserted by the served-side test.
            environment={
                "SERVICE_NAME": self.SERVICE_NAME,
                "PHI_NER_INPUT_LOGGING": "off",
                "TRANSFORMERS_VERBOSITY": "error",
                "TRANSFORMERS_NO_ADVISORY_WARNINGS": "1",
                "TOKENIZERS_PARALLELISM": "false",
                # ONNX-Runtime log severity 3 = ERROR (2=WARNING, 0=VERBOSE) — never
                # verbose, which could echo tensor/input detail.
                "ORT_LOG_SEVERITY_LEVEL": "3",
                # Model artifact is baked-in / pulled at boot, NEVER lazy-per-request
                # (§4.1 FOOTGUN). The served app honors eager load at startup.
                "PHI_NER_MODEL_EAGER_LOAD": "1",
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
                # Generous grace for the model load at boot (§4.1: warm/always-on so
                # the load is a startup cost, not on the per-request path).
                start_period=Duration.seconds(300),
            ),
        )

        # Service — warm pool + CloudMap service-to-service discovery + circuit
        # breaker with rollback. No ALB target group: the controller reaches it at
        # `phi-ner.sentra.internal`, private subnets only (§4.1 / E2.2).
        self.service = ecs.FargateService(
            self,
            "PhiNerService",
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
            health_check_grace_period=Duration.seconds(300),
            enable_execute_command=True,
            cloud_map_options=ecs.CloudMapOptions(
                # DNS name: phi-ner.sentra.internal (E2.2 contract).
                name=self.SERVICE_NAME,
                cloud_map_namespace=service_discovery_namespace,
                dns_record_type=servicediscovery.DnsRecordType.A,
                dns_ttl=Duration.seconds(10),
                container=self.task_definition.default_container,
                container_port=self.CONTAINER_PORT,
            ),
        )

        # Warm-pool autoscale — min_capacity >= 1 (NEVER 0), scale OUT on CPU
        # utilization. This keeps at least one warm, model-resident task at all
        # times (§9.3 Option A) while absorbing free-text volume via utilization.
        self.scalable_task_count = self.service.auto_scale_task_count(
            min_capacity=min_capacity,
            max_capacity=max_capacity,
        )
        self.scalable_task_count.scale_on_cpu_utilization(
            "PhiNerCpuScaling",
            target_utilization_percent=cpu_target_utilization,
            scale_in_cooldown=Duration.seconds(120),
            scale_out_cooldown=Duration.seconds(60),
        )

    @property
    def service_name(self) -> str:
        return self.service.service_name
