"""
Health Service - Health Check Business Logic

Handles dependency verification for DynamoDB, S3, and CloudWatch.
Keeps routes.py clean and focused on HTTP handling.
"""
import logging
from typing import Dict, List

import boto3
from botocore.exceptions import ClientError

from app.config import settings
from app.utils.helpers import get_uptime_seconds

logger = logging.getLogger(__name__)

# Constants
AWS_SERVICE_DYNAMODB = 'dynamodb'
AWS_SERVICE_S3 = 's3'
AWS_SERVICE_LOGS = 'logs'


class HealthService:
    """
    Handles health check logic and dependency verification.
    
    Checks:
    - DynamoDB tables (session-context, policies)
    - S3 bucket (artifacts)
    - CloudWatch Logs
    """
    
    def __init__(self):
        self.region = settings.aws_region
        self.cloudwatch = boto3.client('cloudwatch', region_name=self.region)
    
    async def check_health(self) -> Dict:
        """
        Perform health check on all dependencies.
        
        MVP: Returns 200 OK even if dependencies are unhealthy (for ALB health checks).
        The response body indicates actual health status.
        
        Returns:
            Dict with status, dependencies, and errors (if any)
        """
        dependencies = {}
        errors = []
        
        # Check DynamoDB (critical)
        dynamodb_healthy = await self._check_dynamodb(dependencies, errors)
        
        # Check S3 (non-critical for MVP - used only for Sigma rules caching)
        s3_healthy = await self._check_s3(dependencies, errors)
        
        # Check CloudWatch Logs (non-critical - logs can be buffered)
        cloudwatch_healthy = await self._check_cloudwatch(dependencies, errors)
        
        # Determine overall health (only DynamoDB is critical for startup)
        all_healthy = dynamodb_healthy  # S3 and CloudWatch are non-critical
        
        response = {
            "status": "healthy" if all_healthy else "degraded",
            "timestamp": None,  # Will be set by FastAPI
            "version": "1.0.0",
            "dependencies": dependencies,
            "uptime_seconds": get_uptime_seconds()
        }
        
        if not all_healthy:
            response["errors"] = errors
            logger.warning("Health check degraded", extra={"errors": errors})
        
        # Publish health check status metric (Task 14)
        # 0 = healthy, 1 = unhealthy
        await self._publish_health_metric(0 if all_healthy else 1)
        
        # Return actual health status for proper load balancer behavior
        # If DynamoDB is down, the service cannot function properly
        return response, all_healthy
    
    async def _check_dynamodb(
        self,
        dependencies: Dict,
        errors: List[str]
    ) -> bool:
        """
        Check DynamoDB connectivity and table availability.
        
        Checks 6 tables:
        - sentra-session-context (legacy)
        - sentra-policies (legacy)
        - sentra-agent-registry (Data Model v2)
        - sentra-tool-registry (Data Model v2)
        - sentra-policies-metadata (Data Model v2)
        - sentra-sigma-rules-metadata (Data Model v2)
        
        Returns:
            True if healthy, False otherwise
        """
        try:
            dynamodb = boto3.client(AWS_SERVICE_DYNAMODB, region_name=self.region)
            
            # Check session table
            session_healthy = await self._check_dynamodb_table(
                dynamodb,
                settings.dynamodb_session_table,
                "dynamodb_session_table",
                dependencies,
                errors
            )

            # Check Data Model v2 tables (Workstream 6)
            agent_registry_healthy = await self._check_dynamodb_table(
                dynamodb,
                settings.dynamodb_agent_registry_table,
                "dynamodb_agent_registry_table",
                dependencies,
                errors
            )
            
            tool_registry_healthy = await self._check_dynamodb_table(
                dynamodb,
                settings.dynamodb_tool_registry_table,
                "dynamodb_tool_registry_table",
                dependencies,
                errors
            )
            
            policies_metadata_healthy = await self._check_dynamodb_table(
                dynamodb,
                settings.dynamodb_policies_metadata_table,
                "dynamodb_policies_metadata_table",
                dependencies,
                errors
            )
            
            sigma_rules_metadata_healthy = await self._check_dynamodb_table(
                dynamodb,
                settings.dynamodb_sigma_rules_metadata_table,
                "dynamodb_sigma_rules_metadata_table",
                dependencies,
                errors
            )
            
            # Return True only if ALL tables are healthy
            return (
                session_healthy and
                agent_registry_healthy and
                tool_registry_healthy and
                policies_metadata_healthy and
                sigma_rules_metadata_healthy
            )
            
        except Exception as e:
            dependencies["dynamodb"] = "unhealthy"
            error_msg = f"DynamoDB connection error: {str(e)}"
            errors.append(error_msg)
            logger.error(f"DynamoDB connection failed: {e}", exc_info=True)
            return False
    
    async def _check_dynamodb_table(
        self,
        dynamodb_client,
        table_name: str,
        dependency_key: str,
        dependencies: Dict,
        errors: List[str]
    ) -> bool:
        """
        Check if a specific DynamoDB table exists and is accessible.
        
        Returns:
            True if healthy, False otherwise
        """
        try:
            dynamodb_client.describe_table(TableName=table_name)
            dependencies[dependency_key] = "healthy"
            return True
        except ClientError as e:
            dependencies[dependency_key] = "unhealthy"
            error_msg = f"DynamoDB table '{table_name}' error: {str(e)}"
            errors.append(error_msg)
            logger.error(f"DynamoDB table check failed for {table_name}: {e}", exc_info=True)
            return False
    
    async def _check_s3(
        self,
        dependencies: Dict,
        errors: List[str]
    ) -> bool:
        """
        Check S3 bucket connectivity and accessibility.
        
        Returns:
            True if healthy, False otherwise
        """
        try:
            s3 = boto3.client(AWS_SERVICE_S3, region_name=self.region)
            s3.head_bucket(Bucket=settings.s3_bucket)
            dependencies["s3"] = "healthy"
            return True
        except ClientError as e:
            dependencies["s3"] = "unhealthy"
            error_msg = f"S3 bucket error: {str(e)}"
            errors.append(error_msg)
            logger.error(f"S3 bucket check failed: {e}", exc_info=True)
            return False
        except Exception as e:
            dependencies["s3"] = "unhealthy"
            error_msg = f"S3 connection error: {str(e)}"
            errors.append(error_msg)
            logger.error(f"S3 connection failed: {e}", exc_info=True)
            return False
    
    async def _check_cloudwatch(
        self,
        dependencies: Dict,
        errors: List[str]
    ) -> bool:
        """
        Check CloudWatch Logs connectivity.
        
        Returns:
            True if healthy, False otherwise
        """
        try:
            logs = boto3.client(AWS_SERVICE_LOGS, region_name=self.region)
            
            # Try to describe log group
            try:
                logs.describe_log_groups(
                    logGroupNamePrefix=settings.cloudwatch_log_group
                )
                dependencies["cloudwatch"] = "healthy"
                return True
            except ClientError as e:
                if e.response['Error']['Code'] == 'ResourceNotFoundException':
                    # Log group doesn't exist yet - this is OK for initial setup
                    dependencies["cloudwatch"] = "healthy"
                    logger.warning(
                        f"CloudWatch log group not found (will be created): "
                        f"{settings.cloudwatch_log_group}"
                    )
                    return True
                else:
                    dependencies["cloudwatch"] = "unhealthy"
                    error_msg = f"CloudWatch Logs error: {str(e)}"
                    errors.append(error_msg)
                    logger.error(f"CloudWatch Logs check failed: {e}", exc_info=True)
                    return False
        except Exception as e:
            dependencies["cloudwatch"] = "unhealthy"
            error_msg = f"CloudWatch connection error: {str(e)}"
            errors.append(error_msg)
            logger.error(f"CloudWatch connection failed: {e}", exc_info=True)
            return False
    
    async def _publish_health_metric(self, status: int):
        """
        Publish health check status metric to CloudWatch.
        
        Args:
            status: 0 = healthy, 1 = unhealthy
        
        Note: Fire-and-forget. Metrics failures don't block health checks.
        """
        try:
            self.cloudwatch.put_metric_data(
                Namespace="Sentra/SecurityController",
                MetricData=[
                    {
                        'MetricName': 'HealthCheckStatus',
                        'Value': status,
                        'Unit': 'None'
                    }
                ]
            )
            logger.debug(f"Published health check metric: {status}")
        except Exception as e:
            logger.exception(f"Failed to publish health check metric (non-blocking): {e}")
