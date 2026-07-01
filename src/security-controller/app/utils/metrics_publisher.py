"""
Metrics Publisher for Security Controller

Publishes custom metrics to CloudWatch for monitoring and alerting.
All metrics publishing is asynchronous (fire-and-forget) to avoid blocking validation.
"""
import logging
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from app.config import settings

logger = logging.getLogger(__name__)


class MetricsPublisher:
    """
    Publishes custom metrics to CloudWatch.
    
    Namespace: Sentra/SecurityController
    Metrics:
    - ValidationsTotal (counter)
    - ValidationLatency (histogram)
    - TrustScoreAverage (gauge)
    - DenyRate (gauge)
    - QuarantinedSessions (gauge)
    - SuspendedSessions (gauge)
    - ValidationErrors (counter)
    """
    
    def __init__(self):
        self.cloudwatch = boto3.client('cloudwatch', region_name=settings.aws_region)
        self.namespace = "Sentra/SecurityController"
    
    async def publish_validation_metrics(
        self,
        decision: str,
        latency_ms: float,
        agent_id: str,
        trust_score: float,
        threat_type: Optional[str] = None,
        severity: Optional[str] = None
    ):
        """
        Publish metrics after each validation.
        
        Args:
            decision: ALLOW or DENY
            latency_ms: Validation latency in milliseconds
            agent_id: Agent identifier
            trust_score: Current trust score
            threat_type: Type of threat detected (optional, for DENY)
            severity: Threat severity level (optional, for DENY)
        
        Note: Fire-and-forget. Metrics failures don't block validation.
        """
        try:
            metrics = [
                {
                    'MetricName': 'ValidationsTotal',
                    'Value': 1,
                    'Unit': 'Count',
                    'Dimensions': [
                        {'Name': 'AgentId', 'Value': agent_id},
                        {'Name': 'Decision', 'Value': decision}
                    ]
                },
                {
                    'MetricName': 'ValidationLatency',
                    'Value': latency_ms,
                    'Unit': 'Milliseconds',
                    'Dimensions': [
                        {'Name': 'AgentId', 'Value': agent_id}
                    ]
                },
                {
                    'MetricName': 'TrustScoreAverage',
                    'Value': trust_score,
                    'Unit': 'None',
                    'Dimensions': [
                        {'Name': 'AgentId', 'Value': agent_id}
                    ]
                }
            ]
            
            # Add deny rate metric for DENY decisions
            if decision == "DENY":
                deny_dimensions = [{'Name': 'AgentId', 'Value': agent_id}]

                # Add threat_type dimension if available
                if threat_type:
                    deny_dimensions.append({'Name': 'ThreatType', 'Value': threat_type})

                metrics.append({
                    'MetricName': 'DenyRate',
                    'Value': 1,
                    'Unit': 'None',
                    'Dimensions': deny_dimensions
                })

            # Tenant-dimensioned metrics (LLD-26 §9.1 / WS-E E1). Emitted ALONGSIDE
            # the AgentId-keyed streams above so existing dashboards keep working;
            # per-tenant dashboards become a `tenant_id` filter, not a new pipeline.
            # `tenant_id` is the request's resolved tenant (the `current_tenant()`
            # contextvar) — `default` until identity rollout, then the real tid.
            try:
                from app.utils import tenancy
                tid = tenancy.current_tenant()
                metrics.append({
                    'MetricName': 'Decisions',
                    'Value': 1,
                    'Unit': 'Count',
                    'Dimensions': [
                        {'Name': 'tenant_id', 'Value': tid},
                        {'Name': 'verdict', 'Value': decision},
                    ],
                })
                metrics.append({
                    'MetricName': 'ValidateLatency',
                    'Value': latency_ms,
                    'Unit': 'Milliseconds',
                    'Dimensions': [{'Name': 'tenant_id', 'Value': tid}],
                })
            except Exception:  # noqa: BLE001 — never let a metric tag block validation
                pass

            self.cloudwatch.put_metric_data(
                Namespace=self.namespace,
                MetricData=metrics
            )
            
            logger.debug(f"Published validation metrics for {agent_id}: {decision}")
            
        except Exception as e:
            logger.exception(f"Failed to publish validation metrics (non-blocking): {e}")
            # Don't raise - metrics publishing should not block validation
    
    async def publish_sigma_match_metric(self, rule_id: str):
        """
        Publish a Sigma rule match to CloudWatch.

        Emits one count per match under a per-rule ``RuleId`` dimension. This is
        the source of truth for the console's "Matches" column — the
        ``stats.match_count_*`` fields in the DynamoDB metadata table are dead
        (never incremented at runtime). CloudWatch gives us native time-windowing
        (1h/24h/7d/30d) without a decay job, and ``MetricsQueryService`` reads it
        back via GetMetricData.

        Args:
            rule_id: Sigma rule identifier (e.g., "sigma-llm-001"). Used as the
                RuleId dimension so each rule gets its own series.

        Note: Fire-and-forget. Metrics failures must never block validation.
        """
        try:
            self.cloudwatch.put_metric_data(
                Namespace=self.namespace,
                MetricData=[
                    {
                        'MetricName': 'SigmaRuleMatches',
                        'Value': 1,
                        'Unit': 'Count',
                        'Dimensions': [
                            {'Name': 'RuleId', 'Value': rule_id}
                        ]
                    }
                ]
            )
            logger.debug(f"Published Sigma match metric for rule {rule_id}")
        except Exception as e:
            logger.exception(f"Failed to publish Sigma match metric (non-blocking): {e}")
            # Don't raise - metrics publishing should not block validation

    async def publish_cedar_shadow_metric(self, agreed: bool, disagreement_kind: str = "none"):
        """Publish a Cedar shadow-mode comparison result (feature: cedar-policy CT07).

        One data point per shadowed request: ``CedarShadowDiscrepancy`` = 1 on a
        disagreement (else 0), plus a ``CedarShadowEvaluated`` count so the
        disagreement rate is computable. The ``Kind`` dimension records the shape
        of the disagreement (e.g. ``verdict``, ``violation_type``, ``cedar_error``)
        for triage at CT09.

        Note: Fire-and-forget. Shadow telemetry must never block the live path.
        """
        try:
            self.cloudwatch.put_metric_data(
                Namespace=self.namespace,
                MetricData=[
                    {
                        'MetricName': 'CedarShadowEvaluated',
                        'Value': 1,
                        'Unit': 'Count',
                    },
                    {
                        'MetricName': 'CedarShadowDiscrepancy',
                        'Value': 0 if agreed else 1,
                        'Unit': 'Count',
                        'Dimensions': [
                            {'Name': 'Kind', 'Value': disagreement_kind}
                        ]
                    },
                ]
            )
        except Exception as e:
            logger.exception(f"Failed to publish Cedar shadow metric (non-blocking): {e}")

    # ============================================================
    # WS-I (LLD 28 §5.6): Cedar local-floor / abstain operational metrics.
    # All fire-and-forget, OFF the response path — OPS/dashboard signals, NOT the
    # billing ledger (that is WS-H's durable pipeline). A publish failure here must
    # never block or change a verdict.
    # ============================================================

    async def publish_cedar_abstain_metric(self, denied: bool, agent_id: str, tenant_id: str = ""):
        """Cedar-abstain outcome under cutover (WS-I I2.3 / LLD 28 §4.3, §5.6).

        ``denied=True`` → ``CedarAbstainDenied`` (legacy retired: a missing .cedar
        co-artifact became a fail-secure DENY — a DEFECT worth alarming).
        ``denied=False`` → ``CedarAbstainFallback`` (rollout era: abstain fell back
        to the legacy engine, the expected transient state during the backfill).
        """
        metric = "CedarAbstainDenied" if denied else "CedarAbstainFallback"
        try:
            self.cloudwatch.put_metric_data(
                Namespace=self.namespace,
                MetricData=[{
                    'MetricName': metric,
                    'Value': 1,
                    'Unit': 'Count',
                    'Dimensions': [
                        {'Name': 'AgentId', 'Value': agent_id},
                        {'Name': 'tenant_id', 'Value': tenant_id or '_unknown'},
                    ],
                }],
            )
            logger.debug("Published %s metric for agent=%s", metric, agent_id)
        except Exception as e:  # noqa: BLE001 — metrics never block validate
            logger.warning("Failed to publish %s metric (non-blocking): %s", metric, e)

    async def publish_cedar_eval_latency(self, latency_ms: float, cache_hit: bool, tenant_id: str = ""):
        """Cedar compiled-policy evaluation latency (WS-I I5.2 / LLD 28 §5.6, §8).

        Tagged ``cache_hit=true|false``. An LRU hit evaluates in ~1–5 ms; a spike of
        ``cache_hit=false`` flags a cold or thrashing ``_compiled_cache``.
        """
        try:
            self.cloudwatch.put_metric_data(
                Namespace=self.namespace,
                MetricData=[{
                    'MetricName': 'CedarEvalLatencyMs',
                    'Value': latency_ms,
                    'Unit': 'Milliseconds',
                    'Dimensions': [
                        {'Name': 'tenant_id', 'Value': tenant_id or '_unknown'},
                        {'Name': 'cache_hit', 'Value': 'true' if cache_hit else 'false'},
                    ],
                }],
            )
        except Exception as e:  # noqa: BLE001 — metrics never block validate
            logger.warning("Failed to publish CedarEvalLatencyMs metric (non-blocking): %s", e)

    async def publish_edge_resolve_metric(self, escalated: bool, tenant_id: str = ""):
        """Edge bundle resolution outcome (WS-I I5.1 / LLD 28 §5.6).

        Every edge resolution increments ``EdgeResolveTotal``; the ones that could
        not be decided locally and fell through to the hosted PDP also increment
        ``EscalatedToHostedTotal``. The ratio is the local-floor hit rate.
        """
        try:
            metric_data = [{
                'MetricName': 'EdgeResolveTotal',
                'Value': 1,
                'Unit': 'Count',
                'Dimensions': [{'Name': 'tenant_id', 'Value': tenant_id or '_unknown'}],
            }]
            if escalated:
                metric_data.append({
                    'MetricName': 'EscalatedToHostedTotal',
                    'Value': 1,
                    'Unit': 'Count',
                    'Dimensions': [{'Name': 'tenant_id', 'Value': tenant_id or '_unknown'}],
                })
            self.cloudwatch.put_metric_data(Namespace=self.namespace, MetricData=metric_data)
        except Exception as e:  # noqa: BLE001 — metrics never block validate
            logger.warning("Failed to publish edge-resolve metric (non-blocking): %s", e)

    async def publish_bundle_stale_fail_closed_metric(self, tenant_id: str = ""):
        """Edge rejected a stale/expired signed bundle and failed CLOSED (WS-I I5.1
        / LLD 28 §5.6). Each occurrence is a fail-secure event worth alarming — the
        anti-rollback guard (nbf/iat) refused an out-of-date bundle."""
        try:
            self.cloudwatch.put_metric_data(
                Namespace=self.namespace,
                MetricData=[{
                    'MetricName': 'BundleStaleFailClosed',
                    'Value': 1,
                    'Unit': 'Count',
                    'Dimensions': [{'Name': 'tenant_id', 'Value': tenant_id or '_unknown'}],
                }],
            )
        except Exception as e:  # noqa: BLE001 — metrics never block validate
            logger.warning("Failed to publish BundleStaleFailClosed metric (non-blocking): %s", e)

    async def publish_session_metrics(self, quarantined_count: int, suspended_count: int):
        """
        Publish session status metrics.
        
        Args:
            quarantined_count: Number of quarantined sessions
            suspended_count: Number of suspended sessions
        
        Note: Fire-and-forget. Metrics failures don't block operations.
        """
        try:
            self.cloudwatch.put_metric_data(
                Namespace=self.namespace,
                MetricData=[
                    {
                        'MetricName': 'QuarantinedSessions',
                        'Value': quarantined_count,
                        'Unit': 'Count'
                    },
                    {
                        'MetricName': 'SuspendedSessions',
                        'Value': suspended_count,
                        'Unit': 'Count'
                    }
                ]
            )
            
            logger.debug(f"Published session metrics: quarantined={quarantined_count}, suspended={suspended_count}")
            
        except Exception as e:
            logger.exception(f"Failed to publish session metrics (non-blocking): {e}")
            # Don't raise - metrics publishing should not block operations
    
    async def publish_error_metric(self, error_type: str):
        """
        Publish validation error metric.
        
        Args:
            error_type: Type of error (e.g., DYNAMODB_ERROR, S3_ERROR)
        
        Note: Fire-and-forget. Metrics failures don't block operations.
        """
        try:
            self.cloudwatch.put_metric_data(
                Namespace=self.namespace,
                MetricData=[
                    {
                        'MetricName': 'ValidationErrors',
                        'Value': 1,
                        'Unit': 'Count',
                        'Dimensions': [
                            {'Name': 'ErrorType', 'Value': error_type}
                        ]
                    }
                ]
            )
            
            logger.debug(f"Published error metric: {error_type}")
            
        except Exception as e:
            logger.exception(f"Failed to publish error metric (non-blocking): {e}")
            # Don't raise - metrics publishing should not block operations

    async def publish_identity_fallback_metric(self, state: str, tenant_id: str):
        """Residual uncredentialed-agent legacy-fallback window (LLD-26 / WS-B B1).

        ``state`` ∈ {opened, active, expired}. ``opened``/``active`` should be
        ALARMED — they mean enforce is letting an uncredentialed agent ride the
        legacy path on borrowed time; ``expired`` means the window closed to a hard
        DENY. Fire-and-forget; never blocks validate.
        """
        try:
            self.cloudwatch.put_metric_data(
                Namespace=self.namespace,
                MetricData=[
                    {
                        'MetricName': 'IdentityFallback',
                        'Value': 1,
                        'Unit': 'Count',
                        'Dimensions': [
                            {'Name': 'State', 'Value': state},
                            {'Name': 'tenant_id', 'Value': tenant_id or '_unknown'},
                        ],
                    }
                ],
            )
            logger.debug("Published identity-fallback metric: %s tenant=%s", state, tenant_id)
        except Exception as e:  # noqa: BLE001 — metrics never block validate
            logger.warning("Failed to publish identity-fallback metric (non-blocking): %s", e)

    async def publish_quota_exceeded_metric(self, tenant_id: str):
        """Per-tenant commercial RPS quota denial (LLD-26 §9.3 / WS-E E2b).

        Emitted once each time a validate is DENIED for `QUOTA_EXCEEDED`. One
        dimension (`tenant_id`) so the `{prefix}-quota-exceeded` alarm can page on
        a tenant hitting its ceiling. Quota is a *commercial* guardrail, so this is
        a P1 (not a security-critical) signal. Fire-and-forget; never blocks
        validate.
        """
        try:
            self.cloudwatch.put_metric_data(
                Namespace=self.namespace,
                MetricData=[
                    {
                        'MetricName': 'QuotaExceeded',
                        'Value': 1,
                        'Unit': 'Count',
                        'Dimensions': [
                            {'Name': 'tenant_id', 'Value': tenant_id or '_unknown'},
                        ],
                    }
                ],
            )
            logger.debug("Published quota-exceeded metric: tenant=%s", tenant_id)
        except Exception as e:  # noqa: BLE001 — metrics never block validate
            logger.warning("Failed to publish quota-exceeded metric (non-blocking): %s", e)

    # ============================================================
    # Workstream 11: Policy CRUD Metrics
    # ============================================================

    async def publish_policy_crud_metric(
        self,
        operation: str,
        success: bool,
        agent_id: Optional[str] = None,
        latency_ms: Optional[float] = None
    ):
        """
        Publish policy CRUD operation metrics.

        Args:
            operation: CREATE_POLICY, UPDATE_POLICY, DELETE_POLICY, GET_POLICY
            success: Whether operation succeeded
            agent_id: Agent ID (optional, for dimensions)
            latency_ms: Operation latency in milliseconds (optional)

        Metrics Published:
            - PolicyCRUD/{operation}/Success
            - PolicyCRUD/{operation}/Failure
            - PolicyCRUD/{operation}/Latency (if provided)

        Reference: LLD 11 Section 7.1
        """
        try:
            metric_data = []

            # Success/Failure counter
            metric_name = f"PolicyCRUD/{operation}/{'Success' if success else 'Failure'}"
            dimensions = []
            if agent_id:
                dimensions.append({'Name': 'AgentId', 'Value': agent_id})

            metric_data.append({
                'MetricName': metric_name,
                'Value': 1,
                'Unit': 'Count',
                'Dimensions': dimensions
            })

            # Latency metric (if provided)
            if latency_ms is not None:
                metric_data.append({
                    'MetricName': f"PolicyCRUD/{operation}/Latency",
                    'Value': latency_ms,
                    'Unit': 'Milliseconds',
                    'Dimensions': dimensions
                })

            # Publish metrics
            self.cloudwatch.put_metric_data(
                Namespace=self.namespace,
                MetricData=metric_data
            )

            logger.debug(f"Published policy CRUD metric: {metric_name} (success={success})")

        except Exception as e:
            logger.exception(f"Failed to publish policy CRUD metric (non-blocking): {e}")
            # Don't raise - metrics publishing should not block operations

    async def publish_policy_validation_metric(
        self,
        validation_type: str,
        failure_count: int = 1
    ):
        """
        Publish policy validation failure metrics.

        Args:
            validation_type: Type of validation failure (e.g., SCHEMA_ERROR, AGENT_NOT_FOUND, TOOL_NOT_FOUND)
            failure_count: Number of failures (default: 1)

        Metrics Published:
            - PolicyCRUD/ValidationFailure

        Reference: LLD 11 Section 7.1
        """
        try:
            self.cloudwatch.put_metric_data(
                Namespace=self.namespace,
                MetricData=[
                    {
                        'MetricName': 'PolicyCRUD/ValidationFailure',
                        'Value': failure_count,
                        'Unit': 'Count',
                        'Dimensions': [
                            {'Name': 'ValidationType', 'Value': validation_type}
                        ]
                    }
                ]
            )

            logger.debug(f"Published policy validation failure metric: {validation_type}")

        except Exception as e:
            logger.exception(f"Failed to publish policy validation metric (non-blocking): {e}")
            # Don't raise - metrics publishing should not block operations
