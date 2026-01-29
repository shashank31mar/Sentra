"""
Policy Service - Policy Management Business Logic

Queries policies with filters and enriches with match statistics.

Data Sources:
- DynamoDB: sentra-policies-metadata (metadata)
- S3: Full policy YAML content
- CloudWatch Logs: Match counts (via audit logs)

Requirements: LLD 05 Section 3.4
Task 10: CloudWatch Metrics and Alarms
Workstream 11: Policy CRUD Operations
"""
import logging
import time
from typing import Dict, List, Optional

import boto3
import yaml
from botocore.exceptions import ClientError

from app.config import settings
from app.utils.cache_manager import get_cache_manager
from app.exceptions import (
    ValidationException,
    NotFoundException,
    ConflictException,
    ForbiddenException,
)

logger = logging.getLogger(__name__)


class PolicyServiceError(Exception):
    """Raised when policy service operations fail"""
    pass


class PolicyService:
    """
    Handles policy queries and metadata aggregation.
    
    Provides:
    - Query policies with filters (agent_id, status)
    - Enrich with match counts from audit logs
    - Cache results for performance
    
    Metrics (Task 10):
    - AgentManagementAPI/GetPolicies/Count
    - AgentManagementAPI/GetPolicies/Latency
    - AgentManagementAPI/CacheHitRate
    """
    
    def __init__(self):
        self.region = settings.aws_region
        self.dynamodb = boto3.resource('dynamodb', region_name=self.region)
        self.s3_client = boto3.client('s3', region_name=self.region)
        self.logs_client = boto3.client('logs', region_name=self.region)
        self.cloudwatch = boto3.client('cloudwatch', region_name=self.region)
        
        # Tables
        self.policies_metadata_table = self.dynamodb.Table(settings.dynamodb_policies_metadata_table)
        
        # Cache manager
        self.cache = get_cache_manager()
        self.cache_ttl = settings.policy_cache_ttl_seconds
        
        # Metrics namespace
        self.metrics_namespace = "AgentManagementAPI"
    
    async def query_policies(
        self,
        agent_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50
    ) -> Dict:
        """
        Query policies from DynamoDB metadata table with filters.
        
        Args:
            agent_id: Filter by agent ID (optional)
            status: Filter by status (active/inactive/deprecated) (optional)
            limit: Max results (default: 50, max: 200)
            
        Returns:
            Dictionary with policies array, total, and has_more flag
        """
        start_time = time.time()
        cache_hit = False
        
        try:
            # Build cache key
            cache_key = f"policies:agent={agent_id}:status={status}:limit={limit}"
            cached_data = self.cache.get(cache_key)
            if cached_data:
                logger.debug(f"Returning cached policies for {cache_key}")
                cache_hit = True
                self._publish_metrics("GetPolicies", time.time() - start_time, cache_hit)
                return cached_data
            
            # Cap limit
            limit = min(limit, 200)
            
            # Query DynamoDB based on filters
            policies = []
            
            if agent_id:
                # Use agent-index GSI
                logger.info(f"Querying policies for agent: {agent_id}")
                response = self.policies_metadata_table.query(
                    IndexName='agent-index',
                    KeyConditionExpression='agent_id = :agent_id',
                    ExpressionAttributeValues={':agent_id': agent_id},
                    Limit=limit
                )
                policies = response.get('Items', [])
                
            elif status:
                # Use status-index GSI
                logger.info(f"Querying policies with status: {status}")
                response = self.policies_metadata_table.query(
                    IndexName='status-index',
                    KeyConditionExpression='#status = :status',
                    ExpressionAttributeNames={'#status': 'status'},
                    ExpressionAttributeValues={':status': status},
                    Limit=limit
                )
                policies = response.get('Items', [])
                
            else:
                # Scan all policies (no filters)
                logger.info("Scanning all policies")
                response = self.policies_metadata_table.scan(Limit=limit)
                policies = response.get('Items', [])
            
            # Apply additional filters if both agent_id and status provided
            if agent_id and status:
                policies = [p for p in policies if p.get('status') == status]
            
            # Enrich with match counts from audit logs
            # Note: For MVP, we'll return 0 for match counts
            # Full implementation would query CloudWatch Logs Insights
            for policy in policies:
                policy['match_count_24h'] = 0  # TODO: Implement CloudWatch query
            
            result = {
                "policies": policies[:limit],
                "total": len(policies),
                "has_more": len(policies) > limit
            }
            
            # Cache result
            self.cache.set(cache_key, result, ttl=self.cache_ttl)
            
            # Publish metrics
            self._publish_metrics("GetPolicies", time.time() - start_time, cache_hit)
            
            return result
            
        except Exception as e:
            logger.exception("Error querying policies")
            # Return empty array on error (fail-safe for Dashboard)
            return {"policies": [], "total": 0, "has_more": False, "error": str(e)}
    
    async def get_policy(self, policy_id: str) -> Optional[Dict]:
        """
        Get specific policy by ID (metadata only).
        
        Args:
            policy_id: Policy identifier
            
        Returns:
            Policy metadata dict, or None if not found
        """
        try:
            # Check cache first
            cache_key = f"policy:{policy_id}"
            cached_data = self.cache.get(cache_key)
            if cached_data:
                logger.debug(f"Returning cached policy {policy_id}")
                return cached_data
            
            # Get from DynamoDB
            logger.info(f"Loading policy {policy_id} from DynamoDB")
            response = self.policies_metadata_table.get_item(Key={'policy_id': policy_id})
            
            if 'Item' not in response:
                logger.warning(f"Policy {policy_id} not found")
                return None
            
            policy = response['Item']
            
            # Enrich with match count
            policy['match_count_24h'] = 0  # TODO: Implement CloudWatch query
            
            # Cache result
            self.cache.set(cache_key, policy, ttl=self.cache_ttl)
            
            return policy
            
        except Exception as e:
            logger.exception(f"Error getting policy {policy_id}")
            return None
    
    async def get_policy_content(self, policy_id: str) -> Optional[Dict]:
        """
        Get full policy content from S3 (includes YAML content).
        
        Args:
            policy_id: Policy identifier
            
        Returns:
            Full policy dict with content, or None if not found
        """
        try:
            # First get metadata
            metadata = await self.get_policy(policy_id)
            if not metadata:
                return None
            
            # Get S3 references
            s3_bucket = metadata.get('s3_bucket')
            s3_key = metadata.get('s3_key')
            
            if not s3_bucket or not s3_key:
                logger.warning(f"Policy {policy_id} missing S3 reference")
                return metadata  # Return metadata only
            
            # Download full content from S3
            logger.info(f"Loading policy content from S3: {s3_key}")
            policy_obj = self.s3_client.get_object(Bucket=s3_bucket, Key=s3_key)
            policy_content = policy_obj['Body'].read().decode('utf-8')
            
            # Parse YAML
            policy_data = yaml.safe_load(policy_content)
            
            # Merge metadata with content
            policy_data['metadata'] = metadata
            
            return policy_data
            
        except Exception as e:
            logger.exception(f"Error getting policy content for {policy_id}")
            return None
    
    async def _get_policy_match_counts(self) -> Dict[str, int]:
        """
        Get policy match counts from CloudWatch Logs (last 24h).
        
        Returns:
            Dict mapping policy_id to match count
        """
        # TODO: Implement CloudWatch Logs Insights query
        # For MVP, return empty dict
        return {}
    
    def _publish_metrics(self, operation: str, latency_ms: float, cache_hit: bool):
        """
        Publish CloudWatch metrics for Policy Service operations.
        
        Args:
            operation: Operation name (GetPolicies, GetPolicy)
            latency_ms: Operation latency in milliseconds
            cache_hit: Whether cache was hit
        
        Note: Fire-and-forget. Metrics failures don't block operations.
        """
        try:
            metrics = [
                {
                    'MetricName': f'{operation}/Count',
                    'Value': 1,
                    'Unit': 'Count'
                },
                {
                    'MetricName': f'{operation}/Latency',
                    'Value': latency_ms * 1000,  # Convert to milliseconds
                    'Unit': 'Milliseconds'
                },
                {
                    'MetricName': 'CacheHitRate',
                    'Value': 1 if cache_hit else 0,
                    'Unit': 'None',
                    'Dimensions': [
                        {'Name': 'Operation', 'Value': operation}
                    ]
                }
            ]
            
            self.cloudwatch.put_metric_data(
                Namespace=self.metrics_namespace,
                MetricData=metrics
            )
            
            logger.debug(f"Published metrics for {operation}: latency={latency_ms:.2f}ms, cache_hit={cache_hit}")
            
        except Exception as e:
            logger.warning(f"Failed to publish metrics for {operation} (non-blocking): {e}")

    # ============================================================
    # CRUD Operations (LLD 07)
    # ============================================================

    async def create_policy(
        self,
        policy_data: Dict,
        operator_email: str
    ) -> Dict:
        """
        Create new policy with hybrid storage (DynamoDB + S3).

        Args:
            policy_data: Policy document dict
            operator_email: Operator creating the policy

        Returns:
            Dict with success, policy_id, version, s3_key, etc.

        Raises:
            ValidationException, ConflictException
        """
        from app.services.policy_validator import PolicyValidator
        from app.utils.s3_policy_store import S3PolicyStore
        from app.utils.metrics_publisher import MetricsPublisher
        import hashlib
        from datetime import datetime
        import time

        start_time = time.time()
        agent_id = policy_data.get('agent_id')
        metrics_publisher = MetricsPublisher()

        try:
            # 1. Validate
            validator = PolicyValidator()
            is_valid, errors = validator.validate_policy(policy_data)
            if not is_valid:
                logger.warning(f"Policy validation failed: {errors}")
                await metrics_publisher.publish_policy_validation_metric('SCHEMA_ERROR', len(errors))
                raise ValidationException(errors)

            # 2. Check if policy already exists
            policy_id = f"agent-config-{policy_data['agent_id']}"
            existing = await self.get_policy(policy_id)
            if existing:
                await metrics_publisher.publish_policy_crud_metric('CREATE_POLICY', False, agent_id)
                raise ConflictException(f"Policy {policy_id} already exists", existing.get('version'))

            # 3. Generate content hash
            yaml_content = yaml.dump(policy_data, sort_keys=False)
            content_hash = f"sha256:{hashlib.sha256(yaml_content.encode()).hexdigest()}"

            # 4. Upload to S3
            s3_store = S3PolicyStore()
            version = policy_data['version']
            s3_key = f"policies/agents/{policy_data['agent_id']}/v{version}.yaml"
            s3_version_id = await s3_store.upload(
                key=s3_key,
                content=yaml_content,
                metadata={'policy_id': policy_id, 'version': version}
            )

            # 5. Store metadata in DynamoDB
            now = datetime.utcnow().isoformat() + 'Z'
            metadata_item = {
                'policy_id': policy_id,
                'agent_id': policy_data['agent_id'],
                'name': policy_data['name'],
                'version': version,
                'status': 'active',
                's3_bucket': 'sentra-mvp-artifacts',
                's3_key': s3_key,
                's3_version_id': s3_version_id,
                'allowed_tools_count': len(policy_data['allowed_tools']),
                'policies_count': len(policy_data['policies']),
                'severity_breakdown': self._calculate_severity_breakdown(policy_data['policies']),
                'content_hash': content_hash,
                'schema_version': policy_data.get('schema_version', 'v1'),
                'created_at': now,
                'updated_at': now,
                'created_by': operator_email,
                'last_updated_by': operator_email
            }

            self.policies_metadata_table.put_item(Item=metadata_item)

            # 6. Audit log
            self._log_audit('CREATE_POLICY', policy_id, operator_email, {'version': version, 's3_key': s3_key})

            # Clear cache
            self.cache.clear()

            logger.info(f"Created policy {policy_id} version {version}")

            # Publish success metrics
            latency_ms = (time.time() - start_time) * 1000
            await metrics_publisher.publish_policy_crud_metric('CREATE_POLICY', True, agent_id, latency_ms)

            return {
                'success': True,
                'policy_id': policy_id,
                'version': version,
                's3_key': s3_key,
                's3_version_id': s3_version_id,
                'content_hash': content_hash,
                'created_at': now,
                'message': 'Policy created successfully'
            }

        except (ValidationException, ConflictException):
            # Already handled metrics above
            raise
        except Exception as e:
            # Publish failure metric for unexpected errors
            latency_ms = (time.time() - start_time) * 1000
            await metrics_publisher.publish_policy_crud_metric('CREATE_POLICY', False, agent_id, latency_ms)
            raise

    async def update_policy(
        self,
        policy_id: str,
        policy_data: Dict,
        operator_email: str
    ) -> Dict:
        """
        Update existing policy (creates new S3 version).

        Args:
            policy_id: Policy identifier
            policy_data: Updated policy document
            operator_email: Operator updating the policy

        Returns:
            Dict with success, policy_id, version, previous_version, etc.

        Raises:
            NotFoundException, ForbiddenException, ValidationException
        """
        from app.services.policy_validator import PolicyValidator
        from app.utils.s3_policy_store import S3PolicyStore
        import hashlib
        from datetime import datetime

        # 1. Check policy exists
        existing = await self.get_policy(policy_id)
        if not existing:
            raise NotFoundException(f"Policy {policy_id} not found")

        # 2. Check not disabled
        if existing.get('status') == 'disabled':
            raise ForbiddenException("Cannot update disabled policy. Enable it first.")

        # 3. Merge with existing metadata for validation
        # User provides content fields, we add system metadata
        policy_data_with_metadata = {
            **policy_data,
            'policy_id': policy_id,
            'status': existing.get('status', 'active'),
            'created_at': existing.get('created_at'),
            'created_by': existing.get('created_by')
        }

        # 4. Validate
        validator = PolicyValidator()
        is_valid, errors = validator.validate_policy(policy_data_with_metadata)
        if not is_valid:
            raise ValidationException(errors)

        # 4. Auto-increment version if not provided
        new_version = policy_data.get('version', self._increment_version(existing['version']))

        # 5. Generate content hash
        yaml_content = yaml.dump(policy_data, sort_keys=False)
        content_hash = f"sha256:{hashlib.sha256(yaml_content.encode()).hexdigest()}"

        # 6. Upload to S3 (use existing bucket from metadata)
        bucket_name = existing.get('s3_bucket', 'sentra-mvp-artifacts')
        s3_store = S3PolicyStore(bucket_name=bucket_name)
        s3_key = f"policies/agents/{policy_data['agent_id']}/v{new_version}.yaml"
        s3_version_id = await s3_store.upload(
            key=s3_key,
            content=yaml_content,
            metadata={'policy_id': policy_id, 'version': new_version}
        )

        # 7. Update metadata
        now = datetime.utcnow().isoformat() + 'Z'
        self.policies_metadata_table.update_item(
            Key={'policy_id': policy_id},
            UpdateExpression="""
                SET version = :version,
                    s3_key = :s3_key,
                    s3_version_id = :s3_version_id,
                    content_hash = :content_hash,
                    allowed_tools_count = :tools_count,
                    policies_count = :policies_count,
                    severity_breakdown = :severity,
                    updated_at = :updated_at,
                    last_updated_by = :updated_by
            """,
            ExpressionAttributeValues={
                ':version': new_version,
                ':s3_key': s3_key,
                ':s3_version_id': s3_version_id,
                ':content_hash': content_hash,
                ':tools_count': len(policy_data['allowed_tools']),
                ':policies_count': len(policy_data['policies']),
                ':severity': self._calculate_severity_breakdown(policy_data['policies']),
                ':updated_at': now,
                ':updated_by': operator_email
            }
        )

        # 8. Audit log
        self._log_audit('UPDATE_POLICY', policy_id, operator_email, {
            'previous_version': existing['version'],
            'new_version': new_version,
            's3_key': s3_key
        })

        # Clear cache
        self.cache.clear()

        logger.info(f"Updated policy {policy_id} from {existing['version']} to {new_version}")

        return {
            'success': True,
            'policy_id': policy_id,
            'version': new_version,
            'previous_version': existing['version'],
            's3_key': s3_key,
            's3_version_id': s3_version_id,
            'content_hash': content_hash,
            'updated_at': now,
            'message': 'Policy updated successfully'
        }

    async def delete_policy(
        self,
        policy_id: str,
        operator_email: str
    ) -> Dict:
        """
        Soft delete policy (set status=disabled).

        Args:
            policy_id: Policy identifier
            operator_email: Operator deleting the policy

        Returns:
            Dict with success, policy_id, status, disabled_at

        Raises:
            NotFoundException, ForbiddenException
        """
        from datetime import datetime

        # 1. Check policy exists
        existing = await self.get_policy(policy_id)
        if not existing:
            raise NotFoundException(f"Policy {policy_id} not found")

        # 2. Check not system policy
        if existing.get('created_by') == 'system':
            raise ForbiddenException("Cannot delete system policies")

        # 3. Soft delete (idempotent)
        now = datetime.utcnow().isoformat() + 'Z'
        self.policies_metadata_table.update_item(
            Key={'policy_id': policy_id},
            UpdateExpression="SET #status = :disabled, updated_at = :now, last_updated_by = :operator",
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={
                ':disabled': 'disabled',
                ':now': now,
                ':operator': operator_email
            }
        )

        # 4. Audit log
        self._log_audit('DELETE_POLICY', policy_id, operator_email, {'disabled_at': now})

        # Clear cache
        self.cache.clear()

        logger.info(f"Disabled policy {policy_id}")

        return {
            'success': True,
            'policy_id': policy_id,
            'status': 'disabled',
            'disabled_at': now,
            'message': 'Policy disabled successfully'
        }

    def _calculate_severity_breakdown(self, policies: List[Dict]) -> Dict:
        """Calculate severity breakdown for metadata."""
        breakdown = {'critical': 0, 'high': 0, 'medium': 0, 'low': 0}
        for policy in policies:
            severity = policy.get('severity', 'medium')
            if severity in breakdown:
                breakdown[severity] += 1
        return breakdown

    def _increment_version(self, version: str) -> str:
        """Auto-increment patch version (1.0.0 → 1.0.1)."""
        parts = version.split('.')
        parts[2] = str(int(parts[2]) + 1)
        return '.'.join(parts)

    def _log_audit(self, operation: str, resource_id: str, operator_email: str, details: Dict):
        """Log mutation to audit trail."""
        import json
        from datetime import datetime
        audit_entry = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'operation': operation,
            'resource_id': resource_id,
            'operator_email': operator_email,
            'operator_source': 'dashboard',
            'details': details,
            'result': 'success'
        }
        logger.info(f"Audit: {json.dumps(audit_entry)}")
