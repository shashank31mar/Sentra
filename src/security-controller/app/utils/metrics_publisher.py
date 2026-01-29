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
            
            self.cloudwatch.put_metric_data(
                Namespace=self.namespace,
                MetricData=metrics
            )
            
            logger.debug(f"Published validation metrics for {agent_id}: {decision}")
            
        except Exception as e:
            logger.exception(f"Failed to publish validation metrics (non-blocking): {e}")
            # Don't raise - metrics publishing should not block validation
    
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
